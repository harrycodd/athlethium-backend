"""
Realistic 30-Day Training Block Simulation Test.
Simulates day-by-day workouts, physiological adaptations, and intensity distributions.
"""

import unittest
import datetime
from engine.scheduler import TrainingScheduler
from engine.physiology import PhysiologyEngine
from tests.fixtures import CYCLIST_PROFILE, MARATHONER_PROFILE, TRIATHLETE_PROFILE


class TestAthleteSimulations(unittest.TestCase):

    def test_30_day_cyclist_simulation(self):
        """Simulates 30 days of training for a cyclist targeting an event."""
        profile = CYCLIST_PROFILE
        start_date = datetime.date(2026, 8, 24)

        total_tss = 0
        intensity_counts = {i: 0 for i in range(-1, 8)}
        sport_counts = {}
        daily_logs = []

        curr_ctl = profile.ctl
        curr_atl = profile.atl

        for day in range(30):
            current_date = start_date + datetime.timedelta(days=day)
            
            # 1. Schedule workout for the day
            workout = TrainingScheduler.schedule_day(profile, current_date)
            
            # 2. Record metrics
            intensity_counts[workout.intensity] = intensity_counts.get(workout.intensity, 0) + 1
            sport_counts[workout.sport] = sport_counts.get(workout.sport, 0) + 1
            total_tss += workout.tss

            # 3. Simulate completion and update physiological fitness
            curr_ctl, curr_atl, curr_tsb = PhysiologyEngine.calculate_next_day_metrics(
                curr_ctl, curr_atl, workout.tss
            )
            profile.ctl = curr_ctl
            profile.atl = curr_atl

            daily_logs.append({
                "day": day + 1,
                "date": workout.date,
                "sport": workout.sport,
                "name": workout.name,
                "intensity": workout.intensity,
                "time_mins": workout.time // 60,
                "tss": workout.tss,
                "ctl": curr_ctl,
                "tsb": curr_tsb
            })

        print("\n" + "="*80)
        print("🚲 30-DAY CYCLIST SIMULATION RESULTS")
        print("="*80)
        print(f"Total TSS Accumulated: {total_tss:.1f} (Avg ~{total_tss/4.3:.1f}/week)")
        print(f"Starting CTL: 55.0 -> Final CTL: {curr_ctl:.1f}")
        print(f"Intensity Distribution: {intensity_counts}")
        print(f"Sport Breakdown: {sport_counts}")
        print("\nSample 7 Days of Generated Workouts:")
        for log in daily_logs[:7]:
            print(f"  Day {log['day']:02d} ({log['date']}): {log['sport'].upper():<8} [Zone {log['intensity']}] {log['name']:<35} {log['time_mins']}m (TSS: {log['tss']:.0f})")
        print("="*80)

        # Assertions
        # 1. Must NOT be only easy days! Must contain high intensity days (Zone 4 or Zone 5)
        high_intensity_count = intensity_counts[4] + intensity_counts[5] + intensity_counts[6]
        self.assertGreaterEqual(high_intensity_count, 4, "Should have scheduled at least 4-8 high intensity sessions in 30 days.")

        # 2. Must contain Zone 2 Base Building
        self.assertGreaterEqual(intensity_counts[2], 8, "Should have regular Zone 2 Aerobic Base sessions.")

        # 3. Fitness (CTL) should have increased over the 30-day block
        self.assertGreater(curr_ctl, 55.0, "CTL should progressively increase over 30 days of consistent training.")


if __name__ == "__main__":
    unittest.main()
