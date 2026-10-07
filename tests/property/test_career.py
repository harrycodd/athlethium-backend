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


def simulate(sports, focus, weeks, compliance=1.0, switch=None, weekly_hours=30):
    """
    Returns per-week records: {start, type, hours, tss, ctl, level, sports: {sport: hours},
    longest: {sport: longest session hours}, double_runs: days with two runs}.
    `switch=(week, sports, focus)` changes the athlete's sports mid-career (no restart).
    """
    profile = UserProfile(uid="career", sports=sports, focused_sports=focus, weekly_hours=weekly_hours,
                          daily_max_hours={d: 5.0 for d in DAYS} | {"Saturday": 7.0, "Sunday": 6.0},
                          ctl=0, atl=0, fitness_level="beginner", metrics_date=None,
                          equipment=["power_meter", "running_power", "swim_watch"])
    history, records = {}, []
    day = START
    for w in range(weeks):
        if switch and w == switch[0]:
            profile = dataclasses.replace(profile, sports=switch[1], focused_sports=switch[2])
        monday = day
        week = {"start": monday, "hours": 0.0, "tss": 0.0, "sports": {}, "longest": {}, "double_runs": 0}
        this_week = {}
        for _ in range(7):
            recent = {k: v for k, v in history.items()
                      if monday - datetime.timedelta(weeks=3) <= datetime.date.fromisoformat(k) < monday}
            week_to_date = [[k, v] for k, v in this_week.items()]
            profile = dataclasses.replace(profile, recent_weeks=recent, week_to_date=week_to_date)
            docs = TrainingScheduler.schedule_day_all(profile, day, as_of=day)
            week["double_runs"] += sum(d.sport == "running" for d in docs) > 1
            for doc in docs:
                week["type"] = doc.week_type
                if doc.time > 0:
                    week["longest"][doc.sport] = max(week["longest"].get(doc.sport, 0.0), doc.time / 3600)
                if doc.time > 0 and doc.sport in ENDURANCE:
                    tss, hours = doc.tss * compliance, doc.time / 3600 * compliance
                    last = datetime.date.fromisoformat(profile.metrics_date) if profile.metrics_date else None
                    ctl, atl, new_date = PhysiologyEngine.apply_session_load(profile.ctl, profile.atl, last, day, tss)
                    profile = dataclasses.replace(profile, ctl=ctl, atl=atl, metrics_date=new_date.isoformat())
                    week["hours"] += hours
                    week["tss"] += tss
                    week["sports"][doc.sport] = week["sports"].get(doc.sport, 0.0) + hours
                    this_week[day.isoformat()] = this_week.get(day.isoformat(), 0.0) + tss
            day += datetime.timedelta(days=1)
        week.update(ctl=profile.ctl, level=athlete_level(profile))
        history[monday.isoformat()] = [week["hours"], week["tss"], dict(week["sports"]),
                                       {sp: h for sp, h in week["longest"].items() if sp in ENDURANCE}]
        records.append(week)
    return records


TRI = ["swimming", "cycling", "running"]
CAREERS = {  # name: (sports, focus, pro level reached before week)
    "cyclist": (["cycling"], ["cycling"], 60),
    "runner": (["running"], ["running"], 55),
    "swimmer": (["swimming"], ["swimming"], 65),
    "triathlete": (TRI, ["cycling", "running", "swimming"], 65),
}
# weekly ceilings by sport at pro level (planner MAX_WEEKLY_H)
PRO_CEILING = {"cycling": 30.0, "running": 14.0, "swimming": 20.0}


@pytest.fixture(scope="module", params=sorted(CAREERS))
def career(request):
    sports, focus, pro_by = CAREERS[request.param]
    return request.param, simulate(sports, focus, weeks=104), pro_by


def test_compliant_beginner_reaches_pro_level(career):
    name, weeks, pro_by = career
    levels = [w["level"] for w in weeks]
    reached = {lvl: next((i for i, x in enumerate(levels) if x >= lvl), None) for lvl in (1, 2, 3, 4)}
    assert reached[4] is not None and reached[4] < pro_by, f"{name}: levels reached at {reached}"
    assert all(reached[a] < reached[b] for a, b in ((1, 2), (2, 3), (3, 4))), reached


def test_pro_volume_is_realistic(career):
    name, weeks, _ = career
    late = [w for w in weeks[-26:] if w["type"] == "load"]
    assert sum(w["hours"] for w in late) / len(late) >= 14, f"{name}: pro weeks too small"
    for w in weeks:
        for sport, hours in w["sports"].items():
            assert hours <= PRO_CEILING[sport] + 1e-6, (name, w["start"], sport, hours)


def test_triathlete_split_follows_priorities():
    weeks = simulate(TRI, ["cycling", "running", "swimming"], weeks=104)
    late = [w for w in weeks[-26:] if w["type"] == "load"]
    avg = {sp: sum(w["sports"].get(sp, 0) for w in late) / len(late) for sp in TRI}
    assert avg["cycling"] > avg["running"] and avg["cycling"] > avg["swimming"]
    assert min(avg["running"], avg["swimming"]) >= 4.0, avg  # pro triathletes run & swim several hours


def test_fitness_keeps_rising_until_pro(career):
    name, weeks, _ = career
    ctl = [w["ctl"] for w in weeks]
    for a, b in zip(range(0, 52, 12), range(12, 53, 12), strict=False):
        assert ctl[b] > ctl[a] or weeks[a]["level"] == 4, f"{name}: stalled at CTL {ctl[a]:.1f} (week {a})"


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


# ---------------------------------------------------------------- switching sport mid-career

SWITCH_WEEK = 60


def _load_weeks(weeks, start):
    return [w for w in weeks[start:] if w["type"] == "load"]


def test_cyclist_to_runner_starts_from_transfer_credit_not_full_volume():
    weeks = simulate(["cycling"], ["cycling"], 76, switch=(SWITCH_WEEK, ["running"], ["running"]))
    last_bike_load = max(w["hours"] for w in weeks[SWITCH_WEEK - 4:SWITCH_WEEK] if w["type"] == "load")
    first_run = weeks[SWITCH_WEEK]["sports"]["running"]
    assert first_run <= 0.25 * last_bike_load * 1.10 + 0.5 + 1e-6  # 25% transfer, +10%
    assert first_run >= 2.0                                         # but not a restart
    # running then grows by at most 10% or one 30-min session a week
    prev = None
    for w in _load_weeks(weeks, SWITCH_WEEK):
        if prev:
            assert w["sports"]["running"] <= max(prev * 1.10, prev + 0.5) + 1e-6
        prev = w["sports"]["running"]
    assert weeks[-1]["sports"]["running"] > first_run


@pytest.mark.parametrize("new_sports,focus", [(["running"], ["running"]), (TRI, ["running", "swimming", "cycling"])])
def test_new_runners_build_run_length_from_their_own_running(new_sports, focus):
    """A fit cyclist who takes up running starts with short runs and lengthens them gradually."""
    weeks = simulate(["cycling"], ["cycling"], 80, switch=(SWITCH_WEEK, new_sports, focus))
    after = weeks[SWITCH_WEEK:]
    assert after[0]["longest"]["running"] <= 0.75 + 1e-6          # first week: runs of 45 min at most
    assert after[0]["sports"]["running"] >= 2.0                     # ...but still a real running week
    longest_so_far = after[0]["longest"]["running"]
    for w in after[1:]:
        # the longest run grows by at most 15 min a week
        assert w["longest"]["running"] <= longest_so_far + 0.25 + 1e-6, (w["start"], w["longest"], longest_so_far)
        longest_so_far = max(longest_so_far, w["longest"]["running"])
    # until established (2 h/week and an hour-long run) a new runner never runs twice in a day
    established = next(i for i, w in enumerate(after) if w["sports"]["running"] >= 2.0 and
                       max(x["longest"]["running"] for x in after[:i + 1]) >= 1.0)
    assert all(w["double_runs"] == 0 for w in after[:established + 1])
    assert after[-1]["longest"]["running"] >= 1.5


def test_cyclist_to_triathlete_keeps_fitness():
    weeks = simulate(["cycling"], ["cycling"], 76,
                     switch=(SWITCH_WEEK, TRI, ["running", "swimming", "cycling"]))
    before = weeks[SWITCH_WEEK - 1]["ctl"]
    assert min(w["ctl"] for w in weeks[SWITCH_WEEK:]) > 0.9 * before   # no restart
    assert all(w["level"] == 4 for w in weeks[SWITCH_WEEK:])
    late = _load_weeks(weeks, SWITCH_WEEK + 8)
    assert all(w["sports"].get("running", 0) > w["sports"].get("cycling", 0) * 0.5 for w in late)
    # total load still obeys the 10% rule across the switch
    loads = _load_weeks(weeks, SWITCH_WEEK - 8)
    assert all(b["hours"] <= a["hours"] * 1.10 + 0.02 for a, b in zip(loads, loads[1:], strict=False))


def test_runner_to_cyclist_carries_most_fitness_over():
    weeks = simulate(["running"], ["running"], 76, switch=(SWITCH_WEEK, ["cycling"], ["cycling"]))
    last_run_load = max(w["hours"] for w in weeks[SWITCH_WEEK - 4:SWITCH_WEEK] if w["type"] == "load")
    first_bike = weeks[SWITCH_WEEK]["sports"]["cycling"]
    assert 0.75 * last_run_load * 0.9 <= first_bike <= 0.75 * last_run_load * 1.30 + 1e-6
    assert weeks[-1]["ctl"] > weeks[SWITCH_WEEK - 1]["ctl"]


def test_triathlete_to_cyclist_drops_other_sports_immediately():
    weeks = simulate(TRI, ["cycling", "running", "swimming"], 70, switch=(SWITCH_WEEK, ["cycling"], ["cycling"]))
    assert all(set(w["sports"]) <= {"cycling"} for w in weeks[SWITCH_WEEK:])
    assert weeks[-1]["ctl"] > 0.9 * weeks[SWITCH_WEEK - 1]["ctl"]
