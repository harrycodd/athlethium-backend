import pytest

from engine import zones
from tests.factories import make_profile


@pytest.mark.parametrize("low,high,zone", [(None, 1, None), (65, 72, "low"), (85, 88, "mid"), (96, 102, "high"),
                                            (75, 77, "mid"), (90, 92, "high")])
def test_step_zone(low, high, zone):
    assert zones.step_zone(low, high) == zone


def test_hr_and_speed_mappings_are_monotonic_and_bounded():
    pcts = range(0, 260, 5)
    hr = [zones.pct_ftp_to_pct_hr(p) for p in pcts]
    speed = [zones.pct_ftp_to_pct_speed(p) for p in pcts]
    assert hr == sorted(hr) and speed == sorted(speed)
    assert zones.pct_ftp_to_pct_hr(100) == pytest.approx(101.43, abs=0.01)
    assert zones.pct_ftp_to_pct_hr(400) == 108


def test_threshold_lookup():
    p = make_profile(ftp_cycling=250, ftp_running=300, ftp_pace_running=300, ftp_pace_swimming=100, fthr=170)
    assert zones.threshold_for(p, "cycling", "power") == (250, "W", "power")
    assert zones.threshold_for(p, "running", "power") == (300, "W", "power")
    assert zones.threshold_for(p, "swimming", "power") is None
    assert zones.threshold_for(p, "running", "heart_rate") == (170, "bpm", "hr")
    assert zones.threshold_for(p, "running", "pace") == (300, "s/km", "pace")
    assert zones.threshold_for(p, "swimming", "pace") == (100, "s/100m", "pace")
    assert zones.threshold_for(p, "cycling", "pace") is None
    assert zones.threshold_for(p, "swimming", "time") is None


def test_unknown_thresholds_give_no_numbers():
    p = make_profile(known_thresholds=["hr"])
    assert zones.threshold_for(p, "cycling", "power") is None
    assert zones.threshold_for(p, "running", "power") is None
    assert zones.threshold_for(p, "running", "pace") is None
    assert zones.threshold_for(p, "swimming", "pace") is None
    assert zones.threshold_for(p, "cycling", "heart_rate") is not None
    steps = [{"duration": 60, "target_low": 65, "target_high": 72}]
    assert zones.apply_athlete_targets(steps, "cycling", "power", p) is False
    assert "target_range" not in steps[0]


def test_falls_back_to_generic_ftp_when_cycling_ftp_unset():
    p = make_profile(ftp=230, ftp_cycling=0)
    assert zones.threshold_for(p, "cycling", "power")[0] == 230


def test_targets_scale_with_the_athletes_threshold():
    steps = [{"duration": 600, "target_low": 96, "target_high": 102}, {"duration": 60, "name": "no target"}]
    zones.apply_athlete_targets(steps, "cycling", "power", make_profile(ftp_cycling=300))
    assert steps[0]["target_range"] == {"unit": "W", "min": 288, "max": 306}
    assert "target_range" not in steps[1]


def test_pace_targets_faster_for_harder_work():
    easy = [{"duration": 60, "target_low": 65, "target_high": 72}]
    hard = [{"duration": 60, "target_low": 96, "target_high": 102}]
    p = make_profile(ftp_pace_running=300)
    zones.apply_athlete_targets(easy, "running", "pace", p)
    zones.apply_athlete_targets(hard, "running", "pace", p)
    assert easy[0]["target_range"]["unit"] == "s/km"
    assert hard[0]["target_range"]["max"] < easy[0]["target_range"]["min"]
    assert 290 <= hard[0]["target_range"]["min"] <= hard[0]["target_range"]["max"] <= 310


def test_hr_targets():
    steps = [{"duration": 60, "target_low": 65, "target_high": 72}]
    zones.apply_athlete_targets(steps, "running", "heart_rate", make_profile(fthr=170))
    assert steps[0]["target_range"] == {"unit": "bpm", "min": 129, "max": 137}


def test_steps_tss_and_zone_seconds():
    steps = [{"duration": 3600, "target_low": 100, "target_high": 100}, {"duration": 600},
             {"duration": 1800, "target_low": 85, "target_high": 87}]
    assert zones.steps_tss(steps) == pytest.approx(100 + 0.5 * 0.86 ** 2 * 100, abs=0.1)
    assert zones.zone_seconds(steps) == {"low": 0, "mid": 1800, "high": 3600}
