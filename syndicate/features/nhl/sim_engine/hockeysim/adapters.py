"""Adapter: HockeyGameFeatures -> engine runs -> artifact-shaped predictions.

Mirrors ``soccersim.adapters`` / football ``FootballSimulationAdapter``. Bridges the frozen
feature contracts to the two engines and produces the artifact-shaped outputs the NHL UI reads:

  * ``build_game_prediction``  -> HockeyGamePrediction (predictions_{date}.csv rows) via the fast
    period-lambda game-market sim (``game_market_sim``).
  * ``build_prop_projections`` (Phase 2b) -> HockeyPropProjection rows via the boxscore engine.

Seeding is deterministic per game (crc32 of date:game_pk) so a slate is reproducible.

NOTE (Phase 2a): game-market probabilities come from the re-homed ``simulate_from_period_lambdas``;
``proj``/``spread``/``p_f10``/``p_push`` are computed analytically from the period lambdas here.
Exact column/So-order parity with the legacy vendor CLI output is reconciled in Phase 2b against a
real ``predictions_*.csv`` sample (see plan). The math is faithful NHL modelling, not yet a
guaranteed byte-match.
"""
from __future__ import annotations

import math
import zlib
from typing import Dict, Optional

from .contracts import HockeyGameFeatures, HockeyGamePrediction, HockeyMarketLines
from .game_market_sim import SimConfig as GameMarketSimConfig
from .game_market_sim import simulate_from_period_lambdas

_DEFAULT_GAME_SIMS = 20000


def game_seed(date: str, game_pk: str) -> int:
    """Deterministic per-game seed."""
    return int(zlib.crc32(f"{date}:{game_pk}".encode("utf-8")) & 0xFFFFFFFF)


def american_to_decimal(odds: Optional[int]) -> Optional[float]:
    if odds is None:
        return None
    o = float(odds)
    if o == 0:
        return None
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / abs(o))


def american_to_implied(odds: Optional[int]) -> Optional[float]:
    dec = american_to_decimal(odds)
    return None if not dec else 1.0 / dec


def ev_per_unit(prob: float, odds: Optional[int]) -> Optional[float]:
    """Expected value per 1u stake given a model probability and American odds."""
    dec = american_to_decimal(odds)
    if dec is None:
        return None
    profit = dec - 1.0
    return float(prob) * profit - (1.0 - float(prob))


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _p_at_least_one(lam: float) -> float:
    return 1.0 - math.exp(-max(0.0, float(lam)))


def build_game_prediction(
    game: HockeyGameFeatures,
    *,
    n_sims: int = _DEFAULT_GAME_SIMS,
    seed: Optional[int] = None,
) -> HockeyGamePrediction:
    """Aggregate the fast game-market sim into a full predictions row for one game."""
    hp = [max(0.0, float(x)) for x in game.home.period_goal_lambdas][:3]
    ap = [max(0.0, float(x)) for x in game.away.period_goal_lambdas][:3]
    while len(hp) < 3:
        hp.append(0.9)
    while len(ap) < 3:
        ap.append(0.9)

    market: HockeyMarketLines = game.market
    total_line = market.total_line
    puck_line = float(market.puck_line or -1.5)

    seed_val = int(seed) if seed is not None else game_seed(game.date, game.game_pk)
    cfg = GameMarketSimConfig(n_sims=int(n_sims), random_state=seed_val)
    probs = simulate_from_period_lambdas(
        home_periods=hp, away_periods=ap, total_line=total_line, puck_line=puck_line, cfg=cfg
    )

    proj_home = float(sum(hp))
    proj_away = float(sum(ap))
    model_total = proj_home + proj_away
    # model_spread: home margin (positive = home projected to win by that much).
    model_spread = proj_home - proj_away

    # First-10-minute "yes goal" market: first-period lambda scaled to the opening 10 of 20 min.
    lam_f10 = (hp[0] + ap[0]) * (10.0 / 20.0)
    p_f10_yes = _p_at_least_one(lam_f10)

    # Push probability only matters for integer totals; sum of independent Poissons ~ Poisson(sum).
    p_push = 0.0
    if total_line is not None and float(total_line).is_integer():
        p_push = _poisson_pmf(int(total_line), model_total)

    p_over = float(probs.get("over") or 0.0)
    p_under = float(probs.get("under") or 0.0)
    p_home_ml = float(probs.get("home_ml") or 0.0)
    p_away_ml = float(probs.get("away_ml") or 0.0)
    p_home_pl = float(probs.get("home_puckline_-1.5") or 0.0)
    p_away_pl = float(probs.get("away_puckline_+1.5") or 0.0)

    ev: Dict[str, float] = {}
    for key, prob, odds in (
        ("home_ml", p_home_ml, market.home_ml_odds),
        ("away_ml", p_away_ml, market.away_ml_odds),
        ("over", p_over, market.over_odds),
        ("under", p_under, market.under_odds),
        ("home_pl_-1.5", p_home_pl, market.home_pl_odds),
        ("away_pl_+1.5", p_away_pl, market.away_pl_odds),
    ):
        val = ev_per_unit(prob, odds)
        if val is not None:
            ev[key] = float(val)

    return HockeyGamePrediction(
        home=game.home.name,
        away=game.away.name,
        date=game.date,
        game_pk=game.game_pk,
        proj_home_goals=round(proj_home, 4),
        proj_away_goals=round(proj_away, 4),
        model_total=round(model_total, 4),
        model_spread=round(model_spread, 4),
        period_home_proj=(round(hp[0], 4), round(hp[1], 4), round(hp[2], 4)),
        period_away_proj=(round(ap[0], 4), round(ap[1], 4), round(ap[2], 4)),
        p_home_ml=p_home_ml,
        p_away_ml=p_away_ml,
        p_over=p_over,
        p_under=p_under,
        p_push_total=p_push,
        p_home_pl_minus_1_5=p_home_pl,
        p_away_pl_plus_1_5=p_away_pl,
        p_f10_yes=p_f10_yes,
        p_f10_no=1.0 - p_f10_yes,
        totals_line_used=total_line,
        ev=ev,
    )
