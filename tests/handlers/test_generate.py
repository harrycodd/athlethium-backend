import pytest
from google.cloud.firestore_v1.base_query import FieldFilter

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


@pytest.fixture
def late_evening_utc(monkeypatch):
    """
    Pins the clock UserService reads to 23:30 UTC on 6 Oct 2026. Only that module's clock: freezing
    the whole process (time_machine) puts gRPC deadlines in the past once the real date moves on.
    """
    import datetime
    import types

    from services import user_service

    class Pinned(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            moment = datetime.datetime(2026, 10, 6, 23, 30, tzinfo=datetime.timezone.utc)
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)

    clock = types.SimpleNamespace(**{k: getattr(datetime, k) for k in dir(datetime) if not k.startswith("_")})
    clock.datetime = Pinned
    monkeypatch.setattr(user_service, "datetime", clock)


@pytest.mark.usefixtures("late_evening_utc")
def test_default_date_is_athletes_local_today(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(timezone="Australia/Sydney")})
    r = call(main_module.generate_training_session, json={}, user=user)
    assert r.json["generated_dates"] == ["2026-10-07"]  # already Wednesday in Sydney


@pytest.mark.usefixtures("late_evening_utc")
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


def test_recent_load_summarises_completed_weeks(main_module, athlete, seed):
    import datetime
    seed({
        "workouts/a": make_workout_doc(athlete.uid, "2026-09-22", completed=True, status="completed",
                                       actual_time=3600, actual_tss=50.0),
        "workouts/b": make_workout_doc(athlete.uid, "2026-09-24", completed=True, actual_time=1800, actual_tss=40.0),
        "workouts/c": make_workout_doc(athlete.uid, "2026-09-29", completed=True, actual_time=7200, actual_tss=90.0),
        "workouts/planned": make_workout_doc(athlete.uid, "2026-09-30"),
        "workouts/strength": make_workout_doc(athlete.uid, "2026-09-30", sport="strength", completed=True),
        "workouts/today": make_workout_doc(athlete.uid, "2026-10-06", completed=True, actual_time=3600, actual_tss=70.0),
        "workouts/future": make_workout_doc(athlete.uid, "2026-10-08", completed=True, actual_tss=99.0),
        "workouts/old": make_workout_doc(athlete.uid, "2026-09-01", completed=True, actual_tss=99.0),
        "workouts/bad": make_workout_doc(athlete.uid, "not-a-date", completed=True),
        "workouts/other": make_workout_doc("someone-else", "2026-09-29", completed=True, actual_tss=99.0),
    })
    weeks, week_to_date = main_module.WorkoutService.recent_load(athlete.uid, datetime.date(2026, 10, 7))
    assert weeks == {"2026-09-21": [1.5, 90.0, {"cycling": 1.5}, {"cycling": 1.0}],
                     "2026-09-28": [2.0, 90.0, {"cycling": 2.0}, {"cycling": 2.0}]}
    assert week_to_date == [["2026-10-06", 70.0]]


def test_generation_ramps_from_completed_history(main_module, call, make_user, seed, db, monkeypatch):
    """A big completed block lets this week's plan grow; nothing completed keeps it at entry level."""
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(ctl=30, atl=30, metricsDate="2026-10-04", weekly_hours=25,
                                                dailyMaxHours={d: 4 for d in ["Monday", "Tuesday", "Wednesday",
                                                               "Thursday", "Friday", "Saturday", "Sunday"]})})
    for i, day in enumerate(["2026-09-29", "2026-09-30", "2026-10-02", "2026-10-03", "2026-10-04"]):
        seed({f"workouts/h{i}": make_workout_doc(user.uid, day, completed=True, actual_time=2 * 3600, actual_tss=100.0)})
    # pin "today" without freezing the clock (frozen time stalls the Firestore client's retries)
    import datetime
    monkeypatch.setattr(main_module.UserService, "today_for", staticmethod(lambda p: datetime.date(2026, 10, 5)))
    r = call(main_module.generate_training_session, json={"days": 7}, user=user)
    assert r.status == 200 and len(r.json["generated_dates"]) == 7
    planned = [d.to_dict() for d in db.collection("workouts").where(filter=FieldFilter("userId", "==", user.uid)).get()
               if not d.to_dict().get("completed")]
    hours = sum(d["time"] for d in planned if d["sport"] in ("cycling", "running")) / 3600
    assert 8 <= hours <= 10 * 1.10 + 1e-6  # ramps from last week's 10 h, by at most 10%


def test_double_day_saves_both_sessions_and_keeps_them(main_module, athlete, db):
    """Saving a double day must not delete its own morning session (old same-day clean-up did)."""
    from core.models import WorkoutDoc

    def doc(suffix, sport):
        return WorkoutDoc(workout_id=f"plan_{athlete.uid}_2026-10-07{suffix}", user_id=athlete.uid, date="2026-10-07",
                          name=f"{sport} easy", sport=sport, intensity=2, time=3600, planned_time=3600, tss=50,
                          planned_tss=50, target_type="power", description="", steps=[], slot=suffix and "pm" or "am")

    saved = main_module.WorkoutService.save_day([doc("", "cycling"), doc("_pm", "swimming")])
    assert saved == [f"plan_{athlete.uid}_2026-10-07", f"plan_{athlete.uid}_2026-10-07_pm"]
    again = main_module.WorkoutService.save_day([doc("", "cycling"), doc("_pm", "running")])
    assert len(again) == 2
    docs = {d.id: d.to_dict() for d in db.collection("workouts").get()}
    assert docs[f"plan_{athlete.uid}_2026-10-07_pm"]["sport"] == "running"
    assert docs[f"plan_{athlete.uid}_2026-10-07_pm"]["slot"] == "pm"
    assert main_module.WorkoutService.save_day([]) == []


def test_pro_athlete_gets_double_days_from_the_endpoint(main_module, call, make_user, seed, db, monkeypatch):
    import datetime
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(
        ctl=120, atl=115, metricsDate="2026-10-04", weekly_hours=28, fitness_level="pro",
        activities={"running": True, "cycling": True, "swimming": True, "strength": False, "stretching": False},
        mainFocus={"running": True, "cycling": True, "swimming": True, "strength": False, "stretching": False},
        sports=["swimming", "cycling", "running"], focused_sports=["cycling", "running", "swimming"],
        goal=None, dailyMaxHours={d: 6 for d in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                                "Saturday", "Sunday"]})})
    for i, day in enumerate(["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]):
        seed({f"workouts/h{i}": make_workout_doc(user.uid, day, sport=["cycling", "running", "swimming"][i % 3],
                                                 completed=True, actual_time=4 * 3600, actual_tss=200.0)})
    monkeypatch.setattr(main_module.UserService, "today_for", staticmethod(lambda p: datetime.date(2026, 10, 5)))
    r = call(main_module.generate_training_session, json={"days": 7}, user=user)
    assert r.status == 200, r.text
    planned = [d.to_dict() for d in db.collection("workouts").where(filter=FieldFilter("userId", "==", user.uid)).get()
               if not d.to_dict().get("completed")]
    assert any(d["slot"] == "pm" for d in planned)
    assert {d["sport"] for d in planned} >= {"cycling", "running", "swimming"}
