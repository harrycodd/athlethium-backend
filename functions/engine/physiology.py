"""
Physiological Modeling & Fitness/Fatigue Calculations.
Implements the Banister Impulse-Response model (CTL, ATL, TSB).
"""

from typing import Dict, Any, Tuple
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
