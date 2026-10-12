"""Profile documents are also written directly by the app, so normalisation must survive junk."""

import datetime

import time_machine

from services.user_service import UserService
from services.workout_completer import WorkoutCompleterService, _local_date
from tests.factories import make_profile_doc


def test_well_formed_document():
    p = UserService.normalize_user_profile("u1", make_profile_doc(fitness_level="advanced", metricsDate="2026-10-05",
                                                                  timezone="Europe/London"))
    assert p.uid == "u1" and p.wizard_completed and p.ftp_cycling == 250
    assert p.fitness_level == "advanced" and p.metrics_date == "2026-10-05" and p.timezone == "Europe/London"
    assert p.goal.name == "Autumn Sportive" and p.goal.target_distance is None


def test_malformed_values_fall_back_to_defaults():
    raw = {
        "ctl": "lots", "atl": None, "ftp": float("nan"), "injury": "x", "weeklyHours": [],
        "equipment": "dumbbells", "equipmentToggles": ["bench"],
        "sports": "running", "focused_sports": {"a": 1}, "activities": [], "mainFocus": "x",
        "dailyMaxHours": {"Monday": "two", "Tuesday": 30, "Wednesday": 1.5},
        "dailyHoursOverrides": "none",
        "goal": {"targetDistance": "far", "targetTime": "slow"},
    }
    p = UserService.normalize_user_profile("u1", raw)
    assert (p.ctl, p.atl, p.ftp, p.injury, p.weekly_hours) == (40.0, 30.0, 200.0, 0, 8.0)
    assert p.equipment == ["bodyweight"]
    assert p.sports == ["cycling", "running"] and p.focused_sports == ["cycling"]
    assert p.activities == {} and p.main_focus == {}
    assert p.daily_max_hours == {"Wednesday": 1.5} and p.daily_hours_overrides == {}
    assert p.goal.target_distance is None and p.goal.target_time is None


def test_focus_defaults_to_first_sport_and_legacy_camelcase_level():
    p = UserService.normalize_user_profile("u1", {"sports": ["swimming"], "focused_sports": [], "fitnessLevel": "elite"})
    assert p.focused_sports == ["swimming"] and p.fitness_level == "elite"


@time_machine.travel("2026-10-06 23:30:00+00:00", tick=False)
def test_today_for_profile_timezone():
    assert UserService.today_for(None) == datetime.date(2026, 10, 6)
    tokyo = UserService.normalize_user_profile("u", {"timezone": "Asia/Tokyo"})
    assert UserService.today_for(tokyo) == datetime.date(2026, 10, 7)
    bogus = UserService.normalize_user_profile("u", {"timezone": "Nowhere/Land"})
    assert UserService.today_for(bogus) == datetime.date(2026, 10, 6)


@time_machine.travel("2026-10-06 23:30:00+00:00", tick=False)
def test_fit_local_date():
    naive_utc = datetime.datetime(2026, 10, 6, 23, 0)
    assert _local_date(naive_utc, "Asia/Tokyo") == datetime.date(2026, 10, 7)
    assert _local_date(naive_utc, "Bad/Zone") == datetime.date(2026, 10, 6)
    assert _local_date(None, None) == datetime.date(2026, 10, 6)


def test_manual_tss_rules():
    tss = WorkoutCompleterService.manual_tss
    assert tss({"sport": "yoga"}, 3600, 9) == 0.0
    assert tss({"sport": "running", "plannedTss": 80, "plannedTime": 3600}, 1800, None) == 40.0
    assert tss({"sport": "running", "tss": 0}, 3600, 5) == 65.0
    assert tss({"sport": "running"}, 3600, None) == 50.0


def test_language_is_normalised():
    assert UserService.normalize_user_profile("u1", make_profile_doc()).language == "en"
    for lang in ("en", "es", "fr", "de", "it", "ja"):
        assert UserService.normalize_user_profile("u1", make_profile_doc(language=lang)).language == lang
    for junk in ("pt", "DE", "de-DE", "", 7, None, ["de"], {"de": True}):
        assert UserService.normalize_user_profile("u1", {"language": junk}).language == "en"
