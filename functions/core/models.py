"""
Core Data Models and Type Definitions for Athlethium Backend.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class TrainingPhase(str, Enum):
    BASE = "base"
    BUILD = "build"
    PEAK = "peak"
    TAPER = "taper"
    RECOVERY = "recovery"
    RACE = "race"


class TargetType(str, Enum):
    POWER = "power"
    HEART_RATE = "heart_rate"
    PACE = "pace"
    REPS = "reps"
    TIME = "time"


@dataclass
class Goal:
    name: str = "General Fitness"
    date: Optional[str] = None
    type: str = "general"
    sports: List[str] = field(default_factory=lambda: ["cycling"])
    target_distance: Optional[float] = None
    target_distance_unit: Optional[str] = None
    target_time: Optional[int] = None  # in seconds
    target_time_string: Optional[str] = None  # e.g. "03:45:00"
    target_pace: Optional[str] = None  # e.g. "5:20 /km"
    notes: Optional[str] = None


@dataclass
class UserProfile:
    uid: str
    ctl: float = 40.0  # Chronic Training Load (Fitness)
    atl: float = 30.0  # Acute Training Load (Fatigue)
    weekly_hours: float = 8.0
    daily_available_hours: float = 1.5
    sports: List[str] = field(default_factory=lambda: ["cycling", "running"])
    focused_sports: List[str] = field(default_factory=lambda: ["cycling"])
    equipment: List[str] = field(default_factory=lambda: ["bodyweight", "power_meter"])
    intensity_weeks: int = 3  # e.g. 3:1 load/deload cycle
    injury: int = 0  # 0=None, 1=Minor, 2=Severe
    illness: int = 0  # 0=None, 1=Minor, 2=Severe
    recovery_metric: int = 3  # 1 (quick) to 3 (standard)
    interval_type: str = "structured"  # structured, mix, non-structured

    # Setup wizard & UI preferences
    display_name: Optional[str] = None
    units: str = "Metric"  # Metric or Imperial
    language: str = "en"  # language of generated text: en, es, fr, de, it, ja (see i18n.SUPPORTED)
    main_focus: Dict[str, bool] = field(default_factory=dict)
    activities: Dict[str, bool] = field(default_factory=dict)
    equipment_toggles: Dict[str, bool] = field(default_factory=dict)
    training_goal_type: str = "General Fitness"
    fitness_level: str = "intermediate"
    sport_percentages: Dict[str, float] = field(default_factory=dict)
    sport_sessions_per_week: Dict[str, int] = field(default_factory=dict)
    wizard_completed: bool = False

    # Threshold metrics
    ftp: float = 200.0
    ftp_cycling: float = 200.0
    ftp_running: float = 250.0
    ftp_pace_running: float = 330.0  # sec/km
    ftp_pace_swimming: float = 110.0  # sec/100m
    fthr: float = 170.0

    # Day-of-week hour limits & overrides
    daily_max_hours: Dict[str, float] = field(default_factory=lambda: {
        "Monday": 1.5,
        "Tuesday": 1.5,
        "Wednesday": 1.5,
        "Thursday": 1.5,
        "Friday": 1.5,
        "Saturday": 2.5,
        "Sunday": 2.5
    })
    daily_hours_overrides: Dict[str, float] = field(default_factory=dict)

    # Date (YYYY-MM-DD) whose end-of-day state `ctl`/`atl` describe; None = unknown
    metrics_date: Optional[str] = None
    # IANA time zone (e.g. "Europe/London") used to decide which calendar day "today" is
    timezone: Optional[str] = None
    # Which thresholds the athlete has actually provided (None = treat all as known).
    # Keys: cycling_power, running_power, running_pace, swim_pace, hr
    known_thresholds: Optional[List[str]] = None
    # Completed endurance load per week, keyed by the week's Monday (YYYY-MM-DD):
    # [hours, tss] or [hours, tss, {sport: hours}].
    # Loaded from workout history at request time (not stored on the profile).
    recent_weeks: Dict[str, List[Any]] = field(default_factory=dict)
    # Sessions completed so far in the current week: [[YYYY-MM-DD, tss], ...] (also request-time only).
    # Lets the planner work from the athlete's state at the start of the week.
    week_to_date: List[List[Any]] = field(default_factory=list)

    # Goal and history
    goal: Optional[Goal] = None
    history: Dict[str, Dict[str, List[float]]] = field(default_factory=dict)
    raw_data: Dict[str, Any] = field(default_factory=dict)



@dataclass
class WorkoutStep:
    type: str  # warmup, interval, recovery, cooldown, exercise
    duration: int  # duration in seconds
    name: str = ""
    target_low: Optional[float] = None
    target_high: Optional[float] = None
    target_type: str = "power"  # power, heart_rate, pace, reps, time
    reps: Optional[int] = None
    sets: Optional[int] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "type": self.type,
            "duration": self.duration,
            "name": self.name,
            "targetType": self.target_type
        }
        if self.target_low is not None:
            d["target_low"] = self.target_low
        if self.target_high is not None:
            d["target_high"] = self.target_high
        if self.reps is not None:
            d["reps"] = self.reps
        if self.sets is not None:
            d["sets"] = self.sets
        if self.notes:
            d["notes"] = self.notes
        return d


@dataclass
class TrainingPrescription:
    sport: str
    intensity: int
    duration_hours: float
    focus_name: str
    title: str
    description: str
    coaching_tips: str
    estimated_tss: float
    target_type: TargetType
    steps: List[WorkoutStep] = field(default_factory=list)


@dataclass
class WorkoutDoc:
    workout_id: str
    user_id: str
    date: str  # YYYY-MM-DD
    name: str
    sport: str
    intensity: int
    time: int  # Planned time in seconds
    planned_time: int
    tss: float
    planned_tss: float
    target_type: str
    description: str
    steps: List[Dict[str, Any]]
    completed: bool = False
    status: str = "planned"
    event_type: str = "Training"
    tss_type: str = "estimated"
    coach_rationale: Optional[str] = None
    execution_tips: Optional[str] = None
    session_kind: Optional[str] = None
    week_type: Optional[str] = None
    slot: str = "am"  # "pm" = second session of a double day

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workoutId": self.workout_id,
            "userId": self.user_id,
            "date": self.date,
            "name": self.name,
            "sport": self.sport,
            "intensity": self.intensity,
            "time": self.time,
            "plannedTime": self.planned_time,
            "tss": self.tss,
            "plannedTss": self.planned_tss,
            "targetType": self.target_type,
            "description": self.description,
            "steps": self.steps,
            "completed": self.completed,
            "status": self.status,
            "event_type": self.event_type,
            "tss_type": self.tss_type,
            "coach_rationale": self.coach_rationale,
            "execution_tips": self.execution_tips,
            "session_kind": self.session_kind,
            "week_type": self.week_type,
            "slot": self.slot,
        }
