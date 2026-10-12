"""
Strava webhook: activities recorded on Strava complete the athlete's plan automatically.

Strava calls `strava_webhook` for every activity created, updated or deleted by a connected
athlete, and when an athlete revokes access. It must answer within 2 seconds, so the endpoint only
validates and queues the event (`stravaEvents/{key}`, one document per event, which also
de-duplicates Strava's retries). `process_strava_event` then handles it from a Firestore trigger.

Strava does not sign webhook calls, so an event is only a hint. Nothing is trusted from it:
- activities are always re-fetched from Strava with the athlete's own token (and must be theirs);
- a delete is applied only once Strava confirms the activity is gone;
- a revocation is applied only once Strava rejects the athlete's refresh token.

Each imported activity is linked to one workout via `stravaLinks/{uid}_{activityId}`. Reading
that link inside a transaction serialises concurrent events for the same activity, so an activity
is never imported twice. Load is applied as a TSS delta, so updates never double count.
"""

import datetime
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None
try:
    from firebase_admin import firestore
    from google.api_core import exceptions as gexc
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    firestore = None

from engine.physiology import PhysiologyEngine
from services.activity_stats import relevant_stats
from services.strava_service import HTTP_TIMEOUT_SEC, StravaError, StravaService, private_token_ref
from services.user_service import UserService

STRAVA_ACTIVITY_URL = "https://www.strava.com/api/v3/activities/{id}"
TOKEN_REFRESH_MARGIN_SEC = 300
EVENT_TTL_DAYS = 30
DUPLICATE_TOLERANCE = 0.25  # same day + sport + duration within 25% = the same session
TRANSIENT = {"strava_timeout", "strava_unreachable", "strava_unavailable"}

OBJECT_TYPES = {"activity", "athlete"}
ASPECT_TYPES = {"create", "update", "delete"}
KEPT_UPDATE_KEYS = {"title", "type", "sport_type", "private", "authorized"}

SPORT_TYPES = {
    "cycling": {"Ride", "VirtualRide", "EBikeRide", "EMountainBikeRide", "GravelRide", "MountainBikeRide",
                "Velomobile", "Handcycle"},
    "running": {"Run", "TrailRun", "VirtualRun"},
    "swimming": {"Swim"},
    "strength": {"WeightTraining", "Crossfit", "HighIntensityIntervalTraining"},
    "stretching": {"Yoga", "Pilates"},
}
NO_LOAD_SPORTS = {"strength", "stretching"}


def sport_for(activity: Dict[str, Any]) -> Optional[str]:
    kind = activity.get("sport_type") or activity.get("type")
    return next((sport for sport, kinds in SPORT_TYPES.items() if kind in kinds), None)


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def link_ref(db, user_id: str, activity_id: int):
    return db.collection("stravaLinks").document(f"{user_id}_{activity_id}")


class StravaWebhookService:

    # ------------------------------------------------------------------ intake (HTTP)

    @staticmethod
    def parse_event(body: Dict[str, Any]) -> Dict[str, Any]:
        """Validates a webhook payload and keeps only known fields. Raises ValueError."""
        if body.get("object_type") not in OBJECT_TYPES or body.get("aspect_type") not in ASPECT_TYPES:
            raise ValueError("Unknown event type")
        for key in ("object_id", "owner_id", "subscription_id", "event_time"):
            if not _positive_int(body.get(key)):
                raise ValueError(f"{key} must be a positive integer")
        updates = body.get("updates") or {}
        if not isinstance(updates, dict):
            raise ValueError("updates must be an object")
        return {
            "object_type": body["object_type"],
            "aspect_type": body["aspect_type"],
            "object_id": body["object_id"],
            "owner_id": body["owner_id"],
            "subscription_id": body["subscription_id"],
            "event_time": body["event_time"],
            "updates": {k: str(v)[:200] for k, v in updates.items() if k in KEPT_UPDATE_KEYS},
        }

    @staticmethod
    def event_key(event: Dict[str, Any]) -> str:
        return "{object_type}_{object_id}_{aspect_type}_{owner_id}_{event_time}".format(**event)

    @classmethod
    def enqueue(cls, event: Dict[str, Any]) -> bool:
        """Queues the event for processing. Returns False if it was already queued (a Strava retry)."""
        ref = firestore.client().collection("stravaEvents").document(cls.event_key(event))
        try:
            ref.create({
                **event,
                "status": "queued",
                "receivedAt": firestore.SERVER_TIMESTAMP,
                # optional Firestore TTL policy on this field cleans old events up
                "expireAt": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=EVENT_TTL_DAYS),
            })
        except gexc.AlreadyExists:
            return False
        return True

    # ------------------------------------------------------------------ processing (trigger)

    @classmethod
    def process(cls, event: Dict[str, Any], client_id: str, client_secret: str) -> str:
        """Handles one queued event for every account linked to the Strava athlete. Returns an outcome."""
        try:
            event = cls.parse_event(event)
        except ValueError:
            return "ignored:invalid_event"
        users = [snap.id for snap in firestore.client().collection("users")
                 .where(filter=FieldFilter("stravaAthleteId", "==", str(event["owner_id"]))).get()]
        if not users:
            return "ignored:unknown_athlete"
        return ",".join(cls._process_for_user(uid, event, client_id, client_secret) for uid in sorted(users))

    @classmethod
    def _process_for_user(cls, uid: str, event: Dict[str, Any], client_id: str, client_secret: str) -> str:
        if event["object_type"] == "athlete":
            if event["updates"].get("authorized") == "false":
                return cls._handle_revocation(uid, client_id, client_secret)
            return "ignored:athlete_update"
        try:
            token = cls.access_token(uid, client_id, client_secret)
            if token is None:
                return "ignored:not_connected"
            try:
                activity = cls._with_retry(lambda: cls.fetch_activity(token, event["object_id"]))
            except StravaError as exc:
                if exc.code == "strava_not_found":
                    return cls.remove(uid, event["object_id"])
                raise
        except StravaError as exc:
            return f"failed:{exc.code}"
        if event["aspect_type"] == "delete":
            return "ignored:activity_still_exists"  # not really deleted: a spoofed or stale event
        if str((activity.get("athlete") or {}).get("id")) != str(event["owner_id"]):
            return "ignored:owner_mismatch"
        return cls.upsert(uid, activity)

    @staticmethod
    def _with_retry(fn, attempts: int = 2, delay_sec: float = 2.0):
        for attempt in range(attempts):
            try:
                return fn()
            except StravaError as exc:
                if exc.code not in TRANSIENT or attempt == attempts - 1:
                    raise
                time.sleep(delay_sec)

    # ------------------------------------------------------------------ Strava API

    @staticmethod
    def access_token(uid: str, client_id: str, client_secret: str, force_refresh: bool = False) -> Optional[str]:
        """A valid access token for the athlete, refreshed (and stored) when it is about to expire."""
        ref = private_token_ref(firestore.client(), uid)
        snap = ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        expires_at = data.get("expiresAt") or 0
        if not force_refresh and data.get("accessToken") and float(expires_at) > time.time() + TOKEN_REFRESH_MARGIN_SEC:
            return data["accessToken"]
        if not data.get("refreshToken"):
            return None
        fresh = StravaService._post_token({
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": data["refreshToken"],
        })
        if not fresh.get("access_token"):
            raise StravaError("strava_bad_response", "refresh payload incomplete")
        ref.update({
            "accessToken": fresh["access_token"],
            "refreshToken": fresh.get("refresh_token") or data["refreshToken"],
            "expiresAt": fresh.get("expires_at"),
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        return fresh["access_token"]

    @staticmethod
    def fetch_activity(token: str, activity_id: int) -> Dict[str, Any]:
        try:
            resp = requests.get(STRAVA_ACTIVITY_URL.format(id=activity_id),
                                headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT_SEC)
        except requests.Timeout as exc:
            raise StravaError("strava_timeout") from exc
        except requests.RequestException as exc:
            raise StravaError("strava_unreachable") from exc
        if resp.status_code == 404:
            raise StravaError("strava_not_found")
        if resp.status_code == 429:
            raise StravaError("strava_rate_limited")
        if resp.status_code in (401, 403):
            raise StravaError("strava_auth_rejected", f"HTTP {resp.status_code}")
        if not resp.ok:
            raise StravaError("strava_unavailable", f"HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise StravaError("strava_bad_response", "non-JSON body") from exc
        if not isinstance(body, dict):
            raise StravaError("strava_bad_response", "unexpected JSON shape")
        return body

    @classmethod
    def _handle_revocation(cls, uid: str, client_id: str, client_secret: str) -> str:
        """The athlete revoked access on Strava. Confirmed by Strava rejecting their refresh token."""
        try:
            if cls.access_token(uid, client_id, client_secret, force_refresh=True) is not None:
                return "ignored:still_authorized"
        except StravaError as exc:
            if exc.code != "strava_auth_rejected":
                return f"failed:{exc.code}"
        db = firestore.client()
        private_token_ref(db, uid).delete()
        db.collection("users").document(uid).set(
            {"stravaConnected": False, "stravaAthleteId": firestore.DELETE_FIELD}, merge=True)
        return "disconnected"

    # ------------------------------------------------------------------ workouts

    @staticmethod
    def activity_tss(activity: Dict[str, Any], sport: str, profile) -> float:
        if sport in NO_LOAD_SPORTS:
            return 0.0
        duration = int(activity.get("moving_time") or activity.get("elapsed_time") or 0)
        measured_power = bool(activity.get("device_watts"))
        np_power = float(activity.get("weighted_average_watts") or 0) if measured_power else 0.0
        avg_power = float(activity.get("average_watts") or 0) if measured_power else 0.0
        threshold = 0.0
        if profile is not None and sport in ("cycling", "running"):
            threshold = profile.ftp_running if sport == "running" else (profile.ftp_cycling or profile.ftp)
        use_power = threshold > 0 and (np_power > 0 or avg_power > 0)
        return PhysiologyEngine.calculate_actual_tss(
            sport=sport, duration_sec=duration,
            avg_power=avg_power if use_power else 0, normalized_power=np_power if use_power else 0,
            ftp=threshold if use_power else 200.0,
            avg_hr=float(activity.get("average_heartrate") or 0),
            fthr=profile.fthr if profile is not None else 170.0,
        )

    @staticmethod
    def _same_session(data: Dict[str, Any], duration: int) -> bool:
        done = float(data.get("actual_time") or data.get("time") or 0)
        return done > 0 and abs(done - duration) <= DUPLICATE_TOLERANCE * max(done, duration)

    @classmethod
    def upsert(cls, uid: str, activity: Dict[str, Any]) -> str:
        """Imports or re-syncs one Strava activity into the athlete's workouts."""
        sport = sport_for(activity)
        if sport is None:
            return "ignored:unsupported_type"
        try:
            date = datetime.date.fromisoformat(str(activity.get("start_date_local") or "")[:10]).isoformat()
        except ValueError:
            return "ignored:no_date"
        duration = int(activity.get("moving_time") or activity.get("elapsed_time") or 0)
        if duration <= 0:
            return "ignored:no_duration"
        activity_id = int(activity["id"])
        tss = cls.activity_tss(activity, sport, UserService.get_user_profile(uid))
        completion = {
            "completed": True,
            "status": "completed",
            "completedAt": firestore.SERVER_TIMESTAMP,
            "actual_time": duration,
            "actual_tss": tss,
            "stats": relevant_stats(sport, {
                "duration_seconds": duration,
                "distance_m": activity.get("distance"),
                "avg_speed_ms": activity.get("average_speed"),
                "elevation_m": activity.get("total_elevation_gain"),
                # power only when a power meter measured it (Strava estimates it otherwise)
                "avg_power": activity.get("average_watts") if activity.get("device_watts") else None,
                "normalized_power": activity.get("weighted_average_watts") if activity.get("device_watts") else None,
                "avg_heart_rate": activity.get("average_heartrate"),
                "max_heart_rate": activity.get("max_heartrate"),
                "avg_cadence": activity.get("average_cadence"),
                "calories": activity.get("calories"),
            }),
            "completion_type": "strava",
            "stravaId": str(activity_id),
            "source": "strava",
        }
        db = firestore.client()
        workouts = db.collection("workouts")
        link = link_ref(db, uid, activity_id)

        @firestore.transactional
        def _apply(tx) -> Tuple[str, float, str]:
            link_snap = link.get(transaction=tx)
            if link_snap.exists:
                ref = workouts.document((link_snap.to_dict() or {}).get("workoutId", ""))
                snap = ref.get(transaction=tx)
                if snap.exists:
                    data = snap.to_dict() or {}
                    if data.get("completion_type") == "fit_upload":
                        return "unchanged", 0.0, data.get("date") or date  # the athlete's own file wins
                    previous = float(data.get("actual_tss") or 0) if data.get("completed") else 0.0
                    update = dict(completion)
                    if ref.id == f"strava_{activity_id}":
                        update.update(name=activity.get("name") or "Strava activity", sport=sport, date=date,
                                      time=duration, tss=tss)
                    tx.update(ref, update)
                    return "updated", tss - previous, data.get("date") or date
            same_day: List[Any] = list(tx.get(workouts.where(filter=FieldFilter("userId", "==", uid))
                                              .where(filter=FieldFilter("date", "==", date))))
            mine = [s for s in same_day if (s.to_dict() or {}).get("sport") == sport]
            done = [s for s in mine if (s.to_dict() or {}).get("completed") and not (s.to_dict() or {}).get("stravaId")
                    and cls._same_session(s.to_dict() or {}, duration)]
            planned = sorted((s for s in mine if not (s.to_dict() or {}).get("completed")
                              and (s.to_dict() or {}).get("type") not in ("Goal", "Event")),
                             key=lambda s: ((s.to_dict() or {}).get("slot") == "pm", s.id))
            if done:  # already logged by FIT upload or by ticking it off: one session, counted once
                target, data = done[0].reference, done[0].to_dict() or {}
                if data.get("completion_type") == "fit_upload":
                    tx.update(target, {"stravaId": str(activity_id)})
                    outcome, delta = "linked", 0.0
                else:
                    tx.update(target, completion)
                    outcome, delta = "linked", tss - float(data.get("actual_tss") or 0)
            elif planned:
                target = planned[0].reference
                tx.update(target, completion)
                outcome, delta = "completed_planned", tss
            else:
                target = workouts.document(f"strava_{activity_id}")
                tx.set(target, {
                    "workoutId": target.id, "userId": uid, "date": date, "sport": sport,
                    "name": activity.get("name") or "Strava activity", "description": "", "intensity": 2,
                    "time": duration, "tss": tss, "type": "Session", "createdAt": firestore.SERVER_TIMESTAMP,
                    **completion,
                })
                outcome, delta = "imported", tss
            tx.set(link, {"userId": uid, "activityId": activity_id, "workoutId": target.id,
                          "createdAt": firestore.SERVER_TIMESTAMP})
            return outcome, delta, date

        outcome, delta, load_date = _apply(db.transaction())
        delta = round(delta, 1)
        if delta:
            UserService.apply_completed_session(uid, load_date, delta)
        return outcome

    @classmethod
    def remove(cls, uid: str, activity_id: int) -> str:
        """The activity no longer exists on Strava: undo what importing it did."""
        db = firestore.client()
        link = link_ref(db, uid, activity_id)

        @firestore.transactional
        def _apply(tx) -> Tuple[str, float, Optional[str]]:
            link_snap = link.get(transaction=tx)
            if not link_snap.exists:
                return "ignored:not_imported", 0.0, None
            ref = db.collection("workouts").document((link_snap.to_dict() or {}).get("workoutId", ""))
            snap = ref.get(transaction=tx)
            tx.delete(link)
            if not snap.exists:
                return "removed", 0.0, None
            data = snap.to_dict() or {}
            counted = float(data.get("actual_tss") or 0) if data.get("completion_type") == "strava" else 0.0
            if ref.id == f"strava_{activity_id}":
                tx.delete(ref)
                return "removed", -counted, data.get("date")
            if data.get("completion_type") == "strava":
                tx.update(ref, {
                    "completed": False, "status": "planned", "completedAt": None,
                    **{k: firestore.DELETE_FIELD for k in ("actual_time", "actual_tss", "stats", "completion_type",
                                                          "stravaId", "source")},
                })
                return "reopened", -counted, data.get("date")
            tx.update(ref, {"stravaId": firestore.DELETE_FIELD})  # the athlete's own record stays
            return "unlinked", 0.0, data.get("date")

        outcome, delta, load_date = _apply(db.transaction())
        delta = round(delta, 1)
        if delta and load_date:
            UserService.apply_completed_session(uid, load_date, delta)
        return outcome
