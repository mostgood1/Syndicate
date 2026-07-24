"""Unit tests for the hockeysim projection layer (xG / Poisson / Elo game model).

Pure-math, no network / fixtures. Covers: sane baseline output, home-ice edge, strength
monotonicity, period-share split, Elo blending, profile immutability, and the ``apply_projection``
wiring into ``period_goal_lambdas`` that the adapter consumes.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyTeamFeatures
from syndicate.features.nhl.sim_engine.hockeysim.projection import (
    NHL_PROJECTION_PROFILE,
    GameProjection,
    ProjectionProfile,
    apply_projection,
    project_game,
)


def _avg_team(name: str) -> HockeyTeamFeatures:
    # Explicitly league-average xG so the baseline is unambiguous.
    return HockeyTeamFeatures(name=name, xgf_per_60=3.05, xga_per_60=3.05)


def test_baseline_matchup_is_sane():
    proj = project_game(_avg_team("Home"), _avg_team("Away"))
    assert isinstance(proj, GameProjection)
    # NHL regulation total sits in a believable band.
    assert 5.0 <= proj.model_total <= 7.0
    # Both teams score a plausible amount.
    assert 2.0 <= proj.proj_home_goals <= 4.5
    assert 2.0 <= proj.proj_away_goals <= 4.5
    # Probabilities are complementary and valid.
    assert proj.p_home_ml_seed + proj.p_away_ml_seed == pytest.approx(1.0, abs=1e-6)
    assert 0.0 < proj.p_home_ml_seed < 1.0


def test_home_ice_favours_the_home_side_for_equal_teams():
    proj = project_game(_avg_team("Home"), _avg_team("Away"))
    # Equal-strength teams: home ice must give home the goals + win-prob edge.
    assert proj.proj_home_goals > proj.proj_away_goals
    assert proj.model_spread > 0
    assert proj.p_home_ml_seed > 0.5


def test_stronger_offense_and_weaker_opponent_defense_raises_home_goals():
    weak = project_game(_avg_team("Home"), _avg_team("Away"))
    strong_home = HockeyTeamFeatures(name="Home", xgf_per_60=3.7, xga_per_60=2.6)
    soft_away = HockeyTeamFeatures(name="Away", xgf_per_60=2.6, xga_per_60=3.6)
    strong = project_game(strong_home, soft_away)
    assert strong.proj_home_goals > weak.proj_home_goals
    assert strong.model_spread > weak.model_spread
    assert strong.p_home_ml_seed > weak.p_home_ml_seed


def test_period_lambdas_sum_to_regulation_goals_and_follow_shares():
    proj = project_game(_avg_team("Home"), _avg_team("Away"))
    assert sum(proj.period_home_lambdas) == pytest.approx(proj.proj_home_goals, abs=1e-3)
    assert sum(proj.period_away_lambdas) == pytest.approx(proj.proj_away_goals, abs=1e-3)
    # Default profile weights P3 > P2 > P1.
    p1, p2, p3 = proj.period_home_lambdas
    assert p3 > p2 > p1


def test_period_shares_are_renormalized_when_not_summing_to_one():
    prof = replace(NHL_PROJECTION_PROFILE, period_shares=(1.0, 1.0, 2.0))  # sums to 4
    proj = project_game(_avg_team("Home"), _avg_team("Away"), profile=prof)
    # Regardless of raw share magnitude, per-period lambdas must reconstruct the total.
    assert sum(proj.period_home_lambdas) == pytest.approx(proj.proj_home_goals, abs=1e-3)
    p1, p2, p3 = proj.period_home_lambdas
    assert p3 == pytest.approx(2 * p1, rel=1e-3)


def test_elo_blend_pulls_win_prob_toward_rating_estimate():
    home = HockeyTeamFeatures(name="Home", xgf_per_60=3.6, xga_per_60=2.7, elo_rating=1560)
    away = HockeyTeamFeatures(name="Away", xgf_per_60=2.7, xga_per_60=3.5, elo_rating=1470)
    poisson_only = project_game(home, away)
    blended = project_game(home, away, profile=replace(NHL_PROJECTION_PROFILE, elo_blend_weight=0.5))
    # Elo (90-pt gap + home ice) is less extreme than the Poisson goal model here, so blending down.
    assert blended.p_home_ml_seed != poisson_only.p_home_ml_seed
    assert 0.5 < blended.p_home_ml_seed < poisson_only.p_home_ml_seed


def test_elo_blend_is_noop_without_ratings():
    home = HockeyTeamFeatures(name="Home", xgf_per_60=3.2, xga_per_60=2.9)
    away = HockeyTeamFeatures(name="Away", xgf_per_60=2.9, xga_per_60=3.2)
    base = project_game(home, away)
    blended = project_game(home, away, profile=replace(NHL_PROJECTION_PROFILE, elo_blend_weight=0.8))
    # No elo_rating on the features -> blend cannot apply -> identical seed.
    assert blended.p_home_ml_seed == base.p_home_ml_seed


def test_strength_multiplier_is_clamped():
    prof = replace(NHL_PROJECTION_PROFILE, regression=0.0, strength_mult_clip_high=1.4)
    # Absurdly strong offense vs porous defense would blow past the clamp without it.
    home = HockeyTeamFeatures(name="Home", xgf_per_60=9.0, xga_per_60=1.0)
    away = HockeyTeamFeatures(name="Away", xgf_per_60=1.0, xga_per_60=9.0)
    proj = project_game(home, away, profile=prof)
    ceiling = prof.league_baseline_goals_per_60 * prof.strength_mult_clip_high * prof.home_ice_attack_mult
    # +1e-3 tolerance absorbs the 4-dp rounding of proj_home_goals; without the clamp this value
    # would be ~8x the baseline, so the assertion still meaningfully proves the clamp fired.
    assert proj.proj_home_goals <= ceiling + 1e-3


def test_falls_back_to_goals_per_60_when_xg_absent():
    # No xg fields -> uses goals_per_60 for offense, league baseline for defense; must not crash.
    home = HockeyTeamFeatures(name="Home", goals_per_60=3.4)
    away = HockeyTeamFeatures(name="Away", goals_per_60=2.5)
    proj = project_game(home, away)
    assert proj.proj_home_goals > proj.proj_away_goals


def test_apply_projection_sets_period_goal_lambdas():
    home = HockeyTeamFeatures(name="Home", xgf_per_60=3.4, xga_per_60=2.8)
    away = HockeyTeamFeatures(name="Away", xgf_per_60=2.8, xga_per_60=3.3)
    new_home, new_away, proj = apply_projection(home, away)
    assert new_home.period_goal_lambdas == proj.period_home_lambdas
    assert new_away.period_goal_lambdas == proj.period_away_lambdas
    # Originals are untouched (frozen dataclasses -> new instances).
    assert home.period_goal_lambdas != new_home.period_goal_lambdas


def test_default_profile_is_immutable_singleton():
    with pytest.raises(Exception):
        NHL_PROJECTION_PROFILE.regression = 0.9  # type: ignore[misc]
    assert isinstance(NHL_PROJECTION_PROFILE, ProjectionProfile)


def test_projection_is_deterministic():
    home = HockeyTeamFeatures(name="Home", xgf_per_60=3.3, xga_per_60=2.9)
    away = HockeyTeamFeatures(name="Away", xgf_per_60=2.9, xga_per_60=3.1)
    a = project_game(home, away)
    b = project_game(home, away)
    assert a == b
