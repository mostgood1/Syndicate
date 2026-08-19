"""Unit tests for `historical_truth.boxscore_shot_strength` — the PP/PK SHOT-volume truth source
the goal-share truth (`historical_truth.contracts`) cannot reach (the `landing` feed has no
shot-by-strength-state breakdown; only the separate `boxscore` endpoint does).

Covers: the "saves/shots" string parsing, the DIRECTION (a goalie's own powerPlayShotsAgainst is
the OPPONENT's PP shot volume, verified against a real cross-check in the building session --
sum of the three splits equals shotsAgainst on a 20-game random sample), and the aggregators.
"""
from __future__ import annotations

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.boxscore_shot_strength import (
    DEFAULT_SHOT_INDEX,
    MIN_OPPORTUNITIES_FOR_SHOT_INDEX,
    build_shot_strength_snapshot,
    compute_team_shot_rate_index,
    compute_team_shot_strength_rates,
    parse_boxscore_shot_strength,
)


def _goalie(pp="0/0", sh="0/0", ev="0/0"):
    return {"powerPlayShotsAgainst": pp, "shorthandedShotsAgainst": sh, "evenStrengthShotsAgainst": ev}


def _boxscore(*, home_pp_against="7/7", away_pp_against="2/2", home_sh_against="0/0",
              away_sh_against="0/0", home_ev_against="10/10", away_ev_against="15/15",
              home_team="MTL", away_team="CAR"):
    return {
        "id": 1,
        "homeTeam": {"abbrev": home_team},
        "awayTeam": {"abbrev": away_team},
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


# ---------------------------------------------------------------------------
# compute_team_shot_rate_index -- the per-team, opportunity-normalized signal
# `docs/ai_context/hockeysim_engine_reference.md` §2f wires into the engine.
# ---------------------------------------------------------------------------


def _many_games(n: int, *, home="AAA", away="BBB", home_pp_shots=6, away_pp_shots=4) -> list:
    """`n` identical games (enough opportunities to clear MIN_OPPORTUNITIES_FOR_SHOT_INDEX)."""
    out = []
    for _ in range(n):
        # away's PP shots come from HOME goalie's PP-against; home's PP shots from AWAY goalie's.
        out.append(parse_boxscore_shot_strength(_boxscore(
            home_pp_against=f"0/{away_pp_shots}", away_pp_against=f"0/{home_pp_shots}",
            home_team=home, away_team=away,
        )))
    return out


def test_index_is_neutral_when_below_the_opportunity_floor():
    # 3 opportunities per team, well under MIN_OPPORTUNITIES_FOR_SHOT_INDEX.
    recs = _many_games(3)
    idx = compute_team_shot_rate_index(recs, {"AAA": 3, "BBB": 3}, {"AAA": 3, "BBB": 3})
    assert idx["AAA"].pp_shot_index == DEFAULT_SHOT_INDEX
    assert idx["AAA"].pk_shot_index_allowed == DEFAULT_SHOT_INDEX


def test_index_reflects_a_real_above_average_generator():
    # AAA generates 6 PP shots/game (above the league mix once BBB's lower rate is mixed in);
    # enough opportunities (>= MIN_OPPORTUNITIES_FOR_SHOT_INDEX) for a real index.
    n = MIN_OPPORTUNITIES_FOR_SHOT_INDEX + 5
    recs = _many_games(n, home_pp_shots=6, away_pp_shots=2)
    idx = compute_team_shot_rate_index(recs, {"AAA": n, "BBB": n}, {"AAA": n, "BBB": n})
    # AAA (home every game here) generates more shots per PP chance than the league mix -> > 1.0.
    assert idx["AAA"].pp_shot_index > 1.0
    assert idx["BBB"].pp_shot_index < 1.0


def test_index_league_mean_is_approximately_one_by_construction():
    """Every team's index is measured against the SAME league-wide reference ratio, so the
    (unweighted) mean across teams should land close to 1.0 -- verified on real data in the
    building session (mean 1.0056/1.0056 across 32 real teams); this locks the PROPERTY, not the
    exact real-data numbers, with a small synthetic league."""
    n = MIN_OPPORTUNITIES_FOR_SHOT_INDEX + 10
    recs: list = []
    pp_opp: dict = {}
    pk_opp: dict = {}
    # 4 teams round-robin, each with a different shot-generation level.
    levels = {"AAA": 8, "BBB": 6, "CCC": 4, "DDD": 2}
    teams = list(levels)
    for h in teams:
        for a in teams:
            if h == a:
                continue
            for _ in range(3):  # a few games per pairing to build up opportunity volume
                recs.append(parse_boxscore_shot_strength(_boxscore(
                    home_pp_against=f"0/{levels[a]}", away_pp_against=f"0/{levels[h]}",
                    home_team=h, away_team=a,
                )))
                pp_opp[h] = pp_opp.get(h, 0) + 1
                pp_opp[a] = pp_opp.get(a, 0) + 1
                pk_opp[h] = pk_opp.get(h, 0) + 1
                pk_opp[a] = pk_opp.get(a, 0) + 1
    idx = compute_team_shot_rate_index(recs, pp_opp, pk_opp)
    mean_pp = sum(r.pp_shot_index for r in idx.values()) / len(idx)
    assert 0.9 < mean_pp < 1.1


def test_index_missing_team_data_is_neutral_not_a_crash():
    idx = compute_team_shot_rate_index([], {}, {})
    assert idx == {}
