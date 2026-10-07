"""
Endurance Workout Generator for Cycling, Running, and Swimming.
Generates structured steps, intervals, power targets (% FTP), HR zones, and pacing.
"""

from typing import Dict, Any, List, Optional
from core.models import WorkoutStep, TargetType
from core.config import INTENSITY_ZONES


class EnduranceGenerator:
    """
    Constructs physiologically accurate interval workouts ensuring
    step durations sum precisely to the total requested workout duration.
    """

    @classmethod
    def generate(
        cls,
        sport: str,
        duration_hours: float,
        intensity: int,
        user_equipment: Optional[List[str]] = None,
        interval_style: str = "structured"
    ) -> Dict[str, Any]:
        if user_equipment is None:
            user_equipment = ["power_meter"]

        # Resolve target metric
        target_type = cls.resolve_target_type(sport, user_equipment)

        total_sec = int(round(duration_hours * 3600))
        # Minimum sensible duration is 20 minutes
        total_sec = max(1200, total_sec)

        int_config = INTENSITY_ZONES.get(intensity, INTENSITY_ZONES[2])
        zone_name = int_config["name"]

        # Build steps based on intensity level
        steps: List[WorkoutStep] = []
        descriptions: Dict[str, str] = {}
        title = f"{sport.capitalize()} - {zone_name}"

        if intensity <= 1:
            # Zone 1: Active Recovery Continuous Spin/Jog
            title = f"{sport.capitalize()} Active Recovery"
            steps = cls._build_recovery_steps(total_sec, target_type)
            descriptions = {
                "structured": f"Easy conversational {sport} session in Zone 1 (<55% FTP) to flush metabolites and stimulate active recovery.",
                "mix": f"Gentle {sport} session. Keep the intensity very light and relaxed.",
                "non_structured": "Very easy spin or jog. Keep it conversational. Cafe ride pace."
            }

        elif intensity == 2:
            # Zone 2: Aerobic Endurance Base
            title = f"{sport.capitalize()} Aerobic Base Building"
            steps = cls._build_endurance_base_steps(total_sec, target_type)
            descriptions = {
                "structured": "Steady Zone 2 aerobic base building at 65-72% FTP. Keep pedal pressure / running cadence consistent.",
                "mix": f"Steady endurance {sport} with continuous pressure and steady breathing.",
                "non_structured": "Long steady distance. Keep continuous pressure and stay conversational."
            }

        elif intensity == 3:
            # Zone 3: Tempo / Sweet Spot Sustained Blocks
            title = f"{sport.capitalize()} Sweet Spot / Tempo Blocks"
            steps = cls._build_tempo_steps(total_sec, target_type)
            descriptions = {
                "structured": "Sustained Tempo / Sweet Spot intervals (85-88% FTP) to elevate aerobic capacity without excessive fatigue.",
                "mix": "Include sustained brisk efforts with easy endurance recoveries.",
                "non_structured": "Push hard on rolling terrain with steady endurance in between."
            }

        elif intensity == 4:
            # Zone 4: Threshold Over-Unders / Long Intervals
            title = f"{sport.capitalize()} Threshold Intervals"
            steps = cls._build_threshold_steps(total_sec, target_type)
            descriptions = {
                "structured": "Lactate threshold intervals (95-100% FTP) designed to push up your sustainable race pace.",
                "mix": "2-3 hard sustained threshold efforts with full aerobic recovery.",
                "non_structured": "Include 2-3 long hard climbs or fast sustained efforts."
            }

        elif intensity == 5:
            # Zone 5: VO2 Max Microbursts / Long Intervals
            title = f"{sport.capitalize()} VO2 Max Power Intervals"
            steps = cls._build_vo2max_steps(total_sec, target_type)
            descriptions = {
                "structured": "VO2 Max power intervals (110-120% FTP) to expand maximum aerobic ceiling and cardiac output.",
                "mix": "High-intensity punchy repeats with recovery intervals.",
                "non_structured": "Punchy breathless efforts on short hills or fast segments."
            }

        elif intensity == 6:
            # Zone 6: Anaerobic Capacity Surges
            title = f"{sport.capitalize()} Anaerobic Power Surges"
            steps = cls._build_anaerobic_steps(total_sec, target_type)
            descriptions = {
                "structured": "Short explosive anaerobic repeats (130-140% FTP) with full recoveries to build punchy attack power.",
                "mix": "Hard 1-2 minute attacks followed by easy spinning.",
                "non_structured": "Surge hard over hills or sprint segments with full recovery."
            }

        else:
            # Zone 7: Neuromuscular Sprints
            title = f"{sport.capitalize()} Neuromuscular Sprint Power"
            steps = cls._build_sprint_steps(total_sec, target_type)
            descriptions = {
                "structured": "Maximal all-out sprints (150-200% FTP) with extended recoveries for maximal neuromuscular recruitment.",
                "mix": "Max sprints with 3-5 minutes easy spinning between efforts.",
                "non_structured": "Town-sign sprints with full recovery."
            }

        # Validate step durations sum exactly to total_sec
        cls._normalize_step_durations(steps, total_sec)

        # Select description based on user preference
        selected_desc = descriptions.get(interval_style, descriptions["structured"])

        return {
            "name": title,
            "descriptions": descriptions,
            "description": selected_desc,
            "steps": [s.to_dict() for s in steps],
            "targetType": target_type.value,
            "total_duration_sec": total_sec
        }

    @staticmethod
    def resolve_target_type(sport: str, user_equipment: Optional[List[str]]) -> TargetType:
        """Power if the athlete can measure it, else heart rate, else pace (running) / % FTP (cycling)."""
        equipment = user_equipment if user_equipment is not None else ["power_meter"]
        if sport == "swimming":
            return TargetType.PACE if "swim_watch" in equipment else TargetType.TIME
        if (sport == "cycling" and "power_meter" in equipment) or (sport == "running" and "running_power" in equipment):
            return TargetType.POWER
        if "hr_monitor" in equipment or "heart_rate" in equipment:
            return TargetType.HEART_RATE
        if sport == "running":
            return TargetType.PACE
        return TargetType.POWER

    @staticmethod
    def _wrap_main_set(warmup: List[WorkoutStep], main: List[WorkoutStep], total_sec: int,
                       target_type: TargetType) -> List[WorkoutStep]:
        """Warm-up + main set, then any spare time as steady Zone 2 (not an endless cool-down)."""
        cooldown = 600 if total_sec >= 3600 else 300
        used = sum(st.duration for st in warmup + main)
        spare = total_sec - used - cooldown
        steps = list(warmup) + list(main)
        if spare >= 300:
            steps.append(WorkoutStep("interval", spare, "Steady Aerobic Z2", 65, 72, target_type.value))
        steps.append(WorkoutStep("cooldown", max(cooldown, total_sec - sum(st.duration for st in steps)),
                                 "Cool Down", 45, 55, target_type.value))
        return steps

    @staticmethod
    def _build_recovery_steps(total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        warmup = min(300, int(total_sec * 0.15))
        cooldown = min(300, int(total_sec * 0.15))
        main = total_sec - warmup - cooldown
        return [
            WorkoutStep("warmup", warmup, "Easy Ramp", 45, 55, target_type.value),
            WorkoutStep("interval", main, "Active Recovery Steady", 50, 55, target_type.value),
            WorkoutStep("cooldown", cooldown, "Easy Spin Down", 40, 50, target_type.value),
        ]

    @staticmethod
    def _build_endurance_base_steps(total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        warmup = min(600, int(total_sec * 0.15))
        cooldown = min(600, int(total_sec * 0.15))
        main = total_sec - warmup - cooldown
        return [
            WorkoutStep("warmup", warmup, "Progressive Warmup", 50, 65, target_type.value),
            WorkoutStep("interval", main, "Aerobic Base Z2", 65, 72, target_type.value),
            WorkoutStep("cooldown", cooldown, "Cool Down", 50, 58, target_type.value),
        ]

    @staticmethod
    def _build_tempo_steps(total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        warmup = min(600, int(total_sec * 0.2))
        cooldown = min(600, int(total_sec * 0.15))
        available_work = total_sec - warmup - cooldown

        # Decide interval block: 2x15m, 3x10m, or 2x20m
        if available_work >= 2400:
            work_dur = 900  # 15 min
            rest_dur = 300  # 5 min
            reps = min(3, available_work // (work_dur + rest_dur))
        else:
            work_dur = 600  # 10 min
            rest_dur = 180  # 3 min
            reps = max(2, min(3, available_work // (work_dur + rest_dur)))

        steps = [WorkoutStep("warmup", warmup, "Warmup & Activation", 50, 70, target_type.value)]
        for i in range(reps):
            steps.append(WorkoutStep("interval", work_dur, f"Sweet Spot Block {i+1}", 85, 88, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", rest_dur, "Recovery Spin", 50, 60, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), "Cool Down", 45, 55, target_type.value))
        return steps

    @classmethod
    def _build_threshold_steps(cls, total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        """2-4 x 8 min at threshold with 4 min floats (main set sized to the session)."""
        tt = target_type.value
        warmup = [
            WorkoutStep("warmup", min(720, int(total_sec * 0.2)) - 120, "Progressive Warmup", 50, 75, tt),
            WorkoutStep("interval", 60, "Threshold Opener", 95, 100, tt),
            WorkoutStep("recovery", 60, "Opener Rest", 50, 60, tt),
        ]
        cooldown = 600 if total_sec >= 3600 else 300
        available = total_sec - sum(st.duration for st in warmup) - cooldown
        work, rest = 480, 240
        reps = max(2, min(4, (available + rest) // (work + rest)))
        main: List[WorkoutStep] = []
        for i in range(reps):
            main.append(WorkoutStep("interval", work, f"Threshold Interval {i+1}", 96, 102, tt))
            if i < reps - 1:
                main.append(WorkoutStep("recovery", rest, "Recovery Float", 50, 60, tt))
        return cls._wrap_main_set(warmup, main, total_sec, target_type)

    @classmethod
    def _build_vo2max_steps(cls, total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        """3-6 x 3 min at VO2max with equal recovery."""
        tt = target_type.value
        warmup = [WorkoutStep("warmup", min(720, int(total_sec * 0.22)), "Ramp Warmup & Openers", 50, 75, tt)]
        cooldown = 600 if total_sec >= 3600 else 300
        available = total_sec - warmup[0].duration - cooldown
        work, rest = 180, 180
        reps = max(3, min(6, (available + rest) // (work + rest)))
        main: List[WorkoutStep] = []
        for i in range(reps):
            main.append(WorkoutStep("interval", work, f"VO2 Max Repeat {i+1}", 110, 118, tt))
            if i < reps - 1:
                main.append(WorkoutStep("recovery", rest, "Easy Recovery", 45, 55, tt))
        return cls._wrap_main_set(warmup, main, total_sec, target_type)

    @staticmethod
    def _build_anaerobic_steps(total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        warmup = min(720, int(total_sec * 0.25))
        steps = [WorkoutStep("warmup", warmup, "Dynamic Warmup", 50, 80, target_type.value)]

        reps = 6
        for i in range(reps):
            steps.append(WorkoutStep("interval", 60, f"Anaerobic Attack {i+1}", 130, 140, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", 120, "Active Rest Spin", 45, 55, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), "Cool Down", 45, 55, target_type.value))
        return steps

    @staticmethod
    def _build_sprint_steps(total_sec: int, target_type: TargetType) -> List[WorkoutStep]:
        warmup = min(720, int(total_sec * 0.25))
        steps = [WorkoutStep("warmup", warmup, "Thorough Sprint Warmup", 50, 80, target_type.value)]

        reps = 6
        for i in range(reps):
            steps.append(WorkoutStep("interval", 15, f"All-Out Sprint {i+1}", 160, 220, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", 180, "Full Recovery Spin", 40, 50, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), "Cool Down", 40, 50, target_type.value))
        return steps

    @classmethod
    def generate_race_week_session(cls, kind: str, sport: str, duration_hours: float,
                                   user_equipment: Optional[List[str]] = None,
                                   race_name: str = "Race", multisport: bool = False) -> Dict[str, Any]:
        """Opener (3 days out), shake-out (day before) and the race itself."""
        target_type = TargetType.TIME if (kind == "race" and multisport) else \
            cls.resolve_target_type(sport, user_equipment)
        tt = target_type.value
        total_sec = max(900, int(round(duration_hours * 3600)))
        if kind == "opener":
            title = f"{sport.capitalize()} Race Opener"
            desc = "Mostly easy with three short race-pace efforts to keep the legs sharp without adding fatigue."
            steps = [WorkoutStep("warmup", 900, "Easy Warmup", 50, 70, tt)]
            for i in range(3):
                steps.append(WorkoutStep("interval", 60, f"Race-Pace Effort {i+1}/3", 95, 105, tt))
                steps.append(WorkoutStep("recovery", 180, "Easy Float", 50, 65, tt))
            steps.append(WorkoutStep("cooldown", max(300, total_sec - sum(st.duration for st in steps)), "Easy Spin Down", 45, 60, tt))
        elif kind == "shakeout":
            title = f"{sport.capitalize()} Pre-Race Shake-Out"
            desc = "Short and easy with a few relaxed strides. Lay out your kit, fuel well and sleep early."
            steps = [WorkoutStep("warmup", 600, "Easy", 50, 68, tt)]
            for i in range(3):
                steps.append(WorkoutStep("interval", 20, f"Relaxed Stride {i+1}/3", 105, 115, tt))
                steps.append(WorkoutStep("recovery", 100, "Easy", 50, 65, tt))
            steps.append(WorkoutStep("cooldown", max(120, total_sec - sum(st.duration for st in steps)), "Easy", 50, 65, tt))
        else:
            title = f"Race Day: {race_name}"
            desc = "Race day. Warm up, start conservatively, fuel early and pace by feel and your targets."
            if multisport:  # one power/pace range can't describe a swim-bike-run race
                desc += " Pace each leg by your race plan."
                steps = [WorkoutStep("interval", total_sec, race_name, None, None, tt, notes="Race effort")]
            else:
                steps = [WorkoutStep("interval", total_sec, race_name, 85, 100, tt, notes="Race effort")]
        cls._normalize_step_durations(steps, total_sec)
        return {
            "name": title,
            "descriptions": {"structured": desc, "mix": desc, "non_structured": desc},
            "description": desc,
            "steps": [st.to_dict() for st in steps],
            "targetType": tt,
            "total_duration_sec": total_sec,
        }

    @classmethod
    def generate_benchmark_workout(
        cls,
        sport: str,
        duration_hours: float,
        interval_style: str = "structured",
        target_type: TargetType = TargetType.POWER
    ) -> Dict[str, Any]:
        """
        Generates a standardized post-deload benchmark test session (FTP Test, 5K Time Trial, CSS Test)
        to calibrate threshold metrics and update training zones.
        """
        total_sec = max(2400, int(round(duration_hours * 3600)))
        steps: List[WorkoutStep] = []

        if sport == "cycling":
            title = "Cycling 20-Min FTP Benchmark Test"
            desc = "Standardized 20-minute Functional Threshold Power (FTP) benchmark test following your deload week. Pace yourself evenly to measure maximum 20-min sustainable average power (FTP = 95% of 20-min avg)."
            steps.append(WorkoutStep("warmup", 900, "Progressive Warm-up & Spin", 50, 75, target_type.value))
            for i in range(3):
                steps.append(WorkoutStep("interval", 60, f"Threshold Opener {i+1}/3", 100, 105, target_type.value))
                steps.append(WorkoutStep("recovery", 60, "Easy Spin", 45, 55, target_type.value))
            steps.append(WorkoutStep("recovery", 300, "Pre-Test Rest & Focus", 45, 55, target_type.value))
            steps.append(WorkoutStep("interval", 1200, "20-Min All-Out FTP Benchmark TT", 100, 115, target_type.value, notes="Pace evenly for 20 minutes at maximum sustainable effort."))
            rem = max(300, total_sec - sum(s.duration for s in steps))
            steps.append(WorkoutStep("cooldown", rem, "Easy Spin Down", 40, 50, target_type.value))

        elif sport == "running":
            title = "Running 5K / Threshold Pace Benchmark"
            desc = "Post-deload running benchmark assessment. 20-minute continuous threshold time trial to calibrate your lactate threshold running pace and heart rate zones."
            steps.append(WorkoutStep("warmup", 900, "Easy Aerobic Warm-up Jog", 50, 65, target_type.value))
            for i in range(4):
                steps.append(WorkoutStep("interval", 25, f"Strides & Dynamic Opener {i+1}/4", 105, 120, target_type.value))
                steps.append(WorkoutStep("recovery", 35, "Walk / Easy Float", 40, 50, target_type.value))
            steps.append(WorkoutStep("recovery", 180, "Pre-Test Focus & Rest", 40, 50, target_type.value))
            steps.append(WorkoutStep("interval", 1200, "20-Min Threshold Pace Benchmark Run", 98, 105, target_type.value, notes="Sustain maximum hard pace for 20 minutes to establish threshold pace."))
            rem = max(300, total_sec - sum(s.duration for s in steps))
            steps.append(WorkoutStep("cooldown", rem, "Cool-down Jog & Walk", 40, 50, target_type.value))

        elif sport == "swimming":
            title = "Swimming CSS (Critical Swim Speed) Test"
            desc = "Critical Swim Speed benchmark test (400m + 200m time trials) to update CSS pace per 100m."
            steps.append(WorkoutStep("warmup", 600, "Warm-up & Drills (400m easy)", 50, 65, target_type.value))
            steps.append(WorkoutStep("interval", 420, "400m Time Trial (Max Steady Effort)", 95, 105, target_type.value))
            steps.append(WorkoutStep("recovery", 360, "Easy Recovery Kick & Float (200m)", 40, 50, target_type.value))
            steps.append(WorkoutStep("interval", 210, "200m Time Trial (All-Out Effort)", 105, 115, target_type.value))
            rem = max(300, total_sec - sum(s.duration for s in steps))
            steps.append(WorkoutStep("cooldown", rem, "Cool-down Swim (200m)", 40, 50, target_type.value))

        else:
            title = f"{sport.capitalize()} Baseline Fitness Benchmark"
            desc = "Standardized post-deload fitness benchmark test to evaluate current fitness levels."
            steps.append(WorkoutStep("warmup", 600, "Progressive Warm-up", 50, 70, target_type.value))
            steps.append(WorkoutStep("interval", 1200, "Main Benchmark Assessment Effort", 95, 105, target_type.value))
            rem = max(300, total_sec - sum(s.duration for s in steps))
            steps.append(WorkoutStep("cooldown", rem, "Cool Down", 40, 50, target_type.value))

        cls._normalize_step_durations(steps, total_sec)

        return {
            "name": title,
            "descriptions": {"structured": desc, "mix": desc, "non_structured": desc},
            "description": desc,
            "steps": [s.to_dict() for s in steps],
            "targetType": target_type.value,
            "total_duration_sec": total_sec
        }

    @staticmethod
    def _normalize_step_durations(steps: List[WorkoutStep], target_sec: int):
        """Adjusts cooldown duration so step total exactly matches target_sec."""
        if not steps:
            return
        current_total = sum(s.duration for s in steps)
        diff = target_sec - current_total
        if diff != 0:
            steps[-1].duration = max(60, steps[-1].duration + diff)
