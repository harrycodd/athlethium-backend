# Athlethium Backend Documentation

Welcome to the **Athlethium Backend**! This directory contains documentation, API references, and architecture guides for the Athlethium training engine and Firebase Cloud Functions.

---

## 📚 Table of Contents

1. [Architecture & Training Engine](#-architecture--training-engine)
2. [Deployment Guide](DEPLOYMENT_GUIDE.md)
3. [API Reference](API_DOCS.md)
4. [Firebase Guide & Local Emulators](FIREBASE_GUIDE.md)
4. [Test Harness & Simulations](#-test-harness--simulations)
5. [Directory Structure](#-directory-structure)

---

## 🧠 Architecture & Training Engine

Athlethium uses a **100% deterministic, sports-science grounded training algorithm** built on:
- **Banister Impulse-Response Model**: Calculates Chronic Training Load (CTL / Fitness), Acute Training Load (ATL / Fatigue), and Training Stress Balance (TSB / Form) using Exponentially Weighted Moving Averages (EWMA).
- **Coggan Power & Pace Zones**: 7 distinct intensity zones (Z1 Active Recovery to Z7 Sprint) with exact `% FTP` and `% FTHR` interval targets.
- **Polarized 80/20 & Periodization**:
  - **Macrocycles**: Base ($>12$ wks), Build ($4-12$ wks), Peak ($2-4$ wks), Taper ($<2$ wks), and Race Day.
  - **Mesocycles (3:1)**: 3 weeks of progressive overload followed by 1 week of deload/supercompensation ($40\%$ volume reduction).
  - **Adaptive Guardrails**: Clamps training load during illness, injury, or deep fatigue ($\text{TSB} < -25$).

---

## 🧪 Test Harness & Simulations

A realistic test harness is located in `functions/tests/`. It includes unit tests and full **30-day athlete simulations**.

### Running the Test Suite:
```bash
cd functions
python tests/run_tests.py
```

### Test Coverage:
- `test_athlete_sim.py`: 30-day multi-week simulation across Cyclist, Marathoner, and Triathlete personas.
- `test_generators.py`: Verifies interval durations sum exactly to target seconds.
- `test_periodization.py`: Verifies macrocycle phases and 3:1 deload weeks.
- `test_scheduler.py`: Verifies daily hour limits (`dailyMaxHours`) and safety clamps.

---

## 📁 Directory Structure

```
fitness-app-backend/
├── firebase.json                     # Firebase deployment configuration
├── .firebaserc                       # Active Firebase project configuration
│
├── functions/                        # Cloud Functions backend package
│   ├── main.py                       # HTTP endpoint handlers
│   ├── requirements.txt              # Minimal production dependencies
│   ├── core/                         # Config, Coggan zones, and typed models
│   ├── engine/                       # Physiology (CTL/ATL/TSB), Periodization, Scheduler
│   ├── generators/                   # Interval builders (Endurance, Strength, Mobility)
│   ├── services/                     # Firestore User/Workout adapters & FIT parsing
│   └── tests/                        # Simulation test harness
│
├── docs/                             # Documentation, guides & visual assets
│   ├── README.md                     # This documentation index
│   ├── API_DOCS.md                   # Cloud Functions API reference
│   ├── FIREBASE_GUIDE.md             # Firebase deployment & local emulator guide
│   └── assets/                       # Plots, visual diagrams & chart exports
│
├── scripts/                          # Developer utilities & CLI tools
│   ├── setup_strava_webhook.py       # Strava webhook registration tool
│   ├── seed_firestore.py             # Test athlete seeding tool
│   ├── add_custom_workout.py         # Custom workout builder CLI
│   ├── tui_strength.py               # Strength routine terminal viewer
│   └── tui_stretch.py                # Mobility routine terminal viewer
│
└── examples/                         # Sample JSON payloads & workout exports
    ├── example_full_workout.json
    ├── example_stretching_workout.json
    └── workout.json
```
