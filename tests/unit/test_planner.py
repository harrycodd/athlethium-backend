"""
Example-based tests for the week planner: one named test per Phase 3 fix / edge case.
(The general guarantees are property-tested in tests/property/test_plan_invariants.py.)
"""

import datetime

import pytest

from core.models import Goal
from engine.planner import Kind, WeekPlanner, athlete_level, day_capacity, endurance_sports
from engine.scheduler import TrainingScheduler
from tests.factories import make_goal, make_profile

MON = datetime.date(2026, 10, 5)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ROOMY = {d: 2.0 for d in DAYS} | {"Saturday": 4.0, "Sunday": 3.0}


def weeks(profile, n=8, start=MON, as_of=MON):
    return [WeekPlanner.plan_week(profile, start + datetime.timedelta(weeks=w), as_of=as_of) for w in range(n)]


def kinds(plan):
    return [s.kind for s in plan.sessions]


def docs(profile, n_days=56, start=MON, as_of=MON):
    return [TrainingScheduler.schedule_day(profile, start + datetime.timedelta(days=i), as_of=as_of)
            for i in range(n_days)]


# ------------------------------------------------------------------ volume & progression

def test_fix_weekly_hours_are_respected():
    """Old engine gave a 4 h/week beginner 10-11 h/week."""
    p = make_profile(ctl=10, atl=8, weekly_hours=4, fitness_level="beginner")
    assert all(w.endurance_hours <= 4.0 for w in weeks(p))


def test_fix_elite_volume_ramps_towards_their_target():
    """Old engine capped an 18 h/week elite at ~11-13 h."""
    p = make_profile(ctl=110, atl=100, weekly_hours=18, fitness_level="elite", daily_max_hours={d: 4 for d in DAYS})
    plans = weeks(p)
    load = [w.endurance_hours for w in plans if w.context.week_type == "load"]
    assert load[0] >= 13 and max(load) <= 18 and max(load) > load[0]


def test_fix_no_jump_after_recovery_week():
    """Old engine jumped +79-91% from a deload week back to full load (vs. last load week here)."""
    p = make_profile(daily_max_hours=ROOMY, weekly_hours=20)
    last = None
    for w in weeks(p, 12):
        if w.context.week_type != "load":
            continue
        if last:
            assert w.endurance_hours <= last * 1.10 + 1e-6
        last = w.endurance_hours


def test_new_user_starts_at_entry_volume_for_their_level():
    for level, hours in [("beginner", 2.5), ("intermediate", 4.0), ("advanced", 6.0), ("elite", 8.0)]:
        p = make_profile(ctl=0, atl=0, fitness_level=level, weekly_hours=25, daily_max_hours=ROOMY)
        first = weeks(p, 1)[0]
        cap = hours * (0.65 if first.context.week_type == "recovery" else 1.0)
        assert first.endurance_hours <= cap + 1e-6


def test_missed_sessions_are_not_made_up():
    """A missed week (lower CTL than planned) lowers the next weeks rather than cramming."""
    on_track = make_profile(ctl=60, atl=60, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=20)
    missed = make_profile(ctl=50, atl=30, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=20)
    for a, b in zip(weeks(on_track, 4), weeks(missed, 4), strict=True):
        assert b.endurance_hours <= a.endurance_hours


def test_comeback_after_illness_gap_is_aerobic_then_one_hard_session():
    p = make_profile(ctl=60, atl=60, metrics_date="2026-09-22", daily_max_hours=ROOMY, weekly_hours=15)
    first, second = weeks(p, 2, as_of=datetime.date(2026, 10, 5))
    assert first.comeback and not any(k in (Kind.HARD, Kind.BENCHMARK) for k in kinds(first))
    hard = [k for k in kinds(second) if k in (Kind.HARD, Kind.BENCHMARK)]
    assert len(hard) <= 1
    # and volume restarts from decayed fitness, not the pre-illness load
    fresh = make_profile(ctl=60, atl=60, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=15)
    assert first.endurance_hours < weeks(fresh, 1)[0].endurance_hours


def test_short_gap_is_not_a_comeback():
    p = make_profile(metrics_date="2026-10-01")
    assert not weeks(p, 1)[0].comeback


def test_planning_a_past_week_is_standalone():
    plan = WeekPlanner.plan_week(make_profile(), MON, as_of=MON + datetime.timedelta(weeks=2))
    assert plan.context.week_start == MON


# ------------------------------------------------------------------ distribution & spacing

def test_fix_recovery_weeks_have_no_grey_zone_sessions():
    for w in weeks(make_profile(daily_max_hours=ROOMY, weekly_hours=12)):
        assert all(s.intensity != 3 for s in w.sessions)


def test_fix_time_crunched_athlete_stays_polarised():
    """Old engine: 38% of a 5 h week was hard."""
    p = make_profile(weekly_hours=5, daily_max_hours={"Monday": 0, "Tuesday": 1, "Wednesday": 0.75, "Thursday": 1,
                                                      "Friday": 0, "Saturday": 1.5, "Sunday": 1})
    for w in weeks(p):
        hard = sum(s.hours for s in w.sessions if s.kind in (Kind.HARD, Kind.BENCHMARK))
        assert hard <= 0.25 * w.endurance_hours + 1e-6


def test_single_training_day_gets_no_intensity():
    p = make_profile(weekly_hours=4, daily_max_hours={d: (4.0 if d == "Sunday" else 0) for d in DAYS})
    for w in weeks(p, 4):
        assert Kind.HARD not in kinds(w) and Kind.BENCHMARK not in kinds(w)


def test_hard_days_never_monday_or_back_to_back():
    p = make_profile(daily_max_hours={d: 2.0 for d in DAYS}, weekly_hours=14, fitness_level="advanced", ctl=70)
    all_sessions = [s for w in weeks(p) for s in w.sessions]
    hard_dates = {s.date for s in all_sessions if s.kind in (Kind.HARD, Kind.BENCHMARK)}
    assert hard_dates and all(d.weekday() != 0 for d in hard_dates)
    assert not any(d + datetime.timedelta(days=1) in hard_dates for d in hard_dates)


def test_day_after_hard_is_recovery():
    w = weeks(make_profile(daily_max_hours=ROOMY, weekly_hours=10), 1)[0]
    for i, s in enumerate(w.sessions[:-1]):
        if s.kind == Kind.HARD and w.sessions[i + 1].kind not in (Kind.REST, Kind.MOBILITY, Kind.STRENGTH):
            assert w.sessions[i + 1].kind == Kind.RECOVERY


def test_beginners_get_two_rest_days_and_at_most_one_hard_session():
    p = make_profile(fitness_level="beginner", ctl=10, weekly_hours=6, daily_max_hours=ROOMY)
    for w in weeks(p, 4):
        assert kinds(w).count(Kind.REST) + kinds(w).count(Kind.MOBILITY) >= 2
        assert kinds(w).count(Kind.HARD) <= 1


def test_strength_never_day_before_hard_and_not_in_taper():
    p = make_profile(sports=["cycling", "strength"], goal=make_goal("2026-11-29"), daily_max_hours=ROOMY,
                     weekly_hours=12)
    for w in weeks(p):
        ks = kinds(w)
        for i in range(6):
            if ks[i] == Kind.STRENGTH:
                assert ks[i + 1] not in (Kind.HARD, Kind.BENCHMARK)
        if w.context.week_type in ("taper", "race"):
            assert Kind.STRENGTH not in ks
        assert ks.count(Kind.STRENGTH) <= 2


def test_sport_split_follows_percentages():
    p = make_profile(sports=["cycling", "running"], focused_sports=["running"],
                     sport_percentages={"running": 75, "cycling": 25}, daily_max_hours=ROOMY, weekly_hours=10)
    w = weeks(p, 1)[0]
    run = sum(s.hours for s in w.sessions if s.sport == "running")
    ride = sum(s.hours for s in w.sessions if s.sport == "cycling")
    assert run > ride


def test_sessions_per_week_limit():
    p = make_profile(sports=["cycling", "running"], focused_sports=["cycling"],
                     sport_sessions_per_week={"running": 1}, daily_max_hours=ROOMY, weekly_hours=12)
    w = weeks(p, 1)[0]
    assert sum(1 for s in w.sessions if s.sport == "running") <= 1


def test_running_sessions_respect_impact_limits():
    p = make_profile(sports=["running"], focused_sports=["running"], fitness_level="beginner", ctl=20,
                     daily_max_hours=ROOMY, weekly_hours=8)
    for w in weeks(p):
        assert all(s.hours <= 1.25 for s in w.sessions if s.sport == "running")


def test_strength_and_mobility_only_athlete():
    p = make_profile(sports=["strength", "stretching"], focused_sports=["strength"])
    ks = [k for w in weeks(p, 4) for k in kinds(w)]
    assert Kind.STRENGTH in ks and Kind.MOBILITY in ks
    assert not any(k in (Kind.EASY, Kind.HARD, Kind.LONG) for k in ks)


# ------------------------------------------------------------------ periodisation, taper, race

def test_fix_taper_reduces_volume_without_adding_intensity():
    p = make_profile(goal=make_goal("2026-11-29"), daily_max_hours=ROOMY, weekly_hours=12)
    plans = weeks(p)
    peak_hard = max(sum(1 for s in w.sessions if s.kind == Kind.HARD) for w in plans[:-2])
    taper, race = plans[-2], plans[-1]
    assert taper.context.week_type == "taper" and race.context.week_type == "race"
    assert sum(1 for s in taper.sessions if s.kind == Kind.HARD) <= peak_hard
    assert Kind.HARD not in kinds(race)
    peak = max(w.endurance_hours for w in plans if w.context.week_type == "load")
    assert taper.endurance_hours <= 0.6 * peak + 1e-6


def test_fix_race_day_is_the_event_not_a_sprint_workout():
    p = make_profile(goal=Goal(name="Gran Fondo", date="2026-11-29", sports=["cycling"], target_time=5 * 3600))
    doc = TrainingScheduler.schedule_day(p, datetime.date(2026, 11, 29), as_of=MON)
    assert doc.event_type == "Race" and doc.name == "Race Day: Gran Fondo" and doc.time == 5 * 3600
    assert doc.intensity != 7


@pytest.mark.parametrize("race_day", ["2026-11-29", "2026-11-25", "2026-11-23"])  # Sun, Wed, Mon
def test_race_week_routine_whatever_the_weekday(race_day):
    race = datetime.date.fromisoformat(race_day)
    p = make_profile(goal=make_goal(race_day), daily_max_hours=ROOMY, weekly_hours=12)
    by_date = {s.date: s for w in weeks(p, 10) for s in w.sessions}
    assert by_date[race].kind == Kind.RACE
    assert by_date[race - datetime.timedelta(days=1)].kind == Kind.SHAKEOUT
    assert by_date[race - datetime.timedelta(days=2)].kind == Kind.REST
    assert by_date[race - datetime.timedelta(days=3)].kind == Kind.OPENER
    assert by_date[race + datetime.timedelta(days=1)].kind == Kind.REST
    for offset in (2, 3):
        assert by_date[race + datetime.timedelta(days=offset)].kind in (Kind.RECOVERY, Kind.REST, Kind.MOBILITY)


def test_post_race_week_is_easy():
    p = make_profile(goal=make_goal("2026-10-11"), daily_max_hours=ROOMY, weekly_hours=12)
    post = WeekPlanner.plan_week(p, datetime.date(2026, 10, 12), as_of=MON)
    assert post.context.week_type == "post_race"
    assert not any(k in (Kind.HARD, Kind.BENCHMARK) for k in kinds(post))


def test_race_without_target_time_uses_sport_default_and_race_sport():
    p = make_profile(sports=["cycling", "running"], focused_sports=["cycling"],
                     goal=Goal(name="10k", date="2026-10-11", sports=["running"]))
    race = WeekPlanner.plan_week(p, datetime.date(2026, 10, 11), as_of=MON).session_on(datetime.date(2026, 10, 11))
    assert race.sport == "running" and race.hours == 1.0


def test_benchmark_after_recovery_week():
    p = make_profile(daily_max_hours=ROOMY, weekly_hours=12, uid="bench")
    plans = weeks(p, 9)
    for prev, cur in zip(plans, plans[1:], strict=False):
        if prev.context.week_type == "recovery" and cur.context.week_type == "load":
            assert Kind.BENCHMARK in kinds(cur)


def test_unknown_threshold_triggers_benchmark_and_no_numbers():
    p = make_profile(ctl=0, atl=0, fitness_level="advanced", known_thresholds=[], daily_max_hours=ROOMY,
                     weekly_hours=10, uid="new")
    plans = weeks(p, 4)
    assert plans[0].context.week_type == "load" and Kind.BENCHMARK in kinds(plans[0])
    # only once: later weeks don't keep re-testing (unless they follow a recovery week)
    for prev, cur in zip(plans, plans[1:], strict=False):
        if prev.context.week_type == "load":
            assert Kind.BENCHMARK not in kinds(cur)
    for d in docs(p, 14):
        assert all("target_range" not in s for s in d.steps)


def test_brand_new_beginner_trains_by_feel_with_no_made_up_numbers():
    p = make_profile(ctl=0, atl=0, fitness_level="beginner", known_thresholds=[], metrics_date=None,
                     daily_max_hours=ROOMY, weekly_hours=10, uid="newbie")
    plan_docs = docs(p, 14)
    endurance = [d for d in plan_docs if d.sport != "rest"]
    assert endurance and all("target_range" not in s for d in endurance for s in d.steps)
    assert all("RPE" in d.coach_rationale for d in endurance)
    assert sum(d.time for d in plan_docs[:7]) / 3600 <= 2.5


# ------------------------------------------------------------------ health

def test_minor_issue_halves_volume_and_removes_intensity():
    base = weeks(make_profile(daily_max_hours=ROOMY, weekly_hours=12), 1)[0]
    sick = weeks(make_profile(daily_max_hours=ROOMY, weekly_hours=12, illness=1), 1)[0]
    assert sick.endurance_hours <= base.endurance_hours * 0.5 + 1e-6
    assert not any(k in (Kind.HARD, Kind.BENCHMARK) for k in kinds(sick))


def test_severe_issue_is_full_rest():
    w = weeks(make_profile(injury=2), 1)[0]
    assert set(kinds(w)) == {Kind.REST} and "Severe injury" in w.sessions[0].reason


# ------------------------------------------------------------------ helpers

def test_level_and_capacity_helpers():
    assert athlete_level(make_profile(fitness_level="weird", ctl=30)) == 1
    # fitness unlocks levels: cycling 20/45/65/85, running 18/28/38/52, swimming 18/28/42/65
    assert athlete_level(make_profile(fitness_level="beginner", ctl=50)) == 2
    assert athlete_level(make_profile(fitness_level="beginner", ctl=70)) == 3
    assert athlete_level(make_profile(fitness_level="beginner", ctl=90)) == 4
    run = dict(sports=["running"], focused_sports=["running"], fitness_level="beginner")
    assert [athlete_level(make_profile(ctl=c, **run)) for c in (10, 19, 29, 39, 53)] == [0, 1, 2, 3, 4]
    assert athlete_level(make_profile(fitness_level="pro", ctl=0)) == 4
    assert athlete_level(make_profile(fitness_level="intermediate", ctl=5)) == 0
    assert athlete_level(make_profile(sports=["strength"], focused_sports=["strength"], ctl=25)) == 1
    p = make_profile(daily_hours_overrides={"2026-10-05": 12}, daily_max_hours={"Tuesday": "x"},
                     daily_available_hours=0.75)
    assert day_capacity(p, MON) == 8.0
    assert day_capacity(p, MON + datetime.timedelta(days=1)) == 0.0
    assert day_capacity(p, MON + datetime.timedelta(days=2)) == 0.75
    assert endurance_sports(make_profile(sports=["strength"], focused_sports=["running"])) == (["running"], ["running"])
    assert endurance_sports(make_profile(sports=["swimming"], focused_sports=["cycling"])) == (["swimming"], ["swimming"])


def test_week_without_any_available_time_is_rest():
    w = weeks(make_profile(daily_max_hours={d: 0 for d in DAYS}), 1)[0]
    assert set(kinds(w)) == {Kind.REST}


def test_malformed_metrics_date_is_treated_as_unknown():
    p = make_profile(metrics_date="last tuesday")
    assert not weeks(p, 1)[0].comeback


def test_strength_only_athlete_rests_in_taper_and_race_weeks():
    p = make_profile(sports=["strength"], focused_sports=["strength"], goal=make_goal("2026-10-18"))
    for w in weeks(p, 2):
        assert set(kinds(w)) == {Kind.REST}


def test_load_cap_stops_when_only_quality_sessions_remain():
    from engine.planner import PlannedSession
    hard = [PlannedSession(MON + datetime.timedelta(days=1), Kind.HARD, "cycling", 4, 1.0, "threshold")]
    assert WeekPlanner._cap_load(make_profile(), hard, max_tss=1.0) == hard


def test_load_cap_drops_sessions_that_get_too_short():
    from engine.planner import PlannedSession
    easy = [PlannedSession(MON, Kind.EASY, "cycling", 2, 0.5)]
    assert WeekPlanner._cap_load(make_profile(), easy, max_tss=1.0)[0].kind == Kind.REST


def test_week_is_planned_from_its_start_so_it_does_not_change_mid_week():
    """Completing Monday's session must not change the rest of the week's plan."""
    from engine.physiology import PhysiologyEngine
    base = make_profile(ctl=44.5, atl=44.5, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=20,
                        recent_weeks={"2026-09-28": [6.0, 280.0]})
    monday_plan = WeekPlanner.plan_week(base, MON, as_of=MON)
    ctl, atl, _ = PhysiologyEngine.apply_session_load(44.5, 44.5, datetime.date(2026, 10, 4), MON, 60.0)
    after = make_profile(ctl=ctl, atl=atl, metrics_date="2026-10-05", daily_max_hours=ROOMY, weekly_hours=20,
                         recent_weeks={"2026-09-28": [6.0, 280.0]}, week_to_date=[["2026-10-05", 60.0]])
    tue = MON + datetime.timedelta(days=1)
    assert WeekPlanner.plan_week(after, tue, as_of=tue).sessions == monday_plan.sessions


def test_ramp_baseline_is_last_completed_load_week():
    hist = {"2026-09-14": [9.0, 400.0], "2026-09-21": [6.0, 270.0], "2026-09-28": [3.0, 130.0]}
    p = make_profile(ctl=40, atl=40, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=25,
                     recent_weeks=hist, uid="hist")
    plan = WeekPlanner.plan_week(p, MON, as_of=MON)
    if plan.context.week_type == "load":
        assert plan.endurance_hours <= 1.10 * max(
            h for k, (h, _) in hist.items()) + 1e-6


def test_fit_athlete_with_no_recent_history_restarts_as_comeback():
    p = make_profile(ctl=60, atl=60, metrics_date="2026-10-05", daily_max_hours=ROOMY, recent_weeks={})
    assert WeekPlanner.plan_week(p, MON + datetime.timedelta(days=1), as_of=MON + datetime.timedelta(days=1)).comeback


def test_history_two_weeks_back_means_a_one_week_gap():
    p = make_profile(ctl=60, atl=60, metrics_date="2026-10-05", daily_max_hours=ROOMY,
                     recent_weeks={"2026-09-21": [5.0, 220.0], "bad-key": [1, 1], "2026-09-28": "x",
                                   "2026-09-14": ["a", 1]})
    assert WeekPlanner.plan_week(p, MON, as_of=MON).comeback


def test_week_start_state_ignores_bad_or_out_of_week_sessions():
    clean = make_profile(ctl=50, atl=50, metrics_date="2026-10-06", recent_weeks={"2026-09-28": [5.0, 230.0]})
    noisy = make_profile(ctl=50, atl=50, metrics_date="2026-10-06", recent_weeks={"2026-09-28": [5.0, 230.0]},
                         week_to_date=[["2026-09-30", 80.0], ["junk"], ["2026-10-09", 80.0], "x"])
    assert WeekPlanner._state_at_week_start(noisy, MON) == WeekPlanner._state_at_week_start(clean, MON)


def test_history_outside_the_window_is_ignored():
    p = make_profile(recent_weeks={"2026-08-03": [20.0, 900.0], "2026-09-28": [5.0, 230.0]})
    assert [w[0] for w in WeekPlanner._completed_weeks(p, MON)] == [datetime.date(2026, 9, 28)]


def test_strength_never_starves_endurance_when_time_is_tiny():
    """Found by Hypothesis: 45 min/week + strength used to give completely empty load weeks."""
    p = make_profile(sports=["cycling", "strength"], weekly_hours=2, fitness_level="beginner", ctl=0, atl=0,
                     daily_max_hours={d: (0.75 if d == "Sunday" else 0) for d in DAYS})
    for w in weeks(p, 4):
        assert w.endurance_hours >= 0.5


def test_minor_issue_does_not_compound_week_after_week():
    """Halving volume for a minor illness must not keep halving every planned week (found in snapshots)."""
    p = make_profile(illness=1, daily_max_hours=ROOMY, weekly_hours=12)
    hours = [w.endurance_hours for w in weeks(p, 6) if w.context.week_type == "load"]
    assert min(hours) >= 0.9 * max(hours) - 0.5


def test_planning_ahead_with_sport_history_carries_each_sport_forward():
    hist = {"2026-09-28": [8.0, 360.0, {"cycling": 6.0, "running": 2.0}]}
    p = make_profile(ctl=55, atl=55, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=25,
                     sports=["cycling", "running"], focused_sports=["running", "cycling"], recent_weeks=hist, uid="ahead")
    plans = weeks(p, 4)
    runs = [w.sport_hours.get("running", 0.0) for w in plans if w.context.week_type == "load"]
    assert runs[0] <= max(2.0 * 1.1, 2.0 + 0.5) + 1e-6
    assert all(b <= max(a * 1.1, a + 0.5) + 1e-6 for a, b in zip(runs, runs[1:], strict=False))


def test_new_sport_starts_from_transfer_credit():
    hist = {"2026-09-28": [16.0, 700.0, {"cycling": 16.0}]}
    p = make_profile(ctl=90, atl=90, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=25,
                     sports=["running"], focused_sports=["running"], recent_weeks=hist, uid="switch")
    first = weeks(p, 1)[0]
    if first.context.week_type == "load":
        assert first.sport_hours["running"] <= 0.25 * 16.0 * 1.10 + 1e-6
    assert max(s.hours for s in first.sessions if s.sport == "running") <= 0.4 * 0.25 * 16 * 1.10 + 1e-6


# ------------------------------------------------------------------ switching to running

def _runs(plan):
    return [s for s in plan.sessions if s.sport == "running"]


def test_pro_cyclist_switching_to_running_starts_with_short_easy_runs():
    """Fitness transfers, legs don't: a pro cyclist's first runs are 45 min, easy, one a day."""
    hist = {"2026-09-28": [27.0, 1300.0, {"cycling": 27.0}, {"cycling": 5.0}]}
    p = make_profile(ctl=120, atl=110, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=30,
                     sports=["running"], focused_sports=["running"], recent_weeks=hist, uid="switch",
                     fitness_level="pro")
    first = weeks(p, 1)[0]
    runs = _runs(first)
    assert runs and max(s.hours for s in runs) <= 0.75
    assert all(s.kind in (Kind.EASY, Kind.RECOVERY, Kind.LONG) for s in runs)
    assert len({s.date for s in runs}) == len(runs)  # never two runs in a day


def test_new_runner_with_other_sports_keeps_intensity_off_the_run():
    hist = {"2026-09-28": [12.0, 600.0, {"cycling": 12.0}, {"cycling": 3.0}]}
    p = make_profile(ctl=70, atl=65, metrics_date="2026-10-04", daily_max_hours=ROOMY, weekly_hours=20,
                     sports=["running", "cycling"], focused_sports=["running"], recent_weeks=hist, uid="tri")
    plan = weeks(p, 1)[0]
    assert all(s.kind in (Kind.EASY, Kind.RECOVERY, Kind.LONG) for s in _runs(plan))
    assert any(s.kind in (Kind.HARD, Kind.BENCHMARK) and s.sport == "cycling" for s in plan.sessions)


def test_long_run_grows_by_at_most_15_minutes_a_week_when_planning_ahead():
    hist = {"2026-09-28": [9.0, 450.0, {"cycling": 6.0, "running": 3.0}, {"cycling": 2.0, "running": 1.0}]}
    p = make_profile(ctl=60, atl=60, metrics_date="2026-10-04", daily_max_hours=ROOMY | {"Sunday": 4.0},
                     weekly_hours=25, sports=["running", "cycling"], focused_sports=["running", "cycling"],
                     recent_weeks=hist, uid="ahead")
    longest = 1.0
    for plan in weeks(p, 6):
        week_longest = max(s.hours for s in _runs(plan))
        assert week_longest <= longest + 0.25 + 1e-6
        longest = max(longest, week_longest)
    assert longest > 1.0  # and it does grow


def test_established_runner_keeps_their_long_run():
    hist = {"2026-09-28": [8.0, 400.0, {"running": 8.0}, {"running": 2.0}]}
    p = make_profile(ctl=50, atl=50, metrics_date="2026-10-04", daily_max_hours=ROOMY | {"Sunday": 4.0},
                     weekly_hours=12, sports=["running"], focused_sports=["running"], recent_weeks=hist,
                     uid="runner", fitness_level="advanced")
    plan = weeks(p, 1)[0]
    assert max(s.hours for s in _runs(plan)) >= 2.0
    allowance = WeekPlanner.sport_allowances({"running": 8.0}, ["running"], "load", False, 8.0, 2, {"running": 2.0})
    assert allowance.run_cap == 2.25 and not allowance.new_runner


@pytest.mark.parametrize("history,expected_cap,expected_new", [
    ({"cycling": 10.0}, 0.75, True),                    # older history without session lengths, no running yet
    ({"cycling": 10.0, "running": 3.0}, None, False),   # ...with running: sized from the running allowance
])
def test_run_cap_without_session_lengths(history, expected_cap, expected_new):
    allowance = WeekPlanner.sport_allowances(history, ["running"], "load", False, 10.0, 2)
    assert allowance.run_cap == expected_cap and allowance.new_runner is expected_new


def test_malformed_longest_entry_is_ignored():
    p = make_profile(ctl=50, atl=50, metrics_date="2026-10-04",
                     recent_weeks={"2026-09-28": [5.0, 230.0, {"cycling": 5.0}, "garbage"]})
    assert WeekPlanner._completed_weeks(p, MON) == [(datetime.date(2026, 9, 28), 5.0, 230.0, {"cycling": 5.0}, None)]
