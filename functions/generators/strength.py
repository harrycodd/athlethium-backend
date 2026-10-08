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

BLOCK_DAYS = 28              # keep the same lifts for a 4-week block, then rotate
WARMUP_SEC = 300
COOLDOWN_SEC = 180
SHORT_SESSION_SEC = 25 * 60  # below this the last compound block is dropped
DEFAULT_DATE = datetime.date(2026, 1, 5)


@dataclass(frozen=True)
class Exercise:
    name: str
    needs: Tuple[str, ...] = ()   # all of these (besides bodyweight) are required
    per_side: bool = False
    hold_sec: int = 0             # > 0: a timed hold instead of reps
    cue: str = ""


E = Exercise

# Within each pattern, loaded options come first; the last option always needs no equipment.
VARIANTS: Dict[str, List[Exercise]] = {
    "squat": [
        E("Barbell Back Squat", ("squat_rack",), cue="Brace, sit down between your hips, drive up through the mid-foot."),
        E("Dumbbell Goblet Squat", ("dumbbells",),
          cue="Hold a dumbbell at your chest; elbows inside the knees at the bottom."),
        E("Kettlebell Goblet Squat", ("kettlebells",), cue="Hold the bell by the horns at your chest; sit deep, chest up."),
        E("Tempo Bodyweight Squat", cue="3 s down, 1 s pause at the bottom, stand up tall."),
    ],
    "hinge": [
        E("Barbell Romanian Deadlift", ("barbell",),
          cue="Soft knees, push the hips back until the hamstrings load; bar close to the legs."),
        E("Dumbbell Romanian Deadlift", ("dumbbells",),
          cue="Dumbbells slide down the thighs; flat back, hips back, squeeze the glutes to stand."),
        E("Kettlebell Deadlift", ("kettlebells",), cue="Bell between the feet, hips back, flat back, stand tall."),
        E("Single-Leg Romanian Deadlift", per_side=True,
          cue="Reach the free leg back with hips square; touch a wall for balance if needed."),
    ],
    "single_leg": [
        E("Dumbbell Bulgarian Split Squat", ("dumbbells", "bench"), per_side=True,
          cue="Rear foot on the bench, front shin close to vertical, lower under control."),
        E("Dumbbell Step-Up", ("dumbbells", "bench"), per_side=True,
          cue="Drive through the top foot; don't push off with the bottom one."),
        E("Dumbbell Reverse Lunge", ("dumbbells",), per_side=True, cue="Step back, back knee to just above the floor."),
        E("Bulgarian Split Squat", per_side=True, cue="Rear foot on a chair or step; front knee tracks over the toes."),
        E("Reverse Lunge", per_side=True,
          cue="Step back, back knee to just above the floor, push through the front heel."),
    ],
    "push": [
        E("Barbell Bench Press", ("barbell", "bench"),
          cue="Shoulder blades squeezed together, bar to mid-chest, press up and back."),
        E("Dumbbell Bench Press", ("dumbbells", "bench"),
          cue="Lower the dumbbells to chest level, elbows about 45° from the body."),
        E("Dumbbell Floor Press", ("dumbbells",), cue="Lie on the floor; lower until the upper arms touch it, then press."),
        E("Push-Up", cue="Body in one straight line; hands on a bench makes it easier, feet on it harder."),
    ],
    "vertical_push": [
        E("Standing Dumbbell Overhead Press", ("dumbbells",), cue="Ribs down, glutes tight, press straight overhead."),
        E("Half-Kneeling Kettlebell Press", ("kettlebells",), per_side=True,
          cue="Squeeze the glute of the down knee; press without leaning."),
        E("Pike Push-Up", cue="Hips high, lower the top of your head towards the floor between your hands."),
    ],
    "pull": [
        E("Pull-Up", ("pullup_bar",),
          cue="Full hang to chin over the bar; use a band or slow 5 s lowers if you can't do the reps."),
        E("Lat Pulldown", ("lat_pulldown",), cue="Pull the bar to the top of the chest, elbows down and back."),
        E("Seated Cable Row", ("cables",), cue="Tall chest, pull the handle to the stomach, squeeze the shoulder blades."),
        E("One-Arm Dumbbell Row", ("dumbbells",), per_side=True,
          cue="Hand and knee on a bench or chair; row the dumbbell to the hip."),
        E("Resistance Band Row", ("bands",), cue="Band anchored at chest height; pull the elbows back past the ribs."),
        E("Inverted Row", cue="Under a sturdy table or low bar, body straight; pull the chest to it."),
    ],
    "core": [
        E("Dead Bug", per_side=True, cue="Lower back pressed to the floor; slowly extend the opposite arm and leg."),
        E("Side Plank", per_side=True, hold_sec=30, cue="Hips high, straight line from head to heels."),
        E("Pallof Press", ("bands",), per_side=True, cue="Band at chest height to your side; press out and resist the twist."),
        E("Hanging Knee Raise", ("pullup_bar",), cue="No swinging; curl the pelvis up, lower slowly."),
        E("Suitcase Carry", ("dumbbells",), per_side=True, hold_sec=40,
          cue="Heavy dumbbell in one hand; walk tall without leaning."),
        E("Bird Dog", per_side=True, cue="Reach the opposite arm and leg long, hold 2 s, keep the hips level."),
        E("Front Plank", hold_sec=40, cue="Squeeze the glutes and brace; don't let the hips sag."),
    ],
}
CALF_RAISE = E("Single-Leg Calf Raise", per_side=True,
               cue="On a step: full stretch at the bottom, 2 s up, 2 s down. Hold a dumbbell once 15 reps is easy.")

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
FOCUS_TITLES = {"full": "Full Body", "lower": "Lower Body", "upper": "Upper Body", "core": "Core & Full Body"}

# (sets, reps, rest, load) for the compound lifts. Heavy, low-rep lifting is what improves
# endurance economy; beginners build technique with lighter, higher-rep sets first.
PRESCRIPTIONS = {
    "beginner": (3, 10, "90 s", "Moderate weight: finish each set with 3-4 reps left in the tank."),
    "intermediate": (3, 8, "2 min", "Challenging weight: finish each set with 2-3 reps left in the tank."),
    "heavy": (4, 5, "2-3 min", "Heavy: finish each set with 2 reps left in the tank. Never to failure."),
}

WARMUP_NOTES = ("2 rounds: 10 bodyweight squats, 5 walking lunges each leg, 10 glute bridges, "
                "10 band pull-aparts or arm circles. Then 1-2 light sets of the first lift.")
COOLDOWN_NOTES = ("Half-kneeling hip flexor stretch 30 s each side, standing hamstring stretch 30 s each side, "
                  "doorway chest stretch 30 s.")


def _prescription(level: Optional[str], difficulty: int) -> Tuple[int, int, str, str]:
    if level:
        return PRESCRIPTIONS[level if level in ("beginner", "intermediate") else "heavy"]
    return PRESCRIPTIONS["beginner" if difficulty <= 1 else "intermediate"]


def _pick(pattern: str, equipment: set, rotation: int) -> Exercise:
    """Rotates through the loaded options the athlete can do; bodyweight only when nothing fits."""
    options = [e for e in VARIANTS[pattern] if set(e.needs) <= equipment]
    loaded = [e for e in options if e.needs]
    pool = loaded or options
    return pool[rotation % len(pool)]


def _dose(ex: Exercise, sets: int, reps: int) -> str:
    each = " each side" if ex.per_side else ""
    return f"{sets} × {ex.hold_sec} s hold{each}" if ex.hold_sec else f"{sets} × {reps}{each}"


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
    ) -> Dict[str, Any]:
        focus_key = FOCUS_ALIASES.get(focus.lower(), focus.lower())
        if focus_key not in TEMPLATES:
            focus_key = "full"
        title = FOCUS_TITLES[focus_key]
        total_sec = max(0, int(duration_minutes * 60))
        if total_sec == 0:
            return {"name": f"{title} Strength", "description": "", "steps": [], "targetType": "reps",
                    "total_duration_sec": 0}

        equipment = set(user_equipment or []) | {"bodyweight"}
        day = session_date or DEFAULT_DATE
        template = 0 if day.weekday() < 3 else 1   # the two weekly sessions get different lifts
        rotation = day.toordinal() // BLOCK_DAYS     # same lifts for a 4-week block
        sets, reps, rest, load = _prescription(level, difficulty)

        blocks = TEMPLATES[focus_key][template]
        if total_sec < SHORT_SESSION_SEC:
            blocks = blocks[:2]

        plan: List[Tuple[str, Exercise, int, int, str]] = []  # (step name, exercise, sets, reps, notes)
        for b, block in enumerate(blocks):
            letter = "ABC"[b]
            picks = [_pick(pattern, equipment, rotation + b + template) for pattern in block]
            for i, ex in enumerate(picks):
                if len(picks) > 1:
                    label = f"{letter}{i + 1}"
                    rest_note = f"Superset with {picks[1 - i].name}: alternate sets, rest {rest} after each pair."
                else:
                    label, rest_note = letter, f"Rest {rest} between sets."
                plan.append((f"{label}. {ex.name}", ex, sets, reps,
                             f"{_dose(ex, sets, reps)}. {ex.cue} {rest_note} {load}"))

        # Finisher: core, plus calf raises for runners (calf and Achilles resilience)
        finisher = [_pick("core", equipment, rotation + template + 3 * k)
                    for k in range(2 if focus_key == "core" else 1)]
        if "running" in (sports or []):
            finisher.append(CALF_RAISE)
        for k, ex in enumerate(finisher):
            f_sets, f_reps = (3, 12) if ex is CALF_RAISE else (2, 8)
            plan.append((f"D{k + 1}. {ex.name}", ex, f_sets, f_reps,
                         f"{_dose(ex, f_sets, f_reps)}. {ex.cue} Rest 45 s."))

        # Fixed warm-up and cool-down (scaled down for short sessions); the rest is split across
        # the exercises by number of sets, the last one absorbing rounding.
        short = total_sec < SHORT_SESSION_SEC
        warmup = total_sec * 15 // 100 if short else WARMUP_SEC
        cooldown = total_sec * 10 // 100 if short else COOLDOWN_SEC
        work = total_sec - warmup - cooldown
        total_sets = sum(p[2] for p in plan)
        steps = [WorkoutStep("warmup", warmup, "Warm-up", target_type="time", notes=WARMUP_NOTES)]
        used = 0
        for i, (name, ex, s, r, notes) in enumerate(plan):
            dur = work - used if i == len(plan) - 1 else work * s // total_sets
            used += dur
            steps.append(WorkoutStep("exercise", dur, name, target_type="reps", sets=s,
                                     reps=None if ex.hold_sec else r, notes=notes))
        steps.append(WorkoutStep("cooldown", cooldown, "Cool-down Stretches", target_type="time",
                                 notes=COOLDOWN_NOTES))

        summary = "; ".join(f"{name.split('. ', 1)[1]} {_dose(ex, s, r)}" for name, ex, s, r, _ in plan)
        return {
            "name": f"{title} Strength {'AB'[template]}",
            "description": f"Strength for endurance performance and injury resistance: {summary}.",
            "steps": [step.to_dict() for step in steps],
            "targetType": "reps",
            "total_duration_sec": total_sec,
        }
