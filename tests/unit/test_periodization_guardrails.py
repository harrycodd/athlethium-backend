import datetime

import pytest

from core.models import Goal, TrainingPhase
from engine.guardrails import GuardrailEngine
from engine.periodization import PeriodizationEngine
from tests.factories import make_goal, make_profile

TODAY = datetime.date(2026, 10, 5)


class TestPhase:
    @pytest.mark.parametrize("goal_date,phase,days", [
        ("2026-10-05", TrainingPhase.RACE, 0),
        ("2026-10-01", TrainingPhase.RECOVERY, 4),
        ("2026-10-19", TrainingPhase.TAPER, 14),
        ("2026-10-20", TrainingPhase.PEAK, 15),
        ("2026-11-02", TrainingPhase.PEAK, 28),
        ("2026-11-03", TrainingPhase.BUILD, 29),
        ("2026-12-28", TrainingPhase.BUILD, 84),
        ("2026-12-29", TrainingPhase.BASE, 85),
    ])
    def test_boundaries(self, goal_date, phase, days):
        assert PeriodizationEngine.resolve_training_phase(make_goal(goal_date), TODAY) == (phase, days)

    def test_no_goal_or_no_date(self):
        assert PeriodizationEngine.resolve_training_phase(None, TODAY) == (TrainingPhase.BASE, 999)
        assert PeriodizationEngine.resolve_training_phase(Goal(date=None), TODAY) == (TrainingPhase.BASE, 999)

    def test_date_object_accepted(self):
        goal = Goal(date=datetime.date(2026, 10, 10))
        assert PeriodizationEngine.resolve_training_phase(goal, TODAY) == (TrainingPhase.TAPER, 5)

    def test_malformed_date_falls_back_to_base(self):
        assert PeriodizationEngine.resolve_training_phase(Goal(date="10/10/2026"), TODAY) == (TrainingPhase.BASE, 999)


class TestMesocycle:
    def test_three_one_cycle(self):
        weeks = [PeriodizationEngine.resolve_mesocycle_week(TODAY + datetime.timedelta(weeks=w), 3) for w in range(4)]
        assert [w[1] for w in weeks].count(True) == 1
        recovery = next(w for w in weeks if w[1])
        assert recovery == (3, True, 0.6)
        assert sorted(w[2] for w in weeks if not w[1]) == [0.9, 1.0, 1.1]

    def test_minimum_cycle_length_two(self):
        rel, _, _ = PeriodizationEngine.resolve_mesocycle_week(TODAY, 0)
        assert rel in (0, 1)


class TestGuardrails:
    def clamp(self, profile, intensity=5, duration=1.5, recent=None):
        return GuardrailEngine.apply_safety_clamps(profile, intensity, duration, recent or [])

    def test_severe_injury_and_illness_force_rest(self):
        assert self.clamp(make_profile(injury=2))[:2] == (-1, 0.0)
        assert self.clamp(make_profile(illness=2))[:2] == (-1, 0.0)

    def test_minor_issue_caps_hard_sessions(self):
        assert self.clamp(make_profile(injury=1))[:2] == (2, 1.0)
        assert self.clamp(make_profile(illness=1), intensity=2, duration=2.0) == (2, 2.0, None)

    def test_deep_fatigue_forces_recovery(self):
        intensity, duration, reason = self.clamp(make_profile(ctl=40, atl=70))
        assert (intensity, duration) == (1, 1.0) and "TSB" in reason
        assert self.clamp(make_profile(ctl=40, atl=70), intensity=1) == (1, 1.5, None)

    def test_no_back_to_back_hard_days(self):
        assert self.clamp(make_profile(), recent=[2, 4])[:2] == (2, 1.5)
        assert self.clamp(make_profile(), intensity=3, recent=[5]) == (3, 1.5, None)

    def test_untouched(self):
        assert self.clamp(make_profile(), recent=[2]) == (5, 1.5, None)
