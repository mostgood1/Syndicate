from __future__ import annotations

import re
from typing import Any

from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _safe_float
from syndicate.features.intelligence.signals.normalization import _safe_text as _base_safe_text


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


def _has_live_context(recommendation: dict[str, Any]) -> bool:
    return any(
        bool(recommendation.get(key))
        for key in (
            "is_live",
            "matchup",
            "player_name",
            "subject_key",
            "event_id",
            "game_pk",
        )
    )


def _display_name(recommendation: dict[str, Any]) -> str:
    reasoning = _safe_text(recommendation.get("reasoning") or recommendation.get("reasoning_text") or recommendation.get("summary") or recommendation.get("rationale"), "")
    if reasoning:
        match = re.search(r"\bfor\s+(.+?)\s+Props?\s+at\b", reasoning, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
        match = re.search(r"\bfor\s+(.+?)\s+at\b", reasoning, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return _safe_text(
        recommendation.get("player_name")
        or recommendation.get("name")
        or recommendation.get("subject_key")
        or recommendation.get("pick")
        or recommendation.get("selection")
        or recommendation.get("market"),
        "Play",
    )


def _settlement_summary(recommendation: dict[str, Any]) -> dict[str, Any]:
    status_text = _safe_text(
        recommendation.get("status_display")
        or recommendation.get("status_context")
        or recommendation.get("game_state")
        or "",
        "",
    ).lower()
    actual_value = _safe_text(
        recommendation.get("actual")
        or recommendation.get("actual_value")
        or recommendation.get("actual_so_far")
        or recommendation.get("current_actual")
        or recommendation.get("live_actual"),
        "-",
    )
    if actual_value in {"", "-"} and _safe_text(recommendation.get("sport_slug"), "").lower() == "mlb":
        game_pk = recommendation.get("game_pk")
        context_label = _safe_text(recommendation.get("context_label"), "")
        if game_pk is not None and context_label:
            try:
                from syndicate.blueprints.home import _mlb_actual_payload_for_candidate
                from syndicate.blueprints.home import _mlb_prop_actual_value

                actual_payload = _mlb_actual_payload_for_candidate(context_label, int(game_pk), {})
                if isinstance(actual_payload, dict):
                    live_actual = _mlb_prop_actual_value(recommendation, actual_payload)
                    if live_actual is not None:
                        actual_value = _safe_text(live_actual, "-")
            except Exception:
                pass
    line_value = _numeric_hint(recommendation.get("line"))
    actual_numeric = _numeric_hint(actual_value)
    is_final = bool(recommendation.get("is_final")) or any(token in status_text for token in ("final", "completed", "settled", "graded"))
    is_live = bool(recommendation.get("is_live"))

    if is_final:
        status = "settled"
    elif is_live:
        status = "live"
    elif actual_value not in {"", "-"}:
        status = "resolved"
    else:
        status = "pending"

    result = _safe_text(recommendation.get("settlement_result") or recommendation.get("result"), "")
    if not result and status == "settled" and actual_numeric is not None and line_value is not None:
        selection_text = _safe_text(recommendation.get("selection") or recommendation.get("pick"), "").lower()
        over_selected = selection_text.startswith("over") or " over " in selection_text
        under_selected = selection_text.startswith("under") or " under " in selection_text
        if actual_numeric == line_value:
            result = "push"
        elif over_selected:
            result = "won" if actual_numeric > line_value else "lost"
        elif under_selected:
            result = "won" if actual_numeric < line_value else "lost"

    status_label = {
        "live": "Live",
        "resolved": "Resolved",
        "settled": "Settled",
        "pending": "Pending",
    }.get(status, status.title() if status else "")

    return {
        "status": status,
        "status_label": status_label,
        "actual": actual_value,
        "line": _safe_text(recommendation.get("line"), "-"),
        "result": result,
    }


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
        if not _has_live_context(recommendation):
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
                "display_name": _display_name(recommendation),
                "sport": _safe_text(recommendation.get("sport"), "Sport"),
                "sport_slug": _safe_text(recommendation.get("sport_slug") or recommendation.get("sport"), "sport").lower(),
                "market": _safe_text(recommendation.get("market") or recommendation.get("market_key"), "Market"),
                "player_name": _safe_text(recommendation.get("player_name"), ""),
                "matchup": _safe_text(recommendation.get("matchup"), ""),
                "candidate_type": _safe_text(recommendation.get("candidate_type"), ""),
                "actual": _safe_text(recommendation.get("actual") or recommendation.get("actual_value") or recommendation.get("actual_so_far") or recommendation.get("current_actual") or recommendation.get("live_actual"), "-"),
                "settlement": _settlement_summary(recommendation),
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
            _safe_float(item.get("ev_current")) or 0.0,
            _safe_float(item.get("ev_delta")) or 0.0,
            _safe_float(item.get("adjusted_score")) or 0.0,
            _safe_float(item.get("confidence")) or 0.0,
        ),
        reverse=True,
    )
    return candidates[: max(0, int(limit))]