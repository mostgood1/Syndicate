from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.refresh_state_store import data_root


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _coerce_probability(value: Any) -> float | None:
    probability = _coerce_float(value)
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


def odds_lifecycle_root() -> Path:
    override = str(os.environ.get("SYNDICATE_ODDS_EVENTS_ROOT") or os.environ.get("SYNDICATE_ODDS_EVENT_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    mounted_root = Path("/mnt/data")
    if mounted_root.exists():
        return mounted_root / "odds_events"
    return data_root() / "odds_events"


def odds_lifecycle_path(date_str: str) -> Path:
    date_token = str(date_str or "").strip()
    if not date_token:
        date_token = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return odds_lifecycle_root() / f"{date_token}.jsonl"


def append_odds_lifecycle_events(date_str: str, events: Sequence[Mapping[str, Any]]) -> Path | None:
    records = [json.dumps(dict(event), ensure_ascii=True, separators=(",", ":")) for event in events if isinstance(event, Mapping)]
    if not records:
        return None
    path = odds_lifecycle_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record)
            handle.write("\n")
    return path


def load_odds_lifecycle_events(date_str: str) -> list[dict[str, Any]]:
    path = odds_lifecycle_path(date_str)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def summarize_odds_lifecycle_events(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {"total_events": 0, "open_events": 0, "update_events": 0, "live_events": 0, "close_events": 0, "final_events": 0}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        summary["total_events"] += 1
        event_type = str(event.get("event_type") or "").strip().lower()
        if event_type == "open":
            summary["open_events"] += 1
        elif event_type == "update":
            summary["update_events"] += 1
        elif event_type == "live":
            summary["live_events"] += 1
        elif event_type == "close":
            summary["close_events"] += 1
        elif event_type == "final":
            summary["final_events"] += 1
    return summary


def _candidate_market_id(candidate: Mapping[str, Any], *, sport: str | None = None) -> str | None:
    event_id = _first_present(candidate.get("event_id"), candidate.get("game_id"), candidate.get("game_pk"), candidate.get("gamePk"), candidate.get("matchup"), candidate.get("subject_key"), candidate.get("name"))
    market_type = _first_present(candidate.get("market_type"), candidate.get("market"), candidate.get("market_label"), candidate.get("market_key"), candidate.get("selection"), candidate.get("period"))
    entity = _first_present(candidate.get("entity"), candidate.get("player_name"), candidate.get("player"), candidate.get("team"), candidate.get("selection"), candidate.get("name"))
    line = _first_present(candidate.get("line"), candidate.get("point"), candidate.get("spread"), candidate.get("total"), candidate.get("projected"))
    attached = attach_market_id(dict(candidate), sport=sport or candidate.get("sport") or candidate.get("sport_slug") or "sport", event_id=event_id, market_type=market_type, entity=entity, line=line)
    return str(attached.get("market_id") or "").strip() or None


def _event_timestamp(event: Mapping[str, Any]) -> tuple[int, str]:
    text = str(event.get("timestamp") or event.get("captured_at") or event.get("last_updated") or "").strip()
    if not text:
        return (0, "")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat()
    except Exception:
        parsed = text
    return (1, parsed)


def _event_line(event: Mapping[str, Any]) -> float | None:
    return _coerce_float(event.get("line") or event.get("current_line") or event.get("latest_line") or event.get("value"))


def _event_price(event: Mapping[str, Any]) -> float | None:
    return _coerce_float(event.get("price") or event.get("odds") or event.get("last_odds") or event.get("current_odds"))


def _history_rows(candidate: Mapping[str, Any] | None, market_state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if isinstance(market_state, Mapping):
        history = market_state.get("history")
        if isinstance(history, list) and history:
            return [dict(item) for item in history if isinstance(item, Mapping)]
    if isinstance(candidate, Mapping):
        market_history = candidate.get("market_history")
        if isinstance(market_history, list) and market_history:
            return [dict(item) for item in market_history if isinstance(item, Mapping)]
        odds_history = candidate.get("odds_history")
        if isinstance(odds_history, Mapping):
            history = odds_history.get("history")
            if isinstance(history, list) and history:
                return [dict(item) for item in history if isinstance(item, Mapping)]
    return []


def _history_change_count(rows: Sequence[Mapping[str, Any]]) -> int:
    changes = 0
    previous_line = None
    previous_price = None
    for row in rows:
        current_line = _event_line(row)
        current_price = _event_price(row)
        if previous_line is not None and current_line is not None and current_line != previous_line:
            changes += 1
        elif previous_price is not None and current_price is not None and current_price != previous_price:
            changes += 1
        previous_line = current_line if current_line is not None else previous_line
        previous_price = current_price if current_price is not None else previous_price
    return changes


def _selection_direction(candidate: Mapping[str, Any]) -> float | None:
    pick = str(candidate.get("pick") or candidate.get("selection") or candidate.get("name") or "").strip().lower()
    if "under" in pick:
        return -1.0
    if "over" in pick or "yes" in pick:
        return 1.0
    return None


def _implied_probability_from_american_odds(value: Any) -> float | None:
    odds = _coerce_float(value)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    absolute = abs(odds)
    return absolute / (absolute + 100.0)


def build_market_history_view(candidate: Mapping[str, Any] | None = None, *, sport: str | None = None, market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    candidate_row = dict(candidate) if isinstance(candidate, Mapping) else {}
    resolved_sport = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    market_id = _candidate_market_id(candidate_row, sport=resolved_sport)
    if market_state is None and resolved_sport:
        payload = load_odds_history_payload_for_sport(resolved_sport)
        if isinstance(payload, Mapping):
            markets = payload.get("markets")
            if isinstance(markets, Mapping) and market_id:
                market_state = markets.get(market_id) if isinstance(markets.get(market_id), Mapping) else None
            if market_state is None and market_id and isinstance(markets, Mapping):
                for value in markets.values():
                    if isinstance(value, Mapping) and str(value.get("market_id") or "").strip() == market_id:
                        market_state = value
                        break

    history_rows = _history_rows(candidate_row, market_state)
    if not history_rows:
        opening_line = _coerce_float(candidate_row.get("line"))
        opening_price = _coerce_float(candidate_row.get("odds"))
        return {
            "market_id": market_id,
            "event_id": candidate_row.get("event_id") or candidate_row.get("game_id") or candidate_row.get("matchup"),
            "opening_line": opening_line,
            "latest_line": opening_line,
            "closing_line": opening_line,
            "opening_price": opening_price,
            "latest_price": opening_price,
            "closing_price": opening_price,
            "movement_delta": None,
            "movement_direction": "flat",
            "movement_velocity": None,
            "volatility": 0,
            "clv": None,
            "closing_edge": None,
            "is_steam_move": False,
            "history_points": 0,
            "movement_events": 0,
            "live_events": 0,
            "close_events": 0,
            "final_events": 0,
            "is_live": bool(candidate_row.get("is_live")),
            "selection_direction": _selection_direction(candidate_row),
            "edge_direction": 1.0 if (_coerce_probability(candidate_row.get("fair_probability")) or 0.0) >= (_coerce_probability(candidate_row.get("market_probability")) or 0.0) else -1.0,
            "movement_signal": None,
            "clv_signal": None,
            "raw_history": [],
        }

    ordered_history = sorted(history_rows, key=_event_timestamp)
    opening_entry = ordered_history[0]
    latest_entry = ordered_history[-1]
    closing_entry = next((entry for entry in reversed(ordered_history) if str(entry.get("event_type") or "").strip().lower() in {"close", "final"}), latest_entry)

    opening_line = _event_line(opening_entry)
    latest_line = _event_line(latest_entry)
    closing_line = _event_line(closing_entry)
    opening_price = _event_price(opening_entry)
    latest_price = _event_price(latest_entry)
    closing_price = _event_price(closing_entry)

    movement_delta = None
    if opening_line is not None and latest_line is not None:
        movement_delta = round(latest_line - opening_line, 4)

    movement_direction = "flat"
    if movement_delta is not None:
        if movement_delta > 0:
            movement_direction = "positive"
        elif movement_delta < 0:
            movement_direction = "negative"

    movement_velocity = None
    if movement_delta is not None:
        try:
            start = datetime.fromisoformat(_event_timestamp(opening_entry)[1].replace("Z", "+00:00")).astimezone(timezone.utc)
            end = datetime.fromisoformat(_event_timestamp(latest_entry)[1].replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed_hours = max((end - start).total_seconds() / 3600.0, 0.0)
            if elapsed_hours > 0:
                movement_velocity = round(movement_delta / elapsed_hours, 4)
        except Exception:
            movement_velocity = None

    volatility = _history_change_count(ordered_history)
    candidate_line = _coerce_float(candidate_row.get("line") or candidate_row.get("current_line") or candidate_row.get("projected"))
    candidate_price = _coerce_float(candidate_row.get("odds") or candidate_row.get("current_odds") or candidate_row.get("market_probability"))
    candidate_probability = _coerce_probability(candidate_row.get("market_probability")) or _coerce_probability(candidate_row.get("implied_probability")) or _implied_probability_from_american_odds(candidate_price)
    closing_probability = _implied_probability_from_american_odds(closing_price)

    clv = None
    if candidate_line is not None and closing_line is not None:
        clv = round(candidate_line - closing_line, 4)

    closing_edge = None
    if candidate_probability is not None and closing_probability is not None:
        closing_edge = round(candidate_probability - closing_probability, 4)

    selection_direction = _selection_direction(candidate_row)
    edge_direction = 1.0 if (_coerce_probability(candidate_row.get("fair_probability")) or 0.0) >= (_coerce_probability(candidate_row.get("market_probability")) or 0.0) else -1.0
    movement_signal = None
    if movement_delta is not None:
        direction_factor = selection_direction if selection_direction in {1.0, -1.0} else 0.0
        scale = max(1.0, abs(opening_line or latest_line or candidate_line or 1.0))
        if direction_factor != 0.0:
            movement_signal = round((-direction_factor * movement_delta * edge_direction) / scale, 4)
        else:
            movement_signal = round((movement_delta / scale) * edge_direction, 4)

    clv_signal = None
    if clv is not None:
        scale = max(0.5, abs(opening_line or latest_line or candidate_line or 1.0))
        if selection_direction in {1.0, -1.0}:
            clv_signal = round((-selection_direction * clv) / scale, 4)
        else:
            clv_signal = round(-clv / scale, 4)
    elif closing_edge is not None:
        clv_signal = round(-closing_edge * 5.0, 4)

    live_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "live" or bool(entry.get("is_live")))
    close_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "close")
    final_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "final")
    steam_window = abs(movement_delta or 0.0) >= 0.5 and volatility >= 1 and (movement_velocity is None or abs(movement_velocity) >= 0.05)

    return {
        "market_id": market_id,
        "event_id": candidate_row.get("event_id") or candidate_row.get("game_id") or candidate_row.get("matchup"),
        "opening_line": opening_line,
        "latest_line": latest_line,
        "closing_line": closing_line,
        "opening_price": opening_price,
        "latest_price": latest_price,
        "closing_price": closing_price,
        "movement_delta": movement_delta,
        "movement_direction": movement_direction,
        "movement_velocity": movement_velocity,
        "volatility": volatility,
        "clv": clv,
        "closing_edge": closing_edge,
        "is_steam_move": steam_window,
        "history_points": len(ordered_history),
        "movement_events": volatility,
        "live_events": live_events,
        "close_events": close_events,
        "final_events": final_events,
        "is_live": bool(candidate_row.get("is_live")) or live_events > 0,
        "selection_direction": selection_direction,
        "edge_direction": edge_direction,
        "movement_signal": movement_signal,
        "clv_signal": clv_signal,
        "raw_history": ordered_history[-10:],
    }


def build_market_features(candidate: Mapping[str, Any], *, sport: str | None = None, market_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    features = build_market_history_view(candidate, sport=sport, market_state=market_state)
    candidate_row = dict(candidate)
    features["candidate_line"] = _coerce_float(candidate_row.get("line") or candidate_row.get("current_line") or candidate_row.get("projected"))
    features["candidate_price"] = _coerce_float(candidate_row.get("odds") or candidate_row.get("current_odds") or candidate_row.get("market_probability"))
    features["candidate_probability"] = _coerce_probability(candidate_row.get("market_probability")) or _coerce_probability(candidate_row.get("implied_probability")) or _implied_probability_from_american_odds(features["candidate_price"])
    features["source_sport"] = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    return features