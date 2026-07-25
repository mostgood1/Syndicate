from __future__ import annotations

import json
import os
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_lookback_shard_keys
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.shared.refresh_state_store import data_root


_ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT = 1

# Per-day cap on how many jsonl rows _load_jsonl_rows keeps in memory. Without
# this, a day's odds-event log (appended to on every market movement, all day,
# every day the app has been live) gets read back in full -- and
# load_recent_odds_events multiplies that by a 7-day lookback, with no caching
# between calls. Confirmed in production: a single call surfaced a retained
# list of 1,046,551 dicts and spiked the live-odds-worker's own RSS from
# ~100MB to ~1.86GB in one tick. Rows are append-ordered, so keeping the most
# recent N preserves exactly the "recent market history" this data is for.
_MAX_JSONL_ROWS_PER_FILE = 2000


def _odds_history_shard_lookback() -> int:
    raw = str(os.environ.get("SYNDICATE_ODDS_HISTORY_SHARD_LOOKBACK") or "").strip()
    if not raw:
        return _ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT
    try:
        return max(0, int(raw))
    except Exception:
        return _ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT


def _resolve_shard_key_for_candidate(candidate_row: Mapping[str, Any], *, sport: str | None, shard_key: str | None, end_date: str | None) -> str | None:
    if shard_key:
        return shard_key
    if not sport:
        return None
    candidate_date = str(candidate_row.get("date") or candidate_row.get("game_date") or candidate_row.get("event_date") or "").strip()
    if candidate_date:
        return resolve_current_shard_key(sport, candidate_date[:10])
    if end_date:
        return resolve_current_shard_key(sport, str(end_date)[:10])
    return resolve_current_shard_key(sport, date.today().isoformat())


def _market_state_from_payload(payload: Mapping[str, Any] | None, *, market_id: str | None) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping) or not market_id:
        return None
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        return None
    state = markets.get(market_id) if isinstance(markets.get(market_id), Mapping) else None
    if state is not None:
        return state
    for value in markets.values():
        if isinstance(value, Mapping) and str(value.get("market_id") or "").strip() == market_id:
            return value
    return None


def _resolve_market_state_across_shards(*, sport: str, market_id: str | None, shard_key: str, shard_lookback: int, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any] | None:
    shard_keys = [shard_key] + odds_history_lookback_shard_keys(sport, shard_key, shard_lookback)
    merged_history: list[dict[str, Any]] = []
    found = False
    for key in shard_keys:
        state = _market_state_from_payload(load_odds_history_payload_for_sport(sport, key, cache=payload_cache), market_id=market_id)
        if state is None:
            continue
        history = state.get("history")
        if isinstance(history, list):
            merged_history.extend(item for item in history if isinstance(item, Mapping))
            found = True
    if not found:
        return None
    return {"history": merged_history}


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


def _parse_date_token(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for token in (text, text.replace("Z", "")):
        try:
            return datetime.fromisoformat(token).date()
        except Exception:
            pass
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _trace_file_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except Exception:
        return None


def _trace_log(stage: str, **payload: Any) -> None:
    record = {"stage": stage, **payload}
    print(f"[odds_lifecycle] TRACE {json.dumps(record, default=str, sort_keys=True)}", flush=True)


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


# load_recent_odds_events queries at most a handful of distinct date files per
# call (days_back defaults to 7); this process has been up for days at a time
# in production, so without a bound this cache would itself become another
# unbounded, ever-growing structure -- exactly the failure mode being fixed
# here. Once full, drop the whole cache rather than tracking real LRU: a miss
# just means one full re-read of a file already capped to
# _MAX_JSONL_ROWS_PER_FILE, not the unbounded read this cache exists to avoid.
_JSONL_ROWS_CACHE_MAX_ENTRIES = 32
_JSONL_ROWS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    cache_key = str(path)
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = None
    if mtime is not None:
        cached = _JSONL_ROWS_CACHE.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    if len(rows) > _MAX_JSONL_ROWS_PER_FILE:
        rows = rows[-_MAX_JSONL_ROWS_PER_FILE:]
    if mtime is not None:
        # This file only changes when the odds-refresh subprocess appends new
        # lifecycle events -- read-only callers (live lens snapshot building,
        # one call per game/candidate) hit this dozens to hundreds of times
        # per pass with an unchanged file. Without this cache, capping the
        # per-call row count above still leaves every one of those calls
        # re-reading and re-parsing the whole file from disk; CPython's
        # allocator doesn't reliably return that churn to the OS between
        # calls, so RSS ratchets upward across a single pass even though each
        # individual call's retained memory is bounded.
        if len(_JSONL_ROWS_CACHE) >= _JSONL_ROWS_CACHE_MAX_ENTRIES:
            _JSONL_ROWS_CACHE.clear()
        _JSONL_ROWS_CACHE[cache_key] = (mtime, rows)
    return rows


def load_recent_odds_events(*, days_back: int = 7, end_date: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    lookback = max(int(days_back or 0), 1)
    end_token = _parse_date_token(end_date) or date.today()
    odds_root = root or odds_lifecycle_root()
    rows: list[dict[str, Any]] = []
    for offset in range(lookback):
        current_date = end_token - timedelta(days=offset)
        rows.extend(_load_jsonl_rows(odds_root / f"{current_date.isoformat()}.jsonl"))
    return rows


def _event_aliases(event: Mapping[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in (
        event.get("market_id"),
        event.get("event_id"),
        event.get("game_id"),
        event.get("gamePk"),
        event.get("game_pk"),
        event.get("player_id"),
        event.get("athlete_id"),
        event.get("subject_key"),
        event.get("market_key"),
    ):
        text = str(key or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def build_recent_market_history_index(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        payload = dict(event)
        market_id = str(payload.get("market_id") or "").strip() or _candidate_market_id(payload, sport=str(payload.get("sport") or payload.get("sport_slug") or "").strip().lower() or None)
        aliases = _event_aliases(payload)
        if market_id and market_id not in aliases:
            aliases.insert(0, market_id)
        for alias in aliases:
            index.setdefault(alias, []).append(payload)
    for rows in index.values():
        rows.sort(key=_event_timestamp)
    return index


def _recent_history_rows(candidate: Mapping[str, Any], *, sport: str | None = None, lookback_days: int = 7, end_date: str | None = None) -> list[dict[str, Any]]:
    recent_events = load_recent_odds_events(days_back=lookback_days, end_date=end_date)
    if not recent_events:
        return []
    index = build_recent_market_history_index(recent_events)
    candidate_row = dict(candidate)
    candidate_market_id = _candidate_market_id(candidate_row, sport=sport)
    candidate_aliases = [candidate_market_id, str(candidate_row.get("market_id") or "").strip(), str(candidate_row.get("event_id") or "").strip(), str(candidate_row.get("game_id") or "").strip(), str(candidate_row.get("gamePk") or candidate_row.get("game_pk") or "").strip(), str(candidate_row.get("player_id") or candidate_row.get("athlete_id") or "").strip()]
    for alias in candidate_aliases:
        if alias and alias in index:
            return [dict(row) for row in index[alias]]
    return []


def append_odds_lifecycle_events(date_str: str, events: Sequence[Mapping[str, Any]]) -> Path | None:
    records = [json.dumps(dict(event), ensure_ascii=True, separators=(",", ":")) for event in events if isinstance(event, Mapping)]
    if not records:
        return None
    path = odds_lifecycle_path(date_str)
    started = datetime.now(timezone.utc)
    _trace_log("before_append_odds_lifecycle_events", path=str(path), rows=len(records), size_bytes=_trace_file_size(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record)
            handle.write("\n")
    elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 3)
    _trace_log("after_append_odds_lifecycle_events", path=str(path), rows=len(records), size_bytes=_trace_file_size(path), elapsed_ms=elapsed_ms)
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


def build_market_history_view(candidate: Mapping[str, Any] | None = None, *, sport: str | None = None, market_state: Mapping[str, Any] | None = None, lookback_days: int = 7, end_date: str | None = None, shard_key: str | None = None, shard_lookback: int | None = None, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    candidate_row = dict(candidate) if isinstance(candidate, Mapping) else {}
    resolved_sport = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    market_id = _candidate_market_id(candidate_row, sport=resolved_sport)
    if market_state is None and resolved_sport:
        resolved_shard_key = _resolve_shard_key_for_candidate(candidate_row, sport=resolved_sport, shard_key=shard_key, end_date=end_date)
        if resolved_shard_key:
            market_state = _resolve_market_state_across_shards(
                sport=resolved_sport,
                market_id=market_id,
                shard_key=resolved_shard_key,
                shard_lookback=shard_lookback if shard_lookback is not None else _odds_history_shard_lookback(),
                payload_cache=payload_cache,
            )

    if market_state is None:
        recent_rows = _recent_history_rows(candidate_row, sport=resolved_sport, lookback_days=lookback_days, end_date=end_date)
        if recent_rows:
            market_state = {"history": recent_rows}

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
            "price_delta": None,
            "price_direction": "flat",
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

    # Line and price/odds are two independent dimensions a market can move
    # on -- a total's number (3.5 -> 4.5) and its juice (-110 -> -120) can
    # each shift on their own. Only the line side had a delta/direction
    # tracked here; price had opening/latest values recorded but no delta
    # ever computed from them, so callers had no way to report "odds moved
    # by X" separately from "the line moved by X". Mirrors movement_delta/
    # movement_direction's pattern exactly.
    price_delta = None
    if opening_price is not None and latest_price is not None:
        price_delta = round(latest_price - opening_price, 4)

    price_direction = "flat"
    if price_delta is not None:
        if price_delta > 0:
            price_direction = "positive"
        elif price_delta < 0:
            price_direction = "negative"

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
        "price_delta": price_delta,
        "price_direction": price_direction,
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


def build_market_features(candidate: Mapping[str, Any], *, sport: str | None = None, market_state: Mapping[str, Any] | None = None, lookback_days: int = 7, end_date: str | None = None, shard_key: str | None = None, shard_lookback: int | None = None, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    features = build_market_history_view(candidate, sport=sport, market_state=market_state, lookback_days=lookback_days, end_date=end_date, shard_key=shard_key, shard_lookback=shard_lookback, payload_cache=payload_cache)
    candidate_row = dict(candidate)
    features["candidate_line"] = _coerce_float(candidate_row.get("line") or candidate_row.get("current_line") or candidate_row.get("projected"))
    features["candidate_price"] = _coerce_float(candidate_row.get("odds") or candidate_row.get("current_odds") or candidate_row.get("market_probability"))
    features["candidate_probability"] = _coerce_probability(candidate_row.get("market_probability")) or _coerce_probability(candidate_row.get("implied_probability")) or _implied_probability_from_american_odds(features["candidate_price"])
    features["source_sport"] = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    features["lookback_days"] = max(int(lookback_days or 0), 1)
    features["has_recent_history"] = bool(features.get("history_points") or 0)
    return features


def market_feature_summary(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    market_rows = [dict(item) for item in features if isinstance(item, Mapping)]
    if not market_rows:
        return {
            "market_feature_count": 0,
            "movement_delta_mean": None,
            "movement_velocity_mean": None,
            "volatility_mean": None,
            "clv_mean": None,
            "closing_edge_mean": None,
            "edge_retention_mean": None,
            "closing_line_count": 0,
            "market_history_points": 0,
        }

    movement_deltas = [_coerce_float(row.get("movement_delta")) for row in market_rows if _coerce_float(row.get("movement_delta")) is not None]
    movement_velocity = [_coerce_float(row.get("movement_velocity")) for row in market_rows if _coerce_float(row.get("movement_velocity")) is not None]
    volatility = [_coerce_float(row.get("volatility")) for row in market_rows if _coerce_float(row.get("volatility")) is not None]
    clv_values = [_coerce_float(row.get("clv")) for row in market_rows if _coerce_float(row.get("clv")) is not None]
    closing_edges = [_coerce_float(row.get("closing_edge")) for row in market_rows if _coerce_float(row.get("closing_edge")) is not None]
    edge_retention_values: list[float] = []
    for row in market_rows:
        edge = _coerce_float(row.get("edge")) or _coerce_float(row.get("candidate_edge"))
        closing_edge = _coerce_float(row.get("closing_edge"))
        if edge is None or closing_edge is None or edge == 0:
            continue
        edge_retention_values.append(round(closing_edge / edge, 4))

    return {
        "market_feature_count": len(market_rows),
        "movement_delta_mean": round(sum(movement_deltas) / len(movement_deltas), 4) if movement_deltas else None,
        "movement_velocity_mean": round(sum(movement_velocity) / len(movement_velocity), 4) if movement_velocity else None,
        "volatility_mean": round(sum(volatility) / len(volatility), 4) if volatility else None,
        "clv_mean": round(sum(clv_values) / len(clv_values), 4) if clv_values else None,
        "closing_edge_mean": round(sum(closing_edges) / len(closing_edges), 4) if closing_edges else None,
        "edge_retention_mean": round(sum(edge_retention_values) / len(edge_retention_values), 4) if edge_retention_values else None,
        "closing_line_count": len([row for row in market_rows if row.get("closing_line") is not None]),
        "market_history_points": sum(int(row.get("history_points") or 0) for row in market_rows),
    }