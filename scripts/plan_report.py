"""
Golden-athlete plan report: generates an 8-week plan for each profile in tests/data/golden and
writes a coach-readable Markdown report (docs/golden-plans.md).

    functions/venv/bin/python scripts/plan_report.py            # regenerate the report
    functions/venv/bin/python scripts/plan_report.py --check    # exit 1 if the committed report is stale

Pure engine code only: no Firebase, no network.
"""

import argparse
import datetime
import json
import os
import sys
from collections import Counter
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "functions"))

from engine.zones import zone_seconds  # noqa: E402
from engine.scheduler import TrainingScheduler  # noqa: E402
from services.user_service import UserService  # noqa: E402

GOLDEN_DIR = os.path.join(ROOT, "tests", "data", "golden")
REPORT_PATH = os.path.join(ROOT, "docs", "golden-plans.md")
PLAN_START = datetime.date(2026, 10, 5)  # Monday; also each athlete's "today"
WEEKS = 8
ORDER = ["beginner", "returning", "time_crunched", "elite", "injured_comeback"]
WEEK_NAMES = {"load": "Load", "recovery": "Recovery", "taper": "Taper", "race": "Race", "post_race": "Post-race"}
KIND_NAMES = {"easy": "Easy", "long": "Long", "recovery": "Recovery", "hard": "KEY", "benchmark": "TEST",
              "opener": "Opener", "shakeout": "Shake-out", "race": "RACE", "strength": "Strength",
              "mobility": "Mobility", "rest": "Rest"}


def load_profiles() -> List[Tuple[str, str, object]]:
    out = []
    for key in ORDER:
        with open(os.path.join(GOLDEN_DIR, f"{key}.json")) as f:
            raw = json.load(f)
        about = raw.pop("_about", "")
        out.append((key, about, UserService.normalize_user_profile(f"golden-{key}", raw)))
    return out


def generate(profile) -> List[Dict]:
    """Every workout over the plan (two on double days), in date order."""
    return [doc.to_dict() for i in range(7 * WEEKS)
            for doc in TrainingScheduler.schedule_day_all(profile, PLAN_START + datetime.timedelta(days=i),
                                                         as_of=PLAN_START)]


def _fmt_dur(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} s"
    minutes = round(seconds / 60)
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def _fmt_target(step: Dict) -> str:
    rng = step.get("target_range")
    if not rng:
        if step.get("target_low") is not None:
            return f"{step['target_low']:.0f}-{step['target_high']:.0f}% thr (RPE)"
        return ""
    if rng["unit"] in ("s/km", "s/100m"):
        def pace(s):
            return f"{int(s) // 60}:{int(s) % 60:02d}"
        return f"{pace(rng['min'])}-{pace(rng['max'])} /{rng['unit'].split('/')[1]}"
    return f"{rng['min']}-{rng['max']} {rng['unit']}"


def main_set(doc: Dict) -> str:
    """Human summary of the work, e.g. '4 x 8 min @ 240-255 W'."""
    steps = doc.get("steps", [])
    kind = doc.get("session_kind")
    if not steps:
        return ""
    if kind in ("strength", "mobility"):
        names = [s["name"] for s in steps if s["type"] == "exercise"]
        return ", ".join(names[:4]) + (" ..." if len(names) > 4 else "")
    work = [s for s in steps if s["type"] == "interval" and (s.get("target_low") or 0) >= 90]
    if kind in ("hard", "benchmark", "opener", "shakeout") and work:
        groups = Counter((s["duration"], _fmt_target(s)) for s in work)
        return "; ".join(f"{n} x {_fmt_dur(d)} @ {t}" for (d, t), n in groups.items())
    main = max(steps, key=lambda s: s["duration"])
    return f"{_fmt_dur(doc['time'])} @ {_fmt_target(main)}" if _fmt_target(main) else _fmt_dur(doc["time"])


def week_rows(docs: List[Dict]) -> List[Dict]:
    rows = []
    for w in range(WEEKS):
        start = PLAN_START + datetime.timedelta(weeks=w)
        week = [d for d in docs if 0 <= (datetime.date.fromisoformat(d["date"]) - start).days < 7]
        endurance = [d for d in week if d["sport"] in ("cycling", "running", "swimming") and d["event_type"] != "Race"]
        hours = sum(d["time"] for d in endurance) / 3600
        hard_h = sum(d["time"] for d in endurance if (d["intensity"] or 0) >= 4) / 3600
        zs = Counter()
        for d in endurance:
            zs.update(zone_seconds(d["steps"]))
        zone_total = sum(zs.values()) or 1
        rows.append({
            "week": w + 1,
            "start": week[0]["date"],
            "type": WEEK_NAMES.get(week[0]["week_type"], week[0]["week_type"] or "-"),
            "hours": round(hours, 2),
            "tss": round(sum(d["tss"] for d in week if d["event_type"] != "Race")),
            "sessions": sum(1 for d in week if d["sport"] != "rest"),
            "key": sum(1 for d in week if d["session_kind"] in ("hard", "benchmark")),
            "easy_pct": round(100 * (1 - hard_h / hours)) if hours else 0,
            "high_time_pct": round(100 * zs["high"] / zone_total),
            "mid_time_pct": round(100 * zs["mid"] / zone_total),
            "race": any(d["event_type"] == "Race" for d in week),
        })
    return rows


def render(profiles) -> Tuple[str, Dict]:
    out = [
        "# Golden athlete plans",
        "",
        "Generated by `scripts/plan_report.py` from the profiles in `tests/data/golden/`.",
        f"Plans start Monday {PLAN_START:%d %b %Y} (each athlete's \"today\") and run {WEEKS} weeks.",
        "Regenerate after any planner change; `tests/characterisation/test_golden_plans.py` fails if this",
        "file is out of date, so every change to these plans is reviewed.",
        "",
        "**Coaching rules the planner applies** (beyond the invariants in the brief; edit in",
        "`functions/engine/planner.py`):",
        "",
        "1. Each week ramps from the athlete's last *completed* load week (CTL if there's no history),",
        "   never below an entry volume (2.5 h/week; 2.5/4/6/8 h for brand-new athletes by level).",
        "   A week is planned from the athlete's state on its Monday, so it doesn't shift mid-week.",
        "2. Load weeks rise at most 10% in hours *and* TSS vs the last load week; recovery weeks",
        "   (65% volume) every 3-4 weeks; cycles count back from the event, offset per athlete otherwise.",
        "   Level (and so session caps) grows with fitness, up to pro: CTL 20/45/65/85 (cycling),",
        "   18/28/38/52 (running), 18/28/42/65 (swimming) unlocks intermediate/advanced/elite/pro.",
        "   Weekly ceilings per sport at pro: cycling 30 h, running 14 h, swimming 20 h.",
        "   Advanced+ athletes get an easy second session on a day when singles can't hold the volume.",
        "3. Sports: the split follows the athlete's priorities (main focus 3 : other focus 2 : rest 1).",
        "   Each sport ramps from its *own* recent volume: running +10% or one 30-min session a week,",
        "   cycling/swimming +30% (overall load is still +10%). A new or switched-to sport starts from",
        "   transfer credit: bike->run 25%, run->bike 75%, swim<->others 25% (min 2 h). Runs are",
        "   capped at 40% of the week's running (min 1 h). Switching sport never restarts the athlete.",
        "   New runners (under 2 h/week or no hour-long run yet) run easy only, once a day, starting at",
        "   45 min; the longest run then grows by at most 15 min a week, whatever their other fitness.",
        "4. Hard sessions take ~20% of weekly time (max 25%), are never on Monday or back-to-back,",
        "   need at least 40 min, and the day after one is Zone 1 recovery. No tempo/grey-zone sessions.",
        "5. Beginners: max one hard session, two rest days. Under ~3.3 h/week: no hard sessions.",
        "6. One long Zone 2 session on the weekend day with most time (~30% of the week, max 40%).",
        "7. Session caps by sport and level (running is capped hardest for impact; e.g. beginner runs <= 1 h).",
        "8. Strength (1-2x) only in load/recovery weeks, never the day before a hard session.",
        "9. Taper: 60% then 40% volume, intensity kept but shorter; race week = opener 3 days out,",
        "   rest 2 days out, shake-out the day before, race, rest the day after, easy for 2 more days.",
        "10. Missed sessions are never made up; the plan re-bases on actual fitness.",
        "11. 7+ days without training: one aerobic-only week, then one hard session the next week.",
        "12. Minor illness/injury: half volume, no intensity. Severe: rest until cleared.",
        "13. Benchmark test after each recovery week, and once for new athletes with no threshold.",
        "14. Day-of fatigue guardrail (TSB < -25 -> recovery) applies to the coming week only.",
        "",
        "**How to read the weekly table**",
        "",
        "- *Easy %*: share of endurance time in easy sessions (Seiler session-goal method); target ~80%.",
        "- *High % / Mid %*: share of time *in zone* above threshold / in the tempo \"grey zone\".",
        "  Time-in-zone is lower than session-goal by design (warm-ups and recoveries count as easy).",
        "- *KEY*: hard sessions (threshold or VO2max). *TEST*: benchmark that re-measures threshold.",
        "- Targets are the athlete's own numbers (W, bpm, pace). \"% thr (RPE)\" means we don't have that",
        "  threshold yet, so the session is ridden by feel.",
        "",
    ]
    summary: Dict = {}
    for key, about, profile in profiles:
        docs = generate(profile)
        rows = week_rows(docs)
        summary[key] = {"weeks": rows, "days": [
            [d["date"], d["session_kind"], d["sport"], d["time"], round(d["tss"], 1), main_set(d)] for d in docs]}
        out += [f"## {profile.display_name}", "", about, ""]
        goal = f"{profile.goal.name} on {profile.goal.date}" if profile.goal else "none (general fitness)"
        thresholds = ", ".join(sorted(profile.known_thresholds or [])) or "none yet"
        out += [
            f"- **Inputs:** {profile.weekly_hours:g} h/week max; sports {', '.join(profile.sports)}; "
            f"focus {', '.join(profile.focused_sports)}; level {profile.fitness_level}; "
            f"CTL {profile.ctl:g} / ATL {profile.atl:g} (last logged {profile.metrics_date or 'never'})",
            f"- **Goal:** {goal}",
            f"- **Thresholds on file:** {thresholds}",
            "",
            "| Wk | Starts | Type | Hours | TSS | Sessions | KEY/TEST | Easy % | High % | Mid % |",
            "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in rows:
            t = r["type"] + (" + race" if r["race"] and r["type"] != "Race" else "")
            out.append(f"| {r['week']} | {r['start']} | {t} | {r['hours']:.1f} | {r['tss']} | {r['sessions']} | "
                       f"{r['key']} | {r['easy_pct']} | {r['high_time_pct']} | {r['mid_time_pct']} |")
        out += ["", "<details><summary>Day-by-day plan</summary>", "",
                "| Date | Session | Sport | Duration | TSS | Main set / targets |", "|---|---|---|---:|---:|---|"]
        for d in docs:
            day = datetime.date.fromisoformat(d["date"])
            kind = KIND_NAMES.get(d["session_kind"], d["session_kind"] or "")
            if d["sport"] == "rest":
                out.append(f"| {day:%a %d %b} | Rest | | | | |")
                continue
            label = f"{day:%a %d %b}" + (" (PM)" if d.get("slot") == "pm" else "")
            out.append(f"| {label} | {kind} | {d['sport']} | {_fmt_dur(d['time'])} | {d['tss']:.0f} | "
                       f"{main_set(d)} |")
        out += ["", "</details>", ""]
    return "\n".join(out) + "\n", summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text, _ = render(load_profiles())
    if args.check:
        current = open(REPORT_PATH).read() if os.path.exists(REPORT_PATH) else ""
        if current != text:
            sys.exit("docs/golden-plans.md is out of date: run scripts/plan_report.py")
        return
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write(text)
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
