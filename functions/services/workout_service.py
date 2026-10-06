"""
Workout Persistence and Query Service.
Handles saving generated workouts and querying workouts by date in Firestore.
"""

from typing import Optional, Dict, Any, List
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None
from core.models import WorkoutDoc




class WorkoutService:
    """
    Manages Firestore 'workouts' collection operations.
    """

    @classmethod
    def save_workout(cls, workout: WorkoutDoc) -> str:
        """
        Saves a WorkoutDoc to Firestore with automatic deduplication.
        """
        try:
            db = firestore.client()
            doc_dict = workout.to_dict()
            doc_dict["createdAt"] = firestore.SERVER_TIMESTAMP
            
            target_id = workout.workout_id or f"plan_{workout.user_id}_{workout.date}"

            # Query any existing uncompleted workouts for this user and date to remove duplicates
            existing_snaps = db.collection("workouts") \
                               .where("userId", "==", workout.user_id) \
                               .where("date", "==", workout.date) \
                               .get()

            for doc_snap in existing_snaps:
                data = doc_snap.to_dict() or {}
                # If not completed and not the exact document we are setting, remove duplicate
                if doc_snap.id != target_id and not data.get("completed", False) and data.get("status") != "completed":
                    if data.get("type") != "Goal" and data.get("type") != "Event":
                        try:
                            doc_snap.reference.delete()
                            print(f"[WorkoutService] Removed duplicate uncompleted workout {doc_snap.id} on {workout.date}")
                        except Exception as del_err:
                            print(f"[WorkoutService] Error removing duplicate doc {doc_snap.id}: {del_err}")

            db.collection("workouts").document(target_id).set(doc_dict)
            print(f"[WorkoutService] Saved workout {target_id} for user {workout.user_id} on {workout.date}")
            return target_id
        except Exception as e:
            print(f"[WorkoutService] Error saving workout: {str(e)}")
            raise e

    @classmethod
    def has_workout_for_date(cls, user_id: str, date_str: str) -> bool:
        """
        Checks if a workout is already scheduled for the user on date_str (YYYY-MM-DD).
        """
        try:
            db = firestore.client()
            snap = db.collection("workouts") \
                     .where("userId", "==", user_id) \
                     .where("date", "==", date_str) \
                     .limit(1).get()
            return len(snap) > 0
        except Exception as e:
            print(f"[WorkoutService] Error checking existing workout: {str(e)}")
            return False

    @classmethod
    def get_workout_by_id(cls, workout_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a workout document by its ID.
        """
        try:
            db = firestore.client()
            doc_snap = db.collection("workouts").document(workout_id).get()
            return doc_snap.to_dict() if doc_snap.exists else None
        except Exception as e:
            print(f"[WorkoutService] Error fetching workout {workout_id}: {str(e)}")
            return None
