"""The engine's efficiency-multiplier bounds as LeagueParams fields (lane wncaab-module, 2026-11-03).

NBA/WNBA keep the vendored literals (solve 0.70-1.30, final clip 0.75-1.25). College leagues widen both, because a
college mismatch needs a team far outside them and the sim then fell short of its own target (women's sims: total
-3.2, margin -4.1 on 2026-11-03)."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from syndicate.features.basketball_engine import league_params
from syndicate.features.basketball_engine.league_engine import LeagueEngine
from syndicate.features.shared import basketball_props_smart_sim as bpss

VENDORED = ((0.70, 1.30), (0.75, 1.25))


def _team(p: str) -> pd.DataFrame:
    mins = [34, 33, 32, 30, 28, 18, 12, 8, 5]
    n = len(mins)
    return pd.DataFrame({"player_name": [f"{p}{i}" for i in range(n)], "min": mins, "_sim_min": [float(m) for m in mins],
                         "_prior_fga_pm": [0.36] * n, "_prior_threes_att_pm": [0.12] * n, "_prior_threes_pm": [0.038] * n,
                         "_prior_fgm_pm": [0.15] * n, "_prior_fta_pm": [0.10] * n, "_prior_ftm_pm": [0.072] * n})


def _engine(code: str, **bounds) -> LeagueEngine:
    params = dataclasses.replace(league_params(code), exact_target_calibration=True, **bounds)
    return LeagueEngine(params, sample_lineup=bpss._sample_lineup_local)


def _mean_margin_and_total(eng: LeagueEngine, n: int, home: float, away: float) -> tuple[float, float]:
    margins, totals = [], []
    for s in range(n):
        _, _, hq, aq = eng.simulate_pbp_game_boxscore(np.random.default_rng(s), _team("H"), _team("A"),
                                                       cfg=eng.EventSimConfig(possessions_per_game=70.0),
                                                       target_home_points=home, target_away_points=away)
        margins.append(sum(hq) - sum(aq))
        totals.append(sum(hq) + sum(aq))
    return float(np.mean(margins)), float(np.mean(totals))


@pytest.mark.parametrize("code", ["nba", "wnba"])
def test_nba_and_wnba_keep_the_vendored_bounds(code):
    params = league_params(code)
    assert (params.exact_target_solve_bounds, params.eff_mult_final_bounds) == VENDORED


@pytest.mark.parametrize("code", ["ncaab", "wncaab"])
def test_college_bounds_contain_the_vendored_ones(code):
    params = league_params(code)
    solve, final = params.exact_target_solve_bounds, params.eff_mult_final_bounds
    assert solve[0] < VENDORED[0][0] and solve[1] > VENDORED[0][1]
    assert final[0] < VENDORED[1][0] and final[1] > VENDORED[1][1]


def test_the_bounds_are_reachable_a_blowout_target_moves():
    """off != on: the same blowout target, the vendored bounds against the league's. The wide bounds land closer."""
    home, away = 100.0, 46.0
    narrow = _mean_margin_and_total(_engine("wncaab", exact_target_solve_bounds=VENDORED[0], eff_mult_final_bounds=VENDORED[1]), 40, home, away)
    wide = _mean_margin_and_total(_engine("wncaab"), 40, home, away)
    assert narrow != wide
    assert abs(wide[0] - (home - away)) < abs(narrow[0] - (home - away)) - 5.0, (narrow, wide)
    assert abs(wide[1] - (home + away)) < 6.0, wide


def test_a_close_game_is_not_moved_by_the_wide_bounds():
    """Inside the vendored range the bounds never bind: the same draws, the same result."""
    home, away = 68.0, 64.0
    narrow = _mean_margin_and_total(_engine("wncaab", exact_target_solve_bounds=VENDORED[0], eff_mult_final_bounds=VENDORED[1]), 10, home, away)
    wide = _mean_margin_and_total(_engine("wncaab"), 10, home, away)
    assert narrow == wide


def test_the_bounds_are_in_the_provenance_and_the_pregame_key(monkeypatch):
    from syndicate.features.college_basketball import pregame_sim as ps
    from syndicate.features.ncaab import live_resim as lr

    monkeypatch.setattr(lr, "team_frame", lambda rows, team_code, date: f"frame:{team_code}")
    prior = SimpleNamespace(possessions=70.0, home_points=72.0, away_points=66.0, total=138.0, home_margin=6.0,
                            ratings_as_of=__import__("datetime").date(2026, 11, 2), prior_season_fallback=True)
    priors = SimpleNamespace(by_team={"1": [{}], "2": [{}]}, as_of=__import__("datetime").date(2026, 11, 2))
    prov = lr.build_engine_inputs("2026-11-03", "1", "2", neutral=False, priors=priors, team_prior=prior, league="wncaab")["_provenance"]
    params = league_params("wncaab")
    assert prov["effMultBounds"] == {"solve": list(params.exact_target_solve_bounds), "final": list(params.eff_mult_final_bounds)}
    other = dict(prov, effMultBounds={"solve": list(VENDORED[0]), "final": list(VENDORED[1])})
    assert ps.inputs_key(prov, 200) != ps.inputs_key(other, 200), "a new bound must re-sim a published game"
