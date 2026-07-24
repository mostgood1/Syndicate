"""Tests for the owned NHL ingestion (roster/lineup/goalie collection).

Pure logic (infer_lines/project_lineup/_toi_to_min) + a cache-backed build_team_usage run entirely
offline; a tolerant live smoke exercises the full collector when the network + mirror are available.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.ingestion import lineups as lu
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient, season_code_for_date


def test_toi_to_min():
    assert lu._toi_to_min("18:30") == pytest.approx(18.5)
    assert lu._toi_to_min("00:00") == 0.0
    assert lu._toi_to_min(None) == 0.0
    assert lu._toi_to_min("bad") == 0.0


def test_season_code_for_date():
    assert season_code_for_date("2026-01-15") == "20252026"
    assert season_code_for_date("2025-10-10") == "20252026"
    assert season_code_for_date("2026-08-01") == "20262027"


def _usage(n_f=13, n_d=7, n_g=2):
    """Synthetic usage with descending TOI so ranks are deterministic."""
    rows = []
    for i in range(n_f):
        rows.append({"player_id": 100 + i, "full_name": f"F{i}", "position": "F", "games_played": 5, "toi_avg": 20.0 - i})
    for i in range(n_d):
        rows.append({"player_id": 200 + i, "full_name": f"D{i}", "position": "D", "games_played": 5, "toi_avg": 24.0 - i})
    for i in range(n_g):
        rows.append({"player_id": 300 + i, "full_name": f"G{i}", "position": "G", "games_played": 3, "toi_avg": 60.0 - 30 * i})
    return rows


def test_infer_lines_slots():
    usage = lu.infer_lines(_usage())
    by_id = {r["player_id"]: r for r in usage}
    # top-3 forwards -> L1, next 3 -> L2 ...
    assert by_id[100]["line_slot"] == "L1" and by_id[102]["line_slot"] == "L1"
    assert by_id[103]["line_slot"] == "L2"
    assert by_id[109]["line_slot"] == "L4"
    assert by_id[112]["line_slot"] is None      # 13th forward, no slot
    # top-2 D -> D1
    assert by_id[200]["line_slot"] == "D1" and by_id[201]["line_slot"] == "D1"
    assert by_id[202]["line_slot"] == "D2"
    assert by_id[206]["line_slot"] is None      # 7th D
    # goalies never get a skater slot
    assert by_id[300]["line_slot"] is None


def test_infer_lines_pp_pk_units():
    usage = lu.infer_lines(_usage())
    by_id = {r["player_id"]: r for r in usage}
    # highest-TOI skaters are the D-men (24 > 20); PP1 = top 5 skaters overall
    pp1 = [r["player_id"] for r in usage if r.get("pp_unit") == 1]
    assert len(pp1) == 5
    assert all(r.get("pp_unit") is None for r in usage if r["position"] == "G")


def test_project_lineup_flags_starter_goalie():
    usage = lu.project_lineup(lu.infer_lines(_usage()))
    starters = [r for r in usage if r.get("is_starter_goalie")]
    assert len(starters) == 1
    assert starters[0]["player_id"] == 300      # higher-TOI goalie
    assert all("proj_toi" in r for r in usage)


def _boxscore(home_abbr, away_abbr, home_players):
    return {
        "homeTeam": {"abbrev": home_abbr}, "awayTeam": {"abbrev": away_abbr},
        "playerByGameStats": {
            "homeTeam": {
                "forwards": [p for p in home_players if p["position"] == "C"],
                "defense": [p for p in home_players if p["position"] == "D"],
                "goalies": [p for p in home_players if p["position"] == "G"],
            },
            "awayTeam": {"forwards": [], "defense": [], "goalies": []},
        },
    }


def test_build_team_usage_from_cache(tmp_path):
    client = NhlWebIngestClient(cache_dir=tmp_path, offline=True)
    players = [
        {"playerId": 1, "name": {"default": "Top C"}, "position": "C", "toi": "20:00"},
        {"playerId": 2, "name": {"default": "Top D"}, "position": "D", "toi": "24:00"},
        {"playerId": 3, "name": {"default": "Starter G"}, "position": "G", "toi": "60:00"},
    ]
    for gid in ("1", "2"):
        (tmp_path / f"boxscore_{gid}.json").write_text(json.dumps(_boxscore("BUF", "MTL", players)), encoding="utf-8")
    # stub the schedule lookup (offline) to return our two cached games
    client.recent_finished_game_ids = lambda *a, **k: ["1", "2"]  # type: ignore[assignment]

    usage = lu.build_team_usage(client, "BUF", date="2026-01-16", n_games=5)
    by_id = {r["player_id"]: r for r in usage}
    assert by_id[1]["toi_avg"] == pytest.approx(20.0)     # averaged over 2 games
    assert by_id[2]["games_played"] == 2
    assert by_id[3]["position"] == "G"
    assert usage[0]["toi_avg"] >= usage[-1]["toi_avg"]    # sorted desc


def test_collect_slate_inputs_offline_empty(tmp_path):
    # No scoreboard under this root -> no teams -> zero rows, files still written with headers.
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs
    client = NhlWebIngestClient(cache_dir=tmp_path, offline=True)
    summary = collect_slate_inputs("2026-01-16", root=tmp_path, client=client, out_dir=tmp_path)
    assert summary["teams"] == 0
    assert summary["lineup_rows"] == 0
    assert Path(summary["lineups_path"]).exists()


def test_collect_live_smoke(tmp_path):
    """Full collector against the real mirror + network (skipped if unavailable)."""
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs
    try:
        summary = collect_slate_inputs("2026-06-14", out_dir=tmp_path, n_games=4)
    except Exception as exc:  # network/offline environments
        pytest.skip(f"live NHL API unavailable: {exc}")
    if summary["teams"] == 0:
        pytest.skip("no mirrored scoreboard for 2026-06-14")
    assert summary["lineup_rows"] > 0
    assert summary["goalies"] >= 1
