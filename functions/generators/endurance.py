"""
Endurance Workout Generator for Cycling, Running, and Swimming.
Generates structured steps, intervals, power targets (% FTP), HR zones, and pacing.
"""

from typing import Dict, Any, List, Optional
from core.models import WorkoutStep, TargetType
from i18n import sport_text, t


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
        lang: str = "en",
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

        if sport == "swimming" and intensity in (1, 2, 4, 5):
            return cls._swim_session(total_sec, intensity, target_type, level, progression, swim_css_sec, lang)
        # short label for titles ("Bike Endurance"), the sport's name in sentences and in titles
        label = sport_text(lang, sport, "label")
        name = sport_text(lang, sport, "name")
        sport_title = sport_text(lang, sport, "title")
        params: Dict[str, Any] = {"sport": name}

        # Build steps based on intensity level; each zone has a title and one description per style
        steps: List[WorkoutStep] = []

        if intensity <= 1:
            # Zone 1: Active Recovery Continuous Spin/Jog
            zone, title = "recovery", t(lang, "endurance.recovery.name", sport=label)
            steps = cls._build_recovery_steps(total_sec, target_type, lang)

        elif intensity == 2:
            # Zone 2: Aerobic Endurance Base
            zone, title = "endurance", t(lang, "endurance.endurance.name", sport=label)
            steps = cls._build_endurance_base_steps(total_sec, target_type, lang)

        elif intensity == 3:
            # Zone 3: Tempo / Sweet Spot Sustained Blocks
            zone, title = "tempo", t(lang, "endurance.tempo.name", sport=sport_title)
            steps = cls._build_tempo_steps(total_sec, target_type, lang)

        elif intensity in (4, 5):
            # Zone 4: Threshold long intervals / Zone 5: VO2max intervals
            zone = "threshold" if intensity == 4 else "vo2"
            ladder, low, high = ((THRESHOLD_LADDER, 96, 102) if intensity == 4 else (VO2_LADDER, 110, 118))
            steps, (reps, work, rest) = cls._build_interval_set(
                total_sec, target_type, ladder.get(sport, ladder["cycling"]),
                level, progression, f"step.interval.{zone}", low, high, lang)
            params.update(reps=reps, minutes=work // 60, rest=_mmss(rest))
            title = t(lang, f"endurance.{zone}.name", sport=label, reps=reps, minutes=work // 60)

        elif intensity == 6:
            # Zone 6: Anaerobic Capacity Surges
            zone, title = "anaerobic", t(lang, "endurance.anaerobic.name", sport=sport_title)
            steps = cls._build_anaerobic_steps(total_sec, target_type, lang)

        else:
            # Zone 7: Neuromuscular Sprints
            zone, title = "sprint", t(lang, "endurance.sprint.name", sport=sport_title)
            steps = cls._build_sprint_steps(total_sec, target_type, lang)

        descriptions = {style: t(lang, f"endurance.{zone}.description.{style}", **params)
                        for style in ("structured", "mix", "non_structured")}

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
                       target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
        """Warm-up + main set, then any spare time as steady Zone 2 (not an endless cool-down)."""
        cooldown = 600 if total_sec >= 3600 else 300
        used = sum(st.duration for st in warmup + main)
        spare = total_sec - used - cooldown
        steps = list(warmup) + list(main)
        if spare >= 300:
            steps.append(WorkoutStep("interval", spare, t(lang, "step.steadyAerobicZ2"), 65, 72, target_type.value))
        steps.append(WorkoutStep("cooldown", max(cooldown, total_sec - sum(st.duration for st in steps)),
                                 t(lang, "step.coolDown"), 45, 55, target_type.value))
        return steps

    @staticmethod
    def _build_recovery_steps(total_sec: int, target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
        warmup = min(300, int(total_sec * 0.15))
        cooldown = min(300, int(total_sec * 0.15))
        main = total_sec - warmup - cooldown
        return [
            WorkoutStep("warmup", warmup, t(lang, "step.easyRamp"), 45, 55, target_type.value),
            WorkoutStep("interval", main, t(lang, "step.activeRecoverySteady"), 50, 55, target_type.value),
            WorkoutStep("cooldown", cooldown, t(lang, "step.easySpinDown"), 40, 50, target_type.value),
        ]

    @staticmethod
    def _build_endurance_base_steps(total_sec: int, target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
        warmup = min(600, int(total_sec * 0.15))
        cooldown = min(600, int(total_sec * 0.15))
        main = total_sec - warmup - cooldown
        return [
            WorkoutStep("warmup", warmup, t(lang, "step.progressiveWarmup"), 50, 65, target_type.value),
            WorkoutStep("interval", main, t(lang, "step.aerobicBaseZ2"), 65, 72, target_type.value),
            WorkoutStep("cooldown", cooldown, t(lang, "step.coolDown"), 50, 58, target_type.value),
        ]

    @staticmethod
    def _build_tempo_steps(total_sec: int, target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
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

        steps = [WorkoutStep("warmup", warmup, t(lang, "step.warmupActivation"), 50, 70, target_type.value)]
        for i in range(reps):
            steps.append(WorkoutStep("interval", work_dur, t(lang, "step.sweetSpotBlock", n=i + 1), 85, 88, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", rest_dur, t(lang, "step.recoverySpin"), 50, 60, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), t(lang, "step.coolDown"), 45, 55,
                                 target_type.value))
        return steps

    @classmethod
    def _build_interval_set(cls, total_sec: int, target_type: TargetType, ladder, level: int, progression: int,
                            name_key: str, low: int, high: int, lang: str = "en"):
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
        warmup = [WorkoutStep("warmup", warmup_sec, t(lang, "step.warmup"), 50, 75, tt,
                              notes=t(lang, "notes.warmupOpeners"))]
        main: List[WorkoutStep] = []
        for i in range(reps):
            main.append(WorkoutStep("interval", work, t(lang, name_key, n=i + 1, total=reps), low, high, tt))
            if i < reps - 1:
                main.append(WorkoutStep("recovery", rest, t(lang, "step.easy"), 50, 60, tt))
        return cls._wrap_main_set(warmup, main, total_sec, target_type, lang), (reps, work, rest)

    @staticmethod
    def _swim_session(total_sec: int, intensity: int, target_type: TargetType, level: int, progression: int,
                      css: float, lang: str = "en") -> Dict[str, Any]:
        """Distance-based pool session: warm-up with drills, a main set relative to CSS, easy swim-down."""
        tt = target_type.value
        easy_100 = css * SWIM_EASY_FACTOR
        warm_m, drills = (300, 4) if total_sec >= 2400 else (200, 2)  # shorter warm-up for short swims
        steps = [WorkoutStep("warmup", int(warm_m / 100 * easy_100 + drills * (0.5 * easy_100 * 1.1 + 15)),
                             t(lang, "swim.step.warmup", metres=warm_m, drills=drills), 55, 68, tt,
                             notes=t(lang, "swim.notes.warmup", metres=warm_m, drills=drills,
                                     drill_list=t(lang, "swim.drillList")))]
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
            kind = "threshold" if intensity == 4 else "speed"
            for i in range(reps):
                steps.append(WorkoutStep("interval", rep_sec, t(lang, "swim.step.rep", metres=metres, n=i + 1,
                                                                total=reps), low, high, tt,
                                         notes=t(lang, f"swim.notes.rep.{kind}", metres=metres, time=_mmss(rep_sec))
                                         if i == 0 else None))
                steps.append(WorkoutStep("recovery", rest, t(lang, "swim.step.rest", seconds=rest), 40, 50, tt))
            title = t(lang, f"swim.{kind}.name", reps=reps, metres=metres)
            desc = t(lang, f"swim.{kind}.description", reps=reps, metres=metres, rest=rest)
        else:
            recovery = intensity <= 1
            low, high = (55, 65) if recovery else (65, 72)
            per_200 = 2 * easy_100 + 20
            pull = 4 * int(easy_100 + 15) if available >= 4 * (easy_100 + 15) + per_200 else 0
            n200 = max(1, int((available - pull) // per_200))
            for i in range(n200):
                steps.append(WorkoutStep("interval", int(2 * easy_100), t(lang, "swim.step.easy200", n=i + 1,
                                                                          total=n200), low, high, tt,
                                         notes=t(lang, "swim.notes.easy200") if i == 0 else None))
                steps.append(WorkoutStep("recovery", 20, t(lang, "swim.step.rest", seconds=20), 40, 50, tt))
            if pull:
                steps.append(WorkoutStep("interval", pull, t(lang, "swim.step.pull"), low, high, tt,
                                         notes=t(lang, "swim.notes.pull")))
            kind = "recovery" if recovery else "aerobic"
            title = t(lang, f"swim.{kind}.name" + (".pull" if pull else ""), sets=n200)
            desc = t(lang, f"swim.{kind}.description")
        spare = total_sec - sum(st.duration for st in steps) - cooldown
        if spare >= 120:
            steps.append(WorkoutStep("interval", spare, t(lang, "swim.step.easy"), 65, 72, tt,
                                     notes=t(lang, "swim.notes.easy", metres=int(spare / easy_100) * 100)))
        steps.append(WorkoutStep("cooldown", cooldown, t(lang, "swim.step.swimDown"), 50, 60, tt))
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
    def _build_anaerobic_steps(total_sec: int, target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
        warmup = min(720, int(total_sec * 0.25))
        steps = [WorkoutStep("warmup", warmup, t(lang, "step.dynamicWarmup"), 50, 80, target_type.value)]

        reps = 6
        for i in range(reps):
            steps.append(WorkoutStep("interval", 60, t(lang, "step.anaerobicAttack", n=i + 1), 130, 140, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", 120, t(lang, "step.activeRestSpin"), 45, 55, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), t(lang, "step.coolDown"), 45, 55,
                                 target_type.value))
        return steps

    @staticmethod
    def _build_sprint_steps(total_sec: int, target_type: TargetType, lang: str = "en") -> List[WorkoutStep]:
        warmup = min(720, int(total_sec * 0.25))
        steps = [WorkoutStep("warmup", warmup, t(lang, "step.sprintWarmup"), 50, 80, target_type.value)]

        reps = 6
        for i in range(reps):
            steps.append(WorkoutStep("interval", 15, t(lang, "step.allOutSprint", n=i + 1), 160, 220, target_type.value))
            if i < reps - 1:
                steps.append(WorkoutStep("recovery", 180, t(lang, "step.fullRecoverySpin"), 40, 50, target_type.value))

        current_sum = sum(s.duration for s in steps)
        steps.append(WorkoutStep("cooldown", max(300, total_sec - current_sum), t(lang, "step.coolDown"), 40, 50,
                                 target_type.value))
        return steps

    @classmethod
    def generate_race_week_session(cls, kind: str, sport: str, duration_hours: float,
                                   user_equipment: Optional[List[str]] = None,
                                   race_name: str = "Race", multisport: bool = False,
                                   lang: str = "en") -> Dict[str, Any]:
        """Opener (3 days out), shake-out (day before) and the race itself."""
        target_type = TargetType.TIME if (kind == "race" and multisport) else \
            cls.resolve_target_type(sport, user_equipment)
        tt = target_type.value
        total_sec = max(900, int(round(duration_hours * 3600)))
        if kind == "opener":
            title = t(lang, "raceWeek.opener.name", sport=sport_text(lang, sport, "title"))
            desc = t(lang, "raceWeek.opener.description")
            steps = [WorkoutStep("warmup", 900, t(lang, "step.easyWarmup"), 50, 70, tt)]
            for i in range(3):
                steps.append(WorkoutStep("interval", 60, t(lang, "step.racePaceEffort", n=i + 1, total=3), 95, 105, tt))
                steps.append(WorkoutStep("recovery", 180, t(lang, "step.easyFloat"), 50, 65, tt))
            steps.append(WorkoutStep("cooldown", max(300, total_sec - sum(st.duration for st in steps)),
                                     t(lang, "step.easySpinDown"), 45, 60, tt))
        elif kind == "shakeout":
            title = t(lang, "raceWeek.shakeout.name", sport=sport_text(lang, sport, "title"))
            desc = t(lang, "raceWeek.shakeout.description")
            steps = [WorkoutStep("warmup", 600, t(lang, "step.easy"), 50, 68, tt)]
            for i in range(3):
                steps.append(WorkoutStep("interval", 20, t(lang, "step.relaxedStride", n=i + 1, total=3), 105, 115, tt))
                steps.append(WorkoutStep("recovery", 100, t(lang, "step.easy"), 50, 65, tt))
            steps.append(WorkoutStep("cooldown", max(120, total_sec - sum(st.duration for st in steps)),
                                     t(lang, "step.easy"), 50, 65, tt))
        else:
            title = t(lang, "raceWeek.race.name", race=race_name)
            desc = t(lang, "raceWeek.race.description")
            if multisport:  # one power/pace range can't describe a swim-bike-run race
                desc += " " + t(lang, "raceWeek.race.multisport")
                steps = [WorkoutStep("interval", total_sec, race_name, None, None, tt,
                                     notes=t(lang, "notes.raceEffort"))]
            else:
                steps = [WorkoutStep("interval", total_sec, race_name, 85, 100, tt, notes=t(lang, "notes.raceEffort"))]
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
        target_type: TargetType = TargetType.POWER,
        lang: str = "en",
    ) -> Dict[str, Any]:
        """
        Generates a standardized post-deload benchmark test session (FTP Test, 5K Time Trial, CSS Test)
        to calibrate threshold metrics and update training zones.
        """
        total_sec = max(2400, int(round(duration_hours * 3600)))
        steps: List[WorkoutStep] = []
        tt = target_type.value

        def step(kind: str, seconds: int, key: str, low: int, high: int, notes: Optional[str] = None, **params):
            steps.append(WorkoutStep(kind, seconds, t(lang, key, **params), low, high, tt,
                                     notes=t(lang, notes) if notes else None))

        if sport == "cycling":
            test = "cycling"
            step("warmup", 900, "benchmark.cycling.step.warmup", 50, 75)
            for i in range(3):
                step("interval", 60, "benchmark.cycling.step.opener", 100, 105, n=i + 1, total=3)
                step("recovery", 60, "benchmark.cycling.step.easySpin", 45, 55)
            step("recovery", 300, "benchmark.cycling.step.preTest", 45, 55)
            step("interval", 1200, "benchmark.cycling.step.test", 100, 115, notes="benchmark.cycling.notes.test")
            rem = max(300, total_sec - sum(s.duration for s in steps))
            step("cooldown", rem, "step.easySpinDown", 40, 50)

        elif sport == "running":
            test = "running"
            step("warmup", 900, "benchmark.running.step.warmup", 50, 65)
            for i in range(4):
                step("interval", 25, "benchmark.running.step.strides", 105, 120, n=i + 1, total=4)
                step("recovery", 35, "benchmark.running.step.walk", 40, 50)
            step("recovery", 180, "benchmark.running.step.preTest", 40, 50)
            step("interval", 1200, "benchmark.running.step.test", 98, 105, notes="benchmark.running.notes.test")
            rem = max(300, total_sec - sum(s.duration for s in steps))
            step("cooldown", rem, "benchmark.running.step.cooldown", 40, 50)

        elif sport == "swimming":
            test = "swimming"
            step("warmup", 600, "benchmark.swimming.step.warmup", 50, 65)
            step("interval", 420, "benchmark.swimming.step.tt400", 95, 105)
            step("recovery", 360, "benchmark.swimming.step.recovery", 40, 50)
            step("interval", 210, "benchmark.swimming.step.tt200", 105, 115)
            rem = max(300, total_sec - sum(s.duration for s in steps))
            step("cooldown", rem, "benchmark.swimming.step.cooldown", 40, 50)

        else:
            test = "other"
            step("warmup", 600, "benchmark.other.step.warmup", 50, 70)
            step("interval", 1200, "benchmark.other.step.test", 95, 105)
            rem = max(300, total_sec - sum(s.duration for s in steps))
            step("cooldown", rem, "step.coolDown", 40, 50)

        title = t(lang, f"benchmark.{test}.name", sport=sport_text(lang, sport, "title"))
        desc = t(lang, f"benchmark.{test}.description")
        cls._normalize_step_durations(steps, total_sec)

        return {
            "name": title,
            "descriptions": {"structured": desc, "mix": desc, "non_structured": desc},
            "description": desc,
            "steps": [s.to_dict() for s in steps],
            "targetType": tt,
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
