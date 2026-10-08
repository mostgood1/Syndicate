"""NFL defense-vs-position producer + its sentence (lane intelligence-evidence-coverage, phase 2)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_nfl_defense_vs_position", Path(__file__).resolve().parents[1] / "scripts" / "build_nfl_defense_vs_position.py"
)
dvp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dvp)

POS = {"qb1": "QB", "te1": "TE", "wr1": "WR", "rb1": "RB"}


def _play(**kw):
    base = {"season_type": "REG", "week": "1", "game_id": "g1", "posteam": "CHI", "defteam": "GB", "play_type": "pass",
            "two_point_attempt": "0", "qb_kneel": "0", "sack": "0", "complete_pass": "0", "pass_touchdown": "0",
            "rush_touchdown": "0", "interception": "0", "td_player_id": "", "passer_player_id": "", "receiver_player_id": "",
            "rusher_player_id": "", "passing_yards": "", "receiving_yards": "", "rushing_yards": ""}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def test_positions_take_the_newest_week_and_fold_hb_fb():
    rows = [{"gsis_id": "a", "position": "WR", "week": "1"}, {"gsis_id": "a", "position": "TE", "week": "3"},
            {"gsis_id": "b", "position": "FB", "week": "2"}, {"gsis_id": "c", "position": "K", "week": "2"}]
    assert dvp.load_positions(rows) == {"a": "TE", "b": "RB"}


def test_allowed_by_game_counts_targets_catches_yards_tds_and_skips_sacks_and_two_point():
    plays = [
        _play(passer_player_id="qb1", receiver_player_id="te1", complete_pass=1, passing_yards=20, receiving_yards=20),
        _play(passer_player_id="qb1", receiver_player_id="te1", complete_pass=1, passing_yards=12, receiving_yards=12, pass_touchdown=1, td_player_id="te1"),
        _play(passer_player_id="qb1", receiver_player_id="te1"),  # incompletion: a target, no catch
        _play(passer_player_id="qb1", sack=1),  # a sack is not a target or an attempt here
        _play(passer_player_id="qb1", receiver_player_id="te1", complete_pass=1, receiving_yards=2, two_point_attempt=1),
        _play(play_type="run", rusher_player_id="rb1", rushing_yards=7),
        _play(play_type="run", rusher_player_id="rb1", rushing_yards=3, rush_touchdown=1, td_player_id="rb1"),
    ]
    game = dvp.allowed_by_game(plays, POS)[("GB", "g1")]
    assert dict(game["TE"]) == {"targets": 3.0, "receptions": 2.0, "rec_yds": 32.0, "rec_td": 1.0}
    assert game["QB"]["pass_yds"] == 32.0 and game["QB"]["completions"] == 2.0 and game["QB"]["pass_td"] == 1.0
    assert game["RB"]["rush_yds"] == 10.0 and game["RB"]["carries"] == 2.0 and game["RB"]["rush_td"] == 1.0


def test_per_game_rank_one_is_fewest_allowed():
    games = {
        ("GB", "g1"): {"QB": {}, "RB": {}, "WR": {}, "TE": {"rec_yds": 30.0}},
        ("GB", "g2"): {"QB": {}, "RB": {}, "WR": {}, "TE": {"rec_yds": 10.0}},
        ("DET", "g1"): {"QB": {}, "RB": {}, "WR": {}, "TE": {"rec_yds": 100.0}},
    }
    out = dvp.per_game_ranked(games)
    assert out["GB"]["TE"]["rec_yds"] == {"per_game": 20.0, "games": 2, "rank": 1, "of": 2}
    assert out["DET"]["TE"]["rec_yds"]["rank"] == 2


def test_run_writes_a_dated_file(tmp_path, monkeypatch):
    root = tmp_path / "nfl_source"
    (root / "tracking" / "nflverse" / "pbp").mkdir(parents=True)
    (root / "tracking" / "nflverse" / "roster").mkdir(parents=True)
    plays = [_play(week=3, passer_player_id="qb1", receiver_player_id="te1", complete_pass=1, passing_yards=9, receiving_yards=9)]
    with (root / "tracking" / "nflverse" / "pbp" / "pbp_2026.csv").open("w", newline="", encoding="utf-8") as handle:
        import csv

        writer = csv.DictWriter(handle, fieldnames=list(plays[0]))
        writer.writeheader()
        writer.writerows(plays)
    (root / "tracking" / "nflverse" / "roster" / "roster_2026.csv").write_text(
        "gsis_id,position,week,full_name\nqb1,QB,3,Caleb Williams\nte1,TE,3,Colston Loveland\n", encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_NFL_SOURCE_ROOT", str(root))
    summary = dvp.run()
    path = root / "tracking" / "derived" / "nfl_defense_vs_position_2026_wk03.json"
    assert summary["written"] == str(path) and json.loads(path.read_text())["teams"]["GB"]["TE"]["rec_yds"]["per_game"] == 9.0

    from syndicate.features import intelligence_recent_matchup as rm

    text = rm.nfl_vs_position_text({"player_name": "Colston Loveland", "market": "Receiving Yards"}, "GB")
    assert text == "Vs position: GB allows 9 receiving yards a game to TEs (rank 1 of 1, 1 = fewest; through week 3)."
    assert rm.nfl_vs_position_text({"player_name": "Colston Loveland", "market": "Receiving Yards"}, None) is None
    assert rm.nfl_vs_position_text({"player_name": "Nobody Here", "market": "Receiving Yards"}, "GB") is None
