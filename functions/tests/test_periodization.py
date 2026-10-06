"""
Unit Tests for Periodization Engine.
Verifies Macrocycle Phases and 3:1 Mesocycle Volume Multipliers.
"""

import unittest
import datetime
from engine.periodization import PeriodizationEngine
from core.models import Goal, TrainingPhase


class TestPeriodizationEngine(unittest.TestCase):

    def test_training_phase_detection(self):
        """Verifies phase detection based on days until goal."""
        today = datetime.date(2026, 8, 26)

        # > 12 weeks out -> Base
        goal_base = Goal(date="2026-12-01")
        phase, days = PeriodizationEngine.resolve_training_phase(goal_base, today)
        self.assertEqual(phase, TrainingPhase.BASE)

        # 6 weeks out -> Build
        goal_build = Goal(date="2026-10-07")
        phase, days = PeriodizationEngine.resolve_training_phase(goal_build, today)
        self.assertEqual(phase, TrainingPhase.BUILD)

        # 3 weeks out -> Peak
        goal_peak = Goal(date="2026-09-16")
        phase, days = PeriodizationEngine.resolve_training_phase(goal_peak, today)
        self.assertEqual(phase, TrainingPhase.PEAK)

        # 10 days out -> Taper
        goal_taper = Goal(date="2026-09-05")
        phase, days = PeriodizationEngine.resolve_training_phase(goal_taper, today)
        self.assertEqual(phase, TrainingPhase.TAPER)

        # Same day -> Race
        goal_race = Goal(date="2026-08-26")
        phase, days = PeriodizationEngine.resolve_training_phase(goal_race, today)
        self.assertEqual(phase, TrainingPhase.RACE)

    def test_mesocycle_3_to_1_deload_reduction(self):
        """Verifies that in any 4-week block, exactly 1 week is a deload week (0.60 multiplier)."""
        base_date = datetime.date(2026, 8, 24)  # Monday
        
        results = []
        for w in range(4):
            dt = base_date + datetime.timedelta(weeks=w)
            rel_week, is_recovery, vol_mult = PeriodizationEngine.resolve_mesocycle_week(dt, intensity_weeks=3)
            results.append((rel_week, is_recovery, vol_mult))

        # Exactly one recovery week in a 4-week span
        recovery_weeks = [r for r in results if r[1]]
        loading_weeks = [r for r in results if not r[1]]

        self.assertEqual(len(recovery_weeks), 1, "There should be exactly 1 deload week in 4 consecutive weeks.")
        self.assertEqual(len(loading_weeks), 3, "There should be exactly 3 loading weeks in 4 consecutive weeks.")
        self.assertEqual(recovery_weeks[0][2], 0.60, "Deload week should have 0.60 volume multiplier.")


if __name__ == "__main__":
    unittest.main()
