# Athlethium Backend

The backend engine for **Athlethium**, powering deterministic training periodization, interval generation, FIT file completion, and Strava synchronization via Firebase Cloud Functions.

---

## 🚀 Quickstart

### 1. Run the Test Suite
```bash
cd functions
python tests/run_tests.py
```

### 2. Run Firebase Local Emulators
```bash
npx -y firebase-tools@latest emulators:start --only functions,firestore
```

### 3. Deploy to Firebase
```bash
npx -y firebase-tools@latest deploy --only functions
```

---

## 📖 Documentation

* [Firebase Deployment Guide](docs/DEPLOYMENT_GUIDE.md)
* [Architecture & Test Suite](docs/README.md)
* [API Endpoints Documentation](docs/API_DOCS.md)
* [Firebase Setup & Emulator Guide](docs/FIREBASE_GUIDE.md)

---

## 📁 Folder Structure

* **`functions/`**: The core Python package containing the training engine, interval generators, Firestore services, and simulation test suite.
* **`docs/`**: Markdown guides, API documentation, and architecture diagrams.
* **`scripts/`**: CLI developer tools (Strava webhook setup, seed script, TUI viewers).
* **`examples/`**: Example JSON workout payloads.
