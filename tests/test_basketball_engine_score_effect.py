"""Late-game catch-up / score effects in the native basketball engine (lane basketball-scenario-calibration, Phase 2 #2,
pre-registered 10da26d5): EventSimConfig.score_effect_k.

k = 0 is the default and changes nothing (the factor is exactly 1.0, no RNG draw). k > 0 pulls the offense's make
probability down when it leads by more than expected and up when it trails, so a draw's second-half margin moves
against its first-half margin (real games: line-adjusted slope -0.17; the sim was 0.00) without moving the mean."""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local

QUARTERS = [{"home_pts_mu": 28.5, "away_pts_mu": 27.5, "home_pts_sigma": 6.5, "away_pts_sigma": 6.3, "corr": 0.25},
            {"home_pts_mu": 28.0, "away_pts_mu": 27.8, "home_pts_sigma": 6.4, "away_pts_sigma": 6.4, "corr": 0.25},
            {"home_pts_mu": 28.6, "away_pts_mu": 28.0, "home_pts_sigma": 6.6, "away_pts_sigma": 6.5, "corr": 0.25},
            {"home_pts_mu": 27.0, "away_pts_mu": 26.5, "home_pts_sigma": 6.9, "away_pts_sigma": 6.8, "corr": 0.3}]


def _team(p: str) -> pd.DataFrame:
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(10)], "min": [34, 33, 32, 31, 30, 25, 20, 15, 10, 10]})


def _games(eng, n: int, **cfg):
    out = []
    for seed in range(n):
        out.append(eng.simulate_pbp_game_boxscore(np.random.default_rng(seed), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                                  target_home_points=110.0, target_away_points=110.0, quarters=QUARTERS))
    return out


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_off_and_unset_equals_explicit_zero(league):
    eng = _engine_for_league_local(league)
    assert eng.EventSimConfig().score_effect_k == 0.0
    assert _digest(_games(eng, 6)) == _digest(_games(eng, 6, score_effect_k=0.0))


def test_k_is_reachable_and_produces_reversion_without_moving_the_mean():
    eng = _engine_for_league_local("nba")
    assert _digest(_games(eng, 6, score_effect_k=0.02)) != _digest(_games(eng, 6))

    def halves(games):
        h1 = np.array([sum(hq[:2]) - sum(aq[:2]) for _hb, _ab, hq, aq in games], float)
        h2 = np.array([sum(hq[2:4]) - sum(aq[2:4]) for _hb, _ab, hq, aq in games], float)
        x = h1 - h1.mean()
        return float((x * (h2 - h2.mean())).sum() / (x * x).sum()), float((h1 + h2).mean())

    slope_off, mean_off = halves(_games(eng, 160))
    slope_on, mean_on = halves(_games(eng, 160, score_effect_k=0.02))
    assert slope_on < slope_off - 0.10          # a first-half lead is given back in the second half
    assert abs(mean_on - mean_off) < 2.0        # symmetric around the expected lead: the mean margin does not move
