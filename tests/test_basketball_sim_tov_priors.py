"""WNBA smart sim turnovers (lane wnba-sim-tov-priors).

Measured 2026-10-01 over 126 team-games: the TOV the engine received was 0.726x actual
while the players' real as-of rates summed to 1.027x. Two mechanisms:
- the prior blend counted a MISSING recent rate as a measured 0.0 (stl/blk/tov have no
  rolling features), so the anchor was 0.5 x prior + 0.15 x pred;
- the engine checks p_tov on every shot iteration (~1.1 per possession) but derived it
  per possession, so it realized ~1.1x its prior.
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


@pytest.fixture(autouse=True)
def _restore_flags():
    saved = (sim.PRIOR_BLEND_MISSING_RECENT_IS_ABSENT, events.TOV_PER_ATTEMPT)
    yield
    sim.PRIOR_BLEND_MISSING_RECENT_IS_ABSENT, events.TOV_PER_ATTEMPT = saved


def _team(tov_pm: float = 0.07, n: int = 10) -> pd.DataFrame:
    fga = np.array([0.55, 0.45, 0.40, 0.35, 0.30, 0.25, 0.25, 0.20, 0.20, 0.15])[:n]
    mins = np.array([34, 32, 30, 28, 22, 18, 14, 10, 8, 4], dtype=float)[:n]
    return pd.DataFrame({
        "player_name": [f"P{i}" for i in range(n)], "_sim_min": mins,
        "_prior_fga_pm": fga, "_prior_threes_att_pm": fga * 0.35, "_prior_threes_pm": fga * 0.12,
        "_prior_fgm_pm": fga * 0.45, "_prior_fta_pm": fga * 0.28, "_prior_ftm_pm": fga * 0.22,
        "_prior_pts_pm": fga * 1.1, "_prior_reb_pm": [0.15] * n, "_prior_ast_pm": [0.08] * n,
        "_prior_stl_pm": [0.03] * n, "_prior_blk_pm": [0.02] * n, "_prior_tov_pm": [tov_pm] * n,
        "_prior_pf_pm": [0.08] * n, "pred_pts": fga * 30,
    })


def test_iterations_per_possession_is_one_plus_the_continuation():
    it = events._iterations_per_possession(p_tov=0.15, p3=0.35, fg2=0.50, fg3=0.34, foul=0.20, oreb=0.24)
    made = 0.65 * 0.50 + 0.35 * 0.34
    assert it == pytest.approx(1.0 + 0.85 * (1 - made) * (1 - 0.14) * 0.24)
    assert 1.05 < it < 1.2


def _team_tov(flag: bool, n: int = 60) -> float:
    events.TOV_PER_ATTEMPT = flag
    rng = np.random.default_rng(4)
    tot = 0.0
    cfg = events.EventSimConfig()
    for _ in range(n):
        hb, _ab, _hq, _aq = events.simulate_pbp_game_boxscore(rng, _team(), _team(), cfg=cfg, target_home_points=82.0, target_away_points=82.0)
        tot += sum(p["tov"] for p in hb["players"]) / n
    return tot


def test_reachability_per_attempt_tov_lands_on_the_prior():
    prior = float((_team()["_prior_tov_pm"] * _team()["_sim_min"]).sum())  # 0.07 x 200 = 14 per game
    off, on = _team_tov(False), _team_tov(True)
    assert off > prior * 1.04          # the old rate over-realizes by the OREB continuation
    assert abs(on - prior) / prior < 0.06
    assert on < off


def test_reachability_missing_recent_rate_no_longer_drags_the_anchor(monkeypatch):
    # Drive the real blend through its public seam with one player whose only TOV signal is the prior.
    captured = {}

    def fake_rates(*, priors, team_tri, pkey, player_name):
        return {"tov_pm": 0.10, "stl_pm": 0.04, "blk_pm": 0.02, "pts_pm": 0.5, "reb_pm": 0.2, "ast_pm": 0.1, "threes_pm": 0.04,
                "threes_att_pm": 0.12, "fga_pm": 0.4, "fgm_pm": 0.18, "fta_pm": 0.1, "ftm_pm": 0.08, "pf_pm": 0.08}

    monkeypatch.setattr(sim, "_prior_rates_for_player_local", fake_rates)
    for name in ("_player_split_rate_context_local", "_player_career_opponent_rate_context_local", "_opponent_position_rate_context_local"):
        monkeypatch.setattr(sim, name, lambda **_k: pd.DataFrame())
    df = pd.DataFrame({"player_name": ["A Player"], "team": ["LVA"], "opponent": ["IND"], "pred_tov": [3.0], "pred_min": [30.0], "_pkey": ["A"]})
    for flag in (False, True):
        sim.PRIOR_BLEND_MISSING_RECENT_IS_ABSENT = flag
        module = sim._build_local_smart_sim_module(processed_root=sim.Path("."), league_code="wnba")
        out = sim._apply_player_priors_local(smart_sim_module=module, team_df=df.copy(), priors=None, team_tri="LVA",
                                             sim_minutes=pd.Series([30.0]), date_str=None)
        captured[flag] = float(out["_prior_tov_pm"].iloc[0])
        pred_pm = float(out["_pred_tov_pm"].iloc[0])  # per minute of the (guardrail-scaled) sim minutes
    assert captured[True] == pytest.approx((0.5 * 0.10 + 0.15 * pred_pm) / 0.65, rel=1e-6)
    assert captured[False] == pytest.approx(0.5 * 0.10 + 0.15 * pred_pm, rel=1e-6)
