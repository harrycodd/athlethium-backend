import datetime
import io

import pytest

from tests.factories import make_profile_doc, make_workout_doc
from tests.factories.fit import build_fit

pytestmark = pytest.mark.emulator

UTC = datetime.timezone.utc


@pytest.fixture
def athlete(make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(ftp=250, ftpCycling=250, fthr=170, ctl=50, atl=50,
                                                metricsDate="2026-10-05", timezone="Europe/London")})
    return user


def upload(main_module, call, user, fit_bytes, filename="ride.fit", **form):
    data = {"file": (io.BytesIO(fit_bytes), filename), **form}
    return call(main_module.upload_workout_fit, data=data, user=user)


def steady_ride(seconds=3600, watts=250, **kw):
    return build_fit(seconds=seconds, power=[watts] * seconds, heart_rate=[150] * seconds, **kw)


def test_matches_planned_workout_and_stores_private_file(main_module, call, athlete, seed, db):
    seed({"workouts/plan": make_workout_doc(athlete.uid, "2026-10-06", sport="cycling")})
    r = upload(main_module, call, athlete, steady_ride())
    assert r.status == 200, r.text
    data = r.json["data"]
    assert data["workout_id"] == "plan" and data["actual_tss"] == 100.0 and data["sport"] == "cycling"
    w = db.document("workouts/plan").get().to_dict()
    assert w["status"] == "completed" and w["completion_type"] == "fit_upload"
    assert w["fit_file_path"] == f"users/{athlete.uid}/workouts/plan.fit" and "fit_file_url" not in w

    from firebase_admin import storage
    assert storage.bucket().get_blob(w["fit_file_path"]) is not None


def test_prefers_same_sport_and_skips_completed(main_module, call, athlete, seed, db):
    seed({
        "workouts/done": make_workout_doc(athlete.uid, "2026-10-06", sport="running", completed=True, status="completed"),
        "workouts/swim": make_workout_doc(athlete.uid, "2026-10-06", sport="swimming"),
        "workouts/run": make_workout_doc(athlete.uid, "2026-10-06", sport="running"),
    })
    fit = build_fit(seconds=1800, heart_rate=[170] * 1800, sport="running")
    data = upload(main_module, call, athlete, fit).json["data"]
    assert data["workout_id"] == "run" and data["sport"] == "running"
    assert data["actual_tss"] == 50.0  # hrTSS at threshold HR for 30 min


def test_creates_activity_when_nothing_planned(main_module, call, athlete, db):
    data = upload(main_module, call, athlete, steady_ride(1800)).json["data"]
    w = db.document(f"workouts/{data['workout_id']}").get().to_dict()
    assert w["name"] == "Recorded Activity" and w["userId"] == athlete.uid and w["date"] == "2026-10-06"


def test_late_evening_ride_counts_for_local_day(main_module, call, make_user, seed):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc(timezone="America/Los_Angeles")})
    fit = steady_ride(1800, start=datetime.datetime(2026, 10, 7, 2, 0, tzinfo=UTC))  # 19:00 on the 6th in LA
    assert upload(main_module, call, user, fit).json["data"]["date"] == "2026-10-06"


def test_auto_ftp_detected_for_cycling_only(main_module, call, athlete, db):
    data = upload(main_module, call, athlete, steady_ride(1500, watts=300)).json["data"]
    assert data["new_ftp"] == 285.0
    assert db.document(f"users/{athlete.uid}").get().to_dict()["ftpCycling"] == 285.0

    run = build_fit(seconds=1500, power=[400] * 1500, sport="running",
                    start=datetime.datetime(2026, 10, 8, 7, tzinfo=UTC))
    assert upload(main_module, call, athlete, run).json["data"]["new_ftp"] is None


def test_explicit_workout_must_be_owned(main_module, call, athlete, make_user, seed):
    other = make_user()
    seed({"workouts/theirs": make_workout_doc(other.uid, "2026-10-06")})
    assert upload(main_module, call, athlete, steady_ride(), workoutId="theirs").status == 404
    assert upload(main_module, call, athlete, steady_ride(), workoutId="a/b").status == 400


def test_reupload_to_same_workout_does_not_double_count(main_module, call, athlete, seed, db):
    seed({"workouts/plan": make_workout_doc(athlete.uid, "2026-10-06")})
    upload(main_module, call, athlete, steady_ride(), workoutId="plan")
    first = db.document(f"users/{athlete.uid}").get().to_dict()["ctl"]
    upload(main_module, call, athlete, steady_ride(), workoutId="plan")
    assert db.document(f"users/{athlete.uid}").get().to_dict()["ctl"] == first


def test_filename_is_never_used_as_a_path(main_module, call, athlete, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    r = upload(main_module, call, athlete, steady_ride(600), filename="../../etc/evil.fit")
    assert r.status == 200
    assert not (tmp_path.parent.parent / "etc" / "evil.fit").exists()
    assert list(tmp_path.iterdir()) == []  # temp file cleaned up


@pytest.mark.parametrize("data,status", [
    ({}, 400),
    ({"file": (io.BytesIO(b""), "")}, 400),
    ({"file": (io.BytesIO(b"not a fit file"), "x.fit")}, 400),
])
def test_bad_uploads(main_module, call, athlete, data, status):
    assert call(main_module.upload_workout_fit, data=data, user=athlete).status == status


def test_userid_form_field_must_match(main_module, call, athlete):
    assert upload(main_module, call, athlete, steady_ride(600), userId="someone-else").status == 403


def test_too_large(main_module, call, athlete, monkeypatch):
    monkeypatch.setattr(main_module, "MAX_FIT_BYTES", 100)
    assert upload(main_module, call, athlete, steady_ride(600)).status == 413


def test_storage_failure_still_completes(main_module, call, athlete, monkeypatch):
    def broken_bucket():
        raise RuntimeError("storage down")

    monkeypatch.setattr(main_module.storage, "bucket", broken_bucket)
    r = upload(main_module, call, athlete, steady_ride(600))
    assert r.status == 200 and "fit_file_path" not in r.json["data"]
