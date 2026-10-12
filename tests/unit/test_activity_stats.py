import pytest

from services.activity_stats import exercise_name, logged_set, relevant_stats

RAW = {"duration_seconds": 3600, "distance_m": 30000, "avg_speed_ms": 8.3, "elevation_m": 300, "avg_power": 210,
       "normalized_power": 225, "avg_heart_rate": 140, "max_heart_rate": 172, "avg_cadence": 88, "calories": 900}


@pytest.mark.parametrize("sport,expected", [
    ("cycling", set(RAW)),
    ("running", set(RAW) - {"normalized_power"}),
    ("swimming", {"duration_seconds", "distance_m", "avg_heart_rate", "max_heart_rate", "calories"}),
    ("strength", {"duration_seconds", "avg_heart_rate", "max_heart_rate", "calories"}),
    ("stretching", {"duration_seconds", "avg_heart_rate", "max_heart_rate", "calories"}),
])
def test_only_relevant_stats_per_sport(sport, expected):
    assert set(relevant_stats(sport, RAW)) == expected


def test_missing_zero_and_bad_values_are_dropped():
    assert relevant_stats("cycling", {"distance_m": 0, "avg_power": None, "avg_heart_rate": True,
                                      "calories": "9", "duration_seconds": 61.26}) == {"duration_seconds": 61.3}


@pytest.mark.parametrize("category,name", [
    ("deadlift", "Deadlift"), (["unknown", "bench_press"], "Bench Press"), ("new_thing", "New Thing"),
    ("unknown", "Exercise"), (None, "Exercise"), ([None], "Exercise"),
])
def test_exercise_names(category, name):
    assert exercise_name(category) == name


def test_logged_set():
    sets = [logged_set("squat", 8, 60.25, 35.4), logged_set("plank", None, None, 45), logged_set("row", 10, 0, None)]
    assert sets == [{"exercise": "Squat", "reps": 8, "weight_kg": 60.2, "duration_sec": 35},
                    {"exercise": "Plank", "duration_sec": 45}, {"exercise": "Row", "reps": 10}]
