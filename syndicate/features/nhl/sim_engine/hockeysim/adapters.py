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

# Game-market calibration (lane `nhl-game-lines-model`, user decision 2026-10-03 "ship the four sim
# fixes"). Fit walk-forward on the 2025-26 season (every game predates 2026-27, so as-of for production;
# stable across the season: s 0.93-0.94, delta 0.75-0.88, e 0.25-0.30, q 0.48-0.50), and measured OOS
# 2026-01-01..04-16 (n=681) in docs/reports/nhl_game_lines_model_experiments_2026-10-02.md (variant V4):
#   regulation_scale  -- the projection's 3.1269 goals/team/60 is a FULL-GAME rate (incl. OT goals and SO
#                        credits) used as a REGULATION rate: +0.358 regulation over-projection. Applied to
#                        the game-market lambdas ONLY, so the props engine's goal environment is untouched.
#   tie_weight        -- regulation ties 0.160 modelled vs 0.2465 actual.
#   empty_net_p       -- a one-goal regulation lead becomes two (restores puck-line shape once ties are
#                        re-weighted).
#   full_game_settlement + ot_home_win_prob -- books settle ML/PL/totals on the final incl. OT/SO.
# Together: settled-total bias +0.272 [+0.131, +0.407] -> -0.016 [-0.159, +0.121] (full 2025-26).
# These are mechanisms on a calibrated engine, so the absorbing rates were re-fit with them
# (model_engine_standard 4.4). Off switch: SYNDICATE_NHL_GAME_MARKET_CALIBRATION=off (legacy behaviour).
NHL_GAME_MARKET_CALIBRATION: Dict[str, object] = {
    "regulation_scale": 0.9398,
    "tie_weight": 0.7539,
    "empty_net_p": 0.3006,
    "full_game_settlement": True,
    "ot_home_win_prob": 0.5,
}
LEGACY_GAME_MARKET: Dict[str, object] = {
    "regulation_scale": 1.0,
    "tie_weight": 0.0,
    "empty_net_p": None,
    "full_game_settlement": False,
    "ot_home_win_prob": 0.5,
}


def game_market_calibration() -> Dict[str, object]:
    """The calibration production uses: the fitted one unless the env switch says off."""
    import os

    raw = str(os.environ.get("SYNDICATE_NHL_GAME_MARKET_CALIBRATION") or "").strip().lower()
    return dict(LEGACY_GAME_MARKET if raw in {"off", "0", "false", "legacy"} else NHL_GAME_MARKET_CALIBRATION)


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


def _finite(value: object, default: float = 0.0) -> float:
    """Coerce a sim probability to a finite float (NaN/inf -> default).

    ``simulate_from_period_lambdas`` returns NaN for over/under when no totals line is supplied;
    the emitted artifact row must never carry NaN (breaks CSV/JSON + downstream grading), so an
    ungraded market degrades to 0.0. The totals-line fallback policy lives in the producer, not here.
    """
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def build_game_prediction(
    game: HockeyGameFeatures,
    *,
    n_sims: int = _DEFAULT_GAME_SIMS,
    seed: Optional[int] = None,
    calibration: Optional[Dict[str, object]] = None,
) -> HockeyGamePrediction:
    """Aggregate the fast game-market sim into a full predictions row for one game.

    ``calibration`` defaults to :func:`game_market_calibration` (production); pass
    ``LEGACY_GAME_MARKET`` for the pre-2026-10-03 behaviour, which is reproduced seed for seed.
    """
    cal = dict(calibration if calibration is not None else game_market_calibration())
    scale = float(cal.get("regulation_scale") or 1.0)
    hp = [max(0.0, float(x)) for x in game.home.period_goal_lambdas][:3]
    ap = [max(0.0, float(x)) for x in game.away.period_goal_lambdas][:3]
    while len(hp) < 3:
        hp.append(0.9)
    while len(ap) < 3:
        ap.append(0.9)
    if scale != 1.0:
        hp = [x * scale for x in hp]
        ap = [x * scale for x in ap]

    market: HockeyMarketLines = game.market
    total_line = market.total_line
    puck_line = float(market.puck_line or -1.5)

    seed_val = int(seed) if seed is not None else game_seed(game.date, game.game_pk)
    settle = bool(cal.get("full_game_settlement"))
    cfg = GameMarketSimConfig(
        n_sims=int(n_sims), random_state=seed_val,
        empty_net_p=cal.get("empty_net_p"),
        tie_weight=float(cal.get("tie_weight") or 0.0),
        full_game_settlement=settle,
        ot_home_win_prob=float(cal.get("ot_home_win_prob") or 0.5),
    )
    probs = simulate_from_period_lambdas(
        home_periods=hp, away_periods=ap, total_line=total_line, puck_line=puck_line, cfg=cfg
    )

    if "expected_home_goals" in probs:
        # calibrated: projected goals are the SETTLED expectation (regulation + the OT/SO goal)
        proj_home = float(probs["expected_home_goals"])
        proj_away = float(probs["expected_away_goals"])
    else:
        proj_home = float(sum(hp))
        proj_away = float(sum(ap))
    model_total = proj_home + proj_away
    # model_spread: home margin (positive = home projected to win by that much).
    model_spread = proj_home - proj_away

    # First-10-minute "yes goal" market: first-period lambda scaled to the opening 10 of 20 min.
    lam_f10 = (hp[0] + ap[0]) * (10.0 / 20.0)
    p_f10_yes = _p_at_least_one(lam_f10)

    # Push probability only matters for integer totals.
    p_push = 0.0
    if total_line is not None and float(total_line).is_integer():
        if "push" in probs:
            p_push = float(probs["push"])
        else:
            # legacy: sum of independent Poissons ~ Poisson(sum)
            p_push = _poisson_pmf(int(total_line), model_total)

    p_over = _finite(probs.get("over"))
    p_under = _finite(probs.get("under"))
    p_home_ml = _finite(probs.get("home_ml"))
    p_away_ml = _finite(probs.get("away_ml"))
    p_home_pl = _finite(probs.get("home_puckline_-1.5"))
    p_away_pl = _finite(probs.get("away_puckline_+1.5"))

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
