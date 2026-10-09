"""WNBA PBP engine: team-level calibration (lane wnba-sim-team-calibration).

Component backtest 2026-10-01 (actual minutes, possessions and team points held
fixed): sim FGA 1.25x actual, FG% 0.396 vs 0.462, and team points +4.7 over the
target the engine was GIVEN. On the production path the live LVA-IND sim scored
198.0 against an anchored target of 180.8. Three switches, each tested here for
reachability (off != on) and for the property it exists to restore.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

from syndicate.features.basketball_engine import WNBA  # noqa: E402
from syndicate.features.basketball_engine.league_engine import LeagueEngine  # noqa: E402

# The WNBA engine with its default lineup sampler -- what this file tested when it called the vendored module
# directly (native since 2026-10-09, lane basketball-native-engine; parity-gated against the vendored engine).
events = LeagueEngine(WNBA)
pytestmark = pytest.mark.skipif(events is None, reason="vendored wnba engine not importable")

FLAGS = ("FOULED_MISS_NOT_FGA", "EXACT_TARGET_CALIBRATION", "TEAM_PRIOR_STACKS_ON_TARGET")


@pytest.fixture(autouse=True)
def _restore_flags():
    saved = {f: getattr(events, f) for f in FLAGS}
    yield
    for f, v in saved.items():
        setattr(events, f, v)


def _team(n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    tpa = fga * np.array([0.25, 0.5, 0.3, 0.45, 0.2, 0.4, 0.35, 0.3, 0.5, 0.2])[:n]
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    fta = np.array([0.30] + [0.08] * (n - 1))
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_threes_att_pm": tpa, "_prior_threes_pm": tpa * 0.34,
        "_prior_fgm_pm": (fga - tpa) * 0.52 + tpa * 0.34,
        "_prior_fta_pm": fta, "_prior_ftm_pm": fta * 0.8, "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n,
        "_prior_ast_pm": [0.08] * n, "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [0.02] * n, "_prior_tov_pm": [0.055] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def _run(n: int = 80, seed: int = 11, **kw) -> dict:
    rng = np.random.default_rng(seed)
    tot = {"pts": 0.0, "fga": 0.0, "fgm": 0.0, "fta": 0.0}
    for _ in range(n):
        hb, _ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(), _team(), **kw)
        for k in tot:
            tot[k] += sum(float(p[k]) for p in hb["players"]) / n
    return tot


def test_loop_shot_share_is_a_distribution_flatter_than_raw_volume():
    team = _team()
    mins = team["_sim_min"].to_numpy()
    share = events._loop_shot_share(team, mins, "_prior_fga_pm")
    raw = team["_prior_fga_pm"].to_numpy() * mins
    raw = raw / raw.sum()
    assert share.sum() == pytest.approx(1.0)
    assert share[0] < raw[0]          # the loop compresses the top shooter's volume
    assert share[-1] > raw[-1]        # and floors the end of the bench


def test_solver_inverts_the_points_per_possession_model():
    args = dict(p_tov=0.15, p3=0.36, fg2=0.50, fg3=0.34, foul=0.20, ft=0.80, oreb=0.24)
    for target in (0.95, 1.05, 1.15):
        eff = events._solve_eff_mult(target, **args)
        assert events._loop_points_per_possession(eff=eff, **args) == pytest.approx(target, abs=1e-6)
    lo = events._loop_points_per_possession(eff=0.9, **args)
    assert events._loop_points_per_possession(eff=1.1, **args) > lo


def test_reachability_fouled_miss_is_not_an_fga_and_scores_identically():
    events.FOULED_MISS_NOT_FGA = False
    off = _run(target_home_points=85.0, target_away_points=85.0)
    events.FOULED_MISS_NOT_FGA = True
    on = _run(target_home_points=85.0, target_away_points=85.0)
    assert on["fga"] < off["fga"] * 0.97        # fouled misses leave the FGA column
    assert on["fgm"] == off["fgm"] and on["pts"] == off["pts"]  # same draws: accounting only


def test_reachability_exact_calibration_lands_on_the_target():
    # Realistic WNBA team targets. Known residual, measured 2026-10-01: for a target far
    # below the team's natural level (78 for this synthetic team) the loop lands ~2-2.5
    # pts under (the PPP model drifts at low make rates); real-game team points stay
    # within 0.6% (component backtest, 191 fully-matched team-games).
    for target in (82.0, 92.0):
        events.EXACT_TARGET_CALIBRATION = False
        off = _run(n=150, target_home_points=target, target_away_points=target)["pts"]
        events.EXACT_TARGET_CALIBRATION = True
        on = _run(n=150, target_home_points=target, target_away_points=target)["pts"]
        assert abs(on - target) < 2.0
        if target == 82.0:  # the old helper overshoots here; at 92 it lands near by accident
            assert abs(on - target) < abs(off - target)


def test_team_prior_does_not_stack_on_a_target_but_still_applies_without_one():
    adj = {"eff_mult": 1.10}
    kw = dict(target_home_points=85.0, target_away_points=85.0, home_team_adj=adj, away_team_adj=adj)
    events.TEAM_PRIOR_STACKS_ON_TARGET = True
    stacked = _run(**kw)["pts"]
    events.TEAM_PRIOR_STACKS_ON_TARGET = False
    unstacked = _run(**kw)["pts"]
    assert stacked > unstacked + 4.0           # off != on
    assert abs(unstacked - 85.0) < 2.5
    # No target: the prior is the only efficiency signal and must still apply.
    # 200 draws: at 60 the +4 bound sat ~2 SE from the true ~+7 lift and flaked.
    plain = _run(n=200)["pts"]
    boosted = _run(n=200, home_team_adj=adj, away_team_adj=adj)["pts"]
    assert boosted > plain + 4.0
