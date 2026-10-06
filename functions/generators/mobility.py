"""
Mobility and Stretching Routine Generator.
"""

from typing import Dict, Any, List
from core.models import WorkoutStep


class MobilityGenerator:
    """
    Builds structured mobility, yoga, and stretching routines.
    """

    ROUTINES = {
        "lower": [
            {"name": "Low Lunge Hip Flexor Stretch", "duration": 180, "notes": "90s per side with reach"},
            {"name": "Pigeon Pose / Figure-4 Glute Stretch", "duration": 240, "notes": "2 mins each side"},
            {"name": "Seated Hamstring & Calf Reach", "duration": 180, "notes": "Hinge at hips, keep spine long"},
            {"name": "Deep Squat Ankle & Hip Opener", "duration": 180, "notes": "Pry hips open with elbows"},
            {"name": "Front Splits / Half Splits Flow", "duration": 240, "notes": "Gentle hamstring & hip flexor elongation"},
            {"name": "Frog Pose Hip Abduction", "duration": 180, "notes": "Hold and breathe deeply"}
        ],
        "core": [
            {"name": "Cat-Cow Dynamic Spine Waves", "duration": 120, "notes": "Inhale arch, exhale round"},
            {"name": "Downward Dog to Cobra Flow", "duration": 180, "notes": "Hold each position 5 breaths"},
            {"name": "Thoracic Bridge & Backbend Opener", "duration": 180, "notes": "Open thoracic extension"},
            {"name": "Spinal Twist & Decompression", "duration": 180, "notes": "Gentle rotational release"},
            {"name": "Child's Pose & Deep Diaphragmatic Breathing", "duration": 180, "notes": "Calm nervous system"}
        ],
        "upper": [
            {"name": "Overhead Shoulder Mobility & Wall Slides", "duration": 180, "notes": "Keep ribs down, reach high"},
            {"name": "Doorway / Wall Pectoral Opener", "duration": 180, "notes": "Open chest and anterior delts"},
            {"name": "Thread the Needle Thoracic Opener", "duration": 180, "notes": "Rotate spine and open shoulders"},
            {"name": "Puppy Pose Thoracic Extension", "duration": 180, "notes": "Sink chest toward floor"}
        ],
        "full": [
            {"name": "Cat-Cow Dynamic Spine Waves", "duration": 120, "notes": "Inhale arch, exhale round"},
            {"name": "Downward Dog to Cobra Flow", "duration": 180, "notes": "Hold each position 5 breaths"},
            {"name": "Low Lunge Hip Flexor Stretch", "duration": 180, "notes": "90s per side with reach"},
            {"name": "Pigeon Pose / Figure-4 Glute Stretch", "duration": 240, "notes": "2 mins each side"},
            {"name": "World's Greatest Stretch", "duration": 180, "notes": "Step forward, rotate torso, reach high"},
            {"name": "Seated Hamstring & Calf Reach", "duration": 180, "notes": "Hinge at hips, keep spine long"},
            {"name": "Child's Pose & Deep Diaphragmatic Breathing", "duration": 180, "notes": "Calm nervous system"}
        ]
    }

    @classmethod
    def generate(cls, focus: str = "full", duration_minutes: int = 20, difficulty: int = 1) -> Dict[str, Any]:
        total_sec = duration_minutes * 60
        steps: List[WorkoutStep] = []

        focus_aliases = {
            "legs": "lower",
            "all": "full",
            "full_body": "full",
        }
        normalized_focus = focus_aliases.get(focus.lower(), focus.lower())
        routines_list = cls.ROUTINES.get(normalized_focus, cls.ROUTINES["full"])

        remaining_sec = total_sec
        for item in routines_list:
            if remaining_sec <= 0:
                break
            dur = min(item["duration"], remaining_sec)
            steps.append(WorkoutStep(
                type="exercise",
                duration=dur,
                name=item["name"],
                target_type="time",
                notes=item["notes"]
            ))
            remaining_sec -= dur

        if remaining_sec > 0 and steps:
            steps[-1].duration += remaining_sec

        focus_title = normalized_focus.capitalize() if normalized_focus != "full" else "Athletic Full Body"

        return {
            "name": f"{focus_title} Mobility & Recovery Flow",
            "description": f"Guided {normalized_focus} mobility flow targeting range of motion, postural balance, and tissue recovery.",
            "steps": [s.to_dict() for s in steps],
            "targetType": "time",
            "total_duration_sec": total_sec
        }

