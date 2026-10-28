"""As-of season roster for historical resims (scripts/basketball_scenario_rates.asof_roster; lane
basketball-player-distribution step 1b: the resim tree held only the END-of-season roster)."""
from __future__ import annotations

import pandas as pd

from scripts.basketball_scenario_rates import asof_roster


def _write(tmp_path):
    pd.DataFrame([
        # traded at the deadline; played for LAC before the slate
        {"PLAYER_ID": 1, "PLAYER": "Ivica Zubac", "TEAM_ABBREVIATION": "IND", "POSITION": "C", "HOW_ACQUIRED": "Traded from LAC on 02/05/26"},
        # traded at the deadline; no game yet (injured) -> back to the from-team
        {"PLAYER_ID": 2, "PLAYER": "Hurt Guy", "TEAM_ABBREVIATION": "CHI", "POSITION": "G", "HOW_ACQUIRED": "Traded from CHA on 02/04/26"},
        # signed in March -> not on any roster in November
        {"PLAYER_ID": 3, "PLAYER": "Late Signing", "TEAM_ABBREVIATION": "ATL", "POSITION": "G", "HOW_ACQUIRED": "Signed on 03/04/26"},
        # on the team all season
        {"PLAYER_ID": 4, "PLAYER": "Stays Put", "TEAM_ABBREVIATION": "BOS", "POSITION": "F", "HOW_ACQUIRED": "#3 Pick in 2020 Draft"},
    ]).to_csv(tmp_path / "rosters_2025-26.csv", index=False)
    pd.DataFrame([
        {"PLAYER_ID": 1, "PLAYER_NAME": "Ivica Zubac", "TEAM_ABBREVIATION": "LAC", "GAME_DATE": "2025-10-30"},
        {"PLAYER_ID": 4, "PLAYER_NAME": "Stays Put", "TEAM_ABBREVIATION": "BOS", "GAME_DATE": "2025-10-30"},
        # left mid-season, absent from the end-of-season file, played recently -> added
        {"PLAYER_ID": 5, "PLAYER_NAME": "Waived Later", "TEAM_ABBREVIATION": "MIL", "GAME_DATE": "2025-10-31"},
        # absent from the file, last game long ago -> not added
        {"PLAYER_ID": 6, "PLAYER_NAME": "Long Gone", "TEAM_ABBREVIATION": "MIL", "GAME_DATE": "2025-09-01"},
    ]).to_csv(tmp_path / "player_logs.csv", index=False)


def test_asof_roster_rules(tmp_path):
    _write(tmp_path)
    stats = asof_roster(tmp_path, "2025-11-02")
    out = pd.read_csv(tmp_path / "rosters_2025-26.csv").set_index("PLAYER_ID")["TEAM_ABBREVIATION"].to_dict()
    assert out == {1: "LAC", 2: "CHA", 4: "BOS", 5: "MIL"}
    assert stats["moved_by_logs"] == 1 and stats["reverted_trade"] == 1
    assert stats["dropped_future_add"] == 1 and stats["added_departed"] == 1


def test_after_the_deadline_the_file_team_stands(tmp_path):
    _write(tmp_path)
    asof_roster(tmp_path, "2026-03-10")
    out = pd.read_csv(tmp_path / "rosters_2025-26.csv").set_index("PLAYER_ID")["TEAM_ABBREVIATION"].to_dict()
    # Zubac's last game was for LAC, but the 02/05 trade is after it and before the slate: the file team stands
    assert out == {1: "IND", 2: "CHI", 3: "ATL", 4: "BOS"}


def test_missing_inputs_are_a_no_op(tmp_path):
    assert asof_roster(tmp_path, "2025-11-02") == {"skipped": 1}
