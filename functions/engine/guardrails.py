"""
Physiological Guardrails and Safety Enforcement.
Prevents overtraining, manages injury/illness, and clamps training loads.
"""

from typing import List, Optional, Tuple
from core.models import UserProfile


class GuardrailEngine:
    """
    Applies physiological safety rules to training prescriptions.
    """

    @classmethod
    def apply_safety_clamps(
        cls,
        user_profile: UserProfile,
        requested_intensity: int,
        requested_duration: float,
        recent_intensities: List[int]
    ) -> Tuple[int, float, Optional[str]]:
        """
        Validates intensity and duration against fatigue, injury, and illness.
        Returns: (safe_intensity, safe_duration, reason_if_modified)
        """
        # 1. Severe Injury / Illness check
        if user_profile.injury == 2:
            return -1, 0.0, "Forced rest: Severe injury recovery in progress."
        if user_profile.illness == 2:
            return -1, 0.0, "Forced rest: Severe illness / infection recovery."

        # 2. Minor Injury / Illness check
        if user_profile.injury == 1 or user_profile.illness == 1:
            if requested_intensity > 2:
                safe_int = 2
                safe_dur = min(requested_duration, 1.0)
                return safe_int, safe_dur, "Intensity capped at Zone 2 due to minor injury/illness symptoms."

        # 3. Acute Fatigue (TSB < -25)
        tsb = user_profile.ctl - user_profile.atl
        if tsb < -25:
            if requested_intensity > 1:
                return 1, min(requested_duration, 1.0), "Active recovery forced: Deep fatigue detected (TSB < -25)."

        # 4. Consecutive High-Intensity Prevention (Zone >= 4)
        # Check if yesterday or the day before was a hard day (Zone >= 4)
        had_yesterday_hard = bool(recent_intensities and recent_intensities[-1] >= 4)
        if had_yesterday_hard and requested_intensity >= 4:
            # Drop to Zone 2 Aerobic Base to allow glycogen replenishment
            return 2, requested_duration, "Intensity adjusted to Zone 2: Consecutive high-intensity interval days avoided."

        return requested_intensity, requested_duration, None
