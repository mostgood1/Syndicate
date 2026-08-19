"""Unit tests for `historical_truth.boxscore_shot_strength` — the PP/PK SHOT-volume truth source
the goal-share truth (`historical_truth.contracts`) cannot reach (the `landing` feed has no
shot-by-strength-state breakdown; only the separate `boxscore` endpoint does).

Covers: the "saves/shots" string parsing, the DIRECTION (a goalie's own powerPlayShotsAgainst is
the OPPONENT's PP shot volume, verified against a real cross-check in the building session --
sum of the three splits equals shotsAgainst on a 20-game random sample), and the aggregators.
"""
from __future__ import annotations

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import (
    build_shot_strength_snapshot,
    compute_team_shot_strength_rates,
    parse_boxscore_shot_strength,
)


def _goalie(pp="0/0", sh="0/0", ev="0/0"):
    return {"powerPlayShotsAgainst": pp, "shorthandedShotsAgainst": sh, "evenStrengthShotsAgainst": ev}


def _boxscore(*, home_pp_against="7/7", away_pp_against="2/2", home_sh_against="0/0",
              away_sh_against="0/0", home_ev_against="10/10", away_ev_against="15/15"):
    return {
        "id": 1,
        "homeTeam": {"abbrev": "MTL"},
        "awayTeam": {"abbrev": "CAR"},
        "playerByGameStats": {
            "homeTeam": {"goalies": [_goalie(pp=home_pp_against, sh=home_sh_against, ev=home_ev_against)]},
            "awayTeam": {"goalies": [_goalie(pp=away_pp_against, sh=away_sh_against, ev=away_ev_against)]},
        },
    }


def test_parse_direction_home_pp_shots_come_from_away_goalies_pp_against():
    """MTL (home) PP shots = away (CAR) goalie's powerPlayShotsAgainst denominator."""
    rec = parse_boxscore_shot_strength(_boxscore(home_pp_against="7/7", away_pp_against="2/2"))
    assert rec is not None
    assert rec.away_pp_shots == 7   # from HOME goalie's PP-against
    assert rec.home_pp_shots == 2   # from AWAY goalie's PP-against


def test_parse_shorthanded_and_ev():
    rec = parse_boxscore_shot_strength(_boxscore(
        home_sh_against="1/3", away_sh_against="0/1", home_ev_against="10/28", away_ev_against="15/33",
    ))
    assert rec.away_sh_shots == 3   # home goalie's SH-against = away's SH shots
    assert rec.home_sh_shots == 1   # away goalie's SH-against = home's SH shots
    assert rec.away_ev_shots == 28
    assert rec.home_ev_shots == 33


def test_total_shots_sums_all_six_buckets():
    rec = parse_boxscore_shot_strength(_boxscore())
    assert rec.total_shots == rec.home_pp_shots + rec.away_pp_shots + rec.home_ev_shots + rec.away_ev_shots + rec.home_sh_shots + rec.away_sh_shots


def test_parse_missing_goalies_returns_none():
    payload = _boxscore()
    payload["playerByGameStats"]["homeTeam"]["goalies"] = []
    assert parse_boxscore_shot_strength(payload) is None


def test_parse_unparseable_fields_returns_none():
    payload = _boxscore()
    payload["playerByGameStats"]["homeTeam"]["goalies"] = [{"powerPlayShotsAgainst": "n/a"}]
    assert parse_boxscore_shot_strength(payload) is None


def test_parse_not_a_dict_returns_none():
    assert parse_boxscore_shot_strength(None) is None
    assert parse_boxscore_shot_strength({}) is None  # no homeTeam/awayTeam abbrev


def test_build_shot_strength_snapshot_math():
    recs = [
        parse_boxscore_shot_strength(_boxscore(home_pp_against="4/4", away_pp_against="6/6")),
        parse_boxscore_shot_strength(_boxscore(home_pp_against="2/2", away_pp_against="2/2")),
    ]
    snap = build_shot_strength_snapshot(recs)
    assert snap.n_games == 2
    total_pp = (6 + 4) + (2 + 2)  # away_pp_shots(from home-against) + home_pp_shots(from away-against), summed
    total_shots = sum(r.total_shots for r in recs)
    assert snap.pp_shot_share == round(total_pp / total_shots, 4)


def test_build_shot_strength_snapshot_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        build_shot_strength_snapshot([])


def test_compute_team_shot_strength_rates_pk_is_opponents_pp():
    recs = [parse_boxscore_shot_strength(_boxscore(home_pp_against="7/7", away_pp_against="2/2"))]
    rates = compute_team_shot_strength_rates(recs)
    # MTL (home): PP shots = 2 (from away-against), PK shots-against = 7 (CAR's PP shots)
    assert rates["MTL"].pp_shots_per_game == 2.0
    assert rates["MTL"].pk_shots_against_per_game == 7.0
    # CAR (away): PP shots = 7, PK shots-against = 2 (MTL's PP shots)
    assert rates["CAR"].pp_shots_per_game == 7.0
    assert rates["CAR"].pk_shots_against_per_game == 2.0
