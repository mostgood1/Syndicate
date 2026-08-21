from __future__ import annotations

from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _shared_game_state(game: dict[str, Any]) -> dict[str, Any]:
    live_state = _copy_mapping(game.get("live_state"))
    status_value = game.get("status")
    status_text = _safe_text(status_value.get("status") if isinstance(status_value, Mapping) else status_value, "Scheduled")
    detail_text = _safe_text(game.get("detail") or (status_value or {}).get("detail") if isinstance(status_value, Mapping) else None, status_text)
    return {
        "status": status_text,
        "detail": detail_text,
        "startTime": _safe_text(game.get("startTime") or game.get("start_time") or game.get("gameTime") or live_state.get("startTime") or live_state.get("start_time"), "") or None,
        "live": bool(live_state.get("in_progress") or live_state.get("live")),
        "final": bool(live_state.get("final") or game.get("final")),
        "period": _first_number(live_state.get("period"), game.get("period")),
        "clock": _safe_text(live_state.get("clock") or game.get("clock"), ""),
    }


def _probabilities_from_rows(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    if not rows:
        return {}
    first_row = rows[0]
    away_pct = _safe_float(first_row.get("away_pct"))
    home_pct = _safe_float(first_row.get("home_pct"))
    if away_pct is None and home_pct is None:
        return {}
    if away_pct is None and home_pct is not None:
        away_pct = 100.0 - home_pct
    if home_pct is None and away_pct is not None:
        home_pct = 100.0 - away_pct
    return {
        "away_win": (away_pct / 100.0) if away_pct is not None else None,
        "home_win": (home_pct / 100.0) if home_pct is not None else None,
    }


def _shared_predictions(game: dict[str, Any]) -> dict[str, Any]:
    predictions = _copy_mapping(game.get("predictions"))
    sim = _copy_mapping(game.get("sim") or game.get("simulation"))
    score = _copy_mapping(predictions.get("score") or sim.get("score") or game.get("score"))
    period_rows = game.get("shared_period_rows") if isinstance(game.get("shared_period_rows"), list) else []
    probabilities = _copy_mapping(predictions.get("probabilities"))
    if not probabilities:
        probabilities = _probabilities_from_rows([row for row in period_rows if isinstance(row, Mapping)])
    # THE FULL-GAME PERIOD IS A SOURCE OF RECORD AND WAS NOT BEING READ.
    #
    # This function looked in `predictions`, then `sim.score`, then `score` --
    # but never in `sim.periods.full`, where several producers put the complete
    # four-field projection. NFL's preseason and regular-season cards
    # (`nfl/preseason_cards.py`, `nfl/cards.py`) set all four in
    # `sim.periods.full` and only TWO -- away_mean/home_mean -- in `sim.score`.
    #
    # MEASURED ON PRODUCTION 2026-08-18, both NFL boards, 16 of 16 games each:
    #   home_mean  100%   away_mean  100%
    #   total_mean   0%   margin_mean  0%
    #
    # The artifact had them the whole time: `SmartSimNflPreseasonProjection`
    # carries `margin_mean` and `total_mean` as required CSV columns. They were
    # dropped in transit, so the board could show a projected SCORE but no
    # projected SPREAD or TOTAL -- on a betting product, the two numbers a line
    # is actually compared against.
    full_period = {}
    periods = sim.get("periods")
    if isinstance(periods, Mapping):
        candidate = periods.get("full")
        if isinstance(candidate, Mapping):
            full_period = dict(candidate)

    away_mean = _first_number(predictions.get("away_mean"), score.get("away_mean"), score.get("away"), full_period.get("away_mean"))
    home_mean = _first_number(predictions.get("home_mean"), score.get("home_mean"), score.get("home"), full_period.get("home_mean"))
    total_mean = _first_number(predictions.get("total_mean"), score.get("total_mean"), score.get("total"), full_period.get("total_mean"))
    margin_mean = _first_number(predictions.get("margin_mean"), score.get("margin_mean"), score.get("margin"), full_period.get("margin_mean"))

    # Last resort, and DEFINITIONAL rather than a guess: a projected total is
    # the sum of the two projected scores and a projected margin is their
    # difference. `game_board_contract._normalize_game` already derives exactly
    # this for its market tiles (both directions), so the arithmetic is settled
    # in this codebase -- it simply never reached the published payload.
    #
    # Ordered AFTER every real source so a producer that supplies its own value
    # always wins; this can only fill a hole, never overwrite.
    if total_mean is None and away_mean is not None and home_mean is not None:
        total_mean = round(away_mean + home_mean, 3)
    if margin_mean is None and away_mean is not None and home_mean is not None:
        margin_mean = round(home_mean - away_mean, 3)

    # `sim.win_probability` IS A SOURCE OF RECORD AND WAS NOT BEING READ --
    # the same shape of defect as `sim.periods.full` immediately above, one key
    # over.
    #
    # MEASURED ON PRODUCTION 2026-08-21, all four of the day's soccer fixtures:
    # every one of the six `probabilities` fields was null on every card, while
    # `sim.win_probability` carried {home 0.79, draw 0.14, away 0.07} on the
    # SAME payload. This function looked for `predictions.p_home_win`; soccer
    # publishes the model's 1X2 under `sim.win_probability` and its de-vigged
    # MARKET view under `betting.p_home_win`, so neither lookup could ever hit.
    #
    # READ THE SIM, NOT `betting.*`, and that distinction is the whole point.
    # `betting.p_home_win` is the market's de-vigged probability; putting it in
    # a block called `predictions` would publish the market as the model's
    # opinion and make every edge computed against it read as zero. The cover
    # and total legs are therefore LEFT NULL rather than filled from `betting`:
    # soccer publishes no model number for them on this payload, and a null a
    # reader can see beats a market number wearing the model's label.
    win_probability = _copy_mapping(sim.get("win_probability"))

    # DRAW IS A REAL OUTCOME AND THE CONTRACT HAD NO KEY FOR IT. On a three-way
    # sport it carries 14-23% of the outcome space, so a home/away-only block
    # does not sum to 1 and cannot be read as a distribution. Emitted only when
    # a producer actually supplies one, so two-way sports are unchanged rather
    # than gaining a null field.
    draw = _first_number(probabilities.get("draw"), win_probability.get("draw"), predictions.get("p_draw"))

    result_probabilities = {
        "home_win": _first_number(probabilities.get("home_win"), predictions.get("home_win_prob"), predictions.get("p_home_win"), win_probability.get("home")),
        "away_win": _first_number(probabilities.get("away_win"), predictions.get("away_win_prob"), predictions.get("p_away_win"), win_probability.get("away")),
        "home_cover": _first_number(probabilities.get("home_cover"), predictions.get("p_home_cover")),
        "away_cover": _first_number(probabilities.get("away_cover"), predictions.get("p_away_cover")),
        "total_over": _first_number(probabilities.get("total_over"), predictions.get("p_total_over")),
        "total_under": _first_number(probabilities.get("total_under"), predictions.get("p_total_under")),
    }
    if draw is not None:
        result_probabilities["draw"] = draw

    return {
        "away_mean": away_mean,
        "home_mean": home_mean,
        "total_mean": total_mean,
        "margin_mean": margin_mean,
        "probabilities": result_probabilities,
    }


def _shared_markets(game: dict[str, Any]) -> dict[str, Any]:
    betting = _copy_mapping(game.get("betting"))
    markets = _copy_mapping(game.get("markets"))
    market = _copy_mapping(game.get("market"))

    home_ml = _first_number(
        betting.get("home_ml"),
        markets.get("home_ml"),
        market.get("home_ml"),
        market.get("homeMoneyline"),
    )
    away_ml = _first_number(
        betting.get("away_ml"),
        markets.get("away_ml"),
        market.get("away_ml"),
        market.get("awayMoneyline"),
    )
    home_spread = _first_number(
        betting.get("home_spread"),
        markets.get("home_spread"),
        market.get("home_spread"),
    )
    away_spread = _first_number(
        betting.get("away_spread"),
        markets.get("away_spread"),
        market.get("away_spread"),
    )
    total_line = _first_number(
        betting.get("total"),
        markets.get("total"),
        market.get("total"),
        market.get("total_line"),
    )
    probabilities = _copy_mapping(betting.get("probabilities"))
    if not probabilities:
        probabilities = {
            "home_win": _first_number(betting.get("p_home_win"), markets.get("p_home_win"), market.get("p_home_win")),
            "away_win": _first_number(betting.get("p_away_win"), markets.get("p_away_win"), market.get("p_away_win")),
            "home_cover": _first_number(betting.get("p_home_cover"), markets.get("p_home_cover"), market.get("p_home_cover")),
            "away_cover": _first_number(betting.get("p_away_cover"), markets.get("p_away_cover"), market.get("p_away_cover")),
            "total_over": _first_number(betting.get("p_total_over"), markets.get("p_total_over"), market.get("p_total_over")),
            "total_under": _first_number(betting.get("p_total_under"), markets.get("p_total_under"), market.get("p_total_under")),
        }

    return {
        "moneyline": {"home": home_ml, "away": away_ml},
        "spread": {"home": home_spread, "away": away_spread},
        "total": {"line": total_line},
        "prices": {"home_ml": home_ml, "away_ml": away_ml},
        "probabilities": probabilities,
    }


def normalize_publication_game(game: dict[str, Any], *, sport: str | None = None) -> dict[str, Any]:
    if not isinstance(game, dict):
        return game
    sport_key = _safe_text(sport or game.get("sport") or game.get("sport_slug"), "").lower()
    normalized = dict(game)
    if sport_key in {"mlb", "wnba"}:
        return normalized

    shared_state = _shared_game_state(normalized)
    shared_predictions = _shared_predictions(normalized)
    shared_markets = _shared_markets(normalized)

    normalized["shared_game_state"] = shared_state
    normalized["shared_predictions"] = shared_predictions
    normalized["shared_markets"] = shared_markets

    if not isinstance(normalized.get("predictions"), dict):
        normalized["predictions"] = shared_predictions
    if not isinstance(normalized.get("markets"), dict):
        normalized["markets"] = shared_markets

    return normalized