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
from i18n import t

MIN_STEP_SEC = 30
DEFAULT_DATE = datetime.date(2026, 1, 5)


@dataclass(frozen=True)
class Drill:
    key: str              # messages: drill.<key>.name / drill.<key>.cue
    seconds: int          # per side when per_side
    per_side: bool = False

    def name(self, lang: str) -> str:
        return t(lang, f"drill.{self.key}.name")

    def cue(self, lang: str) -> str:
        return t(lang, f"drill.{self.key}.cue")

    @property
    def total(self) -> int:
        return self.seconds * (2 if self.per_side else 1)


D = Drill

AREAS: Dict[str, List[Drill]] = {
    "calves": [
        D("wall_calf_stretch", 45, per_side=True),
        D("ankle_rocks", 45, per_side=True),
    ],
    "hips": [
        D("90_90_hip_switches", 60),
        D("pigeon_stretch", 60, per_side=True),
        D("deep_squat_hold", 60),
    ],
    "hamstrings": [
        D("lying_hamstring_stretch", 45, per_side=True),
        D("hamstring_floss", 45, per_side=True),
    ],
    "hip_flexors": [
        D("half_kneeling_hip_flexor_stretch", 60, per_side=True),
        D("couch_stretch", 60, per_side=True),
    ],
    "glutes": [
        D("figure_4_stretch", 45, per_side=True),
        D("glute_bridge_march", 45),
    ],
    "thoracic": [
        D("open_book_rotation", 45, per_side=True),
        D("thread_the_needle", 45, per_side=True),
        D("foam_roller_thoracic_extension", 60),
    ],
    "shoulders": [
        D("wall_slides", 60),
        D("doorway_chest_stretch", 45, per_side=True),
        D("sleeper_stretch", 45, per_side=True),
    ],
    "lats": [
        D("childs_pose_side_reach", 45, per_side=True),
        D("bench_lat_stretch", 45),
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
OPENER = D("cat_cow", 60)
CLOSER = D("childs_pose_breathing", 60)


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
                 session_date: Optional[datetime.date] = None, lang: str = "en") -> Dict[str, Any]:
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
            notes = (t(lang, "mobility.notes.perSide", seconds=drill.seconds, cue=drill.cue(lang)) if drill.per_side
                     else drill.cue(lang))
            steps.append(WorkoutStep("exercise", dur, drill.name(lang), target_type="time", notes=notes))
            remaining -= dur
        if steps:
            steps[-1].duration += remaining  # fill the session exactly
        if closer:
            steps.append(WorkoutStep("cooldown", closer, CLOSER.name(lang), target_type="time", notes=CLOSER.cue(lang)))

        # named for the focus area, else for the athlete's one endurance sport
        title = focus_key if focus_key in ("lower", "upper", "core") else None
        if title is None:
            endurance = [s for s in (sports or []) if s in SPORT_AREAS]
            title = endurance[0] if len(endurance) == 1 else ("multisport" if endurance else "athletic")
        names = t(lang, "list.separator").join(s.name for s in steps[1:-1]) if len(steps) > 2 else ""
        return {
            "name": t(lang, f"mobility.name.{title}"),
            "description": (t(lang, "mobility.description.drills", drills=names) if names
                            else t(lang, "mobility.description")),
            "steps": [s.to_dict() for s in steps],
            "targetType": "time",
            "total_duration_sec": total_sec,
        }
