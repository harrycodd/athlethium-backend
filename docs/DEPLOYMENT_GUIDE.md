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
```

- **Strava client ID:** `STRAVA_CLIENT_ID` defaults to the public client ID `157155`. Override it
  only if you use a different Strava app. Put the override in `functions/.env.athlethium-app`.
- **Strava redirect URI:** `STRAVA_REDIRECT_URI` defaults to
  `https://europe-west2-athlethium-app.cloudfunctions.net/strava_callback`.
- **Strava settings page:** set **Authorization Callback Domain** to
  `europe-west2-athlethium-app.cloudfunctions.net`.
- **Unused secrets:** the old `STRAVA_VERIFY_TOKEN` and webhook flow are not used by any deployed
  function.

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
- **New functions:** `strava_auth_start` and `strava_disconnect` are created on first deploy.

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

## 5. Verify

- Sign in on the new build.
  - Today's session appears.
  - `npx firebase functions:log --project athlethium-app` shows `generate_training_session` returning 200.
- Connect and disconnect Strava from Settings.
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
