import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"))
from generators.strength import StrengthGenerator

def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title.center(56)}")
    print("=" * 60)

def main():
    parser = argparse.ArgumentParser(description="Athlethium Gym/Strength Routine Generator (TUI)")
    parser.add_argument("--focus", choices=["lower", "upper", "full"], help="Target area")
    parser.add_argument("--time", type=int, help="Duration in minutes (15-90)")
    parser.add_argument("--diff", type=int, choices=[1, 2, 3], help="Difficulty: 1(Beginner) to 3(Advanced)")
    
    args = parser.parse_args()
    
    # Interactive Prompts if arguments are missing
    print_header("ATHLETHIUM STRENGTH GENERATOR")
    
    focus = args.focus
    if not focus:
        print("\nTarget Area:")
        print("  [1] Lower Body")
        print("  [2] Upper Body")
        print("  [3] Full Body")
        try:
            choice = input("Select focus (1-3) [3]: ").strip()
            focus = {"1": "lower", "2": "upper", "3": "full"}.get(choice, "full")
        except EOFError:
            focus = "full"
            print("full")

    duration = args.time
    if not duration:
        print("\nDuration:")
        try:
            choice = input("Enter time in minutes (15-90) [45]: ").strip()
            duration = int(choice) if choice else 45
        except (ValueError, EOFError):
            duration = 45
            print("45")
        duration = max(15, min(90, duration))

    difficulty = args.diff
    if not difficulty:
        print("\nDifficulty:")
        print("  [1] Beginner (Machines, Bodyweight, Basics)")
        print("  [2] Intermediate (Dumbbells, Cables, Some Barbells)")
        print("  [3] Advanced (Heavy Barbells, Complex Movements)")
        try:
            choice = input("Select difficulty (1-3) [2]: ").strip()
            difficulty = int(choice) if choice else 2
        except (ValueError, EOFError):
            difficulty = 2
            print("2")
        difficulty = max(1, min(3, difficulty))

    # Generate Routine
    print_header("GENERATING ROUTINE...")
    routine = StrengthGenerator.generate(focus, duration, difficulty)
    
    # Display Output
    print(f" Name:       {routine['name']}")
    print(f" Focus:      {routine['focus'].capitalize()} Body")
    print(f" Duration:   {routine['duration_minutes']} Minutes")
    print(f" Difficulty: {routine['difficulty']}")
    print("-" * 60)
    
    print("\nROUTINE STEPS:")
    for i, step in enumerate(routine['steps'], 1):
        print(f"\n {i:2d}. {step['name']}")
        print(f"     Movement: {step['movement_pattern']}")
        print(f"     Action:   {step['instruction']}")
    
    print("\n" + "=" * 60)
    print("  Session ready. Go lift heavy things!".center(60))
    print("=" * 60 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
