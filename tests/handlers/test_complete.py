import pytest

from tests.factories import make_profile_doc, make_workout_doc

pytestmark = pytest.mark.emulator


@pytest.fixture
def athlete(make_user, seed):
    user = make_user()
    seed({
        f"users/{user.uid}": make_profile_doc(ctl=50, atl=50, metricsDate="2026-10-05"),
        "workouts/w1": make_workout_doc(user.uid, "2026-10-06", plannedTss=120.0, plannedTime=5400),
    })
    return user


def complete(main_module, call, user, **body):
    payload = {"workoutId": "w1", "actual_time_sec": 5400}
    payload.update(body)
    return call(main_module.complete_manual_workout, json=payload, user=user)


def test_completes_and_updates_load(main_module, call, athlete, db):
    r = complete(main_module, call, athlete, rpe=7, notes="felt good")
    assert r.status == 200, r.text
    assert r.json["data"]["actual_tss"] == 120.0
    w = db.document("workouts/w1").get().to_dict()
    assert w["status"] == "completed" and w["rpe"] == 7 and w["userNotes"] == "felt good"
    u = db.document(f"users/{athlete.uid}").get().to_dict()
    assert u["metricsDate"] == "2026-10-06"
    assert u["ctl"] == pytest.approx(51.67, abs=0.01) and u["atl"] == pytest.approx(60.0, abs=0.01)


def test_partial_session_scales_tss(main_module, call, athlete):
    assert complete(main_module, call, athlete, actual_time_sec=2700).json["data"]["actual_tss"] == 60.0


def test_recompleting_does_not_double_count(main_module, call, athlete, db):
    complete(main_module, call, athlete)
    first = db.document(f"users/{athlete.uid}").get().to_dict()
    complete(main_module, call, athlete, notes="edited")
    second = db.document(f"users/{athlete.uid}").get().to_dict()
    assert (second["ctl"], second["atl"]) == (first["ctl"], first["atl"])


def test_unplanned_tss_uses_rpe(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(),
          "workouts/w2": make_workout_doc(user.uid, plannedTss=0, tss=0, plannedTime=0, time=0)})
    r = call(main_module.complete_manual_workout, json={"workoutId": "w2", "actual_time_sec": 3600, "rpe": 10},
             user=user)
    assert r.json["data"]["actual_tss"] == 140.0


def test_strength_counts_zero_tss(main_module, call, make_user, seed, db):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(ctl=40, atl=40),
          "workouts/s": make_workout_doc(user.uid, sport="strength")})
    r = call(main_module.complete_manual_workout, json={"workoutId": "s", "actual_time_sec": 1800}, user=user)
    assert r.json["data"]["actual_tss"] == 0.0
    assert db.document(f"users/{user.uid}").get().to_dict()["ctl"] == 40


def test_other_users_workout_is_404_and_untouched(main_module, call, athlete, make_user, db):
    r = complete(main_module, call, make_user())
    assert r.status == 404
    assert db.document("workouts/w1").get().to_dict()["status"] == "planned"


def test_missing_workout_is_404(main_module, call, athlete):
    assert complete(main_module, call, athlete, workoutId="nope").status == 404


@pytest.mark.parametrize("body", [
    {"workoutId": None}, {"workoutId": ""}, {"workoutId": "a/b"}, {"workoutId": 5},
    {"actual_time_sec": None}, {"actual_time_sec": 0}, {"actual_time_sec": -5}, {"actual_time_sec": "3600"},
    {"actual_time_sec": True}, {"actual_time_sec": 90000},
    {"rpe": 0}, {"rpe": 11}, {"rpe": 7.5}, {"rpe": True},
    {"notes": 5}, {"notes": "x" * 2001},
])
def test_bad_input_is_400(main_module, call, athlete, body):
    assert complete(main_module, call, athlete, **body).status == 400
