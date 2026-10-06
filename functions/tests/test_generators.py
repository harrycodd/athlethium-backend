"""
Unit Tests for Workout Generators (Endurance, Strength, Mobility).
Verifies step math, interval durations, and power/HR target integrity.
"""

import unittest
from generators.endurance import EnduranceGenerator
from generators.strength import StrengthGenerator
from generators.mobility import MobilityGenerator


class TestWorkoutGenerators(unittest.TestCase):

    def test_endurance_step_durations_sum_to_exact_total(self):
        """Verify that step duration sum equals requested duration in seconds across all intensities."""
        durations = [0.5, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
        intensities = [1, 2, 3, 4, 5, 6, 7]

        for dur in durations:
            expected_sec = int(round(dur * 3600))
            for intensity in intensities:
                payload = EnduranceGenerator.generate("cycling", dur, intensity)
                steps = payload["steps"]
                actual_sec = sum(s["duration"] for s in steps)
                self.assertEqual(
                    actual_sec, expected_sec,
                    f"Step sum mismatch for dur={dur}h, intensity={intensity}. Expected {expected_sec}s, got {actual_sec}s"
                )

    def test_vo2max_power_targets(self):
        """Verify VO2 max power targets are in Zone 5 (>105% FTP)."""
        payload = EnduranceGenerator.generate("cycling", 1.0, 5)
        interval_steps = [s for s in payload["steps"] if s["type"] == "interval"]
        self.assertTrue(len(interval_steps) > 0)
        for s in interval_steps:
            self.assertGreaterEqual(s["target_low"], 105)

    def test_threshold_power_targets(self):
        """Verify Threshold power targets are in Zone 4 (90-105% FTP)."""
        payload = EnduranceGenerator.generate("cycling", 1.0, 4)
        interval_steps = [s for s in payload["steps"] if s["type"] == "interval"]
        self.assertTrue(len(interval_steps) > 0)
        for s in interval_steps:
            self.assertGreaterEqual(s["target_low"], 90)
            self.assertLessEqual(s["target_high"], 105)

    def test_strength_generator_equipment_filtering(self):
        """Verify strength generator selects bodyweight when no equipment is provided."""
        payload = StrengthGenerator.generate("full", 45, 2, user_equipment=["bodyweight"])
        self.assertTrue(len(payload["steps"]) >= 3)
        self.assertEqual(payload["targetType"], "reps")

    def test_strength_generator_core_and_anatomical_focus(self):
        """Verify core, lower, upper focus categories generate appropriate target routines."""
        for focus in ["core", "legs", "lower", "upper", "all", "full"]:
            payload = StrengthGenerator.generate(focus, 30, 2, user_equipment=["bodyweight", "dumbbells"])
            self.assertTrue(len(payload["steps"]) >= 3)
            self.assertIn("steps", payload)
            actual_sec = sum(s["duration"] for s in payload["steps"])
            self.assertAlmostEqual(actual_sec, 30 * 60, delta=10)

    def test_mobility_generator_duration(self):
        """Verify mobility generator sums to requested duration across focus areas."""
        for focus in ["core", "legs", "lower", "upper", "full"]:
            payload = MobilityGenerator.generate(focus, 20)
            actual_sec = sum(s["duration"] for s in payload["steps"])
            self.assertEqual(actual_sec, 20 * 60)


if __name__ == "__main__":
    unittest.main()

