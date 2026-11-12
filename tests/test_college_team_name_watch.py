"""The watchdog's college team-name check (lane `college-odds-feed-team-names`, 2026-11-12).

User: "run the audit before each slate automatically". The audit runs inside the fleet watchdog (every 5 min from disk,
the audit itself at most hourly) and an unresolved odds-feed name is an emailed `exec:` finding.
"""
from __future__ import annotations

import datetime as dt
import json

from scripts import college_team_name_watch as nw
from scripts import execution_watchdog as xw
from scripts import local_watchdog as wd

NOW = dt.datetime(2026, 11, 12, 22, 30, tzinfo=dt.timezone.utc)

UNRESOLVED = {
    "data_root": "x", "since": "2026-11-11",
    "leagues": {
        "ncaab": {"shards_read": 2, "events": 169, "events_with_an_unresolved_team": 0, "unresolved": {}},
        "wncaab": {"shards_read": 2, "events": 46, "events_with_an_unresolved_team": 1, "unresolved": {
            "CSU Bakersfield Roadrunners": {"events": 1, "dates": ["2026-11-12"],
                                            "espn_spelling": {"Cal State Bakersfield Roadrunners": 1}}}},
    },
}
CLEAN = {"leagues": {"ncaab": {"shards_read": 2, "events": 169, "events_with_an_unresolved_team": 0, "unresolved": {}},
                     "wncaab": {"shards_read": 2, "events": 46, "events_with_an_unresolved_team": 0, "unresolved": {}}}}


class FakeAudit:
    def __init__(self, *reports):
        self.reports, self.calls = list(reports), []

    def __call__(self, root, since=None):
        self.calls.append(since)
        report = self.reports.pop(0)
        if isinstance(report, Exception):
            raise report
        return report


def test_an_unresolved_name_is_an_emailed_warn_naming_the_team_and_espns_spelling(tmp_path):
    audit = FakeAudit(UNRESOLVED)
    findings, row = nw.run(tmp_path, {}, NOW, audit=audit)
    assert [(k, s) for k, s, _ in findings] == [("exec:team_names:wncaab", nw.WARN)]
    message = findings[0][2]
    assert "'CSU Bakersfield Roadrunners'" in message and "'Cal State Bakersfield Roadrunners'" in message
    assert "ncaab_team_registry.py" in message
    assert xw.emailable("exec:team_names:wncaab", nw.WARN)
    assert audit.calls == ["2026-11-11"]  # shards from yesterday (UTC) on: tonight's slate and every later one
    assert row["audited_at"] == NOW.isoformat()


def test_the_audit_runs_at_most_hourly_and_the_finding_holds_between_audits(tmp_path):
    audit = FakeAudit(UNRESOLVED, CLEAN)
    _, row = nw.run(tmp_path, {}, NOW, audit=audit)
    for minutes in (5, 30, 59):
        findings, row = nw.run(tmp_path, {nw.STATE_KEY: row}, NOW + dt.timedelta(minutes=minutes), audit=audit)
        assert [k for k, _, _ in findings] == ["exec:team_names:wncaab"]
    assert len(audit.calls) == 1
    findings, row = nw.run(tmp_path, {nw.STATE_KEY: row}, NOW + dt.timedelta(minutes=60), audit=audit)
    assert findings == [] and len(audit.calls) == 2  # fixed -> the next audit clears it


def test_no_quote_shard_is_no_finding(tmp_path):
    empty = {"leagues": {"ncaab": {"shards_read": 0, "events": 0, "unresolved": {}},
                         "wncaab": {"shards_read": 0, "events": 0, "unresolved": {}}}}
    findings, row = nw.run(tmp_path, {}, NOW, audit=FakeAudit(empty))
    assert findings == [] and row["leagues"]["ncaab"]["shards_read"] == 0


def test_a_crashed_audit_is_reported_until_the_next_audit_and_keeps_the_last_names(tmp_path):
    audit = FakeAudit(UNRESOLVED, OSError("disk"), CLEAN)
    _, row = nw.run(tmp_path, {}, NOW, audit=audit)
    at = NOW + dt.timedelta(hours=1)
    findings, row = nw.run(tmp_path, {nw.STATE_KEY: row}, at, audit=audit)
    assert {k for k, _, _ in findings} == {"exec:team_names:watch_error", "exec:team_names:wncaab"}
    findings, row = nw.run(tmp_path, {nw.STATE_KEY: row}, at + dt.timedelta(minutes=5), audit=audit)
    assert {k for k, _, _ in findings} == {"exec:team_names:watch_error", "exec:team_names:wncaab"}  # no flapping
    findings, row = nw.run(tmp_path, {nw.STATE_KEY: row}, at + dt.timedelta(hours=1), audit=audit)
    assert findings == [] and "error" not in row


def test_the_watchdog_reports_an_unresolved_name_from_a_real_quote_shard(tmp_path, capsys, monkeypatch):
    """End to end through `local_watchdog.main`: the real audit over a shard dated today, in the home's data root."""
    monkeypatch.delenv("SYNDICATE_WATCHDOG_TEAM_NAMES", raising=False)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    shard = tmp_path / "data" / "wncaab_source" / "tracking" / "book_quotes" / f"{today}.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_text(json.dumps({"kind": "game", "date": today, "event_id": "e1", "away_team": "Nowhere Tech Robots",
                                 "home_team": "Washington Huskies", "market": "h2h"}) + "\n", encoding="utf-8")
    wd.main(["--home", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out.strip())
    assert "WNCAAB odds-feed team name(s) that match no ESPN school" in out["message"]
    assert "'Nowhere Tech Robots'" in out["message"]
    state = json.loads((tmp_path / "run" / wd.STATE_NAME).read_text(encoding="utf-8"))
    assert "Nowhere Tech Robots" in state["team_names"]["leagues"]["wncaab"]["unresolved"]


def test_the_off_switch_turns_the_check_off(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SYNDICATE_WATCHDOG_TEAM_NAMES", "0")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    shard = tmp_path / "data" / "wncaab_source" / "tracking" / "book_quotes" / f"{today}.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_text(json.dumps({"kind": "game", "date": today, "event_id": "e1", "away_team": "Nowhere Tech Robots",
                                 "home_team": "Washington Huskies"}) + "\n", encoding="utf-8")
    wd.main(["--home", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out.strip())
    assert "odds-feed team name" not in out["message"]
    state = json.loads((tmp_path / "run" / wd.STATE_NAME).read_text(encoding="utf-8"))
    assert not state.get("team_names")
