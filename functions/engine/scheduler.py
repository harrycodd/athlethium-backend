"""
Daily Training Scheduler & Intensity Orchestrator.
Determines daily workout prescription, sport rotation, and intensity distribution.
"""

import uuid
import datetime
from typing import Dict, Any, List, Optional
from core.models import UserProfile, WorkoutDoc, TrainingPhase, TargetType
from core.config import TSS_MULTIPLIER_MAP
from engine.physiology import PhysiologyEngine
from engine.periodization import PeriodizationEngine
from engine.guardrails import GuardrailEngine
from generators.endurance import EnduranceGenerator
from generators.strength import StrengthGenerator
from generators.mobility import MobilityGenerator


class TrainingScheduler:
    """
    Master scheduler implementing Polarized 80/20 periodization.
    """

    @classmethod
    def schedule_day(
        cls,
        user_profile: UserProfile,
        target_date: datetime.date,
        user_id: Optional[str] = None
    ) -> WorkoutDoc:
        uid = user_id or user_profile.uid
        date_str = target_date.strftime("%Y-%m-%d")
        day_name = target_date.strftime("%A")

        # 1. Resolve Available Hours for today
        available_hours = cls._resolve_daily_hours(user_profile, target_date)
        if available_hours < 0.4:
            return cls._create_rest_workout(uid, date_str, "Rest Day (Zero/Minimal Time Available)")

        # 4. Resolve Periodization Phase & Mesocycle Week
        phase, days_to_goal = PeriodizationEngine.resolve_training_phase(user_profile.goal, target_date)
        rel_week, is_recovery_week, vol_mult = PeriodizationEngine.resolve_mesocycle_week(
            target_date, user_profile.intensity_weeks
        )

        # 5. Check for Post-Deload Benchmark Testing
        is_benchmark, benchmark_sport = cls._resolve_benchmark_test(
            user_profile=user_profile,
            target_date=target_date,
            rel_week=rel_week,
            is_recovery_week=is_recovery_week,
            day_name=day_name
        )

        # 6. Analyze Recent History
        recent_intensities = cls._get_recent_intensities(user_profile)
        num_hard_days_recent = sum(1 for i in recent_intensities[-6:] if i >= 4)

        # 7. Resolve Sport
        sport = benchmark_sport if is_benchmark and benchmark_sport else cls._select_sport_for_day(user_profile, day_name)

        # 8. Determine Intensity & Duration based on Periodization and Athlete State
        tsb = user_profile.ctl - user_profile.atl
        if is_benchmark:
            raw_intensity = 5
            raw_duration = min(available_hours, 1.25)
        else:
            raw_intensity, raw_duration = cls._determine_intensity_and_duration(
                sport=sport,
                day_name=day_name,
                available_hours=available_hours,
                phase=phase,
                is_recovery_week=is_recovery_week,
                tsb=tsb,
                num_hard_days_recent=num_hard_days_recent,
                vol_mult=vol_mult
            )

        # 9. Apply Physiological Safety Guardrails
        safe_intensity, safe_duration, clamp_reason = GuardrailEngine.apply_safety_clamps(
            user_profile=user_profile,
            requested_intensity=raw_intensity,
            requested_duration=raw_duration,
            recent_intensities=recent_intensities
        )

        if safe_intensity <= 0:
            return cls._create_rest_workout(uid, date_str, clamp_reason or "Rest & Physiological Recovery")

        # 10. Generate Structured Steps via Domain Generators
        if is_benchmark and sport in ["cycling", "running", "swimming"]:
            workout_payload = EnduranceGenerator.generate_benchmark_workout(
                sport=sport,
                duration_hours=safe_duration,
                interval_style=user_profile.interval_type
            )
        else:
            workout_payload = cls._generate_steps_for_sport(
                sport=sport,
                intensity=safe_intensity,
                duration_hours=safe_duration,
                user_profile=user_profile
            )

        # 11. Build Rich Scientific Coaching Description
        coaching_notes = cls._build_coaching_notes(
            sport=sport,
            intensity=safe_intensity,
            phase=phase,
            is_recovery_week=is_recovery_week,
            clamp_reason=clamp_reason,
            is_benchmark=is_benchmark
        )

        session_desc = workout_payload.get("description", "").strip()
        if session_desc and coaching_notes:
            full_description = f"{session_desc}\n\n{coaching_notes}"
        else:
            full_description = session_desc or coaching_notes

        is_strength_or_mobility = sport.lower() in ["strength", "stretching", "yoga", "rest"]
        estimated_tss = 0.0 if is_strength_or_mobility else PhysiologyEngine.estimate_session_tss(safe_intensity, safe_duration, sport)
        total_time_sec = int(round(safe_duration * 3600))
        exec_tips = "Focus on form, controlled eccentric tempo, and full range of motion." if is_strength_or_mobility else f"Focus on consistent execution. Target intensity: Zone {safe_intensity}."

        return WorkoutDoc(
            workout_id=f"plan_{uid}_{date_str}",
            user_id=uid,
            date=date_str,
            name=workout_payload.get("name", f"{sport.capitalize()} Session"),
            sport=sport,
            intensity=None if is_strength_or_mobility else safe_intensity,
            time=total_time_sec,
            planned_time=total_time_sec,
            tss=estimated_tss,
            planned_tss=estimated_tss,
            target_type=workout_payload.get("targetType", "time"),
            description=full_description,
            steps=workout_payload.get("steps", []),
            coach_rationale=coaching_notes,
            execution_tips=exec_tips
        )

    @classmethod
    def _resolve_daily_hours(cls, user_profile: UserProfile, target_date: datetime.date) -> float:
        date_str = target_date.strftime("%Y-%m-%d")
        day_name = target_date.strftime("%A")

        # 1. Date override
        if date_str in user_profile.daily_hours_overrides:
            return float(user_profile.daily_hours_overrides[date_str])

        # 2. Day-of-week max hours
        if day_name in user_profile.daily_max_hours:
            return float(user_profile.daily_max_hours[day_name])

        # 3. Default fallback
        return float(user_profile.daily_available_hours)

    @classmethod
    def _select_sport_for_day(cls, user_profile: UserProfile, day_name: str) -> str:
        focused = user_profile.focused_sports or ["cycling"]
        all_sports = user_profile.sports or focused

        # If only one sport active
        if len(all_sports) == 1:
            return all_sports[0]

        # Monday is typically Mobility / Strength / Active Recovery
        if day_name == "Monday":
            if "stretching" in all_sports:
                return "stretching"
            elif "strength" in all_sports:
                return "strength"
            return focused[0]

        # Wednesday / Friday: Alternate focused sports or cross-training
        if day_name in ["Wednesday", "Friday"]:
            if len(focused) > 1:
                secondary = focused[1] if day_name == "Wednesday" else (focused[2] if len(focused) > 2 else focused[0])
                return secondary
            secondary_sports = [s for s in all_sports if s not in focused]
            if secondary_sports:
                idx = 0 if day_name == "Wednesday" else min(1, len(secondary_sports) - 1)
                return secondary_sports[idx]

        # Sunday: Strength, Mobility or secondary endurance
        if day_name == "Sunday":
            if "strength" in all_sports and "strength" not in focused:
                return "strength"
            if len(focused) > 1:
                return focused[-1]

        # Primary quality interval days (Tuesday, Thursday, Saturday)
        return focused[0]

    @classmethod
    def _determine_intensity_and_duration(
        cls,
        sport: str,
        day_name: str,
        available_hours: float,
        phase: TrainingPhase,
        is_recovery_week: bool,
        tsb: float,
        num_hard_days_recent: int,
        vol_mult: float
    ) -> (int, float):
        """
        Determines intensity zone (1-7) and duration based on weekly rhythm and form.
        """
        if sport in ["strength", "yoga", "stretching"]:
            duration = min(available_hours, 1.0)
            return (2 if sport == "strength" else 1), duration

        # Race Day
        if phase == TrainingPhase.RACE:
            return 7, min(available_hours, 2.0)

        # Taper Phase (High intensity sharpness, reduced volume)
        if phase == TrainingPhase.TAPER:
            if day_name in ["Tuesday", "Thursday"] and num_hard_days_recent < 2:
                return 5, min(available_hours, 1.0 * vol_mult)  # Short VO2 Max sharpness
            elif day_name in ["Monday", "Friday"]:
                return 1, min(available_hours, 0.75)  # Active Recovery
            else:
                return 2, min(available_hours, 1.25 * vol_mult)  # Easy Aerobic

        # Deload / Recovery Week
        if is_recovery_week:
            if day_name in ["Tuesday", "Thursday"] and tsb >= 0:
                return 3, min(available_hours, 1.25 * vol_mult)  # Light Tempo
            elif day_name in ["Monday", "Friday"]:
                return 1, min(available_hours, 0.75)  # Easy Recovery
            else:
                return 2, min(available_hours, 1.5 * vol_mult)  # Aerobic Base

        # Regular Loading Week (Standard Polarized Rhythm):
        # - Tuesday: High Intensity Interval Day (Zone 5 VO2 Max or Zone 4 Threshold)
        # - Thursday: Tempo / Threshold (Zone 3/4)
        # - Saturday: Long Aerobic Endurance (Zone 2)
        # - Sunday: Moderate Aerobic Base (Zone 2) or Strength
        # - Wednesday / Friday: Steady Base (Zone 2)
        # - Monday: Active Recovery (Zone 1) or Rest

        if day_name == "Tuesday":
            if tsb >= -15 and num_hard_days_recent < 2:
                intensity = 5 if phase in [TrainingPhase.BUILD, TrainingPhase.PEAK] else 4
                duration = min(available_hours, 1.5 * vol_mult)
                return intensity, duration
            else:
                return 2, min(available_hours, 1.5 * vol_mult)

        elif day_name == "Thursday":
            if tsb >= -10 and num_hard_days_recent < 2:
                return 4, min(available_hours, 1.5 * vol_mult)
            else:
                return 3, min(available_hours, 1.5 * vol_mult)

        elif day_name == "Saturday":
            # Weekend long endurance session
            return 2, min(available_hours, 3.0 * vol_mult)

        elif day_name == "Sunday":
            return 2, min(available_hours, 2.0 * vol_mult)

        elif day_name == "Monday":
            return 1, min(available_hours, 1.0)

        else:  # Wednesday / Friday
            return 2, min(available_hours, 1.5 * vol_mult)

    @classmethod
    def _generate_steps_for_sport(
        cls,
        sport: str,
        intensity: int,
        duration_hours: float,
        user_profile: UserProfile
    ) -> Dict[str, Any]:
        # Extract target anatomical focus from goal notes if present
        anatomical_focus = "full"
        if user_profile.goal and user_profile.goal.notes:
            notes_lower = user_profile.goal.notes.lower()
            if "target area: core" in notes_lower or "core" in notes_lower:
                anatomical_focus = "core"
            elif "target area: lower" in notes_lower or "legs" in notes_lower or "lower body" in notes_lower:
                anatomical_focus = "lower"
            elif "target area: upper" in notes_lower or "upper body" in notes_lower:
                anatomical_focus = "upper"

        if sport == "strength":
            dur_mins = int(duration_hours * 60)
            return StrengthGenerator.generate(
                focus=anatomical_focus,
                duration_minutes=dur_mins,
                difficulty=min(3, max(1, intensity)),
                user_equipment=user_profile.equipment
            )
        elif sport in ["yoga", "stretching"]:
            dur_mins = int(duration_hours * 60)
            return MobilityGenerator.generate(
                focus=anatomical_focus,
                duration_minutes=dur_mins
            )
        else:
            # Cycling, running, swimming
            return EnduranceGenerator.generate(
                sport=sport,
                duration_hours=duration_hours,
                intensity=intensity,
                user_equipment=user_profile.equipment,
                interval_style=user_profile.interval_type
            )


    @classmethod
    def _resolve_benchmark_test(
        cls,
        user_profile: UserProfile,
        target_date: datetime.date,
        rel_week: int,
        is_recovery_week: bool,
        day_name: str
    ) -> (bool, Optional[str]):
        """
        Determines whether today should be a benchmark assessment session.
        Scheduled on the first key training day(s) immediately following a deload week (Week 1 of mesocycle).
        Supports testing up to 3 main focused sports distributed based on athlete fitness level (CTL).
        """
        # Benchmark testing occurs on Week 1 of a loading mesocycle (first week after deload)
        if is_recovery_week or rel_week != 1:
            return False, None

        focused = [s for s in (user_profile.focused_sports or ["cycling"]) if s in ["cycling", "running", "swimming"]][:3]
        if not focused:
            return False, None

        num_focuses = len(focused)
        is_high_fitness = user_profile.ctl >= 70 or (user_profile.fitness_level in ["advanced", "elite"])

        if is_high_fitness:
            # High capacity athlete: Can test primary on Tuesday, secondary on Thursday, tertiary on Saturday
            if day_name == "Tuesday":
                return True, focused[0]
            elif day_name == "Thursday" and num_focuses >= 2:
                return True, focused[1]
            elif day_name == "Saturday" and num_focuses >= 3:
                return True, focused[2]
        else:
            # Intermediate / Beginner: Separate tests with full recovery in between
            if day_name == "Tuesday":
                return True, focused[0]
            elif day_name == "Saturday" and num_focuses >= 2:
                return True, focused[1]
            elif day_name == "Thursday" and num_focuses >= 3 and user_profile.ctl >= 45:
                return True, focused[2]

        return False, None

    @classmethod
    def _build_coaching_notes(
        cls,
        sport: str,
        intensity: int,
        phase: TrainingPhase,
        is_recovery_week: bool,
        clamp_reason: Optional[str],
        is_benchmark: bool = False
    ) -> str:
        if clamp_reason:
            return f"Adaptive Guardrail: {clamp_reason}"

        if is_benchmark:
            return f"Post-Deload Benchmark Assessment: Re-test your threshold and power/pace zones following your recovery week to calibrate upcoming training blocks."

        phase_names = {
            TrainingPhase.BASE: "Endurance Block",
            TrainingPhase.BUILD: "Threshold Block",
            TrainingPhase.PEAK: "Peak Block",
            TrainingPhase.TAPER: "Taper Block",
            TrainingPhase.RECOVERY: "Recovery Block",
            TrainingPhase.RACE: "Race Block"
        }
        phase_label = phase_names.get(phase, "Endurance Block")

        if is_recovery_week:
            return f"Deload Week ({phase_label}): Reduced volume to assimilate previous training stress and restore neuromuscular freshness."

        if intensity == 5:
            return f"High-Intensity Stimulus ({phase_label}): Targeted VO2 Max power intervals to raise maximum aerobic ceiling and cardiac stroke volume."
        elif intensity == 4:
            return f"Threshold Development ({phase_label}): Sustained efforts right at lactate threshold to elevate sustainable race pace."
        elif intensity == 3:
            return f"Sweet Spot Progression ({phase_label}): High training density stimulus balancing aerobic stimulus with rapid recovery."
        elif intensity == 2:
            return f"Aerobic Base Building ({phase_label}): Zone 2 mitochondrial stimulus developing endurance efficiency and lipid metabolism."
        else:
            return f"Active Recovery ({phase_label}): Light regenerative effort to increase systemic blood circulation without adding fatigue."

    @classmethod
    def _get_recent_intensities(cls, user_profile: UserProfile) -> List[int]:
        # Extract recent intensities from history if available
        intensities = []
        for sport_data in user_profile.history.values():
            if "focus" in sport_data:
                intensities.extend([f for f in sport_data["focus"] if f > 0])
        return intensities[-7:] if intensities else []

    @classmethod
    def _create_rest_workout(cls, user_id: str, date_str: str, reason: str) -> WorkoutDoc:
        return WorkoutDoc(
            workout_id=f"plan_{user_id}_{date_str}",
            user_id=user_id,
            date=date_str,
            name="Rest & Recovery Day",
            sport="rest",
            intensity=-1,
            time=0,
            planned_time=0,
            tss=0.0,
            planned_tss=0.0,
            target_type="time",
            description=f"Complete Rest Day: {reason}. Allow physiological adaptations to take place.",
            steps=[],
            coach_rationale=reason
        )
