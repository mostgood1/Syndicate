"""Unit tests for `historical_truth.boxscore_block_rate` — the last remaining special-teams gap:
`block_rate_ev`/`block_rate_pk`/`block_rate_pp_def` had no per-team signal and had never been
checked against a real block rate at all (the vendor's 0.45/0.55/0.35 defaults were never
measured against anything).
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_block_rate import (
    DEFAULT_BLOCK_INDEX,
    MIN_GAMES_FOR_BLOCK_INDEX,
    build_league_block_rate_snapshot,
    compute_team_block_rate_index,
    parse_boxscore_block_rate,
)


def _skater(blocks: int) -> dict:
    return {"blockedShots": blocks}


def _boxscore(*, home_team="MTL", away_team="CAR", home_sog=30, away_sog=25,
              home_blocks=(6, 4), away_blocks=(3, 2)):
    """`home_blocks`/`away_blocks` are (forwards_total, defense_total) tuples, split across two
    synthetic skaters each so the group-summing logic is actually exercised."""
    return {
        "id": 1,
        "homeTeam": {"abbrev": home_team, "sog": home_sog},
        "awayTeam": {"abbrev": away_team, "sog": away_sog},
        "playerByGameStats": {
            "homeTeam": {"forwards": [_skater(home_blocks[0])], "defense": [_skater(home_blocks[1])]},
            "awayTeam": {"forwards": [_skater(away_blocks[0])], "defense": [_skater(away_blocks[1])]},
        },
    }


def test_parse_sums_forwards_and_defense():
    rec = parse_boxscore_block_rate(_boxscore(home_blocks=(6, 4), away_blocks=(3, 2)))
    assert rec is not None
    assert rec.home_blocks == 10
    assert rec.away_blocks == 5


def test_parse_shots_faced_is_opponent_sog_plus_own_blocks():
    rec = parse_boxscore_block_rate(_boxscore(home_sog=30, away_sog=25, home_blocks=(6, 4), away_blocks=(3, 2)))
    # HOME faces AWAY's attempts: away's sog (25) + shots home blocked (10).
    assert rec.home_shots_faced == 25 + 10
    assert rec.away_shots_faced == 30 + 5


def test_parse_missing_playerByGameStats_returns_none():
    payload = _boxscore()
    payload["playerByGameStats"] = {}
    assert parse_boxscore_block_rate(payload) is None


def test_parse_missing_sog_returns_none():
    payload = _boxscore()
    del payload["homeTeam"]["sog"]
    assert parse_boxscore_block_rate(payload) is None


def test_parse_not_a_dict_or_missing_abbrev_returns_none():
    assert parse_boxscore_block_rate(None) is None
    assert parse_boxscore_block_rate({}) is None


def test_league_snapshot_math():
    recs = [
        parse_boxscore_block_rate(_boxscore(home_sog=20, away_sog=20, home_blocks=(5, 0), away_blocks=(5, 0))),
        parse_boxscore_block_rate(_boxscore(home_sog=20, away_sog=20, home_blocks=(5, 0), away_blocks=(5, 0))),
    ]
    snap = build_league_block_rate_snapshot(recs)
    assert snap.n_games == 2
    # Each game: total blocks 10, total shots faced (20+5)+(20+5)=50 -> rate 10/50=0.2, both games identical.
    assert snap.league_block_rate == pytest.approx(0.2)
    assert snap.blocks_per_game == pytest.approx(5.0)  # 10 blocks / 2 teams per game


def test_league_snapshot_empty_raises():
    with pytest.raises(ValueError):
        build_league_block_rate_snapshot([])


def test_index_neutral_below_games_floor():
    recs = [parse_boxscore_block_rate(_boxscore()) for _ in range(3)]
    assert 3 < MIN_GAMES_FOR_BLOCK_INDEX
    idx = compute_team_block_rate_index(recs)
    assert idx["MTL"].block_index == DEFAULT_BLOCK_INDEX


def test_index_reflects_a_real_above_average_blocker():
    n = MIN_GAMES_FOR_BLOCK_INDEX + 5
    # MTL blocks heavily (10/game), CAR lightly (2/game) -- enough games to clear the floor.
    recs = [parse_boxscore_block_rate(_boxscore(home_blocks=(6, 4), away_blocks=(1, 1))) for _ in range(n)]
    idx = compute_team_block_rate_index(recs)
    assert idx["MTL"].block_index > 1.0
    assert idx["CAR"].block_index < 1.0


def test_index_missing_data_is_empty_not_a_crash():
    assert compute_team_block_rate_index([]) == {}
