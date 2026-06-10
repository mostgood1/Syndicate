from __future__ import annotations

from typing import Any

from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _safe_text


def get_top_live_opportunities(
    recommendations: list[dict[str, Any]],
    *,
    limit: int = 5,
    improving_only: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        ev_current = _numeric_hint(
            recommendation.get("ev_current")
            or recommendation.get("expected_value")
            or recommendation.get("expectedValue")
            or recommendation.get("ev")
        )
        if ev_current is None or ev_current <= 0:
            continue
        ev_delta = _numeric_hint(
            recommendation.get("ev_delta")
            or recommendation.get("evDelta")
            or recommendation.get("expected_value_delta")
            or recommendation.get("expectedValueDelta")
            or recommendation.get("expected_value_change")
            or recommendation.get("expectedValueChange")
        )
        if improving_only and (ev_delta is None or ev_delta <= 0):
            continue
        line_movement_impact = _numeric_hint(
            recommendation.get("line_movement_impact")
            or recommendation.get("lineMovementImpact")
            or recommendation.get("line_move")
            or recommendation.get("lineMove")
        )
        candidates.append(
            {
                "selection": _safe_text(recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name"), "Play"),
                "sport": _safe_text(recommendation.get("sport"), "Sport"),
                "sport_slug": _safe_text(recommendation.get("sport_slug") or recommendation.get("sport"), "sport").lower(),
                "market": _safe_text(recommendation.get("market") or recommendation.get("market_key"), "Market"),
                "odds_open": recommendation.get("odds_open") or recommendation.get("odds"),
                "odds_current": recommendation.get("odds_current") or recommendation.get("odds"),
                "ev_open": _numeric_hint(recommendation.get("ev_open") or recommendation.get("expected_value_open")),
                "ev_current": ev_current,
                "ev_delta": ev_delta,
                "line_movement_impact": line_movement_impact,
                "confidence": _numeric_hint(recommendation.get("confidence")),
                "edge": _numeric_hint(recommendation.get("edge")),
                "adjusted_score": _numeric_hint(recommendation.get("adjusted_score") or recommendation.get("score")),
                "reasoning": recommendation.get("reasoning") or recommendation.get("reasoning_text") or recommendation.get("summary") or recommendation.get("rationale"),
                "movement_label": (
                    "Edge improving" if (ev_delta is not None and ev_delta > 0)
                    else "Edge softening" if (ev_delta is not None and ev_delta < 0)
                    else None
                ),
            }
        )

    candidates.sort(
        key=lambda item: (
            float(item.get("ev_current") or 0.0),
            float(item.get("ev_delta") or 0.0),
            float(item.get("adjusted_score") or 0.0),
            float(item.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    return candidates[: max(0, int(limit))]