"""
Week planner: lays out a whole Monday-Sunday week, then the scheduler turns one day of it into
a workout. Planning the week as a unit is what makes the weekly guarantees possible:

- Polarised: hard sessions take ~20% of weekly time (never more than 25%); everything else is
  low intensity; no tempo/"grey zone" sessions are prescribed.
- Progression: a load week is at most 10% above the previous load week (or, for the first
  planned week, above the athlete's current chronic load). Recovery weeks every 3-4 weeks.
- Spacing: hard sessions are never on consecutive days and never on Mondays, so a hard day is
  always preceded by an easy or rest day, including across week boundaries.
- Taper: two reduced-volume weeks before the event, then a race-week routine (opener three days
  out, rest two days out, shake-out the day before, race, rest the day after).

The plan is a pure function of (profile, week, as_of): same inputs, same plan.
"""

import dataclasses
import datetime
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.models import TrainingPhase, UserProfile
from engine.periodization import WeekContext, WeekType, monday_of, week_context
from engine.physiology import PhysiologyEngine
from engine.sessions import session_tss
from i18n import t

ENDURANCE_SPORTS = ("cycling", "running", "swimming")
LEVELS = ("beginner", "intermediate", "advanced", "elite", "pro")

TSS_PER_HOUR = 55.0          # converts chronic load (CTL) into weekly hours
RAMP = 1.10                  # max week-on-week rise between load weeks
HARD_SHARE = 0.20            # share of weekly time given to hard sessions
MAX_HARD_SHARE = 0.25        # hard sessions never exceed this share of the week
LONG_SHARE = 0.30            # long session share of weekly time
LONG_MAX_SHARE = 0.40        # long session never exceeds this share, even when topping up
FACTORS = {                  # volume relative to the last load week
    WeekType.RECOVERY: 0.65,
    WeekType.TAPER: 0.60,
    WeekType.RACE: 0.40,
    WeekType.POST_RACE: 0.50,
}
MIN_SESSION_H = 0.5
MIN_HARD_H = 40 / 60
MIN_LONG_H = 1.0
BENCHMARK_H = 1.0
LONG_SESSION_MIN_WEEK_H = 2.5
COMEBACK_IDLE_DAYS = 7
STRENGTH_H = 0.5
MOBILITY_H = 20 / 60
MOBILITY_PER_WEEK = 2   # when the athlete hasn't said how many they want
SHAKEOUT_H = 25 / 60
OPENER_H = 0.75
SLOT = 1 / 12                # durations are rounded down to 5 minutes

# CTL that unlocks intermediate / advanced / elite caps, per primary sport. Each threshold sits
# below what the previous level's caps can sustain, so a compliant athlete always progresses
# (checked by tests/property/test_career.py). Running/swimming caps are tighter, so lower CTL.
CTL_LEVEL_THRESHOLDS = {"cycling": (20, 45, 65, 85), "running": (18, 28, 38, 52), "swimming": (18, 28, 42, 65)}
HISTORY_WEEKS = 3                    # completed weeks used as the ramp baseline
START_HOURS = (2.5, 4.0, 6.0, 8.0, 10.0)  # first week for athletes with no training history, by level
MAX_HARD_H = (1.0, 1.25, 1.5, 1.75, 2.0)
MAX_RECOVERY_H = (0.75, 1.0, 1.5, 2.0, 2.5)  # day after a hard session
MAX_SESSION_H = {"cycling": (1.5, 2.0, 2.5, 3.0, 4.5), "running": (1.0, 1.25, 1.5, 1.75, 2.0),
                 "swimming": (1.0, 1.25, 1.5, 1.75, 2.0)}
MAX_LONG_H = {"cycling": (2.5, 3.5, 4.5, 5.5, 6.5), "running": (1.25, 1.75, 2.25, 2.75, 3.0),
              "swimming": (1.0, 1.25, 1.5, 2.0, 2.5)}
DOUBLES_MIN_LEVEL = 2                 # advanced+ athletes may train twice a day (only when needed)
# Most weekly hours in one sport, by level. Running is limited hardest (impact): even pro
# marathoners rarely run more than ~14 h a week; swimmers and cyclists go much higher.
MAX_WEEKLY_H = {"cycling": (8.0, 12.0, 18.0, 24.0, 30.0), "running": (4.0, 6.0, 8.0, 11.0, 14.0),
                "swimming": (4.0, 6.0, 9.0, 14.0, 20.0)}

# Share of training in one sport that counts towards the starting volume of another. Aerobic
# fitness carries over, but impact and technique don't: a cyclist new to running starts at a
# quarter of their riding volume, a runner keeps most of theirs on the bike.
TRANSFER = {
    "cycling": {"running": 0.25, "swimming": 0.25},
    "running": {"cycling": 0.75, "swimming": 0.25},
    "swimming": {"cycling": 0.25, "running": 0.25},
}
# Per-sport week-on-week growth: running is held to the 10% rule (impact injuries); low-impact
# cycling and swimming may shift faster *within* the overall +10% weekly load.
SPORT_RAMP = {"running": 1.10, "cycling": 1.30, "swimming": 1.30}
NEW_SPORT_FLOOR_H = 2.0              # any sport can always take ~2 h (e.g. 3 short sessions)
RUN_SESSION_SHARE = 0.40             # no run exceeds 40% of the week's running (impact rule)
MIN_RUN_CAP_H = 1.0                  # ...but a 1 h run is always fine for an established runner
# Someone switching to running brings aerobic fitness but not the legs for it: their runs are
# sized from the running they have actually done, not from fitness credited by other sports.
ESTABLISHED_RUNNER_H = 2.0           # an established runner runs >= 2 h a week...
ESTABLISHED_LONG_RUN_H = 1.0         # ...and has run for an hour; until then: easy runs only
NEW_RUNNER_RUN_H = 0.75              # first runs are 45 min at most, and never two in one day
RUN_STEP_H = 0.25                    # the longest run grows by at most 15 min a week
DEFAULT_RACE_H = {"cycling": 2.0, "running": 1.0, "swimming": 0.75}

# Weekday preferences (0 = Monday). Hard sessions never go on Monday.
HARD_DAY_PREFERENCE = (1, 3, 2, 4, 6, 5)
REST_DAY_PREFERENCE = (0, 4, 2, 6, 3, 1, 5)
STRENGTH_DAY_PREFERENCE = (2, 4, 0, 6, 3, 1, 5)
SPORT_THRESHOLD_KEY = {"cycling": "cycling_power", "running": "running_pace", "swimming": "swim_pace"}


def _grow(volume: float, factor: float, extra_session: bool) -> float:
    return max(factor * volume, volume + MIN_SESSION_H) if extra_session else factor * volume


class Allowance(dict):
    """
    Weekly hours each sport may take ({sport: hours}), plus the longest run allowed when it is
    sized from the athlete's own running history (None = size runs from the running allowance)
    and whether they are still a new runner (easy runs only, one a day).
    """
    run_cap: Optional[float] = None
    new_runner: bool = False


class Kind:
    REST = "rest"
    MOBILITY = "mobility"
    STRENGTH = "strength"
    RECOVERY = "recovery"
    EASY = "easy"
    LONG = "long"
    HARD = "hard"
    BENCHMARK = "benchmark"
    OPENER = "opener"
    SHAKEOUT = "shakeout"
    RACE = "race"


@dataclass(frozen=True)
class PlannedSession:
    date: datetime.date
    kind: str
    sport: str = "rest"
    intensity: int = -1
    hours: float = 0.0
    style: Optional[str] = None   # "threshold" | "vo2" for hard sessions
    reason: str = ""
    slot: str = "am"              # "pm" = second session of a double day


@dataclass(frozen=True)
class WeekPlan:
    context: WeekContext
    target_hours: float
    sessions: Tuple[PlannedSession, ...]
    comeback: bool = False
    level: int = 1
    tss: float = 0.0

    def session_on(self, day: datetime.date) -> PlannedSession:
        """The day's main (or only) session."""
        return self.sessions[(day - self.context.week_start).days]

    def sessions_on(self, day: datetime.date) -> List[PlannedSession]:
        """All sessions that day: the main one, then a second ("pm") session on double days."""
        return [s for s in self.sessions if s.date == day and (s.slot == "am" or s.kind != Kind.REST)]

    @property
    def endurance_hours(self) -> float:
        """Endurance training volume (excludes strength, mobility and the race itself)."""
        return round(sum(s.hours for s in self.sessions if s.sport in ENDURANCE_SPORTS and s.kind != Kind.RACE), 4)

    @property
    def sport_hours(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for s in self.sessions:
            if s.sport in ENDURANCE_SPORTS and s.kind != Kind.RACE:
                out[s.sport] = out.get(s.sport, 0.0) + s.hours
        return out

    @property
    def longest_hours(self) -> Dict[str, float]:
        """Longest single session per endurance sport."""
        out: Dict[str, float] = {}
        for s in self.sessions:
            if s.sport in ENDURANCE_SPORTS and s.kind != Kind.RACE:
                out[s.sport] = max(out.get(s.sport, 0.0), s.hours)
        return out


def _floor_slot(hours: float) -> float:
    return math.floor(hours / SLOT + 1e-9) * SLOT


def athlete_level(profile: UserProfile) -> int:
    """
    The athlete's level grows with their fitness: the stated level is a floor, and CTL unlocks the
    next level's session caps. (Each level's caps allow enough volume to reach the next CTL tier,
    so a compliant athlete can progress from beginner to elite.)
    """
    level = LEVELS.index(profile.fitness_level) if profile.fitness_level in LEVELS else 1
    if profile.ctl < 15 and level == 1:
        level = 0
    _, focus = endurance_sports(profile)
    thresholds = CTL_LEVEL_THRESHOLDS[focus[0]] if focus else CTL_LEVEL_THRESHOLDS["cycling"]
    return max(level, sum(profile.ctl >= t for t in thresholds))


def day_capacity(profile: UserProfile, day: datetime.date) -> float:
    key = day.isoformat()
    if key in profile.daily_hours_overrides:
        hours = profile.daily_hours_overrides[key]
    else:
        hours = profile.daily_max_hours.get(day.strftime("%A"), profile.daily_available_hours)
    try:
        return min(8.0, max(0.0, float(hours)))
    except (TypeError, ValueError):
        return 0.0


def endurance_sports(profile: UserProfile) -> Tuple[List[str], List[str]]:
    """(all endurance sports, focused endurance sports in priority order)."""
    sports = [s for s in profile.sports if s in ENDURANCE_SPORTS]
    if not sports:
        sports = [s for s in profile.focused_sports if s in ENDURANCE_SPORTS]
    focus = [s for s in profile.focused_sports if s in sports] or sports[:1]
    return sports, focus


def _sport_weights(profile: UserProfile, sports: Sequence[str], focus: Sequence[str]) -> Dict[str, float]:
    pcts = {s: float(profile.sport_percentages.get(s, 0) or 0) for s in sports}
    if sum(pcts.values()) > 0:
        return pcts
    # priority order matters: main focus 3, other focus sports 2, the rest 1
    return {s: (3.0 if focus and s == focus[0] else 2.0 if s in focus else 1.0) for s in sports}


def _parse_date(value: Optional[str]) -> Optional[datetime.date]:
    if not value:
        return None
    try:
        return datetime.datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


class WeekPlanner:

    @classmethod
    def plan_week(cls, profile: UserProfile, day: datetime.date, as_of: Optional[datetime.date] = None) -> WeekPlan:
        """
        Plans the week containing `day`. `as_of` is the athlete's "today": planning starts from the
        week containing it, using fitness decayed to that point, and assumes the athlete follows the
        plan for the weeks in between.
        """
        week_start = monday_of(day)
        anchor = monday_of(as_of or day)
        if anchor > week_start:
            anchor = week_start

        # Everything below is evaluated as of the start of the anchor week, so the week's plan
        # doesn't change mid-week as sessions are completed (that broke the 10% rule in practice).
        ctl, idle_days = cls._state_at_week_start(profile, anchor)
        history = cls._completed_weeks(profile, anchor)
        comeback = as_of is not None and idle_days is not None and idle_days >= COMEBACK_IDLE_DAYS
        first_ever_week = not history and idle_days is None and ctl <= 5

        level = athlete_level(dataclasses.replace(profile, ctl=ctl))
        chronic_hours = ctl * 7 / TSS_PER_HOUR
        # Entry volume: athletes with no training data start at their level's entry volume; anyone
        # with data starts from what they actually do (floored at the beginner entry volume), so a
        # returning "advanced" athlete doesn't jump straight back to their old volume.
        entry = START_HOURS[level] if ctl <= 5 else START_HOURS[0]
        reference = max(chronic_hours, entry / RAMP, 1.0)
        reference_tss: Optional[float] = None

        # What the athlete actually completed recently is the true baseline for the 10% rule (CTL
        # lags weeks behind, which would stall progression). Not after a gap: then fitness rules.
        sport_reference: Optional[Dict[str, float]] = None
        longest_reference: Optional[Dict[str, float]] = None
        if history and not comeback:
            # baseline = the most recent completed *load* week (recovery weeks don't reset the ramp)
            loads = [w for w in history if week_context(profile.goal, w[0], profile.intensity_weeks,
                                                        profile.uid).week_type == WeekType.LOAD]
            _, base_h, base_tss, base_sports, _ = max(loads or history, key=lambda w: w[0])
            reference = max(base_h, entry / RAMP, 1.0)
            reference_tss = base_tss if base_tss > 0 else None
            sport_reference = base_sports
            # longest session per sport over the recent weeks (None for history without it)
            if base_sports is not None and all(w[4] is not None for w in history if w[3] is not None):
                longest_reference = {}
                for w in history:
                    for sp, h in (w[4] or {}).items():
                        longest_reference[sp] = max(longest_reference.get(sp, 0.0), h)

        current = anchor
        while True:
            plan = cls._plan_single_week(profile, current, reference, level, comeback=comeback and current == anchor,
                                         reintroduce=comeback and current == anchor + datetime.timedelta(days=7),
                                         reference_tss=reference_tss,
                                         first_week=first_ever_week and current == anchor,
                                         sport_reference=sport_reference, longest_reference=longest_reference)
            if current >= week_start:
                return plan
            # weeks cut back for a minor injury/illness are temporary: they don't lower the baseline
            minor_issue = profile.injury == 1 or profile.illness == 1
            if (plan.context.week_type == WeekType.LOAD or plan.comeback) and not minor_issue:
                reference = max(plan.endurance_hours, 1.0)
                # an aerobic-only comeback week is not a fair TSS baseline for the first week back
                reference_tss = None if plan.comeback else plan.tss
                if sport_reference is not None:
                    sport_reference = plan.sport_hours
            if longest_reference is not None:
                longest_reference = dict(longest_reference)
                for sp, h in plan.longest_hours.items():
                    longest_reference[sp] = max(longest_reference.get(sp, 0.0), h)
            current += datetime.timedelta(days=7)

    @classmethod
    def _state_at_week_start(cls, profile: UserProfile, anchor: datetime.date) -> Tuple[float, Optional[int]]:
        """
        (CTL at the end of the day before `anchor`, idle days before `anchor` or None if unknown/never).
        This week's completed sessions are taken back out of CTL/ATL (the model is linear) and the
        result rewound to Sunday, so the week is planned from where it started.
        """
        metrics_date = _parse_date(profile.metrics_date)
        eve = anchor - datetime.timedelta(days=1)
        if metrics_date is None:
            return profile.ctl, None
        if metrics_date < anchor:
            ctl, _ = PhysiologyEngine.project_metrics(profile.ctl, profile.atl, metrics_date, eve)
            return ctl, (anchor - metrics_date).days - 1
        ctl, atl = profile.ctl, profile.atl
        for entry in profile.week_to_date or []:
            day = _parse_date(entry[0]) if isinstance(entry, (list, tuple)) and len(entry) == 2 else None
            if day is not None and anchor <= day <= metrics_date:
                ctl, atl, _ = PhysiologyEngine.apply_session_load(ctl, atl, metrics_date, day, -float(entry[1]))
        ctl, _ = PhysiologyEngine.rewind_metrics(max(ctl, 0.0), max(atl, 0.0), metrics_date, eve)
        # Last session before this week isn't stored; the completed-weeks history tells us.
        idle = None
        trained = {w[0] for w in cls._completed_weeks(profile, anchor) if w[1] > 0}
        for weeks_back in range(1, HISTORY_WEEKS + 1):
            if anchor - datetime.timedelta(weeks=weeks_back) in trained:
                idle = 0 if weeks_back == 1 else 7 * (weeks_back - 1)
                break
        if idle is None and ctl > 5:
            idle = COMEBACK_IDLE_DAYS  # fit athlete with no training in the last 3 weeks: a gap
        return ctl, idle

    @staticmethod
    def _completed_weeks(profile: UserProfile, anchor: datetime.date) -> List[Tuple[
            datetime.date, float, float, Optional[Dict[str, float]], Optional[Dict[str, float]]]]:
        """
        [(week start, hours, tss, {sport: hours} or None, {sport: longest session hours} or None)]
        for the completed weeks before anchor.
        """
        def per_sport(value: Any) -> Optional[Dict[str, float]]:
            if not isinstance(value, dict):
                return None
            return {str(k): float(v) for k, v in value.items() if k in ENDURANCE_SPORTS}

        out = []
        for key, value in (profile.recent_weeks or {}).items():
            start = _parse_date(key)
            if start is None or not isinstance(value, (list, tuple)) or len(value) not in (2, 3, 4):
                continue
            try:
                hours, tss = float(value[0]), float(value[1])
                by_sport = per_sport(value[2]) if len(value) >= 3 else None
                longest = per_sport(value[3]) if len(value) == 4 else None
            except (TypeError, ValueError, AttributeError):
                continue
            if anchor - datetime.timedelta(weeks=HISTORY_WEEKS) <= start < anchor:
                out.append((start, hours, tss, by_sport, longest))
        return out

    # ------------------------------------------------------------------ one week

    @classmethod
    def _plan_single_week(cls, profile: UserProfile, week_start: datetime.date, reference: float,
                          level: int, comeback: bool, reintroduce: bool = False,
                          reference_tss: Optional[float] = None, first_week: bool = False,
                          sport_reference: Optional[Dict[str, float]] = None,
                          longest_reference: Optional[Dict[str, float]] = None) -> WeekPlan:
        ctx = week_context(profile.goal, week_start, profile.intensity_weeks, profile.uid)
        days = [week_start + datetime.timedelta(days=i) for i in range(7)]
        caps = [day_capacity(profile, d) for d in days]
        sports, focus = endurance_sports(profile)

        if profile.injury >= 2 or profile.illness >= 2:
            reason = t(profile.language, "rest.severeInjury" if profile.injury >= 2 else "rest.severeIllness")
            sessions = tuple(PlannedSession(d, Kind.REST, reason=reason) for d in days)
            return WeekPlan(ctx, 0.0, sessions, comeback, level)

        minor_issue = profile.injury == 1 or profile.illness == 1
        strength_sessions = cls._strength_sessions(profile, ctx, level) if not minor_issue else 0
        raw_capacity = min(float(profile.weekly_hours), sum(caps))
        if sports:
            # strength never squeezes out endurance: keep at least one training day and one session's time
            usable_days = sum(1 for c in caps if c >= MIN_SESSION_H)
            strength_sessions = min(strength_sessions, max(0, usable_days - 1),
                                    max(0, int((raw_capacity - MIN_SESSION_H) / STRENGTH_H + 1e-9)))
        capacity = max(0.0, raw_capacity - strength_sessions * STRENGTH_H)
        if ctx.week_type == WeekType.LOAD and not comeback:
            target = min(capacity, RAMP * reference)
        elif ctx.week_type == WeekType.LOAD:
            target = min(capacity, reference)
        else:
            target = min(capacity, FACTORS[ctx.week_type] * reference)
        if minor_issue:
            target *= 0.5
        target = _floor_slot(target)

        allowance = cls.sport_allowances(sport_reference, sports, ctx.week_type, comeback, reference, level,
                                         longest_reference)
        sessions = [PlannedSession(d, Kind.REST) for d in days]
        if not sports:
            sessions = cls._strength_only_week(profile, ctx, days, caps, target)
        else:
            no_intensity = comeback or minor_issue or ctx.week_type in (WeekType.POST_RACE, WeekType.RACE)
            sessions = cls._layout(profile, ctx, days, caps, target, level, sports, focus, no_intensity,
                                   strength_sessions, max_hard=1 if reintroduce else 2, first_week=first_week,
                                   allowance=allowance)
        sessions = cls._apply_race_proximity(profile, ctx, sessions, caps, sports, focus)
        sessions = cls._trim_to(sessions, target)
        if sports and level >= DOUBLES_MIN_LEVEL and ctx.week_type in (WeekType.LOAD, WeekType.RECOVERY) \
                and not comeback and not minor_issue:
            sessions = cls._add_doubles(profile, sessions, caps, target, level, sports, focus, allowance)
        sessions = cls._add_mobility(profile, ctx, sessions, caps)
        if ctx.week_type == WeekType.LOAD and not comeback and reference_tss:
            sessions = cls._cap_load(profile, sessions, RAMP * reference_tss)
        # last: every earlier step can only shorten easy time, so polarisation is checked at the end
        sessions = cls._enforce_polarisation(sessions)
        # a second session that got trimmed away is simply not there
        sessions = [s for s in sessions if s.slot == "am" or s.kind != Kind.REST]
        tss = round(sum(session_tss(s, profile) for s in sessions if s.kind != Kind.RACE), 1)
        return WeekPlan(ctx, target, tuple(sessions), comeback, level, tss)

    @staticmethod
    def sport_allowances(sport_reference: Optional[Dict[str, float]], sports: Sequence[str], week_type: str,
                         comeback: bool, reference: float, level: int = 1,
                         longest_reference: Optional[Dict[str, float]] = None) -> "Allowance":
        """
        Weekly hours each sport may take this week. Always capped by the level's weekly ceiling for
        the sport. With per-sport history (and not after a gap): +10% on the sport's own volume from
        the last load week, or partial credit from the other sports for a sport that is new or
        growing (TRANSFER), never below a small floor so any sport can get started.
        Runs are sized from the athlete's own running, not from fitness credited by other sports:
        the longest run grows by at most 15 min a week (45 min for someone who hasn't run yet).
        """
        out = Allowance({sport: MAX_WEEKLY_H[sport][level] for sport in sports})
        if sport_reference is None or comeback:
            return out
        for sport in sports:
            factor = SPORT_RAMP[sport] if week_type == WeekType.LOAD else FACTORS.get(week_type, 1.0)
            own = sport_reference.get(sport, 0.0)
            credit = sum(TRANSFER[other].get(sport, 0.0) * hours
                         for other, hours in sport_reference.items() if other != sport and other in TRANSFER)
            base = max(own, credit)
            # "10% or one more 30-min session, whichever is more" (overall load still <= +10%),
            # otherwise a sport whose sessions are all at their cap could never grow
            grown = _grow(base, factor, week_type == WeekType.LOAD and own > 0)
            ramped = max(grown, NEW_SPORT_FLOOR_H)
            out[sport] = min(out[sport], ramped, max(RAMP * reference, NEW_SPORT_FLOOR_H))
        if "running" in out:
            longest_run = (longest_reference or {}).get("running", 0.0)
            if longest_reference is not None:
                out.run_cap = max(NEW_RUNNER_RUN_H, longest_run + RUN_STEP_H)
            elif sport_reference.get("running", 0.0) == 0:
                out.run_cap = NEW_RUNNER_RUN_H  # older history without session lengths
            out.new_runner = sport_reference.get("running", 0.0) < ESTABLISHED_RUNNER_H or \
                (longest_reference is not None and longest_run < ESTABLISHED_LONG_RUN_H)
        return out

    @staticmethod
    def _sport_cap(sport: str, level: int, allowance: Optional[Dict[str, float]], kind: str = Kind.EASY) -> float:
        """
        Longest session allowed: the level's cap; runs also <= 40% of the week's running allowance
        and, with running history, <= 15 min more than the longest recent run (first runs: 45 min).
        """
        cap = (MAX_LONG_H if kind == Kind.LONG else MAX_SESSION_H)[sport][level]
        if sport == "running" and allowance is not None:
            cap = min(cap, max(MIN_RUN_CAP_H, RUN_SESSION_SHARE * allowance[sport]))
            run_cap = getattr(allowance, "run_cap", None)
            if run_cap is not None:
                cap = min(cap, run_cap)
        return cap

    @classmethod
    def _add_doubles(cls, profile, sessions, caps, target, level, sports, focus, allowance):
        """
        Elite/pro athletes: when single sessions can't hold the week's volume, add an easy second
        session on days with time left (never on hard, race-week or rest days).
        """
        out = list(sessions)
        weights = _sport_weights(profile, sports, focus)
        used = {sp: 0.0 for sp in sports}
        for s in out:
            if s.sport in used:
                used[s.sport] += s.hours
        deficit = target - sum(used.values())
        share = {sp: weights.get(sp, 0) / (sum(weights.values()) or 1.0) for sp in sports}
        days_by_room = sorted(range(7), key=lambda i: (-(caps[i] - out[i].hours), i))
        for i in days_by_room:
            if deficit < MIN_SESSION_H:
                break
            main = out[i]
            if main.kind not in (Kind.EASY, Kind.RECOVERY, Kind.LONG) or caps[i] - main.hours < MIN_SESSION_H:
                continue
            room = {sp: allowance[sp] - used[sp] for sp in sports}
            options = [sp for sp in sports if room[sp] >= MIN_SESSION_H and weights.get(sp, 0) > 0
                       and not (sp == main.sport == "running" and getattr(allowance, "new_runner", False))]
            if not options:
                break
            # prefer a different sport from the morning session (classic AM swim / PM ride), then
            # whichever sport is furthest below its priority share of the week
            sport = max(options, key=lambda sp: (sp != main.sport, share[sp] * target - used[sp], -sports.index(sp)))
            # every term is >= MIN_SESSION_H here, so the session is long enough
            hours = _floor_slot(min(deficit, caps[i] - main.hours, room[sport], cls._sport_cap(sport, level, allowance),
                                    MAX_RECOVERY_H[level] if main.kind == Kind.RECOVERY else 24.0))
            kind, intensity = (Kind.RECOVERY, 1) if main.kind == Kind.RECOVERY else (Kind.EASY, 2)
            out.append(PlannedSession(main.date, kind, sport, intensity, hours, slot="pm"))
            used[sport] += hours
            deficit -= hours
        return out

    @classmethod
    def _layout(cls, profile, ctx: WeekContext, days, caps, target, level, sports, focus, no_intensity,
                strength_sessions, max_hard=2, first_week=False, allowance=None):
        n_rest_min = 2 if level == 0 or target < 4 else 1
        rest = {i for i in range(7) if caps[i] < MIN_SESSION_H}
        rest.update([i for i in REST_DAY_PREFERENCE if i not in rest][:max(0, n_rest_min - len(rest))])
        train = [i for i in range(7) if i not in rest]
        sessions: List[PlannedSession] = [PlannedSession(d, Kind.REST) for d in days]
        if not train or target < MIN_SESSION_H:
            return sessions

        used = {sp: 0.0 for sp in sports}

        def room(sport):
            return allowance[sport] - used[sport]

        def max_session(sport, kind=Kind.EASY):
            return min(cls._sport_cap(sport, level, allowance, kind), room(sport))

        # 1. Long session on the weekend day with the most time (chosen first so a lone big
        #    day isn't used up by a hard session)
        free = list(train)
        long_day = None
        if target >= LONG_SESSION_MIN_WEEK_H and ctx.week_type != WeekType.RACE:
            weekend = [i for i in (5, 6) if i in free and caps[i] >= MIN_LONG_H]
            pool = weekend or [i for i in free if caps[i] >= MIN_LONG_H]
            if pool:
                long_day = max(pool, key=lambda i: (caps[i], -abs(i - 5)))
        weights = _sport_weights(profile, sports, focus)
        long_options = [s for s in focus if max_session(s, Kind.LONG) >= MIN_LONG_H] or \
            [s for s in sports if max_session(s, Kind.LONG) >= MIN_LONG_H]
        if long_day is not None and long_options:
            long_sport = max(long_options, key=lambda s: (weights.get(s, 0), MAX_LONG_H[s][level]))
            hours = _floor_slot(min(max_session(long_sport, Kind.LONG), caps[long_day],
                                    max(MIN_LONG_H, LONG_SHARE * target)))
            sessions[long_day] = PlannedSession(days[long_day], Kind.LONG, long_sport, 2, hours)
            used[long_sport] += hours
            free.remove(long_day)
        else:
            long_day = None

        # 2. Hard sessions (never Monday, never on consecutive days)
        hard_days: List[int] = []
        # new runners run easy only (tendons adapt slower than the heart): intensity goes to
        # another sport, or the week stays easy
        quality = [sp for sp in focus if not (sp == "running" and getattr(allowance, "new_runner", False))] or \
            [sp for sp in sports if sp != "running"]
        if not no_intensity and quality:
            n_hard = {WeekType.LOAD: 1 if (level == 0 or target < 5 or len(train) < 4) else 2,
                      WeekType.RECOVERY: 0 if level == 0 else 1,
                      WeekType.TAPER: 1 if level == 0 else 2}[ctx.week_type]
            n_hard = min(n_hard, max_hard)  # first week after a comeback: reintroduce one session
            while n_hard > 0 and min(MAX_HARD_H[level], HARD_SHARE * target / n_hard) < MIN_HARD_H:
                n_hard -= 1
            budget = HARD_SHARE * target / n_hard if n_hard else 0
            styles = cls._hard_styles(ctx, level)
            for i in HARD_DAY_PREFERENCE:
                if len(hard_days) >= n_hard:
                    break
                if i not in free or any(abs(i - j) == 1 for j in hard_days):
                    continue
                rotation = quality[len(hard_days) % len(quality):] + quality[:len(hard_days) % len(quality)]
                sport = next((sp for sp in rotation if max_session(sp) >= MIN_HARD_H), rotation[0])
                hours = _floor_slot(min(budget, MAX_HARD_H[level], max_session(sport), caps[i]))
                if hours < MIN_HARD_H:
                    continue
                style = styles[len(hard_days) % len(styles)]
                sessions[i] = PlannedSession(days[i], Kind.HARD, sport, 5 if style == "vo2" else 4, hours, style)
                used[sport] += hours
                hard_days.append(i)
            cls._maybe_benchmark(profile, ctx, sessions, hard_days, caps, target, quality, first_week)
            free = [i for i in free if i not in hard_days]

        # 3. Easy sessions fill the remaining endurance time, keeping enough free days for strength
        remaining = target - sum(s.hours for s in sessions if s.sport in ENDURANCE_SPORTS)
        strength_days = [i for i in sorted(free, key=lambda d: (caps[d], STRENGTH_DAY_PREFERENCE.index(d)))
                         if caps[i] >= STRENGTH_H and (i + 1) not in hard_days][:strength_sessions]
        easy_days = [i for i in free if i not in strength_days]
        if easy_days and remaining > sum(min(caps[i], 3.0) for i in easy_days) + 1e-9:
            # not enough room without the strength days: endurance comes first
            strength_days = strength_days[:max(0, len(strength_days) - 1)]
            easy_days = [i for i in free if i not in strength_days]
        cls._fill_easy(profile, sessions, days, caps, easy_days, remaining, level, sports, focus, hard_days, long_day,
                       allowance)

        # 4. Strength on the remaining day(s): never the day before a hard session
        for i in strength_days:  # never given to easy sessions above
            sessions[i] = PlannedSession(days[i], Kind.STRENGTH, "strength", 2, STRENGTH_H)
        return sessions

    @staticmethod
    def _strength_sessions(profile: UserProfile, ctx: WeekContext, level: int) -> int:
        if "strength" not in profile.sports or ctx.week_type not in (WeekType.LOAD, WeekType.RECOVERY):
            return 0
        return 1 if (level == 0 or ctx.week_type == WeekType.RECOVERY) else 2

    @staticmethod
    def _hard_styles(ctx: WeekContext, level: int) -> List[str]:
        if ctx.week_type == WeekType.RECOVERY or level == 0:
            return ["threshold"]
        if ctx.phase in (TrainingPhase.BUILD, TrainingPhase.PEAK, TrainingPhase.TAPER):
            return ["vo2", "threshold"]
        return ["threshold"]

    @staticmethod
    def threshold_known(profile: UserProfile, sport: str) -> bool:
        known = profile.known_thresholds
        if known is None:
            return True
        return SPORT_THRESHOLD_KEY[sport] in known or (sport == "running" and "running_power" in known)

    @classmethod
    def _maybe_benchmark(cls, profile, ctx, sessions, hard_days, caps, target, focus, first_week):
        """
        First hard session after a recovery week is a test; so is a brand-new athlete's first hard
        session when we have no threshold for their main sport.
        """
        if not hard_days or ctx.week_type != WeekType.LOAD or ctx.phase in (TrainingPhase.PEAK, TrainingPhase.TAPER):
            return
        previous = week_context(profile.goal, ctx.week_start - datetime.timedelta(days=7),
                                profile.intensity_weeks, profile.uid)
        unknown = [s for s in focus if not cls.threshold_known(profile, s)]
        after_recovery = previous.week_type in (WeekType.RECOVERY, WeekType.POST_RACE)
        if not (after_recovery or (unknown and first_week)):
            return
        first = hard_days[0]
        sport = unknown[0] if unknown else sessions[first].sport
        others = sum(sessions[i].hours for i in hard_days[1:])
        if caps[first] < BENCHMARK_H or others + BENCHMARK_H > MAX_HARD_SHARE * target:
            return
        sessions[first] = PlannedSession(sessions[first].date, Kind.BENCHMARK, sport, 5, BENCHMARK_H)

    @classmethod
    def _fill_easy(cls, profile, sessions, days, caps, free, remaining, level, sports, focus, hard_days, long_day,
                   allowance=None):
        weights = _sport_weights(profile, sports, focus)
        long_cap = sessions[long_day].hours if long_day is not None else None
        biggest_session = max(cls._sport_cap(s, level, allowance) for s in sports)

        def follows_quality(i):
            # Day after a hard session is recovery. Back-to-back weekend endurance is fine.
            return (i - 1) in hard_days

        def ceiling(i):
            c = min(caps[i], biggest_session, MAX_RECOVERY_H[level] if follows_quality(i) else 24.0)
            return min(c, long_cap) if long_cap else c

        n = min(len(free), int(remaining / MIN_SESSION_H + 1e-9))
        chosen = sorted(free, key=lambda i: (-ceiling(i), i))[:n]
        alloc: Dict[int, float] = {}
        left, count = remaining, len(chosen)
        for i in sorted(chosen, key=lambda i: (ceiling(i), i)):
            alloc[i] = _floor_slot(min(ceiling(i), left / count))
            left -= alloc[i]
            count -= 1

        if long_day is not None and left >= SLOT:
            s = sessions[long_day]
            room = min(cls._sport_cap(s.sport, level, allowance, Kind.LONG), caps[long_day], LONG_MAX_SHARE * (
                remaining + sum(x.hours for x in sessions if x.sport in ENDURANCE_SPORTS))) - s.hours
            room = min(room, allowance[s.sport] - sum(x.hours for x in sessions if x.sport == s.sport))
            extra = _floor_slot(min(room, left))
            if extra > 0:
                sessions[long_day] = PlannedSession(s.date, s.kind, s.sport, s.intensity, s.hours + extra)

        # Sport choice: largest shortfall against the athlete's sport split, among sports that
        # can safely hold a session of this length.
        totals = {sp: 0.0 for sp in sports}
        counts = {sp: 0 for sp in sports}
        for s in sessions:
            if s.sport in totals:
                totals[s.sport] += s.hours
                counts[s.sport] += 1
        planned_endurance = sum(totals.values()) + sum(alloc.values())
        weight_sum = sum(weights.values()) or 1.0
        limits = profile.sport_sessions_per_week or {}
        carry = 0.0
        for i in sorted(alloc, key=lambda i: (-alloc[i], i)):
            # >= MIN_SESSION_H; plus any time a shorter-capped sport couldn't use on an earlier day
            hours = min(alloc[i] + carry, ceiling(i))
            carry = alloc[i] + carry - hours
            candidates = [sp for sp in sports if weights.get(sp, 0) > 0] or list(sports)
            allowed = [sp for sp in candidates if not limits.get(sp) or counts[sp] < int(limits[sp])] or candidates
            allowed = [sp for sp in allowed if allowance[sp] - totals[sp] >= MIN_SESSION_H]
            if not allowed:
                continue  # every sport is at its safe weekly limit: leave the day free

            def cap(sp):
                return min(cls._sport_cap(sp, level, allowance), allowance[sp] - totals[sp])

            def shortfall(sp):
                return weights.get(sp, 0) / weight_sum * planned_endurance - totals[sp]

            # the sport furthest below its share gets the day (priorities win), clipped to its cap;
            # whatever it can't use carries over to the next day
            sport = max(allowed, key=lambda sp: (shortfall(sp) > MIN_SESSION_H, cap(sp) >= hours,
                                                 shortfall(sp), -sports.index(sp)))
            placed = _floor_slot(min(hours, cap(sport)))  # both >= MIN_SESSION_H
            carry += hours - placed
            hours = placed
            kind, intensity = (Kind.RECOVERY, 1) if follows_quality(i) else (Kind.EASY, 2)
            sessions[i] = PlannedSession(days[i], kind, sport, intensity, hours)
            totals[sport] += hours
            counts[sport] += 1

        # Top-up: time a short-capped sport couldn't use goes to easy sessions with room left
        # (within their day, session and weekly sport caps), so priorities never cost volume.
        week_total = sum(x.hours for x in sessions if x.sport in ENDURANCE_SPORTS) + carry
        top_up_days = list(alloc) + ([long_day] if long_day is not None else [])
        for i in sorted(top_up_days, key=lambda i: (sessions[i].kind == Kind.LONG, i)):
            if carry < SLOT:
                break
            s = sessions[i]
            if s.kind not in (Kind.EASY, Kind.RECOVERY, Kind.LONG):
                continue
            if s.kind == Kind.LONG:
                limit = min(caps[i], cls._sport_cap(s.sport, level, allowance, Kind.LONG), LONG_MAX_SHARE * week_total)
            else:
                limit = min(ceiling(i), cls._sport_cap(s.sport, level, allowance))
            limit = min(limit, s.hours + allowance[s.sport] - totals[s.sport])
            extra = _floor_slot(min(carry, limit - s.hours))
            if extra > 0:
                sessions[i] = dataclasses.replace(s, hours=s.hours + extra)
                totals[s.sport] += extra
                carry -= extra

    @staticmethod
    def _cap_load(profile: UserProfile, sessions: List[PlannedSession], max_tss: float) -> List[PlannedSession]:
        """Shortens the longest easy sessions (5 min at a time) until weekly TSS <= max_tss."""
        out = list(sessions)
        per = [session_tss(s, profile) for s in out]
        while sum(per) > max_tss + 1e-9:
            easy = [i for i, s in enumerate(out) if s.kind in (Kind.EASY, Kind.LONG, Kind.RECOVERY)]
            if not easy:
                return out
            i = max(easy, key=lambda i: (out[i].hours, i))
            s = out[i]
            hours = _floor_slot(s.hours - SLOT)
            out[i] = (dataclasses.replace(s, hours=hours) if hours >= MIN_SESSION_H
                      else PlannedSession(s.date, Kind.REST, slot=s.slot))
            per[i] = session_tss(out[i], profile)
        return out

    @staticmethod
    def _trim_to(sessions: List[PlannedSession], limit: float) -> List[PlannedSession]:
        """
        Race-week sessions are inserted after the layout; if they push the week past its volume
        target, drop the least important sessions (easy first, the opener last). The race and the
        shake-out are always kept.
        """
        order = (Kind.RECOVERY, Kind.EASY, Kind.LONG, Kind.HARD, Kind.BENCHMARK, Kind.OPENER)
        out = list(sessions)

        def volume():
            return sum(s.hours for s in out if s.sport in ENDURANCE_SPORTS and s.kind != Kind.RACE)

        while volume() > limit + 1e-9:
            removable = [i for i, s in enumerate(out) if s.kind in order and s.sport in ENDURANCE_SPORTS]
            if not removable:
                return out
            i = min(removable, key=lambda i: (order.index(out[i].kind), out[i].hours, -i))
            out[i] = PlannedSession(out[i].date, Kind.REST)
        return out

    @staticmethod
    def _enforce_polarisation(sessions: List[PlannedSession]) -> List[PlannedSession]:
        """If too few easy hours could be placed, downgrade the latest hard sessions until <= 25%."""
        out = list(sessions)
        while True:
            endurance = sum(s.hours for s in out if s.sport in ENDURANCE_SPORTS)
            hard = [i for i, s in enumerate(out) if s.kind in (Kind.HARD, Kind.BENCHMARK)]
            if not hard or sum(out[i].hours for i in hard) <= MAX_HARD_SHARE * endurance + 1e-9:
                return out
            s = out[hard[-1]]
            out[hard[-1]] = dataclasses.replace(s, kind=Kind.EASY, intensity=2, style=None)

    @classmethod
    def _strength_only_week(cls, profile, ctx, days, caps, target):
        sessions = [PlannedSession(d, Kind.REST) for d in days]
        if "strength" not in profile.sports or ctx.week_type not in (WeekType.LOAD, WeekType.RECOVERY):
            return sessions
        placed = 0.0
        for i in (1, 3, 5):
            if caps[i] >= STRENGTH_H and placed + 0.75 <= max(target, 0.75):
                hours = _floor_slot(min(0.75, caps[i]))
                sessions[i] = PlannedSession(days[i], Kind.STRENGTH, "strength", 2, hours)
                placed += hours
        return sessions

    @classmethod
    def _apply_race_proximity(cls, profile, ctx, sessions, caps, sports, focus):
        """Race-week routine around the event date, whichever week the surrounding days fall in."""
        race_date = ctx.race_date
        if race_date is None:
            return sessions
        race_sport = next((s for s in (profile.goal.sports or []) if s in sports), focus[0] if focus else None)
        out = list(sessions)
        for i, s in enumerate(out):
            delta = (s.date - race_date).days
            if delta == 0 and race_sport:
                hours = (profile.goal.target_time / 3600) if profile.goal.target_time else DEFAULT_RACE_H[race_sport]
                out[i] = PlannedSession(s.date, Kind.RACE, race_sport, 4, round(min(hours, 16.0), 2),
                                        reason=profile.goal.name or t(profile.language, "race.defaultName"))
            elif delta == -1 and race_sport:
                out[i] = (PlannedSession(s.date, Kind.SHAKEOUT, race_sport, 2, SHAKEOUT_H)
                          if caps[i] >= SHAKEOUT_H else PlannedSession(s.date, Kind.REST))
            elif delta == -2 or delta == 1:
                out[i] = PlannedSession(s.date, Kind.REST,
                                        reason=t(profile.language, "rest.raceWeek" if delta < 0 else "rest.postRace"))
            elif delta == -3 and race_sport:
                hours = _floor_slot(min(OPENER_H, caps[i]))
                out[i] = (PlannedSession(s.date, Kind.OPENER, race_sport, 2, hours)
                          if hours >= MIN_SESSION_H else PlannedSession(s.date, Kind.REST))
            elif delta in (2, 3) and s.kind not in (Kind.REST, Kind.MOBILITY):
                out[i] = PlannedSession(s.date, Kind.RECOVERY, s.sport if s.sport in sports else race_sport, 1,
                                        _floor_slot(min(s.hours, 0.75)))
            elif -6 <= delta <= -4 and s.kind in (Kind.HARD, Kind.BENCHMARK, Kind.LONG):
                # last quality before the race stays short: no long or hard sessions in the final week
                out[i] = PlannedSession(s.date, Kind.EASY, s.sport, 2, _floor_slot(min(s.hours, 1.0)))
        return out

    @classmethod
    def _add_mobility(cls, profile, ctx, sessions, caps):
        """
        As many 20-min mobility sessions as the athlete asked for (default 2): on free rest days
        first, then as an evening session after an easy, recovery or long session with time to
        spare. Never after hard work, never in race week, never as a third session in a day.
        """
        if "stretching" not in profile.sports:
            return sessions
        wanted = min(7, max(0, int(profile.sport_sessions_per_week.get("stretching", MOBILITY_PER_WEEK) or 0)))
        out = list(sessions)
        mains = [s for s in out if s.slot == "am"]
        for i, s in enumerate(mains):
            if wanted and s.kind == Kind.REST and caps[i] >= MOBILITY_H and not s.reason:
                out[out.index(s)] = PlannedSession(s.date, Kind.MOBILITY, "stretching", 1, MOBILITY_H)
                wanted -= 1
        if not wanted or ctx.week_type == WeekType.RACE:
            return out
        busy = {s.date for s in out if s.slot == "pm"}
        used = {d: sum(s.hours for s in out if s.date == d) for d in {s.date for s in out}}
        spare = [i for i, s in enumerate(mains) if s.kind in (Kind.EASY, Kind.RECOVERY, Kind.LONG)
                 and s.date not in busy and caps[i] - used[s.date] >= MOBILITY_H - 1e-9]
        for i in sorted(spare, key=lambda i: (-(caps[i] - used[mains[i].date]), i))[:wanted]:
            out.append(PlannedSession(mains[i].date, Kind.MOBILITY, "stretching", 1, MOBILITY_H, slot="pm"))
        return out
