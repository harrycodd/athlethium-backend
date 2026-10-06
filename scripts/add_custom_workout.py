#!/usr/bin/env python3
import sys
import os
import uuid
import datetime
import argparse
from firebase_admin import firestore, initialize_app
import firebase_admin

# Ensure the backend directory is in the path for importing generators
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from stretch_generator import StretchGenerator
    from strength_generator import StrengthGenerator
    from workout_generator import WorkoutGenerator
except ImportError as e:
    print(f"Error importing generators: {e}")
    sys.exit(1)

# Colored console helpers (ANSI escape codes)
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Initialize Firebase Admin SDK
if not len(firebase_admin._apps):
    try:
        initialize_app()
    except Exception as e:
        print(f"{RED}Firebase initialization failed: {e}{RESET}")
        print("Please check your credentials or run 'firebase login'.")
        sys.exit(1)

try:
    db = firestore.client()
except Exception as e:
    print(f"{RED}Error initializing Firestore client: {e}{RESET}")
    print(f"\n{YELLOW}This usually means your Firebase credentials have expired or are missing.{RESET}")
    print(f"{BOLD}Please run:{RESET}  {GREEN}npx firebase login --reauth{RESET}")
    print("Or set the GOOGLE_APPLICATION_CREDENTIALS environment variable to a valid service account JSON.")
    sys.exit(1)

def get_existing_users():
    """Queries and returns list of user details from users collection"""
    print(f"{BLUE}Fetching users from Firestore...{RESET}")
    try:
        users_stream = db.collection("users").stream()
        users = []
        for u in users_stream:
            data = u.to_dict()
            users.append({
                "uid": u.id,
                "displayName": data.get("displayName") or data.get("firstName") or "Unknown",
                "email": data.get("email") or "No email"
            })
        return users
    except Exception as e:
        print(f"{YELLOW}Warning: Could not fetch users from database ({e}).{RESET}")
        print("Ensure you have set GOOGLE_APPLICATION_CREDENTIALS or are logged into Firebase.")
        return []

def prompt_user_id(users):
    """Interactively lets the developer pick/enter a user ID"""
    if users:
        print(f"\n{BOLD}Select Target User:{RESET}")
        for idx, u in enumerate(users, 1):
            print(f"  [{idx}] {u['displayName']} ({u['email']}) - ID: {u['uid']}")
        print(f"  [c] Enter Custom User ID Manually")
        
        choice = input(f"\nChoose an option (1-{len(users)} or c): ").strip()
        if choice.lower() == 'c':
            return input("Enter custom User ID: ").strip()
        try:
            val = int(choice)
            if 1 <= val <= len(users):
                return users[val - 1]["uid"]
        except ValueError:
            pass
        print(f"{YELLOW}Invalid choice. Defaulting to custom manual entry.{RESET}")
    
    return input("Enter User ID: ").strip()

def prompt_sport():
    """Interactively lets the developer select a sport type"""
    print(f"\n{BOLD}Select Sport:{RESET}")
    sports = [
        ("Stretching", "stretching"),
        ("Strength (Gym/Bodyweight)", "strength"),
        ("Running", "running"),
        ("Cycling", "cycling"),
        ("Swimming", "swimming")
    ]
    for idx, (label, _) in enumerate(sports, 1):
        print(f"  [{idx}] {label}")
        
    while True:
        choice = input(f"Choose a sport (1-{len(sports)}) [1]: ").strip()
        if not choice:
            return "stretching"
        try:
            val = int(choice)
            if 1 <= val <= len(sports):
                return sports[val - 1][1]
        except ValueError:
            pass
        print(f"{RED}Invalid input. Please choose a number between 1 and {len(sports)}.{RESET}")

def prompt_focus(sport):
    """If stretching or strength, prompt for focus area"""
    if sport not in ["stretching", "strength"]:
        return "full"
        
    print(f"\n{BOLD}Select Focus Area:{RESET}")
    focus_options = ["full", "upper", "lower"]
    for idx, f in enumerate(focus_options, 1):
        print(f"  [{idx}] {f.capitalize()} Body")
        
    while True:
        choice = input(f"Choose focus (1-3) [1]: ").strip()
        if not choice:
            return "full"
        try:
            val = int(choice)
            if 1 <= val <= 3:
                return focus_options[val - 1]
        except ValueError:
            pass
        print(f"{RED}Invalid input. Please choose 1, 2, or 3.{RESET}")

def get_default_duration(sport):
    if sport == "stretching": return 15
    if sport == "strength": return 45
    return 60

def prompt_duration(sport):
    default = get_default_duration(sport)
    while True:
        choice = input(f"\nEnter duration in minutes [{default}]: ").strip()
        if not choice:
            return default
        try:
            val = int(choice)
            if val > 0:
                # Cap stretching to 20 mins max to avoid StretchGenerator crashing/wrapping
                if sport == "stretching" and val > 20:
                    print(f"{YELLOW}Note: Stretching routines cap at 20 minutes. Setting to 20.{RESET}")
                    return 20
                return val
        except ValueError:
            pass
        print(f"{RED}Please enter a positive integer duration.{RESET}")

def prompt_difficulty_intensity(sport):
    if sport in ["stretching", "strength"]:
        print(f"\n{BOLD}Select Difficulty:{RESET}")
        print("  [1] Easy / Beginner")
        print("  [2] Medium / Intermediate")
        print("  [3] Hard / Advanced")
        while True:
            choice = input("Choose difficulty (1-3) [2]: ").strip()
            if not choice:
                return 2
            try:
                val = int(choice)
                if 1 <= val <= 3:
                    return val
            except ValueError:
                pass
            print(f"{RED}Please enter 1, 2, or 3.{RESET}")
    else:
        print(f"\n{BOLD}Select Intensity Level (1-8):{RESET}")
        print("  1: Active Recovery (Z1)")
        print("  2: Endurance Base (Z2)")
        print("  3: Tempo Mix (Z3)")
        print("  4: Threshold Mix (Z4)")
        print("  5: VO2 Max Mix (Z5)")
        print("  6: Anaerobic Mix (Z6)")
        print("  7: Sprint Power (Z7)")
        print("  8: Race Simulation")
        while True:
            choice = input("Choose intensity level (1-8) [2]: ").strip()
            if not choice:
                return 2
            try:
                val = int(choice)
                if 1 <= val <= 8:
                    return val
            except ValueError:
                pass
            print(f"{RED}Please enter a value between 1 and 8.{RESET}")

def prompt_date():
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    while True:
        choice = input(f"\nEnter date (YYYY-MM-DD) [{today_str}]: ").strip()
        if not choice:
            return today_str
        try:
            datetime.datetime.strptime(choice, "%Y-%m-%d")
            return choice
        except ValueError:
            print(f"{RED}Invalid date format. Use YYYY-MM-DD.{RESET}")

def generate_workout_payload(user_id, sport, focus, duration_mins, difficulty_intensity, date_str):
    # Fetch user details to extract equipment/CTL configurations
    print(f"\n{BLUE}Retrieving user profile info for user '{user_id}'...{RESET}")
    user_ref = db.collection("users").document(user_id)
    user_doc = user_ref.get()
    
    equipment = ["bodyweight"]
    ctl = 50.0
    
    if user_doc.exists:
        data = user_doc.to_dict()
        # Parse equipment from user doc (frontend saves as list or key values, fallback to logic in main.py)
        raw_eq = data.get("equipment", [])
        if not raw_eq:
            # check equipmentToggles
            toggles = data.get("equipmentToggles", {})
            raw_eq = [k for k, v in toggles.items() if v]
            
        if raw_eq:
            # Map equipment keys as done in functions/main.py
            equipment = ["bodyweight"]
            if 'dumbbells' in raw_eq or 'kettlebell' in raw_eq:
                equipment.extend(['dumbbells', 'kettlebells'])
            if 'squatRack' in raw_eq:
                equipment.extend(['barbell', 'weights', 'bench'])
            if 'bench' in raw_eq:
                equipment.append('bench')
            if 'pullUpBar' in raw_eq:
                equipment.extend(['pullup_bar', 'weights'])
            if 'cable' in raw_eq or 'latPulldown' in raw_eq or 'flyMachine' in raw_eq:
                equipment.extend(['cables', 'machine'])
            if 'resistanceBands' in raw_eq:
                equipment.append('bands')
            equipment = list(set(equipment))
            
        ctl = float(data.get("ctl", 50.0))
        print(f"{GREEN}Using existing profile settings: Equipment={equipment}, CTL={ctl:.1f}{RESET}")
    else:
        print(f"{YELLOW}Warning: User '{user_id}' does not exist in users collection.{RESET}")
        print(f"Using default configurations (Bodyweight equipment, CTL=50.0)")

    workout_id = str(uuid.uuid4())
    steps = []
    segments = []
    name = "Custom Workout"
    description = ""
    tss = 0
    target_type = "time"
    time_sec = duration_mins * 60
    
    if sport == "stretching":
        # Invoking StretchGenerator
        payload = StretchGenerator.generate(focus, duration_mins, difficulty_intensity)
        name = payload["name"]
        description = payload["description"]
        steps = payload["steps"]
        
        # Map to frontend segments
        for step in steps:
            segments.append({
                "title": step["name"],
                "description": step["instruction"],
                "duration": step["duration_sec"],
                "assetName": step["asset_name"]
            })
            
        diff_label = {1: "Easy", 2: "Medium", 3: "Hard"}.get(difficulty_intensity, "Medium")
        meta = f"{duration_mins}m • {diff_label} • ~0 TSS"
        target_type = "time"
        
    elif sport == "strength":
        # Invoking StrengthGenerator
        payload = StrengthGenerator.generate(focus, duration_mins, difficulty_intensity, equipment)
        name = payload["name"]
        description = payload["description"]
        steps = payload["steps"]
        
        # Map to frontend segments
        for step in steps:
            segments.append({
                "title": step["name"],
                "description": step["instruction"],
                "assetName": step["asset_name"]
            })
            
        diff_label = {1: "Beginner", 2: "Intermediate", 3: "Advanced"}.get(difficulty_intensity, "Intermediate")
        meta = f"{duration_mins}m • {diff_label} • ~0 TSS"
        target_type = "reps"
        
    else:
        # Cardio sports: running, cycling, swimming
        duration_hours = duration_mins / 60.0
        payload = WorkoutGenerator.generate(sport, duration_hours, difficulty_intensity, ctl, equipment)
        name = payload["name"]
        description = payload.get("descriptions", {}).get("mix", payload.get("descriptions", {}).get("structured", ""))
        steps = payload["steps"]
        target_type = payload.get("targetType", "power")
        
        # Calculate TSS
        TSS_MULTIPLIER_MAP = {-1: 0, 0: 20, 1: 40, 2: 60, 3: 80, 4: 60, 5: 60, 6: 70, 7: 80, 8: 90}
        tss_multiplier = TSS_MULTIPLIER_MAP.get(difficulty_intensity, 40)
        tss = round(duration_hours * tss_multiplier)
        
        # Map to segments
        for step in steps:
            stype = step.get("type", "Active").capitalize()
            target_pct = step.get("target_percent_ftp")
            tdesc = f"Target: {target_pct}% FTP" if target_pct else f"{stype} zone"
            segments.append({
                "title": f"{stype} Segment",
                "description": tdesc,
                "duration": step["duration_sec"]
            })
            
        meta = f"{duration_mins}m • Effort Lvl {difficulty_intensity} • ~{tss} TSS"
        
    workout_item = {
        "workoutId": workout_id,
        "userId": user_id,
        "date": date_str,
        "name": name,
        "description": description,
        "meta": meta,
        "tss": tss,
        "tss_type": "estimated",
        "time": time_sec,
        "plannedTime": time_sec,
        "plannedTss": tss,
        "sport": sport,
        "completed": False,
        "status": "planned",
        "event_type": "Training",
        "intensity": difficulty_intensity,
        "targetType": target_type,
        "steps": steps,
        "segments": segments,
        "createdAt": firestore.SERVER_TIMESTAMP
    }
    
    return workout_item

def save_workout(workout_item):
    """Writes the workout item to the Firestore workouts collection"""
    w_id = workout_item["workoutId"]
    print(f"{BLUE}Saving workout {w_id} to Firestore...{RESET}")
    try:
        db.collection("workouts").document(w_id).set(workout_item)
        print(f"{GREEN}Successfully added workout to Firestore!{RESET}")
        return True
    except Exception as e:
        print(f"{RED}Error saving workout: {e}{RESET}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Athlethium Custom Workout Generator & Database Seeder")
    parser.add_argument("--userid", type=str, help="Target user ID")
    parser.add_argument("--sport", choices=["stretching", "strength", "running", "cycling", "swimming"], help="Sport category")
    parser.add_argument("--focus", choices=["full", "upper", "lower"], default="full", help="Focus area (stretching/strength only)")
    parser.add_argument("--duration", type=int, help="Workout duration in minutes")
    parser.add_argument("--difficulty", type=int, help="Difficulty (1-3 for strength/stretch) or intensity (1-8 for cardio)")
    parser.add_argument("--date", type=str, help="Date in YYYY-MM-DD format")
    
    args = parser.parse_args()
    
    # Header Banner
    print("\n" + "=" * 60)
    print(f"{BOLD}       ATHLETHIUM CUSTOM WORKOUT GENERATION TOOL       {RESET}")
    print("=" * 60)

    # Determine interactive or CLI mode
    is_interactive = not (args.userid and args.sport)
    
    if is_interactive:
        users = get_existing_users()
        user_id = prompt_user_id(users)
        sport = prompt_sport()
        focus = prompt_focus(sport)
        duration = prompt_duration(sport)
        difficulty = prompt_difficulty_intensity(sport)
        date_str = prompt_date()
    else:
        user_id = args.userid
        sport = args.sport
        focus = args.focus
        duration = args.duration if args.duration else get_default_duration(sport)
        difficulty = args.difficulty if args.difficulty else 2
        date_str = args.date if args.date else datetime.date.today().strftime("%Y-%m-%d")
        
        # Validation for non-interactive arguments
        try:
            datetime.datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            print(f"{RED}Error: Invalid date format. Use YYYY-MM-DD.{RESET}")
            sys.exit(1)
            
        if sport == "stretching" and duration > 20:
            duration = 20

    # Generate the item
    workout_item = generate_workout_payload(user_id, sport, focus, duration, difficulty, date_str)
    
    # Display generated workout summary
    print("\n" + "-" * 40)
    print(f"{BOLD}Generated Workout Details:{RESET}")
    print(f"  Name:        {workout_item['name']}")
    print(f"  Sport:       {workout_item['sport'].capitalize()}")
    print(f"  Date:        {workout_item['date']}")
    print(f"  Meta:        {workout_item['meta']}")
    print(f"  Description: {workout_item['description'].split('.')[0]}.")
    print(f"  Steps Count: {len(workout_item['steps'])} exercise(s) / segment(s)")
    print("-" * 40 + "\n")
    
    # Save to database
    save_workout(workout_item)
    print("=" * 60 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
