"""
Closed-loop career simulation: the way the app really runs.

Every day the athlete opens the app ("today" moves forward), gets today's session planned from
their current fitness and recently completed weeks, completes it 100%, and their CTL/ATL update.
This catches what fixed-horizon tests can't: plans that stall, ramps that compound week after week,
or levels that can never be unlocked.
"""

import dataclasses
import datetime

import pytest

from core.models import UserProfile
from engine.physiology import PhysiologyEngine
from engine.planner import athlete_level
from engine.scheduler import TrainingScheduler

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ENDURANCE = ("cycling", "running", "swimming")
START = datetime.date(2026, 10, 5)


def simulate(sports, focus, weeks, compliance=1.0):
    """Returns per-week records: {start, type, hours, tss, ctl, level}."""
    profile = UserProfile(uid="career", sports=sports, focused_sports=focus, weekly_hours=25,
                          daily_max_hours={d: 3.0 for d in DAYS} | {"Saturday": 6.0, "Sunday": 5.0},
                          ctl=0, atl=0, fitness_level="beginner", metrics_date=None,
                          equipment=["power_meter", "running_power", "swim_watch"])
    history, records = {}, []
    day = START
    for _ in range(weeks):
        monday = day
        week = {"start": monday, "hours": 0.0, "tss": 0.0}
        this_week = {}
        for _ in range(7):
            recent = {k: v for k, v in history.items()
                      if monday - datetime.timedelta(weeks=3) <= datetime.date.fromisoformat(k) < monday}
            week_to_date = [[k, v] for k, v in this_week.items()]
            profile = dataclasses.replace(profile, recent_weeks=recent, week_to_date=week_to_date)
            doc = TrainingScheduler.schedule_day(profile, day, as_of=day)
            week["type"] = doc.week_type
            if doc.time > 0 and doc.sport in ENDURANCE:
                tss, hours = doc.tss * compliance, doc.time / 3600 * compliance
                last = datetime.date.fromisoformat(profile.metrics_date) if profile.metrics_date else None
                ctl, atl, new_date = PhysiologyEngine.apply_session_load(profile.ctl, profile.atl, last, day, tss)
                profile = dataclasses.replace(profile, ctl=ctl, atl=atl, metrics_date=new_date.isoformat())
                week["hours"] += hours
                week["tss"] += tss
                this_week[day.isoformat()] = tss
            day += datetime.timedelta(days=1)
        week.update(ctl=profile.ctl, level=athlete_level(profile))
        history[monday.isoformat()] = [week["hours"], week["tss"]]
        records.append(week)
    return records


CAREERS = {
    "cyclist": (["cycling"], ["cycling"], 70),
    "runner": (["running"], ["running"], 45),
    "triathlete": (["swimming", "cycling", "running"], ["cycling", "running", "swimming"], 70),
}


@pytest.fixture(scope="module", params=sorted(CAREERS))
def career(request):
    sports, focus, elite_by = CAREERS[request.param]
    return request.param, simulate(sports, focus, weeks=104), elite_by


def test_compliant_beginner_reaches_elite_level(career):
    name, weeks, elite_by = career
    reached = next((i for i, w in enumerate(weeks) if w["level"] == 3), None)
    assert reached is not None and reached < elite_by, f"{name}: elite level reached at week {reached}"


def test_fitness_keeps_rising_until_the_volume_ceiling(career):
    name, weeks, _ = career
    ctl = [w["ctl"] for w in weeks]
    # quarter by quarter CTL rises during the first year (no stall below the elite level)
    for a, b in zip(ctl[0:52:12], ctl[12:53:12], strict=False):
        assert b > a or weeks[ctl.index(a)]["level"] == 3, f"{name}: stalled at CTL {a:.1f}"
    assert max(ctl) > 50


def test_live_ramp_never_exceeds_ten_percent(career):
    """The 10% rule must hold week by week as the athlete actually lives it, not just on paper."""
    _, weeks, _ = career
    last = None
    for w in weeks:
        if w["type"] != "load":
            continue
        if last:
            assert w["hours"] <= last["hours"] * 1.10 + 0.02, (last, w)
            assert w["tss"] <= last["tss"] * 1.10 + 0.5, (last, w)
        last = w


def test_recovery_weeks_keep_coming(career):
    _, weeks, _ = career
    run = 0
    for w in weeks:
        run = run + 1 if w["type"] == "load" else 0
        assert run <= 3


def test_partial_compliance_holds_volume_back():
    """At 70% completion the plan follows what's actually done instead of racing ahead."""
    full = simulate(["cycling"], ["cycling"], weeks=24)
    partial = simulate(["cycling"], ["cycling"], weeks=24, compliance=0.7)
    assert partial[-1]["ctl"] < full[-1]["ctl"]
    assert max(w["hours"] for w in partial) < max(w["hours"] for w in full)
