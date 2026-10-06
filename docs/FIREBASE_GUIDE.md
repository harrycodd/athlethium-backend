# Firebase Cloud Functions Deployment & Development Guide

This guide provides step-by-step instructions for developing, testing, and deploying Firebase Cloud Functions (Python 2nd Gen) for the **Athlethium** (fitness app) backend.

---

## 📋 Prerequisites & Local Setup

To develop and deploy functions, you need the following tools configured on your system:

### 1. Python Environment
The backend functions run on **Python 3.14**.
- Verify your local Python version:
  ```bash
  python3 --version
  ```
- The cloud functions are located in the `functions/` directory of the backend:
  `[fitness-app-backend/functions](file:///Users/harry/fitness/fitness-app-backend/functions)`

### 2. Node.js & Firebase CLI
We use `npx` to run the latest version of `firebase-tools` without needing a global installation.
- Verify Node.js is installed:
  ```bash
  node -v
  ```

### 3. Authentication
Before running any Firebase commands, authenticate with the Firebase CLI:
```bash
npx -y firebase-tools@latest login
```
*If you are operating in a headless or remote server environment, run:*
```bash
npx -y firebase-tools@latest login --no-localhost
```

---

## 💻 Local Development & Testing

You can run your functions locally using the Firebase Emulator Suite. This allows you to test code changes in real-time without deploying to production.

### 1. Set Up Your Local Virtual Environment
If not already done, initialize and activate the Python virtual environment in the `functions/` folder:
```bash
cd fitness-app-backend/functions
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the Firebase Emulator
Run the emulator from the backend root directory (`fitness-app-backend`):
```bash
npx -y firebase-tools@latest emulators:start --only functions
```
- **Local URLs:** The terminal will output the local HTTP endpoints (e.g., `http://127.0.0.1:5001/fitness-app-8f3c4/europe-west2/...`).
- **Emulator UI:** View the local dashboard at [http://127.0.0.1:4000/](http://127.0.0.1:4000/).
- **Live Reload:** The emulator watches your `functions/` folder. Any changes to Python files are automatically reloaded!

---

## 🛠 Adding a New Cloud Function

To add a new function to the backend:

### 1. Define the Function in `main.py`
Open `[functions/main.py](file:///Users/harry/fitness/fitness-app-backend/functions/main.py)` and write your new function.

#### Option A: HTTP Request Function (on_request)
Best for webhook integration or direct HTTP access:
```python
from firebase_functions import https_fn

@https_fn.on_request(region="europe-west2", invoker="public")
def my_new_endpoint(req: https_fn.Request) -> https_fn.Response:
    # Get payload
    data = req.get_json() if req.is_json else {}
    
    # Process payload
    name = data.get("name", "World")
    
    return https_fn.Response(
        json.dumps({"message": f"Hello, {name}!"}),
        status=200,
        mimetype="application/json"
    )
```

#### Option B: Callable Function (on_call)
Best for calling directly from Firebase mobile/web clients (automatically handles auth propagation):
```python
from firebase_functions import https_fn

@https_fn.on_call(region="europe-west2")
def my_callable_function(req: https_fn.CallableRequest):
    # Ensure user is authenticated
    if not req.auth:
         raise https_fn.HttpsError(
             code=https_fn.FunctionsErrorCode.UNAUTHENTICATED,
             message="User must be logged in"
         )
         
    # Access auth details and payload data
    uid = req.auth.uid
    name = req.data.get("name", "User")
    
    return {"status": "success", "uid": uid, "greeting": f"Hello, {name}!"}
```

### 2. Update Dependencies
If your new function requires external libraries, add them to `[functions/requirements.txt](file:///Users/harry/fitness/fitness-app-backend/functions/requirements.txt)`:
```txt
firebase_functions~=0.5.0
firebase-admin>=6.0.0
fitparse
requests>=2.31.0
your-new-package>=1.0.0
```

---

## 🚀 Deploying to Production

When you are ready to deploy your changes to the live Firebase environment:

### 1. Ensure Active Project context
Confirm the active project is correct (should be `fitness-app-8f3c4`):
```bash
npx -y firebase-tools@latest use
```
If you need to switch or add a project:
```bash
npx -y firebase-tools@latest use fitness-app-8f3c4
```

### 2. Run the Deployment Command
Execute the deployment from the `fitness-app-backend` root:
```bash
npx -y firebase-tools@latest deploy --only functions
```

### 3. Deploying Specific Functions
If you only want to deploy a single function rather than all of them, use:
```bash
npx -y firebase-tools@latest deploy --only functions:complete_manual_workout
```

---

## 🔍 Troubleshooting & Monitoring

- **View Live Logs:**
  Monitor function execution logs in the Firebase Console or via the terminal:
  ```bash
  npx -y firebase-tools@latest functions:log
  ```
- **Check Deploy Errors:**
  If the build fails on Cloud Build, review details inside the [Google Cloud Console](https://console.cloud.google.com/) under **Cloud Build** or **Cloud Run**.
