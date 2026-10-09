"""WNBA PBP engine: free throws follow the shooter (lane wnba-sim-star-shortfall).

Decomposition 2026-10-01 (36 games, actual minutes + team points fixed): top-2
scorers took the right number of shots (FGA ratio 1.02) but drew 0.220 FTA/FGA in
the sim vs 0.376 real -- the engine drew `foul` from a TEAM rate before choosing
the shooter, so every player got the same FT rate.
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


def _team(star_fta_pm: float, n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    fta = np.array([star_fta_pm] + [0.06] * (n - 1))
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_fgm_pm": fga * 0.45, "_prior_threes_att_pm": fga * 0.3, "_prior_threes_pm": fga * 0.1,
        "_prior_fta_pm": fta, "_prior_ftm_pm": fta * 0.8, "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n,
        "_prior_ast_pm": [0.08] * n, "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [0.02] * n, "_prior_tov_pm": [0.05] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def test_multipliers_are_shot_weighted_mean_one_and_favour_foul_drawers():
    team = _team(0.30)
    mult = events._ft_rate_multipliers(team, team["_sim_min"].to_numpy())
    w = team["_prior_fga_pm"].to_numpy() * team["_sim_min"].to_numpy()
    assert float((mult * w).sum() / w.sum()) == pytest.approx(1.0)
    # The star (5x the FTA rate of everyone else) gets by far the largest multiplier;
    # it is a per-SHOT ratio, so low-volume players with the same FTA rank above the mid-rotation.
    assert mult[0] == mult.max() and mult[0] > 1.8
    assert mult[1] < 1.0


def test_unknown_rates_get_a_neutral_multiplier():
    team = _team(0.30)
    team.loc[3, "_prior_fga_pm"] = 0.0
    assert events._ft_rate_multipliers(team, team["_sim_min"].to_numpy())[3] == 1.0


def _star_ft_share(flag: bool) -> tuple[float, float]:
    events.SHOOTER_FT_RATE = flag
    try:
        rng = np.random.default_rng(3)
        star_fta = star_fga = team_fta = 0
        for _ in range(60):
            hb, _ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(0.30), _team(0.06), target_home_points=85.0, target_away_points=85.0)
            p0 = hb["players"][0]
            star_fta += p0["fta"]
            star_fga += p0["fga"]
            team_fta += sum(p["fta"] for p in hb["players"])
        return star_fta / max(star_fga, 1), team_fta / 60
    finally:
        events.SHOOTER_FT_RATE = True


def test_reachability_the_switch_changes_who_shoots_free_throws():
    off_rate, off_team = _star_ft_share(False)
    on_rate, on_team = _star_ft_share(True)
    assert on_rate > off_rate * 1.5           # the star now draws fouls at her own rate
    assert on_team == pytest.approx(off_team, rel=0.25)  # the team's free throws are not inflated
