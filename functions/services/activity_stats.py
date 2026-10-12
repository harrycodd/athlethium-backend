"""
Which recorded stats are worth keeping for each sport, and readable names for strength exercises.

Both completion paths (FIT upload and the Strava webhook) store `stats` through `relevant_stats`,
so a strength session never carries a distance or speed, and empty values are dropped rather than
shown as zero.
"""

from typing import Any, Dict, Optional

from i18n import t

SPORT_STATS = {
    "cycling": ("duration_seconds", "distance_m", "avg_speed_ms", "elevation_m", "avg_power", "normalized_power",
                "avg_heart_rate", "max_heart_rate", "avg_cadence", "calories"),
    "running": ("duration_seconds", "distance_m", "avg_speed_ms", "elevation_m", "avg_power",
                "avg_heart_rate", "max_heart_rate", "avg_cadence", "calories"),
    "swimming": ("duration_seconds", "distance_m", "avg_heart_rate", "max_heart_rate", "calories"),
}
NON_ENDURANCE_STATS = ("duration_seconds", "avg_heart_rate", "max_heart_rate", "calories")

# FIT exercise categories with a readable name for the athlete (messages: fitExercise.<category>)
EXERCISE_CATEGORIES = (
    "bench_press", "calf_raise", "carry", "chop", "core", "crunch", "curl", "deadlift", "flye", "hip_raise",
    "hip_stability", "hip_swing", "hyperextension", "lateral_raise", "leg_curl", "leg_raise", "lunge",
    "olympic_lift", "plank", "plyo", "pull_up", "push_up", "row", "shoulder_press", "shoulder_stability", "shrug",
    "sit_up", "squat", "total_body", "triceps_extension", "warm_up", "cardio", "run",
)


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


def exercise_name(category: Any, lang: str = "en") -> str:
    """FIT `exercise_category` (a name, or a list of names) -> a readable exercise name in `lang`."""
    if isinstance(category, (list, tuple)):
        category = next((c for c in category if c not in (None, "unknown")), None)
    if not isinstance(category, str) or category == "unknown":
        return t(lang, "fitExercise.unknown")
    if category in EXERCISE_CATEGORIES:
        return t(lang, f"fitExercise.{category}")
    return category.replace("_", " ").title()  # a category we have no name for: shown as recorded


def logged_set(category: Any, reps: Any, weight_kg: Any, duration_sec: Any, lang: str = "en") -> Dict[str, Any]:
    """One logged strength set, in the shape the app reads and writes (`logged_sets` on a workout)."""
    entry: Dict[str, Any] = {"exercise": exercise_name(category, lang)}
    if _number(reps) is not None:
        entry["reps"] = int(reps)
    if _number(weight_kg) is not None:
        entry["weight_kg"] = round(float(weight_kg), 1)
    if _number(duration_sec) is not None:
        entry["duration_sec"] = int(round(float(duration_sec)))
    return entry

