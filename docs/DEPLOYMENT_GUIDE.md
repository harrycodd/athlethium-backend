# Deploying Athlethium

Production project: `athlethium-app`, region `europe-west2`. Development and CI never touch it;
they use the `demo-athlethium` emulator project.

This release changes the API contract. Every endpoint now requires a Firebase ID token, and
Strava OAuth starts on the server. **Deploy the backend and ship the new app build together.**
Older app builds will get `401` responses from the functions.

## 0. Before you start

- The project must be on the Blaze plan (Cloud Functions requires it).
- `npx firebase login`, then run `npx firebase projects:list` and confirm that `athlethium-app` is listed.
- CI must be green on the commit you are deploying.

## 1. Secrets and configuration

```bash
# The Strava client secret (regenerated after the old one was exposed). Never commit it.
npx firebase functions:secrets:set STRAVA_CLIENT_SECRET --project athlethium-app

# A new random verify token for the Strava webhook handshake (the old one was exposed).
# Keep the value: step 4 needs it once to create the subscription.
openssl rand -hex 24
npx firebase functions:secrets:set STRAVA_VERIFY_TOKEN --project athlethium-app
```

- **Strava client ID:** `STRAVA_CLIENT_ID` defaults to the public client ID `157155`. Override it
  only if you use a different Strava app. Put the override in `functions/.env.athlethium-app`.
- **Strava redirect URI:** `STRAVA_REDIRECT_URI` defaults to
  `https://europe-west2-athlethium-app.cloudfunctions.net/strava_callback`.
- **Strava settings page:** set **Authorization Callback Domain** to
  `europe-west2-athlethium-app.cloudfunctions.net`.
- **Firestore location:** `process_strava_event` is a Firestore trigger. It must run in the
  database's region, which is set by `FIRESTORE_TRIGGER_REGION` in `functions/main.py`
  (default `europe-west2`).
  - Check the location in Firebase console → Firestore → the database's location.
  - If it is different, change `FIRESTORE_TRIGGER_REGION` before deploying. The deploy fails with
    a clear error if they don't match.

## 2. Deploy rules, indexes and functions together

```bash
npx firebase deploy --project athlethium-app \
  --only firestore:rules,firestore:indexes,storage,functions
```

- **Rules:**
  - `firestore.rules` lets each user read and write only their own documents.
  - The `private` subcollection and `oauthStates` are server-only.
  - `storage.rules` denies all client access.
- **Index:** `firestore.indexes.json` adds the `workouts (userId, date)` composite index. The
  planner needs it to read recent training history. Wait until the index shows **Enabled** in the
  console before relying on plan generation.
- **New functions:** `strava_auth_start`, `strava_disconnect`, `strava_webhook` and
  `process_strava_event` are created on first deploy.
- **First Firestore trigger:** if this is the project's first one, Firebase may ask to enable the
  Eventarc API and grant its service agent permissions. Accept, then re-run the deploy if asked.

## 3. One-off data migration (Strava tokens)

Older versions stored Strava tokens on the client-readable `users/{uid}` document. Move them to
the server-only `users/{uid}/private/strava` document.

Dry run first:

```bash
functions/venv/bin/python scripts/migrate_strava_tokens.py \
  --project athlethium-app --i-understand-this-is-production
```

Then apply:

```bash
functions/venv/bin/python scripts/migrate_strava_tokens.py \
  --project athlethium-app --i-understand-this-is-production --apply
```

The script needs Application Default Credentials (`gcloud auth application-default login`). It is
idempotent, so it is safe to re-run.

## 4. Ship the app

Build and release the matching app version from `harrycodd/fitness-app`, e.g.
`eas build --platform all --profile production`, then submit it.

`EXPO_PUBLIC_FUNCTIONS_BASE_URL` must be unset (or set to the production URL) for production builds.

## 4b. Subscribe to Strava activity events (once)

The webhook only receives events after a push subscription exists. Strava allows one per app.

```bash
export STRAVA_CLIENT_SECRET=...   # from https://www.strava.com/settings/api
export STRAVA_VERIFY_TOKEN=...     # the value you set in step 1
functions/venv/bin/python scripts/strava_webhook_subscription.py show
functions/venv/bin/python scripts/strava_webhook_subscription.py create
```

- **`create`:** Strava calls the deployed `strava_webhook` to check the verify token, and the
  command prints the subscription ID.
- **Old subscription:** if `show` lists one (from the old setup, pointing at a function that never
  existed), remove it first with `delete --id <id>`.
- **Optional hardening:** put `STRAVA_SUBSCRIPTION_ID=<id>` in `functions/.env.athlethium-app` and
  redeploy the functions. Events for any other subscription ID are then ignored.
- **Optional clean-up:** add a Firestore TTL policy on `stravaEvents.expireAt` so processed events
  are deleted after 30 days.

## 5. Verify

- Sign in on the new build.
  - Today's session appears.
  - `npx firebase functions:log --project athlethium-app` shows `generate_training_session` returning 200.
- Connect and disconnect Strava from Settings.
- With Strava connected, record (or upload) a short activity on Strava.
  - Within a minute it should complete that day's planned session of the same sport, or appear
    as a new completed session.
  - Each event's outcome is stored on its `stravaEvents/{id}` document (`status`), e.g.
    `completed_planned`, `imported` or `failed:<reason>`.
- Upload a FIT file and complete a session.
- Confirm that `curl -X POST https://europe-west2-athlethium-app.cloudfunctions.net/generate_training_session`
  returns `401`.

## 6. Hardening (recommended)

- In Google Cloud Console → APIs & Services → Credentials, restrict the Firebase Web API key:
  - restrict it to the Firebase APIs you use;
  - add app restrictions for the iOS bundle ID and Android package.
- Enable Firebase App Check for Firestore, Storage and Functions.
- The leaked Strava secret was removed from git history. Its old commit may still be reachable on
  GitHub by its SHA. Ask GitHub Support to purge cached views if that matters to you. The secret
  itself is already rotated.

## Rolling back

`npx firebase functions:list` shows the deployed versions. Redeploy a previous commit with the same
command as step 2.

Rolling back the functions alone will break new app builds that send tokens to Strava endpoints
that no longer exist. Roll back the app and the functions together.

## Logs

- `npx firebase functions:log --project athlethium-app`
- [Logs Explorer](https://console.cloud.google.com/logs/viewer?project=athlethium-app)
