"""
Firebase Cloud Functions Entry Points for Athlethium Backend.
Clean, modular HTTP handlers delegating to core services.
"""

import os
import json
import datetime
import tempfile
from firebase_functions import https_fn
from firebase_admin import initialize_app, firestore, storage
import firebase_admin

# Initialize Firebase Admin SDK
if not len(firebase_admin._apps):
    initialize_app(options={
        'storageBucket': 'athlethium-app.firebasestorage.app'
    })

from services.user_service import UserService
from services.profile_validator import ProfileValidator
from services.workout_service import WorkoutService
from services.workout_completer import WorkoutCompleterService
from services.strava_service import StravaService
from engine.scheduler import TrainingScheduler


@https_fn.on_request(region="europe-west2", invoker="public")
def update_user_profile(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Endpoint to validate and save/update an athlete's profile (including setup wizard).
    Enforces strict server-side data validation.
    """
    try:
        body = req.get_json() if req.is_json else {}
        user_id = body.get("userId") or body.get("uid")
        profile_data = body.get("profile") if "profile" in body else body

        if not user_id:
            return https_fn.Response(
                json.dumps({"error": "userId is required"}),
                status=400,
                mimetype="application/json"
            )

        # Validate and save
        is_valid, errors, saved_profile = UserService.validate_and_save_profile(
            user_id=user_id,
            profile_data=profile_data,
            is_partial=bool(body.get("isPartial", False))
        )

        if not is_valid:
            return https_fn.Response(
                json.dumps({
                    "error": "Validation failed",
                    "details": errors
                }),
                status=400,
                mimetype="application/json"
            )

        return https_fn.Response(
            json.dumps({
                "message": "User profile updated successfully",
                "userId": user_id,
                "wizardCompleted": saved_profile.wizard_completed if saved_profile else True
            }),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        print(f"[Functions] Error in update_user_profile: {str(e)}")
        return https_fn.Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json"
        )


@https_fn.on_request(region="europe-west2", invoker="public")
def generate_training_session(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Endpoint to generate 1 or more days of training sessions.
    Invoked by mobile app frontend.
    """
    try:
        body = req.get_json() if req.is_json else {}
        user_id = body.get("userId")
        date_str = body.get("date")
        num_days = int(body.get("days", 1))

        if not user_id:
            return https_fn.Response(
                json.dumps({"error": "userId is required"}),
                status=400,
                mimetype="application/json"
            )

        # Parse start date
        if date_str:
            try:
                start_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return https_fn.Response(
                    json.dumps({"error": "Invalid date format. Use YYYY-MM-DD"}),
                    status=400,
                    mimetype="application/json"
                )
        else:
            start_date = datetime.date.today()

        user_profile = UserService.get_user_profile(user_id)
        if not user_profile:
            return https_fn.Response(
                json.dumps({"error": f"User profile not found for ID: {user_id}"}),
                status=404,
                mimetype="application/json"
            )

        # Validate that athlete profile is complete and valid
        is_valid, validation_errors, _ = ProfileValidator.validate(user_profile.raw_data or {})
        if not is_valid and not user_profile.wizard_completed:
            return https_fn.Response(
                json.dumps({
                    "error": "Cannot generate plan: Athlete profile is incomplete or invalid",
                    "details": validation_errors
                }),
                status=400,
                mimetype="application/json"
            )

        generated_dates = []
        skipped_dates = []

        for i in range(num_days):
            current_date = start_date + datetime.timedelta(days=i)
            current_date_str = current_date.strftime("%Y-%m-%d")

            # 1. Skip if already scheduled
            if WorkoutService.has_workout_for_date(user_id, current_date_str):
                skipped_dates.append(current_date_str)
                continue

            # 2. Schedule workout via pure deterministic engine
            workout_doc = TrainingScheduler.schedule_day(
                user_profile=user_profile,
                target_date=current_date,
                user_id=user_id
            )

            # 3. Save to Firestore
            WorkoutService.save_workout(workout_doc)
            generated_dates.append(current_date_str)

        return https_fn.Response(
            json.dumps({
                "message": "Training generation complete",
                "userId": user_id,
                "generated_dates": generated_dates,
                "skipped_dates": skipped_dates
            }),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        print(f"[Functions] Error in generate_training_session: {str(e)}")
        return https_fn.Response(
            json.dumps({"error": str(e)}),
            status=500,
            mimetype="application/json"
        )



@https_fn.on_request(region="europe-west2", invoker="public")
def complete_manual_workout(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Endpoint to manually complete a workout with actual time, RPE, and notes.
    """
    try:
        body = req.get_json() if req.is_json else {}
        workout_id = body.get("workoutId")
        actual_time_sec = body.get("actual_time_sec")
        rpe = body.get("rpe")
        notes = body.get("notes", "")

        if not workout_id or not actual_time_sec:
            return https_fn.Response(
                json.dumps({"error": "workoutId and actual_time_sec are required"}),
                status=400,
                mimetype="application/json"
            )

        result = WorkoutCompleterService.complete_manual(
            workout_id=workout_id,
            actual_time_sec=actual_time_sec,
            rpe=rpe,
            notes=notes
        )

        if "error" in result:
            return https_fn.Response(json.dumps(result), status=500, mimetype="application/json")

        return https_fn.Response(
            json.dumps({"message": "Workout completed successfully", "data": result}),
            status=200,
            mimetype="application/json"
        )

    except Exception as e:
        print(f"[Functions] Error in complete_manual_workout: {str(e)}")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


@https_fn.on_request(region="europe-west2", invoker="public")
def upload_workout_fit(req: https_fn.Request) -> https_fn.Response:
    """
    HTTP Endpoint to upload and parse a .fit file to complete a workout.
    """
    try:
        user_id = req.form.get("userId")
        workout_id = req.form.get("workoutId")

        if not user_id:
            return https_fn.Response(
                json.dumps({"error": "userId is required in form-data"}),
                status=400,
                mimetype="application/json"
            )

        if "file" not in req.files:
            return https_fn.Response(
                json.dumps({"error": "No file uploaded. Use key 'file' in multipart/form-data"}),
                status=400,
                mimetype="application/json"
            )

        file = req.files["file"]
        if file.filename == "":
            return https_fn.Response(json.dumps({"error": "Empty filename"}), status=400, mimetype="application/json")

        temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, file.filename)
        file.save(temp_path)

        try:
            result = WorkoutCompleterService.complete_with_fit(
                user_id=user_id,
                fit_file_path=temp_path,
                workout_id=workout_id
            )

            if "error" in result:
                return https_fn.Response(json.dumps(result), status=500, mimetype="application/json")

            # Upload raw .fit to Firebase Cloud Storage
            final_workout_id = result.get("workout_id")
            if final_workout_id:
                try:
                    bucket = storage.bucket()
                    blob_path = f"users/{user_id}/workouts/{final_workout_id}.fit"
                    blob = bucket.blob(blob_path)
                    blob.upload_from_filename(temp_path)
                    blob.make_public()
                    fit_url = blob.public_url

                    firestore.client().collection("workouts").document(final_workout_id).update({
                        "fit_file_url": fit_url
                    })
                    result["fit_file_url"] = fit_url
                except Exception as st_err:
                    print(f"[Functions] Storage upload warning: {str(st_err)}")

            return https_fn.Response(
                json.dumps({"message": "FIT file processed successfully", "data": result}),
                status=200,
                mimetype="application/json"
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        print(f"[Functions] Error in upload_workout_fit: {str(e)}")
        return https_fn.Response(json.dumps({"error": str(e)}), status=500, mimetype="application/json")


@https_fn.on_request(region="europe-west2", invoker="public")
def strava_callback(req: https_fn.Request) -> https_fn.Response:
    """
    OAuth Redirect handler for Strava integration.
    """
    try:
        code = req.args.get("code")
        state_str = req.args.get("state")
        error = req.args.get("error")

        if not state_str:
            return https_fn.Response("Missing state parameter", status=400)

        import urllib.parse
        try:
            state = json.loads(urllib.parse.unquote(state_str))
        except:
            state = json.loads(state_str)

        return_url = state.get("return_url", "athlethium://")
        user_id = state.get("uid")

        if error:
            return https_fn.Response(status=302, headers={"Location": f"{return_url}?error={error}"})

        client_id = os.environ.get("STRAVA_CLIENT_ID", "157155")
        client_secret = os.environ.get("STRAVA_CLIENT_SECRET", "REDACTED_STRAVA_SECRET")

        result = StravaService.exchange_oauth_code(code, user_id, client_id, client_secret)
        if "error" in result:
            return https_fn.Response(status=302, headers={"Location": f"{return_url}?error=token_exchange_failed"})

        return https_fn.Response(status=302, headers={"Location": f"{return_url}?success=true"})

    except Exception as e:
        print(f"[Functions] Error in strava_callback: {str(e)}")
        return https_fn.Response(f"Internal Error: {str(e)}", status=500)
