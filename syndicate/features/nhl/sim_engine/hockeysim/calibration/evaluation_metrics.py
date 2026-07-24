"""Measure the metrics the projection profile produces, for scoring against a truth benchmark.

The projection profile (`ProjectionProfile`) governs the pregame-expected-goal quantities the truth
baseline measures: total goals/game, the home/away split, and the per-period scoring shape. This
module runs a canonical *league-average* matchup through the projection + game-market sim and
extracts those same-named metrics, so ``simulator_evaluator`` can compare them to the benchmark.

League-average teams (xGF = xGA = league mean) are used deliberately: it isolates the *profile*
(baseline pace, home-ice, period shape) from team-strength effects, which is exactly what the
projection profile is responsible for. PP / empty-net / OT / shootout rates are governed by the
engine ``SimConfig`` (not the projection profile) and are evaluated separately; they are omitted
here so the score reflects only what this profile controls.
"""
from __future__ import annotations

from typing import Dict

from ..contracts import HockeyTeamFeatures
from ..game_market_sim import SimConfig as GameMarketSimConfig
from ..game_market_sim import simulate_from_period_lambdas
from ..projection import NHL_PROJECTION_PROFILE, ProjectionProfile, project_game

# Metrics the projection profile directly tunes (via baseline / home-ice / period-share overrides).
# These are what the calibration loop drives to convergence.
CALIBRATED_METRIC_NAMES = (
    "goals_per_game",
    "home_goals_per_game",
    "away_goals_per_game",
    "period1_share",
    "period2_share",
    "period3_share",
)

# Full projection validation set: the calibrated metrics plus home_win_pct, which is *emergent*
# (a Poisson consequence of the goal means, not an independently settable lever). Scored for
# validation/reporting, but not something the overrides can force to an arbitrary value.
PROJECTION_METRIC_NAMES = CALIBRATED_METRIC_NAMES + ("home_win_pct",)


def measure_projection_profile(
    profile: ProjectionProfile = NHL_PROJECTION_PROFILE,
    *,
    n_sims: int = 40000,
    seed: int = 20260115,
) -> Dict[str, float]:
    """Extract projection-controlled metrics for a canonical league-average matchup."""
    avg = profile.league_xg_per_60
    home = HockeyTeamFeatures(name="LeagueAvgHome", xgf_per_60=avg, xga_per_60=avg)
    away = HockeyTeamFeatures(name="LeagueAvgAway", xgf_per_60=avg, xga_per_60=avg)
    proj = project_game(home, away, profile=profile)

    ph = list(proj.period_home_lambdas)
    pa = list(proj.period_away_lambdas)
    per_totals = [ph[i] + pa[i] for i in range(3)]
    reg_total = sum(per_totals) or 1.0

    cfg = GameMarketSimConfig(n_sims=int(n_sims), random_state=int(seed))
    probs = simulate_from_period_lambdas(home_periods=ph, away_periods=pa, total_line=None, puck_line=-1.5, cfg=cfg)

    return {
        "goals_per_game": round(proj.model_total, 4),
        "home_goals_per_game": round(proj.proj_home_goals, 4),
        "away_goals_per_game": round(proj.proj_away_goals, 4),
        "period1_share": round(per_totals[0] / reg_total, 4),
        "period2_share": round(per_totals[1] / reg_total, 4),
        "period3_share": round(per_totals[2] / reg_total, 4),
        "home_win_pct": round(float(probs.get("home_ml") or 0.0), 4),
    }
