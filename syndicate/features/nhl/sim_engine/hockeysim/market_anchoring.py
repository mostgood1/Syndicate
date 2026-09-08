"""Market anchoring for hockeysim — pull the projection's win prob toward the book, keep the pace.

Port of soccer's ``market_anchoring`` (ratings-level bisection anchor, validated −40–51% MAE on
EPL), reduced to a **2-way** home-win problem for hockey (moneyline ties are resolved in OT/SO, so
the market is effectively home vs away).

Mechanics: the projection gives expected home/away goals whose Poisson home-win probability is
``model_p``. We blend that toward the devigged market home-win probability
``target = (1-weight)*model_p + weight*market_p``, then solve — by bisection — the goal-differential
shift ``s`` that makes ``P(home win | home+ s, away- s) == target``. The shift **preserves the total**
(``home+away`` is unchanged), so the calibrated pace / totals market is untouched while the
moneyline + puckline anchor to the book. Period lambdas are rescaled proportionally.

Anchoring is opt-in at the LOADER seam (``loaders.build_game_features(anchor_to_market=False)``),
but the production artifact producer (``scripts/build_nhl_artifacts.py``, called by
``scripts/refresh_nhl_oddsapi.py``) bypasses that flag and anchors every game that has a usable
moneyline at ``_DEFAULT_WEIGHT`` (0.35) BEFORE the game-market sim runs — so the served
``p_home_ml`` / ``p_home_pl_-1.5`` in ``predictions_{date}.csv`` are a 65/35 model/market blend,
not the pure model. The env flag ``SYNDICATE_NHL_MARKET_ANCHOR_WEIGHT`` (``resolve_anchor_weight``)
is the ONE production knob: absent keeps 0.35, ``0`` disables anchoring, any float in ``[0, 1]`` is
used as-is. The producer records ``anchor_weight`` / ``anchor_state`` and the un-anchored
``p_home_ml_raw`` / ``p_home_pl_-1.5_raw`` on every artifact row so the pure model survives beside
the served number (pricing plane v1, P4).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Mapping, Optional, Tuple

from .adapters import american_to_implied
from .contracts import HockeyGameFeatures, HockeyMarketLines, HockeyTeamFeatures
from .projection import _poisson_win_prob  # 2-way (ties split 50/50) Poisson home-win prob

_DEFAULT_WEIGHT = 0.35
_MAX_GOALS = 10

# Production knob (P4). Absent => `_DEFAULT_WEIGHT` (today's behaviour, bit-identical); "0" => no
# anchoring; any float in [0, 1] => that weight. Out-of-range values are clamped; unparseable
# values fall back to the default and say so in the returned `source`.
ENV_ANCHOR_WEIGHT = "SYNDICATE_NHL_MARKET_ANCHOR_WEIGHT"

# `anchor_state` values recorded per predictions row.
ANCHOR_STATE_ANCHORED = "anchored"      # a usable moneyline existed and weight > 0: lambdas were shifted
ANCHOR_STATE_NO_MARKET = "no_market"    # weight > 0 but no usable moneyline: pass-through, served == raw
ANCHOR_STATE_DISABLED = "disabled"      # weight == 0 (flag or --no-anchor): served == raw


def resolve_anchor_weight(
    explicit: Optional[float] = None, *, env: Optional[Mapping[str, str]] = None,
) -> Tuple[float, str]:
    """Return ``(weight, source)`` — the ONE resolved anchor weight the producer must honour.

    Precedence: an ``explicit`` value (CLI ``--anchor-weight`` / a caller's kwarg) beats the env
    flag, which beats ``_DEFAULT_WEIGHT``. ``source`` is one of ``explicit`` / ``env`` /
    ``default`` / ``default_invalid_env`` so the caller can log where the number came from.
    """
    if explicit is not None:
        return max(0.0, min(1.0, float(explicit))), "explicit"
    env_map = os.environ if env is None else env
    raw = str(env_map.get(ENV_ANCHOR_WEIGHT) or "").strip()
    if not raw:
        return _DEFAULT_WEIGHT, "default"
    try:
        val = float(raw)
    except ValueError:
        return _DEFAULT_WEIGHT, "default_invalid_env"
    if val != val:  # NaN
        return _DEFAULT_WEIGHT, "default_invalid_env"
    return max(0.0, min(1.0, val)), "env"


def anchor_state_for(market: "HockeyMarketLines", weight: float) -> str:
    """Classify what anchoring will do for a game at ``weight`` — mirrors ``anchor_game_features``'s
    own no-op rule so the recorded state can never disagree with what happened."""
    if float(weight) <= 0.0:
        return ANCHOR_STATE_DISABLED
    if market_home_prob(market) is None:
        return ANCHOR_STATE_NO_MARKET
    return ANCHOR_STATE_ANCHORED


def devig_two_way_home_prob(home_odds: Optional[int], away_odds: Optional[int]) -> Optional[float]:
    """Devigged market home-win probability from 2-way American moneyline odds."""
    ph = american_to_implied(home_odds)
    pa = american_to_implied(away_odds)
    if ph is None or pa is None:
        return None
    denom = ph + pa
    if denom <= 0:
        return None
    return ph / denom


def market_home_prob(market: HockeyMarketLines) -> Optional[float]:
    """Prefer an explicit devigged prob on the market, else devig the moneyline odds."""
    if market.home_win_probability is not None:
        return max(0.0, min(1.0, float(market.home_win_probability)))
    return devig_two_way_home_prob(market.home_ml_odds, market.away_ml_odds)


def _solve_goal_shift(lam_h: float, lam_a: float, target_p: float, *, max_goals: int = _MAX_GOALS,
                      iters: int = 60, tol: float = 1e-5) -> float:
    """Bisection: find shift ``s`` so ``win_prob(lam_h+s, lam_a-s) ≈ target_p`` (total preserved).

    ``P(home win)`` is monotone increasing in ``s``; ``s`` is bounded so neither λ goes negative.
    Returns the shift clamped to the feasible interval when the target is unreachable.
    """
    eps = 1e-6
    lo, hi = -lam_h + eps, lam_a - eps
    if lo >= hi:
        return 0.0
    # If target is outside the reachable range, clamp to the nearest feasible endpoint.
    if _poisson_win_prob(lam_h + lo, lam_a - lo, max_goals) >= target_p:
        return lo
    if _poisson_win_prob(lam_h + hi, lam_a - hi, max_goals) <= target_p:
        return hi
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p = _poisson_win_prob(lam_h + mid, lam_a - mid, max_goals)
        if abs(p - target_p) < tol:
            return mid
        if p < target_p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class AnchorResult:
    home_goals: float
    away_goals: float
    model_home_prob: float
    market_home_prob: float
    target_home_prob: float
    shift: float


def anchor_expected_goals(
    home_goals: float,
    away_goals: float,
    market_p: float,
    *,
    weight: float = _DEFAULT_WEIGHT,
    max_goals: int = _MAX_GOALS,
) -> AnchorResult:
    """Shift expected goals so the home-win prob blends toward the market (total preserved)."""
    w = max(0.0, min(1.0, float(weight)))
    lam_h = max(0.0, float(home_goals))
    lam_a = max(0.0, float(away_goals))
    model_p = _poisson_win_prob(lam_h, lam_a, max_goals)
    target = (1.0 - w) * model_p + w * float(market_p)
    shift = _solve_goal_shift(lam_h, lam_a, target, max_goals=max_goals)
    return AnchorResult(
        home_goals=round(lam_h + shift, 6),
        away_goals=round(lam_a - shift, 6),
        model_home_prob=round(model_p, 6),
        market_home_prob=round(float(market_p), 6),
        target_home_prob=round(target, 6),
        shift=round(shift, 6),
    )


def _rescale_periods(periods: Tuple[float, ...], old_total: float, new_total: float) -> Tuple[float, float, float]:
    lst = [max(0.0, float(x)) for x in periods][:3]
    while len(lst) < 3:
        lst.append(0.0)
    if old_total <= 0:
        # Degenerate: distribute the new total evenly.
        even = new_total / 3.0
        return (round(even, 6), round(even, 6), round(even, 6))
    scale = new_total / old_total
    return tuple(round(x * scale, 6) for x in lst)  # type: ignore[return-value]


def anchor_game_features(
    game: HockeyGameFeatures,
    *,
    weight: float = _DEFAULT_WEIGHT,
    max_goals: int = _MAX_GOALS,
) -> HockeyGameFeatures:
    """Return a copy of ``game`` with period lambdas anchored toward the market moneyline.

    No-op (returns the input unchanged) when the market carries no usable home-win probability, so
    the caller can anchor unconditionally and slates without odds simply pass through.
    """
    mp = market_home_prob(game.market)
    if mp is None:
        return game

    home_total = float(sum(game.home.period_goal_lambdas))
    away_total = float(sum(game.away.period_goal_lambdas))
    res = anchor_expected_goals(home_total, away_total, mp, weight=weight, max_goals=max_goals)

    new_home_periods = _rescale_periods(game.home.period_goal_lambdas, home_total, res.home_goals)
    new_away_periods = _rescale_periods(game.away.period_goal_lambdas, away_total, res.away_goals)
    new_home: HockeyTeamFeatures = replace(game.home, period_goal_lambdas=new_home_periods)
    new_away: HockeyTeamFeatures = replace(game.away, period_goal_lambdas=new_away_periods)
    return replace(game, home=new_home, away=new_away)
