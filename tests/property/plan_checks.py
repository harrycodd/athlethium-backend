"""
Independent oracle for plan invariants.

Deliberately does NOT reuse engine code: it re-derives intensity from each step's %-of-threshold
targets so a bug in the engine's own classification can't hide a bug in the plan.

Zones (% of threshold power/pace, Seiler 3-zone model):
    low  < 76%   (Coggan Z1-Z2)
    mid  76-90%  (Z3 tempo / sweet spot: "grey zone")
    high > 90%   (Z4+ threshold, VO2, anaerobic, sprint)
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

NON_ENDURANCE = {"rest", "strength", "stretching", "yoga"}
HARD_DAY_HIGH_SECONDS = 5 * 60


def step_zone(step: Dict) -> str:
    low, high = step.get("target_low"), step.get("target_high")
    if low is None or high is None:
        return "none"
    mid = (low + high) / 2
    if mid < 76:
        return "low"
    if mid <= 90:
        return "mid"
    return "high"


def high_seconds(doc: Dict) -> int:
    return sum(s["duration"] for s in doc.get("steps", []) if step_zone(s) == "high")


def is_endurance(doc: Dict) -> bool:
    return doc.get("sport") not in NON_ENDURANCE and doc.get("time", 0) > 0


def is_race(doc: Dict) -> bool:
    return doc.get("event_type") == "Race"


def is_hard_day(doc: Dict) -> bool:
    if not is_endurance(doc):
        return False
    return is_race(doc) or (doc.get("intensity") or 0) >= 4 or high_seconds(doc) >= HARD_DAY_HIGH_SECONDS


def session_goal(doc: Dict) -> str:
    """Seiler session-goal method: the whole session counts toward its purpose."""
    intensity = doc.get("intensity") or 0
    if intensity >= 4:
        return "high"
    if intensity == 3:
        return "mid"
    return "low"


def monday(d: datetime.date) -> datetime.date:
    return d - datetime.timedelta(days=d.weekday())


@dataclass
class WeekStats:
    week_start: datetime.date
    hours: float = 0.0
    endurance_hours: float = 0.0
    tss: float = 0.0
    goal_split: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    zone_split: Dict[str, float] = field(default_factory=lambda: defaultdict(float))
    hard_days: int = 0
    has_race: bool = False

    def share(self, split: Dict[str, float], key: str) -> float:
        total = sum(split.values())
        return split.get(key, 0.0) / total if total else 0.0


def weekly_stats(docs: List[Dict]) -> List[WeekStats]:
    weeks: Dict[datetime.date, WeekStats] = {}
    for doc in docs:
        day = datetime.date.fromisoformat(doc["date"])
        ws = weeks.setdefault(monday(day), WeekStats(monday(day)))
        hours = (doc.get("time") or 0) / 3600
        ws.hours += hours
        ws.tss += doc.get("tss") or 0
        if is_race(doc):
            ws.has_race = True
            continue
        if not is_endurance(doc):
            continue
        ws.endurance_hours += hours
        ws.goal_split[session_goal(doc)] += hours
        for step in doc.get("steps", []):
            zone = step_zone(step)
            if zone != "none":
                ws.zone_split[zone] += step["duration"] / 3600
        if is_hard_day(doc):
            ws.hard_days += 1
    return [weeks[k] for k in sorted(weeks)]


def consecutive_hard_days(docs: List[Dict]) -> List[str]:
    """Dates of hard days that directly follow another hard day (across week boundaries too)."""
    hard = {datetime.date.fromisoformat(d["date"]) for d in docs if is_hard_day(d)}
    return sorted(d.isoformat() for d in hard if d - datetime.timedelta(days=1) in hard)
