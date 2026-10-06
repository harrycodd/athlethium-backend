"""
Intensity zones, athlete-specific targets and step-based load.

Every endurance step carries `target_low`/`target_high` as a percentage of the athlete's
threshold (FTP, threshold pace or CSS). This module turns those into the athlete's own numbers
(watts, bpm, pace) and computes TSS from the steps (IF^2 x hours x 100).
"""

from typing import Any, Dict, List, Optional, Tuple

from core.models import UserProfile

# Seiler 3-zone model on % of threshold.
LOW_MAX_PCT = 76.0
MID_MAX_PCT = 90.0

# Piecewise mapping of % threshold power/pace -> % threshold heart rate (Coggan zones).
# (pct_ftp, pct_fthr) breakpoints; HR plateaus above VO2 intensities.
_FTP_TO_HR = [(0, 0), (40, 50), (55, 68), (56, 69), (75, 83), (76, 84), (90, 94), (91, 95), (105, 105),
              (106, 106), (120, 108), (250, 108)]

# % threshold power -> % threshold *speed* for pace-based sports (Friel-style run/CSS zones):
# Z1 <78%, Z2 78-88%, Z3 88-95%, Z4 95-102%, Z5 102-110% of threshold speed.
_FTP_TO_SPEED = [(0, 60), (40, 70), (55, 78), (56, 78), (75, 88), (76, 88), (90, 95), (91, 95), (105, 102),
                 (106, 102), (120, 110), (250, 135)]

THRESHOLD_KEYS = ("cycling_power", "running_power", "running_pace", "swim_pace", "hr")


def step_zone(target_low: Optional[float], target_high: Optional[float]) -> Optional[str]:
    if target_low is None or target_high is None:
        return None
    mid = (target_low + target_high) / 2
    if mid < LOW_MAX_PCT:
        return "low"
    if mid <= MID_MAX_PCT:
        return "mid"
    return "high"


def _interpolate(table, pct: float) -> float:
    for (x0, y0), (x1, y1) in zip(table, table[1:], strict=False):
        if x0 <= pct <= x1:
            return y0 + (y1 - y0) * (pct - x0) / (x1 - x0) if x1 != x0 else y1
    return table[-1][1]


def pct_ftp_to_pct_hr(pct: float) -> float:
    return _interpolate(_FTP_TO_HR, pct)


def pct_ftp_to_pct_speed(pct: float) -> float:
    return _interpolate(_FTP_TO_SPEED, pct)


def threshold_known(profile: UserProfile, key: str) -> bool:
    return profile.known_thresholds is None or key in profile.known_thresholds


def threshold_for(profile: UserProfile, sport: str, target_type: str) -> Optional[Tuple[float, str, str]]:
    """Returns (threshold_value, unit, kind) or None if the athlete hasn't got that threshold."""
    if target_type == "power":
        if sport == "cycling" and threshold_known(profile, "cycling_power"):
            return profile.ftp_cycling or profile.ftp, "W", "power"
        if sport == "running" and threshold_known(profile, "running_power"):
            return profile.ftp_running, "W", "power"
        return None
    if target_type == "heart_rate":
        return (profile.fthr, "bpm", "hr") if threshold_known(profile, "hr") else None
    if target_type == "pace":
        if sport == "running" and threshold_known(profile, "running_pace"):
            return profile.ftp_pace_running, "s/km", "pace"
        if sport == "swimming" and threshold_known(profile, "swim_pace"):
            return profile.ftp_pace_swimming, "s/100m", "pace"
    return None


def absolute_range(pct_low: float, pct_high: float, threshold: float, kind: str) -> Tuple[float, float]:
    """Converts a %-threshold range into the athlete's own numbers (min, max)."""
    if kind == "power":
        return round(threshold * pct_low / 100), round(threshold * pct_high / 100)
    if kind == "hr":
        return round(threshold * pct_ftp_to_pct_hr(pct_low) / 100), round(threshold * pct_ftp_to_pct_hr(pct_high) / 100)
    # pace: higher intensity = faster = fewer seconds per distance
    return (round(threshold * 100 / pct_ftp_to_pct_speed(pct_high)),
            round(threshold * 100 / pct_ftp_to_pct_speed(pct_low)))


def apply_athlete_targets(steps: List[Dict[str, Any]], sport: str, target_type: str, profile: UserProfile) -> bool:
    """
    Adds `target_range` = {"unit", "min", "max"} to every step with % targets, computed from the
    athlete's own threshold. Returns False (and adds nothing) when that threshold is unknown.
    """
    resolved = threshold_for(profile, sport, target_type)
    if resolved is None:
        return False
    threshold, unit, kind = resolved
    for step in steps:
        low, high = step.get("target_low"), step.get("target_high")
        if low is None or high is None:
            continue
        lo, hi = absolute_range(low, high, threshold, kind)
        step["target_range"] = {"unit": unit, "min": lo, "max": hi}
    return True


def steps_tss(steps: List[Dict[str, Any]]) -> float:
    """TSS = sum(hours x IF^2 x 100) using each step's mid-target as its intensity factor."""
    total = 0.0
    for step in steps:
        low, high = step.get("target_low"), step.get("target_high")
        if low is None or high is None:
            continue
        intensity_factor = (low + high) / 200
        total += step["duration"] / 3600 * intensity_factor ** 2 * 100
    return round(total, 1)


def zone_seconds(steps: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"low": 0, "mid": 0, "high": 0}
    for step in steps:
        zone = step_zone(step.get("target_low"), step.get("target_high"))
        if zone:
            out[zone] += step["duration"]
    return out
