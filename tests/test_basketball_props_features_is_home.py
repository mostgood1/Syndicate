"""P3 input fix: the as-of (prediction) feature row derives `is_home` from the
date's matchup the same way the history rows derive it from MATCHUP, instead
of hardcoding 0.0 for every player.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import basketball_props_features as features_module

HEADER = "GAME_DATE,PLAYER_ID,PLAYER_NAME,TEAM_ABBREVIATION,MATCHUP,MIN,PTS,REB,AST,FG3M,FG3A,STL,BLK,TOV,FGM,FGA,FTA,FTM,OREB,DREB,PF,PLUS_MINUS\n"


def _seed_logs(processed_root: Path) -> None:
    processed_root.mkdir(parents=True, exist_ok=True)
    (processed_root / "player_logs.csv").write_text(
        HEADER
        + "2026-05-03,1,Home Player,LVA,LVA @ SEA,30,20,5,4,2,5,1,0,2,7,15,4,4,1,4,2,5\n"
        + "2026-05-05,1,Home Player,LVA,LVA vs. CHI,31,18,6,3,1,4,1,1,2,6,14,5,5,1,5,1,3\n"
        + "2026-05-03,2,Away Player,NYL,NYL vs. CHI,29,15,7,5,1,3,2,0,3,5,12,4,4,2,5,3,-2\n"
        + "2026-05-05,2,Away Player,NYL,NYL @ ATL,28,12,4,6,2,6,1,0,1,4,11,2,2,0,4,2,4\n"
        + "2026-05-05,3,Idle Player,SEA,SEA @ LVA,25,9,3,2,0,2,0,1,1,3,8,3,3,1,2,1,-6\n",
        encoding="utf-8",
    )


def _rows_by_player(features):
    return {str(row["player_name"]): row for _, row in features.iterrows()}


def test_home_and_away_inference_rows_differ_in_is_home(tmp_path):
    processed_root = tmp_path
    _seed_logs(processed_root)
    (processed_root / "game_odds_2026-05-10.csv").write_text(
        "home_team,visitor_team,total,home_spread\nLVA,NYL,165.5,-3.5\n",
        encoding="utf-8",
    )

    features = features_module.build_features_for_date_local(processed_root=processed_root, date="2026-05-10")
    rows = _rows_by_player(features)

    assert float(rows["Home Player"]["is_home"]) == 1.0
    assert float(rows["Away Player"]["is_home"]) == 0.0
    assert float(rows["Home Player"]["is_home"]) != float(rows["Away Player"]["is_home"])
    # A team with no game on the date keeps the pre-fix value.
    assert float(rows["Idle Player"]["is_home"]) == 0.0
    # The history rows' own derivation is untouched (regression guard on the
    # block the as-of row now mirrors).
    assert str(rows["Home Player"]["team"]) == "LVA"


def test_matchup_map_matches_history_row_parser(tmp_path):
    (tmp_path / "game_odds_2026-05-10.csv").write_text("home_team,visitor_team\nLVA,NYL\n", encoding="utf-8")
    matchup_map = features_module._asof_matchup_map_local(processed_root=tmp_path, date="2026-05-10")
    assert matchup_map == {"LVA": "LVA vs. NYL", "NYL": "NYL @ LVA"}
    assert features_module._parse_matchup_context(matchup_map["LVA"]) == (1.0, "NYL")
    assert features_module._parse_matchup_context(matchup_map["NYL"]) == (0.0, "LVA")


def test_matchup_map_falls_back_across_slate_files_and_full_names(tmp_path):
    # No game_odds; predictions carries the slate, with full team names.
    (tmp_path / "predictions_2026-05-10.csv").write_text(
        "home_team,visitor_team,totals\nLas Vegas Aces,New York Liberty,160\n",
        encoding="utf-8",
    )
    matchup_map = features_module._asof_matchup_map_local(processed_root=tmp_path, date="2026-05-10")
    assert matchup_map.get("LVA") == "LVA vs. NYL"
    assert matchup_map.get("NYL") == "NYL @ LVA"


def test_no_slate_file_keeps_pre_fix_value(tmp_path):
    _seed_logs(tmp_path)
    features = features_module.build_features_for_date_local(processed_root=tmp_path, date="2026-05-10")
    rows = _rows_by_player(features)
    assert {float(rows[name]["is_home"]) for name in ("Home Player", "Away Player", "Idle Player")} == {0.0}
    assert features_module._asof_matchup_map_local(processed_root=tmp_path, date="2026-05-10") == {}
