import datetime

import pytest

from core.models import Goal, TrainingPhase
from engine.periodization import WeekType, cycle_length, monday_of, parse_goal_date, week_context
from tests.factories import make_goal

D = datetime.date
RACE = "2026-11-29"  # Sunday; race week starts Mon 2026-11-23


def ctx(week_start, goal=RACE, intensity_weeks=3, uid="u1"):
    return week_context(make_goal(goal) if goal else None, week_start, intensity_weeks, uid)


class TestWithGoal:
    def test_race_taper_and_post_race_weeks(self):
        assert ctx(D(2026, 11, 23)).week_type == WeekType.RACE
        assert ctx(D(2026, 11, 26)).week_type == WeekType.RACE  # any day maps to its Monday
        assert ctx(D(2026, 11, 16)).week_type == WeekType.TAPER
        post = ctx(D(2026, 11, 30))
        assert post.week_type == WeekType.POST_RACE and post.phase == TrainingPhase.RECOVERY

    def test_block_counts_back_from_the_race(self):
        # 4-week cycle: weeks_to_goal 2,3,4 load; 5 recovery; 6,7,8 load; 9 recovery ...
        types = {n: ctx(D(2026, 11, 23) - datetime.timedelta(weeks=n)).week_type for n in range(2, 14)}
        assert [n for n, t in types.items() if t == WeekType.RECOVERY] == [5, 9, 13]

    def test_three_week_cycle(self):
        types = {n: ctx(D(2026, 11, 23) - datetime.timedelta(weeks=n), intensity_weeks=2).week_type
                 for n in range(2, 9)}
        assert [n for n, t in types.items() if t == WeekType.RECOVERY] == [4, 7]

    @pytest.mark.parametrize("weeks_out,phase", [
        (2, TrainingPhase.PEAK), (4, TrainingPhase.PEAK), (6, TrainingPhase.BUILD),
        (12, TrainingPhase.BUILD), (14, TrainingPhase.BASE),
    ])
    def test_phases(self, weeks_out, phase):
        c = ctx(D(2026, 11, 23) - datetime.timedelta(weeks=weeks_out))
        assert c.phase == phase and c.weeks_to_goal == weeks_out and c.race_date == D(2026, 11, 29)

    def test_long_after_the_goal_falls_back_to_rolling_cycle(self):
        c = ctx(D(2027, 1, 4))
        assert c.weeks_to_goal is None and c.race_date is None and c.phase == TrainingPhase.BASE


class TestWithoutGoal:
    def test_recovery_every_cycle_length_weeks_across_iso_53_year(self):
        # 2026 has 53 ISO weeks; the old ISO-based cycle repeated a week there.
        weeks = [ctx(D(2026, 11, 2) + datetime.timedelta(weeks=n), goal=None) for n in range(16)]
        rec = [n for n, c in enumerate(weeks) if c.week_type == WeekType.RECOVERY]
        assert len(rec) == 4 and all(b - a == 4 for a, b in zip(rec, rec[1:], strict=False))

    def test_athletes_are_offset(self):
        starts = set()
        for uid in ["a", "b", "c", "d", "e", "f", "g", "h"]:
            weeks = [ctx(D(2026, 10, 5) + datetime.timedelta(weeks=n), goal=None, uid=uid) for n in range(4)]
            starts.add(next(n for n, c in enumerate(weeks) if c.week_type == WeekType.RECOVERY))
        assert len(starts) > 1

    def test_bad_goal_date_is_ignored(self):
        assert ctx(D(2026, 10, 5), goal="soon").race_date is None


def test_helpers():
    assert cycle_length(0) == 3 and cycle_length(3) == 4 and cycle_length(9) == 4
    assert monday_of(D(2026, 10, 11)) == D(2026, 10, 5)
    assert parse_goal_date(None) is None and parse_goal_date(Goal(date=None)) is None
    assert parse_goal_date(Goal(date=D(2026, 1, 1))) == D(2026, 1, 1)
    assert parse_goal_date(Goal(date="2026-01-01")) == D(2026, 1, 1)
