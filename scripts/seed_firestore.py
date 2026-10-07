"""
Seeds the `workout_library` collection from examples/workout.json.

    python scripts/seed_firestore.py                      # local emulator (default)
    python scripts/seed_firestore.py --project athlethium-app --i-understand-this-is-production
"""

import argparse
import json
import os

from _target import add_target_args, init_firebase

LIBRARY_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples", "workout.json")


def seed_workout_library(db):
    """Reads workout.json and uploads it to Firestore collection 'workout_library'"""
    if not os.path.exists(LIBRARY_FILE):
        print(f"Error: {LIBRARY_FILE} not found.")
        return

    with open(LIBRARY_FILE, "r") as f:
        library = json.load(f)

    batch = db.batch()
    count = 0
    for sport, intensities in library.items():
        if not sport:  # Handle empty sport key if it exists
            sport = "generic"
        for intensity, workouts in intensities.items():
            doc_ref = db.collection("workout_library").document(f"{sport}_{intensity}")
            batch.set(doc_ref, {"workouts": workouts})
            count += 1
            if count % 400 == 0:  # Firestore batch limit is 500
                batch.commit()
                batch = db.batch()
                print(f"Committed {count} documents...")

    batch.commit()
    print(f"Successfully seeded {count} workout categories to Firestore.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    add_target_args(parser)
    seed_workout_library(init_firebase(parser.parse_args()))
