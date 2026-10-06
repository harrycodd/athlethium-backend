"""
Workout Persistence and Query Service.
Handles saving generated workouts and querying workouts by date in Firestore.
"""

import datetime
from typing import Optional, Dict, Any, List, Tuple
try:
    from firebase_admin import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
except ImportError:
    firestore = None
from core.models import WorkoutDoc

ENDURANCE_SPORTS = ("cycling", "running", "swimming")


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
        """Saves one planned workout (see save_day)."""
        saved = cls.save_day([workout])
        return saved[0] if saved else None

    @classmethod
    def save_day(cls, workouts: List[WorkoutDoc]) -> List[str]:
        """
        Saves a day's planned workouts (one, or two on a double day), removing other *uncompleted*
        workouts on that day that aren't part of this plan. Never overwrites a completed workout.
        Returns the ids saved.
        """
        if not workouts:
            return []
        db = firestore.client()
        user_id, date = workouts[0].user_id, workouts[0].date
        ids = [w.workout_id or f"plan_{w.user_id}_{w.date}" for w in workouts]

        same_day = db.collection("workouts") \
                     .where(filter=FieldFilter("userId", "==", user_id)) \
                     .where(filter=FieldFilter("date", "==", date)) \
                     .get()
        for doc_snap in same_day:
            data = doc_snap.to_dict() or {}
            if doc_snap.id in ids or _is_completed(data) or data.get("type") in ("Goal", "Event"):
                continue
            doc_snap.reference.delete()
            print(f"[WorkoutService] Removed duplicate uncompleted workout {doc_snap.id} on {date}")

        saved = []
        for workout, target_id in zip(workouts, ids, strict=True):
            target_ref = db.collection("workouts").document(target_id)
            existing = target_ref.get()
            if existing.exists and _is_completed(existing.to_dict() or {}):
                print(f"[WorkoutService] Not overwriting completed workout {target_id}")
                continue
            doc_dict = workout.to_dict()
            doc_dict["createdAt"] = firestore.SERVER_TIMESTAMP
            target_ref.set(doc_dict)
            saved.append(target_id)
        print(f"[WorkoutService] Saved {saved} for user {user_id} on {date}")
        return saved

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

    @classmethod
    def recent_load(cls, user_id: str, today: datetime.date,
                    weeks: int = 3) -> Tuple[Dict[str, List[Any]], List[List[Any]]]:
        """
        Completed endurance load for the planner:
        - per Monday-Sunday week for the `weeks` full weeks before today's week:
          {Monday: [hours, tss, {sport: hours}]} (per sport so each sport ramps on its own)
        - this week's completed sessions so far: [[date, tss], ...]
        """
        this_monday = today - datetime.timedelta(days=today.weekday())
        start = this_monday - datetime.timedelta(weeks=weeks)
        snaps = firestore.client().collection("workouts") \
                                  .where(filter=FieldFilter("userId", "==", user_id)) \
                                  .where(filter=FieldFilter("date", ">=", start.isoformat())) \
                                  .get()
        load: Dict[str, List[float]] = {}
        week_to_date: List[List[Any]] = []
        for snap in snaps:
            data = snap.to_dict() or {}
            if not _is_completed(data) or data.get("sport") not in ENDURANCE_SPORTS:
                continue
            try:
                day = datetime.date.fromisoformat(str(data.get("date")))
                hours = float(data.get("actual_time") or data.get("time") or 0) / 3600
                tss = float(data.get("actual_tss") or 0)
            except (TypeError, ValueError):
                continue
            if day >= this_monday:
                if day <= today:
                    week_to_date.append([day.isoformat(), round(tss, 1)])
                continue
            key = (day - datetime.timedelta(days=day.weekday())).isoformat()
            week = load.setdefault(key, [0.0, 0.0, {}])
            week[0] += hours
            week[1] += tss
            week[2][data["sport"]] = week[2].get(data["sport"], 0.0) + hours
        return ({k: [round(h, 3), round(t, 1), {sp: round(x, 3) for sp, x in by.items()}]
                 for k, (h, t, by) in load.items()},
                sorted(week_to_date))
