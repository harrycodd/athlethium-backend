"""
Strength sessions for endurance athletes.

Every session is a complete gym session:
  warm-up drills -> A: lower-body compound lift -> B: push + pull superset -> C: second lower-body
  compound lift -> D: core (plus calf raises for runners) -> cool-down stretches.
Each exercise is a specific movement chosen from the athlete's equipment, with sets, reps, rest
and how heavy to go. Lifts stay the same for a 4-week block (so the athlete can add load), then
rotate; the two weekly sessions use different templates (A early in the week, B later).
"""

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.models import WorkoutStep
from i18n import t

BLOCK_DAYS = 28              # keep the same lifts for a 4-week block, then rotate
WARMUP_SEC = 300
COOLDOWN_SEC = 180
SHORT_SESSION_SEC = 25 * 60  # below this the last compound block is dropped
DEFAULT_DATE = datetime.date(2026, 1, 5)


@dataclass(frozen=True)
class Exercise:
    key: str                      # messages: exercise.<key>.name / exercise.<key>.cue
    needs: Tuple[str, ...] = ()   # all of these (besides bodyweight) are required
    per_side: bool = False
    hold_sec: int = 0             # > 0: a timed hold instead of reps

    def name(self, lang: str) -> str:
        return t(lang, f"exercise.{self.key}.name")

    def cue(self, lang: str) -> str:
        return t(lang, f"exercise.{self.key}.cue")


E = Exercise

# Within each pattern, loaded options come first; the last option always needs no equipment.
VARIANTS: Dict[str, List[Exercise]] = {
    "squat": [
        E("barbell_back_squat", ("squat_rack",)),
        E("dumbbell_goblet_squat", ("dumbbells",)),
        E("kettlebell_goblet_squat", ("kettlebells",)),
        E("tempo_bodyweight_squat"),
    ],
    "hinge": [
        E("barbell_romanian_deadlift", ("barbell",)),
        E("dumbbell_romanian_deadlift", ("dumbbells",)),
        E("kettlebell_deadlift", ("kettlebells",)),
        E("single_leg_romanian_deadlift", per_side=True),
    ],
    "single_leg": [
        E("dumbbell_bulgarian_split_squat", ("dumbbells", "bench"), per_side=True),
        E("dumbbell_step_up", ("dumbbells", "bench"), per_side=True),
        E("dumbbell_reverse_lunge", ("dumbbells",), per_side=True),
        E("bulgarian_split_squat", per_side=True),
        E("reverse_lunge", per_side=True),
    ],
    "push": [
        E("barbell_bench_press", ("barbell", "bench")),
        E("dumbbell_bench_press", ("dumbbells", "bench")),
        E("dumbbell_floor_press", ("dumbbells",)),
        E("push_up"),
    ],
    "vertical_push": [
        E("standing_dumbbell_overhead_press", ("dumbbells",)),
        E("half_kneeling_kettlebell_press", ("kettlebells",), per_side=True),
        E("pike_push_up"),
    ],
    "pull": [
        E("pull_up", ("pullup_bar",)),
        E("lat_pulldown", ("lat_pulldown",)),
        E("seated_cable_row", ("cables",)),
        E("one_arm_dumbbell_row", ("dumbbells",), per_side=True),
        E("resistance_band_row", ("bands",)),
        E("inverted_row"),
    ],
    "core": [
        E("dead_bug", per_side=True),
        E("side_plank", per_side=True, hold_sec=30),
        E("pallof_press", ("bands",), per_side=True),
        E("hanging_knee_raise", ("pullup_bar",)),
        E("suitcase_carry", ("dumbbells",), per_side=True, hold_sec=40),
        E("bird_dog", per_side=True),
        E("front_plank", hold_sec=40),
    ],
}
CALF_RAISE = E("single_leg_calf_raise", per_side=True)

# Compound blocks per focus: template A (early week) and B (later in the week). A block with two
# patterns is a superset.
TEMPLATES: Dict[str, Tuple[List[Tuple[str, ...]], List[Tuple[str, ...]]]] = {
    "full": ([("squat",), ("push", "pull"), ("hinge",)],
             [("single_leg",), ("vertical_push", "pull"), ("hinge",)]),
    "lower": ([("squat",), ("hinge",), ("single_leg",)],
              [("hinge",), ("single_leg",), ("squat",)]),
    "upper": ([("push",), ("pull",), ("vertical_push",)],
              [("pull",), ("vertical_push",), ("push",)]),
    "core": ([("squat",), ("push", "pull")],
             [("hinge",), ("vertical_push", "pull")]),
}
FOCUS_ALIASES = {"legs": "lower", "all": "full", "full_body": "full"}
# names: strength.name.<focus>; the athlete's level picks the prescription (sets, reps), and its
# rest and load advice (strength.rest.<tier>, strength.load.<tier>)

# (sets, reps) for the compound lifts. Heavy, low-rep lifting is what improves endurance economy;
# beginners build technique with lighter, higher-rep sets first.
PRESCRIPTIONS = {
    "beginner": (3, 10),
    "intermediate": (3, 8),
    "heavy": (4, 5),
}


def _prescription(level: Optional[str], difficulty: int) -> str:
    if level:
        return level if level in ("beginner", "intermediate") else "heavy"
    return "beginner" if difficulty <= 1 else "intermediate"


def _pick(pattern: str, equipment: set, rotation: int) -> Exercise:
    """Rotates through the loaded options the athlete can do; bodyweight only when nothing fits."""
    options = [e for e in VARIANTS[pattern] if set(e.needs) <= equipment]
    loaded = [e for e in options if e.needs]
    pool = loaded or options
    return pool[rotation % len(pool)]


def _dose(ex: Exercise, sets: int, reps: int, lang: str) -> str:
    side = ".perSide" if ex.per_side else ""
    if ex.hold_sec:
        return t(lang, "strength.dose.hold" + side, sets=sets, seconds=ex.hold_sec)
    return t(lang, "strength.dose.reps" + side, sets=sets, reps=reps)


class StrengthGenerator:
    """Builds structured strength sessions with named exercises, sets, reps, rest and load."""

    @classmethod
    def generate(
        cls,
        focus: str = "full",
        duration_minutes: int = 30,
        difficulty: int = 2,
        user_equipment: Optional[List[str]] = None,
        session_date: Optional[datetime.date] = None,
        sports: Optional[Sequence[str]] = None,
        level: Optional[str] = None,
        lang: str = "en",
    ) -> Dict[str, Any]:
        focus_key = FOCUS_ALIASES.get(focus.lower(), focus.lower())
        if focus_key not in TEMPLATES:
            focus_key = "full"
        total_sec = max(0, int(duration_minutes * 60))
        if total_sec == 0:
            return {"name": t(lang, f"strength.name.{focus_key}"), "description": "", "steps": [],
                    "targetType": "reps", "total_duration_sec": 0}

        equipment = set(user_equipment or []) | {"bodyweight"}
        day = session_date or DEFAULT_DATE
        template = 0 if day.weekday() < 3 else 1   # the two weekly sessions get different lifts
        rotation = day.toordinal() // BLOCK_DAYS     # same lifts for a 4-week block
        tier = _prescription(level, difficulty)
        sets, reps = PRESCRIPTIONS[tier]
        rest, load = t(lang, f"strength.rest.{tier}"), t(lang, f"strength.load.{tier}")

        blocks = TEMPLATES[focus_key][template]
        if total_sec < SHORT_SESSION_SEC:
            blocks = blocks[:2]

        plan: List[Tuple[str, Exercise, int, int, str]] = []  # (block label, exercise, sets, reps, notes)
        for b, block in enumerate(blocks):
            letter = "ABC"[b]
            picks = [_pick(pattern, equipment, rotation + b + template) for pattern in block]
            for i, ex in enumerate(picks):
                if len(picks) > 1:
                    label = f"{letter}{i + 1}"
                    rest_note = t(lang, "strength.rest.superset", exercise=picks[1 - i].name(lang), rest=rest)
                else:
                    label, rest_note = letter, t(lang, "strength.rest.straight", rest=rest)
                plan.append((label, ex, sets, reps, t(lang, "strength.notes.lift", dose=_dose(ex, sets, reps, lang),
                                                      cue=ex.cue(lang), rest=rest_note, load=load)))

        # Finisher: core, plus calf raises for runners (calf and Achilles resilience)
        finisher = [_pick("core", equipment, rotation + template + 3 * k)
                    for k in range(2 if focus_key == "core" else 1)]
        if "running" in (sports or []):
            finisher.append(CALF_RAISE)
        for k, ex in enumerate(finisher):
            f_sets, f_reps = (3, 12) if ex is CALF_RAISE else (2, 8)
            plan.append((f"D{k + 1}", ex, f_sets, f_reps,
                         t(lang, "strength.notes.finisher", dose=_dose(ex, f_sets, f_reps, lang), cue=ex.cue(lang))))

        # Fixed warm-up and cool-down (scaled down for short sessions); the rest is split across
        # the exercises by number of sets, the last one absorbing rounding.
        short = total_sec < SHORT_SESSION_SEC
        warmup = total_sec * 15 // 100 if short else WARMUP_SEC
        cooldown = total_sec * 10 // 100 if short else COOLDOWN_SEC
        work = total_sec - warmup - cooldown
        total_sets = sum(p[2] for p in plan)
        steps = [WorkoutStep("warmup", warmup, t(lang, "step.warmup"), target_type="time",
                             notes=t(lang, "strength.notes.warmup"))]
        used = 0
        for i, (label, ex, s, r, notes) in enumerate(plan):
            dur = work - used if i == len(plan) - 1 else work * s // total_sets
            used += dur
            steps.append(WorkoutStep("exercise", dur, t(lang, "strength.step.name", label=label, exercise=ex.name(lang)),
                                     target_type="reps", sets=s,
                                     reps=None if ex.hold_sec else r, notes=notes))
        steps.append(WorkoutStep("cooldown", cooldown, t(lang, "strength.step.cooldown"), target_type="time",
                                 notes=t(lang, "strength.notes.cooldown")))

        summary = t(lang, "strength.summary.separator").join(
            t(lang, "strength.summary.item", exercise=ex.name(lang), dose=_dose(ex, s, r, lang))
            for _, ex, s, r, _ in plan)
        return {
            "name": t(lang, f"strength.name.{focus_key}.variant", variant="AB"[template]),
            "description": t(lang, "strength.description", summary=summary),
            "steps": [step.to_dict() for step in steps],
            "targetType": "reps",
            "total_duration_sec": total_sec,
        }
