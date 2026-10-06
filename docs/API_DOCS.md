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

---

## Firestore data

| Path | Who can read/write |
|---|---|
| `users/{uid}` | the owner (Strava fields are server-only) |
| `users/{uid}/private/*` | server only |
| `workouts/{id}` | the owner (`userId == uid`) |
| `oauthStates/{state}` | server only |

The planner queries `workouts` by `userId` and `date`. This needs the composite index in
`firestore.indexes.json`.
