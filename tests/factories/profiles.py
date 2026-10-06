"""
Test data factories for athletes.

Two shapes are needed:
- `make_profile(...)`      -> engine-level `UserProfile` dataclass (pure unit tests)
- `make_profile_doc(...)`  -> raw Firestore `users/{uid}` document, as the setup wizard writes it
"""

import copy
from typing import Any, Dict, Optional

from core.models import Goal, UserProfile

DEFAULT_DAILY_MAX_HOURS = {
    "Monday": 1.0,
    "Tuesday": 1.5,
    "Wednesday": 1.0,
    "Thursday": 1.5,
    "Friday": 1.0,
    "Saturday": 3.0,
    "Sunday": 2.0,
}


def make_goal(date: Optional[str] = "2026-11-29", sports=None, **overrides) -> Goal:
    return Goal(
        name=overrides.pop("name", "Target Event"),
        date=date,
        type=overrides.pop("type", "event"),
        sports=sports or ["cycling"],
        **overrides,
    )


def make_profile(uid: str = "athlete-1", **overrides) -> UserProfile:
    """A wizard-completed, moderately trained cyclist who also runs. Override anything."""
    fields: Dict[str, Any] = dict(
        uid=uid,
        display_name="Test Athlete",
        wizard_completed=True,
        ctl=50.0,
        atl=45.0,
        weekly_hours=10.0,
        sports=["cycling", "running"],
        focused_sports=["cycling"],
        equipment=["bodyweight", "power_meter"],
        intensity_weeks=3,
        ftp=250.0,
        ftp_cycling=250.0,
        fthr=165.0,
        daily_max_hours=dict(DEFAULT_DAILY_MAX_HOURS),
        goal=None,
    )
    fields.update(overrides)
    return UserProfile(**fields)


_BASE_DOC: Dict[str, Any] = {
    "displayName": "Test Athlete",
    "units": "Metric",
    "weekly_hours": 10,
    "activities": {"running": True, "cycling": True, "swimming": False, "strength": False, "stretching": False},
    "mainFocus": {"running": False, "cycling": True, "swimming": False, "strength": False, "stretching": False},
    "trainingGoalType": "Race",
    "goal": {"name": "Autumn Sportive", "date": "2026-11-29", "type": "Event", "sports": ["cycling"]},
    "dailyMaxHours": dict(DEFAULT_DAILY_MAX_HOURS),
    "equipmentToggles": {"dumbbells": True},
    "wizardCompleted": True,
    "ftp": 250,
    "ftpCycling": 250,
    "fthr": 165,
    "ctl": 50,
    "atl": 45,
}


def make_profile_doc(**overrides) -> Dict[str, Any]:
    """A valid setup-wizard payload / users document. Pass key=None to drop a field."""
    doc = copy.deepcopy(_BASE_DOC)
    for k, v in overrides.items():
        if v is None:
            doc.pop(k, None)
        else:
            doc[k] = v
    return doc
