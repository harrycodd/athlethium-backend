"""
The athlete's language reaches every piece of generated text.

Real translations come later, so fake catalogs stand in for German:
- "DE:" + the English template: every user-visible string must start with "DE:";
- a strict one that keeps only each template's key and placeholders ("⟦key|{a}|{b}⟧"): once the
  markers are stripped, only parameter values (numbers, times, set labels) may remain. Any
  English word left over is text that was hard-coded or concatenated outside the catalog.

Scenarios cover every session kind, rest days (planned, race week, severe illness), the day-of
guardrail downgrade, double days, comebacks, swims, race week and the "no threshold" note.
"""

import dataclasses
import datetime
import re
import string

import pytest

import i18n
from engine.planner import Kind
from engine.scheduler import TrainingScheduler as T
from i18n.messages import en
from services.activity_stats import exercise_name, logged_set
from services.user_service import UserService
from tests.factories import make_goal, make_profile, make_profile_doc

MON = datetime.date(2026, 10, 5)
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
ROOMY = {d: 2.0 for d in DAYS} | {"Saturday": 4.0}


def _fields(template):
    return sorted({f for _, f, _, _ in string.Formatter().parse(template) if f is not None})


PREFIXED = {k: "DE:" + v for k, v in en.MESSAGES.items()}
STRICT = {k: "⟦" + "|".join([k] + ["{%s}" % f for f in _fields(v)]) + "⟧" for k, v in en.MESSAGES.items()}


def plan(profile, weeks, start=MON, as_of=MON):
    return [doc.to_dict() for i in range(7 * weeks)
            for doc in T.schedule_day_all(profile, start + datetime.timedelta(days=i), as_of=as_of)]


def scenarios():
    """(scenario name, generated workout dicts), all for German-speaking athletes."""
    de = dict(language="de")
    everything = make_profile(uid="de-all", sports=["cycling", "running", "swimming", "strength", "stretching"],
                              focused_sports=["cycling"], daily_max_hours=ROOMY, weekly_hours=12,
                              known_thresholds=["cycling_power"],  # running/swimming: "no threshold" note
                              goal=make_goal("2026-11-29", name="", sports=["cycling"]), **de)
    fatigued = make_profile(uid="de-tired", ctl=40, atl=80, metrics_date="2026-10-04", daily_max_hours=ROOMY, **de)
    elite = make_profile(uid="de-elite", fitness_level="elite", ctl=95, atl=90, weekly_hours=25,
                         sports=["swimming", "cycling", "running"], focused_sports=["swimming"],
                         daily_max_hours={d: 5.0 for d in DAYS}, **de)
    comeback = make_profile(uid="de-back", metrics_date="2026-09-01", ctl=45, atl=20, daily_max_hours=ROOMY,
                            goal=make_goal("2026-12-20", name="", sports=["cycling"]), **de)
    ill = make_profile(uid="de-ill", illness=2, **de)
    multisport = make_profile(uid="de-tri", sports=["swimming", "cycling", "running"], focused_sports=["running"],
                              daily_max_hours=ROOMY, weekly_hours=10, equipment=["bodyweight", "hr_monitor"],
                              goal=make_goal("2026-10-25", name="", sports=["swimming", "cycling", "running"]), **de)
    return [
        ("everything", plan(everything, 10)),
        ("guardrail", [T.schedule_day(fatigued, MON + datetime.timedelta(days=1), as_of=MON).to_dict()]),
        ("doubles", plan(elite, 3)),
        ("comeback", plan(comeback, 1)),
        ("illness", plan(ill, 1)),
        ("multisport race", plan(multisport, 4)),
        ("planned rest", [T.schedule_day(dataclasses.replace(everything, daily_max_hours={d: 0 for d in DAYS}),
                                         MON).to_dict()]),
    ]


def visible_text(doc):
    """Every user-visible string the backend writes into a workout document."""
    yield doc["name"]
    yield doc["description"]
    yield doc["coach_rationale"]
    if doc["execution_tips"] is not None:
        yield doc["execution_tips"]
    for step in doc["steps"]:
        yield step["name"]
        if "notes" in step:
            yield step["notes"]


@pytest.fixture(scope="module")
def generated():
    """Scenario docs generated with each fake German catalog in place."""
    out = {}
    for name, catalog in (("prefixed", PREFIXED), ("strict", STRICT)):
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(i18n.CATALOGS, "de", catalog)
            out[name] = scenarios()
    return out


def test_scenarios_cover_every_kind_of_document(generated):
    docs = [d for _, ds in generated["prefixed"] for d in ds]
    kinds = {d["session_kind"] for d in docs}
    assert kinds >= {Kind.HARD, Kind.EASY, Kind.LONG, Kind.RECOVERY, Kind.STRENGTH, Kind.MOBILITY, Kind.BENCHMARK,
                     Kind.OPENER, Kind.SHAKEOUT, Kind.RACE, Kind.REST}
    assert {d["sport"] for d in docs} >= {"cycling", "running", "swimming", "strength", "stretching", "rest"}
    assert any(d["slot"] == "pm" for d in docs)
    # the strict catalog leaves each message key in the text: check the interesting ones were used
    text = " ".join(t for _, ds in generated["strict"] for d in ds for t in visible_text(d))
    for key in ("notes.guardrail", "notes.noThreshold", "notes.secondSession", "notes.header.comeback.toEvent.other",
                "notes.header.toEvent.one", "rest.planned", "rest.raceWeek", "rest.postRace", "rest.severeIllness",
                "purpose.hard.vo2", "purpose.hard.threshold", "swim.threshold.name", "swim.aerobic.name.pull",
                "swim.recovery.name", "raceWeek.race.name", "raceWeek.race.multisport", "race.defaultName",
                "strength.name.full.variant", "strength.rest.superset", "mobility.name.multisport",
                "mobility.notes.perSide", "tips.strength", "tips.byFeel"):
        assert f"⟦{key}" in text, key
    assert "⟦benchmark." in text and "⟦guardrail." in text


def test_every_visible_string_is_german(generated):
    for scenario, docs in generated["prefixed"]:
        for doc in docs:
            for text in visible_text(doc):
                assert text.startswith("DE:"), (scenario, doc["date"], doc["session_kind"], text)
            # whole documents: names, rationale and steps
            assert doc["name"].startswith("DE:") and doc["coach_rationale"].startswith("DE:")


def test_no_english_outside_the_catalog(generated):
    """Strip the strict catalog's markers: what's left are parameter values, never words."""
    for scenario, docs in generated["strict"]:
        for doc in docs:
            for text in visible_text(doc):
                assert text.startswith("⟦"), (scenario, text)
                leftover = re.sub(r"⟦[\w.]+|[|⟧⟦]", " ", text)
                words = re.findall(r"[A-Za-z]{2,}", leftover)
                assert words == [], (scenario, doc["session_kind"], text, words)


def test_english_athletes_are_unaffected(generated):
    """The German catalog is only used for German athletes."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(i18n.CATALOGS, "de", PREFIXED)
        docs = plan(make_profile(uid="en", daily_max_hours=ROOMY), 1)
    assert not any("DE:" in text for d in docs for text in visible_text(d))


def test_language_from_the_profile_document(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS, "de", PREFIXED)
    profile = UserService.normalize_user_profile("u-de", make_profile_doc(language="de", goal={"date": "2026-11-29"}))
    assert profile.language == "de" and profile.goal.name == "DE:Target Event"
    doc = T.schedule_day(profile, MON + datetime.timedelta(days=1), as_of=MON)
    assert doc.name.startswith("DE:") and doc.coach_rationale.startswith("DE:")


def test_recorded_exercise_names(monkeypatch):
    monkeypatch.setitem(i18n.CATALOGS, "de", PREFIXED)
    assert exercise_name("squat", "de") == "DE:Squat"
    assert exercise_name("unknown", "de") == "DE:Exercise"
    assert exercise_name("weird_lift", "de") == "Weird Lift"  # no name for it: shown as recorded
    assert logged_set("deadlift", 5, 100, None, "de") == {"exercise": "DE:Deadlift", "reps": 5, "weight_kg": 100.0}
    assert exercise_name("squat") == "Squat"
