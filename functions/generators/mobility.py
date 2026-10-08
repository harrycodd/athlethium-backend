"""
Mobility sessions: named stretches and mobility drills with timings, chosen for the athlete's sports.

Runners get calves, hips and hamstrings; cyclists hip flexors, upper back and glutes; swimmers
shoulders, lats and upper back. A goal note can steer the focus (lower / upper / core). Exercises
are taken in turn from each area and rotate week to week; the session always starts with Cat-Cow
and the durations fill the session exactly.
"""

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from core.models import WorkoutStep

MIN_STEP_SEC = 30
DEFAULT_DATE = datetime.date(2026, 1, 5)


@dataclass(frozen=True)
class Drill:
    name: str
    seconds: int          # per side when per_side
    cue: str
    per_side: bool = False

    @property
    def total(self) -> int:
        return self.seconds * (2 if self.per_side else 1)


D = Drill

AREAS: Dict[str, List[Drill]] = {
    "calves": [
        D("Wall Calf Stretch", 45, "Back leg straight for 20 s, then bend the knee for the rest.", per_side=True),
        D("Ankle Rocks", 45, "Half-kneeling, drive the front knee over the toes and back, heel down.", per_side=True),
    ],
    "hips": [
        D("90/90 Hip Switches", 60, "Sit tall, rotate both knees side to side slowly; pause at each end."),
        D("Pigeon Stretch", 60, "Front shin across the body, hips square; fold forward to deepen.", per_side=True),
        D("Deep Squat Hold", 60, "Heels down, elbows push the knees out, chest up."),
    ],
    "hamstrings": [
        D("Lying Hamstring Stretch", 45, "Strap or towel round the foot, leg straight, pull gently.", per_side=True),
        D("Hamstring Floss", 45, "Half-kneeling, straighten and bend the front leg for 10 slow reps.", per_side=True),
    ],
    "hip_flexors": [
        D("Half-Kneeling Hip Flexor Stretch", 60, "Squeeze the back glute, tuck the pelvis, reach the arm up.",
          per_side=True),
        D("Couch Stretch", 60, "Back knee at the wall, shin up the wall; stay upright.", per_side=True),
    ],
    "glutes": [
        D("Figure-4 Stretch", 45, "On your back, ankle over the opposite knee, pull the leg in.", per_side=True),
        D("Glute Bridge March", 45, "Hold the bridge, lift one foot at a time without the hips dropping."),
    ],
    "thoracic": [
        D("Open Book Rotation", 45, "Side-lying, knees bent; rotate the top arm open and follow it with your eyes.",
          per_side=True),
        D("Thread the Needle", 45, "On all fours, reach one arm under the body, then open it to the ceiling.",
          per_side=True),
        D("Foam Roller Thoracic Extension", 60, "Roller across the upper back, hands behind the head, extend over it."),
    ],
    "shoulders": [
        D("Wall Slides", 60, "Back and forearms on the wall; slide up without the ribs flaring."),
        D("Doorway Chest Stretch", 45, "Forearm on the door frame at shoulder height, step through.", per_side=True),
        D("Sleeper Stretch", 45, "Lie on your side, arm at 90°; gently press the forearm down.", per_side=True),
    ],
    "lats": [
        D("Child's Pose Side Reach", 45, "Walk both hands to one side and breathe into the ribs.", per_side=True),
        D("Bench Lat Stretch", 45, "Kneel, elbows on a bench, sink the chest towards the floor."),
    ],
}
SPORT_AREAS = {
    "running": ["calves", "hips", "hamstrings", "hip_flexors"],
    "cycling": ["hip_flexors", "thoracic", "glutes", "hamstrings"],
    "swimming": ["shoulders", "lats", "thoracic"],
}
FOCUS_AREAS = {
    "lower": ["hips", "hamstrings", "hip_flexors", "calves", "glutes"],
    "upper": ["shoulders", "thoracic", "lats"],
    "core": ["thoracic", "hip_flexors", "glutes", "lats"],
}
FOCUS_ALIASES = {"legs": "lower", "all": "full", "full_body": "full"}
SPORT_TITLES = {"running": "Runner's", "cycling": "Cyclist's", "swimming": "Swimmer's"}
OPENER = D("Cat-Cow", 60, "Slowly arch and round the spine with the breath.")
CLOSER = D("Child's Pose Breathing", 60, "Long breaths out through the mouth to switch off.")


def _areas(focus: str, sports: Optional[Sequence[str]]) -> List[str]:
    if focus in FOCUS_AREAS:
        return FOCUS_AREAS[focus]
    out: List[str] = []
    for sport in sports or []:
        out += [a for a in SPORT_AREAS.get(sport, []) if a not in out]
    return out or ["hips", "hip_flexors", "thoracic", "hamstrings", "shoulders"]


class MobilityGenerator:
    """Builds a timed mobility session of named drills for the athlete's sports."""

    @classmethod
    def generate(cls, focus: str = "full", duration_minutes: int = 20, difficulty: int = 1,
                 sports: Optional[Sequence[str]] = None,
                 session_date: Optional[datetime.date] = None) -> Dict[str, Any]:
        focus_key = FOCUS_ALIASES.get(focus.lower(), focus.lower())
        total_sec = max(0, int(duration_minutes * 60))
        rotation = (session_date or DEFAULT_DATE).toordinal() // 7

        # Cat-Cow, then one drill from each area in turn; breathing always closes the session
        areas = _areas(focus_key, sports)
        drills = [OPENER]
        for round_ in range(max(len(v) for v in AREAS.values())):
            for area in areas:
                options = AREAS[area]
                if round_ < len(options):
                    drills.append(options[(rotation + round_) % len(options)])

        closer = CLOSER.total if total_sec >= OPENER.total + CLOSER.total + MIN_STEP_SEC else 0
        steps: List[WorkoutStep] = []
        remaining = total_sec - closer
        for drill in drills:
            if remaining < MIN_STEP_SEC:
                break
            dur = min(drill.total, remaining)
            side = f"{drill.seconds} s each side. " if drill.per_side else ""
            steps.append(WorkoutStep("exercise", dur, drill.name, target_type="time", notes=f"{side}{drill.cue}"))
            remaining -= dur
        if steps:
            steps[-1].duration += remaining  # fill the session exactly
        if closer:
            steps.append(WorkoutStep("cooldown", closer, CLOSER.name, target_type="time", notes=CLOSER.cue))

        title = {"lower": "Lower Body", "upper": "Upper Body", "core": "Core & Spine"}.get(focus_key)
        if title is None:
            endurance = [s for s in (sports or []) if s in SPORT_AREAS]
            title = SPORT_TITLES[endurance[0]] if len(endurance) == 1 else (
                "Multisport" if endurance else "Athletic")
        names = ", ".join(s.name for s in steps[1:-1]) if len(steps) > 2 else ""
        return {
            "name": f"{title} Mobility",
            "description": f"Mobility for range of motion and recovery{': ' + names if names else ''}.",
            "steps": [s.to_dict() for s in steps],
            "targetType": "time",
            "total_duration_sec": total_sec,
        }
