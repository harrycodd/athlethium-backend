"""
End-to-end flows over real HTTP against the Functions emulator (+ Auth/Firestore/Storage emulators).

Journey: sign up -> set thresholds -> generate plan -> start device/app sync (Strava; Wahoo is
"coming soon") -> log sessions (manual + FIT) -> fitness and future plan update.
The Strava token exchange itself cannot be mocked inside the emulator process, so its success and
failure modes are covered in tests/handlers/test_strava.py.
"""

import datetime
import os
import socket
import time

import pytest
import requests

from tests.conftest import PROJECT_ID
from tests.factories import make_profile_doc
from tests.factories.fit import build_fit

pytestmark = pytest.mark.functions_emulator

ORIGIN = os.environ.get("FUNCTIONS_EMULATOR_ORIGIN", "http://127.0.0.1:5001")
BASE = f"{ORIGIN}/{PROJECT_ID}/europe-west2"


def _functions_up() -> bool:
    host, port = ORIGIN.split("//")[1].split(":")
    try:
        socket.create_connection((host, int(port)), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def require_functions_emulator():
    if not _functions_up():
        if os.environ.get("REQUIRE_EMULATORS") == "1":
            pytest.fail("Functions emulator is not running")
        pytest.skip("Functions emulator is not running")


def post(fn, user=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if user is not None:
        headers.update(user.headers)
    return requests.post(f"{BASE}/{fn}", headers=headers, timeout=60, **kwargs)


def test_full_athlete_journey(make_user, db):
    # 1. Sign up (Auth emulator)
    athlete = make_user("rider@example.test")

    # 2. Onboarding + thresholds
    profile = make_profile_doc(ftp=260, ftpCycling=260, fthr=168, ctl=45, atl=40, timezone="Europe/London",
                               goal={"name": "Gran Fondo", "date": "2026-11-29", "sports": ["cycling"]})
    r = post("update_user_profile", athlete, json={"profile": profile})
    assert r.status_code == 200, r.text
    assert db.document(f"users/{athlete.uid}").get().to_dict()["ftpCycling"] == 260

    # 3. Generate two weeks of plan
    r = post("generate_training_session", athlete, json={"date": "2026-10-05", "days": 14})
    assert r.status_code == 200, r.text
    assert len(r.json()["generated_dates"]) == 14
    tuesday = db.document(f"workouts/plan_{athlete.uid}_2026-10-06").get().to_dict()
    assert tuesday["status"] == "planned" and tuesday["steps"]

    # Idempotent: a second call schedules nothing new
    again = post("generate_training_session", athlete, json={"date": "2026-10-05", "days": 14}).json()
    assert again["generated_dates"] == [] and len(again["skipped_dates"]) == 14

    # 4. Start device/app sync (Strava OAuth; Wahoo is not implemented yet)
    r = post("strava_auth_start", athlete, json={"returnUrl": "athlethium://settings"})
    assert r.status_code == 200 and "strava.com" in r.json()["authUrl"]
    assert db.document(f"oauthStates/{r.json()['state']}").get().exists

    # 5a. Log a session manually
    before = db.document(f"users/{athlete.uid}").get().to_dict()
    r = post("complete_manual_workout", athlete,
             json={"workoutId": f"plan_{athlete.uid}_2026-10-06", "actual_time_sec": tuesday["plannedTime"], "rpe": 8})
    assert r.status_code == 200, r.text
    after = db.document(f"users/{athlete.uid}").get().to_dict()
    assert after["ctl"] > before["ctl"] and after["atl"] > before["atl"]
    assert after["metricsDate"] == "2026-10-06"

    # 5b. Upload a FIT file for the next day's ride
    fit = build_fit(seconds=3600, power=[200] * 3600, heart_rate=[140] * 3600,
                    start=datetime.datetime(2026, 10, 7, 6, 30, tzinfo=datetime.timezone.utc))
    r = post("upload_workout_fit", athlete, files={"file": ("morning.fit", fit)})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["workout_id"] == f"plan_{athlete.uid}_2026-10-07"
    assert data["fit_file_path"].startswith(f"users/{athlete.uid}/")
    assert db.document(f"users/{athlete.uid}").get().to_dict()["metricsDate"] == "2026-10-07"

    # 6. Plan updates: newly generated days are planned from the updated fitness state
    r = post("generate_training_session", athlete, json={"date": "2026-10-19", "days": 7})
    assert r.status_code == 200 and len(r.json()["generated_dates"]) == 7


def test_users_are_isolated_over_http(make_user, db):
    owner, intruder = make_user(), make_user()
    post("update_user_profile", owner, json={"profile": make_profile_doc()})
    post("generate_training_session", owner, json={"date": "2026-10-06"})
    workout_id = f"plan_{owner.uid}_2026-10-06"

    r = post("complete_manual_workout", intruder, json={"workoutId": workout_id, "actual_time_sec": 60})
    assert r.status_code == 404
    r = post("generate_training_session", intruder, json={"userId": owner.uid})
    assert r.status_code == 403
    assert db.document(f"workouts/{workout_id}").get().to_dict()["status"] == "planned"


@pytest.mark.parametrize("fn", ["update_user_profile", "generate_training_session", "complete_manual_workout",
                                "upload_workout_fit", "strava_auth_start", "strava_disconnect"])
def test_unauthenticated_http_calls_rejected(fn, emulators):
    assert post(fn, json={"userId": "anyone"}).status_code == 401


def test_cors_preflight_allows_bearer_auth(emulators):
    r = requests.options(f"{BASE}/generate_training_session", timeout=30, headers={
        "Origin": "http://localhost:8081",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("Access-Control-Allow-Origin") in ("*", "http://localhost:8081")


def _emulator_secret(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "functions", ".secret.local")
    with open(path) as fh:
        return next(line.split("=", 1)[1].strip() for line in fh if line.startswith(f"{name}="))


def test_strava_webhook_handshake_queue_and_trigger(db):
    """Strava -> strava_webhook -> stravaEvents -> process_strava_event, through the real emulators."""
    r = requests.get(f"{BASE}/strava_webhook", timeout=30, params={
        "hub.mode": "subscribe", "hub.verify_token": _emulator_secret("STRAVA_VERIFY_TOKEN"), "hub.challenge": "c-1"})
    assert r.status_code == 200 and r.json() == {"hub.challenge": "c-1"}

    event = {"object_type": "activity", "aspect_type": "create", "object_id": 1, "owner_id": 999_123,
             "subscription_id": 1, "event_time": 1_790_000_000, "updates": {}}
    assert post("strava_webhook", json=event).status_code == 200
    ref = db.document("stravaEvents/activity_1_create_999123_1790000000")
    deadline = datetime.datetime.now() + datetime.timedelta(seconds=60)
    while datetime.datetime.now() < deadline and (ref.get().to_dict() or {}).get("status") in (None, "queued"):
        time.sleep(0.5)  # the trigger runs asynchronously
    assert ref.get().to_dict()["status"] == "ignored:unknown_athlete"  # no athlete linked: nothing else touched
