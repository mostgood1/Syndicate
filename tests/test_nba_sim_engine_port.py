"""NBA PBP engine: the six WNBA engine fixes, ported behind module switches (Phase 2 #1d, pre-registered 2026-10-08
in .syndicate/findings_2026-10-06_basketball_scenario_calibration.md).

WNBA commits 8fd37ff3 SHOOTER_FT_RATE, c0d406d3 FOULED_MISS_NOT_FGA + EXACT_TARGET_CALIBRATION, 9f561ca3
TOV_PER_ATTEMPT (engine half), 863e9e09 PLAYER_REBOUND_CREDIT, cbb14a73 BLOCK_MODE, 4ec1fd72 BLOCK_ALLOC_BY_RATE.
Every NBA default is TODAY's NBA behaviour (byte-identical to the pre-port engine; the HEAD-vs-patched sha256 proof
is run out of tree). Each switch is tested here for reachability (off != on) and for the property it exists for,
mirroring the WNBA tests (tests/test_basketball_sim_{star_shortfall,team_calibration,tov_priors,rebound_credit,
blocks}.py). The runs are seeded, so every comparison is deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# The engine that RUNS (native Syndicate engine since c2b99d4f, lane basketball-native-engine): a LeagueEngine exposes
# the switches under the vendored names and the helpers bound to the NBA league params.
from syndicate.features.shared.basketball_props_smart_sim import _engine_for_league_local  # noqa: E402

events = _engine_for_league_local("nba")

SWITCHES = ("SHOOTER_FT_RATE", "FOULED_MISS_NOT_FGA", "EXACT_TARGET_CALIBRATION", "TOV_PER_ATTEMPT",
            "PLAYER_REBOUND_CREDIT", "BLOCK_MODE", "BLOCK_ALLOC_BY_RATE")
NBA_DEFAULTS = {"SHOOTER_FT_RATE": False, "FOULED_MISS_NOT_FGA": False, "EXACT_TARGET_CALIBRATION": False,
                "TOV_PER_ATTEMPT": False, "PLAYER_REBOUND_CREDIT": False, "BLOCK_MODE": "legacy", "BLOCK_ALLOC_BY_RATE": False}

N = 10
FGA = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])
MINS = np.array([36, 34, 32, 30, 28, 22, 18, 16, 14, 10], dtype=float)  # 240 team minutes
HOME_BLK = [0.06, 0.0, 0.01, 0.02, 0.02, 0.0, 0.0, 0.01, 0.0, 0.0]
TOV_PM = 0.06
FLAT_BLK_PM = 0.02


@pytest.fixture(autouse=True)
def _restore_switches():
    saved = {s: getattr(events, s) for s in SWITCHES}
    for s, v in NBA_DEFAULTS.items():  # every test starts from the NBA defaults
        setattr(events, s, v)
    yield
    for s, v in saved.items():
        setattr(events, s, v)


def _team(star_fta_pm: float = 0.06, blk=None) -> pd.DataFrame:
    fta = np.array([star_fta_pm] + [0.06] * (N - 1))
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(N)], "_sim_min": MINS,
        "_prior_fga_pm": FGA, "_prior_fgm_pm": FGA * 0.47, "_prior_threes_att_pm": FGA * 0.38, "_prior_threes_pm": FGA * 0.137,
        "_prior_fta_pm": fta, "_prior_ftm_pm": fta * 0.78, "_prior_reb_pm": [0.18] * N, "_prior_ast_pm": [0.08] * N,
        "_prior_stl_pm": [0.03] * N, "_prior_blk_pm": blk if blk is not None else [FLAT_BLK_PM] * N,
        "_prior_tov_pm": [TOV_PM] * N, "_prior_pf_pm": [0.07] * N, "pred_pts": FGA * 36,
    })


def _run(n: int = 40, target: float = 112.0, **switches) -> dict:
    """Seeded games: a foul-drawing star + a concentrated-blocker home team vs a flat away team."""
    for k, v in switches.items():
        assert k in SWITCHES
        setattr(events, k, v)
    rng = np.random.default_rng(5)
    agg = {k: 0.0 for k in ("pts", "fga", "fgm", "fta", "tov", "reb", "miss", "home_blk", "away_blk", "star_fta", "star_fga", "blk0")}
    for _ in range(n):
        hb, ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(0.30, HOME_BLK), _team(),
                                                             target_home_points=target, target_away_points=target)
        hp, ap = hb["players"], ab["players"]
        for k in ("pts", "fga", "fgm", "fta", "tov"):
            agg[k] += sum(p[k] for p in hp) / n
        agg["reb"] += sum(p["reb"] for p in hp + ap)
        agg["miss"] += sum(p["fga"] - p["fgm"] for p in hp + ap)
        agg["home_blk"] += sum(p["blk"] for p in hp)
        agg["away_blk"] += sum(p["blk"] for p in ap) / n
        agg["blk0"] += hp[0]["blk"]
        agg["star_fta"] += hp[0]["fta"]
        agg["star_fga"] += hp[0]["fga"]
    agg["star_ft_rate"] = agg["star_fta"] / max(1.0, agg["star_fga"])
    agg["reb_per_miss"] = agg["reb"] / max(1.0, agg["miss"])
    agg["blk0_share"] = agg["blk0"] / max(1.0, agg["home_blk"])
    return agg


_BASE: dict = {}


def _baseline() -> dict:
    """All switches at the NBA defaults (computed once; deterministic)."""
    if not _BASE:
        _BASE.update(_run())
    return _BASE


def test_nba_defaults_are_todays_behaviour():
    for s, v in NBA_DEFAULTS.items():
        assert getattr(events, s) == v
    # The team-prior stacking half of c0d406d3 stays the existing cfg field (b08aeb72), not a second switch.
    assert events.EventSimConfig().team_prior_stacks_on_target is True
    # Native engine: the switch exists per league; NBA leaves it None = "read the cfg field" (b08aeb72 behaviour).
    assert events.TEAM_PRIOR_STACKS_ON_TARGET is None


def test_placeholder_constants_are_present_and_sane():
    # WNBA-fitted values carried as placeholders until the NBA re-fit (Phase 2 #1d); only their sanity is pinned.
    assert 0.0 < events.DREB_PLAYER_CREDIT <= 1.0 and 0.0 < events.OREB_PLAYER_CREDIT <= 1.0
    assert 0.0 < events.LEAGUE_BLOCKS_PER_MISSED_2PA < 0.5
    assert 0.2 < events.BLOCK_RATE_ASSUMED_FG3_PCT < 0.5
    assert events.BLOCK_ALLOC_FLOOR_PM > 0


# --- SHOOTER_FT_RATE (WNBA 8fd37ff3) ---------------------------------------------------------------------------

def test_ft_multipliers_are_shot_weighted_mean_one_and_favour_foul_drawers():
    team = _team(0.30)
    mult = events._ft_rate_multipliers(team, MINS)
    w = FGA * MINS
    assert float((mult * w).sum() / w.sum()) == pytest.approx(1.0)
    assert mult[0] == mult.max() and mult[0] > 1.8
    team.loc[3, "_prior_fga_pm"] = 0.0
    assert events._ft_rate_multipliers(team, MINS)[3] == 1.0  # unknown -> neutral


def test_reachability_shooter_ft_rate_sends_free_throws_to_the_foul_drawer():
    off, on = _baseline(), _run(SHOOTER_FT_RATE=True)
    assert on["star_ft_rate"] > off["star_ft_rate"] * 1.5      # the star draws fouls at his own rate
    assert on["fta"] == pytest.approx(off["fta"], rel=0.25)     # team free throws are not inflated


# --- FOULED_MISS_NOT_FGA (WNBA c0d406d3) -----------------------------------------------------------------------

def test_reachability_fouled_miss_is_not_an_fga_and_scores_identically():
    off, on = _baseline(), _run(FOULED_MISS_NOT_FGA=True)
    assert on["fga"] < off["fga"] * 0.97                        # fouled misses leave the FGA column
    assert on["fgm"] == off["fgm"] and on["pts"] == off["pts"]  # same draws: accounting only


# --- EXACT_TARGET_CALIBRATION (WNBA c0d406d3) ------------------------------------------------------------------

def test_solver_inverts_the_loop_points_per_possession_model():
    args = dict(p_tov=0.13, p3=0.38, fg2=0.52, fg3=0.36, foul=0.25, ft=0.78, oreb=0.24)
    for target in (1.05, 1.12, 1.20):
        eff = events._solve_eff_mult(target, **args)
        assert events._loop_points_per_possession(eff=eff, **args) == pytest.approx(target, abs=1e-6)
    assert events._loop_points_per_possession(eff=1.1, **args) > events._loop_points_per_possession(eff=0.9, **args)
    share = events._loop_shot_share(_team(), MINS, "_prior_fga_pm")
    raw = FGA * MINS / (FGA * MINS).sum()
    assert share.sum() == pytest.approx(1.0) and share[0] < raw[0] and share[-1] > raw[-1]


def test_reachability_exact_calibration_lands_nearer_the_target():
    target = 104.0  # below this team's natural level: the old +/-15% helper overshoots here
    off = _run(target=target)["pts"]
    on = _run(target=target, EXACT_TARGET_CALIBRATION=True)["pts"]
    assert on != off
    assert abs(on - target) < abs(off - target)
    assert abs(on - target) < 3.0


# --- TOV_PER_ATTEMPT (WNBA 9f561ca3, engine half) --------------------------------------------------------------

def test_iterations_per_possession_is_one_plus_the_continuation():
    it = events._iterations_per_possession(p_tov=0.13, p3=0.38, fg2=0.52, fg3=0.36, foul=0.25, oreb=0.24)
    made = 0.62 * 0.52 + 0.38 * 0.36
    assert it == pytest.approx(1.0 + 0.87 * (1 - made) * (1 - 0.175) * 0.24)


def test_reachability_per_attempt_tov_lands_on_the_prior():
    prior = TOV_PM * float(MINS.sum())  # 14.4 per game
    off, on = _baseline()["tov"], _run(TOV_PER_ATTEMPT=True)["tov"]
    assert off > prior * 1.04            # the per-possession rate over-realises by the OREB continuation
    assert on < off
    assert abs(on - prior) / prior < 0.06


# --- PLAYER_REBOUND_CREDIT (WNBA 863e9e09) ---------------------------------------------------------------------

def test_reachability_player_rebounds_per_miss_fall_to_the_credit_rate():
    # FOULED_MISS_NOT_FGA on in both arms so "miss" counts only live misses (each one a rebound chance).
    off = _run(FOULED_MISS_NOT_FGA=True)
    on = _run(FOULED_MISS_NOT_FGA=True, PLAYER_REBOUND_CREDIT=True)
    assert off["reb_per_miss"] > 0.98                               # every live miss credited
    base = float(events.EventSimConfig().base_oreb_rate)
    expected = base * events.OREB_PLAYER_CREDIT + (1.0 - base) * events.DREB_PLAYER_CREDIT
    assert on["reb_per_miss"] == pytest.approx(expected, abs=0.03)  # thinned to the credit rate
    assert on["reb"] < off["reb"]
    assert on["pts"] == pytest.approx(off["pts"], abs=3.0)          # possession flow untouched


# --- BLOCK_MODE (WNBA cbb14a73) --------------------------------------------------------------------------------

def test_no_block_on_a_made_shot_or_a_three_outside_legacy():
    rng = np.random.default_rng(0)
    events.BLOCK_MODE = "team_prior"
    assert not any(events._block_drawn(rng, False, True, 0.05, 0.9) for _ in range(200))
    assert not any(events._block_drawn(rng, True, False, 0.05, 0.9) for _ in range(200))
    events.BLOCK_MODE = "legacy"
    assert any(events._block_drawn(rng, False, True, 0.5, 0.0) for _ in range(50))  # the old draw ignores the make


def test_team_block_rate_scales_with_the_defenses_prior_blocks():
    o = _team()
    fg = events._player_pct(o, "_prior_fgm_pm", "_prior_fga_pm", default=0.46, lo=0.25, hi=0.75)
    rates = {"p_tov": 0.13, "p3": 0.38, "foul_per_fga": 0.25}
    r1 = events._team_block_rate_on_missed_2pa(_team(blk=[0.02] * N), MINS, o, MINS, rates, fg, 1.0, 98.0, 0.24)
    r2 = events._team_block_rate_on_missed_2pa(_team(blk=[0.03] * N), MINS, o, MINS, rates, fg, 1.0, 98.0, 0.24)
    assert r2 == pytest.approx(r1 * 1.5)
    assert events._team_block_rate_on_missed_2pa(_team(blk=[0.02] * N), MINS, o, MINS, rates, fg, 0.9, 98.0, 0.24) < r1
    assert 0.05 <= r1 <= 0.40


def test_reachability_team_blocks_follow_the_defense_prior():
    prior = FLAT_BLK_PM * float(MINS.sum())  # away defense: 4.8 blocks per game
    legacy, team = _baseline()["away_blk"], _run(BLOCK_MODE="team_prior")["away_blk"]
    assert legacy < prior * 0.8
    assert abs(team - prior) < abs(legacy - prior)
    assert abs(team - prior) / prior < 0.15


# --- BLOCK_ALLOC_BY_RATE (WNBA 4ec1fd72) -----------------------------------------------------------------------

def test_block_allocation_is_proportional_to_raw_block_rates():
    t = _team(blk=[0.10, 0.0, 0.01, 0.02, 0.02, 0.0, 0.0, 0.0, 0.0, 0.0])
    events.BLOCK_ALLOC_BY_RATE = True
    w = events._player_usage_weights(t, "_prior_blk_pm", [0, 1, 2, 3, 4])
    floor = events.BLOCK_ALLOC_FLOOR_PM
    assert w[:5] == pytest.approx(np.array([0.10, floor, 0.01, 0.02, 0.02]) / (0.15 + floor))
    assert w[5:].sum() == 0
    events.BLOCK_ALLOC_BY_RATE = False
    flat = events._player_usage_weights(t, "_prior_blk_pm", [0, 1, 2, 3, 4])
    assert flat[0] < w[0] and flat[1] > w[1]
    # Other stats keep the general blend under the switch.
    reb_off = events._player_usage_weights(t, "_prior_reb_pm", [0, 1, 2, 3, 4])
    events.BLOCK_ALLOC_BY_RATE = True
    assert events._player_usage_weights(t, "_prior_reb_pm", [0, 1, 2, 3, 4]) == pytest.approx(reb_off)


def test_reachability_blocks_move_to_the_rim_protector_with_the_same_total():
    off, on = _baseline(), _run(BLOCK_ALLOC_BY_RATE=True)
    assert on["home_blk"] == off["home_blk"]          # same draws, different weights
    assert on["pts"] == off["pts"]
    # The 0.06/min blocker takes a larger share. 1.10x on the PRODUCTION path (Syndicate's exact-inclusion lineup
    # sampler, built into the native engine; the vendored path always ran with it patched in). The old 1.2x bound was
    # set on the vendored module's own sampler (1.30x there), which production never ran. Measured 2026-10-09:
    # vendor+patch == native exactly (share 0.4034 -> 0.4454).
    assert on["blk0_share"] > off["blk0_share"] * 1.05
