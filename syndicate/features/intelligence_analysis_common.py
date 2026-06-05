from __future__ import annotations

from typing import Any


def signal_value(candidate: dict[str, Any], key: str) -> float | None:
    for signal in candidate.get("advanced_signals") or []:
        if isinstance(signal, dict) and str(signal.get("key") or "") == key:
            value = signal.get("value")
            if isinstance(value, (int, float)):
                return round(float(value), 3)
    return None


def first_signal_value(candidate: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = signal_value(candidate, key)
        if value is not None:
            return value
    return None


def candidate_analysis_row(candidate: dict[str, Any], index: int, *, safe_text, advanced_signal_text) -> dict[str, Any]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    market_fit = candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else {}
    why = (
        safe_text(market_fit.get("market_fit_note"), "")
        or advanced_signal_text(candidate, limit=3)
        or safe_text(candidate.get("writeup"), "")
        or safe_text(candidate.get("detail"), "")
        or safe_text(candidate.get("summary"), "")
    )
    return {
        "rank": index,
        "label": safe_text(candidate.get("name"), "Play"),
        "sport": safe_text(candidate.get("sport"), "Sport"),
        "matchup": safe_text(candidate.get("matchup"), "-"),
        "market": safe_text(candidate.get("market"), "Market"),
        "market_label": safe_text(market_fit.get("market_label"), "Market"),
        "market_shape": safe_text(market_fit.get("market_shape"), "general_market"),
        "pick": safe_text(candidate.get("pick"), "-"),
        "line": safe_text(candidate.get("line"), "-"),
        "projected": safe_text(candidate.get("projected"), "-"),
        "live_projection": safe_text(candidate.get("live_projection"), "-"),
        "actual": safe_text(candidate.get("actual"), "-"),
        "odds": safe_text(candidate.get("odds"), "-"),
        "confidence": safe_text(candidate.get("confidence"), "-"),
        "edge": safe_text(candidate.get("edge"), "-"),
        "score": round(float(candidate.get("score") or 0.0), 2),
        "market_fit_score": round(float(market_fit.get("market_fit_score") or 0.0), 2),
        "price_edge_pct": market_context.get("price_edge_pct"),
        "implied_probability": market_context.get("implied_probability"),
        "why": why or "Local board and model context support this angle.",
    }


def filtered_analysis_candidates(
    candidates: list[dict[str, Any]],
    *,
    sports: set[str],
    preferences: dict[str, Any],
    candidate_types: set[str] | None,
    safe_text,
    candidate_market_focuses,
) -> list[dict[str, Any]]:
    requested_markets = {str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()}
    filtered = [candidate for candidate in candidates if safe_text(candidate.get("sport_slug"), "").lower() in sports]
    if candidate_types:
        typed = [candidate for candidate in filtered if safe_text(candidate.get("candidate_type"), "").lower() in candidate_types]
        if typed:
            filtered = typed
    if requested_markets:
        filtered = [candidate for candidate in filtered if candidate_market_focuses(candidate) & requested_markets]
    return filtered[: min(int(preferences.get("limit") or 5), 10)]