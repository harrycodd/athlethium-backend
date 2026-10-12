import pytest
import time_machine

from services.profile_validator import ProfileValidator as V
from tests.factories import make_profile_doc


def errors_for(**overrides):
    ok, errors, _ = V.validate(make_profile_doc(**overrides))
    assert not ok
    return " | ".join(errors)


def test_valid_wizard_payload():
    ok, errors, norm = V.validate(make_profile_doc())
    assert ok, errors
    assert norm["sports"] == ["running", "cycling"]
    assert norm["focused_sports"] == ["cycling"]
    assert norm["wizardCompleted"] is True
    assert "dumbbells" in norm["equipment"] and "bodyweight" in norm["equipment"]


def test_not_a_dict():
    assert V.validate(["x"]) == (False, ["Payload must be a JSON object"], {})


@pytest.mark.parametrize("value,msg", [(None, "displayName is required"), ("  ", "displayName is required"),
                                       ("x" * 101, "cannot exceed 100")])
def test_display_name(value, msg):
    doc = make_profile_doc()
    doc["displayName"] = value
    assert msg in " ".join(V.validate(doc)[1])


def test_units_and_hours():
    assert "units must be one of" in errors_for(units="Furlongs")
    assert "between 1 and 30" in errors_for(weekly_hours=31)
    assert "valid number" in errors_for(weekly_hours="lots")
    ok, _, norm = V.validate(make_profile_doc(weekly_hours=None, weeklyHours=6))
    assert ok and norm["weekly_hours"] == 6.0


def test_sports_from_list_and_defaults():
    doc = make_profile_doc(activities=None, mainFocus=None)
    doc["sports"] = ["running", "kitesurfing"]
    doc["focused_sports"] = ["running", "cycling"]
    doc["goal"]["sports"] = ["running"]
    ok, errors, norm = V.validate(doc)
    assert norm["sports"] == ["running"]
    assert "Focused sport 'cycling' must be an active sport" in errors

    ok, errors, norm = V.validate(make_profile_doc(activities=None, mainFocus=None, goal=None))
    assert ok, errors
    assert norm["sports"] == ["running", "cycling"] and norm["focused_sports"] == ["running"]


def test_main_focus_must_be_active():
    assert "must be enabled in active activities" in errors_for(
        mainFocus={"swimming": True}, goal={"name": "g", "date": "2026-12-01", "sports": ["swimming"]})


def test_needs_at_least_one_sport_and_focus():
    assert "At least one active sport" in errors_for(activities={"running": False})
    assert "At least one main focus" in errors_for(mainFocus={"running": False, "cycling": False})


def test_partial_update_only_checks_given_fields():
    ok, errors, norm = V.validate({"units": "Imperial"}, is_partial=True)
    assert ok, errors
    assert norm["units"] == "Imperial" and "wizardCompleted" not in norm


def test_training_goal_type():
    assert "trainingGoalType cannot be empty" in errors_for(trainingGoalType=" ")


class TestGoal:
    def test_not_object(self):
        assert "goal must be an object" in errors_for(goal="race")

    def test_required_fields(self):
        msg = errors_for(goal={"sports": []})
        assert "Goal name is required" in msg and "Goal date is required" in msg
        assert "at least one sport" in msg

    def test_bad_date_and_sport_not_focused(self):
        msg = errors_for(goal={"name": "x", "date": "29/11/2026", "sports": "running"})
        assert "YYYY-MM-DD" in msg and "main focused sports" in msg

    def test_optional_targets(self):
        goal = {"name": "Marathon", "date": "2026-11-29", "sports": ["cycling"], "targetDistance": "42.2",
                "targetDistanceUnit": "km", "targetTime": 10800, "targetTimeString": "03:00:00",
                "targetPace": " 4:15/km ", "notes": " core "}
        ok, errors, norm = V.validate(make_profile_doc(goal=goal))
        assert ok, errors
        assert norm["goal"]["targetDistance"] == 42.2 and norm["goal"]["targetPace"] == "4:15/km"

    @pytest.mark.parametrize("field,value,msg", [
        ("targetDistance", 0, "greater than 0"), ("targetDistance", "far", "valid number"),
        ("targetTime", -1, "greater than 0"), ("targetTime", "slow", "valid integer"),
        ("targetTimeString", "3h", "HH:MM:SS"),
    ])
    def test_bad_targets(self, field, value, msg):
        goal = {"name": "x", "date": "2026-11-29", "sports": ["cycling"], field: value}
        assert msg in errors_for(goal=goal)

    @time_machine.travel("2026-10-06 12:00:00+00:00", tick=False)
    def test_default_goal_twelve_weeks_out(self):
        ok, _, norm = V.validate(make_profile_doc(goal=None))
        assert ok and norm["goal"]["date"] == "2026-12-29"


class TestAllocation:
    def test_percentages(self):
        ok, errors, norm = V.validate(make_profile_doc(sportPercentages={"running": 40, "cycling": 60}))
        assert ok, errors
        assert norm["sportPercentages"]["swimming"] == 0.0
        assert "must sum to 100%" in errors_for(sportPercentages={"running": 40, "cycling": 40})
        assert "between 0 and 100" in errors_for(sportPercentages={"running": -10, "cycling": 110})
        assert "Invalid percentage" in errors_for(sportPercentages={"running": "x", "cycling": 100})
        assert "must be a map" in errors_for(sportPercentages=[1])

    def test_sessions(self):
        ok, errors, norm = V.validate(make_profile_doc(sportSessionsPerWeek={"running": 3}))
        assert ok, errors
        assert norm["sportSessionsPerWeek"] == {"running": 3, "cycling": 1, "swimming": 0, "strength": 0,
                                                "stretching": 0}
        assert "between 1 and 14" in errors_for(sportSessionsPerWeek={"running": 0})
        assert "Invalid weekly session" in errors_for(sportSessionsPerWeek={"running": "x"})
        assert "must be a map" in errors_for(sportSessionsPerWeek="3")


class TestDailyHours:
    def test_defaults_fill_missing_days(self):
        ok, _, norm = V.validate(make_profile_doc(dailyMaxHours={"Monday": 2}))
        assert ok and norm["dailyMaxHours"]["Tuesday"] == 1.5

    def test_errors(self):
        assert "between 0.0 and 8.0" in errors_for(dailyMaxHours={"Monday": 9})
        assert "Invalid hours format" in errors_for(dailyMaxHours={"Monday": "x"})
        assert "cannot be less than target weekly hours" in errors_for(
            weekly_hours=20, dailyMaxHours={d: 1 for d in ["Monday", "Tuesday"]})

    def test_non_dict_uses_defaults(self):
        ok, _, norm = V.validate(make_profile_doc(dailyMaxHours="busy"))
        assert ok and norm["dailyMaxHours"]["Saturday"] == 2.0


def test_equipment_list_passthrough():
    doc = make_profile_doc(equipmentToggles=None)
    doc["equipment"] = ["power_meter"]
    assert V.validate(doc)[2]["equipment"] == ["power_meter"]
    ok, _, norm = V.validate(make_profile_doc(equipmentToggles={"rowingMachine": True, "bench": False}))
    assert norm["equipment"] == ["bodyweight", "rowingMachine"]


def test_wizard_completed_flag():
    assert V.validate(make_profile_doc(wizardCompleted=False))[2]["wizardCompleted"] is False


class TestTypedOptionalFields:
    def test_valid_values_are_typed(self):
        ok, errors, norm = V.validate(make_profile_doc(
            ctl=55, atl=60.5, ftp=280, injury=1, intensity_weeks=2, intervalType="mix",
            fitness_level="advanced", timezone="Europe/London",
            dailyHoursOverrides={"2026-10-10": 3}, history={"cycling": {"focus": [2]}}))
        assert ok, errors
        assert norm["ctl"] == 55.0 and isinstance(norm["injury"], int)
        assert norm["timezone"] == "Europe/London"
        assert norm["dailyHoursOverrides"] == {"2026-10-10": 3.0}

    @pytest.mark.parametrize("field,value,msg", [
        ("ctl", "fit", "ctl must be a number"),
        ("ctl", True, "ctl must be a number"),
        ("ctl", float("nan"), "ctl must be between"),
        ("ftp", 5000, "ftp must be between"),
        ("injury", 3, "injury must be between"),
        ("intervalType", "chaos", "intervalType must be one of"),
        ("fitness_level", "god", "fitness_level must be one of"),
        ("timezone", "Mars/Olympus", "valid IANA time zone"),
        ("timezone", 5, "valid IANA time zone"),
        ("timezone", "../../etc/passwd", "valid IANA time zone"),
        ("dailyHoursOverrides", [1], "must be a map"),
        ("dailyHoursOverrides", {"tomorrow": 1}, "Invalid daily hours override"),
        ("dailyHoursOverrides", {"2026-10-10": 12}, "Invalid daily hours override"),
        ("history", "lots", "history must be an object"),
    ])
    def test_rejected(self, field, value, msg):
        assert msg in errors_for(**{field: value})


@pytest.mark.parametrize("language", ["en", "es", "fr", "de", "it", "ja"])
def test_supported_languages(language):
    ok, errors, norm = V.validate(make_profile_doc(language=language))
    assert ok, errors
    assert norm["language"] == language
    ok, _, norm = V.validate({"language": language}, is_partial=True)
    assert ok and norm["language"] == language


@pytest.mark.parametrize("language", ["pt", "EN", "de-DE", "", 3, None, ["de"]])
def test_unsupported_language_is_rejected(language):
    doc = make_profile_doc()
    doc["language"] = language
    ok, errors, norm = V.validate(doc)
    assert not ok and "language" not in norm
    assert f"language must be one of ['en', 'es', 'fr', 'de', 'it', 'ja'], received '{language}'" in errors
    ok, errors, norm = V.validate({"language": language}, is_partial=True)
    assert not ok and "language" not in norm


def test_language_is_optional_and_never_defaulted():
    """A save without a language keeps the stored one (normalisation reads a missing one as English)."""
    ok, _, norm = V.validate(make_profile_doc())
    assert ok and "language" not in norm
