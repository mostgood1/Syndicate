from __future__ import annotations

from typing import Any, Mapping


def _normalized_movement_history(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    normalized = candidate.get("normalized") if isinstance(candidate.get("normalized"), Mapping) else {}
    history_sources = [
        candidate.get("odds_history") if isinstance(candidate.get("odds_history"), Mapping) else {},
        candidate.get("movement") if isinstance(candidate.get("movement"), Mapping) else {},
        candidate,
        normalized,
    ]
    for source in history_sources:
        if not isinstance(source, Mapping):
            continue
        history = source.get("history") if isinstance(source.get("history"), list) else None
        if isinstance(history, list) and history:
            normalized_history: list[dict[str, Any]] = []
            for item in history:
                if not isinstance(item, Mapping):
                    continue
                entry = _copy_mapping(item)
                line_value = _coerce_float(entry.get("line"))
                if line_value is None:
                    line_value = _coerce_float(entry.get("current_line"))
                if line_value is None:
                    continue
                normalized_history.append(
                    {
                        "timestamp": entry.get("timestamp") or entry.get("captured_at") or entry.get("updated_at") or entry.get("at") or entry.get("time"),
                        "line": line_value,
                        "odds": _coerce_float(entry.get("odds")),
                        "movement": entry.get("movement") or entry.get("trend"),
                        "source": entry.get("source") or entry.get("source_path") or entry.get("book") or entry.get("market"),
                    }
                )
            if normalized_history:
                return normalized_history
    return []


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _first_float(candidate: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _coerce_float(candidate.get(key))
        if value is not None:
            return value
    return None


def _movement_history(candidate: Mapping[str, Any], opening_line: float | None, current_line: float | None) -> list[dict[str, Any]]:
    history = _normalized_movement_history(candidate)
    if history:
        return history

    raw_history = candidate.get("movement_history") or candidate.get("line_history") or candidate.get("line_movement")
    history = []
    if isinstance(raw_history, list):
        for item in raw_history:
            if not isinstance(item, Mapping):
                continue
            entry = _copy_mapping(item)
            line_value = _coerce_float(entry.get("line"))
            if line_value is None:
                line_value = _coerce_float(entry.get("value"))
            if line_value is None:
                continue
            history.append(
                {
                    "timestamp": entry.get("timestamp") or entry.get("at") or entry.get("time"),
                    "line": line_value,
                    "source": entry.get("source") or entry.get("book") or entry.get("market"),
                }
            )

    if not history and opening_line is not None and current_line is not None:
        history.append({"timestamp": None, "line": opening_line, "source": "opening"})
        if current_line != opening_line:
            history.append({"timestamp": None, "line": current_line, "source": "current"})

    return history


def build_market_data(candidate: Mapping[str, Any]) -> dict[str, Any]:
    candidate_payload = _copy_mapping(candidate)
    opening_line = _first_float(candidate_payload, "opening_line", "open_line", "line_open", "openingLine", "opening")
    current_line = _first_float(candidate_payload, "current_line", "line", "currentLine", "live_line")
    history = _movement_history(candidate_payload, opening_line, current_line)
    return {
        "opening_line": opening_line,
        "current_line": current_line,
        "movement_history": history,
    }


def attach_market_data(candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = _copy_mapping(candidate)
    payload["market_data"] = build_market_data(payload)
    return payload


__all__ = [
    "build_market_data",
    "attach_market_data",
]