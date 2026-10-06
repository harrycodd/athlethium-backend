"""
Periodization Engine for Macrocycle and Mesocycle Planning.
Implements Base, Build, Peak, Taper phases and 3:1 load/deload mesocycles.
"""

import datetime
from typing import Optional, Tuple
from core.models import TrainingPhase, Goal, UserProfile


class PeriodizationEngine:
    """
    Determines training phase, weekly progression factors, and load/recovery weeks.
    """

    @classmethod
    def resolve_training_phase(
        cls,
        goal: Optional[Goal],
        current_date: datetime.date
    ) -> Tuple[TrainingPhase, int]:
        """
        Calculates current training phase and days remaining until target goal.
        """
        if not goal or not goal.date:
            return TrainingPhase.BASE, 999

        try:
            if isinstance(goal.date, str):
                goal_dt = datetime.datetime.strptime(goal.date, "%Y-%m-%d").date()
            else:
                goal_dt = goal.date

            days_remaining = (goal_dt - current_date).days
        except Exception:
            return TrainingPhase.BASE, 999

        if days_remaining <= 0:
            return (TrainingPhase.RACE, 0) if days_remaining == 0 else (TrainingPhase.RECOVERY, abs(days_remaining))
        elif days_remaining <= 14:
            return TrainingPhase.TAPER, days_remaining
        elif days_remaining <= 28:
            return TrainingPhase.PEAK, days_remaining
        elif days_remaining <= 84:
            return TrainingPhase.BUILD, days_remaining
        else:
            return TrainingPhase.BASE, days_remaining

    @classmethod
    def resolve_mesocycle_week(
        cls,
        current_date: datetime.date,
        intensity_weeks: int = 3
    ) -> Tuple[int, bool, float]:
        """
        Determines current week within the mesocycle block (0 to intensity_weeks).
        Returns: (relative_week, is_recovery_week, volume_multiplier)
        """
        # Calculate calendar week index
        iso_year, iso_week, iso_day = current_date.isocalendar()
        cycle_length = max(2, intensity_weeks + 1)
        relative_week = (iso_week - 1) % cycle_length  # 0 to intensity_weeks

        # The last week of the cycle is the deload/recovery week
        is_recovery_week = (relative_week == intensity_weeks)

        if is_recovery_week:
            volume_multiplier = 0.60  # 40% reduction for supercompensation
        else:
            # Progressive loading across loading weeks (e.g. 0.90 -> 1.0 -> 1.10)
            step = 0.10
            volume_multiplier = round(0.90 + (relative_week * step), 2)

        return relative_week, is_recovery_week, volume_multiplier
