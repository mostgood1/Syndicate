from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text.replace("%", ""))
    except Exception:
        return None


def _safe_probability(value: Any) -> float | None:
    probability = _safe_float(value)
    if probability is None:
        return None
    if 0.0 <= probability <= 1.0:
        return probability
    if 1.0 < probability <= 100.0:
        return probability / 100.0
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _candidate_confidence(row: Mapping[str, Any]) -> float | None:
    for key in ("confidence", "model_confidence", "confidence_score", "probability_confidence"):
        confidence = _safe_probability(row.get(key))
        if confidence is not None:
            return confidence
    return None


def _candidate_edge(row: Mapping[str, Any]) -> float | None:
    edge = _first_present(
        _safe_float(row.get("adjusted_edge")),
        _safe_float(row.get("edge")),
        _safe_float(row.get("ev")),
        _safe_float(row.get("expected_value")),
        _safe_float(row.get("price_edge_pct")),
    )
    if edge is None:
        model_probability = _candidate_model_probability(row)
        market_probability = _candidate_market_probability(row)
        if model_probability is not None and market_probability is not None:
            edge = round(model_probability - market_probability, 4)
    if edge is None:
        return None
    if abs(edge) > 1.0 and abs(edge) <= 100.0:
        return edge / 100.0
    return edge


def _candidate_market_probability(row: Mapping[str, Any]) -> float | None:
    return _first_present(
        _safe_probability(row.get("market_probability")),
        _safe_probability(row.get("implied_probability")),
        _safe_probability(row.get("implied_prob")),
    )


def _candidate_model_probability(row: Mapping[str, Any]) -> float | None:
    return _first_present(
        _safe_probability(row.get("model_probability")),
        _safe_probability(row.get("confidence")),
        _safe_probability(row.get("prediction_probability")),
    )


def _rank_score(edge: float | None, confidence: float | None, market_probability: float | None, model_probability: float | None) -> float:
    base_edge = abs(edge or 0.0)
    if base_edge <= 0.0 and market_probability is not None and model_probability is not None:
        base_edge = abs(model_probability - market_probability)
    base_confidence = confidence if confidence is not None else 0.5
    return round(base_edge * (0.4 + base_confidence), 6)


def normalize_odds_entry(*, row: Mapping[str, Any], sport: str, market_key: str, timestamp: str | None = None, source_path: str | None = None, market_id: str | None = None, event_id: str | None = None, market_type: str | None = None, entity: str | None = None, line: float | None = None, odds: float | None = None, selection: str | None = None) -> dict[str, Any]:
    current_timestamp = str(timestamp or _utc_now()).strip()
    edge = _candidate_edge(row)
    confidence = _candidate_confidence(row)
    model_probability = _candidate_model_probability(row)
    market_probability = _candidate_market_probability(row)
    rank_score = _rank_score(edge, confidence, market_probability, model_probability)

    return {
        "schema_version": SCHEMA_VERSION,
        "sport": str(sport or "").strip().lower(),
        "market_key": str(market_key or "").strip(),
        "market_id": str(market_id or row.get("market_id") or market_key or "").strip(),
        "event_id": str(event_id or row.get("event_id") or row.get("event_key") or row.get("game_id") or row.get("game_pk") or "").strip() or None,
        "market_type": str(market_type or row.get("market_type") or row.get("market") or row.get("selection") or "").strip() or None,
        "entity": str(entity or row.get("entity") or row.get("player_name") or row.get("player") or row.get("team") or row.get("name") or row.get("title") or row.get("label") or "").strip() or None,
        "selection": str(selection or row.get("selection") or "").strip() or None,
        "line": line if line is not None else _safe_float(row.get("line")),
        "odds": odds if odds is not None else _safe_float(row.get("odds")),
        "market_probability": market_probability,
        "model_probability": model_probability,
        "edge": edge,
        "confidence": confidence,
        "rank_score": rank_score,
        "timestamp": current_timestamp,
        "source_path": str(source_path or row.get("source_path") or "").strip() or None,
    }


def rank_normalized_odds_entries(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ranked = [dict(entry) for entry in entries if isinstance(entry, Mapping)]
    ranked.sort(
        key=lambda item: (
            float(item.get("rank_score") or 0.0),
            abs(float(item.get("edge") or 0.0)),
            float(item.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked
