"""Blowout bench rest in the native basketball engine (lane basketball-scenario-calibration, Phase 2 #4b, pre-registered
cc00ed23): EventSimConfig.blowout_bench_rest.

False is the default and changes nothing (the sampler receives blowout_boost_bench=False exactly as before). True turns
on the existing bench-boost branch of the per-possession sampler in blowout possessions only, so the top-5 by minutes
lose court time when the game is out of hand (real starters lose 4.38 min from close games to >=20-pt finals; the sim
lost 1.17)."""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local


def _engine(league: str):
    prev = os.environ.get("SYNDICATE_NBA_TEAM_INPUTS")
    os.environ["SYNDICATE_NBA_TEAM_INPUTS"] = "0"
    try:
        return _engine_for_league_local(league)
    finally:
        if prev is None:
            os.environ.pop("SYNDICATE_NBA_TEAM_INPUTS", None)
        else:
            os.environ["SYNDICATE_NBA_TEAM_INPUTS"] = prev


def _team(p: str) -> pd.DataFrame:
    # `_sim_min` is the column the engine reads for minutes weights (a `min`-only frame gives every player equal base
    # weight, and the boost then ranks the BENCH as "top-5 by weight" -- measured 2026-10-12: it inverted the effect).
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(10)], "min": mins, "_sim_min": [float(m) for m in mins]})


def _quarters(home_mu: float, away_mu: float):
    return [{"home_pts_mu": home_mu, "away_pts_mu": away_mu, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25}
            for _ in range(4)]


def _games(eng, n: int, *, home=128.0, away=96.0, **cfg):
    q = _quarters(home / 4.0, away / 4.0)
    return [eng.simulate_pbp_game_boxscore(np.random.default_rng(seed), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                           target_home_points=home, target_away_points=away, quarters=q) for seed in range(n)]


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_off_and_unset_equals_explicit_false(league):
    eng = _engine(league)
    assert eng.EventSimConfig().blowout_bench_rest is False
    assert _digest(_games(eng, 6)) == _digest(_games(eng, 6, blowout_bench_rest=False))


def test_rest_is_reachable_and_moves_points_off_the_top_five_in_blowouts():
    eng = _engine("nba")
    assert _digest(_games(eng, 6, blowout_bench_rest=True, bench_weight_boost=3.0)) != _digest(_games(eng, 6))

    def top5_share(games):
        shares = []
        for hb, _ab, _hq, _aq in games:
            players = hb["players"]
            tot = sum(float(p.get("pts") or 0) for p in players)
            names = {f"H{i}" for i in range(5)}
            top = sum(float(p.get("pts") or 0) for p in players if p.get("player_name") in names)
            if tot > 0:
                shares.append(top / tot)
        return float(np.mean(shares))

    off = top5_share(_games(eng, 60))
    on = top5_share(_games(eng, 60, blowout_bench_rest=True, bench_weight_boost=3.0))
    assert on < off - 0.02          # the bench takes a larger share of the leader's points once it is a blowout
