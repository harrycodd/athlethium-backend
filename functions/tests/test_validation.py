"""
Test Suite for Setup Wizard Server-Side Profile Validation.
"""

import unittest
from services.profile_validator import ProfileValidator


class TestProfileValidation(unittest.TestCase):

    def setUp(self):
        self.valid_wizard_payload = {
            "displayName": "Alex Runner",
            "units": "Metric",
            "weekly_hours": 8.0,
            "activities": {
                "running": True,
                "cycling": True,
                "swimming": False,
                "strength": True,
                "stretching": True
            },
            "mainFocus": {
                "running": True,
                "cycling": False,
                "swimming": False,
                "strength": False,
                "stretching": False
            },
            "trainingGoalType": "Marathon",
            "goal": {
                "name": "Autumn Marathon Sub-4h",
                "type": "Goal",
                "date": "2026-11-15",
                "sports": ["running"],
                "targetDistance": 42.2,
                "targetDistanceUnit": "km",
                "targetTime": 13500,
                "targetTimeString": "03:45:00",
                "targetPace": "5:20 /km",
                "notes": "Target Area: lower • Sub-3:45 goal"
            },
            "sportPercentages": {
                "running": 60,
                "cycling": 20,
                "swimming": 0,
                "strength": 10,
                "stretching": 10
            },
            "sportSessionsPerWeek": {
                "running": 4,
                "cycling": 1,
                "swimming": 0,
                "strength": 2,
                "stretching": 2
            },
            "dailyMaxHours": {
                "Monday": 1.0,
                "Tuesday": 1.5,
                "Wednesday": 1.5,
                "Thursday": 1.5,
                "Friday": 1.0,
                "Saturday": 2.5,
                "Sunday": 2.0
            },
            "equipmentToggles": {
                "dumbbells": True,
                "pullUpBar": True,
                "bench": True
            },
            "wizardCompleted": True
        }

    def test_valid_setup_wizard_payload(self):
        is_valid, errors, normalized = ProfileValidator.validate(self.valid_wizard_payload)
        self.assertTrue(is_valid, f"Validation should succeed but failed with errors: {errors}")
        self.assertEqual(len(errors), 0)
        self.assertEqual(normalized["displayName"], "Alex Runner")
        self.assertEqual(normalized["units"], "Metric")
        self.assertEqual(normalized["weekly_hours"], 8.0)
        self.assertEqual(normalized["focused_sports"], ["running"])
        self.assertIn("running", normalized["sports"])
        self.assertIn("bodyweight", normalized["equipment"])
        self.assertIn("dumbbells", normalized["equipment"])

    def test_missing_or_blank_display_name(self):
        payload = dict(self.valid_wizard_payload)
        payload["displayName"] = "   "
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("displayName" in e for e in errors))

    def test_invalid_units(self):
        payload = dict(self.valid_wizard_payload)
        payload["units"] = "Yards"
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("units" in e for e in errors))

    def test_weekly_hours_out_of_range(self):
        # Too low (< 1)
        payload1 = dict(self.valid_wizard_payload)
        payload1["weekly_hours"] = 0.5
        is_valid, errors1, _ = ProfileValidator.validate(payload1)
        self.assertFalse(is_valid)
        self.assertTrue(any("weekly_hours" in e for e in errors1))

        # Too high (> 30)
        payload2 = dict(self.valid_wizard_payload)
        payload2["weekly_hours"] = 35.0
        is_valid, errors2, _ = ProfileValidator.validate(payload2)
        self.assertFalse(is_valid)
        self.assertTrue(any("weekly_hours" in e for e in errors2))

    def test_main_focus_sport_must_be_active(self):
        payload = dict(self.valid_wizard_payload)
        # swimming is False in activities, but True in mainFocus
        payload["activities"]["swimming"] = False
        payload["mainFocus"]["swimming"] = True
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("swimming" in e and "active" in e for e in errors))

    def test_insufficient_daily_availability_capacity(self):
        payload = dict(self.valid_wizard_payload)
        payload["weekly_hours"] = 15.0
        # Total daily max hours sum is only 11.0 (Monday to Sunday)
        payload["dailyMaxHours"] = {
            "Monday": 1.0,
            "Tuesday": 1.5,
            "Wednesday": 1.5,
            "Thursday": 1.5,
            "Friday": 1.0,
            "Saturday": 2.5,
            "Sunday": 2.0
        }
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("capacity" in e for e in errors))

    def test_goal_sport_must_be_in_focused_sports(self):
        payload = dict(self.valid_wizard_payload)
        # Goal sport is cycling, but main focus is running only
        payload["goal"]["sports"] = ["cycling"]
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("Goal sport 'cycling' must be one of the athlete's main focused sports" in e for e in errors))

    def test_invalid_goal_date_format(self):
        payload = dict(self.valid_wizard_payload)
        payload["goal"]["date"] = "15-11-2026"
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("YYYY-MM-DD" in e for e in errors))

    def test_invalid_goal_time_string_format(self):
        payload = dict(self.valid_wizard_payload)
        payload["goal"]["targetTimeString"] = "3h45m"
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("HH:MM:SS" in e for e in errors))

    def test_sport_percentages_sum_validation(self):
        payload = dict(self.valid_wizard_payload)
        # Sum is 50 + 20 = 70% (well below 100%)
        payload["sportPercentages"] = {
            "running": 50,
            "cycling": 20,
            "swimming": 0,
            "strength": 0,
            "stretching": 0
        }
        is_valid, errors, _ = ProfileValidator.validate(payload)
        self.assertFalse(is_valid)
        self.assertTrue(any("percentages must sum to 100%" in e for e in errors))

    def test_partial_update_validation(self):
        """Verify partial update validates provided fields without requiring complete wizard payload."""
        partial_payload = {
            "weekly_hours": 10.0,
            "units": "Imperial"
        }
        is_valid, errors, normalized = ProfileValidator.validate(partial_payload, is_partial=True)
        self.assertTrue(is_valid, f"Partial validation failed: {errors}")
        self.assertEqual(normalized["weekly_hours"], 10.0)
        self.assertEqual(normalized["units"], "Imperial")

    def test_goal_with_distance_and_pace(self):
        """Verify goal with swimming yards/meters or cardio distances and durations."""
        payload = dict(self.valid_wizard_payload)
        payload["goal"]["targetDistance"] = 1500
        payload["goal"]["targetDistanceUnit"] = "m"
        payload["goal"]["targetTimeString"] = "00:24:30"
        is_valid, errors, normalized = ProfileValidator.validate(payload)
        self.assertTrue(is_valid)
        self.assertEqual(normalized["goal"]["targetDistance"], 1500)
        self.assertEqual(normalized["goal"]["targetTimeString"], "00:24:30")


if __name__ == "__main__":
    unittest.main()

