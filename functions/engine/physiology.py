"""
Physiological Modeling & Fitness/Fatigue Calculations.
Implements the Banister Impulse-Response model (CTL, ATL, TSB).
"""

import datetime
from typing import List, Optional, Tuple
from core.config import TSS_MULTIPLIER_MAP


class PhysiologyEngine:
    """
    Handles Chronic Training Load (CTL), Acute Training Load (ATL),
    and Training Stress Balance (TSB) calculations.
    """

    CTL_TIME_CONSTANT = 42.0  # 42 days for fitness decay
    ATL_TIME_CONSTANT = 7.0   # 7 days for fatigue decay

    @classmethod
    def calculate_next_day_metrics(
        cls,
        current_ctl: float,
        current_atl: float,
        daily_tss: float
    ) -> Tuple[float, float, float]:
        """
        Updates CTL and ATL using standard Exponentially Weighted Moving Average (EWMA).
        Returns: (new_ctl, new_atl, new_tsb)
        """
        new_ctl = current_ctl + (daily_tss - current_ctl) / cls.CTL_TIME_CONSTANT
        new_atl = current_atl + (daily_tss - current_atl) / cls.ATL_TIME_CONSTANT
        new_tsb = new_ctl - new_atl
        return round(new_ctl, 2), round(new_atl, 2), round(new_tsb, 2)

    @classmethod
    def project_metrics(
        cls,
        ctl: float,
        atl: float,
        metrics_date: Optional[datetime.date],
        as_of: datetime.date
    ) -> Tuple[float, float]:
        """
        Decays CTL/ATL (zero load) from the end of `metrics_date` to the end of `as_of`.
        Without this, an athlete who stops training keeps yesterday's fatigue forever.
        """
        if metrics_date is None or as_of <= metrics_date:
            return ctl, atl
        idle_days = (as_of - metrics_date).days
        ctl = ctl * (1 - 1 / cls.CTL_TIME_CONSTANT) ** idle_days
        atl = atl * (1 - 1 / cls.ATL_TIME_CONSTANT) ** idle_days
        return round(ctl, 2), round(atl, 2)

    @classmethod
    def apply_session_load(
        cls,
        ctl: float,
        atl: float,
        metrics_date: Optional[datetime.date],
        session_date: datetime.date,
        tss: float
    ) -> Tuple[float, float, datetime.date]:
        """
        Adds one session's TSS to CTL/ATL, which describe the athlete at the end of `metrics_date`.

        - Later day: decay through the idle days, then apply the session day.
        - Same day (second session) or back-filled earlier day: the EWMA is linear in daily TSS,
          so the session contributes tss/k, decayed by the days since it happened.
        Returns (ctl, atl, new_metrics_date).
        """
        if metrics_date is None:
            metrics_date = session_date - datetime.timedelta(days=1)

        if session_date > metrics_date:
            ctl, atl = cls.project_metrics(ctl, atl, metrics_date, session_date - datetime.timedelta(days=1))
            new_ctl, new_atl, _ = cls.calculate_next_day_metrics(ctl, atl, tss)
            return new_ctl, new_atl, session_date

        age = (metrics_date - session_date).days
        new_ctl = ctl + (tss / cls.CTL_TIME_CONSTANT) * (1 - 1 / cls.CTL_TIME_CONSTANT) ** age
        new_atl = atl + (tss / cls.ATL_TIME_CONSTANT) * (1 - 1 / cls.ATL_TIME_CONSTANT) ** age
        return round(new_ctl, 2), round(new_atl, 2), metrics_date

    @staticmethod
    def normalized_power(power_samples: List[float]) -> float:
        """Coggan NP from 1 Hz samples: 30 s rolling mean, 4th-power mean, 4th root."""
        if not power_samples:
            return 0.0
        window = 30
        if len(power_samples) < window:
            return sum(power_samples) / len(power_samples)
        rolling_sum = sum(power_samples[:window])
        fourth_powers = [(rolling_sum / window) ** 4]
        for i in range(window, len(power_samples)):
            rolling_sum += power_samples[i] - power_samples[i - window]
            fourth_powers.append((rolling_sum / window) ** 4)
        return (sum(fourth_powers) / len(fourth_powers)) ** 0.25

    @classmethod
    def estimate_session_tss(cls, intensity: int, duration_hours: float, sport: str = "cycling") -> float:
        """
        Estimates TSS based on intensity zone and duration in hours.
        Strength and stretching workouts default to 0 TSS.
        """
        if sport.lower() in ["strength", "stretching", "yoga", "rest"]:
            return 0.0
        multiplier = TSS_MULTIPLIER_MAP.get(intensity, 50)
        return round(duration_hours * multiplier, 1)

    @classmethod
    def calculate_actual_tss(
        cls,
        sport: str,
        duration_sec: int,
        avg_power: float = 0,
        normalized_power: float = 0,
        ftp: float = 200.0,
        avg_hr: float = 0,
        fthr: float = 170.0,
        rpe: int = None
    ) -> float:
        """
        Calculates actual TSS from recorded power, HR, or RPE.
        """
        duration_hours = duration_sec / 3600.0
        if duration_hours <= 0:
            return 0.0

        # 1. Power-based TSS (Gold Standard)
        if (normalized_power > 0 or avg_power > 0) and ftp > 0:
            np = normalized_power if normalized_power > 0 else avg_power
            intensity_factor = np / ftp
            tss = (duration_sec * np * intensity_factor) / (ftp * 3600.0) * 100.0
            return round(tss, 1)

        # 2. Heart-Rate-based hrTSS (Silver Standard)
        if avg_hr > 0 and fthr > 0:
            hr_ratio = avg_hr / fthr
            # Exponential hrTSS approximation
            tss = duration_hours * 100.0 * (hr_ratio ** 2)
            return round(tss, 1)

        # 3. RPE-based estimate (Fallback)
        if rpe is not None and 1 <= rpe <= 10:
            rpe_map = {1: 25, 2: 35, 3: 45, 4: 55, 5: 65, 6: 75, 7: 85, 8: 100, 9: 120, 10: 140}
            mult = rpe_map.get(rpe, 50)
            return round(duration_hours * mult, 1)

        # Default moderate estimate
        return round(duration_hours * 50.0, 1)
