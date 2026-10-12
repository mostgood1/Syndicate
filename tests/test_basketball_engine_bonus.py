"""Bonus free-throw mechanism in the native engine (lane ncaab-native-live-tier, user 2026-10-12).

Default OFF and draw-for-draw identical (P1's parity tests are the proof of that); these pin what ON does:
reachable, half-scoped for NCAAB, seeded from a resumed GameState, and inert at rate 0 for the score.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from syndicate.features.basketball_engine import EventSimConfig, GameState, league_params, simulate_pbp_game_boxscore
from syndicate.features.ncaab import live_resim as lr

NCAAB = league_params("ncaab")
RATES = {"pts_pm": 0.42, "fga_pm": 0.33, "fgm_pm": 0.15, "threes_att_pm": 0.13, "threes_pm": 0.045, "fta_pm": 0.11,
         "ftm_pm": 0.08, "oreb_pm": 0.04, "dreb_pm": 0.1, "reb_pm": 0.14, "ast_pm": 0.07, "tov_pm": 0.055, "stl_pm": 0.03,
         "blk_pm": 0.015, "pf_pm": 0.075}


def _frame(team):
    rows = [{"player_name": f"{team}{i}", "athlete_id": f"{team}{i}", "min_proj": [34, 32, 30, 28, 26, 20, 15, 10, 5][i],
             "starter_prob": 1.0 if i < 5 else 0.0, **RATES} for i in range(9)]
    return lr.team_frame(rows, team_code=team, date="2026-01-10")


KW = {"home_players": _frame("H"), "away_players": _frame("A"), "target_home_points": 73.0, "target_away_points": 69.0}


def _run(cfg, seed, state=None):
    return simulate_pbp_game_boxscore(rng=np.random.default_rng(seed), cfg=cfg, league=NCAAB, state=state, **KW)


def _fta(box):
    return sum(int(p.get("fta") or 0) for p in box["players"])


BASE = EventSimConfig(possessions_per_game=68.0)
ON = replace(BASE, bonus_free_throws=True, bonus_nonshoot_foul_per_poss=0.12)


def test_on_at_rate_zero_leaves_every_score_unchanged():
    """The legacy noise draw keeps its place (rate 0), so the RNG stream -- and every point -- is the default's."""
    zero = replace(BASE, bonus_free_throws=True, bonus_nonshoot_foul_per_poss=0.0)
    for seed in range(3):
        off, on = _run(BASE, seed), _run(zero, seed)
        assert off[2:] == on[2:]


def test_reachable_off_is_not_on():
    assert any(_run(BASE, s)[2:] != _run(ON, s)[2:] for s in range(3))


def test_bonus_trips_raise_second_half_free_throws_and_total_points():
    """NCAAB fouls accumulate per HALF, so a half's late possessions are in the bonus: more FTA, more points."""
    n = 40
    off_pts = np.mean([sum(_run(BASE, s)[2]) + sum(_run(BASE, s)[3]) for s in range(n)])
    on_runs = [_run(ON, s) for s in range(n)]
    on_pts = np.mean([sum(r[2]) + sum(r[3]) for r in on_runs])
    off_fta = np.mean([_fta(_run(BASE, s)[0]) + _fta(_run(BASE, s)[1]) for s in range(n)])
    on_fta = np.mean([_fta(r[0]) + _fta(r[1]) for r in on_runs])
    assert on_fta > off_fta + 4, (off_fta, on_fta)
    assert on_pts > off_pts, (off_pts, on_pts)


def test_a_resume_inside_the_half_is_seeded_from_the_live_team_fouls():
    """Away already on 12 team fouls (home shoots two on every non-shooting foul) vs 0: more home free throws."""
    def home_fta(away_fouls):
        gs = GameState(period=2, seconds_remaining=900, home_period_pts=(35, 5), away_period_pts=(34, 6),
                       possession="home", home_team_fouls=0, away_team_fouls=away_fouls)
        return np.mean([_fta(_run(ON, s, gs)[0]) for s in range(30)])

    assert home_fta(12) > home_fta(0)


def test_tip_resume_still_equals_pregame_with_the_mechanism_on():
    tip = GameState(period=1, seconds_remaining=None, home_period_pts=(0,), away_period_pts=(0,))
    for seed in range(2):
        assert _run(ON, seed)[2:] == _run(ON, seed, tip)[2:]
