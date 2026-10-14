"""The live loop's WNBA commence times come from the data-root schedule, not the vendored one
(lane wnba-live-commence-times-native, user request 2026-10-14).

`_wnba_commence_times` (the T-window provider) read vendor/wnba_betting_repo/data/processed/schedule_2026.json,
frozen at the vendor pull (ends 2026-09-24): it returned [] for the whole postseason, Finals G1 included (fleet,
2026-10-14). It now reads the newest schedule_*.json under WNBA_BETTING_DATA_ROOT/processed.
"""
from __future__ import annotations

import datetime as dt
import inspect
import json
import os

from syndicate.features.shared import live_refresh_loop as loop

G1 = {"game_id": "401918305", "date_est": "2026-10-17T00:00:00.000", "datetime_utc": "2026-10-17T19:30:00.000Z",
      "home_tricode": "GSV", "away_tricode": "ATL"}
G2 = {"game_id": "401918306", "date_est": "2026-10-19T00:00:00.000", "datetime_utc": "2026-10-20T00:00:00.000Z"}


def _epoch(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def test_reads_the_newest_data_root_schedule(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    stale = processed / "schedule_2025_26.json"
    stale.write_text(json.dumps([{**G1, "datetime_utc": "2026-10-17T23:00:00.000Z"}]), encoding="utf-8")
    os.utime(stale, (1, 1))
    (processed / "schedule_2026.json").write_text(json.dumps([G1, G1, G2]), encoding="utf-8")
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path))
    assert loop._wnba_commence_times("2026-10-17") == [("401918305", _epoch("2026-10-17T19:30:00Z"))]
    assert loop._wnba_commence_times("2026-10-19") == [("401918306", _epoch("2026-10-20T00:00:00Z"))]  # ET date, UTC epoch
    assert loop._wnba_commence_times("2026-10-14") == []


def test_no_schedule_or_unreadable_schedule_fails_open(tmp_path, monkeypatch):
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path))
    assert loop._wnba_commence_times("2026-10-17") == []
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "schedule_2026.json").write_text("{not json", encoding="utf-8")
    assert loop._wnba_commence_times("2026-10-17") == []


def test_without_the_env_it_uses_the_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("WNBA_BETTING_DATA_ROOT", raising=False)
    monkeypatch.setattr(loop, "data_root", lambda: tmp_path)
    assert loop._wnba_schedule_processed_dir() == tmp_path / "wnba_source" / "data" / "processed"


def test_nothing_vendored_is_read():
    import ast
    import textwrap

    code = "".join(ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(f))))  # code only: the comment names the old path
                   for f in (loop._wnba_commence_times, loop._wnba_schedule_processed_dir))
    assert "vendor" not in code and "wnba_betting_repo" not in code
    assert loop._T_WINDOW_COMMENCE_PROVIDERS["wnba"] is loop._wnba_commence_times
