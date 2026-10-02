"""WNBA PBP engine: the foul probability is solved from FTA/FGA (lane wnba-sim-ft-trips-2).

foul_per_fga used to be clip(FTA/FGA, 0.05, 0.20) -- not a foul probability, and capped
below the real ~0.31 -- so sim FTA ran 0.889x on games where both rosters fully match
the box score, and the missing FT trips became extra FGAs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

events = sim._import_real_events_module_local(package_name="wnba_betting")
pytestmark = pytest.mark.skipif(events is None, reason="vendored wnba engine not importable")


@pytest.fixture(autouse=True)
def _restore_flag():
    saved = events.FOUL_RATE_SOLVED
    yield
    events.FOUL_RATE_SOLVED = saved


def _team(fta_ratio: float = 0.30, n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_threes_att_pm": fga * 0.35, "_prior_threes_pm": fga * 0.12,
        "_prior_fgm_pm": fga * 0.45, "_prior_fta_pm": fga * fta_ratio, "_prior_ftm_pm": fga * fta_ratio * 0.8,
        "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n, "_prior_ast_pm": [0.08] * n,
        "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [0.02] * n, "_prior_tov_pm": [0.06] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def test_solved_rate_inverts_the_box_score_ratio():
    for r in (0.20, 0.29, 0.35):
        f = events._solved_foul_per_attempt(r, 0.45, 0.35)
        m, s3 = 0.45, 0.35
        fta = f * (m * 0.32 + (1 - m) * 0.70 * (2 + s3))
        fga = 1 - f * (1 - m) * 0.70
        assert fta / fga == pytest.approx(r, rel=1e-9)
    assert events._solved_foul_per_attempt(0.31, 0.45, 0.35) > 0.20  # the old cap bound below the real ratio


def _fta_per_fga(flag: bool, n: int = 60) -> float:
    events.FOUL_RATE_SOLVED = flag
    rng = np.random.default_rng(5)
    fta = fga = 0.0
    for _ in range(n):
        hb, ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(), _team(), target_home_points=82.0, target_away_points=82.0)
        for b in (hb, ab):
            fta += sum(p["fta"] for p in b["players"])
            fga += sum(p["fga"] for p in b["players"])
    return fta / fga


def test_reachability_box_score_fta_per_fga_lands_on_the_prior():
    off, on = _fta_per_fga(False), _fta_per_fga(True)
    assert off < 0.26               # capped
    assert abs(on - 0.30) < 0.03    # the team's prior FTA/FGA
