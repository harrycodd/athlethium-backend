"""
Strava webhook: subscription handshake, event intake, and processing (Strava API mocked).

Processing is tested by calling StravaWebhookService directly, never by writing `stravaEvents`
documents, so the Functions emulator's trigger can't race these tests.
"""

import datetime
import re
import time

import pytest
import requests
import requests_mock as rm

from google.cloud.firestore_v1.base_query import FieldFilter

from engine.physiology import PhysiologyEngine
from services.strava_service import STRAVA_TOKEN_URL
from services.strava_webhook import StravaWebhookService as Webhook
from tests.factories import make_profile_doc, make_workout_doc

pytestmark = pytest.mark.emulator

ATHLETE = 4242
UID = "rider"
ACTIVITY_URL = re.compile(r"https://www\.strava\.com/api/v3/activities/(\d+)")


@pytest.fixture(autouse=True)
def webhook_env(monkeypatch):
    monkeypatch.setenv("STRAVA_VERIFY_TOKEN", "verify-me")
    monkeypatch.delenv("STRAVA_SUBSCRIPTION_ID", raising=False)
    monkeypatch.setattr(time, "sleep", lambda s: None)  # no real back-off waits in retries


@pytest.fixture
def strava():
    with rm.Mocker(real_http=True) as m:
        yield m


@pytest.fixture
def rider(seed):
    """A connected athlete with a valid token and an empty plan."""
    seed({
        f"users/{UID}": make_profile_doc(stravaConnected=True, stravaAthleteId=str(ATHLETE), ctl=40, atl=40,
                                         metricsDate="2026-10-05", ftpCycling=250, fthr=165),
        f"users/{UID}/private/strava": {"accessToken": "acc", "refreshToken": "ref",
                                        "expiresAt": time.time() + 3600, "athleteId": str(ATHLETE)},
    })
    return UID


def event(aspect="create", object_id=111, object_type="activity", owner=ATHLETE, **extra):
    return {"object_type": object_type, "aspect_type": aspect, "object_id": object_id, "owner_id": owner,
            "subscription_id": 7, "event_time": 1_790_000_000, "updates": {}, **extra}


def activity(activity_id=111, sport_type="Ride", date="2026-10-06", moving=3600, owner=ATHLETE, **extra):
    return {"id": activity_id, "athlete": {"id": owner}, "name": "Morning Ride", "sport_type": sport_type,
            "type": sport_type, "start_date_local": f"{date}T07:00:00Z", "moving_time": moving,
            "elapsed_time": moving + 120, "distance": 30000.0, "device_watts": True, "average_watts": 190.0,
            "weighted_average_watts": 200.0, "average_heartrate": 140.0, **extra}


def process(evt):
    return Webhook.process(evt, client_id="157155", client_secret="secret")


def workouts(db, uid=UID):
    return {d.id: d.to_dict() for d in db.collection("workouts").where(filter=FieldFilter("userId", "==", uid)).get()}


def ctl(db, uid=UID):
    return db.document(f"users/{uid}").get().to_dict()["ctl"]


def ctl_without_the_ride():
    """The rider's CTL on the activity day had they not trained (fitness decays by a day)."""
    return PhysiologyEngine.apply_session_load(40, 40, datetime.date(2026, 10, 5), datetime.date(2026, 10, 6), 0)[0]


# ------------------------------------------------------------------ HTTP endpoint

class TestEndpoint:
    def handshake(self, main_module, call, **query):
        return call(main_module.strava_webhook, method="GET", query=query)

    def test_subscription_handshake_echoes_challenge(self, main_module, call):
        r = self.handshake(main_module, call, **{"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                 "hub.challenge": "abc123"})
        assert r.status == 200 and r.json == {"hub.challenge": "abc123"}

    @pytest.mark.parametrize("query", [
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "abc"},
        {"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "abc"},
        {"hub.mode": "subscribe", "hub.verify_token": "verify-me"},
        {},
    ])
    def test_handshake_rejected(self, main_module, call, query):
        assert self.handshake(main_module, call, **query).status == 403

    def test_handshake_without_configured_token(self, main_module, call, monkeypatch):
        monkeypatch.delenv("STRAVA_VERIFY_TOKEN")
        r = self.handshake(main_module, call, **{"hub.mode": "subscribe", "hub.verify_token": "",
                                                 "hub.challenge": "abc"})
        assert r.status == 500

    def test_event_is_queued_once(self, main_module, call, db):
        evt = event(owner=999_001)  # no linked athlete: the emulator's trigger just ignores it
        r = call(main_module.strava_webhook, json=evt)
        assert r.status == 200 and r.json["message"] == "Event received"
        assert call(main_module.strava_webhook, json=evt).json["message"] == "Event already received"
        queued = db.document(f"stravaEvents/{Webhook.event_key(evt)}").get().to_dict()
        assert queued["owner_id"] == 999_001 and queued["object_id"] == 111 and "expireAt" in queued

    @pytest.mark.parametrize("body", [
        {}, event(object_type="route"), event(aspect="archive"), event(object_id="1"), event(owner=True),
        event(updates=["x"]),
    ])
    def test_invalid_events_rejected(self, main_module, call, body):
        assert call(main_module.strava_webhook, json=body).status == 400

    def test_other_subscriptions_ignored(self, main_module, call, db, monkeypatch):
        monkeypatch.setenv("STRAVA_SUBSCRIPTION_ID", "8")
        r = call(main_module.strava_webhook, json=event(owner=999_002))
        assert r.status == 200 and r.json["message"].startswith("Ignored")
        assert not list(db.collection("stravaEvents").get())

    def test_only_get_and_post(self, main_module, call):
        assert call(main_module.strava_webhook, method="PUT", json={}).status == 405


def test_unknown_update_fields_are_dropped():
    parsed = Webhook.parse_event(event(updates={"title": "x" * 300, "authorized": False, "evil": "1"}))
    assert parsed["updates"] == {"title": "x" * 200, "authorized": "False"}


# ------------------------------------------------------------------ processing

class TestImport:
    def test_new_activity_completes_the_planned_session_of_that_sport(self, rider, db, seed, strava):
        seed({"workouts/swim": make_workout_doc(UID, "2026-10-06", sport="swimming"),
              "workouts/ride": make_workout_doc(UID, "2026-10-06", sport="cycling")})
        strava.get(ACTIVITY_URL, json=activity())
        before = ctl(db)
        assert process(event()) == "completed_planned"
        ws = workouts(db)
        assert ws["ride"]["completed"] and ws["ride"]["completion_type"] == "strava"
        assert ws["ride"]["stravaId"] == "111" and ws["ride"]["actual_time"] == 3600
        assert ws["ride"]["actual_tss"] == pytest.approx(3600 * 200 * 0.8 / (250 * 3600) * 100, abs=0.1)
        assert ws["ride"]["stats"] == {"duration_seconds": 3600, "distance_m": 30000.0, "avg_power": 190.0,
                                       "normalized_power": 200.0, "avg_heart_rate": 140.0}
        assert not ws["swim"]["completed"]
        assert ctl(db) > before
        assert strava.request_history[-1].headers["Authorization"] == "Bearer acc"

    def test_morning_session_is_completed_first_on_a_double_day(self, rider, db, seed, strava):
        seed({"workouts/pm": make_workout_doc(UID, "2026-10-06", slot="pm"),
              "workouts/am": make_workout_doc(UID, "2026-10-06", slot="am")})
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        assert workouts(db)["am"]["completed"] and not workouts(db)["pm"]["completed"]

    def test_unplanned_activity_is_recorded(self, rider, db, strava):
        strava.get(ACTIVITY_URL, json=activity(sport_type="Run", average_watts=None, device_watts=False))
        assert process(event()) == "imported"
        doc = workouts(db)["strava_111"]
        assert doc["sport"] == "running" and doc["name"] == "Morning Ride" and doc["completed"]
        assert doc["actual_tss"] == pytest.approx(100 * (140 / 165) ** 2, abs=0.1)  # heart-rate TSS

    def test_retries_and_updates_never_double_count(self, rider, db, strava):
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        once = ctl(db)
        assert process(event()) == "updated"   # Strava retry of the same create
        assert ctl(db) == pytest.approx(once, abs=0.05)
        strava.get(ACTIVITY_URL, json=activity(moving=7200, name="Longer ride"))
        assert process(event(aspect="update")) == "updated"
        doc = workouts(db)["strava_111"]
        assert doc["actual_time"] == 7200 and doc["name"] == "Longer ride"
        assert ctl(db) > once

    def test_session_logged_by_fit_upload_is_linked_not_counted_again(self, rider, db, seed, strava):
        seed({"workouts/fit": make_workout_doc(UID, "2026-10-06", completed=True, status="completed",
                                               completion_type="fit_upload", actual_time=3500, actual_tss=70.0)})
        strava.get(ACTIVITY_URL, json=activity())
        before = ctl(db)
        assert process(event()) == "linked"
        assert workouts(db)["fit"]["stravaId"] == "111" and workouts(db)["fit"]["actual_tss"] == 70.0
        assert ctl(db) == before
        assert process(event(aspect="update")) == "unchanged"

    def test_ticked_off_session_takes_stravas_numbers(self, rider, db, seed, strava):
        seed({"workouts/tick": make_workout_doc(UID, "2026-10-06", completed=True, status="completed",
                                                completion_type="manual_toggle", actual_time=3600, actual_tss=50.0)})
        strava.get(ACTIVITY_URL, json=activity())
        assert process(event()) == "linked"
        doc = workouts(db)["tick"]
        assert doc["completion_type"] == "strava" and doc["actual_tss"] > 50.0

    def test_update_to_a_ticked_off_session_keeps_the_plan_name(self, rider, db, seed, strava):
        seed({"workouts/tick": make_workout_doc(UID, "2026-10-06", completed=True, status="completed",
                                                completion_type="manual_toggle", actual_time=3600, actual_tss=50.0)})
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        strava.get(ACTIVITY_URL, json=activity(moving=3900, name="Renamed on Strava"))
        assert process(event(aspect="update")) == "updated"
        doc = workouts(db)["tick"]
        assert doc["name"] == "Cycling Threshold Intervals" and doc["actual_time"] == 3900

    def test_run_with_a_power_meter_uses_running_power(self, rider, db, strava):
        db.document(f"users/{UID}").update({"ftpRunning": 300})
        strava.get(ACTIVITY_URL, json=activity(sport_type="TrailRun", weighted_average_watts=270.0))
        process(event())
        assert workouts(db)["strava_111"]["actual_tss"] == pytest.approx(100 * 0.9 ** 2, abs=0.1)

    def test_second_ride_of_the_day_is_its_own_session(self, rider, db, seed, strava):
        seed({"workouts/am": make_workout_doc(UID, "2026-10-06", completed=True, status="completed",
                                              completion_type="fit_upload", actual_time=1800, actual_tss=30.0)})
        strava.get(ACTIVITY_URL, json=activity(moving=7200))
        assert process(event()) == "imported"

    def test_strength_session_counts_no_endurance_load(self, rider, db, seed, strava):
        seed({"workouts/gym": make_workout_doc(UID, "2026-10-06", sport="strength")})
        strava.get(ACTIVITY_URL, json=activity(sport_type="WeightTraining"))
        before = ctl(db)
        assert process(event()) == "completed_planned"
        gym = workouts(db)["gym"]
        assert gym["actual_tss"] == 0.0 and ctl(db) == before
        assert set(gym["stats"]) == {"duration_seconds", "avg_heart_rate"}  # no distance, speed or power
        assert gym["steps"] == []  # the planned session's content is kept as it was

    @pytest.mark.parametrize("payload,outcome", [
        (activity(sport_type="Walk"), "ignored:unsupported_type"),
        (activity(start_date_local="soon"), "ignored:no_date"),
        (activity(moving=0, elapsed_time=0), "ignored:no_duration"),
        (activity(owner=1), "ignored:owner_mismatch"),
    ])
    def test_activities_that_are_skipped(self, rider, db, strava, payload, outcome):
        strava.get(ACTIVITY_URL, json=payload)
        assert process(event()) == outcome
        assert workouts(db) == {}


class TestDelete:
    def test_deleted_import_is_removed_and_its_load_taken_back(self, rider, db, strava):
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        assert ctl(db) > ctl_without_the_ride()
        strava.get(ACTIVITY_URL, status_code=404)
        assert process(event(aspect="delete")) == "removed"
        assert workouts(db) == {} and ctl(db) == pytest.approx(ctl_without_the_ride(), abs=0.05)
        assert process(event(aspect="delete")) == "ignored:not_imported"

    def test_deleted_activity_reopens_the_planned_session(self, rider, db, seed, strava):
        seed({"workouts/ride": make_workout_doc(UID, "2026-10-06")})
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        strava.get(ACTIVITY_URL, status_code=404)
        assert process(event(aspect="delete")) == "reopened"
        doc = workouts(db)["ride"]
        assert doc["status"] == "planned" and not doc["completed"] and "stravaId" not in doc

    def test_fit_upload_stays_when_its_strava_copy_is_deleted(self, rider, db, seed, strava):
        seed({"workouts/fit": make_workout_doc(UID, "2026-10-06", completed=True, status="completed",
                                               completion_type="fit_upload", actual_time=3600, actual_tss=70.0)})
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        strava.get(ACTIVITY_URL, status_code=404)
        assert process(event(aspect="delete")) == "unlinked"
        assert workouts(db)["fit"]["completed"] and "stravaId" not in workouts(db)["fit"]

    def test_spoofed_delete_is_ignored_while_strava_still_has_the_activity(self, rider, db, strava):
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        assert process(event(aspect="delete")) == "ignored:activity_still_exists"
        assert "strava_111" in workouts(db)

    def test_link_to_a_workout_the_athlete_deleted(self, rider, db, strava):
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        db.document("workouts/strava_111").delete()
        assert process(event(aspect="update")) == "imported"  # re-created
        db.document("workouts/strava_111").delete()
        strava.get(ACTIVITY_URL, status_code=404)
        assert process(event(aspect="delete")) == "removed"


class TestTokensAndAccounts:
    def test_expired_token_is_refreshed_and_stored(self, rider, db, strava):
        db.document(f"users/{UID}/private/strava").update({"expiresAt": time.time() - 10})
        strava.post(STRAVA_TOKEN_URL, json={"access_token": "new-acc", "refresh_token": "new-ref",
                                            "expires_at": int(time.time()) + 21600})
        strava.get(ACTIVITY_URL, json=activity())
        assert process(event()) == "imported"
        assert "grant_type=refresh_token" in strava.request_history[0].text
        assert strava.request_history[-1].headers["Authorization"] == "Bearer new-acc"
        stored = db.document(f"users/{UID}/private/strava").get().to_dict()
        assert stored["accessToken"] == "new-acc" and stored["refreshToken"] == "new-ref"

    def test_refresh_keeps_old_refresh_token_when_none_returned(self, rider, db, strava):
        db.document(f"users/{UID}/private/strava").update({"expiresAt": 0})
        strava.post(STRAVA_TOKEN_URL, json={"access_token": "new-acc", "expires_at": 1})
        strava.get(ACTIVITY_URL, json=activity())
        process(event())
        assert db.document(f"users/{UID}/private/strava").get().to_dict()["refreshToken"] == "ref"

    def test_incomplete_refresh_payload(self, rider, db, strava):
        db.document(f"users/{UID}/private/strava").update({"expiresAt": 0})
        strava.post(STRAVA_TOKEN_URL, json={"expires_at": 1})
        assert process(event()) == "failed:strava_bad_response"

    def test_unknown_athlete_and_missing_tokens(self, rider, db, seed):
        assert process(event(owner=1)) == "ignored:unknown_athlete"
        db.document(f"users/{UID}/private/strava").delete()
        assert process(event()) == "ignored:not_connected"
        seed({f"users/{UID}/private/strava": {"accessToken": "", "expiresAt": 0}})
        assert process(event()) == "ignored:not_connected"

    def test_invalid_queued_event(self):
        assert process({"object_type": "activity"}) == "ignored:invalid_event"

    def test_one_strava_account_linked_to_two_logins(self, rider, db, seed, strava):
        seed({"users/twin": make_profile_doc(stravaConnected=True, stravaAthleteId=str(ATHLETE)),
              "users/twin/private/strava": {"accessToken": "acc2", "refreshToken": "r2", "expiresAt": time.time() + 3600}})
        strava.get(ACTIVITY_URL, json=activity())
        assert process(event()) == "imported,imported"
        assert "strava_111" in workouts(db, "twin")

    @pytest.mark.parametrize("status,outcome", [(429, "failed:strava_rate_limited"), (401, "failed:strava_auth_rejected"),
                                                (500, "failed:strava_unavailable")])
    def test_strava_errors_are_recorded(self, rider, db, strava, status, outcome):
        strava.get(ACTIVITY_URL, status_code=status)
        assert process(event()) == outcome
        assert workouts(db) == {}

    def test_transient_error_is_retried_once(self, rider, db, strava):
        strava.get(ACTIVITY_URL, [{"exc": requests.ConnectTimeout}, {"json": activity()}])
        assert process(event()) == "imported"

    def test_network_failures(self, rider, strava):
        strava.get(ACTIVITY_URL, exc=requests.ConnectionError)
        assert process(event()) == "failed:strava_unreachable"
        strava.get(ACTIVITY_URL, exc=requests.ConnectTimeout)
        assert process(event()) == "failed:strava_timeout"

    @pytest.mark.parametrize("kwargs", [{"text": "not json"}, {"json": [1, 2]}])
    def test_bad_strava_responses(self, rider, strava, kwargs):
        strava.get(ACTIVITY_URL, **kwargs)
        assert process(event()) == "failed:strava_bad_response"

    def test_revocation_disconnects_once_strava_confirms(self, rider, db, strava):
        strava.post(STRAVA_TOKEN_URL, status_code=401)
        revoked = event(object_type="athlete", object_id=ATHLETE, aspect="update", updates={"authorized": "false"})
        assert process(revoked) == "disconnected"
        user = db.document(f"users/{UID}").get().to_dict()
        assert user["stravaConnected"] is False and "stravaAthleteId" not in user
        assert not db.document(f"users/{UID}/private/strava").get().exists

    def test_spoofed_revocation_is_ignored(self, rider, db, strava):
        strava.post(STRAVA_TOKEN_URL, json={"access_token": "still-ok", "refresh_token": "ref", "expires_at": 1})
        revoked = event(object_type="athlete", object_id=ATHLETE, aspect="update", updates={"authorized": "false"})
        assert process(revoked) == "ignored:still_authorized"
        assert db.document(f"users/{UID}").get().to_dict()["stravaConnected"] is True

    def test_revocation_check_fails_on_strava_outage(self, rider, db, strava):
        strava.post(STRAVA_TOKEN_URL, status_code=503)
        revoked = event(object_type="athlete", object_id=ATHLETE, aspect="update", updates={"authorized": "false"})
        assert process(revoked) == "failed:strava_unavailable"
        assert db.document(f"users/{UID}").get().to_dict()["stravaConnected"] is True

    def test_revocation_without_tokens_disconnects(self, rider, db):
        db.document(f"users/{UID}/private/strava").delete()
        revoked = event(object_type="athlete", object_id=ATHLETE, aspect="update", updates={"authorized": "false"})
        assert process(revoked) == "disconnected"

    def test_other_athlete_updates_ignored(self, rider):
        assert process(event(object_type="athlete", aspect="update", updates={"title": "x"})) == "ignored:athlete_update"


def test_trigger_records_the_outcome(main_module, rider, db, monkeypatch):
    """process_strava_event (the Firestore trigger body) writes the outcome back to the event."""
    # not under stravaEvents/, so the emulator's own trigger leaves it alone
    db.document("testEvents/manual").set({"placeholder": True})
    snap = db.document("testEvents/manual").get()
    trigger = main_module.process_strava_event.__wrapped__

    class FakeEvent:
        data = snap

    monkeypatch.setattr(main_module.StravaWebhookService, "process", classmethod(lambda cls, e, **kw: "imported"))
    trigger(FakeEvent())
    assert db.document("testEvents/manual").get().to_dict()["status"] == "imported"

    def boom(cls, e, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(main_module.StravaWebhookService, "process", classmethod(boom))
    trigger(FakeEvent())
    assert db.document("testEvents/manual").get().to_dict()["status"] == "failed:internal"

    class NoData:
        data = None

    trigger(NoData())  # deleted before delivery: nothing to do
