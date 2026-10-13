"""
Athlete Profile and Setup Wizard Data Validator.
Enforces strict server-side validation rules matching the frontend setup wizard.
"""

import re
import datetime
from typing import Dict, Any, List, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from core.config import SUPPORTED_SPORTS, SUPPORTED_UNITS, DAYS_OF_WEEK, EQUIPMENT_MAPPING
from i18n import SUPPORTED as SUPPORTED_LANGUAGES

# key -> (min, max, is_integer)
NUMERIC_FIELDS = {
    "ctl": (0, 250, False),
    "atl": (0, 400, False),
    "ftp": (30, 700, False),
    "ftpCycling": (30, 700, False),
    "ftpRunning": (30, 700, False),
    "ftpPaceRunning": (120, 900, False),   # sec/km
    "ftpPaceSwimming": (50, 300, False),   # sec/100m
    "fthr": (80, 230, False),
    "injury": (0, 2, True),
    "illness": (0, 2, True),
    "recovery_metric": (1, 3, True),
    "intensity_weeks": (1, 6, True),
}
INTERVAL_TYPES = {"structured", "mix", "non_structured", "non-structured"}
FITNESS_LEVELS = {"beginner", "intermediate", "advanced", "elite", "pro"}
BODY_AREAS = ("core", "upper", "lower", "all")  # goal.bodyArea: strength/mobility focus


class ProfileValidator:
    """
    Validates athlete profile data payloads from HTTP endpoints and setup wizard.
    """

    @classmethod
    def validate(cls, data: Dict[str, Any], is_partial: bool = False) -> Tuple[bool, List[str], Dict[str, Any]]:
        """
        Validates profile data.
        Returns:
            (is_valid: bool, errors: List[str], normalized_data: Dict[str, Any])
        """
        errors: List[str] = []
        normalized: Dict[str, Any] = {}

        if not isinstance(data, dict):
            return False, ["Payload must be a JSON object"], {}

        # 1. Athlete Display Name (Step 1)
        if "displayName" in data or not is_partial:
            display_name = data.get("displayName")
            if display_name is None or not isinstance(display_name, str) or not display_name.strip():
                errors.append("displayName is required and cannot be empty")
            elif len(display_name.strip()) > 100:
                errors.append("displayName cannot exceed 100 characters")
            else:
                normalized["displayName"] = display_name.strip()

        # 2. Measurement Units (Step 2)
        if "units" in data or not is_partial:
            units = data.get("units", "Metric")
            if units not in SUPPORTED_UNITS:
                errors.append(f"units must be one of {SUPPORTED_UNITS}, received '{units}'")
            else:
                normalized["units"] = units

        # Language of generated workout text. Optional: a profile without it gets English, and a
        # full save without it keeps whatever language is already stored.
        if "language" in data:
            language = data.get("language")
            if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
                errors.append(f"language must be one of {list(SUPPORTED_LANGUAGES)}, received '{language}'")
            else:
                normalized["language"] = language

        # 3. Weekly Hours (Step 2)
        weekly_hours = None
        if "weekly_hours" in data or "weeklyHours" in data or not is_partial:
            raw_hours = data.get("weekly_hours", data.get("weeklyHours", 7))
            try:
                weekly_hours = float(raw_hours)
                if weekly_hours < 1.0 or weekly_hours > 30.0:
                    errors.append(f"weekly_hours must be between 1 and 30 hours/week, received {weekly_hours}")
                else:
                    normalized["weekly_hours"] = weekly_hours
            except (ValueError, TypeError):
                errors.append("weekly_hours must be a valid number")

        # 4. Activities & Sports (Step 3)
        activities = data.get("activities", {})
        active_sports: List[str] = []

        if isinstance(activities, dict) and activities:
            for sport, enabled in activities.items():
                if sport in SUPPORTED_SPORTS and enabled:
                    active_sports.append(sport)
            normalized["activities"] = {s: bool(activities.get(s, False)) for s in SUPPORTED_SPORTS}
        elif "sports" in data and isinstance(data["sports"], list):
            active_sports = [s for s in data["sports"] if s in SUPPORTED_SPORTS]
            normalized["activities"] = {s: (s in active_sports) for s in SUPPORTED_SPORTS}
        elif not is_partial:
            active_sports = ["running", "cycling"]
            normalized["activities"] = {s: (s in active_sports) for s in SUPPORTED_SPORTS}

        if not is_partial and len(active_sports) == 0:
            errors.append("At least one active sport must be selected")
        normalized["sports"] = active_sports

        # 5. Main Focus & Focused Sports (Step 3)
        main_focus = data.get("mainFocus", {})
        focused_sports: List[str] = []

        if isinstance(main_focus, dict) and main_focus:
            for sport, enabled in main_focus.items():
                if sport in SUPPORTED_SPORTS and enabled:
                    if sport not in active_sports:
                        errors.append(f"Main focus sport '{sport}' must be enabled in active activities")
                    else:
                        focused_sports.append(sport)
            normalized["mainFocus"] = {s: bool(main_focus.get(s, False)) for s in SUPPORTED_SPORTS}
        elif "focused_sports" in data and isinstance(data["focused_sports"], list):
            for s in data["focused_sports"]:
                if s in SUPPORTED_SPORTS:
                    if s not in active_sports:
                        errors.append(f"Focused sport '{s}' must be an active sport")
                    else:
                        focused_sports.append(s)
            normalized["mainFocus"] = {s: (s in focused_sports) for s in SUPPORTED_SPORTS}
        elif not is_partial:
            focused_sports = [active_sports[0]] if active_sports else ["running"]
            normalized["mainFocus"] = {s: (s in focused_sports) for s in SUPPORTED_SPORTS}

        if not is_partial and len(focused_sports) == 0 and len(active_sports) > 0:
            errors.append("At least one main focus sport must be selected from active sports")
        normalized["focused_sports"] = focused_sports

        # 6. Training Goal Type (Step 4)
        if "trainingGoalType" in data or not is_partial:
            training_goal_type = data.get("trainingGoalType", "General Fitness")
            if not isinstance(training_goal_type, str) or not training_goal_type.strip():
                errors.append("trainingGoalType cannot be empty")
            else:
                normalized["trainingGoalType"] = training_goal_type.strip()

        # 7. Goal Milestone / Target (Step 5)
        raw_goal = data.get("goal")
        if raw_goal is not None:
            if not isinstance(raw_goal, dict):
                errors.append("goal must be an object")
            else:
                goal_errors, normalized_goal = cls._validate_goal(raw_goal, focused_sports)
                errors.extend(goal_errors)
                normalized["goal"] = normalized_goal
        elif not is_partial:
            # Generate default fallback goal
            default_sport = focused_sports[0] if focused_sports else "running"
            target_date = (datetime.date.today() + datetime.timedelta(weeks=12)).strftime("%Y-%m-%d")
            normalized["goal"] = {
                "name": f"{normalized.get('trainingGoalType', 'General Fitness')} Target",
                "type": "Goal",
                "date": target_date,
                "sports": [default_sport]
            }

        # 8. Sport Time Allocation & Session Frequency (Step 6)
        raw_percentages = data.get("sportPercentages")
        if raw_percentages is not None:
            if not isinstance(raw_percentages, dict):
                errors.append("sportPercentages must be a map of sport name to percentage")
            else:
                pct_sum = 0
                normalized_pcts = {}
                for sport in SUPPORTED_SPORTS:
                    if sport in raw_percentages:
                        try:
                            val = float(raw_percentages[sport])
                            if val < 0 or val > 100:
                                errors.append(f"Sport percentage for '{sport}' must be between 0 and 100")
                            normalized_pcts[sport] = val
                            if sport in active_sports:
                                pct_sum += val
                        except (ValueError, TypeError):
                            errors.append(f"Invalid percentage value for sport '{sport}'")
                    else:
                        normalized_pcts[sport] = 0.0

                if active_sports and (pct_sum < 95 or pct_sum > 105):
                    errors.append(f"Active sport percentages must sum to 100% (currently {pct_sum:.1f}%)")
                normalized["sportPercentages"] = normalized_pcts

        raw_sessions = data.get("sportSessionsPerWeek")
        if raw_sessions is not None:
            if not isinstance(raw_sessions, dict):
                errors.append("sportSessionsPerWeek must be a map of sport name to sessions per week")
            else:
                normalized_sessions = {}
                for sport in SUPPORTED_SPORTS:
                    if sport in raw_sessions:
                        try:
                            sess = int(raw_sessions[sport])
                            if sport in active_sports and (sess < 1 or sess > 14):
                                errors.append(f"Weekly sessions for '{sport}' must be between 1 and 14")
                            normalized_sessions[sport] = sess
                        except (ValueError, TypeError):
                            errors.append(f"Invalid weekly session count for sport '{sport}'")
                    else:
                        normalized_sessions[sport] = 1 if sport in active_sports else 0
                normalized["sportSessionsPerWeek"] = normalized_sessions

        # 9. Daily Availability Limits & Capacity Constraint (Step 7)
        raw_daily_max = data.get("dailyMaxHours")
        if raw_daily_max is not None or not is_partial:
            daily_max_hours = raw_daily_max if isinstance(raw_daily_max, dict) else {
                "Monday": 1.5,
                "Tuesday": 1.5,
                "Wednesday": 1.5,
                "Thursday": 1.5,
                "Friday": 1.5,
                "Saturday": 2.0,
                "Sunday": 2.0,
            }

            normalized_daily: Dict[str, float] = {}
            total_capacity = 0.0

            for day in DAYS_OF_WEEK:
                if day in daily_max_hours:
                    try:
                        h = float(daily_max_hours[day])
                        if h < 0.0 or h > 8.0:
                            errors.append(f"Daily hours for '{day}' must be between 0.0 and 8.0 hours")
                        normalized_daily[day] = round(h, 2)
                        total_capacity += h
                    except (ValueError, TypeError):
                        errors.append(f"Invalid hours format for day '{day}'")
                else:
                    normalized_daily[day] = 1.5
                    total_capacity += 1.5

            check_weekly_hours = weekly_hours or normalized.get("weekly_hours", 7.0)
            if round(total_capacity, 1) < round(check_weekly_hours, 1):
                errors.append(
                    f"Total weekly availability capacity ({total_capacity:.1f}h) cannot be less than target weekly hours ({check_weekly_hours:.1f}h)"
                )
            normalized["dailyMaxHours"] = normalized_daily

        # 10. Equipment Toggles & Normalized Equipment List (Step 8)
        raw_eq_toggles = data.get("equipmentToggles")
        if raw_eq_toggles is not None and isinstance(raw_eq_toggles, dict):
            normalized["equipmentToggles"] = {k: bool(v) for k, v in raw_eq_toggles.items()}

            # Normalize to backend equipment array
            normalized_eq = ["bodyweight"]
            for eq_k, enabled in raw_eq_toggles.items():
                if enabled:
                    if eq_k in EQUIPMENT_MAPPING:
                        normalized_eq.extend(EQUIPMENT_MAPPING[eq_k])
                    else:
                        normalized_eq.append(eq_k)
            normalized["equipment"] = sorted(list(set(normalized_eq)))
        elif "equipment" in data and isinstance(data["equipment"], list):
            normalized["equipment"] = data["equipment"]

        # 11. Wizard Completed Flag
        if "wizardCompleted" in data:
            normalized["wizardCompleted"] = bool(data["wizardCompleted"])
        elif not is_partial:
            normalized["wizardCompleted"] = True

        # Typed, range-checked optional fields (previously copied through unchecked)
        for key, (low, high, as_int) in NUMERIC_FIELDS.items():
            if key in data:
                value = data[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(f"{key} must be a number")
                elif not (low <= value <= high) or value != value:
                    errors.append(f"{key} must be between {low} and {high}")
                else:
                    normalized[key] = int(value) if as_int else float(value)

        if "intervalType" in data:
            if data["intervalType"] not in INTERVAL_TYPES:
                errors.append(f"intervalType must be one of {sorted(INTERVAL_TYPES)}")
            else:
                normalized["intervalType"] = data["intervalType"]

        if "fitness_level" in data:
            if data["fitness_level"] not in FITNESS_LEVELS:
                errors.append(f"fitness_level must be one of {sorted(FITNESS_LEVELS)}")
            else:
                normalized["fitness_level"] = data["fitness_level"]

        if "timezone" in data:
            tz = data["timezone"]
            try:
                if not isinstance(tz, str) or not tz:
                    raise ValueError
                ZoneInfo(tz)
                normalized["timezone"] = tz
            except (ValueError, ZoneInfoNotFoundError):
                errors.append("timezone must be a valid IANA time zone, e.g. 'Europe/London'")

        if "dailyHoursOverrides" in data:
            overrides = data["dailyHoursOverrides"]
            if not isinstance(overrides, dict):
                errors.append("dailyHoursOverrides must be a map of YYYY-MM-DD to hours")
            else:
                clean: Dict[str, float] = {}
                for date_key, hours in overrides.items():
                    try:
                        datetime.datetime.strptime(str(date_key), "%Y-%m-%d")
                        h = float(hours)
                        if not 0.0 <= h <= 8.0:
                            raise ValueError
                        clean[str(date_key)] = h
                    except (TypeError, ValueError):
                        errors.append(f"Invalid daily hours override '{date_key}'")
                normalized["dailyHoursOverrides"] = clean

        if "history" in data:
            if not isinstance(data["history"], dict):
                errors.append("history must be an object")
            else:
                normalized["history"] = data["history"]

        return len(errors) == 0, errors, normalized

    @classmethod
    def _validate_goal(cls, goal_data: Dict[str, Any], focused_sports: List[str]) -> Tuple[List[str], Dict[str, Any]]:
        errors: List[str] = []
        normalized_goal: Dict[str, Any] = {}

        # Name
        name = goal_data.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            errors.append("Goal name is required")
        else:
            normalized_goal["name"] = name.strip()

        # Date
        date_str = goal_data.get("date")
        if not date_str or not isinstance(date_str, str):
            errors.append("Goal date is required (YYYY-MM-DD)")
        else:
            try:
                datetime.datetime.strptime(date_str, "%Y-%m-%d")
                normalized_goal["date"] = date_str
            except ValueError:
                errors.append("Goal date must be in YYYY-MM-DD format")

        # Type
        normalized_goal["type"] = goal_data.get("type", "Goal")

        # Sports
        goal_sports = goal_data.get("sports", [])
        if isinstance(goal_sports, str):
            goal_sports = [goal_sports]
        if not isinstance(goal_sports, list) or len(goal_sports) == 0:
            errors.append("Goal must specify at least one sport")
        else:
            normalized_goal["sports"] = goal_sports
            for s in goal_sports:
                if focused_sports and s not in focused_sports:
                    errors.append(f"Goal sport '{s}' must be one of the athlete's main focused sports: {focused_sports}")

        # Optional Target Distance
        if "targetDistance" in goal_data and goal_data["targetDistance"] is not None:
            try:
                dist = float(goal_data["targetDistance"])
                if dist <= 0:
                    errors.append("Goal targetDistance must be greater than 0")
                else:
                    normalized_goal["targetDistance"] = dist
            except (ValueError, TypeError):
                errors.append("Goal targetDistance must be a valid number")

        if "targetDistanceUnit" in goal_data and goal_data["targetDistanceUnit"]:
            normalized_goal["targetDistanceUnit"] = str(goal_data["targetDistanceUnit"])

        # Optional Target Time (seconds)
        if "targetTime" in goal_data and goal_data["targetTime"] is not None:
            try:
                t = int(goal_data["targetTime"])
                if t <= 0:
                    errors.append("Goal targetTime must be greater than 0")
                else:
                    normalized_goal["targetTime"] = t
            except (ValueError, TypeError):
                errors.append("Goal targetTime must be a valid integer")

        # Optional Target Time String (HH:MM:SS)
        if "targetTimeString" in goal_data and goal_data["targetTimeString"]:
            time_str = str(goal_data["targetTimeString"]).strip()
            if not re.match(r"^\d{2}:\d{2}:\d{2}$", time_str):
                errors.append("Goal targetTimeString must be in HH:MM:SS format")
            else:
                normalized_goal["targetTimeString"] = time_str

        # Target Pace & Notes
        if "targetPace" in goal_data and goal_data["targetPace"]:
            normalized_goal["targetPace"] = str(goal_data["targetPace"]).strip()

        if "notes" in goal_data and goal_data["notes"]:
            normalized_goal["notes"] = str(goal_data["notes"]).strip()

        if goal_data.get("bodyArea") is not None:
            if goal_data["bodyArea"] in BODY_AREAS:
                normalized_goal["bodyArea"] = goal_data["bodyArea"]
            else:
                errors.append(f"goal.bodyArea must be one of {BODY_AREAS}, received '{goal_data['bodyArea']}'")

        return errors, normalized_goal
