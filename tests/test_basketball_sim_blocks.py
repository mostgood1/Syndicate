"""WNBA PBP engine: blocks happen on missed two-point attempts (lane wnba-sim-blocks).

The loop drew a block on a flat 5% of ALL 2PAs, after and independent of the make --
about half the sim's blocks were on made shots, and team blocks ran 0.65x actual
(real 2026: 0.094 per opponent 2PA, 0.192 per opponent missed 2PA).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

events = sim._import_real_events_module_local(package_name="wnba_betting")
pytestmark = pytest.mark.skipif(events is None, reason="vendored wnba engine not importable")


@pytest.fixture(autouse=True)
def _restore_mode():
    saved = events.BLOCK_MODE
    yield
    events.BLOCK_MODE = saved


def _team(blk_pm: float = 0.02, n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_threes_att_pm": fga * 0.35, "_prior_threes_pm": fga * 0.12,
        "_prior_fgm_pm": fga * 0.45, "_prior_fta_pm": fga * 0.28, "_prior_ftm_pm": fga * 0.22,
        "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n, "_prior_ast_pm": [0.08] * n,
        "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [blk_pm] * n, "_prior_tov_pm": [0.06] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def test_no_block_on_a_made_shot_or_a_three_outside_legacy():
    rng = np.random.default_rng(0)
    for mode in ("team_prior",):
        events.BLOCK_MODE = mode
        assert not any(events._block_drawn(rng, False, True, 0.05, 0.9) for _ in range(200))
        assert not any(events._block_drawn(rng, True, False, 0.05, 0.9) for _ in range(200))
    events.BLOCK_MODE = "legacy"
    assert any(events._block_drawn(rng, False, True, 0.5, 0.0) for _ in range(50))  # the old draw ignored the make


def test_team_rate_scales_with_the_defenses_prior_blocks():
    d, o = _team(0.02), _team()
    mins = d["_sim_min"].to_numpy()
    fg = events._player_pct(o, "_prior_fgm_pm", "_prior_fga_pm", default=0.46, lo=0.25, hi=0.75)
    rates = {"p_tov": 0.13, "p3": 0.35, "foul_per_fga": 0.2}
    r1 = events._team_block_rate_on_missed_2pa(d, mins, o, mins, rates, fg, 1.0, 80.0, 0.24)
    r2 = events._team_block_rate_on_missed_2pa(_team(0.03), mins, o, mins, rates, fg, 1.0, 80.0, 0.24)
    assert r2 == pytest.approx(r1 * 1.5)              # rim protection counts, linearly
    r_eff = events._team_block_rate_on_missed_2pa(d, mins, o, mins, rates, fg, 0.9, 80.0, 0.24)
    assert r_eff < r1                                 # more misses at lower efficiency -> lower per-miss rate
    assert 0.05 <= r1 <= 0.40


def _blocks(mode: str, n: int = 60) -> float:
    events.BLOCK_MODE = mode
    rng = np.random.default_rng(2)
    tot = 0.0
    for _ in range(n):
        hb, _ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(), _team(), target_home_points=82.0, target_away_points=82.0)
        tot += sum(p["blk"] for p in hb["players"]) / n
    return tot


def test_reachability_team_blocks_follow_the_prior():
    prior = 0.02 * 200.0  # 4.0 blocks per game, the defense's prior
    legacy, team = _blocks("legacy"), _blocks("team_prior")
    assert legacy < prior * 0.8
    assert abs(team - prior) / prior < 0.15


@pytest.fixture
def _alloc_flag():
    saved = events.BLOCK_ALLOC_BY_RATE
    yield
    events.BLOCK_ALLOC_BY_RATE = saved


def test_block_allocation_is_proportional_to_raw_block_rates(_alloc_flag):
    t = _team()
    t["_prior_blk_pm"] = [0.10, 0.0, 0.01, 0.02, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0]
    events.BLOCK_ALLOC_BY_RATE = True
    w = events._player_usage_weights(t, "_prior_blk_pm", [0, 1, 2, 3, 4])
    floor = events.BLOCK_ALLOC_FLOOR_PM
    expected = np.array([0.10, floor, 0.01, 0.02, 0.02]) / (0.15 + floor)
    assert w[:5] == pytest.approx(expected)
    assert w[5:].sum() == 0
    events.BLOCK_ALLOC_BY_RATE = False
    flat = events._player_usage_weights(t, "_prior_blk_pm", [0, 1, 2, 3, 4])
    assert flat[0] < w[0] and flat[1] > w[1]  # the general blend flattens toward minutes
