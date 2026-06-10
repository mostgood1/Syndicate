from __future__ import annotations

from typing import Any

from syndicate.features.bankroll_manager import build_portfolio as _build_portfolio
from syndicate.features.intelligence.models import IntelligenceResponse
from syndicate.features.intelligence.models import Parlay
from syndicate.features.intelligence.models import Pick
from syndicate.features.intelligence.models import Portfolio
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _safe_text


MAX_CORRELATION_THRESHOLD = 0.65


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
    return {
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
            try:
                if value is None:
                    continue
                return float(value)
            except (TypeError, ValueError):
                continue
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
        if not _safe_text(recommendation.get("rationale"), ""):
            rationale = recommendation.get("reasoning_text") or recommendation.get("summary") or recommendation.get("writeup")
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
        return recommendation

    ordered_recommendations = sorted(
        [dict(candidate) for candidate in recommendations],
        key=lambda item: (
            _numeric_hint(item.get("adjusted_score") or item.get("score") or item.get("source_summary_score") or item.get("edge")) or 0.0,
            _numeric_hint(item.get("expected_value") or item.get("ev_current") or item.get("ev")) or 0.0,
            _numeric_hint(item.get("confidence")) or 0.0,
        ),
        reverse=True,
    )
    pick_payloads = [Pick.model_validate(_frontend_pick(candidate)).model_dump() for candidate in ordered_recommendations]
    recommendation_payloads = [_frontend_recommendation(candidate) for candidate in ordered_recommendations]
    movement_deltas = [float(item.get("edge_delta")) for item in pick_payloads if item.get("edge_delta") is not None]
    movement_edge_delta = round(sum(movement_deltas) / float(len(movement_deltas)), 4) if movement_deltas else None
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