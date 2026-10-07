"""
Golden athletes: their 8-week plans are snapshotted, and the human-readable report in
docs/golden-plans.md must match the current engine, so any plan change is visible to the coach.
"""

import os

import pytest
from syrupy.extensions.json import JSONSnapshotExtension

from scripts import plan_report
from tests.property.plan_checks import consecutive_hard_days


@pytest.fixture(scope="module")
def report():
    return plan_report.render(plan_report.load_profiles())


def test_golden_plans_snapshot(report, snapshot):
    _, summary = report
    assert summary == snapshot.use_extension(JSONSnapshotExtension)


def test_committed_report_is_up_to_date(report):
    text, _ = report
    with open(plan_report.REPORT_PATH) as f:
        assert f.read() == text, "docs/golden-plans.md is stale: run functions/venv/bin/python scripts/plan_report.py"


@pytest.mark.parametrize("key", plan_report.ORDER)
def test_golden_plans_meet_the_invariants(report, key):
    _, summary = report
    weeks = summary[key]["weeks"]
    for w in weeks:
        if w["hours"] >= 1:
            assert w["easy_pct"] >= 75 and w["mid_time_pct"] <= 5
    load = [w["hours"] for w in weeks if w["type"] == "Load"]
    assert all(b <= a * 1.10 + 0.01 for a, b in zip(load, load[1:], strict=False))
    days = [{"date": d[0], "sport": d[2], "time": d[3], "intensity": 4 if d[1] in ("hard", "benchmark", "race") else 2,
             "steps": [], "event_type": "Race" if d[1] == "race" else "Training"} for d in summary[key]["days"]]
    assert consecutive_hard_days(days) == []


def test_report_cli_check_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(plan_report, "REPORT_PATH", str(tmp_path / "r.md"))
    monkeypatch.setattr("sys.argv", ["plan_report.py"])
    plan_report.main()
    monkeypatch.setattr("sys.argv", ["plan_report.py", "--check"])
    plan_report.main()  # fresh: no exit
    (tmp_path / "r.md").write_text("stale")
    with pytest.raises(SystemExit):
        plan_report.main()
    os.remove(tmp_path / "r.md")
    with pytest.raises(SystemExit):
        plan_report.main()
