from __future__ import annotations

from typing import Any


def _normalize_probability(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        probability = float(value)
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1]
        try:
            probability = float(text)
        except Exception:
            return None
    if probability > 1.0:
        probability /= 100.0
    if probability < 0.0:
        return None
    return max(0.0, min(1.0, probability))


def _historical_context(candidate: dict[str, Any]) -> dict[str, Any]:
    historical_profile = candidate.get("historical_profile") if isinstance(candidate.get("historical_profile"), dict) else {}
    market_profile = historical_profile.get("market") if isinstance(historical_profile.get("market"), dict) else {}
    sport_profile = historical_profile.get("sport") if isinstance(historical_profile.get("sport"), dict) else {}
    source_profile = market_profile if int(market_profile.get("sample_size") or 0) > 0 else sport_profile
    metrics = source_profile.get("metrics") if isinstance(source_profile.get("metrics"), dict) else {}
    roi_segment = metrics.get("roi")
    sample_size = source_profile.get("sample_size") or metrics.get("sample_size") or metrics.get("settled_count")
    try:
        roi_value = float(roi_segment) if roi_segment is not None else None
    except Exception:
        roi_value = None
    try:
        sample_value = int(sample_size) if sample_size is not None else None
    except Exception:
        sample_value = None
    return {
        "roi_segment": round(roi_value, 4) if roi_value is not None else None,
        "sample_size": sample_value if sample_value and sample_value > 0 else None,
    }


def _reasoning_items(candidate: dict[str, Any], *, why: str, historical_context: dict[str, Any]) -> list[str]:
    market_context = candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else {}
    items: list[str] = []
    if why:
        items.append(why)
    model_probability = _normalize_probability(candidate.get("model_probability") or market_context.get("model_probability") or candidate.get("confidence"))
    market_probability = _normalize_probability(candidate.get("market_probability") or market_context.get("implied_probability") or candidate.get("implied_probability"))
    edge_value = candidate.get("edge_pct")
    if edge_value is None:
        raw_edge = candidate.get("edge")
        if isinstance(raw_edge, (int, float)):
            edge_value = float(raw_edge) * 100.0
    if model_probability is not None and market_probability is not None:
        if isinstance(edge_value, (int, float)):
            items.append(f"Model {model_probability:.3f} vs market {market_probability:.3f} ({float(edge_value):+.2f} pts)")
        else:
            items.append(f"Model {model_probability:.3f} vs market {market_probability:.3f}")
    roi_segment = historical_context.get("roi_segment")
    sample_size = historical_context.get("sample_size")
    if roi_segment is not None and sample_size is not None:
        items.append(f"Historical ROI {float(roi_segment):+.3f} across {int(sample_size)} settled bets")
    elif sample_size is not None:
        items.append(f"Historical sample size {int(sample_size)} settled bets")
    return items[:3]


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
    if "historical_context" in candidate:
        historical_context = candidate.get("historical_context") if isinstance(candidate.get("historical_context"), dict) else {"roi_segment": None, "sample_size": None}
    else:
        historical_context = _historical_context(candidate)
    why = (
        safe_text(candidate.get("writeup"), "")
        or safe_text(candidate.get("detail"), "")
        or safe_text(candidate.get("summary"), "")
        or safe_text(market_fit.get("market_fit_note"), "")
        or advanced_signal_text(candidate, limit=3)
    )
    model_probability = _normalize_probability(candidate.get("model_probability") or market_context.get("model_probability") or candidate.get("confidence"))
    market_probability = _normalize_probability(candidate.get("market_probability") or market_context.get("implied_probability") or candidate.get("implied_probability"))
    edge_value = candidate.get("edge_pct")
    if edge_value is None:
        raw_edge = candidate.get("edge")
        if isinstance(raw_edge, (int, float)):
            edge_value = float(raw_edge) * 100.0
    expected_value = candidate.get("expected_value")
    if expected_value is not None:
        try:
            expected_value = float(expected_value)
        except Exception:
            expected_value = None
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
        "expected_value": expected_value,
        "edge_pct": round(float(edge_value), 2) if isinstance(edge_value, (int, float)) else None,
        "model_probability": model_probability,
        "market_probability": market_probability,
        "historical_context": historical_context,
        "reasoning": _reasoning_items(candidate, why=why, historical_context=historical_context),
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