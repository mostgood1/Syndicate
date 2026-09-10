"""The final pass on past MLB live-lens reports (lane `mlb-lens-final-status`).

`live_lens_loop` writes only today's report, so a game still running at the
midnight-Central roll kept a mid-game row in yesterday's report for good -- and
on web, which holds no feed payload for a past date, that row IS the date's
status. Measured 2026-09-10: 823095/823907 served `Live` for six days; 9 games
on 7 of 9 dates.

These pin that the pass finalizes exactly the stale rows, touches nothing else,
costs nothing once a date is final, survives a re-freeze by another writer, is
reachable from the tick without being able to break it -- and that a finalized
row is what makes web's merge serve Final.
"""
from __future__ import annotations

import json
import os

import pytest

from syndicate.features.mlb import live_lens_final_pass as fp

TODAY = "2026-09-10"


def _slim_report(date_str, rows):
    games = [dict(row) for row in rows]
    final = sum(1 for r in games if r["status"]["abstract"] == "Final")
    live = sum(1 for r in games if r["status"]["abstract"] == "Live")
    return {
        "date": date_str,
        "generatedAt": f"{date_str}T23:59:10-05:00",
        "counts": {"games": len(games), "live": live, "final": final, "pregame": len(games) - live - final},
        "performance": {},
        "games": games,
    }


FROZEN_0903 = [
    {"gamePk": 823337, "startTime": "6:05 PM", "status": {"abstract": "Final", "detailed": "Final"}},
    {"gamePk": 823095, "startTime": "8:40 PM", "status": {"abstract": "Live", "detailed": "In Progress"},
     "props": [{"id": "p1"}], "liveProps": [{"id": "lp1"}]},
    {"gamePk": 823907, "startTime": "9:10 PM", "status": {"abstract": "Live", "detailed": "In Progress"}},
]
FINAL_0909 = [{"gamePk": 823901, "startTime": "7:05 PM", "status": {"abstract": "Final", "detailed": "Final"}}]
OLD_0820 = [{"gamePk": 800001, "startTime": "7:05 PM", "status": {"abstract": "Live", "detailed": "In Progress"}}]


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    fp._reset_state_for_tests()
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_LOOKBACK_DAYS", raising=False)

    def _path(date_str):
        return tmp_path / f"live_lens_report_{date_str.replace('-', '_')}.json"

    monkeypatch.setattr(fp, "live_lens_report_path", _path)
    for date_str, rows in (("2026-09-03", FROZEN_0903), ("2026-09-09", FINAL_0909), ("2026-08-20", OLD_0820)):
        _path(date_str).write_text(json.dumps(_slim_report(date_str, rows), indent=2), encoding="utf-8")
    yield _path
    fp._reset_state_for_tests()


class _Fetch:
    """StatsAPI stand-in: records which dates were asked for."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    def __call__(self, date_str):
        self.calls.append(date_str)
        return self.statuses.get(date_str, {})


FINAL = {"abstract": "Final", "detailed": "Final"}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_frozen_row_is_finalized_and_nothing_else_changes(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: {"abstract": "Final", "detailed": "Game Over"}}})
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    report = _load(reports("2026-09-03"))
    rows = {row["gamePk"]: row for row in report["games"]}
    assert rows[823095]["status"] == FINAL
    assert rows[823907]["status"] == {"abstract": "Final", "detailed": "Game Over"}
    assert rows[823095]["finalizedBy"] == "live_lens_final_pass"
    assert rows[823095]["liveProps"] == [{"id": "lp1"}], "only status is rewritten"
    assert rows[823337] == FROZEN_0903[0], "an already-final row is untouched"
    assert report["counts"] == {"games": 3, "live": 0, "final": 3, "pregame": 0}
    assert [item["gamePk"] for item in report["finalPass"][-1]["finalized"]] == [823095, 823907]
    assert stats["finalized"] == 2 and stats["still_open"] == 0
    assert "2026-09-03:823095" in stats["finalized_games"]


def test_an_all_final_report_costs_no_fetch_and_no_write(reports):
    before = os.stat(reports("2026-09-09")).st_mtime_ns
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    assert "2026-09-09" not in fetch.calls
    assert os.stat(reports("2026-09-09")).st_mtime_ns == before


def test_a_game_statsapi_still_calls_live_is_left_alone(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: {"abstract": "Live", "detailed": "In Progress"}}})
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    rows = {row["gamePk"]: row for row in _load(reports("2026-09-03"))["games"]}
    assert rows[823907]["status"]["abstract"] == "Live"
    assert stats["finalized"] == 1 and stats["still_open"] == 1
    # Not verified, so the next unthrottled pass asks again.
    fetch.statuses["2026-09-03"][823907] = FINAL
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=fetch)
    rows = {row["gamePk"]: row for row in _load(reports("2026-09-03"))["games"]}
    assert rows[823907]["status"] == FINAL


def test_an_unreadable_statsapi_writes_nothing(reports):
    before = reports("2026-09-03").read_bytes()
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=lambda d: None)
    assert reports("2026-09-03").read_bytes() == before
    assert stats["fetch_failed"] >= 1 and stats["finalized"] == 0


def test_throttle_and_kill_switch(reports, monkeypatch):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    calls = len(fetch.calls)
    assert fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_060, fetch=fetch)["reason"] == "throttled"
    assert len(fetch.calls) == calls
    monkeypatch.setenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS", "0")
    assert fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=99_000, fetch=fetch)["reason"] == "disabled"


def test_the_lookback_is_bounded(reports):
    fetch = _Fetch({"2026-08-20": {800001: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    assert "2026-08-20" not in fetch.calls, "21 days back is outside the default 10-day look-back"
    assert _load(reports("2026-08-20"))["games"][0]["status"]["abstract"] == "Live"


def test_a_refrozen_report_is_caught_on_the_next_pass(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    # Another writer puts the frozen copy back (a new mtime).
    path = reports("2026-09-03")
    path.write_text(json.dumps(_slim_report("2026-09-03", FROZEN_0903), indent=2), encoding="utf-8")
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 5_000_000_000))
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=fetch)
    assert stats["finalized"] == 2
    assert all(row["status"]["abstract"] == "Final" for row in _load(path)["games"])


def test_a_finalized_row_makes_the_web_merge_serve_final(reports):
    """Web has no feed payload for a past date, so its base status is
    Pregame/Scheduled and the lens row decides. After the pass, it decides Final."""
    from syndicate.features.mlb import cards

    fp.finalize_recent_mlb_live_lens_reports(
        TODAY, now_epoch=1_000, fetch=_Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    )
    row = next(r for r in _load(reports("2026-09-03"))["games"] if r["gamePk"] == 823095)
    base = {"gamePk": 823095, "status": cards._source_status(None)}
    assert base["status"]["abstract"] == "Pregame", "fixture: web's base for a past date"
    assert cards._merge_live_lens_row_into_game(base, row)["status"] == FINAL


def test_the_tick_runs_the_pass_after_the_sports_and_cannot_be_broken_by_it(tmp_path, monkeypatch):
    from syndicate.features.shared import live_lens_loop as loop

    monkeypatch.setattr(loop, "_live_lens_active_sports", lambda: ("mlb",))
    monkeypatch.setattr(loop, "_run_live_lens_tick_for_sport", lambda sport, date_str: {"ok": True, "sport": sport})
    monkeypatch.setattr(loop, "write_json_file", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_meta_dir", lambda: tmp_path)
    monkeypatch.setattr(loop, "central_today_iso", lambda: TODAY)
    seen = []
    monkeypatch.setattr(fp, "finalize_recent_mlb_live_lens_reports",
                        lambda today_iso: seen.append(today_iso) or {"ran": True, "finalized": 0})
    meta = loop._run_live_lens_tick()
    assert seen == [TODAY], "the tick must call the final pass with today's date"
    assert meta["mlbFinalPass"]["ran"] is True

    def _boom(today_iso):
        raise RuntimeError("statsapi down")

    monkeypatch.setattr(fp, "finalize_recent_mlb_live_lens_reports", _boom)
    meta = loop._run_live_lens_tick()
    assert meta["ok"] is True, "a failed final pass must not fail the tick"
    assert "RuntimeError" in meta["mlbFinalPass"]["error"]
