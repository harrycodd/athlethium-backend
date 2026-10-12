"""
Endurance Workout Generator for Cycling, Running, and Swimming.
Generates structured steps, intervals, power targets (% FTP), HR zones, and pacing.
"""

from typing import Dict, Any, List, Optional
from core.models import WorkoutStep, TargetType
from core.config import INTENSITY_ZONES


SPORT_LABEL = {"cycling": "Bike", "running": "Run", "swimming": "Swim"}

# (reps, work sec, rest sec), easiest first. The rung used grows with the athlete's level and
# with the week of the training block, then the largest that fits the session is chosen.
THRESHOLD_LADDER = {
    "cycling": [(3, 480, 240), (3, 600, 300), (4, 600, 300), (3, 720, 360), (3, 900, 300), (2, 1200, 300)],
    "running": [(4, 360, 90), (5, 360, 90), (4, 480, 120), (3, 600, 120), (2, 900, 180)],
}
VO2_LADDER = {
    "cycling": [(5, 180, 180), (6, 180, 180), (5, 240, 180), (4, 300, 180)],
    "running": [(5, 180, 150), (6, 180, 150), (5, 240, 180)],
}
# Swim sets by distance: (reps, metres, rest sec), swum relative to CSS (threshold pace / 100 m)
SWIM_THRESHOLD_LADDER = [(8, 100, 15), (10, 100, 15), (5, 200, 20), (4, 300, 20), (3, 400, 30)]
SWIM_SPEED_LADDER = [(10, 50, 20), (12, 50, 20), (8, 100, 30), (10, 100, 30)]
SWIM_EASY_FACTOR = 1.25      # easy swimming takes 25% longer per 100 m than CSS
SWIM_DRILLS = "catch-up, fist, single-arm, 6-kick switch"
WARMUP_OPENERS = "Build gradually; in the last 5 min do 3 × 1 min building to your interval effort."


def _mmss(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _rung(ladder, level: int, progression: int, fits) -> tuple:
    """Highest rung up to level + progression that fits the session; the easiest one otherwise."""
    top = min(len(ladder) - 1, max(0, level) + max(0, progression))
    for rung in reversed(ladder[:top + 1]):
        if fits(rung):
            return rung
    return ladder[0]


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
        interval_style: str = "structured",
        level: int = 1,
        progression: int = 0,
        swim_css_sec: float = 110.0,
    ) -> Dict[str, Any]:
        """
        `level` 0-4 (beginner-pro) and `progression` (week of the training block, 0-2) pick how big
        the main set is; `swim_css_sec` (threshold pace per 100 m) times distance-based swim sets.
        """
        if user_equipment is None:
            user_equipment = ["power_meter"]

        # Resolve target metric
        target_type = cls.resolve_target_type(sport, user_equipment)

        total_sec = int(round(duration_hours * 3600))
        # Minimum sensible duration is 20 minutes
        total_sec = max(1200, total_sec)

        int_config = INTENSITY_ZONES.get(intensity, INTENSITY_ZONES[2])
        zone_name = int_config["name"]

        if sport == "swimming" and intensity in (1, 2, 4, 5):
            return cls._swim_session(total_sec, intensity, target_type, level, progression, swim_css_sec)
        label = SPORT_LABEL.get(sport, sport.capitalize())

        # Build steps based on intensity level
        steps: List[WorkoutStep] = []
        descriptions: Dict[str, str] = {}
        title = f"{sport.capitalize()} - {zone_name}"

        if intensity <= 1:
            # Zone 1: Active Recovery Continuous Spin/Jog
            title = f"{label} Recovery (Zone 1)"
            steps = cls._build_recovery_steps(total_sec, target_type)
            descriptions = {
                "structured": f"Easy conversational {sport} session in Zone 1 (<55% FTP) to flush metabolites and stimulate active recovery.",
                "mix": f"Gentle {sport} session. Keep the intensity very light and relaxed.",
                "non_structured": "Very easy spin or jog. Keep it conversational. Cafe ride pace."
            }

        elif intensity == 2:
            # Zone 2: Aerobic Endurance Base
            title = f"{label} Endurance (Zone 2)"
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
            steps, (reps, work, rest) = cls._build_interval_set(
                total_sec, target_type, THRESHOLD_LADDER.get(sport, THRESHOLD_LADDER["cycling"]),
                level, progression, "Threshold", 96, 102)
            title = f"{label} Threshold: {reps} × {work // 60} min"
            descriptions = {
                "structured": f"{reps} × {work // 60} min at threshold with {_mmss(rest)} easy between. "
                              "Hard but controlled: you could hold each effort a little longer at the end. "
                              "Raises the effort you can sustain for an hour.",
                "mix": f"{reps} sustained hard efforts of about {work // 60} min with easy recoveries.",
                "non_structured": f"Include {reps} long, hard, steady efforts (climbs or flat) of about {work // 60} min."
            }

        elif intensity == 5:
            # Zone 5: VO2 Max Microbursts / Long Intervals
            steps, (reps, work, rest) = cls._build_interval_set(
                total_sec, target_type, VO2_LADDER.get(sport, VO2_LADDER["cycling"]),
                level, progression, "VO2max", 110, 118)
            title = f"{label} VO2max: {reps} × {work // 60} min"
            descriptions = {
                "structured": f"{reps} × {work // 60} min at VO2max effort with {_mmss(rest)} easy between. "
                              "Hard and breathless but even: the last rep should match the first. "
                              "Raises your aerobic ceiling.",
                "mix": f"{reps} hard, breathless efforts of {work // 60} min with equal easy recovery.",
                "non_structured": f"{reps} punchy {work // 60}-min efforts on hills or fast stretches."
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
    def _build_interval_set(cls, total_sec: int, target_type: TargetType, ladder, level: int, progression: int,
                            name: str, low: int, high: int):
        """Warm-up with openers, `reps` × work at the target with easy recoveries, then any spare
        time as steady Zone 2 and a cool-down."""
        tt = target_type.value
        warmup_sec = min(900, int(total_sec * 0.2))
        cooldown = 600 if total_sec >= 3600 else 300
        available = total_sec - warmup_sec - cooldown
        reps, work, rest = _rung(ladder, level, progression,
                                 lambda r: r[0] * r[1] + (r[0] - 1) * r[2] <= available)
        while reps > 2 and reps * work + (reps - 1) * rest > available:
            reps -= 1  # short sessions keep the effort length but do fewer reps...
        if reps * work + (reps - 1) * rest > available:
            work = max(120, (available - (reps - 1) * rest) // reps // 60 * 60)  # ...or shorter efforts
        warmup = [WorkoutStep("warmup", warmup_sec, "Warm-up", 50, 75, tt, notes=WARMUP_OPENERS)]
        main: List[WorkoutStep] = []
        for i in range(reps):
            main.append(WorkoutStep("interval", work, f"{name} {i + 1}/{reps}", low, high, tt))
            if i < reps - 1:
                main.append(WorkoutStep("recovery", rest, "Easy", 50, 60, tt))
        return cls._wrap_main_set(warmup, main, total_sec, target_type), (reps, work, rest)

    @staticmethod
    def _swim_session(total_sec: int, intensity: int, target_type: TargetType, level: int, progression: int,
                      css: float) -> Dict[str, Any]:
        """Distance-based pool session: warm-up with drills, a main set relative to CSS, easy swim-down."""
        tt = target_type.value
        easy_100 = css * SWIM_EASY_FACTOR
        warm_m, drills = (300, 4) if total_sec >= 2400 else (200, 2)  # shorter warm-up for short swims
        steps = [WorkoutStep("warmup", int(warm_m / 100 * easy_100 + drills * (0.5 * easy_100 * 1.1 + 15)),
                             f"Warm-up: {warm_m} m easy + {drills} × 50 m drill", 55, 68, tt,
                             notes=f"{warm_m} m easy, mixing strokes. Then {drills} × 50 m drill ({SWIM_DRILLS}), "
                                   "15 s rest.")]
        cooldown = int(2 * easy_100)
        available = total_sec - steps[0].duration - cooldown
        if intensity in (4, 5):
            ladder, low, high, pace = ((SWIM_THRESHOLD_LADDER, 96, 102, css) if intensity == 4
                                       else (SWIM_SPEED_LADDER, 105, 112, css - 5))
            reps, metres, rest = _rung(ladder, level, progression,
                                       lambda r: r[0] * (r[1] / 100 * pace + r[2]) <= available)
            while reps > 4 and reps * (metres / 100 * pace + rest) > available:
                reps -= 1  # short swims do fewer reps
            rep_sec = int(round(metres / 100 * pace))
            effort = "at CSS (your threshold pace)" if intensity == 4 else "fast: about 5 s per 100 m quicker than CSS"
            for i in range(reps):
                steps.append(WorkoutStep("interval", rep_sec, f"{metres} m {i + 1}/{reps}", low, high, tt,
                                         notes=f"{metres} m {effort}, about {_mmss(rep_sec)}." if i == 0 else None))
                steps.append(WorkoutStep("recovery", rest, f"Rest {rest} s", 40, 50, tt))
            kind = "Threshold" if intensity == 4 else "Speed"
            title = f"Swim {kind}: {reps} × {metres} m"
            desc = (f"{reps} × {metres} m {effort} with {rest} s rest. Hold the same time on every rep."
                    if intensity == 4 else
                    f"{reps} × {metres} m fast with {rest} s rest. Strong, long strokes; don't let the last reps fade.")
        else:
            recovery = intensity <= 1
            low, high = (55, 65) if recovery else (65, 72)
            per_200 = 2 * easy_100 + 20
            pull = 4 * int(easy_100 + 15) if available >= 4 * (easy_100 + 15) + per_200 else 0
            n200 = max(1, int((available - pull) // per_200))
            for i in range(n200):
                steps.append(WorkoutStep("interval", int(2 * easy_100), f"200 m easy {i + 1}/{n200}", low, high, tt,
                                         notes="Relaxed, long strokes; breathe every 3 strokes." if i == 0 else None))
                steps.append(WorkoutStep("recovery", 20, "Rest 20 s", 40, 50, tt))
            if pull:
                steps.append(WorkoutStep("interval", pull, "4 × 100 m pull", low, high, tt,
                                         notes="With a pull buoy, 15 s rest. Focus on a strong catch."))
            main_set = f"{n200} × 200 m" + (" + pull" if pull else "")
            title = f"Swim Recovery: {main_set}" if recovery else f"Swim Aerobic: {main_set}"
            desc = ("Very easy recovery swim; technique over speed." if recovery else
                    "Easy aerobic swim: drills for technique, then steady 200s at a relaxed, conversational effort.")
        spare = total_sec - sum(st.duration for st in steps) - cooldown
        if spare >= 120:
            steps.append(WorkoutStep("interval", spare, "Easy swim", 65, 72, tt,
                                     notes=f"About {int(spare / easy_100) * 100} m easy, any stroke."))
        steps.append(WorkoutStep("cooldown", cooldown, "Swim-down: 200 m easy", 50, 60, tt))
        EnduranceGenerator._normalize_step_durations(steps, total_sec)
        return {
            "name": title,
            "descriptions": {"structured": desc, "mix": desc, "non_structured": desc},
            "description": desc,
            "steps": [st.to_dict() for st in steps],
            "targetType": tt,
            "total_duration_sec": total_sec,
        }

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
