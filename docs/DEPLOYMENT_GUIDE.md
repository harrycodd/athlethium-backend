# Athlethium Firebase Deployment Guide

This guide details how to deploy the Athlethium backend (Cloud Functions, Firestore rules, and storage) to Firebase.

---

## 📋 1. Prerequisites

### A. Upgrade to Firebase Blaze Plan
Google Cloud requires the project to be on the **Blaze (Pay-As-You-Go)** plan to enable Cloud Functions and Google Artifact Registry.

1. Open your [Firebase Console Usage & Billing Page](https://console.firebase.google.com/project/athlethium-app/usage/details).
2. Click **Upgrade Project** and select **Blaze Plan**.
3. *Note*: Firebase offers a generous free tier (2M Cloud Function invocations, 5GB storage, 50k Firestore daily reads/writes free every month).

### B. Verify Firebase Login & Project
Ensure you are logged in to the Firebase CLI and the active project is set to `athlethium-app`:

```bash
# Check logged-in user
npx -y firebase-tools@latest login

# Confirm active project
npx -y firebase-tools@latest use athlethium-app
```

---

## 🚀 2. Deploying to Firebase

### Deploy All Cloud Functions:
Run the following command from the `fitness-app-backend/` directory:

```bash
npx -y firebase-tools@latest deploy --only functions
```

### Deploy a Specific Cloud Function:
To deploy only a single endpoint (e.g. `generate_training_session`):

```bash
npx -y firebase-tools@latest deploy --only functions:generate_training_session
```

---

## 🔑 3. Setting Environment Secrets (Strava Integration)

If using Strava integration, set your secrets securely in Firebase Cloud Functions:

```bash
npx -y firebase-tools@latest functions:secrets:set STRAVA_CLIENT_ID
npx -y firebase-tools@latest functions:secrets:set STRAVA_CLIENT_SECRET
npx -y firebase-tools@latest functions:secrets:set STRAVA_VERIFY_TOKEN
```

---

## 💻 4. Running Local Emulators (Testing Before Deploying)

You can run the entire backend and Firestore database locally on your machine without deploying to cloud:

```bash
cd /Users/harry/fitness/fitness-app-backend
npx -y firebase-tools@latest emulators:start --only functions,firestore
```

* **Functions Emulator**: `http://127.0.0.1:5001/athlethium-app/europe-west2/...`
* **Emulator UI Suite**: `http://127.0.0.1:4000/`

---

## 📊 5. Monitoring & Debugging Logs

### Live Cloud Logs:
To stream real-time execution logs from your deployed Cloud Functions:

```bash
npx -y firebase-tools@latest functions:log
```

### Google Cloud Console Logs:
View structured logs in the [Google Cloud Logs Explorer](https://console.cloud.google.com/logs/viewer?project=athlethium-app).

---

## 🧪 6. Running the Local Test Harness

Before deploying changes, always verify the test suite:

```bash
cd /Users/harry/fitness/fitness-app-backend/functions
../venv/bin/python tests/run_tests.py
```
