"""
One-off migration: move legacy Strava OAuth tokens off `users/{uid}` (client-readable)
into `users/{uid}/private/strava` (server-only), then delete the legacy fields.

Idempotent and safe to re-run. Dry run by default.

    python scripts/migrate_strava_tokens.py                                   # emulator, dry run
    python scripts/migrate_strava_tokens.py --project athlethium-app \\
        --i-understand-this-is-production --apply                             # production
"""

import argparse

from firebase_admin import firestore

from _target import add_target_args, init_firebase

LEGACY = ["stravaAccessToken", "stravaRefreshToken", "stravaExpiresAt"]


def migrate(db, apply: bool) -> int:
    moved = 0
    for snap in db.collection("users").stream():
        data = snap.to_dict() or {}
        if not any(k in data for k in LEGACY):
            continue
        moved += 1
        print(f"{'MIGRATE' if apply else 'would migrate'} users/{snap.id}")
        if not apply:
            continue
        if data.get("stravaAccessToken") and data.get("stravaRefreshToken"):
            snap.reference.collection("private").document("strava").set({
                "accessToken": data["stravaAccessToken"],
                "refreshToken": data["stravaRefreshToken"],
                "expiresAt": data.get("stravaExpiresAt"),
                "athleteId": data.get("stravaAthleteId"),
                "migratedAt": firestore.SERVER_TIMESTAMP,
            }, merge=True)
        snap.reference.update({k: firestore.DELETE_FIELD for k in LEGACY})
    print(f"{moved} user document(s) {'migrated' if apply else 'need migrating'}.")
    return moved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_target_args(parser)
    parser.add_argument("--apply", action="store_true", help="Write changes (default is a dry run)")
    args = parser.parse_args()
    migrate(init_firebase(args), args.apply)
