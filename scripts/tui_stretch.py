import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions"))
from generators.mobility import MobilityGenerator

def print_header(title):
    print("\n" + "=" * 50)
    print(f"  {title.center(46)}")
    print("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="Athlethium Stretching Routine Generator (TUI)")
    parser.add_argument("--focus", choices=["lower", "upper", "full"], help="Target area")
    parser.add_argument("--time", type=int, help="Duration in minutes (5-20)")
    parser.add_argument("--diff", type=int, choices=[1, 2, 3], help="Difficulty: 1(Easy) to 3(Hard)")
    
    args = parser.parse_args()
    
    # Interactive Prompts if arguments are missing
    print_header("ATHLETHIUM STRETCH GENERATOR")
    
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
            choice = input("Enter time in minutes (5-20) [10]: ").strip()
            duration = int(choice) if choice else 10
        except (ValueError, EOFError):
            duration = 10
            print("10")
        duration = max(5, min(20, duration))

    difficulty = args.diff
    if not difficulty:
        print("\nDifficulty:")
        print("  [1] Easy (Basic stretches)")
        print("  [2] Medium (Deeper stretches, some balance)")
        print("  [3] Hard (Advanced mobility/flexibility)")
        try:
            choice = input("Select difficulty (1-3) [2]: ").strip()
            difficulty = int(choice) if choice else 2
        except (ValueError, EOFError):
            difficulty = 2
            print("2")
        difficulty = max(1, min(3, difficulty))

    # Generate Routine
    print_header("GENERATING ROUTINE...")
    routine = StretchGenerator.generate(focus, duration, difficulty)
    
    # Display Output
    print(f" Name:       {routine['name']}")
    print(f" Focus:      {routine['focus'].capitalize()} Body")
    print(f" Duration:   {routine['duration_minutes']} Minutes")
    print(f" Difficulty: {routine['difficulty']}")
    print("-" * 50)
    
    print("\nROUTINE STEPS:")
    for i, step in enumerate(routine['steps'], 1):
        print(f"\n {i:2d}. {step['name']}")
        print(f"     Target: {step['muscle_group']}")
        print(f"     Action: {step['instruction']}")
    
    print("\n" + "=" * 50)
    print("  Session ready. Have a great stretch!".center(50))
    print("=" * 50 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
