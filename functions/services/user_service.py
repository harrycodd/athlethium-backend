"""
User Profile Service.
Fetches, normalizes, and updates athlete profile documents in Firestore.
"""

import datetime
from typing import Optional, Dict, Any, List, Tuple
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None
from core.models import UserProfile, Goal
from core.config import EQUIPMENT_MAPPING
from services.profile_validator import ProfileValidator




class UserService:
    """
    Handles Firestore user document retrieval and fitness state persistence.
    """

    @classmethod
    def get_user_profile(cls, user_id: str) -> Optional[UserProfile]:
        """
        Fetches user profile from Firestore and normalizes into a UserProfile dataclass.
        """
        try:
            db = firestore.client()
            doc_snap = db.collection("users").document(user_id).get()
            if not doc_snap.exists:
                return None

            raw_data = doc_snap.to_dict() or {}
            return cls.normalize_user_profile(user_id, raw_data)
        except Exception as e:
            print(f"[UserService] Error fetching user profile {user_id}: {str(e)}")
            return None

    @classmethod
    def normalize_user_profile(cls, user_id: str, raw_data: Dict[str, Any]) -> UserProfile:
        """
        Converts raw Firestore dictionary into strongly-typed UserProfile.
        """
        # 1. Normalize Equipment
        raw_equipment = raw_data.get("equipment", [])
        equipment_toggles = raw_data.get("equipmentToggles", {})
        combined_equipment_keys = set(raw_equipment)
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

        # 4. Parse Goal
        raw_goal = raw_data.get("goal")
        goal_obj = None
        if raw_goal and isinstance(raw_goal, dict):
            goal_obj = Goal(
                name=raw_goal.get("name", "Target Event"),
                date=raw_goal.get("date"),
                type=raw_goal.get("type", "event"),
                sports=raw_goal.get("sports", focused_sports),
                target_distance=float(raw_goal["targetDistance"]) if raw_goal.get("targetDistance") is not None else None,
                target_distance_unit=raw_goal.get("targetDistanceUnit"),
                target_time=int(raw_goal["targetTime"]) if raw_goal.get("targetTime") is not None else None,
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
            ctl=float(raw_data.get("ctl", 40.0)),
            atl=float(raw_data.get("atl", 30.0)),
            weekly_hours=float(raw_data.get("weekly_hours", raw_data.get("weeklyHours", 8.0))),
            daily_available_hours=float(raw_data.get("daily_available_hours", 1.5)),
            sports=sports,
            focused_sports=focused_sports,
            equipment=normalized_equipment,
            intensity_weeks=int(raw_data.get("intensity_weeks", 3)),
            injury=int(raw_data.get("injury", 0)),
            illness=int(raw_data.get("illness", 0)),
            recovery_metric=int(raw_data.get("recovery_metric", 3)),
            interval_type=raw_data.get("intervalType", raw_data.get("interval_type", "structured")),
            ftp=float(raw_data.get("ftp", 200.0)),
            ftp_cycling=float(raw_data.get("ftpCycling", raw_data.get("ftp", 200.0))),
            ftp_running=float(raw_data.get("ftpRunning", 250.0)),
            ftp_pace_running=float(raw_data.get("ftpPaceRunning", 330.0)),
            ftp_pace_swimming=float(raw_data.get("ftpPaceSwimming", 110.0)),
            fthr=float(raw_data.get("fthr", 170.0)),
            daily_max_hours=daily_max_hours,
            daily_hours_overrides=daily_hours_overrides,
            goal=goal_obj,
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

        try:
            db = firestore.client()
            user_doc_ref = db.collection("users").document(user_id)
            user_doc_ref.set(normalized_data, merge=True)
            saved_profile = cls.get_user_profile(user_id)
            return True, [], saved_profile
        except Exception as e:
            print(f"[UserService] Error saving user profile for {user_id}: {str(e)}")
            return False, [f"Database error saving profile: {str(e)}"], None

    @classmethod
    def update_user_fitness(
        cls,
        user_id: str,
        new_ctl: float,
        new_atl: float,
        new_ftp: Optional[float] = None
    ):
        """
        Persists updated CTL, ATL, and FTP back to the user's Firestore document.
        """
        try:
            db = firestore.client()
            payload = {
                "ctl": round(new_ctl, 2),
                "atl": round(new_atl, 2),
                "lastMetricsUpdate": firestore.SERVER_TIMESTAMP
            }
            if new_ftp is not None:
                payload["ftp"] = round(new_ftp, 1)
                payload["ftpCycling"] = round(new_ftp, 1)

            db.collection("users").document(user_id).update(payload)
            print(f"[UserService] Updated fitness for {user_id}: CTL={new_ctl:.1f}, ATL={new_atl:.1f}")
        except Exception as e:
            print(f"[UserService] Error updating fitness metrics for {user_id}: {str(e)}")

