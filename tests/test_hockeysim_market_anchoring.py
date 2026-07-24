"""Tests for hockeysim market anchoring (2-way home-win bisection).

Verifies: devig, the blend/solve preserves total while moving the win prob to the blended target,
weight endpoints (0 = model, 1 = market), period-lambda rescale, and the opt-in loader wiring
(no-op without odds).
"""
from __future__ import annotations

import dataclasses

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.contracts import (
    HockeyGameFeatures,
    HockeyMarketLines,
    HockeyTeamFeatures,
)
from syndicate.features.nhl.sim_engine.hockeysim.market_anchoring import (
    anchor_expected_goals,
    anchor_game_features,
    devig_two_way_home_prob,
    market_home_prob,
)
from syndicate.features.nhl.sim_engine.hockeysim.projection import _poisson_win_prob


def test_devig_two_way():
    p = devig_two_way_home_prob(-150, 130)
    assert 0.55 < p < 0.61          # -150 favorite, devigged
    assert devig_two_way_home_prob(None, 130) is None
    # symmetric pick'em ~0.5
    assert devig_two_way_home_prob(100, 100) == pytest.approx(0.5)


def test_market_home_prob_prefers_explicit():
    m = HockeyMarketLines(home_ml_odds=-150, away_ml_odds=130, home_win_probability=0.62)
    assert market_home_prob(m) == pytest.approx(0.62)
    m2 = HockeyMarketLines(home_ml_odds=-150, away_ml_odds=130)
    assert market_home_prob(m2) == pytest.approx(devig_two_way_home_prob(-150, 130))
    assert market_home_prob(HockeyMarketLines()) is None


def test_anchor_preserves_total_and_hits_target():
    res = anchor_expected_goals(3.2, 3.0, market_p=0.70, weight=0.35)
    # total preserved
    assert res.home_goals + res.away_goals == pytest.approx(6.2, abs=1e-4)
    # resulting win prob equals the blended target
    got = _poisson_win_prob(res.home_goals, res.away_goals, 10)
    assert got == pytest.approx(res.target_home_prob, abs=2e-3)
    # target is between model and market
    assert res.model_home_prob < res.target_home_prob < res.market_home_prob


def test_anchor_weight_endpoints():
    # weight 0 -> no movement
    r0 = anchor_expected_goals(3.2, 3.0, 0.70, weight=0.0)
    assert r0.shift == pytest.approx(0.0, abs=1e-3)
    # weight 1 -> win prob matches market
    r1 = anchor_expected_goals(3.2, 3.0, 0.70, weight=1.0)
    assert _poisson_win_prob(r1.home_goals, r1.away_goals, 10) == pytest.approx(0.70, abs=3e-3)


def test_anchor_can_move_toward_underdog():
    # model favors home; market favors away -> shift should be negative (home goals down)
    res = anchor_expected_goals(3.6, 2.6, market_p=0.35, weight=0.5)
    assert res.shift < 0
    assert res.home_goals < 3.6 and res.away_goals > 2.6


def _game(home_periods, away_periods, market):
    home = HockeyTeamFeatures(name="Home", period_goal_lambdas=tuple(home_periods))
    away = HockeyTeamFeatures(name="Away", period_goal_lambdas=tuple(away_periods))
    return HockeyGameFeatures(game_pk="1", date="2026-01-15", home=home, away=away, market=market)


def test_anchor_game_features_rescales_periods_and_preserves_total():
    g = _game((1.0, 1.1, 1.1), (1.0, 1.0, 1.0), HockeyMarketLines(home_ml_odds=-200, away_ml_odds=170))
    before_total = sum(g.home.period_goal_lambdas) + sum(g.away.period_goal_lambdas)
    anchored = anchor_game_features(g, weight=0.4)
    after_total = sum(anchored.home.period_goal_lambdas) + sum(anchored.away.period_goal_lambdas)
    assert after_total == pytest.approx(before_total, abs=1e-3)
    # home favored by market -> home lambdas scaled up
    assert sum(anchored.home.period_goal_lambdas) > sum(g.home.period_goal_lambdas)
    # period shape preserved (proportional rescale)
    h = anchored.home.period_goal_lambdas
    assert h[1] == pytest.approx(h[0] * (1.1 / 1.0), rel=1e-3)


def test_anchor_game_features_noop_without_market():
    g = _game((1.0, 1.1, 1.1), (1.0, 1.0, 1.0), HockeyMarketLines())  # no odds
    anchored = anchor_game_features(g, weight=0.4)
    assert anchored.home.period_goal_lambdas == g.home.period_goal_lambdas
    assert anchored is g  # unchanged reference


def test_loader_opt_in_anchoring():
    from syndicate.features.nhl.sim_engine.hockeysim.features import loaders

    # Build directly (no mirror needed): project on, anchor on, with a market.
    market = HockeyMarketLines(home_ml_odds=-250, away_ml_odds=210)
    plain = loaders.build_game_features(
        "1", "2026-01-15", "Boston Bruins", "Chicago Blackhawks",
        root=_empty_root(), market=market, anchor_to_market=False,
    )
    anchored = loaders.build_game_features(
        "1", "2026-01-15", "Boston Bruins", "Chicago Blackhawks",
        root=_empty_root(), market=market, anchor_to_market=True, anchor_weight=0.5,
    )
    # Anchoring toward a heavy home favorite should raise home's projected goals.
    assert sum(anchored.home.period_goal_lambdas) > sum(plain.home.period_goal_lambdas)
    # total preserved by the anchor
    assert (sum(anchored.home.period_goal_lambdas) + sum(anchored.away.period_goal_lambdas)) == pytest.approx(
        sum(plain.home.period_goal_lambdas) + sum(plain.away.period_goal_lambdas), abs=1e-2
    )


def _empty_root(tmp=[]):
    # a path with no mirror data -> league-average projection, but anchoring still applies.
    import tempfile
    from pathlib import Path
    if not tmp:
        tmp.append(Path(tempfile.mkdtemp()))
    return tmp[0]
