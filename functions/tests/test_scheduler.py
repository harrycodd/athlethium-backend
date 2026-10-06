"""
Unit Tests for Daily Training Scheduler and Safety Guardrails.
"""

import unittest
import datetime
from engine.scheduler import TrainingScheduler
from tests.fixtures import CYCLIST_PROFILE, INJURED_PROFILE, FATIGUED_PROFILE


class TestTrainingScheduler(unittest.TestCase):

    def test_injured_athlete_forces_rest(self):
        """Verify that severe injury (injury=2) forces complete rest."""
        workout = TrainingScheduler.schedule_day(INJURED_PROFILE, datetime.date(2026, 8, 25))
        self.assertEqual(workout.intensity, -1)
        self.assertEqual(workout.sport, "rest")
        self.assertEqual(workout.time, 0)

    def test_fatigued_athlete_forces_recovery(self):
        """Verify that deep fatigue (TSB < -25) forces Active Recovery (Zone 1)."""
        workout = TrainingScheduler.schedule_day(FATIGUED_PROFILE, datetime.date(2026, 8, 25))
        self.assertIn(workout.intensity, [1, -1])

    def test_daily_max_hours_constraint(self):
        """Verify that workout planned time does not exceed dailyMaxHours."""
        # Monday max is 1.0 hr (3600 sec)
        monday = datetime.date(2026, 8, 24)  # Monday
        workout = TrainingScheduler.schedule_day(CYCLIST_PROFILE, monday)
        self.assertLessEqual(workout.time, 3600)

    def test_daily_hours_override_respected(self):
        """Verify date-specific overrides take precedence."""
        profile = CYCLIST_PROFILE
        profile.daily_hours_overrides["2026-08-25"] = 0.5  # 30 mins
        workout = TrainingScheduler.schedule_day(profile, datetime.date(2026, 8, 25))
        self.assertLessEqual(workout.time, 1800)


if __name__ == "__main__":
    unittest.main()
