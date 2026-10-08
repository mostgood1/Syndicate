"""NHL defense-vs-position producer + its sentence (lane intelligence-evidence-coverage, 2026-10-08)."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_nhl_defense_vs_position", Path(__file__).resolve().parents[1] / "scripts" / "build_nhl_defense_vs_position.py"
)
dvp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dvp)


def _box(gid, home, away, home_f_sog, away_d_sog, game_type=2, date="2026-10-03"):
    skater = lambda name, sog, pos: {"name": {"default": name}, "position": pos, "sog": sog, "goals": 0, "assists": 1, "points": 1}
    return {"id": gid, "gameType": game_type, "gameDate": date, "homeTeam": {"abbrev": home}, "awayTeam": {"abbrev": away},
            "playerByGameStats": {
                "homeTeam": {"forwards": [skater("R. Donato", home_f_sog, "C")], "defense": [], "goalies": []},
                "awayTeam": {"forwards": [], "defense": [skater("K. Korchinski", away_d_sog, "D")], "goalies": []}}}


def test_allowed_counts_the_opponents_skaters_and_skips_preseason():
    games, positions, newest = dvp.allowed_by_game([_box(1, "BUF", "CHI", 5, 2), _box(2, "BUF", "CHI", 99, 99, game_type=1)])
    assert games[("CHI", "1")]["F"]["sog"] == 5.0  # CHI faced BUF's forward
    assert games[("BUF", "1")]["D"]["sog"] == 2.0  # BUF faced CHI's defenseman
    assert ("CHI", "2") not in games and positions == {"R. Donato": "F", "K. Korchinski": "D"} and newest == "2026-10-03"


def test_run_and_sentence(tmp_path, monkeypatch):
    root = tmp_path / "nhl_source"
    cache = root / "data" / "ingestion_cache"
    cache.mkdir(parents=True)
    for gid, home, away, f, d in ((2026020001, "BUF", "CHI", 5, 2), (2026020002, "BOS", "CHI", 9, 1), (2026020003, "BOS", "BUF", 3, 4)):
        (cache / f"boxscore_{gid}.json").write_text(json.dumps(_box(gid, home, away, f, d)), encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_NHL_SOURCE_ROOT", str(root))
    summary = dvp.run(dt.date(2026, 10, 8))
    path = root / "data" / "processed" / "nhl_defense_vs_position_2026-2027_asof_20261003.json"
    assert summary["written"] == str(path)
    teams = json.loads(path.read_text())["teams"]
    assert teams["CHI"]["F"]["sog"] == {"per_game": 7.0, "games": 2, "rank": 3, "of": 3}

    from syndicate.features import intelligence_recent_matchup as rm

    row = {"player_name": "Ryan Donato", "market": "sog"}
    assert rm.nhl_vs_position_text(row, "CHI", selected_date="2026-10-08") == (
        "Vs position: CHI allows 7 shots on goal a game to forwards (rank 3 of 3, 1 = fewest; 2 games this season).")
    assert rm.nhl_vs_position_text({**row, "player_name": "Rasmus Dahlin"}, "CHI", selected_date="2026-10-08") is None
    assert rm.nhl_vs_position_text(row, "CHI", selected_date="2027-10-08") is None  # never another season's table
