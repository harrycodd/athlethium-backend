"""
Workout Persistence and Query Service.
Handles saving generated workouts and querying workouts by date in Firestore.
"""

from typing import Optional, Dict, Any
try:
    from firebase_admin import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    firestore = None
from core.models import WorkoutDoc


def _is_completed(data: Dict[str, Any]) -> bool:
    return bool(data.get("completed")) or data.get("status") == "completed"


class WorkoutService:
    """
    Manages Firestore 'workouts' collection operations.
    Database errors propagate to the caller so they surface as 500s instead of
    silently looking like "no workout" (which previously allowed overwrites).
    """

    @classmethod
    def save_workout(cls, workout: WorkoutDoc) -> Optional[str]:
        """
        Saves a planned WorkoutDoc, removing other *uncompleted* workouts on the same day.
        Never overwrites a completed workout; returns None if the slot is already completed.
        """
        db = firestore.client()
        doc_dict = workout.to_dict()
        doc_dict["createdAt"] = firestore.SERVER_TIMESTAMP

        target_id = workout.workout_id or f"plan_{workout.user_id}_{workout.date}"
        target_ref = db.collection("workouts").document(target_id)

        existing = target_ref.get()
        if existing.exists and _is_completed(existing.to_dict() or {}):
            print(f"[WorkoutService] Not overwriting completed workout {target_id}")
            return None

        same_day = db.collection("workouts") \
                     .where(filter=FieldFilter("userId", "==", workout.user_id)) \
                     .where(filter=FieldFilter("date", "==", workout.date)) \
                     .get()
        for doc_snap in same_day:
            data = doc_snap.to_dict() or {}
            if doc_snap.id == target_id or _is_completed(data):
                continue
            if data.get("type") in ("Goal", "Event"):
                continue
            doc_snap.reference.delete()
            print(f"[WorkoutService] Removed duplicate uncompleted workout {doc_snap.id} on {workout.date}")

        target_ref.set(doc_dict)
        print(f"[WorkoutService] Saved workout {target_id} for user {workout.user_id} on {workout.date}")
        return target_id

    @classmethod
    def has_workout_for_date(cls, user_id: str, date_str: str) -> bool:
        """Checks if a workout is already scheduled for the user on date_str (YYYY-MM-DD)."""
        snap = firestore.client().collection("workouts") \
                                 .where(filter=FieldFilter("userId", "==", user_id)) \
                                 .where(filter=FieldFilter("date", "==", date_str)) \
                                 .limit(1).get()
        return len(snap) > 0

    @classmethod
    def get_workout_by_id(cls, workout_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a workout document by its ID."""
        doc_snap = firestore.client().collection("workouts").document(workout_id).get()
        return doc_snap.to_dict() if doc_snap.exists else None
