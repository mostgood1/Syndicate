from __future__ import annotations

from typing import Any

from syndicate.features.bankroll_manager import build_portfolio as _build_portfolio
from syndicate.features.intelligence.models import IntelligenceResponse
from syndicate.features.intelligence.models import Parlay
from syndicate.features.intelligence.models import Pick
from syndicate.features.intelligence.models import Portfolio
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _safe_float
from syndicate.features.intelligence.signals.normalization import _safe_text as _base_safe_text


MAX_CORRELATION_THRESHOLD = 0.65


def _safe_text(*values: Any, default: str = "") -> str:
    if not values:
        return default
    if len(values) == 1:
        return _base_safe_text(values[0], default)
    for value in values:
        text = _base_safe_text(value, "")
        if text:
            return text
    return default


def _has_live_signal(candidate: dict[str, Any]) -> bool:
    live_projection = _safe_text(candidate.get("live_projection"), "")
    return bool(
        candidate.get("hero_live_box")
        or candidate.get("hero_sim_box")
        or (live_projection and live_projection != "-")
        or candidate.get("live_total") is not None
    )


def _recommendation_state(candidate: dict[str, Any]) -> str:
    game_state = candidate.get("game_state") if isinstance(candidate.get("game_state"), dict) else {}
    settlement = candidate.get("settlement") if isinstance(candidate.get("settlement"), dict) else {}
    status = _safe_text(
        candidate.get("status_display")
        or candidate.get("status_context")
        or game_state.get("detailed")
        or game_state.get("abstract"),
        "",
    ).lower()
    settlement_status = _safe_text(
        settlement.get("status") if isinstance(settlement, dict) else None,
        settlement.get("status_label") if isinstance(settlement, dict) else None,
        candidate.get("settlement_status"),
        candidate.get("settlement_state"),
        candidate.get("settlement_label"),
        "",
    ).lower()
    settlement_result = _safe_text(
        settlement.get("result") if isinstance(settlement, dict) else None,
        candidate.get("settlement_result"),
        candidate.get("result"),
        "",
    ).lower()
    live_flag = candidate.get("is_live") if isinstance(candidate.get("is_live"), bool) else None
    if any(token in status for token in ("final", "completed", "settled", "resolved", "graded")):
        return "final"
    if settlement_status in {"final", "completed", "settled", "resolved", "graded"}:
        return "final"
    if settlement_result in {"won", "lost", "push", "graded", "final", "completed", "settled", "resolved"}:
        return "final"
    if "warmup" in status or "scheduled" in status or "pregame" in status:
        return "pregame"
    if ("live" in status or "in progress" in status) and live_flag and _has_live_signal(candidate):
        return "live"
    if live_flag and _has_live_signal(candidate):
        return "live"
    if "live" in status or "in progress" in status:
        return "stale"
    return "pregame"


def _response_state(candidate: dict[str, Any]) -> str:
    state = _recommendation_state(candidate)
    if state in {"final", "stale"}:
        return state
    if state == "live" and not _has_live_signal(candidate):
        return "stale"
    return state


def _frontend_display_name(candidate: dict[str, Any]) -> str:
    reasoning = _safe_text(
        candidate.get("reasoning") or candidate.get("reasoning_text") or candidate.get("summary") or candidate.get("rationale"),
        "",
    )
    if reasoning:
        import re

        match = re.search(r"\bfor\s+(.+?)\s+Props?\s+at\b", reasoning, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"\bfor\s+(.+?)\s+at\b", reasoning, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return _safe_text(
        candidate.get("player_name")
        or candidate.get("name")
        or candidate.get("subject_key")
        or candidate.get("pick")
        or candidate.get("selection")
        or candidate.get("market"),
        "Play",
    )


def _frontend_correlation_group(candidate: dict[str, Any]) -> dict[str, Any]:
    event_id = _safe_text(candidate.get("event_id"), "")
    matchup = _safe_text(candidate.get("matchup"), "")
    sport_slug = _safe_text(candidate.get("sport_slug"), "")
    market_key = _safe_text(candidate.get("market_key") or candidate.get("market"), "")
    subject_key = _safe_text(candidate.get("subject_key") or candidate.get("name") or candidate.get("pick"), "")
    group_key = event_id or matchup or f"{sport_slug}:{market_key}:{subject_key}".strip(":") or subject_key or market_key or "candidate"
    group_label = matchup or event_id or subject_key or market_key or "Candidate group"
    group_type = "game" if event_id or matchup else "candidate"
    return {
        "key": group_key,
        "label": group_label,
        "type": group_type,
        "sport_slug": sport_slug or None,
        "market_key": market_key or None,
        "subject_key": subject_key or None,
    }


def _frontend_explanation(candidate: dict[str, Any]) -> dict[str, list[str]]:
    edge_drivers: list[str] = []
    confidence_drivers: list[str] = []
    risk_flags: list[str] = []

    movement = candidate.get("movement") if isinstance(candidate.get("movement"), dict) else {}
    edge_delta = _numeric_hint(movement.get("edge_delta") if movement else None)
    current_edge = _numeric_hint(candidate.get("adjusted_edge") if candidate.get("adjusted_edge") is not None else candidate.get("edge"))
    if edge_delta is not None:
        if edge_delta > 0.01:
            edge_drivers.append(f"Line moving in our favor ({edge_delta:+.2f})")
        elif edge_delta < -0.01:
            edge_drivers.append(f"Line moving against the position ({edge_delta:+.2f})")
    if current_edge is not None:
        edge_drivers.append(f"Current edge {current_edge:+.2f}")

    model_probability = _numeric_hint(candidate.get("model_probability"))
    implied_probability = _numeric_hint(candidate.get("implied_probability"))
    confidence_value = _numeric_hint(candidate.get("confidence"))
    if model_probability is not None and implied_probability is not None:
        gap = round(model_probability - implied_probability, 4)
        if gap > 0:
            confidence_drivers.append(f"Model agrees with value versus market ({gap:+.2f})")
        elif gap < 0:
            confidence_drivers.append(f"Model is below market price ({gap:+.2f})")
        else:
            confidence_drivers.append("Model and market are aligned")
    elif confidence_value is not None:
        confidence_drivers.append(f"Confidence {confidence_value:.2f}")

    volatility_value = _numeric_hint(candidate.get("volatility") if candidate.get("volatility") is not None else candidate.get("volatility_score"))
    if volatility_value is not None:
        if volatility_value >= 0.67:
            risk_flags.append(f"High volatility ({volatility_value:.2f})")
        elif volatility_value >= 0.34:
            risk_flags.append(f"Moderate volatility ({volatility_value:.2f})")
        else:
            risk_flags.append(f"Low volatility ({volatility_value:.2f})")

    if bool(candidate.get("is_live")):
        risk_flags.append("Live market risk remains")

    if not edge_drivers:
        edge_drivers.append("No line movement signal available")
    if not confidence_drivers:
        confidence_drivers.append("No model agreement signal available")
    if not risk_flags:
        risk_flags.append("No volatility signal available")

    return {
        "edge_drivers": edge_drivers[:3],
        "confidence_drivers": confidence_drivers[:3],
        "risk_flags": risk_flags[:3],
    }


def _frontend_pick(candidate: dict[str, Any]) -> dict[str, Any]:
    bet_size_profile = candidate.get("bet_size_profile") if isinstance(candidate.get("bet_size_profile"), dict) else {}
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    bet_size = _numeric_hint(candidate.get("recommended_bet_size") or bet_size_profile.get("recommended_bet_size"))
    confidence_value = _numeric_hint(candidate.get("confidence"))
    current_edge = candidate.get("adjusted_edge") if candidate.get("adjusted_edge") is not None else candidate.get("edge")
    previous_edge = (
        candidate.get("previous_adjusted_edge")
        if candidate.get("previous_adjusted_edge") is not None
        else candidate.get("previous_edge")
    )
    if previous_edge is None:
        previous_edge = candidate.get("edge_previous") or candidate.get("prior_edge")
    previous_edge_value = _numeric_hint(previous_edge)
    current_edge_value = _numeric_hint(current_edge)
    edge_delta = None if current_edge_value is None or previous_edge_value is None else round(current_edge_value - previous_edge_value, 4)
    rising_edge = edge_delta is not None and edge_delta > 0.01
    falling_edge = edge_delta is not None and edge_delta < -0.01
    movement = {
        "edge_delta": edge_delta,
        "trend": "up" if edge_delta is not None and edge_delta > 0.01 else "down" if edge_delta is not None and edge_delta < -0.01 else "flat",
    }
    display_pills = candidate.get("display_pills") if isinstance(candidate.get("display_pills"), list) else []
    probabilities = {
        "model_probability": _numeric_hint(candidate.get("model_probability") or market_context.get("model_probability")),
        "implied_probability": _numeric_hint(candidate.get("implied_probability") or market_context.get("implied_probability")),
    }
    risk_level = _safe_text(candidate.get("risk_level"), "")
    if not risk_level:
        volatility_value = _numeric_hint(candidate.get("volatility") or candidate.get("volatility_score")) or 0.0
        if volatility_value < 0.34:
            risk_level = "low"
        elif volatility_value < 0.67:
            risk_level = "medium"
        else:
            risk_level = "high"
    selection = _safe_text(candidate.get("selection") or candidate.get("pick") or candidate.get("name"), "Play")
    explanation = _frontend_explanation(candidate)
    return {
        "display_name": _frontend_display_name(candidate),
        "selection": selection,
        "sport": _safe_text(candidate.get("sport"), "Sport"),
        "sport_slug": _safe_text(candidate.get("sport_slug"), "sport"),
        "market": _safe_text(candidate.get("market"), "Market"),
        "market_key": _safe_text(candidate.get("market_key") or candidate.get("market"), "market"),
        "matchup": _safe_text(candidate.get("matchup"), "-"),
        "line": candidate.get("line"),
        "odds": candidate.get("odds"),
        "edge": current_edge_value,
        "last_updated_timestamp": candidate.get("last_updated_timestamp") or candidate.get("updated_at") or candidate.get("timestamp"),
        "previous_edge": previous_edge_value,
        "edge_delta": edge_delta,
        "rising_edge": rising_edge,
        "falling_edge": falling_edge,
        "confidence": confidence_value,
        "model_probability": probabilities["model_probability"],
        "implied_probability": probabilities["implied_probability"],
        "recommended_bet_size": bet_size,
        "risk_level": risk_level,
        "expected_value": _numeric_hint(candidate.get("expected_value")),
        "volatility": _numeric_hint(candidate.get("volatility") if candidate.get("volatility") is not None else candidate.get("volatility_score")),
        "drivers": [dict(item) for item in (candidate.get("signal_contributions_top_positive") or []) if isinstance(item, dict)],
        "risks": [dict(item) for item in (candidate.get("signal_contributions_top_negative") or []) if isinstance(item, dict)],
        "explanation": explanation,
        "visual": {
            "pills": [str(item).strip() for item in display_pills if str(item).strip()][:6],
            "risk_level": risk_level,
            "correlation_group": _frontend_correlation_group(candidate),
        },
        "movement": movement,
    }


def _frontend_portfolio(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    portfolio = _build_portfolio(recommendations, max_correlation_threshold=MAX_CORRELATION_THRESHOLD)
    risk_profile = portfolio.get("risk_profile") if isinstance(portfolio.get("risk_profile"), dict) else {}

    def _number(*values: Any, default: float = 0.0) -> float:
        for value in values:
            numeric_value = _safe_float(value)
            if numeric_value is not None:
                return numeric_value
        return default

    risk_level = _safe_text(risk_profile.get("level") or portfolio.get("risk_level"), "low")
    return {
        "total_exposure": portfolio.get("total_exposure"),
        "expected_return": portfolio.get("expected_return"),
        "risk_level": risk_level,
        "risk_label": f"{risk_level} risk",
        "diversification_score": _number(risk_profile.get("diversification_score"), portfolio.get("diversification_score")),
        "average_correlation": _number(risk_profile.get("average_correlation"), portfolio.get("average_correlation")),
    }


def build_response(*, recommendations: list[dict[str, Any]], parlays: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    generated_parlays = [dict(parlay) for parlay in (parlays or []) if isinstance(parlay, dict)]
    if not generated_parlays:
        from syndicate.features.intelligence import _build_parlays as _legacy_build_parlays

        generated_parlays = _legacy_build_parlays(
            recommendations,
            limit=3,
            preferences={
                "parlay_type": "standard",
                "parlay_leg_min": 2,
                "parlay_leg_max": 3,
                "max_correlation_threshold": MAX_CORRELATION_THRESHOLD,
            },
        )

    visible_recommendations = [dict(candidate) for candidate in recommendations if _response_state(candidate) not in {"final", "stale"}]

    def _frontend_parlay(parlay: dict[str, Any]) -> dict[str, Any]:
        correlation_profile = parlay.get("correlation_profile") if isinstance(parlay.get("correlation_profile"), dict) else {}
        return {
            "legs": [dict(leg) for leg in (parlay.get("legs") or []) if isinstance(leg, dict)],
            "combined_probability": parlay.get("combined_probability"),
            "combined_edge": parlay.get("combined_edge"),
            "expected_value": parlay.get("combined_expected_value"),
            "correlation_score": correlation_profile.get("max_correlation") if correlation_profile else None,
        }

    def _frontend_recommendation(candidate: dict[str, Any]) -> dict[str, Any]:
        recommendation = dict(candidate)
        writeup = _safe_text(recommendation.get("writeup"), "")
        if not _safe_text(recommendation.get("rationale"), ""):
            rationale = recommendation.get("reasoning_text") or recommendation.get("summary") or writeup
            if rationale:
                recommendation["rationale"] = rationale
        if not recommendation.get("advanced_inputs") and recommendation.get("advanced_context"):
            recommendation["advanced_inputs"] = recommendation.get("advanced_context")
        if recommendation.get("advanced_ready") is None and isinstance(recommendation.get("advanced_gate"), dict):
            recommendation["advanced_ready"] = bool(recommendation.get("advanced_gate", {}).get("ready"))
        if recommendation.get("advanced_inputs") or recommendation.get("advanced_context") or recommendation.get("advanced_ready"):
            rationale_text = _safe_text(recommendation.get("rationale"), "")
            if rationale_text and "advanced drivers in play" not in rationale_text.lower():
                recommendation["rationale"] = f"Advanced drivers in play. {rationale_text}"
        if writeup:
            rationale_text = _safe_text(recommendation.get("rationale"), "")
            if writeup not in rationale_text:
                recommendation["rationale"] = f"{rationale_text} {writeup}".strip()
        if "explanation" not in recommendation:
            recommendation["explanation"] = _frontend_explanation(candidate)
        if not recommendation.get("display_name"):
            recommendation["display_name"] = _frontend_display_name(candidate)
        return recommendation

    ordered_recommendations = sorted(
        visible_recommendations,
        key=lambda item: (
            _numeric_hint(item.get("adjusted_score") or item.get("score") or item.get("source_summary_score") or item.get("edge")) or 0.0,
            _numeric_hint(item.get("expected_value") or item.get("ev_current") or item.get("ev")) or 0.0,
            _numeric_hint(item.get("confidence")) or 0.0,
        ),
        reverse=True,
    )
    pick_payloads = [Pick.model_validate(_frontend_pick(candidate)).model_dump() for candidate in ordered_recommendations]
    recommendation_payloads = [_frontend_recommendation(candidate) for candidate in ordered_recommendations]
    movement_deltas = [value for value in (_safe_float(item.get("edge_delta")) for item in pick_payloads) if value is not None]
    movement_edge_delta = round(sum(movement_deltas) / len(movement_deltas), 4) if movement_deltas else None
    if movement_edge_delta is None:
        movement_trend = "flat"
    elif movement_edge_delta > 0.01:
        movement_trend = "up"
    elif movement_edge_delta < -0.01:
        movement_trend = "down"
    else:
        movement_trend = "flat"

    response = {
        "recommendations": recommendation_payloads,
        "picks": pick_payloads,
        "top_live_opportunities": get_top_live_opportunities(ordered_recommendations, limit=5),
        "portfolio": Portfolio.model_validate(_frontend_portfolio(ordered_recommendations)).model_dump(),
        "parlays": [Parlay.model_validate(_frontend_parlay(parlay)).model_dump() for parlay in generated_parlays],
        "movement": {
            "edge_delta": movement_edge_delta,
            "trend": movement_trend,
        },
    }

    validate_response_contract(response)
    return response


def validate_response_contract(response: dict[str, Any]) -> dict[str, Any]:
    IntelligenceResponse.model_validate(response)
    return response