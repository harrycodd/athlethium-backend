"""
Periodization: which kind of week a given Monday-to-Sunday week is.

- With a target event, weeks are counted *backwards* from the race week so the block always
  ends in: ... load, load, load, taper week, race week. Recovery weeks fall every
  `cycle_length` weeks before that, and the week after the race is a recovery week.
- Without an event (or after it), the load/recovery cycle runs on continuous week numbers
  (no ISO week-53 glitches) offset per athlete, so not every user deloads the same week.
"""

import datetime
import zlib
from dataclasses import dataclass
from typing import Optional

from core.models import Goal, TrainingPhase

EPOCH_MONDAY = datetime.date(2024, 1, 1)  # a Monday


class WeekType:
    LOAD = "load"
    RECOVERY = "recovery"
    TAPER = "taper"
    RACE = "race"
    POST_RACE = "post_race"


@dataclass(frozen=True)
class WeekContext:
    week_start: datetime.date
    week_type: str
    phase: TrainingPhase
    weeks_to_goal: Optional[int]  # 0 = race week; None = no upcoming goal
    race_date: Optional[datetime.date] = None


def monday_of(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def parse_goal_date(goal: Optional[Goal]) -> Optional[datetime.date]:
    if not goal or not goal.date:
        return None
    if isinstance(goal.date, datetime.date):
        return goal.date
    try:
        return datetime.datetime.strptime(str(goal.date), "%Y-%m-%d").date()
    except ValueError:
        return None


def cycle_length(intensity_weeks: int) -> int:
    """Load weeks + 1 recovery week, kept to the 3-4 week range."""
    return min(4, max(3, int(intensity_weeks) + 1))


def _phase_for(weeks_to_goal: int) -> TrainingPhase:
    """Phase for weeks_to_goal >= 2 (taper and race weeks are decided by the caller)."""
    if weeks_to_goal <= 4:
        return TrainingPhase.PEAK
    if weeks_to_goal <= 12:
        return TrainingPhase.BUILD
    return TrainingPhase.BASE


def week_context(goal: Optional[Goal], week_start: datetime.date, intensity_weeks: int, uid: str) -> WeekContext:
    week_start = monday_of(week_start)
    length = cycle_length(intensity_weeks)
    race_date = parse_goal_date(goal)

    if race_date is not None:
        weeks_to_goal = (monday_of(race_date) - week_start).days // 7
        if weeks_to_goal == 0:
            return WeekContext(week_start, WeekType.RACE, TrainingPhase.RACE, 0, race_date)
        if weeks_to_goal == 1:
            return WeekContext(week_start, WeekType.TAPER, TrainingPhase.TAPER, 1, race_date)
        if weeks_to_goal == -1:
            return WeekContext(week_start, WeekType.POST_RACE, TrainingPhase.RECOVERY, None, race_date)
        if weeks_to_goal >= 2:
            position = (weeks_to_goal - 2) % length
            week_type = WeekType.RECOVERY if position == length - 1 else WeekType.LOAD
            return WeekContext(week_start, week_type, _phase_for(weeks_to_goal), weeks_to_goal, race_date)

    offset = zlib.crc32(uid.encode("utf-8")) % length
    position = ((week_start - EPOCH_MONDAY).days // 7 + offset) % length
    week_type = WeekType.RECOVERY if position == length - 1 else WeekType.LOAD
    return WeekContext(week_start, week_type, TrainingPhase.BASE, None, None)
