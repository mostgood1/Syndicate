"""NBA has a T-window commence-time provider (lane nba-t-window-provider, user decision 2026-10-14).

There was none: the only candidate source was a vendored NBA schedule mirror that did not exist. The native NBA
fetch-schedule now writes the season in play, so `_nba_commence_times` reads the newest schedule_*.json under
NBA_BETTING_DATA_ROOT/processed (date_est filter, datetime_utc epoch, one entry per game), like the WNBA provider.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from syndicate.features.shared import live_refresh_loop as loop

OPENER = [
    {"game_id": "0022600001", "date_est": "2026-10-20T00:00:00.000", "datetime_utc": "2026-10-20T23:00:00.000Z"},
    {"game_id": "0022600002", "date_est": "2026-10-20T00:00:00.000", "datetime_utc": "2026-10-21T01:30:00.000Z"},
    {"game_id": "0022600003", "date_est": "2026-10-20T00:00:00.000", "datetime_utc": "2026-10-20T19:00:00.000Z"},
    {"game_id": "0022600004", "date_est": "2026-10-21T00:00:00.000", "datetime_utc": "2026-10-21T23:00:00.000Z"},
]


def _epoch(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def test_reads_the_newest_schedule_once_per_game(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    stale = processed / "schedule_2024_25.json"
    stale.write_text(json.dumps([{**OPENER[0], "datetime_utc": "2026-10-20T20:00:00.000Z"}]), encoding="utf-8")
    os.utime(stale, (1, 1))
    for name in ("schedule_2026_27.json", "schedule_2025_26.json"):  # the season file and its alias, same content
        (processed / name).write_text(json.dumps(OPENER + OPENER[:1]), encoding="utf-8")
    monkeypatch.setenv("NBA_BETTING_DATA_ROOT", str(tmp_path))
    got = loop._nba_commence_times("2026-10-20")
    assert got == [("0022600001", _epoch("2026-10-20T23:00:00Z")), ("0022600002", _epoch("2026-10-21T01:30:00Z")),
                   ("0022600003", _epoch("2026-10-20T19:00:00Z"))]
    assert loop._nba_commence_times("2026-10-17") == []


def test_missing_or_bad_schedule_fails_open(tmp_path, monkeypatch):
    monkeypatch.setenv("NBA_BETTING_DATA_ROOT", str(tmp_path))
    assert loop._nba_commence_times("2026-10-20") == []
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "schedule_2026_27.json").write_text("{nope", encoding="utf-8")
    assert loop._nba_commence_times("2026-10-20") == []


def test_nba_is_registered_and_its_windows_fire(tmp_path, monkeypatch):
    assert loop._T_WINDOW_COMMENCE_PROVIDERS["nba"] is loop._nba_commence_times
    assert "nba" in loop._t_window_sports()
    monkeypatch.setattr(loop, "_commence_times_cached", lambda sport, date_str, now_epoch: (
        [("0022600003", _epoch("2026-10-20T19:00:00Z"))] if sport == "nba" else []))
    monkeypatch.setattr(loop, "_read_t_window_markers", lambda date_str: {})
    monkeypatch.setitem(loop._LIVE_STATUS_CHECKERS, "nba", lambda date_str: False)
    ramp = loop._t_window_due_sports(now_epoch=_epoch("2026-10-20T18:00:00Z"), date_str="2026-10-20")
    assert ramp == {"nba": {"nba:ramp:0022600003": _epoch("2026-10-20T18:00:00Z")}}
    closing = loop._t_window_due_sports(now_epoch=_epoch("2026-10-20T18:52:00Z"), date_str="2026-10-20")
    assert list(closing["nba"]) == ["nba:closing:0022600003"]
    monkeypatch.setitem(loop._LIVE_STATUS_CHECKERS, "nba", lambda date_str: True)  # live: the live cadence owns it
    assert "nba" not in loop._t_window_due_sports(now_epoch=_epoch("2026-10-20T18:52:00Z"), date_str="2026-10-20")
