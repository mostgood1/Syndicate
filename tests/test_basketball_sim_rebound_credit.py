"""WNBA PBP engine: not every miss is a PLAYER rebound (lane wnba-sim-rebound-credit).

The loop credited a player on every missed shot (~1.05 player rebounds per missed FG);
real 2026 box scores credit 0.889 -- the rest are team rebounds and dead balls -- so sim
rebounds ran ~1.2x actual.
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
    saved = events.PLAYER_REBOUND_CREDIT
    yield
    events.PLAYER_REBOUND_CREDIT = saved


def _team(n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_threes_att_pm": fga * 0.35, "_prior_threes_pm": fga * 0.12,
        "_prior_fgm_pm": fga * 0.45, "_prior_fta_pm": fga * 0.28, "_prior_ftm_pm": fga * 0.22,
        "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n, "_prior_ast_pm": [0.08] * n,
        "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [0.02] * n, "_prior_tov_pm": [0.06] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def test_credit_rates_reproduce_the_fitted_player_rebound_shares():
    assert events.OREB_PLAYER_CREDIT * 0.24 == pytest.approx(0.227)
    assert events.DREB_PLAYER_CREDIT * 0.76 == pytest.approx(0.663)
    assert 0 < events.DREB_PLAYER_CREDIT < events.OREB_PLAYER_CREDIT <= 1


def _per_miss(flag: bool, n: int = 60) -> tuple[float, float]:
    events.PLAYER_REBOUND_CREDIT = flag
    rng = np.random.default_rng(9)
    reb = miss = pts = 0.0
    for _ in range(n):
        hb, ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(), _team(), target_home_points=82.0, target_away_points=82.0)
        for b in (hb, ab):
            reb += sum(p["reb"] for p in b["players"])
            miss += sum(p["fga"] - p["fgm"] for p in b["players"])
            pts += sum(p["pts"] for p in b["players"]) / (2 * n)
    return reb / miss, pts


def test_reachability_player_rebounds_per_miss_fall_to_the_real_rate():
    off, pts_off = _per_miss(False)
    on, pts_on = _per_miss(True)
    assert off > 0.98                       # every miss credited (fouled-and-no-FT misses too)
    assert 0.85 < on < 0.93                 # real 2026: 0.889
    assert pts_on == pytest.approx(pts_off, abs=2.0)  # possession flow untouched
