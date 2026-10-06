import json
import os
from firebase_admin import firestore, initialize_app

# Initialize Firebase
if not len(initialize_app._apps):
    initialize_app()

db = firestore.client()

def seed_workout_library():
    """Reads workout.json and uploads it to Firestore collection 'workout_library'"""
    file_path = os.path.join(os.path.dirname(__file__), 'workout.json')
    
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    with open(file_path, 'r') as f:
        library = json.load(f)

    batch = db.batch()
    count = 0
    
    for sport, intensities in library.items():
        if not sport: # Handle empty sport key if it exists
            sport = "generic"
            
        for intensity, workouts in intensities.items():
            doc_id = f"{sport}_{intensity}"
            doc_ref = db.collection("workout_library").document(doc_id)
            
            # Use batch for efficiency
            batch.set(doc_ref, {"workouts": workouts})
            count += 1
            
            # Firestore batch limit is 500
            if count % 400 == 0:
                batch.commit()
                batch = db.batch()
                print(f"Committed {count} documents...")

    batch.commit()
    print(f"Successfully seeded {count} workout categories to Firestore.")

if __name__ == "__main__":
    seed_workout_library()
