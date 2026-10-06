"""nba_history_refresh: player_logs stays current with THIS season's regular-season games, never loses prior seasons,
never takes a non-regular game, writes nothing on an empty fetch, and the props refresh actually calls it."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.shared import nba_history_refresh as hr

COLS = ["SEASON_ID", "PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_ID", "GAME_DATE", "MIN", "PTS", "REB", "AST",
        "FG3M", "STL", "BLK", "TOV", "SEASON"]
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


def _row(season, gid, date, name="A. Player", pts=10):
    return {"SEASON_ID": "2" + season[:4], "PLAYER_ID": 1, "PLAYER_NAME": name, "TEAM_ABBREVIATION": "NYK",
            "GAME_ID": gid, "GAME_DATE": date, "MIN": 30, "PTS": pts, "REB": 5, "AST": 3, "FG3M": 1, "STL": 1, "BLK": 0,
            "TOV": 2, "SEASON": season}


def _write_logs(root, rows):
    pd.DataFrame(rows, columns=COLS).to_csv(root / hr.FILE, index=False)


def test_current_season_string():
    assert hr.current_season("2026-10-20") == "2026-27" and hr.current_season("2027-03-01") == "2026-27"
    assert hr.current_season("2026-04-10") == "2025-26"


def test_merge_replaces_this_season_keeps_prior_and_drops_non_regular(tmp_path):
    _write_logs(tmp_path, [_row("2025-26", "0022500002", "2025-10-21"), _row("2025-26", "0022501230", "2026-04-12")])
    fetched = pd.DataFrame([_row("2026-27", "0022600001", "2026-10-20"),
                            _row("2026-27", "0012600050", "2026-10-15"),     # a preseason id: must be dropped
                            _row("2026-27", "0022600014", "2026-10-21")]).drop(columns=["SEASON"])
    out = hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=lambda s: fetched, now=NOW)
    assert out["wrote"] and out["season_rows"] == 2 and out["dropped_non_regular"] == 1 and out["other_seasons_kept"] == 2
    df = pd.read_csv(tmp_path / hr.FILE, dtype={"GAME_ID": str})
    assert sorted(df["SEASON"].unique()) == ["2025-26", "2026-27"] and len(df) == 4
    assert not df["GAME_ID"].str.startswith("001").any() and df["GAME_ID"].str.len().eq(10).all()
    # a second fetch of the same season REPLACES its rows (no duplicates), prior season untouched
    out2 = hr.refresh_player_logs(tmp_path, "2026-10-23", fetch=lambda s: fetched, now=NOW + timedelta(hours=7))
    assert out2["wrote"] and len(pd.read_csv(tmp_path / hr.FILE)) == 4


def test_empty_fetch_before_opening_night_writes_nothing(tmp_path):
    _write_logs(tmp_path, [_row("2025-26", "0022500002", "2025-10-21")])
    before = (tmp_path / hr.FILE).read_bytes()

    def no_rows(season):
        raise RuntimeError(f"LeagueGameLog returned no rows for {season}")

    out = hr.refresh_player_logs(tmp_path, "2026-10-06", fetch=no_rows, now=NOW)
    assert not out["wrote"] and "no rows" in out["reason"] and (tmp_path / hr.FILE).read_bytes() == before


def test_throttle_and_force(tmp_path):
    _write_logs(tmp_path, [_row("2025-26", "0022500002", "2025-10-21")])
    calls = []
    fetch = lambda s: calls.append(s) or pd.DataFrame()  # noqa: E731
    hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=fetch, now=NOW)
    assert hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=fetch, now=NOW + timedelta(hours=1)).get("skipped")
    hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=fetch, now=NOW + timedelta(hours=1), force=True)
    hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=fetch, now=NOW + timedelta(hours=7))
    assert calls == ["2026-27"] * 3


def test_schema_mismatch_is_refused(tmp_path):
    _write_logs(tmp_path, [_row("2025-26", "0022500002", "2025-10-21")])
    bad = pd.DataFrame([{"GAME_ID": "0022600001", "GAME_DATE": "2026-10-20"}])
    out = hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=lambda s: bad, now=NOW)
    assert not out["wrote"] and "lacks" in out["reason"]


def test_a_stale_parquet_beside_the_csv_is_rewritten(tmp_path):
    _write_logs(tmp_path, [_row("2025-26", "0022500002", "2025-10-21")])
    pq = tmp_path / "player_logs.parquet"
    pd.read_csv(tmp_path / hr.FILE).to_parquet(pq, index=False)
    fetched = pd.DataFrame([_row("2026-27", "0022600001", "2026-10-20")])
    hr.refresh_player_logs(tmp_path, "2026-10-22", fetch=lambda s: fetched, now=NOW)
    assert (not pq.exists()) or set(pd.read_parquet(pq)["SEASON"]) == {"2025-26", "2026-27"}


def _load_refresh_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "refresh_nba_oddsapi_props.py"
    spec = importlib.util.spec_from_file_location("refresh_nba_oddsapi_props_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_props_refresh_gate_reaches_the_history_refresh_and_off_switch_skips_it(tmp_path, monkeypatch):
    """Reachability: the gate used to return True as soon as player_logs EXISTED and never refreshed it."""
    mod = _load_refresh_script()
    src = tmp_path / "nba_source"
    (src / "data" / "processed").mkdir(parents=True)
    _write_logs(src / "data" / "processed", [_row("2025-26", "0022500002", "2025-10-21")])
    seen = []
    monkeypatch.setattr(hr, "refresh_player_logs", lambda root, d, **k: seen.append((Path(root), d)) or {"wrote": False})
    log = tmp_path / "refresh.log"
    ok, _ = mod._ensure_player_logs_for_props_refresh(source_root=src, date_str="2026-10-22", log_file=log, heartbeat_cb=lambda: None)
    assert ok and seen == [(src / "data" / "processed", "2026-10-22")]
    monkeypatch.setenv("SYNDICATE_NBA_PLAYER_LOGS_REFRESH", "0")
    mod._ensure_player_logs_for_props_refresh(source_root=src, date_str="2026-10-22", log_file=log, heartbeat_cb=lambda: None)
    assert len(seen) == 1
