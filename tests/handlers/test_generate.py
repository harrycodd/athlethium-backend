import pytest
from google.cloud.firestore_v1.base_query import FieldFilter
import time_machine

from tests.factories import make_profile_doc, make_workout_doc

pytestmark = pytest.mark.emulator


@pytest.fixture
def athlete(make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc()})
    return user


def test_generates_requested_days(main_module, call, athlete, db):
    r = call(main_module.generate_training_session, json={"date": "2026-10-05", "days": 7}, user=athlete)
    assert r.status == 200, r.text
    assert r.json["generated_dates"] == [f"2026-10-{d:02d}" for d in range(5, 12)]
    docs = db.collection("workouts").where(filter=FieldFilter("userId", "==", athlete.uid)).get()
    assert len(docs) == 7
    assert {d.id for d in docs} == {f"plan_{athlete.uid}_2026-10-{d:02d}" for d in range(5, 12)}


def test_skips_days_already_planned(main_module, call, athlete, seed):
    seed({"workouts/manual": make_workout_doc(athlete.uid, "2026-10-06")})
    r = call(main_module.generate_training_session, json={"date": "2026-10-05", "days": 3}, user=athlete)
    assert r.json["generated_dates"] == ["2026-10-05", "2026-10-07"]
    assert r.json["skipped_dates"] == ["2026-10-06"]


def test_goal_day_no_longer_crashes(main_module, call, athlete, db):
    r = call(main_module.generate_training_session, json={"date": "2026-11-29"}, user=athlete)
    assert r.status == 200 and r.json["generated_dates"] == ["2026-11-29"]


@time_machine.travel("2026-10-06 23:30:00+00:00", tick=False)
def test_default_date_is_athletes_local_today(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(timezone="Australia/Sydney")})
    r = call(main_module.generate_training_session, json={}, user=user)
    assert r.json["generated_dates"] == ["2026-10-07"]  # already Wednesday in Sydney


@time_machine.travel("2026-10-06 23:30:00+00:00", tick=False)
def test_default_date_utc_when_timezone_invalid(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(timezone="Not/AZone")})
    r = call(main_module.generate_training_session, json={"date": ""}, user=user)
    assert r.json["generated_dates"] == ["2026-10-06"]


@pytest.mark.parametrize("body,msg", [
    ({"days": 0}, "days must be"), ({"days": 29}, "days must be"), ({"days": "many"}, "days must be"),
    ({"days": True}, "days must be"), ({"days": 1.5}, "days must be"),
    ({"date": "06/10/2026"}, "Invalid date"), ({"date": 20261006}, "Invalid date"),
])
def test_bad_input_is_400(main_module, call, athlete, body, msg):
    r = call(main_module.generate_training_session, json=body, user=athlete)
    assert r.status == 400 and msg in r.json["error"]


def test_days_as_numeric_string_ok(main_module, call, athlete):
    r = call(main_module.generate_training_session, json={"date": "2026-10-05", "days": "2"}, user=athlete)
    assert len(r.json["generated_dates"]) == 2


def test_no_profile_is_404(main_module, call, make_user):
    assert call(main_module.generate_training_session, json={}, user=make_user()).status == 404


def test_incomplete_wizard_profile_is_400(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": {"displayName": "", "wizardCompleted": False}})
    r = call(main_module.generate_training_session, json={}, user=user)
    assert r.status == 400 and "incomplete" in r.json["error"]


def test_never_overwrites_completed_workout(main_module, call, athlete, seed, db, monkeypatch):
    plan_id = f"plan_{athlete.uid}_2026-10-05"
    seed({f"workouts/{plan_id}": make_workout_doc(athlete.uid, "2026-10-05", completed=True, status="completed",
                                                  actual_tss=99)})
    # Simulate the pre-check missing it (e.g. a race between two requests)
    monkeypatch.setattr(main_module.WorkoutService, "has_workout_for_date", classmethod(lambda cls, u, d: False))
    r = call(main_module.generate_training_session, json={"date": "2026-10-05"}, user=athlete)
    assert r.json["skipped_dates"] == ["2026-10-05"]
    assert db.document(f"workouts/{plan_id}").get().to_dict()["actual_tss"] == 99


def test_save_removes_uncompleted_duplicates_but_keeps_events(main_module, athlete, seed, db):
    from engine.scheduler import TrainingScheduler
    from services.user_service import UserService
    import datetime

    seed({
        "workouts/dup": make_workout_doc(athlete.uid, "2026-10-05"),
        "workouts/done": make_workout_doc(athlete.uid, "2026-10-05", completed=True),
        "workouts/event": make_workout_doc(athlete.uid, "2026-10-05", type="Event"),
    })
    profile = UserService.get_user_profile(athlete.uid)
    doc = TrainingScheduler.schedule_day(profile, datetime.date(2026, 10, 5))
    assert main_module.WorkoutService.save_workout(doc) == doc.workout_id
    ids = {d.id for d in db.collection("workouts").get()}
    assert ids == {"done", "event", doc.workout_id}
    assert main_module.WorkoutService.get_workout_by_id("dup") is None
    assert main_module.WorkoutService.get_workout_by_id("done")["completed"] is True
