"""
Workout Completion Service.
Handles manual workout completion, FIT file parsing, actual TSS calculation,
and automatic FTP detection.
"""

import datetime
import uuid
from typing import Dict, Any, Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
try:
    from firebase_admin import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    firestore = None
from engine.physiology import PhysiologyEngine
from services.user_service import UserService


try:
    import fitparse
except ImportError:
    fitparse = None


NON_ENDURANCE_SPORTS = {"strength", "stretching", "yoga", "rest"}
FIT_SPORTS = {"cycling": "cycling", "running": "running", "swimming": "swimming",
              "training": "strength", "walking": "running"}


class WorkoutNotFound(Exception):
    """The workout does not exist or belongs to another user (deliberately indistinguishable)."""


class FitFileError(Exception):
    """The uploaded file could not be parsed as a FIT activity."""


def _is_completed(data: Dict[str, Any]) -> bool:
    return bool(data.get("completed")) or data.get("status") == "completed"


def _local_date(start_time: Optional[datetime.datetime], timezone: Optional[str]) -> datetime.date:
    """FIT timestamps are UTC; the session belongs to the athlete's local calendar day."""
    tz: Any = datetime.timezone.utc
    if timezone:
        try:
            tz = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = datetime.timezone.utc
    if start_time is None:
        return datetime.datetime.now(tz).date()
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=datetime.timezone.utc)
    return start_time.astimezone(tz).date()


class WorkoutCompleterService:
    """
    Processes workout completions (manual or via FIT files) and updates athlete fitness.
    """

    @classmethod
    def _get_owned_workout(cls, db, user_id: str, workout_id: str):
        ref = db.collection("workouts").document(workout_id)
        snap = ref.get()
        if not snap.exists:
            raise WorkoutNotFound(workout_id)
        data = snap.to_dict() or {}
        if data.get("userId") != user_id:
            raise WorkoutNotFound(workout_id)
        return ref, data

    @staticmethod
    def manual_tss(workout_data: Dict[str, Any], actual_time_sec: int, rpe: Optional[int]) -> float:
        """Planned TSS scaled to the time actually done; RPE estimate if nothing was planned."""
        sport = str(workout_data.get("sport", "cycling")).lower()
        if sport in NON_ENDURANCE_SPORTS:
            return 0.0
        planned_tss = float(workout_data.get("plannedTss") or workout_data.get("planned_tss")
                            or workout_data.get("tss") or 0.0)
        planned_time = float(workout_data.get("plannedTime") or workout_data.get("time") or 0.0)
        if planned_tss > 0 and planned_time > 0:
            return round(planned_tss * (actual_time_sec / planned_time), 1)
        return PhysiologyEngine.calculate_actual_tss(sport=sport, duration_sec=actual_time_sec, rpe=rpe)

    @classmethod
    def complete_manual(
        cls,
        user_id: str,
        workout_id: str,
        actual_time_sec: int,
        rpe: Optional[int] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Completes the caller's workout and updates CTL/ATL. Re-completing the same workout
        only applies the change in TSS, so load is never double counted.
        """
        db = firestore.client()
        workout_ref, workout_data = cls._get_owned_workout(db, user_id, workout_id)

        actual_tss = cls.manual_tss(workout_data, actual_time_sec, rpe)
        previous_tss = float(workout_data.get("actual_tss") or 0.0) if _is_completed(workout_data) else 0.0

        workout_ref.update({
            "completed": True,
            "status": "completed",
            "completedAt": firestore.SERVER_TIMESTAMP,
            "actual_time": actual_time_sec,
            "actual_tss": actual_tss,
            "rpe": rpe,
            "userNotes": notes,
            "completion_type": "manual"
        })

        delta = round(actual_tss - previous_tss, 1)
        if delta and workout_data.get("date"):
            UserService.apply_completed_session(user_id, workout_data["date"], delta)

        return {
            "workoutId": workout_id,
            "actual_time": actual_time_sec,
            "actual_tss": actual_tss,
            "status": "completed"
        }

    @staticmethod
    def parse_fit(fit_file_path: str) -> Dict[str, Any]:
        """Extracts sport, start time, duration and 1 Hz power/HR samples from a FIT file."""
        if not fitparse:
            raise FitFileError("fitparse module is not available")
        try:
            fitfile = fitparse.FitFile(fit_file_path)
            power: List[float] = []
            hr: List[float] = []
            start_time = None
            for record in fitfile.get_messages("record"):
                values = record.get_values()
                if values.get("timestamp") and not start_time:
                    start_time = values["timestamp"]
                if values.get("power") is not None:
                    power.append(float(values["power"]))
                if values.get("heart_rate") is not None:
                    hr.append(float(values["heart_rate"]))

            total_time_sec = 0
            sport = None
            for session in fitfile.get_messages("session"):
                s_vals = session.get_values()
                if s_vals.get("total_timer_time"):
                    total_time_sec = int(s_vals["total_timer_time"])
                elif s_vals.get("total_elapsed_time"):
                    total_time_sec = int(s_vals["total_elapsed_time"])
                if s_vals.get("start_time") and not start_time:
                    start_time = s_vals["start_time"]
                if s_vals.get("sport"):
                    sport = FIT_SPORTS.get(str(s_vals["sport"]).lower())
        except Exception as exc:
            raise FitFileError(f"Could not read FIT file: {exc}") from exc

        if total_time_sec <= 0:
            total_time_sec = len(power) or len(hr)
        if total_time_sec <= 0:
            raise FitFileError("FIT file contains no activity data")
        return {"sport": sport, "start_time": start_time, "duration_sec": total_time_sec, "power": power, "hr": hr}

    @classmethod
    def complete_with_fit(
        cls,
        user_id: str,
        fit_file_path: str,
        workout_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses a .fit file, computes TSS for the right sport, checks for a cycling FTP increase,
        and completes the matching planned workout (or records a new activity).
        """
        parsed = cls.parse_fit(fit_file_path)
        db = firestore.client()
        user_profile = UserService.get_user_profile(user_id)

        target_ref = None
        target_data: Dict[str, Any] = {}
        if workout_id:
            target_ref, target_data = cls._get_owned_workout(db, user_id, workout_id)

        date_str = _local_date(parsed["start_time"], user_profile.timezone if user_profile else None).isoformat()
        sport = parsed["sport"] or str(target_data.get("sport") or "cycling")
        if sport in NON_ENDURANCE_SPORTS:
            sport = "cycling" if parsed["power"] else "running"

        power, hr = parsed["power"], parsed["hr"]
        avg_power = sum(power) / len(power) if power else 0.0
        avg_hr = sum(hr) / len(hr) if hr else 0.0
        np_power = PhysiologyEngine.normalized_power(power)

        if sport == "running":
            threshold_power = user_profile.ftp_running if user_profile else 250.0
        else:
            threshold_power = (user_profile.ftp_cycling or user_profile.ftp) if user_profile else 200.0
        fthr = user_profile.fthr if user_profile else 170.0
        use_power = sport in ("cycling", "running") and avg_power > 0

        actual_tss = PhysiologyEngine.calculate_actual_tss(
            sport=sport,
            duration_sec=parsed["duration_sec"],
            avg_power=avg_power if use_power else 0,
            normalized_power=np_power if use_power else 0,
            ftp=threshold_power,
            avg_hr=avg_hr,
            fthr=fthr
        )

        # Auto-FTP (cycling only): best 20-minute power x 0.95
        suggested_new_ftp = None
        if sport == "cycling" and len(power) >= 1200:
            rolling_sum = sum(power[:1200])
            max_20m = rolling_sum
            for i in range(1200, len(power)):
                rolling_sum += power[i] - power[i - 1200]
                max_20m = max(max_20m, rolling_sum)
            potential_ftp = round(max_20m / 1200.0 * 0.95, 1)
            if potential_ftp > threshold_power + 2.0:
                suggested_new_ftp = potential_ftp

        if target_ref is None:
            target_ref, target_data = cls._match_planned_workout(db, user_id, date_str, sport)

        stats_dict = {
            "avg_power": round(avg_power, 1),
            "normalized_power": round(np_power, 1),
            "avg_heart_rate": round(avg_hr, 1),
            "duration_seconds": parsed["duration_sec"]
        }
        completion = {
            "completed": True,
            "status": "completed",
            "completedAt": firestore.SERVER_TIMESTAMP,
            "actual_time": parsed["duration_sec"],
            "actual_tss": actual_tss,
            "stats": stats_dict,
            "completion_type": "fit_upload"
        }

        previous_tss = 0.0
        if target_ref is not None:
            if _is_completed(target_data):
                previous_tss = float(target_data.get("actual_tss") or 0.0)
            target_ref.update(completion)
            final_workout_id = target_ref.id
            session_date = target_data.get("date") or date_str
        else:
            final_workout_id = str(uuid.uuid4())
            db.collection("workouts").document(final_workout_id).set({
                "workoutId": final_workout_id,
                "userId": user_id,
                "date": date_str,
                "name": "Recorded Activity",
                "sport": sport,
                "intensity": 2,
                "time": parsed["duration_sec"],
                "tss": actual_tss,
                "createdAt": firestore.SERVER_TIMESTAMP,
                **completion
            })
            session_date = date_str

        delta = round(actual_tss - previous_tss, 1)
        if user_profile and (delta or suggested_new_ftp):
            UserService.apply_completed_session(user_id, session_date, delta, new_ftp=suggested_new_ftp)

        return {
            "workout_id": final_workout_id,
            "sport": sport,
            "date": session_date,
            "actual_time": parsed["duration_sec"],
            "actual_tss": actual_tss,
            "stats": stats_dict,
            "new_ftp": suggested_new_ftp
        }

    @staticmethod
    def _match_planned_workout(db, user_id: str, date_str: str, sport: str):
        """Prefers an uncompleted planned session of the same sport that day, then any uncompleted one."""
        snaps = db.collection("workouts") \
                  .where(filter=FieldFilter("userId", "==", user_id)) \
                  .where(filter=FieldFilter("date", "==", date_str)) \
                  .get()
        open_sessions = [s for s in snaps if not _is_completed(s.to_dict() or {})]
        same_sport = [s for s in open_sessions if (s.to_dict() or {}).get("sport") == sport]
        chosen = (same_sport or open_sessions or [None])[0]
        if chosen is None:
            return None, {}
        return chosen.reference, chosen.to_dict() or {}
