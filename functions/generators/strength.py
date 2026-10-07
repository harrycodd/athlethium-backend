"""
Strength Workout Generator for Functional & Endurance Athletes.
Selects exercises based on user equipment and targeted anatomical focus.
"""

from typing import Dict, Any, List, Optional
from core.models import WorkoutStep


class StrengthGenerator:
    """
    Builds structured strength workouts with sets, reps, tempo, and rest.
    """

    EXERCISES = {
        "lower": [
            {"name": "Goblet Squats", "equip": ["dumbbells", "kettlebells", "weights", "bodyweight"], "sets": 3, "reps": 10},
            {"name": "Romanian Deadlifts (RDL)", "equip": ["dumbbells", "barbell", "weights"], "sets": 3, "reps": 10},
            {"name": "Walking Lunges", "equip": ["dumbbells", "kettlebells", "bodyweight"], "sets": 3, "reps": 12},
            {"name": "Bulgarian Split Squats", "equip": ["dumbbells", "bench", "bodyweight"], "sets": 3, "reps": 8},
            {"name": "Calf Raises", "equip": ["bodyweight", "dumbbells"], "sets": 3, "reps": 15},
            {"name": "Single-Leg Glute Bridges", "equip": ["bodyweight", "bands"], "sets": 3, "reps": 12}
        ],
        "upper": [
            {"name": "Push-Ups / Dumbbell Bench Press", "equip": ["bench", "dumbbells", "bodyweight"], "sets": 3, "reps": 10},
            {"name": "Dumbbell Bent-Over Rows", "equip": ["dumbbells", "barbell", "weights"], "sets": 3, "reps": 10},
            {"name": "Overhead Shoulder Press", "equip": ["dumbbells", "kettlebells", "barbell"], "sets": 3, "reps": 10},
            {"name": "Pull-Ups / Lat Pulldown", "equip": ["pullup_bar", "lat_pulldown", "bands", "bodyweight"], "sets": 3, "reps": 8},
            {"name": "Face Pulls / Band Pull-Aparts", "equip": ["bands", "cables"], "sets": 3, "reps": 15},
            {"name": "Plank Shoulder Taps", "equip": ["bodyweight"], "sets": 3, "reps": 16}
        ],
        "core": [
            {"name": "Plank Hold / Hollow Body", "equip": ["bodyweight"], "sets": 3, "reps": 45},
            {"name": "Hanging Leg Raises / Toes to Bar", "equip": ["pullup_bar", "bodyweight"], "sets": 3, "reps": 12},
            {"name": "Ab Wheel Rollouts / Deadbugs", "equip": ["bodyweight", "weights"], "sets": 3, "reps": 10},
            {"name": "Side Plank Rotations", "equip": ["bodyweight"], "sets": 3, "reps": 10},
            {"name": "Russian Twists / Cable Chops", "equip": ["dumbbells", "cables", "bodyweight"], "sets": 3, "reps": 16},
            {"name": "Bird-Dog Extensions", "equip": ["bodyweight", "bands"], "sets": 3, "reps": 12}
        ],
        "full": [
            {"name": "Squat to Overhead Press (Thruster)", "equip": ["dumbbells", "kettlebells", "bodyweight"], "sets": 3, "reps": 10},
            {"name": "Deadlift / Hip Hinge", "equip": ["dumbbells", "barbell", "weights", "bodyweight"], "sets": 3, "reps": 8},
            {"name": "Push-Ups / Chest Press", "equip": ["dumbbells", "bench", "bodyweight"], "sets": 3, "reps": 10},
            {"name": "Single-Arm Dumbbell Row", "equip": ["dumbbells", "kettlebells", "bench"], "sets": 3, "reps": 10},
            {"name": "Plank / Hollow Body Hold", "equip": ["bodyweight"], "sets": 3, "reps": 45},
            {"name": "Side Plank Rotations", "equip": ["bodyweight"], "sets": 3, "reps": 10}
        ]
    }

    @classmethod
    def generate(
        cls,
        focus: str = "full",
        duration_minutes: int = 45,
        difficulty: int = 2,
        user_equipment: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        if user_equipment is None:
            user_equipment = ["bodyweight", "dumbbells"]

        # Normalize focus aliases
        focus_aliases = {
            "legs": "lower",
            "all": "full",
            "full_body": "full",
        }
        normalized_focus = focus_aliases.get(focus.lower(), focus.lower())
        focus_key = normalized_focus if normalized_focus in cls.EXERCISES else "full"

        eq_set = set(user_equipment + ["bodyweight"])
        available_pool = [
            ex for ex in cls.EXERCISES[focus_key]
            if any(eq in eq_set for eq in ex["equip"]) or "bodyweight" in ex["equip"]
        ]
        if not available_pool:
            available_pool = cls.EXERCISES["full"]


        # Number of exercises based on duration (approx 6-8 mins per exercise including rests)
        num_exercises = max(3, min(6, duration_minutes // 8))
        selected_exercises = available_pool[:num_exercises]

        total_sec = duration_minutes * 60
        warmup_sec = 300
        cooldown_sec = 300
        work_sec_per_ex = (total_sec - warmup_sec - cooldown_sec) // len(selected_exercises)

        steps: List[WorkoutStep] = [
            WorkoutStep("warmup", warmup_sec, "Dynamic Movement & Joint Mobility", None, None, "time", notes="Hip circles, arm sweeps, world's greatest stretch")
        ]

        for ex in selected_exercises:
            steps.append(WorkoutStep(
                type="exercise",
                duration=work_sec_per_ex,
                name=ex["name"],
                target_type="reps",
                sets=ex["sets"],
                reps=ex["reps"],
                notes=f"Perform {ex['sets']} sets of {ex['reps']} reps with 60-90s rest between sets."
            ))

        steps.append(WorkoutStep("cooldown", cooldown_sec, "Cool Down & Static Stretches", None, None, "time"))

        title = f"{focus.capitalize()} Body Functional Strength"
        description = (
            f"Targeted {focus} body strength training to reinforce structural integrity, "
            f"power transfer, and injury resistance. Complete {len(selected_exercises)} compound exercises."
        )

        return {
            "name": title,
            "description": description,
            "steps": [s.to_dict() for s in steps],
            "targetType": "reps",
            "total_duration_sec": total_sec
        }
