"""NBA / WNBA defense-vs-position producer + its sentence (lane intelligence-evidence-coverage, phase 2)."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_basketball_defense_vs_position",
    Path(__file__).resolve().parents[1] / "scripts" / "build_basketball_defense_vs_position.py",
)
dvp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dvp)

WNBA_FIELDS = ["game_id", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME", "MIN", "PTS", "REB", "AST", "FG3M", "START_POSITION", "date"]


def _w(gid, team, pid, name, pts, pos="", mins="20", date="2026-06-01"):
    return {"game_id": gid, "TEAM_ABBREVIATION": team, "PLAYER_ID": pid, "PLAYER_NAME": name, "MIN": mins,
            "PTS": pts, "REB": 1, "AST": 1, "FG3M": 0, "START_POSITION": pos, "date": date}


def test_nba_ids_carry_the_phase_and_both_schemas_normalise():
    rows = [
        {"gameId": "22500471", "teamTricode": "HOU", "personId": "1", "firstName": "Kevin", "familyName": "Durant",
         "position": "F", "minutes": "36:33", "points": "22", "reboundsTotal": "5", "assists": "11", "threePointersMade": "2", "date": "2026-01-01"},
        {"game_id": "0042500101", "TEAM_ABBREVIATION": "HOU", "PLAYER_ID": "1", "PLAYER_NAME": "Kevin Durant", "MIN": "30",
         "PTS": "30", "REB": "4", "AST": "5", "FG3M": "3", "date": "2026-04-20"},
        {"game_id": "0012500001", "TEAM_ABBREVIATION": "HOU", "PLAYER_ID": "1", "MIN": "20", "PTS": "9", "date": "2025-10-05"},
        {"gameId": "22500471", "teamTricode": "HOU", "personId": "2", "minutes": "0:00", "points": "0", "date": "2026-01-01"},
    ]
    recs = dvp.normalise("nba", rows)
    assert [(r["phase"], r["game"], r["name"]) for r in recs] == [("regular", "0022500471", "Kevin Durant"), ("playoffs", "0042500101", "Kevin Durant")]
    assert recs[0]["stats"]["pra"] == 38.0 and recs[0]["season"] == "2025-26"


def test_positions_prefer_starts_then_roster():
    recs = [{"player": "a", "start_pos": "G"}, {"player": "a", "start_pos": "G"}, {"player": "a", "start_pos": "F"}, {"player": "b", "start_pos": None}]
    assert dvp.positions(recs, {"b": "F-C", "c": "C"}) == {"a": "G", "b": "F", "c": "C"}


def test_run_splits_phases_ranks_and_the_sentence_reads_the_regular_table(tmp_path, monkeypatch):
    root = tmp_path / "wnba_source"
    proc = root / "data" / "processed"
    proc.mkdir(parents=True)
    (proc / "schedule_2026.csv").write_text(
        "game_id,game_subtype,season_type_slug\n1,STD,regular-season\n2,STD,regular-season\n3,RD16,post-season\n9,STD,preseason\n", encoding="utf-8")
    rows = [
        _w(1, "ATL", "g1", "Rhyne Howard", 20, "G"), _w(1, "LV", "g2", "Jackie Young", 10, "G"),
        _w(2, "ATL", "g1", "Rhyne Howard", 30, "G"), _w(2, "CHI", "g3", "Ariel Atkins", 8, "G"),
        _w(3, "ATL", "g1", "Rhyne Howard", 40, "G", date="2026-09-20"), _w(3, "CHI", "g3", "Ariel Atkins", 5, "G", date="2026-09-20"),
        _w(9, "ATL", "g1", "Rhyne Howard", 99, "G", date="2026-05-01"), _w(9, "CHI", "g3", "Ariel Atkins", 99, "G", date="2026-05-01"),
    ]
    with (proc / "boxscores_history.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=WNBA_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setenv("SYNDICATE_WNBA_SOURCE_ROOT", str(root))
    summaries = dvp.run("wnba")
    assert [(s["phase"], s["through"]) for s in summaries] == [("regular", "2026-06-01"), ("playoffs", "2026-09-20")]
    table = json.loads((proc / "wnba_defense_vs_position_2026_regular_asof_20260601.json").read_text())
    # LV code folded to LVA; preseason game 9 (99 points) never counted
    assert table["teams"]["LVA"]["G"]["pts"] == {"per_game": 20.0, "games": 1, "rank": 2, "of": 3}
    assert table["teams"]["ATL"]["G"]["pts"]["rank"] == 1 and table["player_positions"]["Rhyne Howard"] == "G"

    from syndicate.features import intelligence_recent_matchup as rm

    row = {"sport": "wnba", "player_name": "Rhyne Howard", "market": "player_points"}
    assert rm.basketball_vs_position_text(row, "LV", selected_date="2026-10-07") == (
        "Vs position: LVA allows 20 points a game to guards (rank 2 of 3, 1 = fewest; 2026 regular season, 1 game).")
    assert "21 points + rebounds a game" in rm.basketball_vs_position_text({**row, "market": "player_points_rebounds"}, "LV", selected_date="2026-10-07")
    assert rm.basketball_vs_position_text({**row, "market": "player_double_double"}, "LV", selected_date="2026-10-07") is None
    assert rm.basketball_vs_position_text(row, "LV", selected_date="2027-06-01") is None  # never last season's table
