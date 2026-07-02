from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from syndicate.features.shared.basketball_props_tracking import sync_basketball_props_tracking_for_source_root
from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import shared_odds_history_root
from syndicate.features.shared.odds_framework import normalize_odds_entry
from syndicate.features.shared.odds_lifecycle import append_odds_lifecycle_events
from syndicate.features.shared.recommendation_engine import build_recommendation_output


_ODDS_HISTORY_LIMIT = 50


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _odds_history_path(tracking_root: Path) -> Path:
    return tracking_root / "odds_history.json"


def _odds_history_artifact_path(source_root: Path, sport: str) -> Path:
    return source_root / "artifacts" / sport / "odds_history.json"


def _shared_odds_history_path(sport: str) -> Path:
    return shared_odds_history_root() / str(sport or "").strip().lower() / "odds_history.json"


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


def _is_final_status_row(row: Mapping[str, Any], normalized_entry: Mapping[str, Any] | None = None) -> bool:
    text_parts = [
        row.get("status"),
        row.get("state"),
        row.get("game_state"),
        row.get("period"),
        row.get("result"),
        row.get("outcome"),
        row.get("market_status"),
    ]
    if isinstance(normalized_entry, Mapping):
        text_parts.extend([normalized_entry.get("market_type"), normalized_entry.get("selection")])
    text = " ".join(str(value or "").strip().lower() for value in text_parts if str(value or "").strip())
    return any(marker in text for marker in ("final", "closed", "close", "finale", "completed", "finished"))


def _market_lifecycle_event(
    *,
    row: Mapping[str, Any],
    normalized_entry: Mapping[str, Any],
    event_type: str,
    sport: str,
    timestamp: str,
    market_key: str,
    current_line: float | None,
    current_odds: float | None,
    is_live: bool,
) -> dict[str, Any]:
    event = {
        "timestamp": timestamp,
        "game_id": normalized_entry.get("event_id") or row.get("event_id") or row.get("game_id") or row.get("game_pk"),
        "sport": sport,
        "market_id": normalized_entry.get("market_id") or market_key,
        "player_id": row.get("player_id") or row.get("athlete_id"),
        "market_type": normalized_entry.get("market_type") or row.get("market_type") or row.get("market") or row.get("selection"),
        "event_type": event_type,
        "line": current_line,
        "price": current_odds,
        "implied_prob": normalized_entry.get("market_probability") or normalized_entry.get("implied_probability"),
        "source": normalized_entry.get("source_path") or row.get("source_path") or row.get("book") or row.get("bookmaker"),
        "is_live": bool(is_live),
    }
    if event_type == "final":
        event["result"] = row.get("result") or row.get("outcome") or row.get("market_status") or "final"
        event["closing_line"] = current_line
        event["closing_price"] = current_odds
    return {key: value for key, value in event.items() if value is not None}


def _is_live_odds_row(row: Mapping[str, Any], normalized_entry: Mapping[str, Any] | None = None) -> bool:
    text_parts = [
        row.get("market_type"),
        row.get("market"),
        row.get("selection"),
        row.get("period"),
        row.get("status"),
        row.get("state"),
        row.get("game_state"),
        row.get("live"),
        row.get("is_live"),
    ]
    if isinstance(normalized_entry, Mapping):
        text_parts.extend([
            normalized_entry.get("market_type"),
            normalized_entry.get("selection"),
        ])
    text = " ".join(str(value or "").strip().lower() for value in text_parts if str(value or "").strip())
    return any(marker in text for marker in ("live", "in_play", "in play", "in-progress", "in progress"))


def _line_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _movement_direction(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "flat"
    return "up" if delta > 0 else "down"


def _percent_change(current_line: float | None, previous_line: float | None) -> float | None:
    if current_line is None or previous_line in (None, 0):
        return None
    try:
        return ((current_line - previous_line) / abs(previous_line)) * 100.0
    except Exception:
        return None


def _primary_line_value(row: Mapping[str, Any]) -> float | None:
    for key in (
        "line",
        "point",
        "spread",
        "total",
        "price",
        "odds",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_line",
        "away_line",
        "home_puck_line",
        "away_puck_line",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        current_value = _line_number(row.get(key))
        if current_value is not None:
            return current_value
    return None


def _primary_odds_value(row: Mapping[str, Any]) -> float | None:
    for key in (
        "odds",
        "price",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_spread_price",
        "away_spread_price",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        current_value = _line_number(row.get(key))
        if current_value is not None:
            return current_value
    return None


def _odds_history_market_states(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return {}
    markets = payload.get("markets")
    if isinstance(markets, dict) and markets:
        return {str(key): value for key, value in markets.items() if isinstance(value, dict)}
    states: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if key in {"sport", "date", "updated_at", "history_limit", "markets"}:
            continue
        if isinstance(value, dict) and isinstance(value.get("history"), list):
            states[str(key)] = value
    return states


def _canonical_market_type(row: Mapping[str, Any]) -> str | None:
    for key in ("market_type", "market", "selection", "period"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def _canonical_entity(row: Mapping[str, Any]) -> str | None:
    for key in (
        "entity",
        "player_name",
        "player",
        "team",
        "team_key",
        "subject_key",
        "selection",
        "matchup",
        "home_team",
        "away_team",
        "name",
        "title",
        "label",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def _canonical_event_id(row: Mapping[str, Any]) -> str | None:
    for key in ("event_id", "event_key", "game_id", "game_pk"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    matchup = str(row.get("matchup") or "").strip()
    if matchup:
        return matchup
    home_team = str(row.get("home_team") or "").strip()
    away_team = str(row.get("away_team") or "").strip()
    if home_team and away_team:
        return f"{away_team}@{home_team}"
    return None


def _canonical_odds_record(*, row: Mapping[str, Any], market_key: str, sport: str, timestamp: str, current_line: float | None) -> dict[str, Any]:
    event_id = _canonical_event_id(row)
    market_type = _canonical_market_type(row)
    entity = _canonical_entity(row)
    market_id = str(row.get("market_id") or "").strip() or market_key
    odds_value = _primary_odds_value(row)
    return {
        "market_id": market_id,
        "sport": sport,
        "event_id": event_id,
        "market_type": market_type,
        "entity": entity,
        "line": current_line,
        "odds": odds_value,
        "timestamp": timestamp,
    }


def _odds_history_line_snapshot(row: Mapping[str, Any]) -> dict[str, Any] | None:
    snapshot: dict[str, Any] = {}
    for key in (
        "line",
        "point",
        "spread",
        "total",
        "price",
        "odds",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_line",
        "away_line",
        "home_puck_line",
        "away_puck_line",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        value = row.get(key)
        if value in (None, "", "-"):
            continue
        snapshot[key] = _json_safe(value)
    return snapshot or None


def _odds_history_market_key(row: Mapping[str, Any]) -> str | None:
    market_id = str(row.get("market_id") or "").strip()
    if market_id:
        return market_id
    parts: list[str] = []
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "home_team",
        "away_team",
        "player_key",
        "player_name",
        "team_key",
        "team",
        "market",
        "selection",
        "book",
        "bookmaker",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    if not parts:
        fallback = str(row.get("name") or row.get("title") or row.get("label") or "").strip()
        if fallback:
            parts.append(f"name={fallback}")
    return "|".join(parts) if parts else None


def _market_rows_from_mapping(payload: Mapping[str, Any], *, context: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    merged_context = dict(context or {})
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "home_team",
        "away_team",
        "player_key",
        "player_name",
        "team_key",
        "team",
        "market",
        "selection",
        "book",
        "bookmaker",
        "date",
        "sport",
    ):
        value = payload.get(key)
        if value in (None, ""):
            continue
        merged_context.setdefault(key, value)

    rows: list[dict[str, Any]] = []
    if _odds_history_line_snapshot(payload):
        rows.append({**merged_context, **dict(payload)})

    for key in ("games", "rows", "items"):
        nested = payload.get(key)
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item, context=merged_context))

    for key in ("lines", "markets", "props", "player_props", "team_odds", "hitter_props", "pitcher_props"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            for nested_key, nested_value in nested.items():
                nested_context = dict(merged_context)
                if nested_key and not nested_context.get("market"):
                    nested_context["market"] = str(nested_key)
                if isinstance(nested_value, Mapping):
                    rows.extend(_market_rows_from_mapping(nested_value, context=nested_context))
                elif isinstance(nested_value, list):
                    for item in nested_value:
                        if isinstance(item, Mapping):
                            rows.extend(_market_rows_from_mapping(item, context=nested_context))
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item, context=merged_context))

    return rows


def _odds_history_rows_from_json(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, Mapping):
                rows.extend(_market_rows_from_mapping(item))
        return rows
    if isinstance(payload, Mapping):
        return _market_rows_from_mapping(payload)
    return []


def _odds_history_rows_from_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, Mapping):
            rows.extend(_market_rows_from_mapping(payload))
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item))
    return rows


def _odds_history_rows_from_csv(path: Path) -> list[dict[str, Any]]:
    try:
        frame = pd.read_csv(path)
    except Exception:
        return []
    if frame.empty:
        return []
    return [dict(row) for row in frame.to_dict(orient="records") if isinstance(row, Mapping)]


def _odds_history_snapshot_paths(*, sport: str, source_root: Path, date_str: str) -> list[Path]:
    slug = str(sport or "").strip().lower()
    date_slug = str(date_str or "").strip().replace("-", "_")
    candidates: list[Path] = []

    def add(*parts: str) -> None:
        candidate = source_root.joinpath(*parts)
        if candidate not in candidates:
            candidates.append(candidate)

    if slug == "mlb":
        for snapshot_dir in (
            source_root / "source_artifacts" / "data" / "daily" / "snapshots" / date_str,
            source_root / "data" / "daily" / "snapshots" / date_str,
        ):
            rel_parts = snapshot_dir.relative_to(source_root).parts
            add(*rel_parts, f"oddsapi_game_lines_{date_slug}.json")
            add(*rel_parts, f"oddsapi_hitter_props_{date_slug}.json")
            add(*rel_parts, f"oddsapi_pitcher_props_{date_slug}.json")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug in {"nba", "wnba"}:
        for prefix_root in (
            source_root / "data" / "processed",
            source_root / "source_artifacts" / "data" / "processed",
        ):
            rel_parts = prefix_root.relative_to(source_root).parts
            add(*rel_parts, "live_snapshots", f"live_lines_{date_str}.jsonl")
            add(*rel_parts, f"live_lens_signals_{date_str}.jsonl")
            add(*rel_parts, f"live_lens_projections_{date_str}.jsonl")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "nhl":
        for base_parts in (
            ("data", "odds", "games", f"date={date_str}", "scoreboard.csv"),
            ("data", "odds", "team", f"date={date_str}", "oddsapi.csv"),
            ("data", "props", "player_props_lines", f"date={date_str}", "oddsapi.csv"),
        ):
            add(*base_parts)
            add("source_artifacts", *base_parts)
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "nfl":
        season, week = _infer_nfl_week_scope(source_root)
        add(f"real_betting_lines_{date_str.replace('-', '_')}.json")
        add("source_artifacts", f"real_betting_lines_{date_str.replace('-', '_')}.json")
        add(f"oddsapi_player_props_{season}_wk{week}.csv")
        add("source_artifacts", f"oddsapi_player_props_{season}_wk{week}.csv")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "ncaab":
        for base_parts in (
            ("raw_outputs", "by_date", date_str, f"odds_{date_str}.csv"),
            ("source_artifacts", "raw_outputs", "by_date", date_str, f"odds_{date_str}.csv"),
            ("api", "live_lines", f"live_lines_{date_str}.json"),
            ("data", "api", "live_lines", f"live_lines_{date_str}.json"),
            ("source_artifacts", "api", "live_lines", f"live_lines_{date_str}.json"),
        ):
            add(*base_parts)
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "ncaaf":
        artifact_root = source_root / "source_artifacts"
        if artifact_root.exists():
            for candidate in sorted(artifact_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv")):
                if candidate.is_file():
                    candidates.append(candidate)
        return candidates

    return []


def _sync_odds_history_for_refresh(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    tracking_root = source_root / "tracking"
    history_path = _odds_history_path(tracking_root)
    artifact_history_path = _odds_history_artifact_path(source_root, slug)
    shared_history_path = _shared_odds_history_path(slug)
    candidates = _odds_history_snapshot_paths(sport=slug, source_root=source_root, date_str=date_str)
    if not candidates:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_odds_snapshots",
            "sport": slug,
            "date": date_str,
            "history_path": str(history_path),
            "shared_history_path": str(shared_history_path),
            "files_scanned": 0,
            "entries_appended": 0,
        }

    existing: dict[str, Any] = {}
    for candidate_path in (artifact_history_path, history_path):
        try:
            if candidate_path.exists():
                payload = json.loads(candidate_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    existing = payload
                    break
        except Exception:
            continue

    markets = _odds_history_market_states(existing)

    now = _utc_now()
    entries_appended = 0
    count_live = 0
    count_pregame = 0
    files_scanned = 0
    seen_current_snapshots: set[tuple[str, float, float | None]] = set()
    lifecycle_events: list[dict[str, Any]] = []
    seen_market_keys: set[str] = set()
    seen_live_market_keys: set[str] = set()

    for candidate in candidates:
        files_scanned += 1
        suffix = candidate.suffix.lower()
        if suffix == ".csv":
            rows = _odds_history_rows_from_csv(candidate)
        elif suffix == ".jsonl":
            rows = _odds_history_rows_from_jsonl(candidate)
        else:
            rows = _odds_history_rows_from_json(candidate)
        if not rows:
            continue

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            market_key = _odds_history_market_key(row)
            line_snapshot = _odds_history_line_snapshot(row)
            current_line = _primary_line_value(row)
            if not market_key or not line_snapshot or current_line is None:
                continue
            current_odds = _primary_odds_value(row)
            dedupe_key = (market_key, current_line, current_odds)
            if dedupe_key in seen_current_snapshots:
                continue
            seen_current_snapshots.add(dedupe_key)
            seen_market_keys.add(market_key)

            market_state = markets.get(market_key)
            if not isinstance(market_state, dict):
                market_state = {"history": []}
            history = market_state.get("history")
            if not isinstance(history, list):
                history = []

            previous_line = _line_number(market_state.get("last_line"))
            if previous_line is None and history:
                previous_line = _line_number((history[-1] or {}).get("current_line"))
            previous_odds = _line_number(market_state.get("last_odds"))
            if previous_odds is None and history:
                previous_odds = _line_number((history[-1] or {}).get("last_odds"))

            if previous_line is not None and current_line == previous_line and previous_odds is not None and current_odds == previous_odds and history:
                markets[market_key] = market_state
                continue

            try:
                source_path = str(candidate.relative_to(source_root))
            except Exception:
                source_path = str(candidate)

            delta = current_line - previous_line if previous_line is not None else None
            movement = _movement_direction(delta)
            percent_change = _percent_change(current_line, previous_line)
            canonical_record = _canonical_odds_record(
                row=row,
                market_key=market_key,
                sport=slug,
                timestamp=now,
                current_line=current_line,
            )
            canonical_row = attach_market_id(
                {key: value for key, value in row.items() if key not in {"history", "markets"}},
                sport=slug,
                event_id=canonical_record.get("event_id"),
                market_type=canonical_record.get("market_type"),
                entity=canonical_record.get("entity"),
                line=current_line,
            )
            normalized_entry = normalize_odds_entry(
                row=row,
                sport=slug,
                market_key=market_key,
                timestamp=now,
                source_path=source_path,
                market_id=canonical_row.get("market_id"),
                event_id=canonical_record.get("event_id"),
                market_type=canonical_record.get("market_type"),
                entity=canonical_record.get("entity"),
                line=current_line,
                odds=current_odds,
                selection=str(row.get("selection") or "").strip() or None,
            )
            is_live_row = _is_live_odds_row(row, normalized_entry)
            is_final_row = _is_final_status_row(row, normalized_entry)
            if is_live_row:
                count_live += 1
            else:
                count_pregame += 1

            previous_market_type = None
            if history:
                previous_market_type = str((history[-1] or {}).get("normalized", {}).get("market_type") or (history[-1] or {}).get("market_type") or "").strip().lower() or None

            event_type = "open" if previous_line is None and not history else "update"
            if is_live_row and market_key not in seen_live_market_keys:
                event_type = "live"
                seen_live_market_keys.add(market_key)
            elif is_final_row:
                event_type = "final"
            elif previous_market_type is not None and str(normalized_entry.get("market_type") or "").strip().lower() != previous_market_type:
                event_type = "update"

            lifecycle_events.append(
                _market_lifecycle_event(
                    row=row,
                    normalized_entry=normalized_entry,
                    event_type=event_type,
                    sport=slug,
                    timestamp=now,
                    market_key=market_key,
                    current_line=current_line,
                    current_odds=_primary_odds_value(row),
                    is_live=is_live_row,
                )
            )

            history.append(
                {
                    "captured_at": now,
                    "timestamp": now,
                    "sport": slug,
                    "date": date_str,
                    "source_path": source_path,
                    "market_key": market_key,
                    "market_id": canonical_row.get("market_id"),
                    **canonical_record,
                    "previous_line": previous_line,
                    "current_line": current_line,
                    "last_odds": current_odds,
                    "delta": delta,
                    "delta_line": delta,
                    "percent_change": percent_change,
                    "movement": movement,
                    "line": _json_safe(line_snapshot),
                    "row": _json_safe(canonical_row),
                    "normalized": normalized_entry,
                }
            )
            if len(history) > _ODDS_HISTORY_LIMIT:
                history = history[-_ODDS_HISTORY_LIMIT:]
            market_state["history"] = history
            market_state["last_line"] = current_line
            market_state["previous_line"] = previous_line
            market_state["last_odds"] = current_odds
            market_state["delta"] = delta
            market_state["delta_line"] = delta
            market_state["percent_change"] = percent_change
            market_state["movement"] = movement
            market_state["last_updated"] = now
            market_state["last_source_path"] = source_path
            markets[market_key] = market_state
            entries_appended += 1

    missing_market_keys = [key for key in markets.keys() if key not in seen_market_keys]
    for market_key in missing_market_keys:
        market_state = markets.get(market_key)
        if not isinstance(market_state, dict):
            continue
        history = market_state.get("history") if isinstance(market_state.get("history"), list) else []
        latest = history[-1] if history else {}
        if not isinstance(latest, Mapping):
            continue
        normalized_entry = latest.get("normalized") if isinstance(latest.get("normalized"), Mapping) else {}
        lifecycle_events.append(
            _market_lifecycle_event(
                row=latest.get("row") if isinstance(latest.get("row"), Mapping) else latest,
                normalized_entry=normalized_entry,
                event_type="close",
                sport=slug,
                timestamp=now,
                market_key=market_key,
                current_line=_line_number(latest.get("current_line")),
                current_odds=_line_number(latest.get("last_odds")),
                is_live=bool(normalized_entry.get("is_live") if isinstance(normalized_entry, Mapping) else False),
            )
        )

    if lifecycle_events:
        append_odds_lifecycle_events(date_str, lifecycle_events)

    if not entries_appended and history_path.exists():
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_line_or_odds_changes",
            "sport": slug,
            "date": date_str,
            "history_path": str(history_path),
            "files_scanned": int(files_scanned),
            "entries_appended": 0,
        }

    payload = {
        "schema_version": 1,
        "sport": slug,
        "date": date_str,
        "updated_at": now,
        "history_limit": _ODDS_HISTORY_LIMIT,
        "markets": markets,
    }
    payload.update(markets)
    _write_json(history_path, payload)
    _write_json(shared_history_path, payload)
    _write_json(artifact_history_path, payload)
    return {
        "ok": True,
        "skipped": False,
        "reason": None,
        "sport": slug,
        "date": date_str,
        "history_path": str(history_path),
        "shared_history_path": str(shared_history_path),
        "artifact_history_path": str(artifact_history_path),
        "files_scanned": int(files_scanned),
        "entries_appended": int(entries_appended),
        "markets_tracked": len(markets),
    }


def _read_json_payload(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _choose_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _movement_signal_paths_from_meta(meta: Mapping[str, Any] | None) -> list[Path]:
    paths: list[Path] = []
    if not isinstance(meta, Mapping):
        return paths
    direct_path = meta.get("signals_path") or meta.get("movement_path")
    if isinstance(direct_path, str) and direct_path.strip():
        paths.append(Path(direct_path).expanduser())
    artifacts = meta.get("artifacts")
    if isinstance(artifacts, Mapping):
        for artifact in artifacts.values():
            if not isinstance(artifact, Mapping):
                continue
            for key in ("signals_path", "movement_path"):
                value = artifact.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(Path(value).expanduser())
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.resolve()) if path.exists() else str(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)
    return unique_paths


def _normalize_signal_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def _candidate_signal_tokens(row: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "subject_key",
        "player_name",
        "player_key",
        "team",
        "team_key",
        "market",
        "selection",
        "name",
    ):
        token = _normalize_signal_token(row.get(key))
        if token:
            tokens.add(token)
    return tokens


def _payload_rows(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)], "list"
    if isinstance(payload, dict):
        for key in ("data", "recommendations", "rows", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)], key
    return [], ""


def _update_payload_rows(payload: Any, rows: list[dict[str, Any]], container_key: str) -> Any:
    if isinstance(payload, list):
        return rows
    if isinstance(payload, dict) and container_key:
        updated = dict(payload)
        updated[container_key] = rows
        return updated
    return payload


def _recommendation_paths_for_refresh(*, source_root: Path, sport: str, date_str: str) -> list[Path]:
    candidates = [
        source_root / "data" / "processed" / f"recommendations_slate_{date_str}.json",
        source_root / "data" / "processed" / f"props_recommendations_top_by_game_{date_str}.json",
        source_root / "data" / "processed" / f"recommendations_{date_str}.json",
        source_root / "api" / "recommendations" / f"recommendations_{date_str}.json",
        source_root / "data" / "api" / "recommendations" / f"recommendations_{date_str}.json",
        source_root / "source_artifacts" / "api" / "recommendations" / f"recommendations_{date_str}.json",
    ]
    if sport in {"nba", "wnba"}:
        candidates.extend(
            [
                source_root / "data" / "processed" / f"recommendations_slate_{date_str}.json",
                source_root / "data" / "processed" / f"props_recommendations_top_by_game_{date_str}.json",
            ]
        )
    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists():
            unique_candidates.append(candidate)
    return unique_candidates


def refresh_impacted_recommendations_for_tracking(*, sport: str, source_root: Path, date_str: str, tracking_meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    signal_paths = _movement_signal_paths_from_meta(tracking_meta)
    if not signal_paths:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_movement_signals",
            "files_updated": 0,
            "rows_updated": 0,
            "signals_rows": 0,
        }

    signal_tokens: set[str] = set()
    signals_rows = 0
    for path in signal_paths:
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if frame.empty:
            continue
        if "movement_signals" not in path.name:
            candidate_mask = pd.Series(False, index=frame.index)
            if "movement_significant" in frame.columns:
                candidate_mask = candidate_mask | frame["movement_significant"].fillna(False).astype(bool)
            if "line_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["line_move"], errors="coerce").abs().fillna(0.0).ge(0.5)
            if "implied_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["implied_move"], errors="coerce").abs().fillna(0.0).ge(0.02)
            if "price_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["price_move"], errors="coerce").abs().fillna(0.0).ge(10.0)
            frame = frame.loc[candidate_mask].copy()
        if frame.empty:
            continue
        signals_rows += int(len(frame))
        for _, row in frame.iterrows():
            signal_tokens.update(_candidate_signal_tokens(row))

    if not signal_tokens:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_signal_tokens",
            "files_updated": 0,
            "rows_updated": 0,
            "signals_rows": int(signals_rows),
        }

    files_updated = 0
    rows_updated = 0
    updated_files: list[str] = []
    recommendation_paths = _recommendation_paths_for_refresh(source_root=source_root, sport=sport, date_str=date_str)
    for recommendation_path in recommendation_paths:
        payload = _read_json_payload(recommendation_path)
        rows, container_key = _payload_rows(payload)
        if not rows:
            continue

        changed = False
        for index, row in enumerate(rows):
            row_tokens = _candidate_signal_tokens(row)
            if not row_tokens or signal_tokens.isdisjoint(row_tokens):
                continue
            rows[index] = build_recommendation_output(row, sport=sport)
            changed = True
            rows_updated += 1

        if not changed:
            continue

        updated_payload = _update_payload_rows(payload, rows, container_key)
        if isinstance(updated_payload, dict):
            updated_payload["lightweight_refresh"] = {
                "sport": sport,
                "date": date_str,
                "updated_at": _utc_now(),
                "signals_rows": int(signals_rows),
                "rows_updated": int(rows_updated),
            }
        _write_json(recommendation_path, updated_payload)
        files_updated += 1
        try:
            updated_files.append(str(recommendation_path.relative_to(source_root)))
        except Exception:
            updated_files.append(str(recommendation_path))

    return {
        "ok": True,
        "skipped": False,
        "reason": None,
        "files_updated": int(files_updated),
        "rows_updated": int(rows_updated),
        "signals_rows": int(signals_rows),
        "signal_paths": [str(path) for path in signal_paths],
        "updated_files": updated_files,
    }


def _coalesce_series(df: pd.DataFrame, candidates: list[str], default: Any = "") -> pd.Series:
    for column in candidates:
        if column in df.columns:
            return df[column]
    return pd.Series(default, index=df.index)


def _to_snapshot_ts(df: pd.DataFrame, *, fallback_ts: str) -> pd.Series:
    for column in ("snapshot_ts", "last_seen_at", "first_seen_at", "retrieved_at", "pulled_at"):
        if column in df.columns:
            values = pd.to_datetime(df[column], errors="coerce", utc=True)
            if values.notna().any():
                return values.fillna(pd.Timestamp(fallback_ts, tz="UTC")).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return pd.Series(fallback_ts, index=df.index)


def _persist_tracking_snapshot(
    *,
    tracking_root: Path,
    prefix: str,
    scope: str,
    snapshot_df: pd.DataFrame,
    key_cols: list[str],
    line_col: str | None,
    price_cols: list[str],
    label_cols: list[str] | None = None,
) -> dict[str, Any]:
    tracking_root.mkdir(parents=True, exist_ok=True)
    opening_path = tracking_root / f"{prefix}_opening_{scope}.csv"
    history_path = tracking_root / f"{prefix}_history_{scope}.csv"
    movement_path = tracking_root / f"{prefix}_movement_signals_{scope}.csv"

    normalized = snapshot_df.copy() if isinstance(snapshot_df, pd.DataFrame) else pd.DataFrame()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "empty_snapshot",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    required_cols = list(dict.fromkeys(key_cols + ([line_col] if line_col else []) + price_cols + ["snapshot_ts"]))
    if label_cols:
        required_cols.extend([col for col in label_cols if col not in required_cols])
    for column in required_cols:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    normalized = normalized[required_cols].copy()
    normalized["snapshot_ts"] = pd.to_datetime(normalized["snapshot_ts"], errors="coerce", utc=True)
    normalized = normalized[normalized["snapshot_ts"].notna()].copy()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "missing_snapshot_ts",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    normalized = normalized.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").reset_index(drop=True)
    existing_history = _read_csv(history_path)
    if existing_history.empty:
        combined_history = normalized.copy()
    else:
        for column in normalized.columns:
            if column not in existing_history.columns:
                existing_history[column] = pd.NA
        existing_history = existing_history[normalized.columns].copy()
        existing_history["snapshot_ts"] = pd.to_datetime(existing_history["snapshot_ts"], errors="coerce", utc=True)
        combined_history = pd.concat([existing_history, normalized], ignore_index=True, sort=False)
        dedupe_cols = [col for col in normalized.columns if col != "snapshot_ts"] + ["snapshot_ts"]
        combined_history = combined_history.drop_duplicates(subset=dedupe_cols, keep="first")
        combined_history = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").reset_index(drop=True)
    combined_history_to_write = combined_history.copy()
    combined_history_to_write["snapshot_ts"] = combined_history_to_write["snapshot_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    combined_history_to_write.to_csv(history_path, index=False)

    opening = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).first()
    opening_to_write = opening.copy()
    opening_to_write["snapshot_ts"] = pd.to_datetime(opening_to_write["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    opening_to_write.to_csv(opening_path, index=False)

    latest = combined_history.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).last()
    movement = latest.merge(
        opening[key_cols + ([line_col] if line_col else []) + price_cols].rename(
            columns={
                **({line_col: "open_line"} if line_col else {}),
                **{column: f"open_{column}" for column in price_cols},
            }
        ),
        on=key_cols,
        how="left",
    )
    movement = movement.rename(columns={line_col: "current_line"} if line_col else {})
    for column in price_cols:
        movement = movement.rename(columns={column: f"current_{column}"})
    if line_col:
        movement["line_move"] = pd.to_numeric(movement.get("current_line"), errors="coerce") - pd.to_numeric(movement.get("open_line"), errors="coerce")
    for column in price_cols:
        movement[f"{column}_move"] = pd.to_numeric(movement.get(f"current_{column}"), errors="coerce") - pd.to_numeric(movement.get(f"open_{column}"), errors="coerce")
    movement["latest_snapshot_ts"] = pd.to_datetime(movement["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    movement = movement.drop(columns=["snapshot_ts"], errors="ignore")
    movement.to_csv(movement_path, index=False)

    return {
        "ok": True,
        "skipped": False,
        "opening_path": str(opening_path),
        "history_path": str(history_path),
        "movement_path": str(movement_path),
        "opening_rows": int(len(opening)),
        "history_rows": int(len(combined_history)),
        "signals_rows": int(len(movement)),
    }


def _build_nhl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event_id", "game_id", "date"], default="")
    out["player_key"] = _coalesce_series(df, ["player_id", "_merge_key", "player_name", "player"], default="")
    out["player_name"] = _coalesce_series(df, ["player_name", "player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book", "bookmaker"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line", "point"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_ncaab_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    home = _coalesce_series(df, ["home_team", "home", "team_home"], default="")
    away = _coalesce_series(df, ["away_team", "away", "team_away"], default="")
    event_id = _coalesce_series(df, ["event_id", "id"], default="")
    out["event_key"] = event_id.where(event_id.astype(str).str.strip().ne(""), away.astype(str) + " @ " + home.astype(str))
    out["book"] = _coalesce_series(df, ["bookmaker_key", "bookmaker", "provider", "book"], default="")
    out["market"] = _coalesce_series(df, ["market", "market_key"], default="")
    out["selection"] = _coalesce_series(df, ["outcome_name", "name", "team"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["point", "line", "spread", "overUnder"], default=pd.NA), errors="coerce")
    out["price"] = pd.to_numeric(_coalesce_series(df, ["price", "odds", "homeMoneyline", "awayMoneyline"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_nfl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event", "event_id"], default="")
    out["player_name"] = _coalesce_series(df, ["player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _flatten_team_lines_payload(payload: dict[str, Any], *, fallback_ts: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    lines = ((payload or {}).get("lines") or {}) if isinstance(payload, dict) else {}
    snapshot_ts = str((payload or {}).get("fetched_at") or fallback_ts)
    for event_key, event_payload in lines.items():
        event_data = event_payload or {}
        moneyline = event_data.get("moneyline") or {}
        for side in ("home", "away"):
            price = moneyline.get(side)
            if price is not None:
                rows.append({
                    "event_key": event_key,
                    "market": "moneyline",
                    "selection": side,
                    "line": pd.NA,
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
        total_runs = event_data.get("total_runs") or {}
        if total_runs:
            for side in ("over", "under"):
                price = total_runs.get(side)
                if price is not None:
                    rows.append({
                        "event_key": event_key,
                        "market": "total",
                        "selection": side,
                        "line": total_runs.get("line"),
                        "price": price,
                        "snapshot_ts": snapshot_ts,
                    })
        run_line = event_data.get("run_line") or {}
        if run_line:
            rows.append({
                "event_key": event_key,
                "market": "spread",
                "selection": "home",
                "line": run_line.get("home"),
                "price": pd.NA,
                "snapshot_ts": snapshot_ts,
            })
    return pd.DataFrame(rows)


def _flatten_mlb_game_lines(path: Path) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for game in payload.get("games") or []:
        event_key = f"{game.get('away_team', '')} @ {game.get('home_team', '')}".strip()
        segments = ((game.get("markets") or {}).get("segments") or {"full": game.get("markets") or {}})
        for segment_name, segment_payload in segments.items():
            if not isinstance(segment_payload, dict):
                continue
            h2h = segment_payload.get("h2h") or {}
            for side in ("home", "away"):
                odds_key = f"{side}_odds"
                if odds_key in h2h:
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "moneyline",
                        "selection": side,
                        "line": pd.NA,
                        "price": h2h.get(odds_key),
                        "snapshot_ts": snapshot_ts,
                    })
            spreads = segment_payload.get("spreads") or {}
            if spreads:
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_home",
                    "selection": "home",
                    "line": spreads.get("home_line"),
                    "price": spreads.get("home_odds"),
                    "snapshot_ts": snapshot_ts,
                })
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_away",
                    "selection": "away",
                    "line": spreads.get("away_line"),
                    "price": spreads.get("away_odds"),
                    "snapshot_ts": snapshot_ts,
                })
            totals = segment_payload.get("totals") or {}
            if totals:
                for side in ("over", "under"):
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "total",
                        "selection": side,
                        "line": totals.get("line"),
                        "price": totals.get(f"{side}_odds"),
                        "snapshot_ts": snapshot_ts,
                    })
    return pd.DataFrame(rows)


def _flatten_mlb_props(path: Path, root_key: str) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for player_name, markets in (payload.get(root_key) or {}).items():
        for market_name, market_payload in (markets or {}).items():
            if not isinstance(market_payload, dict):
                continue
            for side in ("over", "under"):
                price = market_payload.get(f"{side}_odds")
                if price is None:
                    continue
                rows.append({
                    "player_name": player_name,
                    "market": market_name,
                    "selection": side,
                    "line": market_payload.get("line"),
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
    return pd.DataFrame(rows)


def _sync_csv_tracking(*, tracking_root: Path, prefix: str, scope: str, snapshot_df: pd.DataFrame, key_cols: list[str], line_col: str, price_cols: list[str], label_cols: list[str] | None = None) -> dict[str, Any]:
    return _persist_tracking_snapshot(
        tracking_root=tracking_root,
        prefix=prefix,
        scope=scope,
        snapshot_df=snapshot_df,
        key_cols=key_cols,
        line_col=line_col,
        price_cols=price_cols,
        label_cols=label_cols,
    )


def _infer_nfl_week_scope(source_root: Path) -> tuple[str, Path | None]:
    current_week_path = _choose_existing([source_root / "current_week.json", source_root / "source_artifacts" / "current_week.json"])
    if current_week_path is not None and current_week_path.exists():
        payload = _read_json(current_week_path)
        if isinstance(payload, dict):
            season = payload.get("season")
            week = payload.get("week")
            if season and week:
                path = _choose_existing([
                    source_root / f"oddsapi_player_props_{season}_wk{week}.csv",
                    source_root / "source_artifacts" / f"oddsapi_player_props_{season}_wk{week}.csv",
                ])
                return f"{season}_wk{week}", path
    candidates = sorted(
        list(source_root.glob("oddsapi_player_props_*.csv")) + list((source_root / "source_artifacts").glob("oddsapi_player_props_*.csv")),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        stem = candidates[0].stem.replace("oddsapi_player_props_", "")
        return stem, candidates[0]
    return "unknown", None


def sync_sport_post_refresh_tracking(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    if slug in {"nba", "wnba"}:
        results = sync_basketball_props_tracking_for_source_root(sport=slug, source_root=source_root, date_str=date_str)
        if bool(results.get("ok")):
            results["artifacts"] = dict(results.get("artifacts") or {})
            results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
                sport=slug,
                source_root=source_root,
                date_str=date_str,
                tracking_meta=results,
            )
            results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    tracking_root = source_root / "tracking"
    results: dict[str, Any] = {"ok": True, "sport": slug, "date": date_str, "tracking_root": str(tracking_root), "artifacts": {}}

    if slug == "nhl":
        props_path = source_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv"
        team_path = source_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv"
        props_df = _build_nhl_props_snapshot(props_path)
        team_df = _build_ncaab_snapshot(team_path)
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_player_props",
            scope=date_str,
            snapshot_df=props_df,
            key_cols=["event_key", "player_key", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
            label_cols=["player_name"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "nfl":
        scope, props_path = _infer_nfl_week_scope(source_root)
        props_df = _build_nfl_props_snapshot(props_path) if props_path is not None else pd.DataFrame()
        team_candidates = sorted(
            list(source_root.glob("real_betting_lines_*.json")) + list((source_root / "source_artifacts").glob("real_betting_lines_*.json")),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        team_df = _flatten_team_lines_payload(_read_json(team_candidates[0]), fallback_ts=_utc_now()) if team_candidates else pd.DataFrame()
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_player_props",
            scope=scope,
            snapshot_df=props_df,
            key_cols=["event_key", "player_name", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "mlb":
        snapshot_root = source_root / "source_artifacts" / "data" / "daily" / "snapshots" / date_str
        if not snapshot_root.exists():
            snapshot_root = source_root / "data" / "daily" / "snapshots" / date_str
        date_slug = date_str.replace("-", "_")
        game_df = _flatten_mlb_game_lines(snapshot_root / f"oddsapi_game_lines_{date_slug}.json")
        hitter_df = _flatten_mlb_props(snapshot_root / f"oddsapi_hitter_props_{date_slug}.json", "hitter_props")
        pitcher_df = _flatten_mlb_props(snapshot_root / f"oddsapi_pitcher_props_{date_slug}.json", "pitcher_props")
        results["artifacts"]["game_lines"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_game_lines",
            scope=date_str,
            snapshot_df=game_df,
            key_cols=["event_key", "segment", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["hitter_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_hitter_props",
            scope=date_str,
            snapshot_df=hitter_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["pitcher_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_pitcher_props",
            scope=date_str,
            snapshot_df=pitcher_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "ncaab":
        odds_path = source_root / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        if not odds_path.exists():
            odds_path = source_root / "data" / "ncaab_source" / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        team_df = _build_ncaab_snapshot(odds_path)
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_ncaab_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "ncaaf":
        artifact_root = source_root / "source_artifacts"
        latest_predicted = sorted(artifact_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        manifest = {
            "sport": slug,
            "date": date_str,
            "generated_at": _utc_now(),
            "latest_predicted_totals": str(latest_predicted[0]) if latest_predicted else None,
            "predicted_totals_files": [str(path) for path in latest_predicted[:10]],
            "notes": "NCAAF currently mirrors schedule-enhanced totals snapshots rather than per-market odds rows; this manifest keeps the central post-refresh contract owned by Syndicate until a normalized lines snapshot is added.",
        }
        manifest_path = tracking_root / f"odds_ncaaf_source_manifest_{date_str}.json"
        _write_json(manifest_path, manifest)
        results["artifacts"]["source_manifest"] = {
            "ok": True,
            "skipped": False,
            "manifest_path": str(manifest_path),
            "predicted_totals_files": len(latest_predicted),
        }
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    return {"ok": False, "sport": slug, "date": date_str, "error": f"unsupported_sport:{slug}"}


def sync_post_refresh_tracking_for_source_root(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    return sync_sport_post_refresh_tracking(sport=sport, source_root=source_root, date_str=date_str)