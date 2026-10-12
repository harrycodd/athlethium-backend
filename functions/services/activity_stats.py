"""
Which recorded stats are worth keeping for each sport, and readable names for strength exercises.

Both completion paths (FIT upload and the Strava webhook) store `stats` through `relevant_stats`,
so a strength session never carries a distance or speed, and empty values are dropped rather than
shown as zero.
"""

from typing import Any, Dict, Optional

SPORT_STATS = {
    "cycling": ("duration_seconds", "distance_m", "avg_speed_ms", "elevation_m", "avg_power", "normalized_power",
                "avg_heart_rate", "max_heart_rate", "avg_cadence", "calories"),
    "running": ("duration_seconds", "distance_m", "avg_speed_ms", "elevation_m", "avg_power",
                "avg_heart_rate", "max_heart_rate", "avg_cadence", "calories"),
    "swimming": ("duration_seconds", "distance_m", "avg_heart_rate", "max_heart_rate", "calories"),
}
NON_ENDURANCE_STATS = ("duration_seconds", "avg_heart_rate", "max_heart_rate", "calories")

# FIT exercise categories -> names shown to the athlete
EXERCISE_NAMES = {
    "bench_press": "Bench Press", "calf_raise": "Calf Raise", "carry": "Loaded Carry", "chop": "Cable Chop",
    "core": "Core", "crunch": "Crunch", "curl": "Biceps Curl", "deadlift": "Deadlift", "flye": "Chest Fly",
    "hip_raise": "Hip Raise / Glute Bridge", "hip_stability": "Hip Stability", "hip_swing": "Kettlebell Swing",
    "hyperextension": "Back Extension", "lateral_raise": "Lateral Raise", "leg_curl": "Leg Curl",
    "leg_raise": "Leg Raise", "lunge": "Lunge", "olympic_lift": "Olympic Lift", "plank": "Plank",
    "plyo": "Plyometrics", "pull_up": "Pull-Up", "push_up": "Push-Up", "row": "Row",
    "shoulder_press": "Shoulder Press", "shoulder_stability": "Shoulder Stability", "shrug": "Shrug",
    "sit_up": "Sit-Up", "squat": "Squat", "total_body": "Full Body", "triceps_extension": "Triceps Extension",
    "warm_up": "Warm-up", "cardio": "Cardio", "run": "Run",
}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return round(float(value), 1)


def relevant_stats(sport: str, raw: Dict[str, Any]) -> Dict[str, float]:
    """Keeps only the stats that mean something for `sport`, dropping missing and zero values."""
    keys = SPORT_STATS.get(sport, NON_ENDURANCE_STATS)
    out = {}
    for key in keys:
        value = _number(raw.get(key))
        if value is not None:
            out[key] = value
    return out


def exercise_name(category: Any) -> str:
    """FIT `exercise_category` (a name, or a list of names) -> a readable exercise name."""
    if isinstance(category, (list, tuple)):
        category = next((c for c in category if c not in (None, "unknown")), None)
    if not isinstance(category, str) or category == "unknown":
        return "Exercise"
    return EXERCISE_NAMES.get(category, category.replace("_", " ").title())


def logged_set(category: Any, reps: Any, weight_kg: Any, duration_sec: Any) -> Dict[str, Any]:
    """One logged strength set, in the shape the app reads and writes (`logged_sets` on a workout)."""
    entry: Dict[str, Any] = {"exercise": exercise_name(category)}
    if _number(reps) is not None:
        entry["reps"] = int(reps)
    if _number(weight_kg) is not None:
        entry["weight_kg"] = round(float(weight_kg), 1)
    if _number(duration_sec) is not None:
        entry["duration_sec"] = int(round(float(duration_sec)))
    return entry

