"""
Builds the concrete workout (steps + TSS) for a planned session. Shared by the planner (to
measure weekly load exactly as the athlete will see it) and the scheduler (to emit the workout).
"""

from typing import Any, Dict

from core.models import UserProfile
from engine.physiology import PhysiologyEngine
from engine.zones import steps_tss
from generators.endurance import EnduranceGenerator
from generators.mobility import MobilityGenerator
from generators.strength import StrengthGenerator
from i18n import t

ENDURANCE = ("cycling", "running", "swimming")
LEVELS = {"beginner": 0, "intermediate": 1, "advanced": 2, "elite": 3, "pro": 4}


def anatomical_focus(profile: UserProfile) -> str:
    notes = (profile.goal.notes or "").lower() if profile.goal else ""
    if "core" in notes:
        return "core"
    if "legs" in notes or "lower body" in notes or "target area: lower" in notes:
        return "lower"
    if "upper body" in notes or "target area: upper" in notes:
        return "upper"
    return "full"


def build_payload(session, profile: UserProfile) -> Dict[str, Any]:
    kind, lang = session.kind, profile.language
    if kind == "strength":
        return StrengthGenerator.generate(focus=anatomical_focus(profile),
                                          duration_minutes=int(round(session.hours * 60)),
                                          difficulty=2, user_equipment=profile.equipment,
                                          session_date=session.date, sports=profile.sports,
                                          level=profile.fitness_level, lang=lang)
    if kind == "mobility":
        return MobilityGenerator.generate(focus=anatomical_focus(profile),
                                          duration_minutes=int(round(session.hours * 60)),
                                          sports=profile.sports, session_date=session.date, lang=lang)
    if kind == "benchmark":
        return EnduranceGenerator.generate_benchmark_workout(
            sport=session.sport, duration_hours=session.hours, interval_style=profile.interval_type,
            target_type=EnduranceGenerator.resolve_target_type(session.sport, profile.equipment), lang=lang)
    if kind in ("opener", "shakeout", "race"):
        return EnduranceGenerator.generate_race_week_session(
            kind, session.sport, session.hours, profile.equipment,
            race_name=(profile.goal.name if profile.goal else None) or t(lang, "race.defaultName"),
            multisport=bool(profile.goal and len(set(profile.goal.sports or [])) > 1), lang=lang)
    return EnduranceGenerator.generate(sport=session.sport, duration_hours=session.hours,
                                      intensity=session.intensity, user_equipment=profile.equipment,
                                      interval_style=profile.interval_type,
                                      level=LEVELS.get(profile.fitness_level, 1),
                                      # interval sets grow over the 3 weeks of a training block
                                      progression=session.date.toordinal() // 7 % 3,
                                      swim_css_sec=profile.ftp_pace_swimming, lang=lang)


def payload_tss(session, payload: Dict[str, Any]) -> float:
    if session.sport not in ENDURANCE:
        return 0.0
    if payload.get("targetType") == "time":  # no measurable target: estimate from zone and duration
        return PhysiologyEngine.estimate_session_tss(session.intensity, session.hours, session.sport)
    return steps_tss(payload.get("steps", []))


def session_tss(session, profile: UserProfile) -> float:
    if session.sport not in ENDURANCE or session.kind == "rest":
        return 0.0
    return payload_tss(session, build_payload(session, profile))
