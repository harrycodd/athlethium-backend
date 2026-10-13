"""
Property-based tests: plan invariants must hold for *any* sensible athlete.

Hypothesis generates athletes across the whole range (new to elite, 1.5-25 h/week, single and
multi-sport, odd daily availability, goals near and far, illness flags, gaps in training, any
start date including ISO 53-week years) and every generated plan is checked against the coaching
invariants. Failures shrink to a minimal athlete, which is how most fixes in this phase were found.
"""

import datetime
import os

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from core.models import Goal, UserProfile
from engine.planner import WeekPlanner
from engine.scheduler import TrainingScheduler
from tests.property.plan_checks import (consecutive_hard_days, high_seconds, is_endurance, is_hard_day,
                                        monday, weekly_stats)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ENDURANCE = ["cycling", "running", "swimming"]
WEEKS = 10

# 150 examples per property in the normal run; HYPOTHESIS_MAX_EXAMPLES=1000 for a deep soak.
SETTINGS = settings(max_examples=int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "150")), deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])


@st.composite
def athletes(draw, with_goal=None, allow_issues=False):
    sports = draw(st.lists(st.sampled_from(ENDURANCE), min_size=1, max_size=3, unique=True))
    extras = draw(st.lists(st.sampled_from(["strength", "stretching"]), max_size=2, unique=True))
    focus = draw(st.lists(st.sampled_from(sports), min_size=1, max_size=len(sports), unique=True))
    daily = {d: draw(st.sampled_from([0, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0])) for d in DAYS}
    ctl = draw(st.floats(min_value=0, max_value=150, allow_nan=False))
    start = draw(st.dates(min_value=datetime.date(2020, 1, 1), max_value=datetime.date(2030, 12, 31)))
    goal = None
    if with_goal is True or (with_goal is None and draw(st.booleans())):
        goal = Goal(name="Event", date=(start + datetime.timedelta(days=draw(st.integers(10, 120)))).isoformat(),
                    sports=[focus[0]])
    known = draw(st.one_of(st.none(), st.lists(
        st.sampled_from(["cycling_power", "running_power", "running_pace", "swim_pace", "hr"]), unique=True)))
    gap = draw(st.one_of(st.none(), st.integers(0, 30)))
    profile = UserProfile(
        uid=draw(st.text(alphabet="abcdef0123", min_size=4, max_size=8)),
        sports=sports + extras,
        focused_sports=focus,
        weekly_hours=draw(st.floats(min_value=1.5, max_value=30)),
        daily_max_hours=daily,
        ctl=ctl,
        atl=ctl * draw(st.floats(min_value=0.5, max_value=1.5)),
        fitness_level=draw(st.sampled_from(["beginner", "intermediate", "advanced", "elite", "pro"])),
        intensity_weeks=draw(st.integers(1, 5)),
        equipment=draw(st.lists(st.sampled_from(["power_meter", "hr_monitor", "swim_watch", "running_power"]),
                                unique=True)) + ["bodyweight"],
        injury=draw(st.sampled_from([0, 0, 0, 1, 2])) if allow_issues else 0,
        illness=draw(st.sampled_from([0, 0, 0, 1, 2])) if allow_issues else 0,
        ftp_cycling=draw(st.floats(min_value=100, max_value=450)),
        ftp_running=draw(st.floats(min_value=150, max_value=450)),
        ftp_pace_running=draw(st.floats(min_value=180, max_value=480)),
        ftp_pace_swimming=draw(st.floats(min_value=60, max_value=180)),
        fthr=draw(st.floats(min_value=120, max_value=200)),
        known_thresholds=known,
        metrics_date=(start - datetime.timedelta(days=gap)).isoformat() if gap is not None else None,
        goal=goal,
    )
    return profile, monday(start)


def build_day(profile, day, start):
    """Every workout that day (two on a double day)."""
    return [d.to_dict() for d in TrainingScheduler.schedule_day_all(profile, day, as_of=start)]


def build_plan(profile, start, weeks=WEEKS):
    return [doc for i in range(7 * weeks) for doc in build_day(profile, start + datetime.timedelta(days=i), start)]


def week_plans(profile, start, weeks=WEEKS):
    return [WeekPlanner.plan_week(profile, start + datetime.timedelta(weeks=w), as_of=start) for w in range(weeks)]


# ---------------------------------------------------------------- polarised distribution

@SETTINGS
@given(athletes())
def test_polarised_distribution(case):
    profile, start = case
    for week in weekly_stats(build_plan(profile, start)):
        if week.endurance_hours < 1.0:
            continue
        # Session-goal method (Seiler): ~80% of time in easy sessions, <=25% in hard sessions.
        assert week.share(week.goal_split, "high") <= 0.25 + 1e-6, week
        assert week.share(week.goal_split, "mid") == 0.0, week
        # Time-in-zone: the grey zone stays tiny, and low dominates.
        assert week.share(week.zone_split, "mid") <= 0.05, week
        assert week.share(week.zone_split, "low") >= 0.75, week


@SETTINGS
@given(athletes(with_goal=False))
def test_load_weeks_with_enough_time_include_intensity(case):
    profile, start = case
    for plan in week_plans(profile, start):
        roomy_days = [s for s in plan.sessions if s.sport in ENDURANCE and s.hours >= 0.75]
        if (plan.context.week_type == "load" and not plan.comeback and plan.endurance_hours >= 5
                and plan.level > 0 and len(roomy_days) >= 3):
            assert any(s.kind in ("hard", "benchmark") for s in plan.sessions), plan


# ---------------------------------------------------------------- load progression

@SETTINGS
@given(athletes())
def test_weekly_load_rises_at_most_ten_percent(case):
    profile, start = case
    plans = week_plans(profile, start)
    last_load = None
    for plan in plans:
        if plan.context.week_type != "load":
            continue
        hours = plan.endurance_hours
        if last_load is not None and last_load > 0:
            assert hours <= last_load * 1.10 + 1e-6, (last_load, hours, plan.context)
        last_load = hours


@SETTINGS
@given(athletes())
def test_weekly_tss_rises_at_most_ten_percent(case):
    """Planned weekly TSS: +10% max between load weeks (aerobic comeback weeks reset the baseline)."""
    profile, start = case
    last = None
    for plan in week_plans(profile, start):
        if plan.context.week_type != "load":
            continue
        if plan.comeback:
            last = None
            continue
        if last:
            assert plan.tss <= last * 1.10 + 0.5, (last, plan.tss)
        last = plan.tss


@SETTINGS
@given(athletes())
def test_day_of_guardrails_only_ever_reduce_load(case):
    """Workouts can come out easier than planned (fatigue/illness on the day), never harder."""
    profile, start = case
    docs = build_plan(profile, start, weeks=3)
    plans = {p.context.week_start: p for p in week_plans(profile, start, weeks=3)}
    by_week = {}
    for d in docs:
        by_week.setdefault(monday(datetime.date.fromisoformat(d["date"])), 0.0)
        if d.get("event_type") != "Race":
            by_week[monday(datetime.date.fromisoformat(d["date"]))] += d["tss"]
    for week_start, tss in by_week.items():
        assert tss <= plans[week_start].tss + 0.5


@SETTINGS
@given(athletes(with_goal=False))
def test_recovery_week_every_three_to_four_weeks(case):
    profile, start = case
    types = [p.context.week_type for p in week_plans(profile, start, weeks=12)]
    run = 0
    for t in types:
        run = run + 1 if t == "load" else 0
        assert run <= 3
    recovery = [p for p in week_plans(profile, start, weeks=12) if p.context.week_type == "recovery"]
    assert len(recovery) >= 2


@SETTINGS
@given(athletes())
def test_never_exceeds_available_time(case):
    profile, start = case
    for plan in week_plans(profile, start, weeks=4):
        assert plan.endurance_hours <= profile.weekly_hours + 1e-6
        per_day = {}
        for s in plan.sessions:
            if s.kind != "race":
                per_day[s.date] = per_day.get(s.date, 0.0) + s.hours
        for day, hours in per_day.items():  # both sessions of a double day together fit the day
            cap = profile.daily_hours_overrides.get(day.isoformat(), profile.daily_max_hours.get(day.strftime("%A")))
            assert hours <= cap + 1e-6, (day, hours, cap)


# ---------------------------------------------------------------- spacing

@SETTINGS
@given(athletes(allow_issues=True))
def test_no_hard_days_back_to_back_including_across_weeks(case):
    profile, start = case
    docs = build_plan(profile, start)
    assert consecutive_hard_days(docs) == []
    # ... and therefore every hard day follows an easy or rest day; Mondays are never hard
    for d in docs:
        if is_hard_day(d) and d.get("event_type") != "Race":
            assert datetime.date.fromisoformat(d["date"]).weekday() != 0


# ---------------------------------------------------------------- athlete-specific targets

@SETTINGS
@given(athletes(), st.floats(min_value=1.05, max_value=1.5))
def test_targets_come_from_the_athletes_own_thresholds(case, factor):
    """
    A stronger athlete (power, heart rate and run pace) gets the same plan with harder targets.
    Swim pace stays the same here: swim sets are by distance, so a faster swimmer's sets (and
    their training stress, which drives the weekly load cap) legitimately differ. Swim targets
    are covered by test_swim_targets_come_from_the_swimmers_own_pace below.
    """
    profile, start = case
    docs = build_plan(profile, start, weeks=2)
    stronger = profile.__class__(**{**profile.__dict__,
                                    "ftp_cycling": profile.ftp_cycling * factor,
                                    "ftp_running": profile.ftp_running * factor,
                                    "fthr": profile.fthr * factor,
                                    "ftp_pace_running": profile.ftp_pace_running / factor})
    docs_stronger = build_plan(stronger, start, weeks=2)
    for a, b in zip(docs, docs_stronger, strict=True):
        assert [s["duration"] for s in a["steps"]] == [s["duration"] for s in b["steps"]]  # same structure
        for sa, sb in zip(a["steps"], b["steps"], strict=True):
            ra, rb = sa.get("target_range"), sb.get("target_range")
            assert (ra is None) == (rb is None)
            if ra is None:
                continue
            if ra["unit"] in ("W", "bpm"):
                assert rb["max"] >= ra["max"] and rb["min"] >= ra["min"]
            else:  # pace: stronger athlete = faster = fewer seconds
                assert rb["max"] <= ra["max"] and rb["min"] <= ra["min"]


@SETTINGS
@given(st.sampled_from([("easy", 2), ("recovery", 1), ("long", 2), ("hard", 4), ("hard", 5)]),
       st.sampled_from([0.5, 0.75, 1.0, 1.25, 1.5, 2.0]), st.integers(0, 4),
       st.floats(min_value=60, max_value=180), st.floats(min_value=1.05, max_value=1.5))
def test_swim_targets_come_from_the_swimmers_own_pace(kind_intensity, hours, level, css, factor):
    """Every swim fills exactly its planned time, and a faster swimmer's pace targets are faster."""
    from engine.planner import PlannedSession
    from engine.sessions import build_payload
    from engine.zones import apply_athlete_targets

    kind, intensity = kind_intensity
    session = PlannedSession(datetime.date(2026, 10, 6), kind, "swimming", intensity, hours,
                             style="threshold" if intensity == 4 else ("vo2" if intensity == 5 else None))
    base = UserProfile(uid="swim", sports=["swimming"], focused_sports=["swimming"],
                       equipment=["swim_watch"], fitness_level=["beginner", "intermediate", "advanced",
                                                                 "elite", "pro"][level],
                       ftp_pace_swimming=css)
    faster = UserProfile(**{**base.__dict__, "ftp_pace_swimming": css / factor})
    for profile in (base, faster):
        assert sum(s["duration"] for s in build_payload(session, profile)["steps"]) == round(hours * 3600)

    def targets(profile):  # as the scheduler builds them: % of CSS -> the swimmer's own pace
        payload = build_payload(session, profile)
        assert apply_athlete_targets(payload["steps"], "swimming", payload["targetType"], profile)
        return [s["target_range"] for s in payload["steps"] if s.get("target_range")]

    slow, fast = targets(base), targets(faster)
    assert slow and fast
    # the slowest and the fastest targets are both quicker for the faster swimmer
    assert max(t["max"] for t in fast) < max(t["max"] for t in slow)
    assert min(t["min"] for t in fast) < min(t["min"] for t in slow)


@SETTINGS
@given(athletes())
def test_unknown_thresholds_never_get_made_up_numbers(case):
    profile, start = case
    known = profile.known_thresholds
    for d in build_plan(profile, start, weeks=2):
        units = {s["target_range"]["unit"] for s in d["steps"] if "target_range" in s}
        if known is None or not units:
            continue
        if "W" in units:
            assert ("cycling_power" if d["sport"] == "cycling" else "running_power") in known
        if "bpm" in units:
            assert "hr" in known
        if "s/km" in units:
            assert "running_pace" in known
        if "s/100m" in units:
            assert "swim_pace" in known


# ---------------------------------------------------------------- taper

@SETTINGS
@given(athletes(with_goal=True))
def test_sensible_taper(case):
    profile, start = case
    race = datetime.date.fromisoformat(profile.goal.date)
    assume((race - start).days >= 35)
    weeks = (monday(race) - start).days // 7 + 1
    plans = week_plans(profile, start, weeks=weeks)
    load_hours = [p.endurance_hours for p in plans if p.context.week_type == "load"]
    assume(load_hours)
    peak = max(load_hours)
    taper, race_week = plans[-2], plans[-1]
    assert taper.context.week_type == "taper" and race_week.context.week_type == "race"
    assert taper.endurance_hours <= 0.6 * peak + 0.5
    assert race_week.endurance_hours <= 0.4 * peak + 0.5
    by_date = {s.date: s for p in plans for s in p.sessions}
    assert by_date[race].kind == "race"
    for offset in (1, 2):  # the two days before the race are shake-out / rest, never hard
        before = by_date.get(race - datetime.timedelta(days=offset))
        if before:
            assert before.kind in ("shakeout", "rest", "mobility")
    # No hard or long sessions in the final 6 days except the race and opener
    for s in by_date.values():
        if 0 < (race - s.date).days <= 6:
            assert s.kind not in ("hard", "long", "benchmark")


# ---------------------------------------------------------------- determinism

@SETTINGS
@given(athletes(allow_issues=True))
def test_same_inputs_same_plan(case):
    profile, start = case
    assert build_plan(profile, start, weeks=3) == build_plan(profile, start, weeks=3)


@SETTINGS
@given(athletes(), st.integers(0, 20))
def test_any_day_can_be_generated_on_its_own(case, offset):
    """Generating one day alone gives the same sessions as generating the whole block."""
    profile, start = case
    day = start + datetime.timedelta(days=offset)
    full = [d for d in build_plan(profile, start, weeks=3) if d["date"] == day.isoformat()]
    assert build_day(profile, day, start) == full


# ---------------------------------------------------------------- health flags

@SETTINGS
@given(athletes(allow_issues=True))
def test_illness_and_injury(case):
    profile, start = case
    docs = build_plan(profile, start, weeks=2)
    if profile.injury == 2 or profile.illness == 2:
        assert all(d["sport"] == "rest" for d in docs)
    elif profile.injury == 1 or profile.illness == 1:
        # the race itself stays on the calendar (the athlete decides on the day)
        docs = [d for d in docs if d.get("event_type") != "Race"]
        assert all(not is_hard_day(d) for d in docs)
        assert all(high_seconds(d) == 0 or d.get("session_kind") in ("opener", "shakeout") for d in docs
                   if is_endurance(d))
