import pytest

from core.models import TargetType, WorkoutStep
from generators.endurance import EnduranceGenerator as E
from generators.mobility import MobilityGenerator
from generators.strength import StrengthGenerator


def total(workout):
    return sum(s["duration"] for s in workout["steps"])


class TestEndurance:
    @pytest.mark.parametrize("intensity", [0, 1, 2, 3, 4, 5, 6, 7])
    @pytest.mark.parametrize("hours", [0.5, 1.0, 1.5, 3.0])
    def test_steps_sum_to_duration(self, intensity, hours):
        w = E.generate("cycling", hours, intensity)
        assert total(w) == w["total_duration_sec"] == int(hours * 3600)
        assert all(s["duration"] > 0 for s in w["steps"])

    def test_minimum_twenty_minutes(self):
        assert E.generate("running", 0.1, 2)["total_duration_sec"] == 1200

    def test_sprint_session_ends_with_cooldown_not_a_long_sprint(self):
        steps = E.generate("cycling", 1.5, 7)["steps"]
        sprints = [s for s in steps if s["type"] == "interval"]
        assert all(s["duration"] == 15 for s in sprints)
        assert steps[-1]["type"] == "cooldown"

    @pytest.mark.parametrize("sport,equipment,expected", [
        ("cycling", None, "power"),
        ("cycling", ["power_meter"], "power"),
        ("running", ["running_power"], "power"),
        ("running", ["hr_monitor"], "heart_rate"),
        ("cycling", ["heart_rate"], "heart_rate"),
        ("running", ["bodyweight"], "power"),
        ("swimming", ["swim_watch"], "pace"),
        ("swimming", [], "time"),
        ("rowing", [], "power"),
    ])
    def test_target_type(self, sport, equipment, expected):
        assert E.generate(sport, 1.0, 2, equipment)["targetType"] == expected

    def test_interval_style_selects_description(self):
        w = E.generate("cycling", 1.0, 2, interval_style="mix")
        assert w["description"] == w["descriptions"]["mix"]
        w = E.generate("cycling", 1.0, 2, interval_style="unknown")
        assert w["description"] == w["descriptions"]["structured"]

    def test_tempo_long_and_short_blocks(self):
        long_blocks = [s for s in E.generate("cycling", 1.5, 3)["steps"] if s["type"] == "interval"]
        short_blocks = [s for s in E.generate("cycling", 0.75, 3)["steps"] if s["type"] == "interval"]
        assert {s["duration"] for s in long_blocks} == {900}
        assert {s["duration"] for s in short_blocks} == {600}

    def test_vo2_microbursts_vs_repeats(self):
        long_w = [s for s in E.generate("cycling", 1.5, 5)["steps"] if s["type"] == "interval"]
        short_w = [s for s in E.generate("cycling", 0.75, 5)["steps"] if s["type"] == "interval"]
        assert len(long_w) == 12 and {s["duration"] for s in long_w} == {30}
        assert len(short_w) == 4 and {s["duration"] for s in short_w} == {150}

    @pytest.mark.parametrize("sport,marker", [
        ("cycling", "FTP"), ("running", "Threshold Pace"), ("swimming", "CSS"), ("rowing", "Baseline"),
    ])
    def test_benchmarks(self, sport, marker):
        w = E.generate_benchmark_workout(sport, 1.25)
        assert marker in w["name"]
        assert total(w) == w["total_duration_sec"] == 4500

    def test_benchmark_minimum_forty_minutes(self):
        assert E.generate_benchmark_workout("cycling", 0.5)["total_duration_sec"] == 2400

    def test_normalize_handles_empty_and_floors_last_step(self):
        E._normalize_step_durations([], 100)
        steps = [WorkoutStep("warmup", 100), WorkoutStep("cooldown", 100)]
        E._normalize_step_durations(steps, 120)
        assert steps[-1].duration == 60
        steps = [WorkoutStep("warmup", 100)]
        E._normalize_step_durations(steps, 100)
        assert steps[0].duration == 100

    def test_step_to_dict_optional_fields(self):
        d = WorkoutStep("exercise", 60, "Squat", target_type=TargetType.REPS.value, reps=10, sets=3, notes="n").to_dict()
        assert d == {"type": "exercise", "duration": 60, "name": "Squat", "targetType": "reps",
                     "reps": 10, "sets": 3, "notes": "n"}


class TestStrength:
    def test_defaults_and_duration(self):
        w = StrengthGenerator.generate()
        assert w["total_duration_sec"] == 2700
        assert w["steps"][0]["type"] == "warmup" and w["steps"][-1]["type"] == "cooldown"

    @pytest.mark.parametrize("focus,key", [("legs", "Legs"), ("all", "All"), ("upper", "Upper"), ("weird", "Weird")])
    def test_focus_aliases(self, focus, key):
        assert StrengthGenerator.generate(focus, 40, 2, ["bodyweight"])["name"].startswith(key)

    def test_exercise_count_bounds(self):
        short = StrengthGenerator.generate("full", 16, 1, ["bodyweight"])
        long = StrengthGenerator.generate("full", 120, 3, ["dumbbells"])
        assert len([s for s in short["steps"] if s["type"] == "exercise"]) == 3
        assert len([s for s in long["steps"] if s["type"] == "exercise"]) == 6

    def test_pool_fallback_when_nothing_matches(self, monkeypatch):
        monkeypatch.setitem(StrengthGenerator.EXERCISES, "core", [{"name": "Rings", "equip": ["rings"], "sets": 1, "reps": 1}])
        w = StrengthGenerator.generate("core", 45, 2, ["bands"])
        names = [s["name"] for s in w["steps"] if s["type"] == "exercise"]
        assert "Rings" not in names and names


class TestMobility:
    @pytest.mark.parametrize("focus,title", [("full", "Athletic Full Body"), ("legs", "Lower"), ("core", "Core"),
                                             ("full_body", "Athletic Full Body"), ("nope", "Nope")])
    def test_titles(self, focus, title):
        assert MobilityGenerator.generate(focus, 20)["name"].startswith(title)

    def test_duration_is_filled_exactly(self):
        for minutes in [5, 20, 60]:
            w = MobilityGenerator.generate("upper", minutes)
            assert total(w) == minutes * 60

    def test_zero_minutes(self):
        assert MobilityGenerator.generate("full", 0)["steps"] == []
