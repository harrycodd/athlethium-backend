import dataclasses
import datetime

import pytest

from engine.planner import Kind, PlannedSession, WeekPlanner
from engine.scheduler import TrainingScheduler as T
from tests.factories import make_goal, make_profile

MON = datetime.date(2026, 10, 5)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ROOMY = {d: 2.0 for d in DAYS} | {"Saturday": 4.0}


def plan_day(profile, kind, start=MON, weeks=8):
    for i in range(7 * weeks):
        day = start + datetime.timedelta(days=i)
        doc = T.schedule_day(profile, day, as_of=start)
        if doc.session_kind == kind:
            return doc
    raise AssertionError(f"no {kind} session found")


class TestDocument:
    def test_identity_shape_and_targets(self):
        doc = plan_day(make_profile(uid="u1", daily_max_hours=ROOMY), Kind.LONG)
        assert doc.workout_id == f"plan_u1_{doc.date}" and doc.user_id == "u1"
        assert sum(s["duration"] for s in doc.steps) == doc.time == doc.planned_time
        assert doc.tss == doc.planned_tss > 0
        assert doc.week_type in ("load", "recovery")
        main = next(s for s in doc.steps if s["type"] == "interval")
        assert main["target_range"] == {"unit": "W", "min": round(250 * 0.65), "max": round(250 * 0.72)}
        assert doc.description.endswith(doc.coach_rationale)
        assert "talk in full sentences" in doc.execution_tips

    def test_explicit_user_id_wins(self):
        assert T.schedule_day(make_profile(uid="u1"), MON, user_id="other").user_id == "other"

    def test_rest_day(self):
        doc = T.schedule_day(make_profile(daily_max_hours={d: 0 for d in DAYS}), MON)
        assert doc.sport == "rest" and doc.intensity == -1 and doc.time == 0 and doc.steps == []
        assert doc.session_kind == "rest" and doc.coach_rationale == "Planned rest day"

    def test_hard_session_notes(self):
        p = make_profile(daily_max_hours=ROOMY, weekly_hours=12, goal=make_goal("2026-11-29"))
        doc = plan_day(p, Kind.HARD)
        assert doc.intensity in (4, 5) and "Key session" in doc.coach_rationale
        assert "weeks to your event" in doc.coach_rationale
        assert "Hit the targets" in doc.execution_tips

    def test_threshold_and_vo2_notes(self):
        p = make_profile(daily_max_hours=ROOMY, weekly_hours=12, goal=make_goal("2026-11-29"))
        notes = {T.schedule_day(p, MON + datetime.timedelta(days=i), as_of=MON).coach_rationale for i in range(42)}
        assert any("VO2max" in n for n in notes) and any("threshold intervals" in n for n in notes)

    def test_one_week_to_event_wording(self):
        p = make_profile(goal=make_goal("2026-10-18"), daily_max_hours=ROOMY)
        doc = T.schedule_day(p, MON + datetime.timedelta(days=1), as_of=MON)
        assert "1 week to your event" in doc.coach_rationale

    def test_strength_and_mobility_documents(self):
        p = make_profile(sports=["cycling", "strength", "stretching"], daily_max_hours=ROOMY, weekly_hours=10,
                         goal=make_goal("2026-12-20", notes="target area: upper body"))
        strength = plan_day(p, Kind.STRENGTH)
        assert strength.sport == "strength" and strength.intensity is None and strength.tss == 0.0
        assert "form" in strength.execution_tips and strength.name.startswith("Upper")
        mobility = plan_day(p, Kind.MOBILITY)
        assert mobility.sport == "stretching" and mobility.time == 1200

    def test_benchmark_document(self):
        p = make_profile(daily_max_hours=ROOMY, weekly_hours=12, uid="bench")
        doc = plan_day(p, Kind.BENCHMARK, weeks=9)
        assert "Benchmark" in doc.name and "re-measures your threshold" in doc.coach_rationale
        assert doc.execution_tips == "Follow the step targets."

    def test_race_week_documents(self):
        p = make_profile(goal=make_goal("2026-10-18", name="Club TT"), daily_max_hours=ROOMY)
        opener = plan_day(p, Kind.OPENER, weeks=2)
        shakeout = plan_day(p, Kind.SHAKEOUT, weeks=2)
        race = plan_day(p, Kind.RACE, weeks=2)
        assert opener.date == "2026-10-15" and shakeout.date == "2026-10-17" and race.date == "2026-10-18"
        assert race.event_type == "Race" and race.name == "Race Day: Club TT"
        assert "Race day" in race.coach_rationale

    def test_comeback_note(self):
        p = make_profile(metrics_date="2026-09-20", daily_max_hours=ROOMY)
        doc = plan_day(p, Kind.EASY, weeks=1)
        assert "easing back in after time off" in doc.coach_rationale

    def test_no_threshold_means_feel_based(self):
        p = make_profile(known_thresholds=[], daily_max_hours=ROOMY, fitness_level="beginner", ctl=10, atl=10)
        doc = plan_day(p, Kind.EASY)
        assert "RPE" in doc.coach_rationale and all("target_range" not in s for s in doc.steps)

    def test_swim_without_watch_estimates_tss(self):
        p = make_profile(sports=["swimming"], focused_sports=["swimming"], equipment=["bodyweight"],
                         daily_max_hours=ROOMY)
        doc = plan_day(p, Kind.EASY)
        assert doc.target_type == "time" and doc.tss == pytest.approx(doc.time / 3600 * 50, abs=0.2)

    def test_go_by_feel_tip_for_benchmark_without_threshold(self):
        p = make_profile(known_thresholds=["hr"], daily_max_hours=ROOMY, weekly_hours=12, fitness_level="advanced",
                         ctl=0, atl=0, uid="x")
        doc = plan_day(p, Kind.BENCHMARK, weeks=4)
        assert doc.execution_tips == "Go by feel (RPE)."


class TestGuardrailsOnTheDay:
    def test_deep_fatigue_downgrades_a_hard_day(self):
        p = make_profile(ctl=40, atl=80, metrics_date="2026-10-05", daily_max_hours=ROOMY)
        tue = MON + datetime.timedelta(days=1)
        planned = WeekPlanner.plan_week(p, tue, as_of=MON).session_on(tue)
        assert planned.kind in (Kind.HARD, Kind.BENCHMARK)
        doc = T.schedule_day(p, tue, as_of=MON)
        assert doc.intensity == 1 and doc.session_kind == Kind.RECOVERY
        assert doc.coach_rationale.split(". ", 1)[1].startswith("Adaptive Guardrail")

    def test_guardrail_rest(self, monkeypatch):
        from engine import scheduler
        monkeypatch.setattr(scheduler.GuardrailEngine, "apply_safety_clamps",
                            classmethod(lambda cls, **kw: (-1, 0.0, "Forced rest: test")))
        doc = T.schedule_day(make_profile(daily_max_hours=ROOMY), MON + datetime.timedelta(days=1), as_of=MON)
        assert doc.sport == "rest" and doc.coach_rationale == "Forced rest: test"

    def test_guardrail_downgrade_to_easy(self, monkeypatch):
        from engine import scheduler
        monkeypatch.setattr(scheduler.GuardrailEngine, "apply_safety_clamps",
                            classmethod(lambda cls, **kw: (2, 1.0, "Capped")))
        doc = plan_day(make_profile(daily_max_hours=ROOMY), Kind.EASY)
        assert doc.intensity == 2 and doc.time == 3600


class TestFitnessProjection:
    def test_unknown_or_malformed_metrics_date_untouched(self):
        p = make_profile(ctl=50, atl=80)
        assert T._project_fitness(p, MON) is p
        bad = make_profile(ctl=50, atl=80, metrics_date="yesterday")
        assert T._project_fitness(bad, MON) is bad

    def test_idle_days_drain_fatigue(self):
        p = T._project_fitness(make_profile(ctl=50, atl=80, metrics_date="2026-09-20"), MON)
        assert p.atl < 30 and p.ctl > 35


def test_rest_document_without_week():
    doc = T._rest("u", "2026-10-05", "reason")
    assert doc.week_type is None and doc.session_kind == "rest"


def test_scheduler_handles_unknown_kind_text():
    session = PlannedSession(MON, "custom", "cycling", 2, 1.0)
    week = WeekPlanner.plan_week(make_profile(), MON)
    assert T._coaching_notes(session, week, None, True).startswith("Load week") or \
        T._coaching_notes(session, week, None, True).startswith("Recovery week")
    assert T._execution_tip(dataclasses.replace(session, kind="opener"), True) == "Follow the step targets."


@pytest.mark.parametrize("notes,expected", [("legs", "lower"), ("lower body", "lower"), ("core", "core"),
                                            ("upper body", "upper"), ("", "full")])
def test_anatomical_focus_from_goal_notes(notes, expected):
    from engine.sessions import anatomical_focus
    assert anatomical_focus(make_profile(goal=make_goal(notes=notes))) == expected
    assert anatomical_focus(make_profile(goal=None)) == "full"
