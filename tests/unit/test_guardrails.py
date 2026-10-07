from engine.guardrails import GuardrailEngine
from tests.factories import make_profile


def clamp(profile, intensity=5, duration=1.5, recent=None):
    return GuardrailEngine.apply_safety_clamps(profile, intensity, duration, recent or [])


def test_severe_injury_and_illness_force_rest():
    assert clamp(make_profile(injury=2))[:2] == (-1, 0.0)
    assert clamp(make_profile(illness=2))[:2] == (-1, 0.0)


def test_minor_issue_caps_hard_sessions():
    assert clamp(make_profile(injury=1))[:2] == (2, 1.0)
    assert clamp(make_profile(illness=1), intensity=2, duration=2.0) == (2, 2.0, None)


def test_deep_fatigue_forces_recovery():
    intensity, duration, reason = clamp(make_profile(ctl=40, atl=70))
    assert (intensity, duration) == (1, 1.0) and "TSB" in reason
    assert clamp(make_profile(ctl=40, atl=70), intensity=1) == (1, 1.5, None)


def test_no_back_to_back_hard_days():
    assert clamp(make_profile(), recent=[2, 4])[:2] == (2, 1.5)
    assert clamp(make_profile(), intensity=3, recent=[5]) == (3, 1.5, None)


def test_untouched():
    assert clamp(make_profile(), recent=[2]) == (5, 1.5, None)
