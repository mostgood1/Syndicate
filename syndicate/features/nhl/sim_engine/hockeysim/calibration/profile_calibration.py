"""Derive projection-profile overrides from a truth snapshot.

Turns measured truth into the handful of `ProjectionProfile` field values that make a canonical
league-average matchup reproduce the real baseline: the per-team pace, the home-ice / road
multipliers, and the period scoring shape. The derived numbers are then baked into
`projection.NHL_PROJECTION_PROFILE` as *documented, audited* defaults (never applied at runtime) —
this function is what computes them and what the calibration report + tests use to verify
convergence.
"""
from __future__ import annotations

from typing import Any, Dict

from ..historical_truth.contracts import TruthSnapshot


def derive_projection_overrides(snapshot: TruthSnapshot) -> Dict[str, Any]:
    """Compute `ProjectionProfile` field overrides that reproduce ``snapshot``'s baseline.

    For a league-average matchup the projection yields ``base * home_ice`` (home) and
    ``base * away_ice`` (away). Setting ``base = goals/2`` and the multipliers from the measured
    home/away split makes the profile reproduce the truth goals + split exactly; period shares copy
    the measured regulation shape.
    """
    cal = snapshot.to_calibration_snapshot()
    goals = float(cal["goals_per_game"])
    home = float(cal["home_goals_per_game"])
    away = float(cal["away_goals_per_game"])
    base = goals / 2.0 if goals > 0 else 3.05
    home_ice = home / base if base > 0 else 1.0
    away_ice = away / base if base > 0 else 1.0
    shares = (
        round(float(cal["period1_share"]), 4),
        round(float(cal["period2_share"]), 4),
        round(float(cal["period3_share"]), 4),
    )
    return {
        "league_baseline_goals_per_60": round(base, 4),
        "league_xg_per_60": round(base, 4),
        "home_ice_attack_mult": round(home_ice, 4),
        "away_ice_attack_mult": round(away_ice, 4),
        "period_shares": shares,
    }
