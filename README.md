# Athlethium Backend

[![CI](https://github.com/harrycodd/fitness-app-backend/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/harrycodd/fitness-app-backend/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/harrycodd/fitness-app-backend/branch/main/graph/badge.svg)](https://codecov.io/gh/harrycodd/fitness-app-backend)
![plan logic coverage](https://img.shields.io/badge/plan%20logic%20coverage-100%25%20(enforced)-brightgreen)

Python Cloud Functions for **Athlethium**, an endurance training app. The backend plans training
weeks, generates structured sessions, completes workouts from FIT files, and connects Strava.
The React Native app lives in [harrycodd/fitness-app](https://github.com/harrycodd/fitness-app).

---

## Architecture

```
 React Native app (Expo)                    Firebase project
 ───────────────────────                    ─────────────────────────────────────────────
 Firebase Auth sign-in  ─────────────────▶  Auth
 reads own docs  ◀──── security rules ────  Firestore  users/{uid}, workouts/{id}
 HTTPS + ID token ───────────────────────▶  Cloud Functions (Python 3.12, europe-west2)
                                              main.py            HTTP handlers, auth, errors
                                              services/          Firestore, Strava, FIT files
                                              engine/            planner, physiology, zones
                                              generators/        session/interval builders
                                            Storage  users/{uid}/workouts/*.fit (server only)
```

- **Every endpoint needs a Firebase ID token** (`Authorization: Bearer <token>`). The user is
  taken from the token, never from the request body.
- **Endpoints:** `update_user_profile`, `generate_training_session`, `complete_manual_workout`,
  `upload_workout_fit`, `strava_auth_start`, `strava_callback`, `strava_disconnect`.
  See [docs/API_DOCS.md](docs/API_DOCS.md).
- **Planner** (`functions/engine/planner.py`) plans whole Monday–Sunday weeks from the athlete's
  fitness (CTL/ATL), recent completed weeks and availability:
  - polarised: at most 25% hard sessions, no tempo;
  - load grows at most +10% (hours and TSS) per week;
  - recovery week every 3–4 weeks;
  - taper and race-week routine before an event;
  - comeback after time off; illness and injury handling;
  - levels from beginner to pro, with double days at higher levels;
  - sport switching with partial fitness transfer.
  The rules are listed in [docs/golden-plans.md](docs/golden-plans.md), with example plans for
  five reference athletes.
- **Security rules:**
  - `firestore.rules`: owner-only access; Strava tokens live in a server-only `private` subcollection.
  - `storage.rules`: no client access at all.
  - Both have tests.

## Running locally (emulators only)

Development never touches the production project. Everything runs against the Firebase Emulator
Suite with the `demo-athlethium` project ID (`demo-*` projects cannot reach real resources).

Requirements: Python 3.12, Node 22, Java 21 (for the Firestore/Storage emulators).

```bash
python3.12 -m venv functions/venv
functions/venv/bin/pip install -r requirements-dev.txt
npm ci

# Functions emulator needs a value for each declared secret; use a dummy.
echo "STRAVA_CLIENT_SECRET=emulator-dummy-secret" > functions/.secret.local

npx firebase emulators:start --project demo-athlethium --only auth,firestore,functions,storage
```

- Emulator UI: http://127.0.0.1:4000
- Functions: `http://127.0.0.1:5001/demo-athlethium/europe-west2/<function>`

To point the app at the emulators, set `EXPO_PUBLIC_FUNCTIONS_BASE_URL` in the app (see its README).

Seed the workout library into the emulator with `functions/venv/bin/python scripts/seed_firestore.py`.
Scripts that write data default to the emulator. They refuse production unless given
`--project athlethium-app --i-understand-this-is-production`.

## Running the tests

One command starts the emulators, runs every suite and stops them:

```bash
./scripts/test.sh                         # everything
./scripts/test.sh tests/unit -k planner   # a subset (args go to pytest)
```

| Suite | What it covers |
|---|---|
| `tests/unit` | physiology, periodisation, zones, generators, scheduler, planner, validation |
| `tests/handlers` | each HTTP handler in-process against the Firestore emulator |
| `tests/integration` | full athlete journey over HTTP through the Functions emulator |
| `tests/property` | Hypothesis invariants (polarisation, ramp, recovery, availability) and 2-year career simulations (beginner to pro, sport switches) |
| `tests/characterisation` | snapshot tests for the golden athletes in `tests/data/golden` |
| `tests/rules` | Firestore and Storage security rules (vitest + `@firebase/rules-unit-testing`) |

Coverage gates (enforced by `scripts/run_suites.sh` and CI):
- backend overall ≥ 80% (currently ~98.5%);
- `functions/engine` and `functions/generators` at 100% line and branch.

Longer property runs: `HYPOTHESIS_MAX_EXAMPLES=1000 functions/venv/bin/python -m pytest tests/property --no-cov`.

After changing the planner, regenerate the golden plans report and commit it:

```bash
functions/venv/bin/python scripts/plan_report.py          # rewrites docs/golden-plans.md
functions/venv/bin/python scripts/plan_report.py --check  # CI: fails if it is stale
```

Lint: `functions/venv/bin/ruff check .`

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:
1. ruff lint;
2. `./scripts/test.sh` (all suites against the emulators, with the coverage gates);
3. the golden-plans staleness check.

A coverage summary is added to each run's summary page. When a `CODECOV_TOKEN` repository secret
is set, coverage is also uploaded to Codecov (drives the badge above).

## Deploying

See [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md).

## Folder structure

```
functions/            Cloud Functions package (deployed)
  main.py             HTTP endpoints
  core/               config and typed models
  engine/             planner, scheduler, physiology, periodisation, zones, guardrails
  generators/         endurance, strength and mobility session builders
  services/           auth, Firestore user/workout services, FIT completion, Strava
tests/                pytest suites, factories, golden data, rules tests
scripts/              test runner, seed and migration scripts, plan report
docs/                 API docs, deployment guide, golden plans
firestore.rules  storage.rules  firestore.indexes.json  firebase.json
```
