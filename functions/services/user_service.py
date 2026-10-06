"""
User Profile Service.
Fetches, normalizes, and updates athlete profile documents in Firestore.
"""

import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, Dict, Any, List, Tuple
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None
from core.models import UserProfile, Goal
from core.config import EQUIPMENT_MAPPING
from engine.physiology import PhysiologyEngine
from services.profile_validator import ProfileValidator




def _num(raw: Dict[str, Any], key: str, default: float) -> float:
    """Reads a numeric field, falling back to `default` when missing or malformed."""
    try:
        value = float(raw.get(key, default))
    except (TypeError, ValueError):
        return float(default)
    return value if value == value else float(default)  # NaN guard


def _hours_map(raw: Any) -> Dict[str, float]:
    """Keeps only entries whose value is a valid number of hours (0-24)."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            hours = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= hours <= 24.0:
            out[str(key)] = hours
    return out


_THRESHOLD_FIELDS = {
    "cycling_power": ("ftpCycling", "ftp"),
    "running_power": ("ftpRunning",),
    "running_pace": ("ftpPaceRunning",),
    "swim_pace": ("ftpPaceSwimming",),
    "hr": ("fthr",),
}


def _known_thresholds(raw: Dict[str, Any]) -> List[str]:
    """Thresholds the athlete actually has; defaults must never be passed off as their numbers."""
    known = []
    for key, fields in _THRESHOLD_FIELDS.items():
        for f in fields:
            try:
                if raw.get(f) is not None and float(raw[f]) > 0:
                    known.append(key)
                    break
            except (TypeError, ValueError):
                continue
    return known


class UserService:
    """
    Handles Firestore user document retrieval and fitness state persistence.
    """

    @classmethod
    def get_user_profile(cls, user_id: str) -> Optional[UserProfile]:
        """
        Fetches user profile from Firestore and normalizes into a UserProfile dataclass.
        """
        # Database errors propagate: they must surface as a 500, not as "profile not found".
        db = firestore.client()
        doc_snap = db.collection("users").document(user_id).get()
        if not doc_snap.exists:
            return None

        raw_data = doc_snap.to_dict() or {}
        return cls.normalize_user_profile(user_id, raw_data)

    @classmethod
    def normalize_user_profile(cls, user_id: str, raw_data: Dict[str, Any]) -> UserProfile:
        """
        Converts raw Firestore dictionary into strongly-typed UserProfile.
        """
        # 1. Normalize Equipment
        raw_equipment = raw_data.get("equipment", [])
        if not isinstance(raw_equipment, list):
            raw_equipment = []
        equipment_toggles = raw_data.get("equipmentToggles", {})
        if not isinstance(equipment_toggles, dict):
            equipment_toggles = {}
        combined_equipment_keys = {e for e in raw_equipment if isinstance(e, str)}
        for eq_k, enabled in equipment_toggles.items():
            if enabled:
                combined_equipment_keys.add(eq_k)

        normalized_equipment = ["bodyweight"]
        for key in combined_equipment_keys:
            if key in EQUIPMENT_MAPPING:
                normalized_equipment.extend(EQUIPMENT_MAPPING[key])
            else:
                normalized_equipment.append(key)
        normalized_equipment = sorted(list(set(normalized_equipment)))

        # 2. Sports & Focus
        activities = raw_data.get("activities", {})
        main_focus = raw_data.get("mainFocus", {})
        sports = raw_data.get("sports", ["cycling", "running"])
        focused_sports = raw_data.get("focused_sports", ["cycling"])
        if not focused_sports and sports:
            focused_sports = [sports[0]]

        # 3. Daily Available Hours & Max Limits
        daily_max_hours = raw_data.get("dailyMaxHours", {
            "Monday": 1.5,
            "Tuesday": 1.5,
            "Wednesday": 1.5,
            "Thursday": 1.5,
            "Friday": 1.5,
            "Saturday": 2.5,
            "Sunday": 2.5
        })
        daily_hours_overrides = raw_data.get("dailyHoursOverrides", {})
        daily_max_hours = _hours_map(daily_max_hours)
        daily_hours_overrides = _hours_map(daily_hours_overrides)
        if not isinstance(sports, list):
            sports = ["cycling", "running"]
        if not isinstance(focused_sports, list):
            focused_sports = sports[:1]
        if not isinstance(activities, dict):
            activities = {}
        if not isinstance(main_focus, dict):
            main_focus = {}

        # 4. Parse Goal
        raw_goal = raw_data.get("goal")
        goal_obj = None
        if raw_goal and isinstance(raw_goal, dict):
            goal_obj = Goal(
                name=raw_goal.get("name", "Target Event"),
                date=raw_goal.get("date"),
                type=raw_goal.get("type", "event"),
                sports=raw_goal.get("sports", focused_sports),
                target_distance=_num(raw_goal, "targetDistance", 0.0) or None,
                target_distance_unit=raw_goal.get("targetDistanceUnit"),
                target_time=int(_num(raw_goal, "targetTime", 0)) or None,
                target_time_string=raw_goal.get("targetTimeString"),
                target_pace=raw_goal.get("targetPace"),
                notes=raw_goal.get("notes")
            )

        return UserProfile(
            uid=user_id,
            display_name=raw_data.get("displayName"),
            units=raw_data.get("units", "Metric"),
            main_focus=main_focus,
            activities=activities,
            equipment_toggles=equipment_toggles,
            training_goal_type=raw_data.get("trainingGoalType", "General Fitness"),
            sport_percentages=raw_data.get("sportPercentages", {}),
            sport_sessions_per_week=raw_data.get("sportSessionsPerWeek", {}),
            wizard_completed=bool(raw_data.get("wizardCompleted", False)),
            ctl=_num(raw_data, "ctl", 40.0),
            atl=_num(raw_data, "atl", 30.0),
            weekly_hours=_num(raw_data, "weekly_hours", _num(raw_data, "weeklyHours", 8.0)),
            daily_available_hours=_num(raw_data, "daily_available_hours", 1.5),
            sports=sports,
            focused_sports=focused_sports,
            equipment=normalized_equipment,
            intensity_weeks=int(_num(raw_data, "intensity_weeks", 3)),
            injury=int(_num(raw_data, "injury", 0)),
            illness=int(_num(raw_data, "illness", 0)),
            recovery_metric=int(_num(raw_data, "recovery_metric", 3)),
            interval_type=raw_data.get("intervalType", raw_data.get("interval_type", "structured")),
            ftp=_num(raw_data, "ftp", 200.0),
            ftp_cycling=_num(raw_data, "ftpCycling", _num(raw_data, "ftp", 200.0)),
            ftp_running=_num(raw_data, "ftpRunning", 250.0),
            ftp_pace_running=_num(raw_data, "ftpPaceRunning", 330.0),
            ftp_pace_swimming=_num(raw_data, "ftpPaceSwimming", 110.0),
            fthr=_num(raw_data, "fthr", 170.0),
            daily_max_hours=daily_max_hours,
            daily_hours_overrides=daily_hours_overrides,
            goal=goal_obj,
            fitness_level=str(raw_data.get("fitness_level") or raw_data.get("fitnessLevel") or "intermediate"),
            metrics_date=raw_data.get("metricsDate"),
            timezone=raw_data.get("timezone"),
            known_thresholds=_known_thresholds(raw_data),
            history=raw_data.get("history", {}),
            raw_data=raw_data
        )

    @classmethod
    def validate_and_save_profile(
        cls,
        user_id: str,
        profile_data: Dict[str, Any],
        is_partial: bool = False
    ) -> Tuple[bool, List[str], Optional[UserProfile]]:
        """
        Validates profile data using ProfileValidator and saves to Firestore.
        """
        is_valid, errors, normalized_data = ProfileValidator.validate(profile_data, is_partial=is_partial)
        if not is_valid:
            return False, errors, None

        # Database errors propagate to the handler (500); they are not validation failures.
        db = firestore.client()
        db.collection("users").document(user_id).set(normalized_data, merge=True)
        return True, [], cls.get_user_profile(user_id)

    @classmethod
    def update_user_fitness(
        cls,
        user_id: str,
        new_ctl: float,
        new_atl: float,
        new_ftp: Optional[float] = None,
        metrics_date: Optional[str] = None
    ):
        """
        Persists updated CTL, ATL (as of `metrics_date`) and FTP back to the user's document.
        """
        db = firestore.client()
        payload = {
            "ctl": round(new_ctl, 2),
            "atl": round(new_atl, 2),
            "lastMetricsUpdate": firestore.SERVER_TIMESTAMP
        }
        if metrics_date is not None:
            payload["metricsDate"] = metrics_date
        if new_ftp is not None:
            payload["ftp"] = round(new_ftp, 1)
            payload["ftpCycling"] = round(new_ftp, 1)

        db.collection("users").document(user_id).update(payload)
        print(f"[UserService] Updated fitness for {user_id}: CTL={new_ctl:.1f}, ATL={new_atl:.1f}")

    @classmethod
    def apply_completed_session(
        cls,
        user_id: str,
        session_date: str,
        tss: float,
        new_ftp: Optional[float] = None
    ):
        """Adds a completed session's TSS to the athlete's CTL/ATL, honouring idle-day decay."""
        profile = cls.get_user_profile(user_id)
        if not profile:
            return
        metrics_date = None
        if profile.metrics_date:
            try:
                metrics_date = datetime.datetime.strptime(profile.metrics_date, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                metrics_date = None
        session_day = datetime.datetime.strptime(session_date, "%Y-%m-%d").date()
        new_ctl, new_atl, new_date = PhysiologyEngine.apply_session_load(
            profile.ctl, profile.atl, metrics_date, session_day, tss
        )
        cls.update_user_fitness(user_id, new_ctl, new_atl, new_ftp=new_ftp, metrics_date=new_date.isoformat())

    @staticmethod
    def today_for(profile: Optional[UserProfile]) -> datetime.date:
        """The athlete's local calendar date (UTC if no valid time zone is stored)."""
        tz = None
        if profile and profile.timezone:
            try:
                tz = ZoneInfo(profile.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                tz = None
        return datetime.datetime.now(tz or datetime.timezone.utc).date()

