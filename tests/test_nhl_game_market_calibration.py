"""NHL game-market calibration: full-game settlement, tie mass, empty net, regulation pace -- lane
`nhl-game-lines-model`, user decision 2026-10-03 "ship the four sim fixes".

The lambdas below are a REAL production row (fleet predictions_2026-10-03.csv, CHI @ BUF, gamePk 2026020022, anchored), not
invented. The production row itself read p_home_ml 0.632625 / model_total 6.4207 / p_over(6.0) 0.4583 under
the legacy sim; the identity test reproduces exactly those numbers.
"""
from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim import adapters as A
from syndicate.features.nhl.sim_engine.hockeysim.contracts import (
    HockeyGameFeatures,
    HockeyMarketLines,
    HockeyTeamFeatures,
)
from syndicate.features.nhl.sim_engine.hockeysim.game_market_sim import SimConfig, simulate_from_period_lambdas

HOME = (1.0644, 1.266, 1.3097)   # Buffalo Sabres, fleet 2026-10-03
AWAY = (0.813, 0.9671, 1.0005)   # Chicago Blackhawks


def _game(total_line=6.0):
    return HockeyGameFeatures(
        game_pk="2026020022", date="2026-10-03",
        home=HockeyTeamFeatures(name="Buffalo Sabres", period_goal_lambdas=HOME),
        away=HockeyTeamFeatures(name="Chicago Blackhawks", period_goal_lambdas=AWAY),
        market=HockeyMarketLines(total_line=total_line),
    )


def test_legacy_config_reproduces_the_production_row_exactly():
    p = A.build_game_prediction(_game(), calibration=A.LEGACY_GAME_MARKET)
    # the anchored row as production wrote it (fleet predictions_2026-10-03.csv, legacy sim)
    assert p.model_total == pytest.approx(6.4207, abs=1e-4)
    # p_over and model_total reproduce exactly; p_home_ml to half a draw in 20,000 -- the CSV stores the
    # period lambdas rounded to 4 dp, so the replayed inputs are not bit-identical to the producer's
    assert p.p_home_ml == pytest.approx(0.632625, abs=1e-4)
    assert p.p_over == pytest.approx(0.4583, abs=1e-9)


def test_default_simconfig_keeps_the_legacy_output_shape():
    out = simulate_from_period_lambdas(list(HOME), list(AWAY), total_line=6.0, cfg=SimConfig(n_sims=5000, random_state=7))
    assert set(out) == {"home_ml", "away_ml", "over", "under", "home_puckline_-1.5", "away_puckline_+1.5"}


def test_reachability_calibrated_differs_from_legacy():
    legacy = A.build_game_prediction(_game(), calibration=A.LEGACY_GAME_MARKET)
    cal = A.build_game_prediction(_game(), calibration=A.NHL_GAME_MARKET_CALIBRATION)
    assert cal.model_total != pytest.approx(legacy.model_total, abs=1e-3)
    assert cal.p_over != pytest.approx(legacy.p_over, abs=1e-3)
    assert cal.p_home_ml != pytest.approx(legacy.p_home_ml, abs=1e-4)


def test_production_default_is_the_calibrated_config(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NHL_GAME_MARKET_CALIBRATION", raising=False)
    assert A.game_market_calibration() == A.NHL_GAME_MARKET_CALIBRATION
    monkeypatch.setenv("SYNDICATE_NHL_GAME_MARKET_CALIBRATION", "off")
    assert A.game_market_calibration() == A.LEGACY_GAME_MARKET
    off = A.build_game_prediction(_game())
    assert off.p_over == pytest.approx(0.4583, abs=1e-9)


def test_full_game_settlement_adds_the_ot_goal_to_the_total():
    reg = simulate_from_period_lambdas(list(HOME), list(AWAY), total_line=6.5,
                                       cfg=SimConfig(n_sims=20000, random_state=3, tie_weight=1e-12))
    full = simulate_from_period_lambdas(list(HOME), list(AWAY), total_line=6.5,
                                        cfg=SimConfig(n_sims=20000, random_state=3, full_game_settlement=True))
    # a 3-3 regulation tie settles 7 > 6.5: only the full-game settlement counts it as an over
    assert full["over"] > reg["over"]
    assert full["expected_home_goals"] + full["expected_away_goals"] == pytest.approx(
        sum(HOME) + sum(AWAY) + full["p_reg_tie"], abs=0.05)


def test_tie_weight_raises_the_regulation_tie_rate_as_designed():
    base = simulate_from_period_lambdas(list(HOME), list(AWAY), cfg=SimConfig(n_sims=20000, random_state=5, full_game_settlement=True))
    up = simulate_from_period_lambdas(list(HOME), list(AWAY), cfg=SimConfig(n_sims=20000, random_state=5, full_game_settlement=True, tie_weight=0.7539))
    p = base["p_reg_tie"]
    assert up["p_reg_tie"] == pytest.approx(p * 1.7539 / (1 + 0.7539 * p), abs=1e-9)
    assert up["p_reg_tie"] > p


def test_ot_split_and_puck_line_settle_on_the_full_game():
    out = simulate_from_period_lambdas(list(HOME), list(AWAY), cfg=SimConfig(n_sims=20000, random_state=9, full_game_settlement=True, ot_home_win_prob=0.5))
    assert out["home_ml"] + out["away_ml"] == pytest.approx(1.0, abs=1e-12)
    assert out["home_ml"] == pytest.approx(out["p_reg_home"] + 0.5 * out["p_reg_tie"], abs=1e-12)
    # an OT/SO win is by one goal: never a -1.5 cover
    assert out["home_puckline_-1.5"] <= out["p_reg_home"]


def test_regulation_scale_touches_the_game_market_only():
    """The pace rescale lives in the adapter, not the projection profile, so the props engine's
    goals_per_60 (back-filled by apply_projection) is unchanged."""
    from syndicate.features.nhl.sim_engine.hockeysim.projection import NHL_PROJECTION_PROFILE

    assert NHL_PROJECTION_PROFILE.league_baseline_goals_per_60 == pytest.approx(3.1269)
    cal = A.build_game_prediction(_game(), calibration={**A.LEGACY_GAME_MARKET, "regulation_scale": 0.9398})
    assert cal.period_home_proj[0] == pytest.approx(round(HOME[0] * 0.9398, 4), abs=1e-4)
