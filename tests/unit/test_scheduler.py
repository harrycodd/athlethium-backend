import datetime

import pytest

from core.models import TrainingPhase
from engine.scheduler import TrainingScheduler as T
from tests.factories import make_goal, make_profile

# 2026-10-05 is a Monday in ISO week 41 -> mesocycle week 0 for a 3:1 cycle.
MON = datetime.date(2026, 10, 5)
BENCHMARK_WEEK = MON + datetime.timedelta(weeks=1)   # relative week 1
RECOVERY_WEEK = MON + datetime.timedelta(weeks=3)    # relative week 3
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day(week_start, name):
    return week_start + datetime.timedelta(days=DAYS.index(name))


class TestScheduleDay:
    def test_doc_identity_and_shape(self):
        doc = T.schedule_day(make_profile(uid="u1"), day(MON, "Saturday"))
        assert doc.workout_id == "plan_u1_2026-10-10"
        assert doc.user_id == "u1" and doc.date == "2026-10-10"
        assert sum(s["duration"] for s in doc.steps) == doc.time
        assert doc.tss == doc.planned_tss > 0
        assert doc.description.endswith(doc.coach_rationale)

    def test_explicit_user_id_wins(self):
        assert T.schedule_day(make_profile(uid="u1"), MON, user_id="other").user_id == "other"

    def test_too_little_time_is_rest(self):
        doc = T.schedule_day(make_profile(daily_hours_overrides={"2026-10-06": 0.3}), day(MON, "Tuesday"))
        assert doc.sport == "rest" and doc.intensity == -1 and doc.time == 0 and doc.steps == []

    def test_guardrail_rest(self):
        doc = T.schedule_day(make_profile(injury=2), day(MON, "Tuesday"))
        assert doc.sport == "rest" and "Severe injury" in doc.coach_rationale

    def test_guardrail_clamp_is_explained(self):
        doc = T.schedule_day(make_profile(injury=1), day(MON, "Tuesday"))
        assert doc.intensity == 2 and doc.coach_rationale.startswith("Adaptive Guardrail")

    def test_strength_has_no_intensity_or_tss(self):
        p = make_profile(sports=["cycling", "strength"], focused_sports=["cycling"])
        doc = T.schedule_day(p, day(MON, "Monday"))
        assert doc.sport == "strength" and doc.intensity is None and doc.tss == 0.0
        assert "form" in doc.execution_tips

    def test_benchmark_day(self):
        doc = T.schedule_day(make_profile(), day(BENCHMARK_WEEK, "Tuesday"))
        assert doc.intensity == 5 and "FTP Benchmark" in doc.name
        assert doc.coach_rationale.startswith("Post-Deload Benchmark")

    def test_deterministic(self):
        p = make_profile(goal=make_goal("2026-11-29"))
        assert T.schedule_day(p, MON).to_dict() == T.schedule_day(p, MON).to_dict()


class TestFitnessProjection:
    def test_unknown_metrics_date_untouched(self):
        p = make_profile(ctl=50, atl=80)
        assert T._project_fitness(p, MON) is p

    def test_malformed_metrics_date_untouched(self):
        p = make_profile(ctl=50, atl=80, metrics_date="yesterday")
        assert T._project_fitness(p, MON) is p

    def test_idle_gap_clears_fatigue_guardrail(self):
        tired = make_profile(ctl=50, atl=80, metrics_date="2026-10-05")
        assert T.schedule_day(tired, day(MON, "Tuesday")).intensity == 1      # TSB < -25 next day
        back_after_gap = make_profile(ctl=50, atl=80, metrics_date="2026-09-20")
        assert T.schedule_day(back_after_gap, day(MON, "Tuesday")).intensity == 4


class TestDailyHours:
    def test_override_then_weekday_then_default(self):
        p = make_profile(daily_hours_overrides={"2026-10-05": 2.0}, daily_max_hours={"Tuesday": 1.25},
                         daily_available_hours=0.75)
        assert T._resolve_daily_hours(p, MON) == 2.0
        assert T._resolve_daily_hours(p, day(MON, "Tuesday")) == 1.25
        assert T._resolve_daily_hours(p, day(MON, "Wednesday")) == 0.75


class TestSportSelection:
    def pick(self, day_name, sports, focused):
        return T._select_sport_for_day(make_profile(sports=sports, focused_sports=focused), day_name)

    def test_single_sport(self):
        assert self.pick("Monday", ["running"], ["running"]) == "running"

    def test_empty_lists_fall_back(self):
        assert self.pick("Tuesday", [], []) == "cycling"

    @pytest.mark.parametrize("sports,expected", [
        (["cycling", "stretching", "strength"], "stretching"),
        (["cycling", "strength"], "strength"),
        (["cycling", "running"], "cycling"),
    ])
    def test_monday(self, sports, expected):
        assert self.pick("Monday", sports, ["cycling"]) == expected

    def test_wed_fri_with_multiple_focus(self):
        tri = ["swimming", "cycling", "running"]
        assert self.pick("Wednesday", tri, tri) == "cycling"
        assert self.pick("Friday", tri, tri) == "running"
        assert self.pick("Friday", tri, ["swimming", "cycling"]) == "swimming"

    def test_wed_fri_secondary_sports(self):
        assert self.pick("Wednesday", ["cycling", "running", "swimming"], ["cycling"]) == "running"
        assert self.pick("Friday", ["cycling", "running", "swimming"], ["cycling"]) == "swimming"
        assert self.pick("Friday", ["cycling", "running"], ["cycling"]) == "running"

    def test_wed_without_secondary_uses_primary(self):
        assert self.pick("Wednesday", ["cycling", "running"], ["cycling", "running"]) == "running"
        assert self.pick("Wednesday", ["cycling", "running"], ["running", "cycling"]) == "cycling"

    def test_wed_all_sports_focused_single_focus(self):
        assert self.pick("Wednesday", ["cycling", "cycling"], ["cycling"]) == "cycling"

    def test_sunday(self):
        assert self.pick("Sunday", ["cycling", "strength"], ["cycling"]) == "strength"
        assert self.pick("Sunday", ["cycling", "running"], ["cycling", "running"]) == "running"
        assert self.pick("Sunday", ["cycling", "running"], ["cycling"]) == "cycling"

    def test_quality_days_use_primary(self):
        assert self.pick("Tuesday", ["cycling", "running"], ["running", "cycling"]) == "running"


class TestIntensityAndDuration:
    def decide(self, day_name, phase=TrainingPhase.BASE, recovery=False, tsb=0.0, hard=0, hours=3.0, sport="cycling"):
        return T._determine_intensity_and_duration(sport, day_name, hours, phase, recovery, tsb, hard, 1.0)

    def test_strength_and_mobility(self):
        assert self.decide("Tuesday", sport="strength") == (2, 1.0)
        assert self.decide("Tuesday", sport="stretching", hours=0.5) == (1, 0.5)

    def test_race_day(self):
        assert self.decide("Sunday", phase=TrainingPhase.RACE) == (7, 2.0)

    @pytest.mark.parametrize("day_name,hard,expected", [
        ("Tuesday", 0, (5, 1.0)),
        ("Thursday", 2, (2, 1.25)),
        ("Monday", 0, (1, 0.75)),
        ("Saturday", 0, (2, 1.25)),
    ])
    def test_taper(self, day_name, hard, expected):
        assert self.decide(day_name, phase=TrainingPhase.TAPER, hard=hard) == expected

    @pytest.mark.parametrize("day_name,tsb,expected", [
        ("Tuesday", 5, (3, 1.25)),
        ("Thursday", -5, (2, 1.5)),
        ("Friday", 0, (1, 0.75)),
        ("Sunday", 0, (2, 1.5)),
    ])
    def test_recovery_week(self, day_name, tsb, expected):
        assert self.decide(day_name, recovery=True, tsb=tsb) == expected

    @pytest.mark.parametrize("day_name,phase,tsb,hard,expected", [
        ("Tuesday", TrainingPhase.BASE, 0, 0, (4, 1.5)),
        ("Tuesday", TrainingPhase.BUILD, 0, 0, (5, 1.5)),
        ("Tuesday", TrainingPhase.PEAK, -20, 0, (2, 1.5)),
        ("Tuesday", TrainingPhase.BASE, 0, 2, (2, 1.5)),
        ("Thursday", TrainingPhase.BASE, 0, 0, (4, 1.5)),
        ("Thursday", TrainingPhase.BASE, -12, 0, (3, 1.5)),
        ("Saturday", TrainingPhase.BASE, 0, 0, (2, 3.0)),
        ("Sunday", TrainingPhase.BASE, 0, 0, (2, 2.0)),
        ("Monday", TrainingPhase.BASE, 0, 0, (1, 1.0)),
        ("Wednesday", TrainingPhase.BASE, 0, 0, (2, 1.5)),
    ])
    def test_loading_week(self, day_name, phase, tsb, hard, expected):
        assert self.decide(day_name, phase=phase, tsb=tsb, hard=hard) == expected


class TestStepGeneration:
    @pytest.mark.parametrize("notes,expected_word", [
        ("Target area: core", "Core"),
        ("strong legs please", "Lower"),
        ("upper body focus", "Upper"),
        ("nothing specific", "Full"),
    ])
    def test_strength_focus_from_goal_notes(self, notes, expected_word):
        p = make_profile(goal=make_goal(notes=notes))
        out = T._generate_steps_for_sport("strength", 2, 0.75, p)
        assert out["name"].lower().startswith(expected_word.lower())

    def test_mobility_and_no_goal(self):
        out = T._generate_steps_for_sport("stretching", 1, 0.5, make_profile())
        assert "Mobility" in out["name"]

    def test_endurance(self):
        out = T._generate_steps_for_sport("running", 2, 1.0, make_profile())
        assert out["targetType"] == "power" and out["steps"]


class TestBenchmark:
    def bench(self, day_name, week=BENCHMARK_WEEK, **kw):
        p = make_profile(**kw)
        rel = 1 if week == BENCHMARK_WEEK else 0
        return T._resolve_benchmark_test(p, day(week, day_name), rel, False, day_name)

    def test_only_week_one(self):
        p = make_profile()
        assert T._resolve_benchmark_test(p, MON, 1, True, "Tuesday") == (False, None)
        assert T._resolve_benchmark_test(p, MON, 0, False, "Tuesday") == (False, None)

    def test_no_endurance_focus(self):
        assert self.bench("Tuesday", focused_sports=["strength"]) == (False, None)

    def test_empty_focus_defaults_to_cycling(self):
        assert self.bench("Tuesday", focused_sports=[]) == (True, "cycling")

    def test_high_fitness_tests_three_sports_tue_thu_sat(self):
        tri = dict(ctl=80, focused_sports=["swimming", "cycling", "running"])
        assert self.bench("Tuesday", **tri) == (True, "swimming")
        assert self.bench("Thursday", **tri) == (True, "cycling")
        assert self.bench("Saturday", **tri) == (True, "running")
        assert self.bench("Wednesday", **tri) == (False, None)
        assert self.bench("Thursday", ctl=80, focused_sports=["cycling"]) == (False, None)
        assert self.bench("Saturday", ctl=80, focused_sports=["cycling", "running"]) == (False, None)

    def test_fitness_level_counts_as_high(self):
        assert self.bench("Thursday", ctl=20, fitness_level="elite",
                          focused_sports=["cycling", "running"]) == (True, "running")

    def test_lower_fitness_spreads_tests(self):
        duo = dict(ctl=40, focused_sports=["cycling", "running"])
        assert self.bench("Tuesday", **duo) == (True, "cycling")
        assert self.bench("Saturday", **duo) == (True, "running")
        assert self.bench("Saturday", ctl=40, focused_sports=["cycling"]) == (False, None)
        assert self.bench("Thursday", **duo) == (False, None)
        tri = ["swimming", "cycling", "running"]
        assert self.bench("Thursday", ctl=50, focused_sports=tri) == (True, "running")
        assert self.bench("Thursday", ctl=40, focused_sports=tri) == (False, None)


class TestCoachingNotes:
    @pytest.mark.parametrize("kwargs,prefix", [
        (dict(clamp_reason="x"), "Adaptive Guardrail: x"),
        (dict(is_benchmark=True), "Post-Deload Benchmark"),
        (dict(is_recovery_week=True), "Deload Week"),
        (dict(intensity=5), "High-Intensity Stimulus"),
        (dict(intensity=4), "Threshold Development"),
        (dict(intensity=3), "Sweet Spot Progression"),
        (dict(intensity=2), "Aerobic Base Building"),
        (dict(intensity=1), "Active Recovery"),
    ])
    def test_notes(self, kwargs, prefix):
        args = dict(sport="cycling", intensity=2, phase=TrainingPhase.BASE, is_recovery_week=False,
                    clamp_reason=None, is_benchmark=False)
        args.update(kwargs)
        assert T._build_coaching_notes(**args).startswith(prefix)

    def test_unknown_phase_label(self):
        assert "Endurance Block" in T._build_coaching_notes("cycling", 2, "unknown", False, None)


class TestRecentIntensities:
    def test_reads_focus_lists_and_ignores_others(self):
        p = make_profile(history={"cycling": {"focus": [0, 2, 5]}, "running": {"tss": [40]}})
        assert T._get_recent_intensities(p) == [2, 5]

    def test_empty(self):
        assert T._get_recent_intensities(make_profile(history={})) == []
