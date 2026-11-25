"""Portfolio Watch builders (scripts/portfolio_watch, lane portfolio-monitor)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PW = Path(__file__).resolve().parents[1] / "scripts" / "portfolio_watch"
sys.path.insert(0, str(PW))

import build_dashboard  # noqa: E402
import build_history  # noqa: E402
import paths  # noqa: E402


def test_publish_is_atomic_and_leaves_no_tmp(tmp_path):
    target = tmp_path / "a" / "b" / "index.html"
    assert build_dashboard.publish("<html>one</html>", target).startswith("wrote")
    assert build_dashboard.publish("<html>two</html>", target).startswith("wrote")
    assert target.read_text(encoding="utf-8") == "<html>two</html>"
    assert not any(p.name.endswith(".tmp") for p in target.parent.iterdir())


def test_an_unwritable_target_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert build_dashboard.publish("<html/>", blocker / "index.html").startswith("FAILED")


def test_the_page_publishes_to_all_three_targets_and_data_cannot_close_its_script_tag(tmp_path, monkeypatch):
    page, hist = tmp_path / "page", tmp_path / "history"
    page.mkdir()
    hist.mkdir()
    (page / "readings.json").write_text(json.dumps({"rows": [{"at": "2026-11-20T15:00:00Z",
                                                             "label": "x</script><b>"}], "meta": []}), encoding="utf-8")
    (hist / "daily_rollup.json").write_text(json.dumps({"rows": [{"date": "2026-11-19", "bets": 1}]}), encoding="utf-8")
    local, fleet = tmp_path / "local" / "dashboard.html", tmp_path / "fleet" / "index.html"
    monkeypatch.setattr(build_dashboard, "PAGE", page)
    monkeypatch.setattr(build_dashboard, "OUT", page / "dashboard.html")
    monkeypatch.setattr(paths, "HISTORY", hist)
    monkeypatch.setattr(paths, "LOCAL_PAGE_COPY", local)
    monkeypatch.setattr(paths, "FLEET_PAGE", fleet)
    monkeypatch.setattr(paths, "S8_HEARTBEAT", tmp_path / "none.json")
    assert build_dashboard.main() == 0
    texts = [p.read_text(encoding="utf-8") for p in (page / "dashboard.html", local, fleet)]
    assert texts[0] == texts[1] == texts[2]
    assert "x<\\/script>" in texts[0] and "x</script><b>" not in texts[0]


def test_ops_by_day_counts_non_gate_anomalies_and_slow_live_reads(tmp_path, monkeypatch):
    lines = [
        {"at": "2026-11-20T05:00:00Z", "anomalies": ["GATE 2 loads", "ENDPOINT live_today slow"],
         "endpoints": {"live_today": {"seconds": 3.4}}},
        {"at": "2026-11-20T07:00:00Z", "anomalies": [], "endpoints": {"live_today": {"seconds": 2.2}}},
    ]
    (tmp_path / "readings.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setattr(build_history, "READINGS", tmp_path)
    ops = build_history.ops_by_day()
    # 05:00Z is 11:00 PM CST 11-19; 07:00Z is 1:00 AM CST 11-20
    assert ops["2026-11-19"] == {"readings": 1, "anomalies": 1, "anomaly_lines": 1, "live_over_2s": 1,
                                 "live_over_3s": 1}
    assert ops["2026-11-20"] == {"readings": 1, "anomalies": 0, "anomaly_lines": 0, "live_over_2s": 1,
                                 "live_over_3s": 0}


def test_a_persistent_anomaly_counts_once_per_day_not_once_per_reading(tmp_path, monkeypatch):
    # 11-21: one open grade conflict re-flagged at 18 readings read as "23 anomalies" on the rollup.
    lines = [{"at": f"2026-11-21T{h:02d}:04:00Z", "anomalies": ["LEDGER grade_conflicts: 1"]} for h in range(8, 14)]
    lines += [
        {"at": "2026-11-21T15:04:00Z", "anomalies": ["ENDPOINT live_today slow: 4.22s > budget 3.0s",
                                                     "LEDGER grade_conflicts: 1",
                                                     "ORDERS resting order ac07e83e (taker): resting 134 min (> 120)"]},
        {"at": "2026-11-21T15:34:00Z", "anomalies": ["ENDPOINT live_today slow: 3.27s > budget 3.0s",
                                                     "LEDGER grade_conflicts: 1",
                                                     "ORDERS resting order ac07e83e (taker): resting 164 min (> 120)",
                                                     "GATE 2 deploys.md load(s) unclassified"]},
    ]
    (tmp_path / "readings.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    monkeypatch.setattr(build_history, "READINGS", tmp_path)
    day = build_history.ops_by_day()["2026-11-21"]
    assert day["readings"] == 8
    assert day["anomaly_lines"] == 12          # every non-GATE line at every reading
    assert day["anomalies"] == 3               # the conflict, the slow live read, the resting order


def test_history_keeps_the_previous_rollup_when_there_is_no_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(build_history, "READINGS", tmp_path / "empty")
    out = tmp_path / "daily_rollup.json"
    out.write_text('{"rows": [{"date": "kept"}]}', encoding="utf-8")
    monkeypatch.setattr(build_history, "OUT", out)
    assert build_history.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["rows"][0]["date"] == "kept"


def test_the_fleet_target_is_the_wsl_share_not_a_folder_on_c():
    # 11-20: a lost leading backslash turned the UNC path into C:\wsl.localhost\... and the "fleet copy" landed on C:.
    if sys.platform == "win32":
        # No backslash literals here (a heredoc mangled them once): compare the UNC drive in forward-slash form.
        assert paths.FLEET_PAGE.drive.replace(chr(92), "/").lower().startswith("//wsl.localhost/"), paths.FLEET_PAGE
    assert paths.FLEET_PAGE.as_posix().endswith("syndicate-prod/data/reports/portfolio_watch/index.html")


def test_todays_rollup_row_is_partial_and_earlier_days_are_not(tmp_path, monkeypatch):
    # 11-24 8:04 PM (findings H-R1): the newest row's 30-day ROI fell below noise when 2 bets graded today and a
    # full old day left the window. A reader must be able to tell that row from a settled day.
    from test_live_book_edge_readout import _order

    ledger = tmp_path / "readings" / "20261125T020404Z"
    ledger.mkdir(parents=True)
    orders = [_order(i, date="2026-11-23" if i < 4 else "2026-11-24", outcome="won" if i % 2 else "lost")
              for i in range(8)]
    (ledger / "live_all.json").write_text(json.dumps({"orders": orders}, indent=2), encoding="utf-8")
    monkeypatch.setattr(build_history, "READINGS", tmp_path / "readings")
    monkeypatch.setattr(build_history, "HISTORY", tmp_path / "history")
    monkeypatch.setattr(build_history, "OUT", tmp_path / "history" / "daily_rollup.json")
    monkeypatch.setattr(build_history, "today_ct", lambda: "2026-11-24")
    assert build_history.main() == 0
    rows = json.loads((tmp_path / "history" / "daily_rollup.json").read_text(encoding="utf-8"))["rows"]
    assert [(r["date"], r["partial"], r["bets"]) for r in rows] == [("2026-11-23", False, 4), ("2026-11-24", True, 4)]
