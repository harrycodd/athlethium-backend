"""
Daily Training Scheduler.

Turns one day of the week plan (engine.planner) into a structured, athlete-specific workout:
steps from the generators, targets in the athlete's own watts / bpm / pace, TSS from the steps,
and day-of safety guardrails (injury, illness, deep fatigue).
"""

import dataclasses
import datetime
from typing import List, Optional

from core.models import TargetType, TrainingPhase, UserProfile, WorkoutDoc
from engine.guardrails import GuardrailEngine
from engine.periodization import WeekType
from engine.physiology import PhysiologyEngine
from engine.planner import Kind, PlannedSession, WeekPlan, WeekPlanner
from engine.sessions import build_payload, payload_tss
from engine.zones import apply_athlete_targets
from i18n import sport_text, t

ENDURANCE = ("cycling", "running", "swimming")
GUARDRAIL_HORIZON_DAYS = 7

# message keys (i18n/messages) for the week type, training phase and session purpose
WEEK_LABELS = {
    WeekType.LOAD: "week.load",
    WeekType.RECOVERY: "week.recovery",
    WeekType.TAPER: "week.taper",
    WeekType.RACE: "week.race",
    WeekType.POST_RACE: "week.postRace",
}
PHASE_LABELS = {
    TrainingPhase.BASE: "phase.base",
    TrainingPhase.BUILD: "phase.build",
    TrainingPhase.PEAK: "phase.peak",
    TrainingPhase.TAPER: "phase.taper",
    TrainingPhase.RACE: "phase.race",
    TrainingPhase.RECOVERY: "phase.recovery",
}
SESSION_PURPOSE = {
    Kind.EASY: "purpose.easy",
    Kind.LONG: "purpose.long",
    Kind.RECOVERY: "purpose.recovery",
    Kind.STRENGTH: "purpose.strength",
    Kind.MOBILITY: "purpose.mobility",
    Kind.BENCHMARK: "purpose.benchmark",
    Kind.OPENER: "purpose.opener",
    Kind.SHAKEOUT: "purpose.shakeout",
    Kind.RACE: "purpose.race",
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
        The day's main workout. `as_of` is the athlete's "today" (plans ramp from there). Defaults
        to target_date, which plans the week stand-alone from the athlete's current fitness.
        """
        return cls.schedule_day_all(user_profile, target_date, user_id, as_of)[0]

    @classmethod
    def schedule_day_all(
        cls,
        user_profile: UserProfile,
        target_date: datetime.date,
        user_id: Optional[str] = None,
        as_of: Optional[datetime.date] = None,
    ) -> List[WorkoutDoc]:
        """Every workout for the day: the main one, plus a second ("pm") session on double days."""
        uid = user_id or user_profile.uid
        week = WeekPlanner.plan_week(user_profile, target_date, as_of=as_of)
        docs = [cls._build_doc(user_profile, session, week, uid, target_date, as_of)
                for session in week.sessions_on(target_date)]
        # a guardrail can turn the main session into rest; then there is no second session either
        return docs[:1] if docs[0].sport == "rest" else docs

    @classmethod
    def _build_doc(cls, user_profile: UserProfile, session: PlannedSession, week: WeekPlan, uid: str,
                   target_date: datetime.date, as_of: Optional[datetime.date]) -> WorkoutDoc:
        date_str = target_date.strftime("%Y-%m-%d")
        workout_id = f"plan_{uid}_{date_str}" + ("_pm" if session.slot == "pm" else "")
        lang = user_profile.language
        if session.kind == Kind.REST:
            return cls._rest(uid, date_str, session.reason or t(lang, "rest.planned"), week, lang)

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
                return cls._rest(uid, date_str, clamp_reason or t(lang, "rest.default"), week, lang)
            if clamp_reason:
                session = dataclasses.replace(session, kind=Kind.RECOVERY if intensity == 1 else Kind.EASY,
                                              intensity=intensity, hours=hours, style=None)

        payload = build_payload(session, user_profile)
        steps = payload.get("steps", [])
        has_targets = False
        if session.sport in ENDURANCE:
            has_targets = apply_athlete_targets(steps, session.sport, payload.get("targetType", "time"), user_profile)
        tss = payload_tss(session, payload)

        notes = cls._coaching_notes(session, week, clamp_reason, has_targets, lang)
        if session.slot == "pm":
            notes += " " + t(lang, "notes.secondSession")
        description = "\n\n".join(p for p in (payload.get("description", "").strip(), notes) if p)
        total_time_sec = sum(st["duration"] for st in steps) if steps else int(round(session.hours * 3600))
        is_endurance = session.sport in ENDURANCE

        return WorkoutDoc(
            workout_id=workout_id,
            user_id=uid,
            date=date_str,
            name=payload.get("name", t(lang, "session.generic.name", sport=sport_text(lang, session.sport, "title"))),
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
            execution_tips=(t(lang, "tips.strength") if not is_endurance
                            else cls._execution_tip(session, has_targets, lang)),
            session_kind=session.kind,
            week_type=week.context.week_type,
            slot=session.slot,
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
    def _coaching_notes(session: PlannedSession, week: WeekPlan, clamp_reason: Optional[str], has_targets: bool,
                        lang: str = "en") -> str:
        ctx = week.context
        header_key = "notes.header" + (".comeback" if week.comeback else "")
        if ctx.weeks_to_goal:
            header_key += ".toEvent.one" if ctx.weeks_to_goal == 1 else ".toEvent.other"
        header = t(lang, header_key, week=t(lang, WEEK_LABELS.get(ctx.week_type, "week.training")),
                   phase=t(lang, PHASE_LABELS.get(ctx.phase, "phase.base")), weeks=ctx.weeks_to_goal)
        if clamp_reason:
            body = t(lang, "notes.guardrail", reason=clamp_reason)
        elif session.kind == Kind.HARD:
            body = t(lang, "purpose.hard.vo2" if session.style == "vo2" else "purpose.hard.threshold")
        else:
            body = t(lang, SESSION_PURPOSE[session.kind]) if session.kind in SESSION_PURPOSE else ""
        if session.sport in ENDURANCE and not has_targets and session.kind != Kind.RACE:
            body += " " + t(lang, "notes.noThreshold")
        return t(lang, "notes.rationale", header=header, body=body).strip()

    @staticmethod
    def _execution_tip(session: PlannedSession, has_targets: bool, lang: str = "en") -> str:
        if session.kind in (Kind.EASY, Kind.LONG, Kind.RECOVERY):
            return t(lang, "tips.easy")
        if session.kind == Kind.HARD:
            return t(lang, "tips.hard")
        return t(lang, "tips.followTargets" if has_targets else "tips.byFeel")

    @classmethod
    def _rest(cls, user_id: str, date_str: str, reason: str, week: Optional[WeekPlan] = None,
              lang: str = "en") -> WorkoutDoc:
        return WorkoutDoc(
            workout_id=f"plan_{user_id}_{date_str}",
            user_id=user_id,
            date=date_str,
            name=t(lang, "rest.name"),
            sport="rest",
            intensity=-1,
            time=0,
            planned_time=0,
            tss=0.0,
            planned_tss=0.0,
            target_type=TargetType.TIME.value,
            description=t(lang, "rest.description", reason=reason),
            steps=[],
            coach_rationale=reason,
            session_kind=Kind.REST,
            week_type=week.context.week_type if week else None,
        )
