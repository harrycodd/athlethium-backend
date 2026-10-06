"""
Workout Completion Service.
Handles manual workout completion, FIT file parsing, actual TSS calculation,
and automatic FTP detection.
"""

import os
import json
import datetime
import uuid
from typing import Dict, Any, Optional
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None
from engine.physiology import PhysiologyEngine
from services.user_service import UserService


try:
    import fitparse
except ImportError:
    fitparse = None


class WorkoutCompleterService:
    """
    Processes workout completions (manual or via FIT files) and updates athlete fitness.
    """

    @classmethod
    def complete_manual(
        cls,
        workout_id: str,
        actual_time_sec: int,
        rpe: Optional[int] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Completes a workout manually and recalculates user CTL/ATL.
        """
        db = firestore.client()
        workout_ref = db.collection("workouts").document(workout_id)
        workout_snap = workout_ref.get()

        if not workout_snap.exists:
            return {"error": f"Workout {workout_id} not found."}

        workout_data = workout_snap.to_dict() or {}
        user_id = workout_data.get("userId")
        sport = workout_data.get("sport", "cycling")
        intensity = workout_data.get("intensity", 2)

        # Calculate actual TSS - take planned TSS for manual completion (0 for strength/stretching)
        is_strength_or_mobility = sport.lower() in ["strength", "stretching", "yoga", "rest"]
        if is_strength_or_mobility:
            actual_tss = 0.0
        else:
            actual_tss = float(workout_data.get("plannedTss") or workout_data.get("planned_tss") or workout_data.get("tss") or 0.0)

        # Update workout document
        update_data = {
            "completed": True,
            "status": "completed",
            "completedAt": firestore.SERVER_TIMESTAMP,
            "actual_time": actual_time_sec,
            "actual_tss": actual_tss,
            "rpe": rpe,
            "userNotes": notes,
            "completion_type": "manual"
        }
        workout_ref.update(update_data)

        # Update athlete CTL / ATL
        if user_id:
            user_profile = UserService.get_user_profile(user_id)
            if user_profile:
                new_ctl, new_atl, new_tsb = PhysiologyEngine.calculate_next_day_metrics(
                    current_ctl=user_profile.ctl,
                    current_atl=user_profile.atl,
                    daily_tss=actual_tss
                )
                UserService.update_user_fitness(user_id, new_ctl, new_atl)

        return {
            "workoutId": workout_id,
            "actual_time": actual_time_sec,
            "actual_tss": actual_tss,
            "status": "completed"
        }

    @classmethod
    def complete_with_fit(
        cls,
        user_id: str,
        fit_file_path: str,
        workout_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses a .fit file, extracts power/HR/duration metrics, checks for FTP increases,
        and marks workout as completed.
        """
        if not fitparse:
            return {"error": "fitparse module is not available"}

        try:
            fitfile = fitparse.FitFile(fit_file_path)
            
            # Extract records and session data
            total_time_sec = 0
            power_readings = []
            hr_readings = []
            start_time = None

            for record in fitfile.get_messages("record"):
                values = record.get_values()
                if "timestamp" in values and not start_time:
                    start_time = values["timestamp"]
                if "power" in values and values["power"] is not None:
                    power_readings.append(float(values["power"]))
                if "heart_rate" in values and values["heart_rate"] is not None:
                    hr_readings.append(float(values["heart_rate"]))

            # Extract session level totals
            for session in fitfile.get_messages("session"):
                s_vals = session.get_values()
                if "total_elapsed_time" in s_vals and s_vals["total_elapsed_time"]:
                    total_time_sec = int(s_vals["total_elapsed_time"])
                elif "total_timer_time" in s_vals and s_vals["total_timer_time"]:
                    total_time_sec = int(s_vals["total_timer_time"])

            if total_time_sec <= 0:
                total_time_sec = len(power_readings) or len(hr_readings) or 1800

            avg_power = sum(power_readings) / len(power_readings) if power_readings else 0
            avg_hr = sum(hr_readings) / len(hr_readings) if hr_readings else 0

            # Normalized Power approximation (4th power rolling 30s)
            np_power = avg_power * 1.05 if avg_power > 0 else 0

            user_profile = UserService.get_user_profile(user_id)
            user_ftp = (user_profile.ftp_cycling or user_profile.ftp or 200.0) if user_profile else 200.0
            user_fthr = (user_profile.fthr or 170.0) if user_profile else 170.0

            actual_tss = PhysiologyEngine.calculate_actual_tss(
                sport="cycling",
                duration_sec=total_time_sec,
                avg_power=avg_power,
                normalized_power=np_power,
                ftp=user_ftp,
                avg_hr=avg_hr,
                fthr=user_fthr
            )

            # Auto-FTP Check (Best 20min power * 0.95)
            suggested_new_ftp = None
            if len(power_readings) >= 1200:
                # Calculate best 20 min rolling power
                rolling_sum = sum(power_readings[:1200])
                max_20m = rolling_sum
                for i in range(1200, len(power_readings)):
                    rolling_sum += power_readings[i] - power_readings[i - 1200]
                    if rolling_sum > max_20m:
                        max_20m = rolling_sum
                best_20m_avg = max_20m / 1200.0
                potential_ftp = round(best_20m_avg * 0.95, 1)
                if potential_ftp > user_ftp + 2.0:
                    suggested_new_ftp = potential_ftp
                    print(f"[WorkoutCompleter] New FTP detected: {potential_ftp}W (old: {user_ftp}W)")

            # Resolve workout ID
            db = firestore.client()
            date_str = start_time.strftime("%Y-%m-%d") if start_time else datetime.date.today().strftime("%Y-%m-%d")
            
            final_workout_id = workout_id
            if not final_workout_id:
                # Find planned workout for this date
                snaps = db.collection("workouts") \
                          .where("userId", "==", user_id) \
                          .where("date", "==", date_str) \
                          .limit(1).get()
                if snaps:
                    final_workout_id = snaps[0].id

            stats_dict = {
                "avg_power": round(avg_power, 1),
                "normalized_power": round(np_power, 1),
                "avg_heart_rate": round(avg_hr, 1),
                "duration_seconds": total_time_sec
            }

            if final_workout_id:
                db.collection("workouts").document(final_workout_id).update({
                    "completed": True,
                    "status": "completed",
                    "completedAt": firestore.SERVER_TIMESTAMP,
                    "actual_time": total_time_sec,
                    "actual_tss": actual_tss,
                    "stats": stats_dict,
                    "completion_type": "fit_upload"
                })
            else:
                # Create a new completed workout record
                final_workout_id = str(uuid.uuid4())
                db.collection("workouts").document(final_workout_id).set({
                    "workoutId": final_workout_id,
                    "userId": user_id,
                    "date": date_str,
                    "name": "Recorded Activity",
                    "sport": "cycling",
                    "intensity": 2,
                    "time": total_time_sec,
                    "actual_time": total_time_sec,
                    "tss": actual_tss,
                    "actual_tss": actual_tss,
                    "completed": True,
                    "status": "completed",
                    "stats": stats_dict,
                    "createdAt": firestore.SERVER_TIMESTAMP,
                    "completion_type": "fit_upload"
                })

            # Update athlete fitness metrics
            if user_profile:
                new_ctl, new_atl, new_tsb = PhysiologyEngine.calculate_next_day_metrics(
                    current_ctl=user_profile.ctl,
                    current_atl=user_profile.atl,
                    daily_tss=actual_tss
                )
                UserService.update_user_fitness(user_id, new_ctl, new_atl, new_ftp=suggested_new_ftp)

            return {
                "workout_id": final_workout_id,
                "actual_time": total_time_sec,
                "actual_tss": actual_tss,
                "stats": stats_dict,
                "new_ftp": suggested_new_ftp
            }

        except Exception as e:
            print(f"[WorkoutCompleter] Error processing FIT file: {str(e)}")
            return {"error": str(e)}
