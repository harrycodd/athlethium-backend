"""
Characterisation ("golden master") tests for the plan-generation engine.

These record what the algorithm *does*, not what it *should* do. Any change to plan output
shows up as a snapshot diff, so behaviour changes are always deliberate:

    pytest tests/characterisation --snapshot-update   # only after reviewing the diff
"""

import datetime

import pytest
from syrupy.extensions.json import JSONSnapshotExtension

from engine.periodization import PeriodizationEngine
from engine.physiology import PhysiologyEngine
from engine.scheduler import TrainingScheduler
from generators.endurance import EnduranceGenerator
from generators.mobility import MobilityGenerator
from generators.strength import StrengthGenerator
from tests.factories import make_goal, make_profile

MONDAY = datetime.date(2026, 10, 5)


@pytest.fixture
def snapshot_json(snapshot):
    return snapshot.use_extension(JSONSnapshotExtension)


def _summarise(doc):
    return {
        "date": doc.date,
        "sport": doc.sport,
        "intensity": doc.intensity,
        "minutes": round(doc.time / 60, 1),
        "tss": doc.tss,
        "name": doc.name,
        "targetType": doc.target_type,
        "steps": [
            [s["type"], s["duration"], s.get("target_low"), s.get("target_high"), s["targetType"]]
            for s in doc.steps
        ],
        "rationale": doc.coach_rationale,
    }


def _plan(profile, start, days):
    out = []
    for i in range(days):
        d = start + datetime.timedelta(days=i)
        try:
            out.append(_summarise(TrainingScheduler.schedule_day(profile, d)))
        except Exception as exc:  # the crash *is* the current behaviour we are recording
            out.append({"date": d.isoformat(), "error": f"{type(exc).__name__}: {exc}"})
    return out


CASES = {
    "default_no_goal": dict(),
    "goal_8_weeks_out": dict(goal=make_goal("2026-11-29")),
    "goal_in_10_days_taper": dict(goal=make_goal("2026-10-15")),
    "goal_passed": dict(goal=make_goal("2026-09-20")),
    "runner_only": dict(sports=["running"], focused_sports=["running"], equipment=["bodyweight", "hr_monitor"]),
    "triathlete_with_strength": dict(
        sports=["swimming", "cycling", "running", "strength", "stretching"],
        focused_sports=["swimming", "cycling", "running"],
        equipment=["bodyweight", "power_meter", "swim_watch", "dumbbells"],
        goal=make_goal("2026-12-20", sports=["cycling"], notes="Target area: core"),
    ),
    "high_fitness": dict(ctl=95.0, atl=90.0, focused_sports=["cycling", "running"]),
    "beginner_low_ctl": dict(ctl=10.0, atl=8.0, fitness_level="beginner"),
    "deep_fatigue": dict(ctl=50.0, atl=85.0),
    "minor_injury": dict(injury=1),
    "severe_illness": dict(illness=2),
    "time_crunched": dict(daily_max_hours={d: 0.5 for d in
                          ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}),
    "hard_yesterday_in_history": dict(history={"cycling": {"focus": [2, 2, 5]}}),
    "date_overrides": dict(daily_hours_overrides={"2026-10-06": 0.0, "2026-10-10": 5.0}),
    "two_week_mesocycle": dict(intensity_weeks=1),
    "no_equipment_swimmer": dict(sports=["swimming"], focused_sports=["swimming"], equipment=["bodyweight"]),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_eight_week_plan(case, snapshot_json):
    profile = make_profile(**CASES[case])
    assert _plan(profile, MONDAY, 56) == snapshot_json


def test_iso_year_boundary(snapshot_json):
    """2026 has 53 ISO weeks: records how the mesocycle behaves across new year."""
    assert _plan(make_profile(), datetime.date(2026, 12, 21), 21) == snapshot_json


def test_endurance_generator_grid(snapshot_json):
    grid = {}
    for sport in ["cycling", "running", "swimming"]:
        for intensity in [1, 2, 3, 4, 5, 6, 7]:
            for hours in [0.25, 0.75, 1.5]:
                key = f"{sport}|z{intensity}|{hours}h"
                try:
                    w = EnduranceGenerator.generate(sport, hours, intensity, ["power_meter"])
                    grid[key] = [w["name"], w["targetType"], [[s["type"], s["duration"]] for s in w["steps"]]]
                except Exception as exc:
                    grid[key] = f"{type(exc).__name__}: {exc}"
    assert grid == snapshot_json


def test_benchmark_and_strength_mobility(snapshot_json):
    out = {
        f"bench|{s}": EnduranceGenerator.generate_benchmark_workout(s, 1.25)["steps"]
        for s in ["cycling", "running", "swimming", "rowing"]
    }
    for focus in ["full", "lower", "upper", "core", "legs", "bogus"]:
        out[f"strength|{focus}"] = StrengthGenerator.generate(focus, 45, 2, ["bodyweight"])["steps"]
        out[f"mobility|{focus}"] = MobilityGenerator.generate(focus, 20)["steps"]
    assert out == snapshot_json


def test_physiology_and_periodisation(snapshot_json):
    out = {
        "next_day": [PhysiologyEngine.calculate_next_day_metrics(50, 45, tss) for tss in [0, 50, 150]],
        "estimate": [PhysiologyEngine.estimate_session_tss(z, 1.5, "cycling") for z in range(-1, 8)],
        "actual": [
            PhysiologyEngine.calculate_actual_tss("cycling", 3600, avg_power=200, ftp=250),
            PhysiologyEngine.calculate_actual_tss("cycling", 3600, avg_hr=150, fthr=170),
            PhysiologyEngine.calculate_actual_tss("cycling", 3600, rpe=7),
            PhysiologyEngine.calculate_actual_tss("cycling", 3600),
            PhysiologyEngine.calculate_actual_tss("cycling", 0),
        ],
        "phase": [
            PeriodizationEngine.resolve_training_phase(make_goal(g), MONDAY)
            for g in [None, "2026-10-05", "2026-10-01", "2026-10-15", "2026-10-30", "2026-12-01", "2027-03-01", "bad"]
        ],
        "meso": [PeriodizationEngine.resolve_mesocycle_week(MONDAY + datetime.timedelta(weeks=w), 3) for w in range(8)],
    }
    assert out == snapshot_json
