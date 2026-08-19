"""Principled game projection for the ``hockeysim`` engine.

This is the Syndicate-native replacement for the vendor's trained NN game model
(``nhl_betting/models/nn_games.py``). Rather than porting the neural net, it derives per-team
expected goals from an **xG / Poisson / Elo** formulation and splits them into per-period lambdas
that feed the already-absorbed period-lambda game-market sim
(:func:`hockeysim.game_market_sim.simulate_from_period_lambdas`).

Design (decided this session): a *principled* projection now, calibrated toward vendor/market
parity later via the Phase-3 truth layer and the Phase-9 shadow comparison. Every constant lives
in a frozen :class:`ProjectionProfile` (the projection-layer analog of the engine's ``SimConfig``
calibration profile) so future truth-calibrated deltas are auditable field overrides, never new
control flow.

Grounding (matches the vendor baselines being replaced):
  * league baseline ``3.05`` goals / team / 60 min — ``models/poisson.PoissonGoals.base_mu``.
  * home/away attack split ``1.05`` / ``0.95`` — ``models/poisson.PoissonConfig``.
  * Elo win prob via the logistic 400-point curve with a home-ice bump —
    ``models/elo.Elo.expected``.

The projection is pure math (stdlib only, no numpy / pandas / network) so it is trivially
unit-testable and safe to call from anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from .contracts import HockeyTeamFeatures


@dataclass(frozen=True)
class ProjectionProfile:
    """Frozen calibration levers for the projection layer.

    Kept separate from the engine ``SimConfig`` (which governs the boxscore/game-market
    simulators) because these govern the *pregame expected-goal* derivation. One projection,
    and league/era differences are expressed only here.
    """

    # League baseline goals per team per 60 (regulation pace anchor).
    # Truth-calibrated to 3.1269 (was 3.05, vendor Poisson default) — 2025-26 regular season,
    # 1312 games (goals/game 6.2538 -> /2). See docs/reports/hockeysim_phase3_truth_baseline_report.md.
    league_baseline_goals_per_60: float = 3.1269
    # League mean xGF/60 used to normalize team xG into a relative strength multiplier.
    # (xGA/60 shares the same league mean since every goal-for is some team's goal-against.)
    # Held equal to the baseline so a league-average team projects to the baseline pace.
    league_xg_per_60: float = 3.1269
    # Multiplicative home-ice / road adjustment on expected goals.
    # Truth-calibrated to 1.0209 / 0.9791 (was 1.05 / 0.95) — real home goal share is only 51.0%
    # (home 3.1921 / away 3.0617 per game); the vendor 1.05/0.95 overstated home ice. A 108-game
    # window had claimed 54.8%, so this required the full-season sample.
    home_ice_attack_mult: float = 1.0209
    away_ice_attack_mult: float = 0.9791
    # Per-period share of a team's regulation goals: (P1, P2, P3). Renormalized if not summing 1.
    # Truth-calibrated to (0.2924, 0.3478, 0.3598) (was (0.31, 0.34, 0.35)) — P1 lower, P3 highest.
    period_shares: Tuple[float, float, float] = (0.2924, 0.3478, 0.3598)
    # Shrinkage of team attack/defense multipliers toward the league mean (1.0). 0 = raw ratio.
    regression: float = 0.25
    # Clamp on the combined attack*defense strength multiplier to avoid extreme allocations.
    strength_mult_clip_low: float = 0.55
    strength_mult_clip_high: float = 1.70
    # Elo logistic scale (points) and home-ice bump (points) for the rating-based win prob.
    elo_scale: float = 400.0
    elo_home_adv: float = 50.0
    # Blend weight of the Elo win prob into the Poisson-derived p_home_ml seed (0 = pure Poisson).
    elo_blend_weight: float = 0.0
    # Max goals in the Poisson score matrix used for the win-prob seed.
    max_goals: int = 10


NHL_PROJECTION_PROFILE = ProjectionProfile()


@dataclass(frozen=True)
class GameProjection:
    """Output of :func:`project_game` — expected goals + per-period lambdas + win-prob seed."""

    proj_home_goals: float
    proj_away_goals: float
    model_total: float
    # home margin (positive = home projected to win by that many goals).
    model_spread: float
    period_home_lambdas: Tuple[float, float, float]
    period_away_lambdas: Tuple[float, float, float]
    # Regulation-tie-resolved moneyline seed (Poisson score matrix, ties split 50/50 or Elo-blended).
    p_home_ml_seed: float
    p_away_ml_seed: float


def _shrink(ratio: float, regression: float) -> float:
    """Blend a strength ratio toward the league mean (1.0) by ``regression`` in [0, 1]."""
    r = max(0.0, min(1.0, float(regression)))
    return (1.0 - r) * float(ratio) + r * 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _offense_rate(team: HockeyTeamFeatures, profile: ProjectionProfile) -> float:
    """Team offensive xG/60 (falls back to goals_per_60, then the league baseline)."""
    for candidate in (team.xgf_per_60, team.goals_per_60):
        if candidate is not None and float(candidate) > 0:
            return float(candidate)
    return profile.league_xg_per_60


def _defense_rate(team: HockeyTeamFeatures, profile: ProjectionProfile) -> float:
    """Opponent-suppression xGA/60 (falls back to the league baseline when unknown)."""
    if team.xga_per_60 is not None and float(team.xga_per_60) > 0:
        return float(team.xga_per_60)
    return profile.league_xg_per_60


def _poisson_pmf_row(lam: float, max_goals: int) -> Tuple[float, ...]:
    lam = max(0.0, float(lam))
    return tuple(math.exp(-lam) * (lam ** k) / math.factorial(k) for k in range(max_goals + 1))


def _poisson_win_prob(lam_home: float, lam_away: float, max_goals: int) -> float:
    """P(home regulation goals > away) + 0.5 * P(tie), from independent Poisson margins."""
    ph = _poisson_pmf_row(lam_home, max_goals)
    pa = _poisson_pmf_row(lam_away, max_goals)
    p_home = 0.0
    p_tie = 0.0
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            joint = ph[h] * pa[a]
            if h > a:
                p_home += joint
            elif h == a:
                p_tie += joint
    return p_home + 0.5 * p_tie


def _elo_win_prob(home_elo: Optional[float], away_elo: Optional[float], profile: ProjectionProfile) -> Optional[float]:
    if home_elo is None or away_elo is None:
        return None
    ra = float(home_elo) + profile.elo_home_adv
    rb = float(away_elo)
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / profile.elo_scale))


def project_game(
    home: HockeyTeamFeatures,
    away: HockeyTeamFeatures,
    *,
    profile: ProjectionProfile = NHL_PROJECTION_PROFILE,
) -> GameProjection:
    """Project one game from team-strength inputs.

    Expected goals use a Dixon-Coles-style attack x opponent-defense multiplier on the league
    baseline, with home-ice applied multiplicatively::

        att_home = shrink(xgf_home / league_xg)
        def_away = shrink(xga_away / league_xg)
        E[home goals] = baseline * clip(att_home * def_away) * home_ice_mult

    (symmetrically for the away side). Regulation goals are split into per-period lambdas by the
    profile's period shares, and a moneyline seed is derived from the Poisson score matrix
    (optionally blended with an Elo rating win prob).
    """
    base = float(profile.league_baseline_goals_per_60)
    league_xg = float(profile.league_xg_per_60) or 3.05

    att_home = _shrink(_offense_rate(home, profile) / league_xg, profile.regression)
    att_away = _shrink(_offense_rate(away, profile) / league_xg, profile.regression)
    def_home = _shrink(_defense_rate(home, profile) / league_xg, profile.regression)
    def_away = _shrink(_defense_rate(away, profile) / league_xg, profile.regression)

    mult_home = _clamp(att_home * def_away, profile.strength_mult_clip_low, profile.strength_mult_clip_high)
    mult_away = _clamp(att_away * def_home, profile.strength_mult_clip_low, profile.strength_mult_clip_high)

    proj_home = base * mult_home * profile.home_ice_attack_mult
    proj_away = base * mult_away * profile.away_ice_attack_mult

    # Per-period split (renormalize shares defensively).
    shares = list(profile.period_shares)
    ssum = sum(shares) or 1.0
    shares = [s / ssum for s in shares]
    period_home = tuple(round(proj_home * s, 6) for s in shares)
    period_away = tuple(round(proj_away * s, 6) for s in shares)

    # Win-prob seed: Poisson score matrix on regulation lambdas, optionally Elo-blended.
    p_home = _poisson_win_prob(proj_home, proj_away, profile.max_goals)
    elo_p = _elo_win_prob(home.elo_rating, away.elo_rating, profile)
    if elo_p is not None and profile.elo_blend_weight > 0:
        w = _clamp(profile.elo_blend_weight, 0.0, 1.0)
        p_home = (1.0 - w) * p_home + w * elo_p
    p_home = _clamp(p_home, 1e-4, 1.0 - 1e-4)

    return GameProjection(
        proj_home_goals=round(proj_home, 4),
        proj_away_goals=round(proj_away, 4),
        model_total=round(proj_home + proj_away, 4),
        model_spread=round(proj_home - proj_away, 4),
        period_home_lambdas=period_home,  # type: ignore[arg-type]
        period_away_lambdas=period_away,  # type: ignore[arg-type]
        p_home_ml_seed=round(p_home, 6),
        p_away_ml_seed=round(1.0 - p_home, 6),
    )


def apply_projection(
    home: HockeyTeamFeatures,
    away: HockeyTeamFeatures,
    *,
    profile: ProjectionProfile = NHL_PROJECTION_PROFILE,
) -> Tuple[HockeyTeamFeatures, HockeyTeamFeatures, GameProjection]:
    """Convenience: project the game and return updated team features with period lambdas set.

    Loaders call this so the downstream adapter (:func:`hockeysim.adapters.build_game_prediction`),
    which reads ``team.period_goal_lambdas``, transparently consumes the projection. Returns
    ``(home_with_lambdas, away_with_lambdas, projection)``.

    Also back-fills ``goals_per_60`` from the projected (opponent- and home-ice-adjusted) goal
    rate. Without this, ``goals_per_60`` sits at its dataclass default (2.9 -- the OLD, pre-Phase-3b
    vendor constant, not the truth-calibrated ``league_baseline_goals_per_60`` of 3.1269) for EVERY
    team, because nothing else on the loader path ever sets it (`docs/ai_context/hockeysim_engine_reference.md`
    §CONSUMED+UNPOPULATED). That default is what ``player_props.py``'s ``TeamRates`` -- the boxscore
    /props engine's actual rate input -- reads verbatim, so every team's shot/goal environment for
    SOG, saves, and points props was identical and stale. This does not fix ``shots_per_60`` /
    ``faceoff_win_pct`` -- those have no equivalent projected value to back-fill from; both now have
    real producers instead (`hockeysim_engine_reference.md` §2j). ``blocks_per_60``/``penalties_per_60``
    were REMOVED from ``HockeyTeamFeatures``/``TeamRates`` entirely (§2l) -- confirmed dead code, not
    an absent input needing a producer.
    """
    proj = project_game(home, away, profile=profile)
    new_home = replace(home, period_goal_lambdas=proj.period_home_lambdas, goals_per_60=proj.proj_home_goals)
    new_away = replace(away, period_goal_lambdas=proj.period_away_lambdas, goals_per_60=proj.proj_away_goals)
    return new_home, new_away, proj
