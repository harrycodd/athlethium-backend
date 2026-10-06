"""
Firebase Cloud Functions Entry Points for Athlethium Backend.

Every app-facing endpoint requires `Authorization: Bearer <Firebase ID token>`; the acting
user is always the token's uid. `strava_callback` is the only unauthenticated endpoint and is
protected by a single-use, server-issued OAuth state nonce.
"""

import datetime
import json
import os
import tempfile
from typing import Any, Dict, Optional, Tuple

from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore, storage
import firebase_admin

from services.auth import AuthError, require_uid
from services.user_service import UserService
from services.profile_validator import ProfileValidator
from services.workout_service import WorkoutService
from services.workout_completer import WorkoutCompleterService, WorkoutNotFound, FitFileError
from services.strava_service import StravaService, complete_authorization
from engine.scheduler import TrainingScheduler


def _local_emulator_credential():
    """
    Demo projects (`demo-*`) only ever run on the local Emulator Suite, where no Google
    credentials exist and the emulators accept anonymous access. Never used in production.
    """
    project = os.environ.get("GCLOUD_PROJECT", "")
    if not (project.startswith("demo-") and os.environ.get("FIRESTORE_EMULATOR_HOST")):
        return None
    from firebase_admin import credentials
    from google.auth.credentials import AnonymousCredentials

    class _Anonymous(credentials.Base):
        def get_credential(self):
            return AnonymousCredentials()

    return _Anonymous()


# Initialise from the runtime's FIREBASE_CONFIG (project + default bucket), never a hard-coded project.
if not len(firebase_admin._apps):
    initialize_app(_local_emulator_credential())


REGION = "europe-west2"
# Bearer tokens (not cookies) carry auth, so any origin may call; CORS adds no ambient authority.
CORS = options.CorsOptions(cors_origins="*", cors_methods=["post", "options"])
MAX_PLAN_DAYS = 28
MAX_FIT_BYTES = 25 * 1024 * 1024
MAX_NOTES_CHARS = 2000
STRAVA_CLIENT_ID_DEFAULT = "157155"  # public OAuth client id
STRAVA_REDIRECT_URI_DEFAULT = f"https://{REGION}-athlethium-app.cloudfunctions.net/strava_callback"


class BadRequest(Exception):
    pass


def _json(body: Dict[str, Any], status: int = 200) -> https_fn.Response:
    return https_fn.Response(json.dumps(body), status=status, mimetype="application/json")


def _require_post(req: https_fn.Request) -> Optional[https_fn.Response]:
    if req.method != "POST":
        return _json({"error": "Method not allowed"}, 405)
    return None


def _json_body(req: https_fn.Request) -> Dict[str, Any]:
    body = req.get_json(silent=True) if req.is_json else None
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object")
    return body


def _check_claimed_user(body: Dict[str, Any], uid: str):
    """Legacy clients send userId; it must match the token (it is never trusted on its own)."""
    claimed = body.get("userId") or body.get("uid")
    if claimed is not None and claimed != uid:
        raise PermissionError("userId does not match the signed-in user")


def _valid_doc_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 200 and "/" not in value


def _run(handler_name: str, fn) -> https_fn.Response:
    """Maps service exceptions to HTTP responses; never leaks internal error text on 500."""
    try:
        return fn()
    except AuthError:
        return _json({"error": "Authentication required"}, 401)
    except PermissionError as exc:
        return _json({"error": str(exc)}, 403)
    except BadRequest as exc:
        return _json({"error": str(exc)}, 400)
    except WorkoutNotFound:
        return _json({"error": "Workout not found"}, 404)
    except Exception as exc:
        print(f"[Functions] Error in {handler_name}: {type(exc).__name__}: {exc}")
        return _json({"error": "Internal server error"}, 500)


@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def update_user_profile(req: https_fn.Request) -> https_fn.Response:
    """Validates and saves/updates the signed-in athlete's profile (including setup wizard)."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        body = _json_body(req)
        _check_claimed_user(body, uid)
        profile_data = body.get("profile") if "profile" in body else body
        is_partial = body.get("isPartial", False)
        if not isinstance(is_partial, bool):
            raise BadRequest("isPartial must be a boolean")

        is_valid, errors, saved_profile = UserService.validate_and_save_profile(
            user_id=uid, profile_data=profile_data, is_partial=is_partial
        )
        if not is_valid:
            return _json({"error": "Validation failed", "details": errors}, 400)
        return _json({
            "message": "User profile updated successfully",
            "userId": uid,
            "wizardCompleted": bool(saved_profile and saved_profile.wizard_completed),
        })

    return _run("update_user_profile", handle)


def _parse_generate_request(body: Dict[str, Any]) -> Tuple[Optional[datetime.date], int]:
    raw_days = body.get("days", 1)
    if isinstance(raw_days, bool) or not isinstance(raw_days, (int, str)):
        raise BadRequest(f"days must be an integer between 1 and {MAX_PLAN_DAYS}")
    try:
        num_days = int(raw_days)
    except ValueError:
        raise BadRequest(f"days must be an integer between 1 and {MAX_PLAN_DAYS}")
    if not 1 <= num_days <= MAX_PLAN_DAYS:
        raise BadRequest(f"days must be an integer between 1 and {MAX_PLAN_DAYS}")

    date_str = body.get("date")
    if date_str in (None, ""):
        return None, num_days
    if not isinstance(date_str, str):
        raise BadRequest("Invalid date format. Use YYYY-MM-DD")
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date(), num_days
    except ValueError:
        raise BadRequest("Invalid date format. Use YYYY-MM-DD")


@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def generate_training_session(req: https_fn.Request) -> https_fn.Response:
    """Generates 1..28 days of training for the signed-in athlete, skipping days already planned."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        body = _json_body(req)
        _check_claimed_user(body, uid)
        start_date, num_days = _parse_generate_request(body)

        user_profile = UserService.get_user_profile(uid)
        if not user_profile:
            return _json({"error": "User profile not found"}, 404)

        is_valid, validation_errors, _ = ProfileValidator.validate(user_profile.raw_data or {})
        if not is_valid and not user_profile.wizard_completed:
            return _json({
                "error": "Cannot generate plan: Athlete profile is incomplete or invalid",
                "details": validation_errors
            }, 400)

        today = UserService.today_for(user_profile)  # the athlete's local calendar day
        if start_date is None:
            start_date = today

        generated_dates, skipped_dates = [], []
        for i in range(num_days):
            current_date = start_date + datetime.timedelta(days=i)
            current_date_str = current_date.strftime("%Y-%m-%d")
            if WorkoutService.has_workout_for_date(uid, current_date_str):
                skipped_dates.append(current_date_str)
                continue
            workout_doc = TrainingScheduler.schedule_day(user_profile=user_profile, target_date=current_date,
                                                         user_id=uid, as_of=today)
            if WorkoutService.save_workout(workout_doc):
                generated_dates.append(current_date_str)
            else:
                skipped_dates.append(current_date_str)

        return _json({
            "message": "Training generation complete",
            "userId": uid,
            "generated_dates": generated_dates,
            "skipped_dates": skipped_dates
        })

    return _run("generate_training_session", handle)


@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def complete_manual_workout(req: https_fn.Request) -> https_fn.Response:
    """Completes one of the signed-in athlete's workouts with actual time, RPE and notes."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        body = _json_body(req)
        workout_id = body.get("workoutId")
        actual_time_sec = body.get("actual_time_sec")
        rpe = body.get("rpe")
        notes = body.get("notes", "") or ""

        if not _valid_doc_id(workout_id):
            raise BadRequest("workoutId is required")
        if isinstance(actual_time_sec, bool) or not isinstance(actual_time_sec, (int, float)) \
                or not 0 < actual_time_sec <= 86400:
            raise BadRequest("actual_time_sec must be a number of seconds between 1 and 86400")
        if rpe is not None and (isinstance(rpe, bool) or not isinstance(rpe, int) or not 1 <= rpe <= 10):
            raise BadRequest("rpe must be an integer from 1 to 10")
        if not isinstance(notes, str) or len(notes) > MAX_NOTES_CHARS:
            raise BadRequest(f"notes must be text up to {MAX_NOTES_CHARS} characters")

        result = WorkoutCompleterService.complete_manual(
            user_id=uid, workout_id=workout_id, actual_time_sec=int(actual_time_sec), rpe=rpe, notes=notes
        )
        return _json({"message": "Workout completed successfully", "data": result})

    return _run("complete_manual_workout", handle)


@https_fn.on_request(region=REGION, invoker="public", cors=CORS, memory=options.MemoryOption.MB_512)
def upload_workout_fit(req: https_fn.Request) -> https_fn.Response:
    """Uploads and parses a .fit file to complete the signed-in athlete's workout."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        if req.content_length is not None and req.content_length > MAX_FIT_BYTES:
            return _json({"error": "File too large (max 25 MB)"}, 413)

        claimed = req.form.get("userId")
        if claimed and claimed != uid:
            raise PermissionError("userId does not match the signed-in user")
        workout_id = req.form.get("workoutId") or None
        if workout_id is not None and not _valid_doc_id(workout_id):
            raise BadRequest("Invalid workoutId")

        upload = req.files.get("file")
        if upload is None:
            raise BadRequest("No file uploaded. Use key 'file' in multipart/form-data")
        if not upload.filename:
            raise BadRequest("Empty filename")

        # Never build paths from the client's filename (path traversal / collisions).
        fd, temp_path = tempfile.mkstemp(suffix=".fit")
        os.close(fd)
        try:
            upload.save(temp_path)
            if os.path.getsize(temp_path) > MAX_FIT_BYTES:
                return _json({"error": "File too large (max 25 MB)"}, 413)
            try:
                result = WorkoutCompleterService.complete_with_fit(
                    user_id=uid, fit_file_path=temp_path, workout_id=workout_id
                )
            except FitFileError as exc:
                return _json({"error": str(exc)}, 400)

            final_workout_id = result.get("workout_id")
            if final_workout_id:
                try:
                    # Private object: GPS traces are personal data. Clients get no Storage access.
                    blob_path = f"users/{uid}/workouts/{final_workout_id}.fit"
                    storage.bucket().blob(blob_path).upload_from_filename(temp_path)
                    firestore.client().collection("workouts").document(final_workout_id).update({
                        "fit_file_path": blob_path,
                        "fit_file_url": firestore.DELETE_FIELD,
                    })
                    result["fit_file_path"] = blob_path
                except Exception as st_err:
                    print(f"[Functions] Storage upload warning: {st_err}")

            return _json({"message": "FIT file processed successfully", "data": result})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return _run("upload_workout_fit", handle)


def _strava_client_id() -> str:
    return os.environ.get("STRAVA_CLIENT_ID") or STRAVA_CLIENT_ID_DEFAULT


@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def strava_auth_start(req: https_fn.Request) -> https_fn.Response:
    """Issues a single-use OAuth state for the signed-in athlete and returns the Strava auth URL."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        body = _json_body(req)
        try:
            result = StravaService.start_authorization(
                user_id=uid,
                return_url=body.get("returnUrl"),
                client_id=_strava_client_id(),
                redirect_uri=os.environ.get("STRAVA_REDIRECT_URI") or STRAVA_REDIRECT_URI_DEFAULT,
            )
        except ValueError as exc:
            raise BadRequest(str(exc))
        return _json(result)

    return _run("strava_auth_start", handle)


@https_fn.on_request(region=REGION, invoker="public", secrets=["STRAVA_CLIENT_SECRET"])
def strava_callback(req: https_fn.Request) -> https_fn.Response:
    """OAuth redirect target for Strava. Trusts only server-issued state."""

    def handle():
        client_secret = os.environ.get("STRAVA_CLIENT_SECRET")
        if not client_secret:
            print("[Functions] STRAVA_CLIENT_SECRET is not configured")
            return https_fn.Response("Strava integration is not configured", status=500)
        status, headers = complete_authorization(
            state=req.args.get("state"),
            code=req.args.get("code"),
            error=req.args.get("error"),
            client_id=_strava_client_id(),
            client_secret=client_secret,
        )
        if status == 400:
            return https_fn.Response("Invalid or expired authorization request. Please try connecting again.",
                                     status=400)
        return https_fn.Response(status=status, headers=headers)

    return _run("strava_callback", handle)


@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def strava_disconnect(req: https_fn.Request) -> https_fn.Response:
    """Revokes and deletes the signed-in athlete's Strava tokens."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)
        return _json({"message": "Strava disconnected", "data": StravaService.disconnect(uid)})

    return _run("strava_disconnect", handle)
