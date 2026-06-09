from __future__ import annotations

from typing import Any, Mapping


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _safe_text(value, "")
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except Exception:
        return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _american_to_decimal(odds: float | None) -> float | None:
    if odds is None or odds == 0.0:
        return None
    if odds > 0:
        return 1.0 + (odds / 100.0)
    return 1.0 + (100.0 / abs(odds))


def _odds_adjustment(odds: Any) -> float | None:
    american_odds = _safe_float(odds)
    if american_odds is None:
        return None
    decimal_odds = _american_to_decimal(american_odds)
    if decimal_odds is None:
        return None
    return max(0.01, decimal_odds - 1.0)


def _implied_probability_from_odds(odds: Any) -> float | None:
    american_odds = _safe_float(odds)
    if american_odds is None:
        return None
    if american_odds > 0:
        return 100.0 / (american_odds + 100.0)
    return abs(american_odds) / (abs(american_odds) + 100.0)


def _confidence_scale(candidate: Mapping[str, Any]) -> float:
    confidence = _safe_float(candidate.get("confidence"))
    if confidence is None:
        confidence = _safe_float(candidate.get("model_confidence"))
    if confidence is None:
        confidence = _safe_float(candidate.get("confidence_score"))
    if confidence is None:
        confidence = 50.0
    if confidence > 1.0:
        confidence /= 100.0
    return _clamp(confidence, 0.0, 1.0)


def _cap_fraction(confidence: float) -> float:
    # Scale between 2% and 5% per play.
    return 0.02 + (0.03 * confidence)


def compute_bet_size(candidate: Mapping[str, Any]) -> dict[str, Any]:
    base_candidate = dict(candidate) if isinstance(candidate, Mapping) else {}

    model_probability = _safe_float(base_candidate.get("model_probability"))
    if model_probability is not None and model_probability > 1.0:
        model_probability /= 100.0
    model_probability = _clamp(model_probability if model_probability is not None else 0.5, 0.0, 1.0)

    implied_probability = _safe_float(base_candidate.get("implied_probability"))
    if implied_probability is not None and implied_probability > 1.0:
        implied_probability /= 100.0
    if implied_probability is None:
        implied_probability = _implied_probability_from_odds(base_candidate.get("odds"))
    implied_probability = _clamp(implied_probability if implied_probability is not None else 0.5, 0.0, 1.0)

    odds_adjustment = _odds_adjustment(base_candidate.get("odds"))
    if odds_adjustment is None:
        odds_adjustment = max(0.01, 1.0 - implied_probability)

    edge = model_probability - implied_probability
    kelly_fraction = edge / odds_adjustment if odds_adjustment > 0.0 else 0.0
    kelly_fraction = max(0.0, kelly_fraction)

    confidence = _confidence_scale(base_candidate)
    cap_fraction = _cap_fraction(confidence)
    recommended_bet_size = min(kelly_fraction * confidence, cap_fraction)

    return {
        "model_probability": round(model_probability, 4),
        "implied_probability": round(implied_probability, 4),
        "odds": base_candidate.get("odds"),
        "odds_adjustment": round(odds_adjustment, 4),
        "edge": round(edge, 4),
        "kelly_fraction": round(kelly_fraction, 4),
        "confidence": round(confidence, 4),
        "cap_fraction": round(cap_fraction, 4),
        "recommended_bet_size": round(recommended_bet_size, 4),
    }


__all__ = ["compute_bet_size"]