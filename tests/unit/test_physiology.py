import datetime

import pytest

from engine.physiology import PhysiologyEngine as P

D = datetime.date


class TestNextDay:
    def test_zero_load_decays_both(self):
        ctl, atl, tsb = P.calculate_next_day_metrics(42.0, 70.0, 0)
        assert ctl == pytest.approx(41.0)
        assert atl == pytest.approx(60.0)
        assert tsb == pytest.approx(-19.0)

    def test_load_equal_to_ctl_keeps_ctl(self):
        ctl, _, _ = P.calculate_next_day_metrics(50.0, 50.0, 50.0)
        assert ctl == 50.0


class TestProjection:
    def test_no_metrics_date_returns_unchanged(self):
        assert P.project_metrics(50, 60, None, D(2026, 10, 10)) == (50, 60)

    def test_as_of_not_after_metrics_date_unchanged(self):
        assert P.project_metrics(50, 60, D(2026, 10, 10), D(2026, 10, 10)) == (50, 60)
        assert P.project_metrics(50, 60, D(2026, 10, 10), D(2026, 10, 1)) == (50, 60)

    def test_two_week_gap_drains_fatigue_much_faster_than_fitness(self):
        ctl, atl = P.project_metrics(60, 80, D(2026, 10, 1), D(2026, 10, 15))
        assert ctl == pytest.approx(60 * (41 / 42) ** 14, abs=0.01)
        assert atl == pytest.approx(80 * (6 / 7) ** 14, abs=0.01)
        assert ctl - atl > 0  # athlete comes back fresh


class TestApplySessionLoad:
    def test_first_ever_session(self):
        ctl, atl, d = P.apply_session_load(0, 0, None, D(2026, 10, 6), 84)
        assert (ctl, atl, d) == (2.0, 12.0, D(2026, 10, 6))

    def test_next_day_matches_single_ewma_step(self):
        ctl, atl, d = P.apply_session_load(50, 50, D(2026, 10, 5), D(2026, 10, 6), 100)
        assert (ctl, atl) == P.calculate_next_day_metrics(50, 50, 100)[:2]
        assert d == D(2026, 10, 6)

    def test_gap_decays_idle_days_first(self):
        gap = P.apply_session_load(50, 50, D(2026, 10, 1), D(2026, 10, 6), 100)
        no_gap = P.apply_session_load(50, 50, D(2026, 10, 5), D(2026, 10, 6), 100)
        assert gap[0] < no_gap[0] and gap[1] < no_gap[1]

    def test_two_sessions_same_day_equal_one_combined_session(self):
        ctl1, atl1, d1 = P.apply_session_load(50, 50, D(2026, 10, 5), D(2026, 10, 6), 60)
        ctl2, atl2, d2 = P.apply_session_load(ctl1, atl1, d1, D(2026, 10, 6), 40)
        combined = P.apply_session_load(50, 50, D(2026, 10, 5), D(2026, 10, 6), 100)
        assert (ctl2, atl2) == pytest.approx(combined[:2], abs=0.02)
        assert d2 == D(2026, 10, 6)

    def test_backfilled_session_is_decayed(self):
        recent = P.apply_session_load(50, 50, D(2026, 10, 10), D(2026, 10, 10), 70)
        older = P.apply_session_load(50, 50, D(2026, 10, 10), D(2026, 10, 3), 70)
        assert older[1] < recent[1]
        assert older[2] == D(2026, 10, 10)

    def test_negative_delta_reduces_load(self):
        ctl, atl, _ = P.apply_session_load(50, 50, D(2026, 10, 6), D(2026, 10, 6), -42)
        assert ctl == 49.0 and atl == 44.0


class TestNormalizedPower:
    def test_empty(self):
        assert P.normalized_power([]) == 0.0

    def test_short_ride_is_average(self):
        assert P.normalized_power([100, 200]) == 150

    def test_steady_power_equals_average(self):
        assert P.normalized_power([250.0] * 600) == pytest.approx(250.0)

    def test_variable_power_exceeds_average(self):
        samples = ([400.0] * 60 + [100.0] * 60) * 10
        assert P.normalized_power(samples) > sum(samples) / len(samples)


class TestTss:
    @pytest.mark.parametrize("sport", ["strength", "stretching", "yoga", "rest", "Strength"])
    def test_estimate_zero_for_non_endurance(self, sport):
        assert P.estimate_session_tss(4, 1.0, sport) == 0.0

    def test_estimate_uses_zone_multiplier_and_default(self):
        assert P.estimate_session_tss(4, 1.5) == 120.0
        assert P.estimate_session_tss(99, 1.0) == 50.0

    def test_actual_zero_duration(self):
        assert P.calculate_actual_tss("cycling", 0, avg_power=300) == 0.0

    def test_power_at_ftp_for_one_hour_is_100(self):
        assert P.calculate_actual_tss("cycling", 3600, normalized_power=250, ftp=250) == 100.0

    def test_avg_power_used_when_no_np(self):
        assert P.calculate_actual_tss("cycling", 3600, avg_power=125, ftp=250) == 25.0

    def test_hr_fallback(self):
        assert P.calculate_actual_tss("running", 3600, avg_hr=170, fthr=170) == 100.0

    def test_power_ignored_without_ftp(self):
        assert P.calculate_actual_tss("cycling", 3600, avg_power=200, ftp=0, avg_hr=85, fthr=170) == 25.0

    @pytest.mark.parametrize("rpe,expected", [(1, 25.0), (10, 140.0)])
    def test_rpe_fallback(self, rpe, expected):
        assert P.calculate_actual_tss("running", 3600, rpe=rpe) == expected

    @pytest.mark.parametrize("rpe", [None, 0, 11])
    def test_default_moderate(self, rpe):
        assert P.calculate_actual_tss("running", 7200, rpe=rpe) == 100.0
