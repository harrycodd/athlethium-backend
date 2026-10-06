"""
Daily Training Scheduler.

Turns one day of the week plan (engine.planner) into a structured, athlete-specific workout:
steps from the generators, targets in the athlete's own watts / bpm / pace, TSS from the steps,
and day-of safety guardrails (injury, illness, deep fatigue).
"""

import dataclasses
import datetime
from typing import Optional

from core.models import TargetType, TrainingPhase, UserProfile, WorkoutDoc
from engine.guardrails import GuardrailEngine
from engine.periodization import WeekType
from engine.physiology import PhysiologyEngine
from engine.planner import Kind, PlannedSession, WeekPlan, WeekPlanner
from engine.sessions import build_payload, payload_tss
from engine.zones import apply_athlete_targets

ENDURANCE = ("cycling", "running", "swimming")
GUARDRAIL_HORIZON_DAYS = 7

WEEK_LABELS = {
    WeekType.LOAD: "Load week",
    WeekType.RECOVERY: "Recovery week",
    WeekType.TAPER: "Taper week",
    WeekType.RACE: "Race week",
    WeekType.POST_RACE: "Post-race recovery week",
}
PHASE_LABELS = {
    TrainingPhase.BASE: "Base",
    TrainingPhase.BUILD: "Build",
    TrainingPhase.PEAK: "Peak",
    TrainingPhase.TAPER: "Taper",
    TrainingPhase.RACE: "Race",
    TrainingPhase.RECOVERY: "Recovery",
}
SESSION_PURPOSE = {
    Kind.EASY: "Aerobic base: conversational Zone 2. Most of your training lives here.",
    Kind.LONG: "Long aerobic session: steady Zone 2 for durability and fat oxidation. Fuel as you would on race day.",
    Kind.RECOVERY: "Recovery: very easy Zone 1 the day after a key session. Keep it genuinely easy.",
    Kind.STRENGTH: "Strength: supports injury resistance and power transfer. Kept away from the day before a hard session.",
    Kind.MOBILITY: "Mobility on a rest day.",
    Kind.BENCHMARK: "Benchmark test: re-measures your threshold so every target stays personal to you.",
    Kind.OPENER: "Race opener three days out: short race-pace efforts to stay sharp without fatigue.",
    Kind.SHAKEOUT: "Pre-race shake-out: short and easy with a few strides.",
    Kind.RACE: "Race day.",
}


class TrainingScheduler:

    @classmethod
    def schedule_day(
        cls,
        user_profile: UserProfile,
        target_date: datetime.date,
        user_id: Optional[str] = None,
        as_of: Optional[datetime.date] = None,
    ) -> WorkoutDoc:
        """
        `as_of` is the athlete's "today" (plans ramp from there). Defaults to target_date, which
        plans the week stand-alone from the athlete's current fitness.
        """
        uid = user_id or user_profile.uid
        date_str = target_date.strftime("%Y-%m-%d")
        week = WeekPlanner.plan_week(user_profile, target_date, as_of=as_of)
        session = week.session_on(target_date)

        if session.kind == Kind.REST:
            return cls._rest(uid, date_str, session.reason or "Planned rest day", week)

        intensity, hours, clamp_reason = session.intensity, session.hours, None
        # Day-of guardrails use today's fatigue, so they only apply to the coming week; later weeks
        # are planned on the assumption the athlete follows the plan (and get re-checked then).
        near_term = as_of is None or (target_date - as_of).days < GUARDRAIL_HORIZON_DAYS
        if session.sport in ENDURANCE and session.kind != Kind.RACE and near_term:
            projected = cls._project_fitness(user_profile, target_date)
            intensity, hours, clamp_reason = GuardrailEngine.apply_safety_clamps(
                user_profile=projected, requested_intensity=session.intensity,
                requested_duration=session.hours, recent_intensities=[],
            )
            if intensity <= 0:
                return cls._rest(uid, date_str, clamp_reason or "Rest & recovery", week)
            if clamp_reason:
                session = dataclasses.replace(session, kind=Kind.RECOVERY if intensity == 1 else Kind.EASY,
                                              intensity=intensity, hours=hours, style=None)

        payload = build_payload(session, user_profile)
        steps = payload.get("steps", [])
        has_targets = False
        if session.sport in ENDURANCE:
            has_targets = apply_athlete_targets(steps, session.sport, payload.get("targetType", "time"), user_profile)
        tss = payload_tss(session, payload)

        notes = cls._coaching_notes(session, week, clamp_reason, has_targets)
        description = "\n\n".join(p for p in (payload.get("description", "").strip(), notes) if p)
        total_time_sec = sum(st["duration"] for st in steps) if steps else int(round(session.hours * 3600))
        is_endurance = session.sport in ENDURANCE

        return WorkoutDoc(
            workout_id=f"plan_{uid}_{date_str}",
            user_id=uid,
            date=date_str,
            name=payload.get("name", f"{session.sport.capitalize()} Session"),
            sport=session.sport,
            intensity=session.intensity if is_endurance else None,
            time=total_time_sec,
            planned_time=total_time_sec,
            tss=tss,
            planned_tss=tss,
            target_type=payload.get("targetType", "time"),
            description=description,
            steps=steps,
            event_type="Race" if session.kind == Kind.RACE else "Training",
            coach_rationale=notes,
            execution_tips=("Focus on form, controlled tempo and full range of motion." if not is_endurance
                            else cls._execution_tip(session, has_targets)),
            session_kind=session.kind,
            week_type=week.context.week_type,
        )

    @classmethod
    def _project_fitness(cls, user_profile: UserProfile, target_date: datetime.date) -> UserProfile:
        """Decays stored CTL/ATL across idle days up to the eve of target_date."""
        if not user_profile.metrics_date:
            return user_profile
        try:
            metrics_date = datetime.datetime.strptime(user_profile.metrics_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return user_profile
        ctl, atl = PhysiologyEngine.project_metrics(
            user_profile.ctl, user_profile.atl, metrics_date, target_date - datetime.timedelta(days=1)
        )
        return dataclasses.replace(user_profile, ctl=ctl, atl=atl)

    @staticmethod
    def _coaching_notes(session: PlannedSession, week: WeekPlan, clamp_reason: Optional[str], has_targets: bool) -> str:
        ctx = week.context
        header = f"{WEEK_LABELS.get(ctx.week_type, 'Training week')} ({PHASE_LABELS.get(ctx.phase, 'Base')} phase)"
        if week.comeback:
            header += ": easing back in after time off, aerobic only this week"
        if ctx.weeks_to_goal:
            header += f", {ctx.weeks_to_goal} week{'s' if ctx.weeks_to_goal != 1 else ''} to your event"
        if clamp_reason:
            body = f"Adaptive Guardrail: {clamp_reason}"
        elif session.kind == Kind.HARD:
            body = ("Key session: VO2max intervals to raise your aerobic ceiling." if session.style == "vo2"
                    else "Key session: threshold intervals to lift your sustainable pace.")
        else:
            body = SESSION_PURPOSE.get(session.kind, "")
        if session.sport in ENDURANCE and not has_targets and session.kind != Kind.RACE:
            body += " No threshold on file for this sport yet, so targets are % of threshold / feel (RPE)."
        return f"{header}. {body}".strip()

    @staticmethod
    def _execution_tip(session: PlannedSession, has_targets: bool) -> str:
        if session.kind in (Kind.EASY, Kind.LONG, Kind.RECOVERY):
            return "Stay easy enough to talk in full sentences. Resist the urge to push."
        if session.kind == Kind.HARD:
            return "Hit the targets on every rep; stop the set if form or pace falls apart."
        return "Follow the step targets." if has_targets else "Go by feel (RPE)."

    @classmethod
    def _rest(cls, user_id: str, date_str: str, reason: str, week: Optional[WeekPlan] = None) -> WorkoutDoc:
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
            target_type=TargetType.TIME.value,
            description=f"Complete Rest Day: {reason}. Allow physiological adaptations to take place.",
            steps=[],
            coach_rationale=reason,
            session_kind=Kind.REST,
            week_type=week.context.week_type if week else None,
        )
