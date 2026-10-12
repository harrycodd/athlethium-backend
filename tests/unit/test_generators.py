import datetime

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
        ("running", ["bodyweight"], "pace"),
        ("running", ["power_meter"], "pace"),
        ("cycling", ["running_power"], "power"),
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

    @staticmethod
    def efforts(workout, marker):
        return [s for s in workout["steps"] if s["type"] == "interval" and s["name"].startswith(marker)]

    @pytest.mark.parametrize("level,progression,expected", [
        (0, 0, (3, 480)), (0, 1, (3, 600)), (1, 1, (4, 600)), (2, 1, (3, 720)), (4, 2, (2, 1200)),
    ])
    def test_bike_threshold_progresses_with_level_and_block_week(self, level, progression, expected):
        w = E.generate("cycling", 1.75, 4, level=level, progression=progression)
        work = self.efforts(w, "Threshold")
        assert (len(work), work[0]["duration"]) == expected
        assert w["name"] == f"Bike Threshold: {expected[0]} × {expected[1] // 60} min"
        assert all((s["target_low"], s["target_high"]) == (96, 102) for s in work)

    def test_run_threshold_is_cruise_intervals_with_short_recoveries(self):
        w = E.generate("running", 1.0, 4, level=1, progression=0)
        assert w["name"] == "Run Threshold: 5 × 6 min"
        recoveries = [s for s in w["steps"] if s["type"] == "recovery"]
        assert {s["duration"] for s in recoveries} == {90}

    @pytest.mark.parametrize("sport,level,expected", [("cycling", 0, (5, 180)), ("cycling", 3, (4, 300)),
                                                      ("running", 2, (5, 240)), ("rowing", 0, (5, 180))])
    def test_vo2_sets(self, sport, level, expected):
        work = self.efforts(E.generate(sport, 1.5, 5, level=level), "VO2max")
        assert (len(work), work[0]["duration"]) == expected

    def test_a_short_session_gets_fewer_reps_not_a_longer_session(self):
        w = E.generate("cycling", 40 / 60, 4, level=4, progression=2)
        assert total(w) == 2400 and len(self.efforts(w, "Threshold")) >= 2

    def test_a_tiny_session_shortens_the_efforts(self):
        w = E.generate("cycling", 20 / 60, 4, level=2)
        work = self.efforts(w, "Threshold")
        assert total(w) == 1200 and len(work) == 2 and work[0]["duration"] < 480

    def test_openers_live_in_the_warm_up_not_a_separate_hard_step(self):
        steps = E.generate("cycling", 1.0, 4)["steps"]
        assert steps[0]["type"] == "warmup" and "3 × 1 min" in steps[0]["notes"]
        assert steps[1]["name"].startswith("Threshold 1/")

    @pytest.mark.parametrize("intensity", [4, 5])
    def test_spare_time_in_long_hard_sessions_is_zone2_not_cooldown(self, intensity):
        steps = E.generate("cycling", 2.5, intensity)["steps"]
        assert steps[-2]["name"] == "Steady Aerobic Z2" and steps[-2]["duration"] > 1500
        assert steps[-1]["type"] == "cooldown" and steps[-1]["duration"] <= 600

    @pytest.mark.parametrize("kind,marker,max_high_s", [("opener", "Opener", 180), ("shakeout", "Shake-Out", 60)])
    def test_race_week_sessions_are_light(self, kind, marker, max_high_s):
        w = E.generate_race_week_session(kind, "running", 0.75 if kind == "opener" else 0.42, ["hr_monitor"])
        assert marker in w["name"] and w["targetType"] == "heart_rate"
        high = sum(s["duration"] for s in w["steps"] if (s["target_low"] + s["target_high"]) / 2 > 90)
        assert high <= max_high_s
        assert total(w) == w["total_duration_sec"]

    def test_race_session(self):
        w = E.generate_race_week_session("race", "cycling", 3.0, race_name="Gran Fondo")
        assert w["name"] == "Race Day: Gran Fondo" and w["total_duration_sec"] == 10800
        assert E.generate_race_week_session("race", "running", 0.1)["total_duration_sec"] == 900

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


WED = datetime.date(2026, 10, 7)   # template A (early week)
FRI = datetime.date(2026, 10, 9)   # template B (later in the week)
HOME_GYM = ["bodyweight", "dumbbells", "kettlebells", "weights", "bench", "pullup_bar", "bands"]


def exercises(workout):
    return [s for s in workout["steps"] if s["type"] == "exercise"]


def lift_names(workout):
    return [s["name"].split(". ", 1)[1] for s in exercises(workout)]


class TestStrength:
    def test_a_full_session_of_named_exercises(self):
        w = StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED, ["cycling"], "advanced")
        assert total(w) == w["total_duration_sec"] == 1800
        assert [s["type"] for s in w["steps"]][0::len(w["steps"]) - 1] == ["warmup", "cooldown"]
        names = [s["name"] for s in exercises(w)]
        assert [n.split(".")[0] for n in names] == ["A", "B1", "B2", "C", "D1"]  # 4 compound lifts + core
        assert "Dumbbell Goblet Squat" in lift_names(w)
        assert all(s["duration"] > 0 and s["sets"] for s in exercises(w))
        assert all(n.split(" / ")[0] == n for n in lift_names(w))  # one specific movement each, no "X / Y"
        for name in lift_names(w)[:4]:
            assert name in w["description"]

    def test_push_and_pull_are_a_superset(self):
        w = StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED, level="intermediate")
        b1, b2 = exercises(w)[1:3]
        assert "Superset with" in b1["notes"] and b1["name"].split(". ")[1] in b2["notes"]

    def test_two_weekly_sessions_use_different_lifts(self):
        a = StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED)
        b = StrengthGenerator.generate("full", 30, 2, HOME_GYM, FRI)
        assert a["name"].endswith("A") and b["name"].endswith("B")
        assert lift_names(a)[:4] != lift_names(b)[:4]

    def test_lifts_hold_for_a_block_then_rotate(self):
        days = [WED + datetime.timedelta(weeks=w) for w in range(12)]
        sessions = [tuple(lift_names(StrengthGenerator.generate("full", 30, 2, HOME_GYM, d))) for d in days]
        assert len(set(sessions)) >= 2               # the lifts change over three months
        assert sum(a == b for a, b in zip(sessions, sessions[1:], strict=False)) >= 6  # ...but mostly carry over week to week

    def test_equipment_decides_the_exercise(self):
        gym = StrengthGenerator.generate("lower", 30, 2, ["squat_rack", "barbell", "bench", "dumbbells"], WED)
        home = StrengthGenerator.generate("lower", 30, 2, ["bodyweight"], WED)
        assert "Barbell Back Squat" in lift_names(gym) or "Barbell Romanian Deadlift" in lift_names(gym)
        assert not any(w in n for n in lift_names(home) for w in ("Barbell", "Dumbbell", "Kettlebell"))

    def test_bodyweight_only_when_nothing_loaded_fits(self):
        w = StrengthGenerator.generate("full", 30, 2, ["dumbbells"], WED)
        assert "Push-Up" not in lift_names(w) and "Tempo Bodyweight Squat" not in lift_names(w)

    @pytest.mark.parametrize("level,sets,reps", [("beginner", 3, 10), ("intermediate", 3, 8), ("advanced", 4, 5),
                                                 ("pro", 4, 5), (None, 3, 8)])
    def test_sets_and_reps_follow_experience(self, level, sets, reps):
        a = exercises(StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED, level=level))[0]
        assert (a["sets"], a["reps"]) == (sets, reps)

    def test_difficulty_without_level(self):
        a = exercises(StrengthGenerator.generate("full", 30, 1, HOME_GYM, WED))[0]
        assert (a["sets"], a["reps"]) == (3, 10)

    def test_runners_get_calf_raises(self):
        runner = StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED, ["running", "cycling"])
        rider = StrengthGenerator.generate("full", 30, 2, HOME_GYM, WED, ["cycling"])
        assert "Single-Leg Calf Raise" in lift_names(runner) and "Single-Leg Calf Raise" not in lift_names(rider)
        calf = next(s for s in exercises(runner) if "Calf" in s["name"])
        assert (calf["sets"], calf["reps"]) == (3, 12) and "each side" in calf["notes"]

    def test_holds_have_no_rep_count(self):
        names = set()
        for week in range(8):  # rotate through the core options
            for s in exercises(StrengthGenerator.generate("core", 30, 2, ["bodyweight"],
                                                          WED + datetime.timedelta(weeks=4 * week))):
                names.add(s["name"])
                if " s hold" in s["notes"]:
                    assert "reps" not in s and s["sets"]
        assert any("Plank" in n for n in names)

    def test_core_focus_has_two_core_exercises(self):
        w = StrengthGenerator.generate("core", 30, 2, HOME_GYM, WED)
        assert w["name"].startswith("Core & Full Body")
        assert [s["name"][:2] for s in exercises(w)].count("D1") + [s["name"][:2] for s in exercises(w)].count("D2") == 2

    @pytest.mark.parametrize("focus,title", [("legs", "Lower Body"), ("all", "Full Body"), ("upper", "Upper Body"),
                                             ("weird", "Full Body"), ("full_body", "Full Body")])
    def test_focus_aliases(self, focus, title):
        assert StrengthGenerator.generate(focus, 30, 2, ["bodyweight"])["name"].startswith(title)

    def test_short_session_keeps_the_essentials(self):
        w = StrengthGenerator.generate("full", 16, 2, ["bodyweight"], WED)
        assert total(w) == 16 * 60
        assert [s["name"][0] for s in exercises(w)] == ["A", "B", "B", "D"]
        assert w["steps"][0]["duration"] < 300

    def test_zero_minutes(self):
        assert StrengthGenerator.generate("full", 0)["steps"] == []


class TestMobility:
    @pytest.mark.parametrize("minutes", [5, 20, 60])
    def test_duration_is_filled_exactly(self, minutes):
        w = MobilityGenerator.generate("full", minutes, sports=["running"], session_date=WED)
        assert total(w) == minutes * 60 and all(s["duration"] > 0 for s in w["steps"])

    def test_named_drills_with_timings_open_and_close_the_session(self):
        w = MobilityGenerator.generate("full", 20, sports=["cycling"], session_date=WED)
        names = [s["name"] for s in w["steps"]]
        assert names[0] == "Cat-Cow" and names[-1] == "Child's Pose Breathing"
        assert any("each side" in s.get("notes", "") for s in w["steps"])
        assert "Couch Stretch" in names or "Half-Kneeling Hip Flexor Stretch" in names  # cyclists: hip flexors

    @pytest.mark.parametrize("sports,expected,title", [
        (["running"], {"Wall Calf Stretch", "Ankle Rocks"}, "Runner's Mobility"),
        (["swimming"], {"Wall Slides", "Doorway Chest Stretch", "Sleeper Stretch"}, "Swimmer's Mobility"),
    ])
    def test_drills_suit_the_sport(self, sports, expected, title):
        w = MobilityGenerator.generate("full", 20, sports=sports, session_date=WED)
        assert w["name"] == title and expected & {s["name"] for s in w["steps"]}

    @pytest.mark.parametrize("focus,sports,title", [
        ("legs", ["swimming"], "Lower Body Mobility"), ("upper", None, "Upper Body Mobility"),
        ("core", None, "Core & Spine Mobility"), ("full_body", ["running", "cycling"], "Multisport Mobility"),
        ("full", None, "Athletic Mobility"), ("full", ["strength"], "Athletic Mobility"),
    ])
    def test_titles(self, focus, sports, title):
        assert MobilityGenerator.generate(focus, 20, sports=sports)["name"] == title

    def test_rotates_week_to_week(self):
        a = MobilityGenerator.generate("full", 20, sports=["running"], session_date=WED)
        b = MobilityGenerator.generate("full", 20, sports=["running"], session_date=WED + datetime.timedelta(weeks=1))
        assert [s["name"] for s in a["steps"]] != [s["name"] for s in b["steps"]]

    def test_very_short_session_has_no_closer(self):
        w = MobilityGenerator.generate("full", 1.5, sports=["running"])
        assert total(w) == 90 and w["steps"][-1]["name"] != "Child's Pose Breathing"
        assert w["description"] == "Mobility for range of motion and recovery."

    def test_zero_minutes(self):
        assert MobilityGenerator.generate("full", 0)["steps"] == []


class TestSwim:
    CSS = 100  # 1:40 per 100 m

    def swim(self, hours, intensity, level=1, progression=0, css=CSS):
        return E.generate("swimming", hours, intensity, ["swim_watch"], level=level, progression=progression,
                          swim_css_sec=css)

    def reps(self, workout):
        return [s for s in workout["steps"] if s["type"] == "interval" and " m " in s["name"] + " "
                and "/" in s["name"]]

    @pytest.mark.parametrize("level,progression,name", [(0, 0, "Swim Threshold: 8 × 100 m"),
                                                        (1, 1, "Swim Threshold: 5 × 200 m"),
                                                        (4, 2, "Swim Threshold: 3 × 400 m")])
    def test_threshold_sets_are_by_distance_at_css(self, level, progression, name):
        w = self.swim(1.25, 4, level, progression)
        assert w["name"] == name and total(w) == 4500
        metres = int(name.split("× ")[1].split(" ")[0])
        assert {s["duration"] for s in self.reps(w)} == {metres // 100 * self.CSS}  # each rep at CSS pace
        assert "at CSS" in self.reps(w)[0]["notes"]

    def test_speed_set_is_faster_than_css(self):
        w = self.swim(1.0, 5, level=0)
        assert w["name"].startswith("Swim Speed: ")
        reps = self.reps(w)
        assert all(s["target_low"] >= 105 for s in reps) and reps[0]["duration"] == round((self.CSS - 5) / 2)

    def test_aerobic_swim_has_drills_200s_and_pull(self):
        w = self.swim(1.0, 2)
        names = [s["name"] for s in w["steps"]]
        assert names[0] == "Warm-up: 300 m easy + 4 × 50 m drill" and "catch-up" in w["steps"][0]["notes"]
        assert "4 × 100 m pull" in names and names[-1] == "Swim-down: 200 m easy"
        assert w["name"].startswith("Swim Aerobic:") and w["name"].endswith("+ pull")

    def test_recovery_swim_is_easier(self):
        rec = self.swim(0.75, 1)
        easy = self.swim(0.75, 2)
        assert rec["name"].startswith("Swim Recovery:")
        assert max(s["target_high"] for s in rec["steps"]) < max(s["target_high"] for s in easy["steps"])

    def test_short_swim_has_a_short_warm_up_and_no_pull(self):
        w = self.swim(20 / 60, 2)
        assert total(w) == 1200 and w["steps"][0]["name"].startswith("Warm-up: 200 m")
        assert "pull" not in w["name"]

    def test_short_hard_swim_drops_reps(self):
        w = self.swim(25 / 60, 4, level=1, progression=1, css=130)
        assert total(w) == 1500 and 4 <= len(self.reps(w)) < 8

    def test_spare_time_becomes_easy_swimming(self):
        w = self.swim(1.5, 4, level=0)
        easy = [s for s in w["steps"] if s["name"] == "Easy swim"]
        assert easy and easy[0]["notes"].startswith("About ")

    def test_faster_swimmer_swims_further_in_the_same_time(self):
        slow, fast = self.swim(1.0, 2, css=120), self.swim(1.0, 2, css=90)
        assert total(slow) == total(fast) == 3600
        count = lambda w: int(w["name"].split(": ")[1].split(" ×")[0])  # noqa: E731
        assert count(fast) > count(slow)
