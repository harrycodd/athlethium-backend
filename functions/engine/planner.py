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

import datetime
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from core.models import TrainingPhase, UserProfile
from engine.periodization import WeekContext, WeekType, monday_of, week_context
from engine.physiology import PhysiologyEngine
from engine.sessions import session_tss

ENDURANCE_SPORTS = ("cycling", "running", "swimming")
LEVELS = ("beginner", "intermediate", "advanced", "elite")

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
SHAKEOUT_H = 25 / 60
OPENER_H = 0.75
SLOT = 1 / 12                # durations are rounded down to 5 minutes

START_HOURS = (2.5, 4.0, 6.0, 8.0)  # first week for athletes with no training history, by level
MAX_HARD_H = (1.0, 1.25, 1.5, 1.75)
MAX_RECOVERY_H = (0.75, 1.0, 1.5, 2.0)  # day after a hard or long session
MAX_SESSION_H = {"cycling": (1.5, 2.0, 2.5, 3.0), "running": (1.0, 1.25, 1.5, 1.75), "swimming": (1.0, 1.25, 1.5, 1.75)}
MAX_LONG_H = {"cycling": (2.5, 3.5, 4.5, 5.5), "running": (1.25, 1.75, 2.25, 2.75), "swimming": (1.0, 1.25, 1.5, 2.0)}
DEFAULT_RACE_H = {"cycling": 2.0, "running": 1.0, "swimming": 0.75}

# Weekday preferences (0 = Monday). Hard sessions never go on Monday.
HARD_DAY_PREFERENCE = (1, 3, 2, 4, 6, 5)
REST_DAY_PREFERENCE = (0, 4, 2, 6, 3, 1, 5)
STRENGTH_DAY_PREFERENCE = (2, 4, 0, 6, 3, 1, 5)
SPORT_THRESHOLD_KEY = {"cycling": "cycling_power", "running": "running_pace", "swimming": "swim_pace"}


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


@dataclass(frozen=True)
class WeekPlan:
    context: WeekContext
    target_hours: float
    sessions: Tuple[PlannedSession, ...]
    comeback: bool = False
    level: int = 1
    tss: float = 0.0

    def session_on(self, day: datetime.date) -> PlannedSession:
        return self.sessions[(day - self.context.week_start).days]

    @property
    def endurance_hours(self) -> float:
        """Endurance training volume (excludes strength, mobility and the race itself)."""
        return round(sum(s.hours for s in self.sessions if s.sport in ENDURANCE_SPORTS and s.kind != Kind.RACE), 4)


def _floor_slot(hours: float) -> float:
    return math.floor(hours / SLOT + 1e-9) * SLOT


def athlete_level(profile: UserProfile) -> int:
    level = LEVELS.index(profile.fitness_level) if profile.fitness_level in LEVELS else 1
    if profile.ctl >= 90:
        level = max(level, 3)
    elif profile.ctl >= 65:
        level = max(level, 2)
    elif profile.ctl < 15 and level == 1:
        level = 0
    return level


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
    return {s: (2.0 if s in focus else 1.0) for s in sports}


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

        metrics_date = _parse_date(profile.metrics_date)
        ctl = profile.ctl
        if metrics_date is not None and metrics_date < anchor:
            ctl, _ = PhysiologyEngine.project_metrics(profile.ctl, profile.atl, metrics_date,
                                                      anchor - datetime.timedelta(days=1))
        comeback = (metrics_date is not None and as_of is not None
                    and (as_of - metrics_date).days - 1 >= COMEBACK_IDLE_DAYS)

        level = athlete_level(profile)
        chronic_hours = ctl * 7 / TSS_PER_HOUR
        # Entry volume: athletes with no training data start at their level's entry volume; anyone
        # with data starts from what they actually do (floored at the beginner entry volume), so a
        # returning "advanced" athlete doesn't jump straight back to their old volume.
        entry = START_HOURS[level] if profile.ctl <= 5 else START_HOURS[0]
        reference = max(chronic_hours, entry / RAMP, 1.0)

        current = anchor
        reference_tss: Optional[float] = None
        while True:
            plan = cls._plan_single_week(profile, current, reference, level, comeback=comeback and current == anchor,
                                         reintroduce=comeback and current == anchor + datetime.timedelta(days=7),
                                         reference_tss=reference_tss,
                                         first_week=metrics_date is None and current == anchor)
            if current >= week_start:
                return plan
            if plan.context.week_type == WeekType.LOAD or plan.comeback:
                reference = max(plan.endurance_hours, 1.0)
                # an aerobic-only comeback week is not a fair TSS baseline for the first week back
                reference_tss = None if plan.comeback else plan.tss
            current += datetime.timedelta(days=7)

    # ------------------------------------------------------------------ one week

    @classmethod
    def _plan_single_week(cls, profile: UserProfile, week_start: datetime.date, reference: float,
                          level: int, comeback: bool, reintroduce: bool = False,
                          reference_tss: Optional[float] = None, first_week: bool = False) -> WeekPlan:
        ctx = week_context(profile.goal, week_start, profile.intensity_weeks, profile.uid)
        days = [week_start + datetime.timedelta(days=i) for i in range(7)]
        caps = [day_capacity(profile, d) for d in days]
        sports, focus = endurance_sports(profile)

        if profile.injury >= 2 or profile.illness >= 2:
            reason = "Severe injury" if profile.injury >= 2 else "Severe illness"
            sessions = tuple(PlannedSession(d, Kind.REST, reason=f"{reason}: complete rest until cleared.")
                             for d in days)
            return WeekPlan(ctx, 0.0, sessions, comeback, level)

        minor_issue = profile.injury == 1 or profile.illness == 1
        strength_sessions = cls._strength_sessions(profile, ctx, level) if not minor_issue else 0
        capacity = max(0.0, min(float(profile.weekly_hours), sum(caps)) - strength_sessions * STRENGTH_H)
        if ctx.week_type == WeekType.LOAD and not comeback:
            target = min(capacity, RAMP * reference)
        elif ctx.week_type == WeekType.LOAD:
            target = min(capacity, reference)
        else:
            target = min(capacity, FACTORS[ctx.week_type] * reference)
        if minor_issue:
            target *= 0.5
        target = _floor_slot(target)

        sessions = [PlannedSession(d, Kind.REST) for d in days]
        if not sports:
            sessions = cls._strength_only_week(profile, ctx, days, caps, target)
        else:
            no_intensity = comeback or minor_issue or ctx.week_type in (WeekType.POST_RACE, WeekType.RACE)
            sessions = cls._layout(profile, ctx, days, caps, target, level, sports, focus, no_intensity,
                                   strength_sessions, max_hard=1 if reintroduce else 2, first_week=first_week)
        sessions = cls._apply_race_proximity(profile, ctx, sessions, caps, sports, focus)
        sessions = cls._trim_to(sessions, target)
        sessions = cls._add_mobility(profile, sessions, caps)
        if ctx.week_type == WeekType.LOAD and not comeback and reference_tss:
            sessions = cls._cap_load(profile, sessions, RAMP * reference_tss)
        # last: every earlier step can only shorten easy time, so polarisation is checked at the end
        sessions = cls._enforce_polarisation(sessions)
        tss = round(sum(session_tss(s, profile) for s in sessions if s.kind != Kind.RACE), 1)
        return WeekPlan(ctx, target, tuple(sessions), comeback, level, tss)

    @classmethod
    def _layout(cls, profile, ctx: WeekContext, days, caps, target, level, sports, focus, no_intensity,
                strength_sessions, max_hard=2, first_week=False):
        n_rest_min = 2 if level == 0 or target < 4 else 1
        rest = {i for i in range(7) if caps[i] < MIN_SESSION_H}
        rest.update([i for i in REST_DAY_PREFERENCE if i not in rest][:max(0, n_rest_min - len(rest))])
        train = [i for i in range(7) if i not in rest]
        sessions: List[PlannedSession] = [PlannedSession(d, Kind.REST) for d in days]
        if not train or target < MIN_SESSION_H:
            return sessions

        def max_session(sport):
            return MAX_SESSION_H[sport][level]

        # 1. Long session on the weekend day with the most time (chosen first so a lone big
        #    day isn't used up by a hard session)
        free = list(train)
        long_day = None
        if target >= LONG_SESSION_MIN_WEEK_H and ctx.week_type != WeekType.RACE:
            weekend = [i for i in (5, 6) if i in free and caps[i] >= MIN_LONG_H]
            pool = weekend or [i for i in free if caps[i] >= MIN_LONG_H]
            if pool:
                long_day = max(pool, key=lambda i: (caps[i], -abs(i - 5)))
        long_sport = max(focus, key=lambda s: MAX_LONG_H[s][level])
        if long_day is not None:
            hours = _floor_slot(min(MAX_LONG_H[long_sport][level], caps[long_day], max(MIN_LONG_H, LONG_SHARE * target)))
            sessions[long_day] = PlannedSession(days[long_day], Kind.LONG, long_sport, 2, hours)
            free.remove(long_day)

        # 2. Hard sessions (never Monday, never on consecutive days)
        hard_days: List[int] = []
        if not no_intensity:
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
                sport = focus[len(hard_days) % len(focus)]
                hours = _floor_slot(min(budget, MAX_HARD_H[level], max_session(sport), caps[i]))
                if hours < MIN_HARD_H:
                    continue
                style = styles[len(hard_days) % len(styles)]
                sessions[i] = PlannedSession(days[i], Kind.HARD, sport, 5 if style == "vo2" else 4, hours, style)
                hard_days.append(i)
            cls._maybe_benchmark(profile, ctx, sessions, hard_days, caps, target, focus, first_week)
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
        cls._fill_easy(profile, sessions, days, caps, easy_days, remaining, level, sports, focus, hard_days, long_day)

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
    def _fill_easy(cls, profile, sessions, days, caps, free, remaining, level, sports, focus, hard_days, long_day):
        weights = _sport_weights(profile, sports, focus)
        long_cap = sessions[long_day].hours if long_day is not None else None
        biggest_session = max(MAX_SESSION_H[s][level] for s in sports)

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
            room = min(MAX_LONG_H[s.sport][level], caps[long_day], LONG_MAX_SHARE * (remaining + sum(
                x.hours for x in sessions if x.sport in ENDURANCE_SPORTS))) - s.hours
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
        for i in sorted(alloc, key=lambda i: (-alloc[i], i)):
            hours = alloc[i]  # >= MIN_SESSION_H: n days chosen so each share is at least that
            candidates = [sp for sp in sports if weights.get(sp, 0) > 0] or list(sports)
            allowed = [sp for sp in candidates if not limits.get(sp) or counts[sp] < int(limits[sp])] or candidates
            fits = [sp for sp in allowed if MAX_SESSION_H[sp][level] >= hours] or allowed

            def shortfall(sp):
                return weights.get(sp, 0) / weight_sum * planned_endurance - totals[sp]

            sport = max(fits, key=lambda sp: (shortfall(sp), -sports.index(sp)))
            hours = _floor_slot(min(hours, MAX_SESSION_H[sport][level]))
            kind, intensity = (Kind.RECOVERY, 1) if follows_quality(i) else (Kind.EASY, 2)
            sessions[i] = PlannedSession(days[i], kind, sport, intensity, hours)
            totals[sport] += hours
            counts[sport] += 1

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
            out[i] = (PlannedSession(s.date, s.kind, s.sport, s.intensity, hours) if hours >= MIN_SESSION_H
                      else PlannedSession(s.date, Kind.REST))
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
            out[hard[-1]] = PlannedSession(s.date, Kind.EASY, s.sport, 2, s.hours)

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
                                        reason=profile.goal.name or "Race")
            elif delta == -1 and race_sport:
                out[i] = (PlannedSession(s.date, Kind.SHAKEOUT, race_sport, 2, SHAKEOUT_H)
                          if caps[i] >= SHAKEOUT_H else PlannedSession(s.date, Kind.REST))
            elif delta == -2 or delta == 1:
                out[i] = PlannedSession(s.date, Kind.REST, reason="Race week rest" if delta < 0 else "Post-race rest")
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
    def _add_mobility(cls, profile, sessions, caps):
        if "stretching" not in profile.sports:
            return sessions
        out = list(sessions)
        for i, s in enumerate(out):
            if s.kind == Kind.REST and caps[i] >= MOBILITY_H and not s.reason:
                out[i] = PlannedSession(s.date, Kind.MOBILITY, "stretching", 1, MOBILITY_H)
                break
        return out
