"""Factories for `workouts/{id}` documents."""

from typing import Any, Dict


def make_workout_doc(user_id: str = "athlete-1", date: str = "2026-10-06", **overrides) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "workoutId": f"plan_{user_id}_{date}",
        "userId": user_id,
        "date": date,
        "name": "Cycling Threshold Intervals",
        "sport": "cycling",
        "intensity": 4,
        "time": 5400,
        "plannedTime": 5400,
        "tss": 120.0,
        "plannedTss": 120.0,
        "targetType": "power",
        "description": "",
        "steps": [],
        "completed": False,
        "status": "planned",
    }
    doc.update(overrides)
    return doc
