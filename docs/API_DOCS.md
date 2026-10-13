# Athlethium API

Base URL: `https://europe-west2-athlethium-app.cloudfunctions.net/<function>`.
Against the emulators it is `http://127.0.0.1:5001/demo-athlethium/europe-west2/<function>`.

## Authentication

Every endpoint except `strava_callback` requires a Firebase ID token for the signed-in user:

```
Authorization: Bearer <Firebase ID token>
```

- The user is always taken from the token.
- Older clients may still send `userId` (or `uid`) in the body. It is accepted only if it matches
  the token; otherwise the response is `403`.
- All endpoints take `POST` with a JSON body, except `upload_workout_fit` (multipart) and
  `strava_callback` (`GET`, called by Strava).

### Errors

| Status | Body | When |
|---|---|---|
| 400 | `{"error": "...", "details"?: [...]}` | invalid input, invalid/incomplete profile |
| 401 | `{"error": "Authentication required"}` | missing or invalid ID token |
| 403 | `{"error": "..."}` | `userId` does not match the token |
| 404 | `{"error": "..."}` | profile or workout not found (or not owned by the user) |
| 405 | `{"error": "..."}` | wrong HTTP method |
| 413 | `{"error": "File too large (max 25 MB)"}` | FIT upload too large |
| 500 | `{"error": "Internal server error"}` | unexpected failure (details only in logs) |

---

## `update_user_profile`

Validates and saves the athlete's profile (used by the setup wizard and settings).

```json
{ "profile": { "weekly_hours": 8, "sports": ["cycling"], "...": "..." }, "isPartial": true }
```

The profile may also be sent as the top-level body. With `isPartial: true` only the given fields
are validated and merged.

Response: `{"message": "...", "userId": "<uid>", "wizardCompleted": true}`.
On validation errors the response is `400` with a `details` list.

`language` (optional) is the athlete's language for generated text: one of `en`, `es`, `fr`,
`de`, `it`, `ja`; any other value is a validation error. When omitted, the stored value is kept.

## `generate_training_session`

Plans training for the signed-in athlete, skipping days that already have a session.

| Field | Type | Default | Notes |
|---|---|---|---|
| `date` | `YYYY-MM-DD` | athlete's local today | first day to plan (uses the profile `timezone`) |
| `days` | integer 1–28 | 1 | number of days |

```json
{ "message": "Training generation complete", "userId": "<uid>",
  "generated_dates": ["2026-10-06"], "skipped_dates": [] }
```

Writes one document per session to `workouts`:
- the main session gets the ID `plan_<uid>_<date>`;
- the second session of a double day gets `plan_<uid>_<date>_pm` (with `slot: "pm"`).

Each document carries:
- `steps` with personal `target_range`s (W, bpm or pace);
- `coach_rationale`, `execution_tips`, `session_kind` and `week_type`.

Completed sessions are never overwritten.

## `complete_manual_workout`

```json
{ "workoutId": "plan_<uid>_2026-10-06", "actual_time_sec": 3600, "rpe": 6, "notes": "felt good" }
```

Body fields:
- `actual_time_sec`: 1–86400.
- `rpe`: optional, 1–10.
- `notes`: up to 2000 characters.

The workout must belong to the user. Re-completing replaces the previous load rather than
adding to it.

Response:

```json
{ "message": "...",
  "data": { "workoutId": "...", "actual_time": 3600, "actual_tss": 55.0, "status": "completed" } }
```

## `upload_workout_fit`

`multipart/form-data` with:
- `file`: a `.fit` file, max 25 MB;
- `workoutId`: optional.

Without a `workoutId`, the activity is matched to an uncompleted planned session on the same
local day. A session of the same sport is preferred, which matters on double days. If nothing
matches, a new "Recorded Activity" is created.

- **TSS:** computed from normalised power, or from heart rate when there is no power.
- **FTP:** a cycling FTP increase from the best 20 minutes is suggested.
- **Storage:** the raw file is stored privately at `users/{uid}/workouts/{id}.fit`; clients have
  no Storage access.

Response: `{"message": "...", "data": {"workout_id", "sport", "date", "actual_time", "actual_tss", "stats", "new_ftp"}}`.

## Strava

### `strava_auth_start`

```json
{ "returnUrl": "athlethium://settings" }
```

- `returnUrl` must use the app's scheme: `athlethium`, `exp` or `exps`.
- The response is `{"state", "authUrl", "returnUrl"}`. The app opens `authUrl` in an auth session.
- `state` is single-use and bound to the user.

### `strava_callback` (GET, called by Strava)

Exchanges the code using the `STRAVA_CLIENT_SECRET` secret. Tokens are stored in the server-only
document `users/{uid}/private/strava`.

It then redirects to `returnUrl` with one of:
- `?success=true`
- `?error=<code>`, where `<code>` is one of:
  - `access_denied`
  - `strava_timeout`
  - `strava_unreachable`
  - `strava_rate_limited`
  - `strava_auth_rejected`
  - `strava_unavailable`
  - `strava_bad_response`
  - `missing_code`

### `strava_disconnect`

Revokes the grant with Strava (best effort) and deletes the stored tokens.
Response: `{"message": "Strava disconnected", "data": {...}}`.

### `strava_webhook` (called by Strava)

The endpoint for Strava's push subscription. It takes no Firebase token.

- **`GET`:** the subscription handshake. When `hub.mode=subscribe` and `hub.verify_token` matches
  the `STRAVA_VERIFY_TOKEN` secret, it returns `{"hub.challenge": "<challenge>"}`. Otherwise it
  returns `403`.
- **`POST`:** an event such as `{"object_type": "activity" | "athlete", "aspect_type": "create" |
  "update" | "delete", "object_id", "owner_id", "subscription_id", "event_time", "updates"}`.
  - The event is validated (`400` if malformed) and queued as `stravaEvents/{type_id_aspect_owner_time}`.
  - The response is `200` straight away. Strava's retries land on the same document, so they
    are queued once.
  - When `STRAVA_SUBSCRIPTION_ID` is set, events for other subscriptions are acknowledged and
    dropped.

### `process_strava_event` (Firestore trigger on `stravaEvents/{id}`)

Handles each queued event for every account linked to the Strava athlete (`stravaAthleteId`).
Nothing in the event is trusted:

- **Activity created or updated:**
  - The activity is fetched from Strava with the athlete's token, refreshing the token if it
    expires within 5 minutes. It must belong to `owner_id`.
  - Supported types are rides, runs, swims, strength (no TSS) and yoga/pilates (no TSS). Other
    types are ignored.
  - TSS comes from measured power (vs FTP) or heart rate (vs threshold HR).
- **Which workout it lands on**, on the activity's local date and for the same sport:
  1. A session already logged by FIT upload or by ticking it off, with duration within 25%, is
     **linked**. A FIT upload keeps its own numbers; a ticked-off session takes Strava's.
  2. Otherwise the first open planned session (morning first) is **completed**.
  3. Otherwise a new completed workout `strava_{activityId}` is **imported**.
- **Counting:** each activity is linked through `stravaLinks/{uid}_{activityId}`. Retries and
  updates re-sync the same workout and apply only the TSS change, so nothing is counted twice.
- **Activity deleted:** acted on only if Strava returns 404 for it.
  - An imported workout is removed.
  - A completed planned session is reopened.
  - A FIT upload is just unlinked.
  - The activity's TSS is taken back off fitness.
- **Athlete revoked access** (`updates.authorized == "false"`): acted on only if Strava rejects the
  athlete's refresh token. The tokens are then deleted and `stravaConnected` is set to `false`.

The outcome is written to the event document's `status`:
- `completed_planned`, `imported`, `updated`, `linked`, `unchanged`;
- `removed`, `reopened`, `unlinked`, `disconnected`;
- `ignored:<reason>` or `failed:<strava error code>`.

Transient Strava errors are retried once.

---

## Firestore data

| Path | Who can read/write |
|---|---|
| `users/{uid}` | the owner (Strava fields are server-only) |
| `users/{uid}/private/*` | server only |
| `workouts/{id}` | the owner (`userId == uid`) |
| `oauthStates/{state}` | server only |
| `stravaEvents/{id}`, `stravaLinks/{id}` | server only |

### Language

`users/{uid}.language` (`en`, `es`, `fr`, `de`, `it` or `ja`; missing or unsupported = `en`)
sets the language of every text the backend writes for the athlete: a planned workout's `name`,
`description`, `coach_rationale`, `execution_tips` and step `name`/`notes` (exercise names and
cues included), and the names given to imported activities ("Recorded Activity", "Strava
activity") and logged strength sets. Text is generated when the session is planned or imported,
so changing the language affects new workouts only. Codes the app reads for logic (`sport`,
`session_kind`, `week_type`, step `type`, target units) never change. Messages live in
`functions/i18n/messages/<lang>.py`; a language without translations falls back to English.

The app changes the language from Settings. It then regenerates the athlete's upcoming unfinished
sessions, so they follow the new language straight away.

`users/{uid}.goal.bodyArea` (`core`, `upper`, `lower` or `all`) is the strength and mobility focus,
stored as a code so it works in any language. Older goals without it fall back to matching
English keywords in `goal.notes`.

The planner queries `workouts` by `userId` and `date`. This needs the composite index in
`firestore.indexes.json`.
