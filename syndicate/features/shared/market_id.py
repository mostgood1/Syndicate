from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return _TOKEN_RE.sub("_", text).strip("_")


def _normalize_line(value: Any) -> str:
    if value in (None, "", "-"):
        return ""
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if not text:
            return ""
        try:
            number = float(text)
        except Exception:
            return _normalize_token(text)
    if number.is_integer():
        return str(int(number))
    return (f"{number:.10f}").rstrip("0").rstrip(".")


def _extract_date_and_matchup(event_id: Any) -> tuple[str, str]:
    text = str(event_id or "").strip()
    if not text:
        return "", ""
    parts = [part.strip() for part in text.split(":") if part.strip()]
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", first):
            return first, ":".join(parts[1:])
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last):
            return last, ":".join(parts[:-1])
    return "", text


def build_market_id(sport: Any, event_id: Any, market_type: Any, entity: Any | None = None, line: Any | None = None) -> str:
    sport_token = _normalize_token(sport) or "sport"
    date_token, matchup_token = _extract_date_and_matchup(event_id)
    event_token = _normalize_token(matchup_token or event_id) or "event"
    market_token = _normalize_token(market_type) or "market"
    entity_token = _normalize_token(entity)
    line_token = _normalize_line(line)

    parts = [sport_token.upper()]
    if date_token:
        parts.append(date_token)
    parts.append(event_token)
    parts.append(market_token.upper())
    if entity_token:
        parts.append(entity_token)
    if line_token:
        parts.append(line_token)
    return ":".join(parts)


def attach_market_id(
    row: dict[str, Any],
    *,
    sport: Any,
    event_id: Any | None = None,
    market_type: Any | None = None,
    entity: Any | None = None,
    line: Any | None = None,
) -> dict[str, Any]:
    payload = dict(row)
    inferred_event_id = event_id if event_id is not None else payload.get("event_id") or payload.get("matchup") or payload.get("game_id")
    inferred_market_type = market_type if market_type is not None else payload.get("market_type") or payload.get("market") or payload.get("selection") or payload.get("period")
    is_prop_candidate = str(payload.get("candidate_type") or "").strip().lower() == "prop"
    if entity is not None:
        inferred_entity = entity
    else:
        inferred_entity = payload.get("entity") or payload.get("player_name") or payload.get("player")
        # Props identify their subject by player, never by team -- falling back to
        # team here previously mislabeled entity-less prop rows as e.g. "ATL"
        # instead of leaving them blank, which also produced spurious duplicate
        # candidates for the same player prop (2026-07-23).
        if not inferred_entity and not is_prop_candidate:
            inferred_entity = payload.get("team") or payload.get("selection")
    inferred_line = line if line is not None else payload.get("line") or payload.get("point") or payload.get("spread") or payload.get("total")
    payload.setdefault("event_id", inferred_event_id)
    payload.setdefault("market_type", inferred_market_type)
    payload.setdefault("entity", inferred_entity)
    payload.setdefault("line", inferred_line)
    payload["market_id"] = build_market_id(sport, inferred_event_id, inferred_market_type, inferred_entity, inferred_line)
    return payload