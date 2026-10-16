"""Shooting fouls on threes in the native basketball engine (lane basketball-scenario-calibration, round 2 R2-c,
pre-registered c35e8e89): EventSimConfig.foul_3pa_mult.

1.0 (default) changes nothing. Below 1.0 a three is fouled less often (real: 0.41 three-shot trips per team-game vs ~1.5
in the sim), which, with FOULED_MISS_NOT_FGA, stops fouled missed threes leaving 3PA and inflating 3P%. The EXACT solver
helpers take the same multiplier and keep their old arithmetic at 1.0."""
from __future__ import annotations

import dataclasses
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from syndicate.features.basketball_engine import engine as E
from syndicate.features.shared import basketball_props_smart_sim as bpss


@pytest.fixture(autouse=True)
def _team_inputs_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NBA_TEAM_INPUTS", "0")


def _team(p: str) -> pd.DataFrame:
    mins = [36, 35, 34, 33, 32, 24, 18, 14, 9, 5]
    n = len(mins)
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
                         "_prior_fga_pm": [0.40] * n, "_prior_threes_att_pm": [0.17] * n, "_prior_threes_pm": [0.0612] * n,
                         "_prior_fgm_pm": [0.188] * n, "_prior_fta_pm": [0.11] * n, "_prior_ftm_pm": [0.086] * n})


def _quarters():
    return [{"home_pts_mu": 28.0, "away_pts_mu": 27.0, "home_pts_sigma": 6.5, "away_pts_sigma": 6.5, "corr": 0.25} for _ in range(4)]


def _engine(**lp):
    from syndicate.features.basketball_engine import league_params
    from syndicate.features.basketball_engine.league_engine import LeagueEngine

    return LeagueEngine(dataclasses.replace(league_params("nba"), **lp), sample_lineup=bpss._sample_lineup_local)


def _run(eng, n, **cfg):
    return [eng.simulate_pbp_game_boxscore(np.random.default_rng(s), _team("H"), _team("A"), cfg=eng.EventSimConfig(**cfg),
                                           target_home_points=112.0, target_away_points=108.0, quarters=_quarters()) for s in range(n)]


def _digest(games) -> str:
    h = hashlib.sha256()
    for g in games:
        h.update(json.dumps(g, sort_keys=True, default=str).encode())
    return h.hexdigest()


@pytest.mark.parametrize("league", ["nba", "wnba"])
def test_default_is_off_and_equals_explicit_one(league):
    eng = bpss._engine_for_league_local(league)
    assert eng.EventSimConfig().foul_3pa_mult == 1.0
    assert _digest(_run(eng, 3)) == _digest(_run(eng, 3, foul_3pa_mult=1.0))


def test_solver_helpers_keep_their_arithmetic_at_one():
    args = dict(p_tov=0.12, p3=0.41, fg2=0.55, fg3=0.36, foul=0.10, oreb=0.24)
    assert E._iterations_per_possession(**args) == E._iterations_per_possession(**args, foul3_mult=1.0)
    lp_args = (0.12, 0.41, 0.55, 0.36, 0.10, 0.78, 0.24, 1.05)
    assert E._loop_points_per_possession(*lp_args) == E._loop_points_per_possession(*lp_args, foul3_mult=1.0)
    assert E._solve_eff_mult(1.15, 0.12, 0.41, 0.55, 0.36, 0.10, 0.78, 0.24) == \
        E._solve_eff_mult(1.15, 0.12, 0.41, 0.55, 0.36, 0.10, 0.78, 0.24, foul3_mult=1.0)
    # Fewer fouls on threes -> fewer FT points per possession at the same eff.
    assert E._loop_points_per_possession(*lp_args, foul3_mult=0.3) < E._loop_points_per_possession(*lp_args)


def test_reachable_and_cuts_three_shot_trips_and_3p_pct():
    eng = _engine(fouled_miss_not_fga=True)
    off = _run(eng, 60)
    on = _run(eng, 60, foul_3pa_mult=0.25)
    assert _digest(on) != _digest(off)

    def pct3(games):
        m = a = 0
        for hb, ab, _hq, _aq in games:
            for box in (hb, ab):
                for p in box["players"]:
                    m += int(p.get("threes") or 0); a += int(p.get("fg3a") or 0)
        return m / a

    assert pct3(on) < pct3(off) - 0.005   # fouled missed threes stop leaving 3PA


def test_foul_2pa_mult_default_off_and_reachable():
    eng = bpss._engine_for_league_local("nba")
    assert eng.EventSimConfig().foul_2pa_mult == 1.0
    assert _digest(_run(eng, 3)) == _digest(_run(eng, 3, foul_2pa_mult=1.0))
    e2 = _engine(fouled_miss_not_fga=True)

    def fta(games):
        return sum(int(p.get("fta") or 0) for hb, ab, _hq, _aq in games for box in (hb, ab) for p in box["players"])

    assert fta(_run(e2, 30, foul_2pa_mult=1.8)) > fta(_run(e2, 30)) * 1.2
