from __future__ import annotations

import ast
import argparse
import contextlib
import csv
import datetime as dt
import errno
import importlib
import importlib.util
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_props_edges import export_props_edges_local
from syndicate.features.shared.basketball_live_artifacts import build_live_player_lens_payload_from_artifacts
from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local
from syndicate.features.shared.basketball_props_recommendations import export_props_recommendations_local
from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local
from syndicate.features.shared.memory_observability import log_dataframe_memory
from syndicate.features.shared.memory_observability import log_list_memory
from syndicate.features.shared.memory_observability import log_runtime_memory
from syndicate.features.shared.refresh_state_store import build_input_hash
from syndicate.features.shared.refresh_state_store import path_fingerprint
from syndicate.features.shared.refresh_state_store import path_exists as _keyvalue_path_exists
from syndicate.features.shared.refresh_state_store import read_json_file as _keyvalue_read_json_file
from syndicate.features.shared.refresh_state_store import read_text_file as _keyvalue_read_text_file
from syndicate.features.shared.refresh_state_store import record_refresh_state
from syndicate.features.shared.refresh_state_store import should_recompute
from syndicate.features.shared.refresh_state_store import write_json_file as _keyvalue_write_json_file
from syndicate.features.shared.refresh_state_store import write_text_file as _keyvalue_write_text_file


def _json_ready(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _refresh_state_scope_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(Path(path).resolve())
    except Exception:
        return str(Path(path))


def _canonical_wnba_tri(value: object) -> str:
    text = str(value or "").strip().upper()
    compact = "".join(ch for ch in text if ch.isalnum())
    mapped = {
        "LA": "LAS",
        "LV": "LVA",
        "LVA": "LVA",
        "GS": "GSV",
        "GSW": "GSV",
        "NY": "NYL",
        "CONN": "CON",
        "WAS": "WSH",
        "LASVEGASACES": "LVA",
        "LOSANGELESSPARKS": "LAS",
        "NEWYORKLIBERTY": "NYL",
        "CONNECTICUTSUN": "CON",
        "WASHINGTONMYSTICS": "WSH",
        "INDIANAFEVER": "IND",
        "MINNESOTALYNX": "MIN",
        "SEATTLESTORM": "SEA",
        "PHOENIXMERCURY": "PHX",
        "DALLASWINGS": "DAL",
        "ATLANTADREAM": "ATL",
        "CHICAGOSKY": "CHI",
        "GOLDENSTATEVALKYRIES": "GSV",
    }
    return mapped.get(text, mapped.get(compact, text))


def _source_app_fallback_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_WNBA_SOURCE_APP_FALLBACK") or "").strip().lower() in {"1", "true", "yes", "on"}


def _copy_if_exists(source_path: str | None, destination_path: Path) -> bool:
    source_text = str(source_path or "").strip()
    if not source_text:
        return False
    source = Path(source_text)
    if not source.exists() or not source.is_file():
        return False
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination_path)
    return True


def _copy_matching_files(*, source_directory: Path, pattern: str, destination_directory: Path) -> list[str]:
    if not source_directory.exists() or not source_directory.is_dir():
        return []
    copied: list[str] = []
    for source in sorted(source_directory.glob(pattern)):
        if not source.is_file():
            continue
        destination = destination_directory / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_with_fallback(source, destination)
        copied.append(str(destination))
    return copied


def _copy_existing_processed_artifact(*, source_root: Path, processed_root: Path, file_name: str) -> str | None:
    source = source_root / "data" / "processed" / file_name
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / file_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_with_fallback(source, destination)
    return str(destination)


def _copy_file_with_fallback(source: Path, destination: Path) -> None:
    try:
        shutil.copy2(source, destination)
    except OSError:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as source_handle, destination.open("wb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle)
        try:
            shutil.copystat(source, destination)
        except OSError:
            pass


def _copy_existing_live_lens_artifact(*, source_root: Path, file_name: str, destinations: tuple[tuple[Path, str | None], ...]) -> dict[str, str]:
    candidates = (
        source_root / "data" / "processed" / file_name,
        source_root / "data" / "live_lens" / file_name,
    )
    source = next((path for path in candidates if path.exists() and path.is_file()), None)
    if source is None:
        return {}
    copied: dict[str, str] = {}
    raw = source.read_bytes()
    for out_path, copied_key in destinations:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _copy_existing_live_snapshot_artifact(*, source_root: Path, file_name: str, destination: Path) -> str | None:
    source = source_root / "data" / "processed" / "live_snapshots" / file_name
    if not source.exists() or not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.resolve() == destination.resolve():
            return str(destination)
    except Exception:
        pass
    shutil.copy2(source, destination)
    return str(destination)


def _read_live_snapshot_payload(path: Path) -> dict[str, object] | None:
    # The production writer below always overwrites with a single record, so
    # try the keyvalue-aware reader first (cross-service consistent) before
    # falling back to the old multi-line-JSONL local read, which only
    # matters for files an external source app's own exporter appended to.
    keyvalue_record = _keyvalue_read_json_file(path)
    if isinstance(keyvalue_record, dict):
        payload = keyvalue_record.get("payload") if isinstance(keyvalue_record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(keyvalue_record.get("games"), list):
            return keyvalue_record

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        raw = str(line or "").strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except Exception:
            continue
        payload = record.get("payload") if isinstance(record, dict) and isinstance(record.get("payload"), dict) else None
        if isinstance(payload, dict):
            return payload
        if isinstance(record, dict) and isinstance(record.get("games"), list):
            return record
    return None


def _write_live_snapshot_payload(path: Path, payload: dict[str, object]) -> bool:
    if not isinstance(payload, dict):
        return False
    # Written cross-service through the keyvalue store: the live-lens
    # background loop and the on-demand web request path run on different
    # Render services with separate local disks, so a plain local write here
    # would be invisible to whichever service didn't just write it.
    record = {"payload": payload}
    _keyvalue_write_json_file(path, record)
    return True


def _payload_has_snapshot_content(kind: str, payload: dict[str, object] | None) -> bool:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    if not games:
        return False
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind == "live_player_lens":
        return any(isinstance(game, dict) and bool(game.get("rows")) for game in games)
    if normalized_kind == "live_player_boxscore":
        return any(isinstance(game, dict) and bool(game.get("players")) for game in games)
    if normalized_kind == "live_lines":
        return any(
            isinstance(game, dict)
            and (
                any(_float_or_none(game.get(key)) is not None for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"))
                or (
                    isinstance(game.get("lines"), dict)
                    and (
                        any(_float_or_none((game.get("lines") or {}).get(key)) is not None for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"))
                        or any(
                            _float_or_none(value) is not None
                            for period_key in ("period_totals", "period_spreads")
                            for value in (((game.get("lines") or {}).get(period_key) or {}).values() if isinstance(((game.get("lines") or {}).get(period_key)), dict) else [])
                        )
                    )
                )
            )
            for game in games
        )
    if normalized_kind == "live_pbp_stats":
        return any(
            isinstance(game, dict)
            and any(game.get(key) is not None for key in ("pbp_recent", "pbp_attempts", "pbp_possessions", "pbp_quarters"))
            for game in games
        )
    return True


def _live_lines_interval_count(payload: dict[str, object] | None) -> int:
    games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
    interval_count = 0
    for game in games:
        if not isinstance(game, dict):
            continue
        lines = game.get("lines") if isinstance(game.get("lines"), dict) else {}
        for key in ("period_totals", "period_spreads"):
            values = lines.get(key) if isinstance(lines.get(key), dict) else {}
            interval_count += sum(1 for value in values.values() if _float_or_none(value) is not None)
    return interval_count


def _prefer_live_lines_payload(current: dict[str, object] | None, candidate: dict[str, object] | None) -> dict[str, object] | None:
    if not _payload_has_snapshot_content("live_lines", candidate):
        return current
    if not _payload_has_snapshot_content("live_lines", current):
        return candidate
    if _live_lines_interval_count(candidate) > _live_lines_interval_count(current):
        return candidate
    return current


def _load_game_odds_rows_by_matchup(*, source_root: Path, processed_root: Path, date_str: str) -> dict[tuple[str, str], dict[str, object]]:
    candidates = [
        source_root / "data" / "processed" / f"game_odds_{date_str}.csv",
        processed_root / f"game_odds_{date_str}.csv",
    ]
    out: dict[tuple[str, str], dict[str, object]] = {}
    odds_path = next((path for path in candidates if path.exists() and path.is_file() and _count_csv_rows_quick(path) > 0), None)
    if odds_path is None:
        return out
    try:
        with odds_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                home_tri = _canonical_wnba_tri(_to_tricode_local(str(row.get("home_team") or row.get("home_tri") or "").strip()))
                away_tri = _canonical_wnba_tri(_to_tricode_local(str(row.get("visitor_team") or row.get("away_team") or row.get("away_tri") or "").strip()))
                if not home_tri or not away_tri:
                    continue
                out[(home_tri, away_tri)] = {
                    "total": _float_or_none(row.get("total")),
                    "home_spread": _float_or_none(row.get("home_spread")),
                    "away_spread": _float_or_none(row.get("away_spread")),
                    "home_ml": _float_or_none(row.get("home_ml")),
                    "away_ml": _float_or_none(row.get("away_ml")),
                    "bookmaker": str(row.get("bookmaker") or "").strip() or None,
                }
    except Exception:
        return {}
    return out


def _load_period_lines_rows_by_matchup(*, source_root: Path, processed_root: Path, date_str: str) -> dict[tuple[str, str], dict[str, dict[str, float | None]]]:
    candidates = [
        source_root / "data" / "processed" / f"period_lines_{date_str}.csv",
        processed_root / f"period_lines_{date_str}.csv",
    ]
    period_path = next((path for path in candidates if path.exists() and path.is_file() and _count_csv_rows_quick(path) > 0), None)
    if period_path is None:
        return {}
    out: dict[tuple[str, str], dict[str, dict[str, float | None]]] = {}
    try:
        with period_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                home_tri = _canonical_wnba_tri(_to_tricode_local(str(row.get("home_team") or row.get("home_tri") or "").strip()))
                away_tri = _canonical_wnba_tri(_to_tricode_local(str(row.get("visitor_team") or row.get("away_team") or row.get("away_tri") or "").strip()))
                if not home_tri or not away_tri:
                    continue
                out[(home_tri, away_tri)] = {
                    "period_totals": {
                        "h1": _float_or_none(row.get("h1_total")),
                        "q1": _float_or_none(row.get("q1_total")),
                        "q2": _float_or_none(row.get("q2_total")),
                        "q3": _float_or_none(row.get("q3_total")),
                        "q4": _float_or_none(row.get("q4_total")),
                    },
                    "period_spreads": {
                        "h1": _float_or_none(row.get("h1_spread")),
                        "q1": _float_or_none(row.get("q1_spread")),
                        "q2": _float_or_none(row.get("q2_spread")),
                        "q3": _float_or_none(row.get("q3_spread")),
                        "q4": _float_or_none(row.get("q4_spread")),
                    },
                }
    except Exception:
        return {}
    return out


def _build_source_live_lines_payload(
    *,
    source_root: Path,
    processed_root: Path,
    date_str: str,
    state_payload: dict[str, object] | None,
) -> dict[str, object] | None:
    games = state_payload.get("games") if isinstance(state_payload, dict) and isinstance(state_payload.get("games"), list) else []
    if not games:
        return None

    odds_by_matchup = _load_game_odds_rows_by_matchup(source_root=source_root, processed_root=processed_root, date_str=date_str)
    period_by_matchup = _load_period_lines_rows_by_matchup(source_root=source_root, processed_root=processed_root, date_str=date_str)
    source_app = _load_source_app(source_root)

    out_games: list[dict[str, object]] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        event_id = str(game.get("event_id") or "").strip()
        home_tri = _canonical_wnba_tri(_to_tricode_local(str(game.get("home") or "").strip()) or str(game.get("home") or "").strip())
        away_tri = _canonical_wnba_tri(_to_tricode_local(str(game.get("away") or "").strip()) or str(game.get("away") or "").strip())
        if not event_id or not home_tri or not away_tri:
            continue
        matchup_key = (home_tri, away_tri)
        pregame_lines = dict(odds_by_matchup.get(matchup_key) or {})
        period_lines = dict(period_by_matchup.get(matchup_key) or {})
        live_lines = {}
        if bool(game.get("in_progress")) and source_app is not None and hasattr(source_app, "_live_oddsapi_period_totals_for_game"):
            try:
                live_lines = source_app._live_oddsapi_period_totals_for_game(date_str, home_tri, away_tri) or {}
            except Exception:
                live_lines = {}
        game_lines = live_lines.get("game_lines") if isinstance(live_lines.get("game_lines"), dict) else {}
        period_totals = live_lines.get("period_totals") if isinstance(live_lines.get("period_totals"), dict) else None
        period_spreads = live_lines.get("period_spreads") if isinstance(live_lines.get("period_spreads"), dict) else None
        if not (isinstance(period_totals, dict) and any(_float_or_none(value) is not None for value in period_totals.values())):
            period_totals = period_lines.get("period_totals") if isinstance(period_lines.get("period_totals"), dict) else None
            period_spreads = period_lines.get("period_spreads") if isinstance(period_lines.get("period_spreads"), dict) else None
        merged_lines = {
            "total": _float_or_none(game_lines.get("total")) if isinstance(game_lines, dict) and game_lines.get("total") is not None else _float_or_none(pregame_lines.get("total")),
            "home_spread": _float_or_none(game_lines.get("home_spread")) if isinstance(game_lines, dict) and game_lines.get("home_spread") is not None else _float_or_none(pregame_lines.get("home_spread")),
            "away_spread": _float_or_none(game_lines.get("away_spread")) if isinstance(game_lines, dict) and game_lines.get("away_spread") is not None else _float_or_none(pregame_lines.get("away_spread")),
            "home_ml": _float_or_none(game_lines.get("home_ml")) if isinstance(game_lines, dict) and game_lines.get("home_ml") is not None else _float_or_none(pregame_lines.get("home_ml")),
            "away_ml": _float_or_none(game_lines.get("away_ml")) if isinstance(game_lines, dict) and game_lines.get("away_ml") is not None else _float_or_none(pregame_lines.get("away_ml")),
            "period_totals": period_totals,
            "period_spreads": period_spreads,
        }
        out_games.append(
            {
                "event_id": event_id,
                "found": any(_float_or_none(merged_lines.get(key)) is not None for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml"))
                or any(
                    _float_or_none(value) is not None
                    for values in (merged_lines.get("period_totals"), merged_lines.get("period_spreads"))
                    if isinstance(values, dict)
                    for value in values.values()
                ),
                "game_id": game.get("game_id"),
                "home": home_tri,
                "away": away_tri,
                "in_progress": bool(game.get("in_progress")),
                "source": {
                    "scoreboard": "live_state_snapshot",
                    "game_lines": "processed_game_odds" if any(_float_or_none(merged_lines.get(key)) is not None for key in ("total", "home_spread", "away_spread", "home_ml", "away_ml")) else None,
                    "period_totals": "oddsapi_fast" if isinstance(live_lines.get("period_totals"), dict) and any(_float_or_none(value) is not None for value in live_lines.get("period_totals", {}).values()) else ("processed_period_lines" if isinstance(period_totals, dict) and any(_float_or_none(value) is not None for value in period_totals.values()) else None),
                },
                "lines": merged_lines,
            }
        )

    payload = {"ok": True, "ttl": 20, "date": date_str, "games": out_games}
    return payload if _payload_has_snapshot_content("live_lines", payload) else None


def _snapshot_artifact_has_meaningful_content(kind: str, path: Path | None) -> bool:
    payload = _read_live_snapshot_payload(path) if path is not None else None
    return _payload_has_snapshot_content(kind, payload)


def _build_local_live_snapshot_payload(*, kind: str, date_str: str, event_ids: list[str]) -> dict[str, object] | None:
    normalized_kind = str(kind or "").strip().lower()
    try:
        from syndicate.features.wnba.cards import build_live_lines_payload
        from syndicate.features.wnba.cards import build_live_pbp_stats_payload
        from syndicate.features.wnba.cards import build_live_player_boxscore_payload
        from syndicate.features.wnba.cards import build_live_player_lens_payload
        from syndicate.features.wnba.cards import build_live_state_payload

        if normalized_kind == "live_state":
            return build_live_state_payload(date_str, ttl=12, allow_stored_date_fallback=True)
        if normalized_kind == "live_pbp_stats":
            return build_live_pbp_stats_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
        if normalized_kind == "live_lines":
            return build_live_lines_payload(date_str, event_ids, ttl=20, include_period_totals=True, allow_stored_date_fallback=True)
        if normalized_kind == "live_player_boxscore":
            return build_live_player_boxscore_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
        if normalized_kind == "live_player_lens":
            return build_live_player_lens_payload(date_str, event_ids, ttl=20, allow_stored_date_fallback=True)
    except Exception:
        return None
    return None


def _build_bundle_local_live_snapshot_payload(*, kind: str, date_str: str, event_ids: list[str], processed_root: Path) -> dict[str, object] | None:
    bundle_root = processed_root.parents[1]
    env_name = "SYNDICATE_WNBA_SOURCE_ROOT"
    previous_value = os.environ.get(env_name)
    os.environ[env_name] = str(bundle_root)
    try:
        try:
            from syndicate.features.wnba import cards as cards_module

            cache_clear = getattr(getattr(cards_module, "_local_live_snapshot_payload", None), "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
            state_cache_clear = getattr(getattr(cards_module, "_local_live_state_payload", None), "cache_clear", None)
            if callable(state_cache_clear):
                state_cache_clear()
        except Exception:
            cards_module = None
        payload = _build_local_live_snapshot_payload(kind=kind, date_str=date_str, event_ids=event_ids)
        try:
            cache_clear = getattr(getattr(cards_module, "_local_live_snapshot_payload", None), "cache_clear", None)
            if callable(cache_clear):
                cache_clear()
            state_cache_clear = getattr(getattr(cards_module, "_local_live_state_payload", None), "cache_clear", None)
            if callable(state_cache_clear):
                state_cache_clear()
        except Exception:
            pass
        return payload
    finally:
        if previous_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_value


def _build_bundle_local_live_player_lens_payload(*, processed_root: Path, date_str: str) -> dict[str, object] | None:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not game_cards_path.exists() or not game_cards_path.is_file():
        return None
    event_games: dict[str, dict[str, object]] = {}
    try:
        with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                event_id = str(row.get("event_id") or "").strip()
                home_tri = str(row.get("home_tri") or "").strip().upper()
                away_tri = str(row.get("away_tri") or "").strip().upper()
                if not event_id or not home_tri or not away_tri:
                    continue
                event_games[event_id] = {
                    "event_id": event_id,
                    "home_tri": home_tri,
                    "away_tri": away_tri,
                }
    except Exception:
        return None
    if not event_games:
        return None
    try:
        return build_live_player_lens_payload_from_artifacts(
            processed_root=processed_root,
            date_str=date_str,
            event_games=event_games,
            source="syndicate_live_lens_projection_artifact",
        )
    except Exception:
        return None


def _boxscores_history_sources(*, source_root: Path, processed_root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for root in (source_root / "data" / "processed", processed_root):
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("boxscores_*.csv")):
            try:
                key = str(path.resolve())
            except Exception:
                key = str(path)
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            candidates.append(path)
    return candidates


def _refresh_boxscores_history_artifact(*, source_root: Path, processed_root: Path) -> str | None:
    sources = _boxscores_history_sources(source_root=source_root, processed_root=processed_root)
    if not sources:
        existing = source_root / "data" / "processed" / "boxscores_history.csv"
        if not existing.exists() or not existing.is_file():
            return None
        destination = processed_root / existing.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(existing, destination)
        return str(destination)

    rows: list[dict[str, str]] = []
    header_order: list[str] = []
    seen_rows: set[tuple[str, ...]] = set()
    for source in sources:
        with source.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            for field in reader.fieldnames:
                if field not in header_order:
                    header_order.append(field)
            for row in reader:
                normalized = {field: str((row or {}).get(field, "") or "") for field in header_order}
                row_key = tuple(normalized.get(field, "") for field in header_order)
                if row_key in seen_rows:
                    continue
                seen_rows.add(row_key)
                rows.append(normalized)

    if not header_order:
        return None

    destination = processed_root / "boxscores_history.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header_order)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in header_order})
    return str(destination)


def _export_team_advanced_stats_artifacts(*, source_root: Path, processed_root: Path) -> list[str]:
    copied: list[str] = []
    source_processed = source_root / "data" / "processed"
    if not source_processed.exists() or not source_processed.is_dir():
        return copied
    for source in sorted(source_processed.glob("team_advanced_stats_*.csv")):
        if not source.is_file():
            continue
        destination = processed_root / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_with_fallback(source, destination)
        copied.append(str(destination))
    return copied


def _export_live_snapshot_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    live_snapshots_root = processed_root / "live_snapshots"
    snapshot_specs = (
        ("live_state", None),
        ("live_pbp_stats", "live_pbp_stats_path"),
        ("live_lines", "live_lines_path"),
        ("live_player_boxscore", "live_player_boxscore_path"),
        ("live_player_lens", "live_player_lens_path"),
    )
    copied: dict[str, str] = {}
    state_payload: dict[str, object] | None = None

    state_file = f"live_state_{date_str}.jsonl"
    state_destination = live_snapshots_root / state_file
    existing_state = _copy_existing_live_snapshot_artifact(
        source_root=source_root,
        file_name=state_file,
        destination=state_destination,
    )
    if existing_state:
        copied["live_state_path"] = existing_state
        state_payload = _read_live_snapshot_payload(state_destination)

    source_app = None
    client = None

    def _ensure_client():
        nonlocal source_app, client
        if client is not None:
            return client
        source_app = _load_source_app(source_root)
        if source_app is None:
            return None
        client = source_app.app.test_client()
        return client

    def _fetch_json(query: str) -> dict[str, object] | None:
        test_client = _ensure_client()
        if test_client is None:
            return None
        try:
            response = test_client.get(query)
            if int(getattr(response, "status_code", 0) or 0) != 200:
                return None
            payload = response.get_json() if response is not None else None
        except Exception:
            payload = None
        return payload if isinstance(payload, dict) else None

    refreshed_state_payload = _fetch_json(f"/api/live_state?date={date_str}") if _source_app_fallback_enabled() else None
    if _payload_has_snapshot_content("live_state", refreshed_state_payload):
        state_payload = refreshed_state_payload
    if not _payload_has_snapshot_content("live_state", state_payload):
        local_state_payload = _build_local_live_snapshot_payload(kind="live_state", date_str=date_str, event_ids=[])
        if _payload_has_snapshot_content("live_state", local_state_payload):
            state_payload = local_state_payload
    if _payload_has_snapshot_content("live_state", state_payload) and _write_live_snapshot_payload(state_destination, state_payload):
        copied["live_state_path"] = str(state_destination)
    elif existing_state and not _snapshot_artifact_has_meaningful_content("live_state", state_destination):
        try:
            state_destination.unlink(missing_ok=True)
        except Exception:
            pass

    event_ids = [
        str(game.get("event_id") or "").strip()
        for game in ((state_payload or {}).get("games") or [])
        if isinstance(game, dict) and str(game.get("event_id") or "").strip()
    ]
    joined_event_ids = ",".join(dict.fromkeys(event_ids))

    for kind, copied_key in snapshot_specs[1:]:
        file_name = f"{kind}_{date_str}.jsonl"
        destination = live_snapshots_root / file_name
        existing = _copy_existing_live_snapshot_artifact(
            source_root=source_root,
            file_name=file_name,
            destination=destination,
        )
        payload = None
        if joined_event_ids and _source_app_fallback_enabled():
            query = f"/api/{kind}?date={date_str}&event_ids={joined_event_ids}"
            if kind == "live_lines":
                query = f"{query}&include_period_totals=1"
            payload = _fetch_json(query)
        if kind == "live_lines":
            source_payload = _build_source_live_lines_payload(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                state_payload=state_payload,
            )
            payload = _prefer_live_lines_payload(payload, source_payload)
        local_payload = _build_local_live_snapshot_payload(kind=kind, date_str=date_str, event_ids=event_ids)
        if kind == "live_lines":
            payload = _prefer_live_lines_payload(payload, local_payload)
        elif not _payload_has_snapshot_content(kind, payload):
            payload = local_payload
        bundle_payload = _build_bundle_local_live_snapshot_payload(
            kind=kind,
            date_str=date_str,
            event_ids=event_ids,
            processed_root=processed_root,
        )
        if kind == "live_lines":
            payload = _prefer_live_lines_payload(payload, bundle_payload)
        elif not _payload_has_snapshot_content(kind, payload):
            payload = bundle_payload
        if kind == "live_player_lens" and not _payload_has_snapshot_content(kind, payload):
            payload = _build_bundle_local_live_player_lens_payload(processed_root=processed_root, date_str=date_str)
        if isinstance(payload, dict) and _payload_has_snapshot_content(kind, payload) and _write_live_snapshot_payload(destination, payload):
            if copied_key:
                copied[copied_key] = str(destination)
            continue
        if existing and _snapshot_artifact_has_meaningful_content(kind, destination) and copied_key:
            copied[copied_key] = existing
            continue
        if existing:
            try:
                destination.unlink(missing_ok=True)
            except Exception:
                pass

    return copied


def _count_csv_rows_quick(path: Path | None) -> int:
    try:
        if path is None or not path.exists() or not path.is_file():
            return 0
        newline_count = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                newline_count += chunk.count(b"\n")
        return max(0, int(newline_count - 1))
    except Exception:
        return 0


def _path_has_meaningful_content(path: Path | None) -> bool:
    try:
        if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        if path.suffix.lower() == ".csv":
            return _count_csv_rows_quick(path) > 0
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            return False
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                return bool(payload)
            if isinstance(payload, list):
                return len(payload) > 0
        return True
    except Exception:
        return False


def _append_log(log_file: Path, line: str) -> None:
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8", errors="ignore") as out:
            out.write(f"[{dt.datetime.utcnow().isoformat(timespec='seconds')}] {line.rstrip()}\n")
    except Exception:
        pass


def _log_frame_memory(stage: str, frame: object, **details: object) -> None:
    log_runtime_memory(stage, **details)
    log_dataframe_memory(stage, frame)


def _refresh_step_input_hash(*, source_root: Path, processed_root: Path, date_str: str, do_edges: bool, do_export: bool, artifact_root: Path | None = None) -> str:
    smart_sim_paths = sorted(processed_root.glob(f"smart_sim_{date_str}_*.json"))
    return build_input_hash(
        {
            "step": "wnba_refresh",
            "date": date_str,
            "do_edges": bool(do_edges),
            "do_export": bool(do_export),
            "artifact_root": str(artifact_root) if artifact_root is not None else None,
            "inputs": [
                path_fingerprint(source_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv"),
                path_fingerprint(processed_root / f"oddsapi_player_props_{date_str}.csv"),
                path_fingerprint(processed_root / f"game_cards_{date_str}.csv"),
                path_fingerprint(processed_root / f"cards_sim_detail_{date_str}.json"),
                *[path_fingerprint(path) for path in smart_sim_paths],
            ],
        }
    )


def _materialize_processed_snapshot_alias(*, processed_root: Path, date_str: str, snapshot_path: Path, log_file: Path | None = None) -> tuple[Path, int, str | None]:
    alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    try:
        if not snapshot_path.exists() or not snapshot_path.is_file() or snapshot_path.stat().st_size <= 0:
            return alias_path, 0, None
        alias_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot_path, alias_path)
        rows = int(_count_csv_rows_quick(alias_path))
        if log_file is not None:
            _append_log(log_file, f"Materialized processed OddsAPI props snapshot alias: {alias_path} (rows={rows})")
        return alias_path, rows, None
    except Exception as exc:
        if log_file is not None:
            _append_log(log_file, f"Failed to materialize processed OddsAPI props snapshot alias: {exc}")
        return alias_path, 0, str(exc)


def _source_python(source_root: Path) -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if override and Path(override).exists() and "windowsapps" not in override.lower():
        return override
    if sys.executable and Path(sys.executable).exists() and "windowsapps" not in str(sys.executable).lower():
        return sys.executable
    for installed in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if installed.exists():
            return str(installed)
    candidates = [
        source_root / ".venv" / "Scripts" / "python.exe",
        source_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists() and "windowsapps" not in str(candidate).lower():
            return str(candidate)
    if sys.executable and Path(sys.executable).exists():
        return sys.executable
    return "python"


def _count_cards_sim_detail_games(path: Path | None) -> int:
    try:
        if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return 0
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, list):
            return 0
        count = 0
        for row in games:
            if not isinstance(row, dict):
                continue
            sim = row.get("sim") if isinstance(row.get("sim"), dict) else {}
            players = sim.get("players") if isinstance(sim.get("players"), dict) else {}
            home_players = players.get("home") if isinstance(players.get("home"), list) else []
            away_players = players.get("away") if isinstance(players.get("away"), list) else []
            if len(home_players) + len(away_players) > 0:
                count += 1
        return int(count)
    except Exception:
        return 0


def _count_matching_files(source_directory: Path | None, pattern: str) -> int:
    try:
        if source_directory is None or not source_directory.exists() or not source_directory.is_dir():
            return 0
        return sum(1 for path in source_directory.glob(pattern) if path.is_file())
    except Exception:
        return 0


def _local_python() -> str:
    override = str(os.environ.get("SYNDICATE_PYTHON_EXE") or "").strip()
    if override and Path(override).exists() and "windowsapps" not in override.lower():
        return override
    if sys.executable and Path(sys.executable).exists() and "windowsapps" not in str(sys.executable).lower():
        return sys.executable
    for installed in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311" / "python.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python311-arm64" / "python.exe",
    ):
        if installed.exists():
            return str(installed)
    return "python"


def _local_worker_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _owned_snapshot_cli_args(*, date_str: str, out_path: Path, regions: str, bookmakers: str, markets: str) -> list[str]:
    args = [
        _local_python(),
        str(REPO_ROOT / "scripts" / "fetch_basketball_oddsapi_props_local.py"),
        "--league",
        "wnba",
        "--date",
        date_str,
        "--out",
        str(out_path),
        "--regions",
        str(regions or "us").strip() or "us",
    ]
    if bookmakers:
        args.extend(["--bookmakers", bookmakers])
    if markets:
        args.extend(["--markets", markets])
    return args


def _source_worker_env(source_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    src_dir = str(source_root / "src")
    existing = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OMP_THREAD_LIMIT", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    env.setdefault("MKL_NUM_THREADS", "1")
    env.setdefault("NUMEXPR_NUM_THREADS", "1")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    return env


def _run_source_processed_export(
    *,
    source_root: Path,
    package_name: str,
    command_name: str,
    date_str: str,
    expected_file_name: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> tuple[str | None, int]:
    existing_path = source_root / "data" / "processed" / expected_file_name
    if _path_has_meaningful_content(existing_path):
        return str(existing_path), 0

    rc = _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            command_name,
            "--date",
            date_str,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=15 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )

    if _path_has_meaningful_content(existing_path):
        return str(existing_path), int(rc)

    _append_log(log_file, f"{command_name} did not create expected artifact: {existing_path}")
    return None, int(rc)


def _recommendation_tier(*, market: str, ev_value: float | None, edge_value: float | None) -> str:
    if str(market or "").strip().upper() == "ML":
        if ev_value is None:
            return "Low"
        if ev_value >= 0.04:
            return "High"
        if ev_value >= 0.02:
            return "Medium"
        return "Low"
    if edge_value is None:
        return "Low"
    abs_edge = abs(float(edge_value))
    if abs_edge >= 4.0:
        return "High"
    if abs_edge >= 2.0:
        return "Medium"
    return "Low"


def _float_or_none(value: object) -> float | None:
    try:
        text = str(value or "").strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _mean_or_none(values: list[float]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return float(sum(cleaned) / len(cleaned))


def _aggregate_game_odds_from_market_rows(
    group_rows: list[dict[str, object]], *, home_name: str, away_name: str
) -> dict[str, float | None]:
    home_ml_values: list[float] = []
    away_ml_values: list[float] = []
    home_spread_values: list[float] = []
    away_spread_values: list[float] = []
    total_values: list[float] = []

    for current in group_rows:
        market = str(current.get("market") or "").strip().lower()
        outcome_name = str(current.get("outcome_name") or "").strip()
        point_value = _float_or_none(current.get("point"))
        price_value = _float_or_none(current.get("price"))
        if market == "h2h":
            if outcome_name == home_name and price_value is not None:
                home_ml_values.append(price_value)
            elif outcome_name == away_name and price_value is not None:
                away_ml_values.append(price_value)
        elif market == "spreads" and point_value is not None:
            if outcome_name == home_name:
                home_spread_values.append(point_value)
            elif outcome_name == away_name:
                away_spread_values.append(point_value)
        elif market == "totals" and point_value is not None:
            total_values.append(point_value)

    home_spread = _mean_or_none(home_spread_values)
    away_spread = _mean_or_none(away_spread_values)
    if home_spread is None and away_spread is not None:
        home_spread = -float(away_spread)
    if away_spread is None and home_spread is not None:
        away_spread = -float(home_spread)

    return {
        "home_ml": _mean_or_none(home_ml_values),
        "away_ml": _mean_or_none(away_ml_values),
        "home_spread": home_spread,
        "away_spread": away_spread,
        "total": _mean_or_none(total_values),
    }


def _structured_literal_or_none(value: object) -> object | None:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    try:
        return ast.literal_eval(text)
    except Exception:
        return None


def _american_price_to_prob(value: object) -> float | None:
    number = _float_or_none(value)
    if number is None or number == 0:
        return None
    if number > 0:
        return 100.0 / (number + 100.0)
    return abs(number) / (abs(number) + 100.0)


def _clamp_probability(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _format_signed_line(value: float | None) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:+.1f}"


def _format_plain_line(value: float | None) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number:.1f}"


def _local_props_tier(ev_pct: float | None) -> str:
    if ev_pct is None:
        return "Low"
    if ev_pct >= 8.0:
        return "High"
    if ev_pct >= 4.0:
        return "Medium"
    return "Low"


def _read_game_cards_csv_rows(path: Path) -> list[dict[str, str]]:
    # game_cards.csv is written through the keyvalue-aware writer above (this
    # process's own write, in the same run, when force-refreshing), so read
    # it back the same way rather than assuming it landed on local disk.
    text = _keyvalue_read_text_file(path)
    if text is None:
        if not path.exists() or not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            return []
    if not text or not text.strip():
        return []
    try:
        return [dict(row) for row in csv.DictReader(io.StringIO(text))]
    except Exception:
        return []


def _local_game_cards_index(*, processed_root: Path, date_str: str) -> tuple[list[dict[str, str]], dict[str, dict[str, str]], dict[tuple[str, str], dict[str, str]]]:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    game_cards_csv_rows = _read_game_cards_csv_rows(game_cards_path)
    if not game_cards_csv_rows:
        schedule_path = processed_root / f"schedule_{date_str[:4]}.csv"
        if not schedule_path.exists() or not schedule_path.is_file() or _count_csv_rows_quick(schedule_path) <= 0:
            return [], {}, {}

        rows: list[dict[str, str]] = []
        by_team: dict[str, dict[str, str]] = {}
        by_names: dict[tuple[str, str], dict[str, str]] = {}
        with schedule_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                if str(row.get("date_utc") or "").strip() != date_str:
                    continue
                home_name = str(row.get("home_name") or "").strip()
                away_name = str(row.get("away_name") or "").strip()
                home_tri = str(row.get("home_tricode") or "").strip().upper()
                away_tri = str(row.get("away_tricode") or "").strip().upper()
                if not home_name or not away_name or not home_tri or not away_tri:
                    continue
                normalized = {
                    "date": date_str,
                    "game_id": str(row.get("game_id") or "").strip(),
                    "home_team": home_name,
                    "visitor_team": away_name,
                    "commence_time": str(row.get("time_est") or row.get("time_utc") or "").strip(),
                    "home_tri": home_tri,
                    "away_tri": away_tri,
                }
                rows.append(normalized)
                by_team[home_tri] = {
                    "side": "home",
                    "opponent": away_tri,
                    "home_tri": home_tri,
                    "away_tri": away_tri,
                    "home_team": home_name,
                    "away_team": away_name,
                    "game_id": normalized.get("game_id", ""),
                }
                by_team[away_tri] = {
                    "side": "away",
                    "opponent": home_tri,
                    "home_tri": home_tri,
                    "away_tri": away_tri,
                    "home_team": home_name,
                    "away_team": away_name,
                    "game_id": normalized.get("game_id", ""),
                }
                by_names[(home_name.lower(), away_name.lower())] = normalized
        return rows, by_team, by_names

    rows: list[dict[str, str]] = []
    by_team: dict[str, dict[str, str]] = {}
    by_names: dict[tuple[str, str], dict[str, str]] = {}
    for row in game_cards_csv_rows:
        if not isinstance(row, dict):
            continue
        normalized = {str(key): str(value or "").strip() for key, value in row.items()}
        home_tri = normalized.get("home_tri", "").upper()
        away_tri = normalized.get("away_tri", "").upper()
        home_team = normalized.get("home_team", "")
        away_team = normalized.get("visitor_team", "")
        if not home_tri or not away_tri:
            continue
        rows.append(normalized)
        by_team[home_tri] = {
            "side": "home",
            "opponent": away_tri,
            "home_tri": home_tri,
            "away_tri": away_tri,
            "home_team": home_team,
            "away_team": away_team,
            "game_id": normalized.get("game_id", ""),
        }
        by_team[away_tri] = {
            "side": "away",
            "opponent": home_tri,
            "home_tri": home_tri,
            "away_tri": away_tri,
            "home_team": home_team,
            "away_team": away_team,
            "game_id": normalized.get("game_id", ""),
        }
        if home_team and away_team:
            by_names[(home_team.lower(), away_team.lower())] = normalized
    return rows, by_team, by_names


def _load_local_props_recommendations(*, processed_root: Path, date_str: str) -> list[dict[str, object]]:
    out_path = processed_root / f"props_recommendations_{date_str}.csv"
    if not out_path.exists() or not out_path.is_file() or _count_csv_rows_quick(out_path) <= 0:
        return []

    def _coerce_top_play(row: dict[str, str]) -> dict[str, object]:
        top_play = _structured_literal_or_none(row.get("top_play"))
        if isinstance(top_play, dict) and top_play:
            return top_play

        ev_pct = _float_or_none(row.get("ev_pct") or row.get("score"))
        ev_value = _float_or_none(row.get("ev"))
        if ev_value is None and ev_pct is not None:
            ev_value = float(ev_pct) / 100.0

        market_value = str(row.get("market") or row.get("stat") or "").strip().lower()
        side_value = str(row.get("side") or row.get("selection") or "").strip().upper()
        return {
            "market": market_value,
            "stat": market_value,
            "side": side_value,
            "line": _float_or_none(row.get("line")),
            "price": _float_or_none(row.get("price")),
            "edge": _float_or_none(row.get("edge")),
            "ev": ev_value,
            "ev_pct": ev_pct,
            "p_win": _float_or_none(row.get("p_win") or row.get("win_prob")),
            "proj": _float_or_none(row.get("proj") or row.get("sim_mu") or row.get("sim_mu_adjusted")),
            "book": str(row.get("book") or row.get("bookmaker") or "").strip() or None,
            "display_pick": str(row.get("display_pick") or "").strip() or None,
            "selection": str(row.get("selection") or "").strip() or None,
            "basketball_summary": str(row.get("basketball_summary") or row.get("top_play_explain") or "").strip() or None,
            "basketball_reasons": _structured_literal_or_none(row.get("top_play_reasons")) or [],
        }

    rows_out: list[dict[str, object]] = []
    with out_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not isinstance(row, dict):
                continue
            parsed = dict(row)
            parsed["model"] = _structured_literal_or_none(row.get("model")) or {}
            parsed["top_play"] = _coerce_top_play(row)
            parsed["top_play_reasons"] = _structured_literal_or_none(row.get("top_play_reasons")) or []
            parsed["top_play_explain"] = str(row.get("top_play_explain") or "").strip()
            rows_out.append(parsed)
    return rows_out


def _cards_sim_detail_has_quarter_content(path: Path | None) -> bool:
    try:
        if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
            return False
        payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        games = payload.get("games") if isinstance(payload, dict) else None
        if not isinstance(games, list):
            return False
        for row in games:
            if not isinstance(row, dict):
                continue
            sim = row.get("sim") if isinstance(row.get("sim"), dict) else {}
            quarters = sim.get("quarters") if isinstance(sim.get("quarters"), list) else []
            if any(
                isinstance(quarter, dict)
                and any(
                    quarter.get(field) is not None
                    for field in ("away_pts_mu", "home_pts_mu", "total_mean", "margin_mean", "p_home_win")
                )
                for quarter in quarters
            ):
                return True
        return False
    except Exception:
        return False


def _basketball_recent_form_fields(row: dict[str, object], *, line_value: float | None = None) -> dict[str, float]:
    sources: list[dict[str, object]] = [row]
    for key in ("top_play", "model"):
        nested = row.get(key)
        if isinstance(nested, dict):
            sources.append(nested)

    def first_numeric(*names: str) -> float | None:
        for source in sources:
            for name in names:
                value = _float_or_none(source.get(name))
                if value is not None:
                    return float(value)
        return None

    payload: dict[str, float] = {}
    scalar_fields = (
        (("basketball_last5_average", "last5_average", "last_5_average", "last5_avg"), "last5_average"),
        (("basketball_last10_average", "last10_average", "last_10_average", "last10_avg"), "last10_average"),
        (("basketball_last_game_value", "last_game_value", "last_game", "last_game_stat"), "last_game_value"),
        (("basketball_projected_minutes", "projected_minutes"), "projected_minutes"),
        (("basketball_last10_workload", "last10_workload", "last_10_workload"), "last10_workload"),
        (("basketball_last5_delta", "last5_delta_signal", "last5_delta"), "last5_delta_signal"),
        (("basketball_last10_delta", "last10_delta_signal", "last10_delta"), "last10_delta_signal"),
        (("basketball_last_game_delta", "last_game_delta_signal", "last_game_delta"), "last_game_delta_signal"),
        (("basketball_minutes_workload_delta", "workload_delta_signal", "minutes_workload_delta"), "workload_delta_signal"),
    )
    for candidate_names, output_name in scalar_fields:
        value = first_numeric(*candidate_names)
        if value is not None:
            payload[output_name] = round(float(value), 3)

    if line_value is not None and line_value > 0:
        for raw_key, delta_key in (("last5_average", "last5_delta_signal"), ("last10_average", "last10_delta_signal"), ("last_game_value", "last_game_delta_signal")):
            if delta_key in payload or raw_key not in payload:
                continue
            payload[delta_key] = round((float(payload[raw_key]) - line_value) / max(line_value, 8.0), 3)

    if "workload_delta_signal" not in payload and "projected_minutes" in payload and "last10_workload" in payload:
        payload["workload_delta_signal"] = round(
            (float(payload["projected_minutes"]) - float(payload["last10_workload"])) / max(float(payload["last10_workload"]), 12.0),
            3,
        )
    return payload


def _build_local_recommendations_slate_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    rows, _, by_names = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    recommendations_path = processed_root / f"recommendations_{date_str}.csv"

    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    if recommendations_path.exists() and recommendations_path.is_file() and _count_csv_rows_quick(recommendations_path) > 0:
        with recommendations_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                home_name = str(row.get("home") or "").strip()
                away_name = str(row.get("away") or "").strip()
                game_row = by_names.get((home_name.lower(), away_name.lower()))
                if game_row is None:
                    continue
                home_tri = str(game_row.get("home_tri") or "").strip().upper()
                away_tri = str(game_row.get("away_tri") or "").strip().upper()
                market = str(row.get("market") or "").strip().upper()
                side = str(row.get("side") or "").strip() or market
                line = _float_or_none(row.get("line"))
                price = _float_or_none(row.get("price"))
                ev = _float_or_none(row.get("ev"))
                implied_prob = _float_or_none(row.get("implied_prob"))
                edge = _float_or_none(row.get("edge"))
                pred_margin = _float_or_none(row.get("pred_margin"))
                pred_total = _float_or_none(row.get("pred_total"))
                market_home_margin = _float_or_none(row.get("market_home_margin"))
                ev_pct = (ev * 100.0) if ev is not None else None
                win_prob = _clamp_probability((implied_prob or 0.5) + (ev or 0.0))

                if market == "ATS":
                    side_is_home = side.lower() == home_name.lower()
                    signed_line = market_home_margin if market_home_margin is not None and side_is_home else (
                        (-market_home_margin) if market_home_margin is not None else (-abs(line) if side_is_home and line is not None else abs(line) if line is not None else None)
                    )
                    display_pick = f"{side} {_format_signed_line(signed_line)}".strip()
                    summary = f"Model margin {_format_plain_line(pred_margin)} vs market {_format_signed_line(signed_line)}"
                    team_label = side
                else:
                    display_pick = f"{side} {_format_plain_line(line)}".strip()
                    summary = f"Model total {_format_plain_line(pred_total)} vs line {_format_plain_line(line)}"
                    team_label = "Total"

                grouped.setdefault((home_tri, away_tri), []).append(
                    {
                        "market": market,
                        "team": team_label,
                        "display_pick": display_pick,
                        "selection": side,
                        "price": price,
                        "score": edge if edge is not None else ev_pct,
                        "ev_pct": ev_pct,
                        "win_prob": win_prob,
                        "p_win": win_prob,
                        "basketball_summary": summary,
                        "top_play_reasons": [
                            bit
                            for bit in [
                                f"Edge {_format_plain_line(edge)}" if edge is not None else "",
                                f"EV {ev_pct:.1f}%" if ev_pct is not None else "",
                            ]
                            if bit
                        ],
                        "matchup": f"{away_tri} @ {home_tri}",
                    }
                )

    _, by_team, _ = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    prop_rows = _load_local_props_recommendations(processed_root=processed_root, date_str=date_str)
    per_game_prop_counts: dict[tuple[str, str], int] = {}
    for row in prop_rows:
        team_tri = str(row.get("team") or "").strip().upper()
        game_meta = by_team.get(team_tri)
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        if game_meta is None or not top_play:
            continue
        home_tri = str(game_meta.get("home_tri") or "").strip().upper()
        away_tri = str(game_meta.get("away_tri") or "").strip().upper()
        game_key = (home_tri, away_tri)
        if per_game_prop_counts.get(game_key, 0) >= 3:
            continue

        player_name = str(row.get("player") or "").strip()
        stat = str(top_play.get("stat") or "").strip().lower()
        line_value = _float_or_none(top_play.get("line"))
        side = str(top_play.get("side") or "").strip().upper() or "OVER"
        ev_pct = _float_or_none(top_play.get("ev_pct"))
        win_prob = _clamp_probability(_float_or_none(top_play.get("p_win")) or _american_price_to_prob(top_play.get("price")) or 0.5)
        selection = f"{side} {_format_plain_line(line_value)}".strip()
        stat_label = stat.replace("_", " ").title() if stat else "Prop"
        display_pick = f"{player_name} {selection}".strip()
        summary = f"{stat_label} projection {_format_plain_line(_float_or_none(top_play.get('proj')))}"
        recent_form_fields = _basketball_recent_form_fields(row, line_value=line_value)
        projection_value = _float_or_none(top_play.get("proj"))
        if projection_value is None:
            projection_value = _float_or_none(row.get("top_play_baseline"))
        if projection_value is None:
            model = row.get("model") if isinstance(row.get("model"), dict) else {}
            if stat:
                projection_value = _float_or_none(model.get(stat))

        grouped_pick = {
            "market": "PROPS",
            "team": team_tri,
            "display_pick": display_pick,
            "selection": selection,
            "projection": projection_value,
            "projected": projection_value,
            "odds": _float_or_none(top_play.get("price")),
            "price": _float_or_none(top_play.get("price")),
            "score": ev_pct,
            "ev_pct": ev_pct,
            "win_prob": win_prob,
            "p_win": win_prob,
            "basketball_summary": summary,
            "top_play_reasons": row.get("top_play_reasons") if isinstance(row.get("top_play_reasons"), list) else [],
            "matchup": f"{away_tri} @ {home_tri}",
        }
        grouped_pick.update(recent_form_fields)
        grouped.setdefault(game_key, []).append(grouped_pick)
        per_game_prop_counts[game_key] = int(per_game_prop_counts.get(game_key, 0) + 1)

    per_game: list[dict[str, object]] = []
    picks_count = 0
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        picks = grouped.get((home_tri, away_tri), [])
        if picks:
            picks.sort(key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
            picks_count += len(picks)
        per_game.append({"home": home_tri, "away": away_tri, "matchup": f"{away_tri} @ {home_tri}", "picks": picks})

    payload = {"date": date_str, "counts": {"games": len(per_game), "picks": picks_count}, "per_game": per_game}
    out_path = processed_root / f"recommendations_slate_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return len(per_game), out_path


def _build_local_top_by_game_snapshot(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    _, by_team, _ = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    prop_rows = _load_local_props_recommendations(processed_root=processed_root, date_str=date_str)
    if not by_team or not prop_rows:
        return 0, None

    rows_out: list[dict[str, object]] = []
    per_game_counts: dict[str, int] = {}
    ordered = sorted(
        prop_rows,
        key=lambda row: float((((row.get("top_play") or {}) if isinstance(row.get("top_play"), dict) else {}).get("ev_pct") or float("-inf"))),
        reverse=True,
    )
    for row in ordered:
        team_tri = str(row.get("team") or "").strip().upper()
        meta = by_team.get(team_tri)
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        if meta is None or not top_play:
            continue
        home_tri = str(meta.get("home_tri") or "").strip().upper()
        away_tri = str(meta.get("away_tri") or "").strip().upper()
        game_key = f"{away_tri}@{home_tri}"
        if per_game_counts.get(game_key, 0) >= 3:
            continue
        ev_pct = _float_or_none(top_play.get("ev_pct"))
        win_prob = _clamp_probability((_american_price_to_prob(top_play.get("price")) or 0.5) + (_float_or_none(top_play.get("ev")) or 0.0))
        enriched_top_play = dict(top_play)
        enriched_top_play.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        enriched_top_play["p_win"] = win_prob
        enriched_top_play["snapshot_ts"] = None
        row_out = {
            "game_key": game_key,
            "game_id": meta.get("game_id"),
            "player": str(row.get("player") or "").strip(),
            "team": team_tri,
            "team_tricode": team_tri,
            "opponent": str(meta.get("opponent") or "").strip().upper(),
            "score": ev_pct,
            "score_adj": ev_pct,
            "tier": _local_props_tier(ev_pct),
            "model": row.get("model") if isinstance(row.get("model"), dict) else {},
            "top_play": enriched_top_play,
            "top_play_reasons": row.get("top_play_reasons") if isinstance(row.get("top_play_reasons"), list) else [],
            "basketball_summary": str(row.get("top_play_explain") or "").strip() or None,
        }
        row_out.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        rows_out.append(row_out)
        per_game_counts[game_key] = int(per_game_counts.get(game_key, 0) + 1)
        if len(rows_out) >= 25:
            break

    if not rows_out:
        return 0, None

    out_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"date": date_str, "data": rows_out}, indent=2), encoding="utf-8")
    return len(rows_out), out_path


def _build_local_cards_props_snapshot_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    rows, by_team, _ = _local_game_cards_index(processed_root=processed_root, date_str=date_str)
    prop_rows = _load_local_props_recommendations(processed_root=processed_root, date_str=date_str)
    if not rows or not by_team:
        return 0, None

    grouped: dict[tuple[str, str], dict[str, list[dict[str, object]]]] = {}
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        grouped[(home_tri, away_tri)] = {"home": [], "away": []}

    for row in prop_rows:
        team_tri = str(row.get("team") or "").strip().upper()
        meta = by_team.get(team_tri)
        top_play = row.get("top_play") if isinstance(row.get("top_play"), dict) else {}
        if meta is None or not top_play:
            continue
        home_tri = str(meta.get("home_tri") or "").strip().upper()
        away_tri = str(meta.get("away_tri") or "").strip().upper()
        if (home_tri, away_tri) not in grouped:
            continue
        ev_pct = _float_or_none(top_play.get("ev_pct"))
        win_prob = _clamp_probability((_american_price_to_prob(top_play.get("price")) or 0.5) + (_float_or_none(top_play.get("ev")) or 0.0))
        base_pick = dict(top_play)
        base_pick.update(_basketball_recent_form_fields(row, line_value=_float_or_none(top_play.get("line"))))
        base_pick["player"] = str(row.get("player") or "").strip()
        base_pick["team"] = team_tri
        base_pick["opponent"] = str(meta.get("opponent") or "").strip().upper()
        base_pick["p_win"] = win_prob
        base_pick["tier"] = _local_props_tier(ev_pct)
        base_pick["score"] = ev_pct
        base_pick["recommendation_priority_score"] = ev_pct
        base_pick["basketball_priority_score"] = ev_pct
        base_pick["basketball_summary"] = str(row.get("top_play_explain") or "").strip() or None
        pick_row = dict(base_pick)
        pick_row["picks"] = [dict(base_pick)]
        pick_row["best"] = dict(base_pick)
        grouped[(home_tri, away_tri)][str(meta.get("side") or "away")].append(pick_row)

    games_out: list[dict[str, object]] = []
    for game_row in rows:
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        current = grouped.get((home_tri, away_tri), {"home": [], "away": []})
        home_rows = sorted(current.get("home") or [], key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
        away_rows = sorted(current.get("away") or [], key=lambda item: float(item.get("ev_pct") or float("-inf")), reverse=True)
        if not home_rows and not away_rows:
            continue
        games_out.append({"home_tri": home_tri, "away_tri": away_tri, "game_id": game_row.get("game_id"), "prop_recommendations": {"home": home_rows, "away": away_rows}})

    out_path = processed_root / f"cards_props_snapshot_{date_str}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"date": date_str, "games": games_out}, indent=2), encoding="utf-8")
    return len(games_out), out_path


_GAME_CARDS_HEADER_ORDER = [
    "date",
    "game_id",
    "home_team",
    "visitor_team",
    "commence_time",
    "home_ml",
    "away_ml",
    "home_spread",
    "away_spread",
    "total",
    "bookmaker",
    "home_tri",
    "away_tri",
]


def _write_game_cards_csv_rows(out_path: Path, rows_out: list[dict[str, object]]) -> None:
    # game_cards.csv is read cross-service (the live-lens background loop on
    # the live-odds-worker service needs the same data the web service just
    # wrote), so this goes through the keyvalue-aware writer rather than a
    # plain local file write -- each Render service has its own separate
    # local disk, so a plain write here would be invisible to any other
    # service reading the same nominal path.
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_GAME_CARDS_HEADER_ORDER)
    writer.writeheader()
    for current in rows_out:
        writer.writerow({field: current.get(field, "") for field in _GAME_CARDS_HEADER_ORDER})
    _keyvalue_write_text_file(out_path, buffer.getvalue())


def _build_local_game_cards_artifact(*, source_root: Path, processed_root: Path, date_str: str, log_file: Path | None = None) -> tuple[int, Path | None]:
    out_path = processed_root / f"game_cards_{date_str}.csv"

    def _log(message: str) -> None:
        if log_file is not None:
            _append_log(log_file, message)

    def _prediction_matchups() -> set[tuple[str, str]]:
        predictions_path = processed_root / f"predictions_{date_str}.csv"
        if not predictions_path.exists() or not predictions_path.is_file() or _count_csv_rows_quick(predictions_path) <= 0:
            return set()

        matchups: set[tuple[str, str]] = set()
        try:
            with predictions_path.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if not isinstance(row, dict):
                        continue
                    home_name = str(row.get("home_team") or "").strip().casefold()
                    away_name = str(row.get("visitor_team") or row.get("away_team") or "").strip().casefold()
                    if home_name and away_name:
                        matchups.add((home_name, away_name))
        except Exception:
            return set()
        return matchups

    def _game_card_date_prefixes() -> tuple[str, str]:
        try:
            game_date = dt.date.fromisoformat(date_str)
        except Exception:
            return (date_str, date_str)
        return (date_str, (game_date + dt.timedelta(days=1)).isoformat())

    expected_matchups = _prediction_matchups()
    snapshot_matchups: set[tuple[str, str]] = set()
    odds_by_matchup = _load_game_odds_rows_by_matchup(source_root=source_root, processed_root=processed_root, date_str=date_str)

    raw_candidates = [
        source_root / "data" / "raw" / f"odds_wnba_current_{date_str}.csv",
        source_root / "data" / "raw" / f"odds_wnba_current_{date_str}.parquet",
    ]
    raw_path = next((path for path in raw_candidates if path.exists() and path.is_file()), None)
    if raw_path is None:
        props_snapshot_path = source_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv"
        if props_snapshot_path.exists() and props_snapshot_path.is_file() and _count_csv_rows_quick(props_snapshot_path) > 0:
            try:
                import pandas as pd

                props_frame = pd.read_csv(props_snapshot_path)
                _log_frame_memory("wnba_props_snapshot_read", props_frame, path=str(props_snapshot_path))
            except Exception as exc:
                _append_log(log_file, f"Failed to read raw player props snapshot {props_snapshot_path}: {exc}")
                props_frame = pd.DataFrame()

            required_columns = {"event_id", "commence_time", "home_team", "away_team"}
            if not props_frame.empty and required_columns.issubset(set(str(column) for column in props_frame.columns)):
                working = props_frame.copy()
                _log_frame_memory("wnba_props_snapshot_copied", working, path=str(props_snapshot_path))
                working["commence_time"] = working["commence_time"].astype(str)
                working = working[working["commence_time"].str.startswith(_game_card_date_prefixes())].copy()
                _log_frame_memory("wnba_props_snapshot_filtered", working, path=str(props_snapshot_path))
                if not working.empty:
                    rows_out: list[dict[str, object]] = []
                    grouped = working.groupby(["event_id", "commence_time", "home_team", "away_team"], dropna=False, sort=True)
                    for (event_id, commence_time, home_team, away_team), group in grouped:
                        home_name = str(home_team or "").strip()
                        away_name = str(away_team or "").strip()
                        if not home_name or not away_name:
                            continue
                        snapshot_matchups.add((home_name.casefold(), away_name.casefold()))
                        home_tri = _canonical_wnba_tri(_to_tricode_local(home_name))
                        away_tri = _canonical_wnba_tri(_to_tricode_local(away_name))
                        odds_row = odds_by_matchup.get((home_tri, away_tri)) if home_tri and away_tri else None
                        # The processed game_odds file usually only has a matchup
                        # skeleton (no prices) -- fall back to aggregating the raw
                        # h2h/spreads/totals rows already present in this snapshot
                        # group whenever the game_odds lookup has nothing usable.
                        aggregated = _aggregate_game_odds_from_market_rows(
                            group.to_dict("records"), home_name=home_name, away_name=away_name
                        )
                        home_ml = _float_or_none((odds_row or {}).get("home_ml"))
                        away_ml = _float_or_none((odds_row or {}).get("away_ml"))
                        home_spread = _float_or_none((odds_row or {}).get("home_spread"))
                        away_spread = _float_or_none((odds_row or {}).get("away_spread"))
                        total = _float_or_none((odds_row or {}).get("total"))
                        rows_out.append(
                            {
                                "date": date_str,
                                "game_id": f"0{str(event_id or '').strip()}" if str(event_id or '').strip() else "",
                                "home_team": home_name,
                                "visitor_team": away_name,
                                "commence_time": str(commence_time or "").strip(),
                                "home_ml": home_ml if home_ml is not None else aggregated["home_ml"],
                                "away_ml": away_ml if away_ml is not None else aggregated["away_ml"],
                                "home_spread": home_spread if home_spread is not None else aggregated["home_spread"],
                                "away_spread": away_spread if away_spread is not None else aggregated["away_spread"],
                                "total": total if total is not None else aggregated["total"],
                                "bookmaker": str((odds_row or {}).get("bookmaker") or "oddsapi_consensus").strip() or "oddsapi_consensus",
                                "home_tri": home_tri,
                                "away_tri": away_tri,
                            }
                        )

                    if rows_out and (not expected_matchups or expected_matchups.issubset(snapshot_matchups)):
                        _write_game_cards_csv_rows(out_path, rows_out)
                        _log(f"Built local game_cards from raw player props snapshot fallback: {out_path} (rows={len(rows_out)})")
                        return len(rows_out), out_path

                    if rows_out and expected_matchups and not expected_matchups.issubset(snapshot_matchups):
                        missing_matchups = sorted(expected_matchups.difference(snapshot_matchups))
                        missing_text = ", ".join(f"{away.upper()} @ {home.upper()}" for home, away in missing_matchups)
                        _log(
                            f"Raw player props snapshot only covered {len(snapshot_matchups)} of {len(expected_matchups)} predicted games for {date_str}; missing={missing_text}; falling back to processed game_odds"
                        )

        # Fallback to processed game_odds when raw team odds snapshots are unavailable.
        game_odds_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
        if not game_odds_path.exists() or not game_odds_path.is_file() or _count_csv_rows_quick(game_odds_path) <= 0:
            _log(f"Local game_cards build skipped for {date_str}: no raw team odds snapshot found")
            return 0, None

        allowed_matchups: set[tuple[str, str]] = set()
        props_market_rows_by_matchup: dict[tuple[str, str], list[dict[str, object]]] = {}
        props_snapshot_path = source_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv"
        if props_snapshot_path.exists() and props_snapshot_path.is_file() and _count_csv_rows_quick(props_snapshot_path) > 0:
            try:
                with props_snapshot_path.open("r", encoding="utf-8", newline="") as props_handle:
                    props_reader = csv.DictReader(props_handle)
                    for props_row in props_reader:
                        if not isinstance(props_row, dict):
                            continue
                        props_home = str(props_row.get("home_team") or "").strip().casefold()
                        props_away = str(props_row.get("away_team") or "").strip().casefold()
                        if not props_home or not props_away:
                            continue
                        if not expected_matchups or expected_matchups.issubset(snapshot_matchups):
                            allowed_matchups.add((props_home, props_away))
                        props_market_rows_by_matchup.setdefault((props_home, props_away), []).append(props_row)
            except Exception:
                allowed_matchups = set()
                props_market_rows_by_matchup = {}

        rows_out: list[dict[str, object]] = []
        with game_odds_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader, start=1):
                if not isinstance(row, dict):
                    continue
                home_name = str(row.get("home_team") or "").strip()
                away_name = str(row.get("visitor_team") or row.get("away_team") or "").strip()
                if not home_name or not away_name:
                    continue
                if allowed_matchups and (home_name.casefold(), away_name.casefold()) not in allowed_matchups:
                    continue
                # game_odds_{date}.csv is frequently only ever seeded with a bare
                # matchup skeleton (no prices) -- fall back to aggregating the raw
                # h2h/spreads/totals rows from the props snapshot for this matchup
                # whenever the game_odds row itself has nothing usable.
                home_ml = _float_or_none(row.get("home_ml"))
                away_ml = _float_or_none(row.get("away_ml"))
                home_spread = _float_or_none(row.get("home_spread"))
                away_spread = _float_or_none(row.get("away_spread"))
                total = _float_or_none(row.get("total"))
                if None in (home_ml, away_ml, home_spread, away_spread, total):
                    market_rows = props_market_rows_by_matchup.get((home_name.casefold(), away_name.casefold())) or []
                    if market_rows:
                        aggregated = _aggregate_game_odds_from_market_rows(
                            market_rows, home_name=home_name, away_name=away_name
                        )
                        home_ml = home_ml if home_ml is not None else aggregated["home_ml"]
                        away_ml = away_ml if away_ml is not None else aggregated["away_ml"]
                        home_spread = home_spread if home_spread is not None else aggregated["home_spread"]
                        away_spread = away_spread if away_spread is not None else aggregated["away_spread"]
                        total = total if total is not None else aggregated["total"]
                rows_out.append(
                    {
                        "date": date_str,
                        "game_id": str(row.get("game_id") or idx),
                        "home_team": home_name,
                        "visitor_team": away_name,
                        "commence_time": str(row.get("commence_time") or "").strip(),
                        "home_ml": home_ml,
                        "away_ml": away_ml,
                        "home_spread": home_spread,
                        "away_spread": away_spread,
                        "total": total,
                        "bookmaker": str(row.get("bookmaker") or "oddsapi_consensus").strip() or "oddsapi_consensus",
                        "home_tri": _to_tricode_local(home_name),
                        "away_tri": _to_tricode_local(away_name),
                    }
                )

        if not rows_out:
            if out_path.exists() and out_path.is_file():
                out_path.unlink()
            _log(f"Local game_cards build skipped for {date_str}: processed game_odds had no usable rows")
            return 0, None

        _write_game_cards_csv_rows(out_path, rows_out)
        _append_log(log_file, f"Built local game_cards from game_odds fallback: {out_path} (rows={len(rows_out)})")
        return len(rows_out), out_path

    try:
        import pandas as pd

        if raw_path.suffix.lower() == ".parquet":
            raw_frame = pd.read_parquet(raw_path)
        else:
            raw_frame = pd.read_csv(raw_path)
        _log_frame_memory("wnba_game_cards_raw_read", raw_frame, path=str(raw_path))
    except Exception as exc:
        _log(f"Failed to read raw team odds snapshot {raw_path}: {exc}")
        return 0, None

    if raw_frame.empty:
        return 0, None

    required_columns = {"event_id", "commence_time", "market", "outcome_name", "point", "price", "home_team", "away_team"}
    if not required_columns.issubset(set(str(column) for column in raw_frame.columns)):
        _log(f"Local game_cards build skipped for {date_str}: raw team odds snapshot missing required columns")
        return 0, None

    working = raw_frame.copy()
    _log_frame_memory("wnba_game_cards_copied", working, path=str(raw_path))
    working["commence_time"] = working["commence_time"].astype(str)
    working = working[working["commence_time"].str.startswith(_game_card_date_prefixes())].copy()
    _log_frame_memory("wnba_game_cards_filtered", working, path=str(raw_path))
    if working.empty:
        return 0, None

    rows_out: list[dict[str, object]] = []
    grouped = working.groupby(["event_id", "commence_time", "home_team", "away_team"], dropna=False, sort=True)
    for (event_id, commence_time, home_team, away_team), group in grouped:
        home_name = str(home_team or "").strip()
        away_name = str(away_team or "").strip()
        if not home_name or not away_name:
            continue

        group_rows = group.to_dict("records")
        aggregated = _aggregate_game_odds_from_market_rows(group_rows, home_name=home_name, away_name=away_name)

        rows_out.append(
            {
                "date": date_str,
                "game_id": f"0{str(event_id or '').strip()}" if str(event_id or "").strip() else "",
                "home_team": home_name,
                "visitor_team": away_name,
                "commence_time": str(commence_time or "").strip(),
                "home_ml": aggregated["home_ml"],
                "away_ml": aggregated["away_ml"],
                "home_spread": aggregated["home_spread"],
                "away_spread": aggregated["away_spread"],
                "total": aggregated["total"],
                "bookmaker": "oddsapi_consensus",
                "home_tri": _to_tricode_local(home_name),
                "away_tri": _to_tricode_local(away_name),
            }
        )

    if not rows_out:
        return 0, None

    _write_game_cards_csv_rows(out_path, rows_out)
    return len(rows_out), out_path


def _smart_sim_projection_index(*, processed_root: Path, date_str: str) -> dict[tuple[str, str], dict[str, float]]:
    index: dict[tuple[str, str], dict[str, float]] = {}
    for path in sorted(processed_root.glob(f"smart_sim_{date_str}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        home = str(payload.get("home") or "").strip().upper()
        away = str(payload.get("away") or "").strip().upper()
        quarters = payload.get("quarters") if isinstance(payload.get("quarters"), list) else []
        if not quarters:
            periods_payload = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
            for quarter_number in range(1, 5):
                quarter_payload = periods_payload.get(f"q{quarter_number}") if isinstance(periods_payload.get(f"q{quarter_number}"), dict) else None
                if not isinstance(quarter_payload, dict):
                    continue
                quarters.append(
                    {
                        "home_pts_mu": quarter_payload.get("home_mean"),
                        "away_pts_mu": quarter_payload.get("away_mean"),
                    }
                )
        if not home or not away or not quarters:
            continue
        home_total = 0.0
        away_total = 0.0
        for quarter in quarters:
            if not isinstance(quarter, dict):
                continue
            home_total += float(_float_or_none(quarter.get("home_pts_mu")) or 0.0)
            away_total += float(_float_or_none(quarter.get("away_pts_mu")) or 0.0)
        if home_total <= 0 and away_total <= 0:
            continue
        index[(home, away)] = {
            "pred_margin": home_total - away_total,
            "pred_total": home_total + away_total,
        }
    return index


def _build_local_live_lens_signals_artifact(*, processed_root: Path, date_str: str, live_lens_root: Path) -> dict[str, str]:
    try:
        from syndicate.features.wnba.cards import build_live_lens_tuning_payload

        tuning_payload = build_live_lens_tuning_payload()
    except Exception:
        tuning_payload = {}

    total_market = tuning_payload.get("markets", {}).get("total", {}) if isinstance(tuning_payload, dict) else {}
    watch_threshold = float(_float_or_none(total_market.get("watch")) or 3.0)
    bet_threshold = float(_float_or_none(total_market.get("bet")) or 6.0)

    projections = _smart_sim_projection_index(processed_root=processed_root, date_str=date_str)
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not projections or not game_cards_path.exists() or not game_cards_path.is_file():
        return {}

    rows_out: list[dict[str, object]] = []
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            projection = projections.get((home_tri, away_tri))
            total_line = _float_or_none(row.get("total"))
            if projection is None or total_line is None:
                continue
            pred_total = _float_or_none(projection.get("pred_total"))
            if pred_total is None:
                continue
            edge = pred_total - total_line
            abs_edge = abs(float(edge))
            if abs_edge < watch_threshold:
                continue
            rows_out.append(
                {
                    "market": "total",
                    "klass": "BET" if abs_edge >= bet_threshold else "WATCH",
                    "game_id": str(row.get("game_id") or "").strip(),
                    "home": str(row.get("home_tri") or row.get("home_team") or "").strip().upper(),
                    "away": str(row.get("away_tri") or row.get("visitor_team") or "").strip().upper(),
                    "side": "OVER" if edge > 0 else "UNDER",
                    "live_line": round(total_line, 3),
                    "pred": round(pred_total, 3),
                    "edge": round(edge, 3),
                    "edge_adj": round(edge, 3),
                    "elapsed": 0,
                    "remaining": 40,
                    "tags": ["sim:pregame"],
                }
            )

    if not rows_out:
        return {}

    raw = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows_out).encode("utf-8")
    copied: dict[str, str] = {}
    for out_path, copied_key in (
        (processed_root / f"live_lens_signals_{date_str}.jsonl", "live_lens_signals_path"),
        (live_lens_root / f"live_lens_signals_{date_str}.jsonl", None),
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _build_local_live_lens_projections_artifact(*, processed_root: Path, date_str: str, live_lens_root: Path) -> dict[str, str]:
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not predictions_path.exists() or not predictions_path.is_file() or not game_cards_path.exists() or not game_cards_path.is_file():
        return {}

    game_lookup: dict[tuple[str, str], dict[str, str]] = {}
    pair_lookup: dict[tuple[str, str], dict[str, str]] = {}
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            if not home_tri or not away_tri:
                continue
            payload = {
                "game_id": str(row.get("game_id") or "").strip(),
                "home": home_tri,
                "away": away_tri,
            }
            game_lookup[(home_tri, away_tri)] = payload
            pair_lookup[tuple(sorted((home_tri, away_tri)))] = payload

    line_lookup: dict[tuple[str, str, str], float] = {}
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    if edges_path.exists() and edges_path.is_file():
        with edges_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                player_name = str(row.get("player_name") or row.get("player") or "").strip()
                team_tri = str(row.get("team") or "").strip().upper()
                stat_key = str(row.get("stat") or row.get("market") or "").strip().lower()
                line_value = _float_or_none(row.get("line"))
                if not player_name or not team_tri or not stat_key or line_value is None:
                    continue
                line_lookup.setdefault((player_name.upper(), team_tri, stat_key), float(line_value))

    stat_columns = (
        ("pts", "pred_pts", "mean_pts"),
        ("reb", "pred_reb", "mean_reb"),
        ("ast", "pred_ast", "mean_ast"),
        ("threes", "pred_threes", "mean_threes"),
        ("stl", "pred_stl", "mean_stl"),
        ("blk", "pred_blk", "mean_blk"),
        ("tov", "pred_tov", "mean_tov"),
        ("pra", "pred_pra", "mean_pra"),
    )
    rows_out: list[dict[str, object]] = []
    with predictions_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            player_name = str(row.get("player_name") or row.get("player") or "").strip()
            team_tri = str(row.get("team") or "").strip().upper()
            opponent_tri = str(row.get("opponent") or "").strip().upper()
            if not player_name or not team_tri:
                continue

            matchup = None
            if team_tri and opponent_tri:
                matchup = game_lookup.get((team_tri, opponent_tri)) or game_lookup.get((opponent_tri, team_tri)) or pair_lookup.get(tuple(sorted((team_tri, opponent_tri))))
            if matchup is None:
                continue

            line_name_key = player_name.upper()
            for stat_key, proj_col, sim_col in stat_columns:
                proj = _float_or_none(row.get(proj_col))
                sim_mu = _float_or_none(row.get(sim_col))
                if proj is None and sim_mu is None:
                    continue
                if proj is None:
                    proj = sim_mu
                if sim_mu is None:
                    sim_mu = proj
                line_value = line_lookup.get((line_name_key, team_tri, stat_key))
                context: dict[str, object] = {
                    "pregame_team_total_ratio": 1.0,
                    "pregame_game_total_ratio": 1.0,
                }
                if line_value is not None and sim_mu is not None:
                    context["sim_vs_line"] = round(float(sim_mu) - float(line_value), 3)
                    context["sim_vs_line_adjusted"] = round(float(sim_mu) - float(line_value), 3)
                rows_out.append(
                    {
                        "market": "player_prop",
                        "game_id": matchup.get("game_id"),
                        "home": matchup.get("home"),
                        "away": matchup.get("away"),
                        "player": player_name,
                        "name_key": player_name,
                        "team_tri": team_tri,
                        "stat": stat_key,
                        "line": line_value,
                        "proj": round(float(proj), 3) if proj is not None else None,
                        "proj_original": round(float(proj), 3) if proj is not None else None,
                        "sim_mu": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "sim_mu_adjusted": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "sim_mu_adjusted_original": round(float(sim_mu), 3) if sim_mu is not None else None,
                        "elapsed": 0,
                        "strength": abs(float(sim_mu) - float(line_value)) if (sim_mu is not None and line_value is not None) else None,
                        "context": context,
                    }
                )

    if not rows_out:
        return {}

    raw = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows_out).encode("utf-8")
    copied: dict[str, str] = {}
    for out_path, copied_key in (
        (processed_root / f"live_lens_projections_{date_str}.jsonl", "live_lens_projections_path"),
        (live_lens_root / f"live_lens_projections_{date_str}.jsonl", None),
    ):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        if copied_key:
            copied[copied_key] = str(out_path)
    return copied


def _build_local_game_recommendations_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    if not game_cards_path.exists() or not game_cards_path.is_file() or _count_csv_rows_quick(game_cards_path) <= 0:
        return 0, None
    sim_index = _smart_sim_projection_index(processed_root=processed_root, date_str=date_str)
    if not sim_index:
        return 0, None

    rows: list[dict[str, object]] = []
    implied_prob = 110.0 / 210.0
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            home_tri = str(row.get("home_tri") or "").strip().upper()
            away_tri = str(row.get("away_tri") or "").strip().upper()
            projection = sim_index.get((home_tri, away_tri))
            if projection is None:
                continue
            home_name = str(row.get("home_team") or home_tri).strip() or home_tri
            away_name = str(row.get("visitor_team") or away_tri).strip() or away_tri
            pred_margin = float(projection.get("pred_margin") or 0.0)
            pred_total = float(projection.get("pred_total") or 0.0)
            market_home_margin = _float_or_none(row.get("home_spread"))
            if market_home_margin is None:
                away_spread = _float_or_none(row.get("away_spread"))
                if away_spread is not None:
                    market_home_margin = -away_spread
            total_line = _float_or_none(row.get("total"))

            if market_home_margin is not None:
                cover_edge = pred_margin - market_home_margin
                pick_home = cover_edge >= 0
                edge_value = abs(cover_edge)
                ev_value = edge_value / 100.0
                rows.append(
                    {
                        "market": "ATS",
                        "side": home_name if pick_home else away_name,
                        "home": home_name,
                        "away": away_name,
                        "date": date_str,
                        "ev": round(ev_value, 6),
                        "price": -110.0,
                        "implied_prob": round(implied_prob, 6),
                        "edge": round(edge_value, 6),
                        "line": round(abs(market_home_margin), 6),
                        "pred_margin": round(pred_margin if pick_home else (-pred_margin), 6),
                        "market_home_margin": round(market_home_margin, 6),
                        "pred_total": "",
                        "tier": _recommendation_tier(market="ATS", ev_value=ev_value, edge_value=edge_value),
                    }
                )

            if total_line is not None:
                total_edge = pred_total - total_line
                ev_value = abs(total_edge) / 100.0
                rows.append(
                    {
                        "market": "TOTAL",
                        "side": "Over" if total_edge >= 0 else "Under",
                        "home": home_name,
                        "away": away_name,
                        "date": date_str,
                        "ev": round(ev_value, 6),
                        "price": -110.0,
                        "implied_prob": round(implied_prob, 6),
                        "edge": round(total_edge, 6),
                        "line": round(total_line, 6),
                        "pred_margin": "",
                        "market_home_margin": "",
                        "pred_total": round(pred_total, 6),
                        "tier": _recommendation_tier(market="TOTAL", ev_value=ev_value, edge_value=total_edge),
                    }
                )

    if not rows:
        return 0, None

    out_path = processed_root / f"recommendations_{date_str}.csv"
    header_order = [
        "market",
        "side",
        "home",
        "away",
        "date",
        "ev",
        "price",
        "implied_prob",
        "edge",
        "line",
        "pred_margin",
        "market_home_margin",
        "pred_total",
        "tier",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header_order)
        writer.writeheader()
        for current in rows:
            writer.writerow({field: current.get(field, "") for field in header_order})
    return len(rows), out_path


def _seed_game_odds_from_raw_history(*, source_root: Path, date_str: str, log_file: Path) -> bool:
    processed_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
    if _path_has_meaningful_content(processed_path):
        return True

    raw_candidates = (
        source_root / "data" / "raw" / "games_nba_api.csv",
        source_root / "data" / "raw" / "games_nba_api.parquet",
    )
    raw_frame = None
    for candidate in raw_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".parquet":
                import pandas as pd

                raw_frame = pd.read_parquet(candidate)
            else:
                import pandas as pd

                raw_frame = pd.read_csv(candidate)
            break
        except Exception as exc:
            _append_log(log_file, f"Failed to read raw games history {candidate}: {exc}")
    if raw_frame is None or raw_frame.empty:
        return False

    import pandas as pd

    date_col = next((col for col in ("date", "game_date", "date_utc", "date_est") if col in raw_frame.columns), None)
    home_col = next((col for col in ("home_team", "home") if col in raw_frame.columns), None)
    away_col = next((col for col in ("visitor_team", "away_team", "away") if col in raw_frame.columns), None)
    if not date_col or not home_col or not away_col:
        return False

    day_frame = raw_frame.copy()
    day_frame[date_col] = pd.to_datetime(day_frame[date_col], errors="coerce").dt.strftime("%Y-%m-%d")
    day_frame = day_frame[day_frame[date_col] == date_str].copy()
    if day_frame.empty:
        return False

    out = day_frame[[date_col, home_col, away_col]].rename(
        columns={date_col: "date", home_col: "home_team", away_col: "visitor_team"}
    )
    out = out.dropna(subset=["home_team", "visitor_team"]).drop_duplicates().reset_index(drop=True)
    if out.empty:
        return False

    processed_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(processed_path, index=False)
    _append_log(log_file, f"Seeded fallback game odds slate from raw history: {processed_path} (rows={len(out)})")
    return True


def _seed_game_odds_from_props_snapshot(*, source_root: Path, date_str: str, log_file: Path) -> bool:
    processed_path = source_root / "data" / "processed" / f"game_odds_{date_str}.csv"
    snapshot_candidates = (
        source_root / "data" / "processed" / f"oddsapi_player_props_{date_str}.csv",
        source_root / "data" / "raw" / f"odds_wnba_player_props_{date_str}.csv",
    )
    import pandas as pd

    if _path_has_meaningful_content(processed_path):
        try:
            existing = pd.read_csv(processed_path)
        except Exception:
            existing = pd.DataFrame()

        snapshot_matchups: set[tuple[str, str]] = set()
        for candidate in snapshot_candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            try:
                candidate_frame = pd.read_csv(candidate)
            except Exception:
                continue
            if candidate_frame.empty or not {"home_team", "away_team"}.issubset(candidate_frame.columns):
                continue
            for home_name, away_name in candidate_frame[["home_team", "away_team"]].dropna().drop_duplicates().itertuples(index=False):
                home_text = str(home_name).strip().casefold()
                away_text = str(away_name).strip().casefold()
                if home_text and away_text:
                    snapshot_matchups.add((home_text, away_text))
            if snapshot_matchups:
                break

        existing_matchups: set[tuple[str, str]] = set()
        if not existing.empty and {"home_team", "visitor_team"}.issubset(existing.columns):
            for home_name, away_name in existing[["home_team", "visitor_team"]].dropna().drop_duplicates().itertuples(index=False):
                home_text = str(home_name).strip().casefold()
                away_text = str(away_name).strip().casefold()
                if home_text and away_text:
                    existing_matchups.add((home_text, away_text))

        if snapshot_matchups and existing_matchups and existing_matchups.isdisjoint(snapshot_matchups):
            _append_log(
                log_file,
                f"Replacing stale game_odds slate for {date_str}: existing matchups do not overlap props snapshot",
            )
        else:
            return True

    for candidate in snapshot_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            frame = pd.read_csv(candidate)
        except Exception as exc:
            _append_log(log_file, f"Failed to read props snapshot {candidate}: {exc}")
            continue
        if frame.empty or not {"home_team", "away_team"}.issubset(frame.columns):
            continue
        out = frame[["home_team", "away_team"]].dropna().drop_duplicates().copy()
        out = out.rename(columns={"away_team": "visitor_team"})
        out.insert(0, "date", date_str)
        if "commence_time" in frame.columns:
            times = frame[["home_team", "away_team", "commence_time"]].dropna(subset=["home_team", "away_team"]).copy()
            times = times.rename(columns={"away_team": "visitor_team"})
            times = times.drop_duplicates(subset=["home_team", "visitor_team"], keep="first")
            out = out.merge(times, on=["home_team", "visitor_team"], how="left")
        processed_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(processed_path, index=False)
        _append_log(log_file, f"Seeded fallback game odds slate from props snapshot: {processed_path} (rows={len(out)})")
        return True
    return False


def _run_source_subprocess_cli_command(
    *,
    source_root: Path,
    package_name: str,
    command_parts: list[str],
    log_file: Path,
    heartbeat_cb: callable | None,
    timeout_s: float,
) -> int:
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            *command_parts,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=timeout_s,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


def _ensure_source_game_inputs(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> dict[str, int]:
    processed_root = source_root / "data" / "processed"
    raw_root = source_root / "data" / "raw"
    raw_candidates = (
        raw_root / "games_nba_api.csv",
        raw_root / "games_nba_api.parquet",
    )
    feature_candidates = (
        processed_root / "features.csv",
        processed_root / "features.parquet",
    )

    rc_schedule = _run_source_subprocess_cli_command(
        source_root=source_root,
        package_name=package_name,
        command_parts=["fetch-schedule"],
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
        timeout_s=10 * 60,
    )

    rc_fetch = 0
    if not any(path.exists() and path.is_file() and path.stat().st_size > 0 for path in raw_candidates):
        rc_fetch = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["fetch", "--years", "10"],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=45 * 60,
        )

    rc_build_features = 0
    if not any(path.exists() and path.is_file() and path.stat().st_size > 0 for path in feature_candidates):
        rc_build_features = _run_source_subprocess_cli_command(
            source_root=source_root,
            package_name=package_name,
            command_parts=["build-features"],
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
            timeout_s=20 * 60,
        )

    _seed_game_odds_from_props_snapshot(source_root=source_root, date_str=date_str, log_file=log_file)
    _seed_game_odds_from_raw_history(source_root=source_root, date_str=date_str, log_file=log_file)

    rc_predict_date = _run_source_predict_date(
        source_root=source_root,
        package_name=package_name,
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )
    if int(rc_predict_date) != 0:
        _append_log(log_file, f"predict-date failed with exit code {int(rc_predict_date)}; retrying via CPU daily-update fallback")
        rc_predict_date = _run_source_daily_update_cpu_fallback(
            source_root=source_root,
            package_name=package_name,
            date_str=date_str,
            log_file=log_file,
            heartbeat_cb=heartbeat_cb,
        )
    return {
        "schedule": int(rc_schedule),
        "fetch": int(rc_fetch),
        "build_features": int(rc_build_features),
        "predict_date": int(rc_predict_date),
    }


def _run_source_predict_date(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> int:
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            "predict-date",
            "--date",
            date_str,
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=20 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


def _run_source_daily_update_cpu_fallback(
    *,
    source_root: Path,
    package_name: str,
    date_str: str,
    log_file: Path,
    heartbeat_cb: callable | None,
) -> int:
    return _run_to_file(
        [
            _source_python(source_root),
            "-m",
            f"{package_name}.cli",
            "daily-update",
            "--date",
            date_str,
            "--no-npu",
            "--no-git-push",
        ],
        log_file,
        cwd=source_root,
        env=_source_worker_env(source_root),
        timeout_s=45 * 60,
        heartbeat_cb=heartbeat_cb,
        heartbeat_every_s=5.0,
    )


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(str(os.environ.get(name, str(default))).strip()))
    except Exception:
        return int(default)


def _env_timeout_s(name: str, default_s: float) -> float | None:
    try:
        raw = str(os.environ.get(name, str(default_s))).strip()
        value = float(raw)
    except Exception:
        value = float(default_s)
    return None if value <= 0 else float(value)


def _run_to_file(
    args: list[str],
    log_file: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float | None,
    heartbeat_cb: callable | None,
    heartbeat_every_s: float = 15.0,
) -> int:
    cmd_text = " ".join(shlex.quote(str(a)) for a in args)
    _append_log(log_file, f"$ {cmd_text}")
    log_runtime_memory("subprocess_before_launch", command=cmd_text, cwd=str(cwd), timeout_s=timeout_s)
    start = time.time()
    last_heartbeat = start
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8", errors="ignore") as out:
        proc = subprocess.Popen(
            [str(a) for a in args],
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        log_runtime_memory("subprocess_after_launch", command=cmd_text, cwd=str(cwd), child_pid=int(proc.pid), timeout_s=timeout_s)
        while True:
            try:
                rc = int(proc.wait(timeout=1.0))
                log_runtime_memory("subprocess_after_exit", command=cmd_text, cwd=str(cwd), child_pid=int(proc.pid), return_code=rc, timeout_s=timeout_s)
                return rc
            except subprocess.TimeoutExpired:
                now = time.time()
                if heartbeat_cb and (now - last_heartbeat) >= max(1.0, float(heartbeat_every_s)):
                    try:
                        heartbeat_cb()
                    except Exception:
                        pass
                    last_heartbeat = now
                if timeout_s is not None and (now - start) >= float(timeout_s):
                    log_runtime_memory("subprocess_timeout", command=cmd_text, cwd=str(cwd), child_pid=int(proc.pid), timeout_s=timeout_s)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=5.0)
                    except Exception:
                        pass
                    _append_log(log_file, f"Command timed out after {int(timeout_s)}s")
                    return 124


def _season_year_for_date(date_str: str) -> int:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.year if parsed.month >= 7 else (parsed.year - 1)


def _season_str_from_year(season_year: int) -> str:
    return f"{season_year}-{(season_year + 1) % 100:02d}"


def _active_player_logs_paths(source_root: Path) -> list[Path]:
    return [
        source_root / "data" / "processed" / "player_logs.parquet",
        source_root / "data" / "processed" / "player_logs.csv",
    ]


def _active_player_logs_fallback_paths(source_root: Path) -> list[Path]:
    processed_root = source_root / "data" / "processed"
    paths = [
        processed_root / "boxscores_history.parquet",
        processed_root / "boxscores_history.csv",
    ]
    for pattern in ("boxscores_*.parquet", "boxscores_*.csv"):
        paths.extend(sorted(processed_root.glob(pattern)))
    return [path for path in paths if path.exists() and path.stat().st_size > 0]


def _file_is_fresh(path: Path, *, max_age_minutes: int) -> bool:
    try:
        if max_age_minutes <= 0:
            return path.exists() and path.stat().st_size > 0
        if not path.exists() or path.stat().st_size <= 0:
            return False
        age_s = max(0.0, time.time() - float(path.stat().st_mtime))
        return age_s <= (float(max_age_minutes) * 60.0)
    except Exception:
        return False


def _player_logs_ready(source_root: Path, *, max_age_minutes: int) -> bool:
    paths = _active_player_logs_paths(source_root) + _active_player_logs_fallback_paths(source_root)
    return any(_file_is_fresh(path, max_age_minutes=max_age_minutes) for path in paths)


def _bootstrap_local_boxscores_history_for_props(*, source_root: Path, date_str: str, log_file: Path) -> tuple[bool, str | None]:
    processed_root = source_root / "data" / "processed"
    try:
        from syndicate.features.shared.basketball_boxscores_history import bootstrap_boxscores_history_local

        result = bootstrap_boxscores_history_local(
            processed_root=processed_root,
            date_str=date_str,
            league_code="wnba",
            lookback_days=max(7, _env_int("REFRESH_PLAYER_LOGS_BOOTSTRAP_LOOKBACK_DAYS", 35)),
        )
    except Exception as exc:
        _append_log(log_file, f"local boxscores bootstrap failed: {exc}")
        return False, f"local boxscores bootstrap failed: {exc}"

    if int(result.get("history_rows") or 0) > 0 and str(result.get("wrote") or "").strip():
        _append_log(log_file, f"bootstrapped local boxscores history via ESPN: {result.get('wrote')}")
        return True, None
    reason = str(result.get("error") or "local boxscores bootstrap wrote no history rows").strip()
    _append_log(log_file, f"local boxscores bootstrap unavailable: {reason}")
    return False, reason


def _ensure_player_logs_for_props_refresh(*, source_root: Path, date_str: str, log_file: Path, heartbeat_cb: callable) -> tuple[bool, str | None]:
    raw_max_age = (
        os.environ.get("REFRESH_PLAYER_LOGS_MAX_AGE_HOURS")
        or os.environ.get("DAILY_PLAYER_LOGS_MAX_AGE_HOURS")
        or "12"
    ).strip()
    try:
        max_age_minutes = int(max(0.0, float(raw_max_age) * 60.0))
    except Exception:
        max_age_minutes = 12 * 60

    if _player_logs_ready(source_root, max_age_minutes=max_age_minutes):
        return True, None
    if any(path.exists() and path.stat().st_size > 0 for path in (_active_player_logs_paths(source_root) + _active_player_logs_fallback_paths(source_root))):
        return True, None

    bootstrapped_ok, bootstrap_error = _bootstrap_local_boxscores_history_for_props(
        source_root=source_root,
        date_str=date_str,
        log_file=log_file,
    )
    if bootstrapped_ok:
        return True, None

    allow_fetch_on_miss = (os.environ.get("REFRESH_PLAYER_LOGS_FETCH_ON_MISS") or "0").strip().lower() in {"1", "true", "yes"}
    if not allow_fetch_on_miss:
        return False, bootstrap_error or "player_logs not found and no local boxscores fallback is available; run fetch-player-logs"
    _append_log(log_file, "player_logs missing and source fetch fallback is disabled in Syndicate-only mode")
    return False, "player_logs missing and no local fetch fallback is available"


def _ensure_game_predictions_for_props_refresh(*, source_root: Path, date_str: str, log_file: Path, heartbeat_cb: callable) -> tuple[bool, str | None]:
    processed_root = source_root / "data" / "processed"
    pred_path = processed_root / f"predictions_{date_str}.csv"
    if pred_path.exists() and pred_path.is_file() and _count_csv_rows_quick(pred_path) > 0:
        if _repair_predictions_slate_from_game_odds_if_needed(processed_root=processed_root, date_str=date_str, log_file=log_file):
            return True, None

    fallback_candidates = [
        processed_root / f"games_predictions_npu_{date_str}.csv",
        source_root / f"predictions_{date_str}.csv",
        source_root / "data" / "processed" / f"games_predictions_npu_{date_str}.csv",
    ]
    for candidate in fallback_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.resolve() != pred_path.resolve():
                pred_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, pred_path)
        except Exception:
            pass
        if pred_path.exists() and pred_path.is_file() and _count_csv_rows_quick(pred_path) > 0:
            _repair_predictions_slate_from_game_odds_if_needed(processed_root=processed_root, date_str=date_str, log_file=log_file)
            _append_log(log_file, f"Using existing game predictions artifact: {pred_path}")
            return True, None

    _append_log(log_file, f"Generating required game predictions artifact via source bootstrap: {pred_path}")
    bootstrap_result = _ensure_source_game_inputs(
        source_root=source_root,
        package_name="wnba_betting",
        date_str=date_str,
        log_file=log_file,
        heartbeat_cb=heartbeat_cb,
    )
    repo_pred_path = source_root / f"predictions_{date_str}.csv"
    if (not pred_path.exists() or _count_csv_rows_quick(pred_path) <= 0) and repo_pred_path.exists() and repo_pred_path.is_file():
        try:
            pred_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo_pred_path, pred_path)
        except Exception:
            pass
    _repair_predictions_slate_from_game_odds_if_needed(processed_root=processed_root, date_str=date_str, log_file=log_file)
    if _count_csv_rows_quick(pred_path) <= 0:
        game_odds_path = processed_root / f"game_odds_{date_str}.csv"
        return False, f"source bootstrap did not produce {pred_path.name} (rc={bootstrap_result.get('predict_date')})"
    _append_log(log_file, f"Generated game predictions at {pred_path} (rows={_count_csv_rows_quick(pred_path)})")
    return True, None


def _repair_predictions_slate_from_game_odds_if_needed(*, processed_root: Path, date_str: str, log_file: Path) -> bool:
    import pandas as pd

    pred_path = processed_root / f"predictions_{date_str}.csv"
    game_odds_path = processed_root / f"game_odds_{date_str}.csv"
    props_snapshot_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    pred_exists = pred_path.exists() and pred_path.is_file() and _count_csv_rows_quick(pred_path) > 0

    try:
        pred_df = pd.read_csv(pred_path) if pred_exists else pd.DataFrame()
        odds_df = pd.read_csv(game_odds_path) if (game_odds_path.exists() and game_odds_path.is_file() and _count_csv_rows_quick(game_odds_path) > 0) else pd.DataFrame()
        props_df = pd.read_csv(props_snapshot_path) if (props_snapshot_path.exists() and props_snapshot_path.is_file() and _count_csv_rows_quick(props_snapshot_path) > 0) else pd.DataFrame()
        _log_frame_memory("wnba_repair_pred_read", pred_df, path=str(pred_path))
        _log_frame_memory("wnba_repair_odds_read", odds_df, path=str(game_odds_path))
        _log_frame_memory("wnba_repair_props_read", props_df, path=str(props_snapshot_path))
    except Exception:
        return bool(pred_exists)

    def _norm_pair(home_val: object, away_val: object) -> tuple[str, str]:
        return (str(home_val or "").strip().upper(), str(away_val or "").strip().upper())

    if "date" in odds_df.columns and not odds_df.empty:
        odds_df = odds_df.copy()
        _log_frame_memory("wnba_repair_odds_copied", odds_df, path=str(game_odds_path))
        odds_df["date"] = pd.to_datetime(odds_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        odds_df = odds_df[odds_df["date"] == str(date_str)].copy()
        _log_frame_memory("wnba_repair_odds_filtered", odds_df, path=str(game_odds_path))
    odds_pairs = {
        _norm_pair(row.get("home_team"), row.get("visitor_team"))
        for _, row in odds_df.iterrows()
        if str(row.get("home_team") or "").strip() and str(row.get("visitor_team") or "").strip()
    }

    props_pairs = {
        _norm_pair(row.get("home_team"), row.get("away_team"))
        for _, row in props_df.iterrows()
        if str(row.get("home_team") or "").strip() and str(row.get("away_team") or "").strip()
    }
    target_pairs = props_pairs or odds_pairs
    if not target_pairs:
        return bool(pred_exists)

    if pred_df is not None and not pred_df.empty:
        pred_work = pred_df.copy()
        _log_frame_memory("wnba_repair_pred_copied", pred_work, path=str(pred_path))
        if "date" in pred_work.columns:
            pred_work["date"] = pd.to_datetime(pred_work["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            pred_work = pred_work[pred_work["date"] == str(date_str)].copy()
            _log_frame_memory("wnba_repair_pred_filtered", pred_work, path=str(pred_path))
        pred_pairs = {
            _norm_pair(row.get("home_team"), row.get("visitor_team"))
            for _, row in pred_work.iterrows()
            if str(row.get("home_team") or "").strip() and str(row.get("visitor_team") or "").strip()
        }
        if pred_pairs & target_pairs:
            return True


    # ✅ FIXED rebuild block starts here
    if not props_df.empty:
        rebuild = props_df[[column for column in ["home_team", "away_team", "commence_time"]
                            if column in props_df.columns]].copy()
        _log_frame_memory("wnba_repair_rebuild_from_props", rebuild, path=str(props_snapshot_path))

        rebuild = rebuild.rename(columns={"away_team": "visitor_team"})
        rebuild["date"] = str(date_str)

        rebuild = rebuild.drop_duplicates(
            subset=["home_team", "visitor_team"], keep="first"
        )

    elif not odds_df.empty:
        rebuild = odds_df.copy()
    else:
        return False

# ✅ merge odds if available
    if not odds_df.empty:
        odds_merge = odds_df.copy()
        _log_frame_memory("wnba_repair_odds_merge_copy", odds_merge, path=str(game_odds_path))

        if "visitor_team" not in odds_merge.columns:
            if "away_team" in odds_merge.columns:
                odds_merge["visitor_team"] = odds_merge["away_team"]
            else:
                return False

        odds_merge = odds_merge[[column for column in [
            "home_team", "visitor_team",
            "home_ml", "away_ml",
            "home_spread", "away_spread",
            "total", "bookmaker"
        ] if column in odds_merge.columns]].copy()
        _log_frame_memory("wnba_repair_odds_merge_trimmed", odds_merge, path=str(game_odds_path))

        odds_merge = odds_merge.drop_duplicates(
            subset=["home_team", "visitor_team"], keep="first"
        )

        if not rebuild.empty:
            rebuild = rebuild.merge(
                odds_merge,
                on=["home_team", "visitor_team"],
                how="left"
            )
            _log_frame_memory("wnba_repair_rebuild_merged", rebuild, path=str(game_odds_path))
        
    if rebuild.empty:
        return False

        # ✅ Normalize rebuild into final shape
    rebuild = rebuild[[column for column in [
        "date", "home_team", "visitor_team", "commence_time",
        "home_ml", "away_ml", "home_spread", "away_spread", "total", "bookmaker"
    ] if column in rebuild.columns]].copy()
    _log_frame_memory("wnba_repair_rebuild_final_slice", rebuild, path=str(game_odds_path))
    
    if "date" not in rebuild.columns:
        rebuild["date"] = str(date_str)

    for col in ("home_ml", "away_ml", "home_spread", "away_spread", "total"):
        if col in rebuild.columns:
            rebuild[col] = pd.to_numeric(rebuild[col], errors="coerce")
    

    def _implied(odds: float | None) -> float | None:
        try:
            value = float(odds)
        except Exception:
            return None
        if value == 0:
            return None
        if value > 0:
            return 100.0 / (value + 100.0)
        return (-value) / ((-value) + 100.0)

    home_probs: list[float] = []
    for _, row in rebuild.iterrows():
        home_ml = row.get("home_ml") if "home_ml" in rebuild.columns else None
        away_ml = row.get("away_ml") if "away_ml" in rebuild.columns else None
        p_home = _implied(home_ml)
        p_away = _implied(away_ml)
        if p_home is not None and p_away is not None and float(p_home + p_away) > 0:
            home_probs.append(float(p_home) / float(p_home + p_away))
        else:
            home_probs.append(0.5)
    rebuild["home_win_prob"] = home_probs
    rebuild["spread_margin"] = -pd.to_numeric(rebuild.get("home_spread"), errors="coerce")
    rebuild["totals"] = pd.to_numeric(rebuild.get("total"), errors="coerce")

    cols = [
        "date", "home_team", "visitor_team", "home_win_prob", "spread_margin", "totals",
        "commence_time", "home_ml", "away_ml", "home_spread", "away_spread", "total", "bookmaker",
    ]
    out_df = rebuild[[column for column in cols if column in rebuild.columns]].drop_duplicates(subset=["home_team", "visitor_team"], keep="first")
    _log_frame_memory("wnba_repair_output_frame", out_df, path=str(pred_path))
    if out_df.empty:
        return False
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(pred_path, index=False)
    _append_log(log_file, f"Rebuilt predictions slate from local game odds for {date_str}: {pred_path} (rows={len(out_df)})")
    return _count_csv_rows_quick(pred_path) > 0


def _predict_props_cli_args(*, source_root: Path, date_str: str, out_path: Path) -> list[str]:
    smart_sim_n_sims = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 150))
    smart_sim_workers = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1))
    calib_window = max(1, _env_int("REFRESH_PREDICT_PROPS_CALIB_WINDOW", 7))
    player_calib_window = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_CALIB_WINDOW", 30))
    player_min_pairs = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_MIN_PAIRS", 6))
    player_shrink_k = max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_SHRINK_K", 8))
    args = [
        "predict-props",
        "--date",
        date_str,
        "--out",
        str(out_path),
        "--slate-only",
        "--calibrate",
        "--calib-window",
        str(calib_window),
    ]
    if _env_bool("REFRESH_PREDICT_PROPS_USE_PURE_ONNX", False):
        args.append("--use-pure-onnx")
    if _env_bool("REFRESH_PREDICT_PROPS_CALIBRATE_PLAYER", True):
        args.extend([
            "--calibrate-player",
            "--player-calib-window",
            str(player_calib_window),
            "--player-min-pairs",
            str(player_min_pairs),
            "--player-shrink-k",
            str(player_shrink_k),
        ])
    else:
        args.append("--no-calibrate-player")
    if _env_bool("REFRESH_PREDICT_PROPS_USE_SMART_SIM", True):
        args.extend([
            "--use-smart-sim",
            "--smart-sim-n-sims",
            str(smart_sim_n_sims),
            "--smart-sim-workers",
            str(smart_sim_workers),
        ])
        args.append("--smart-sim-pbp" if _env_bool("REFRESH_PREDICT_PROPS_SMART_SIM_PBP", True) else "--no-smart-sim-pbp")
    else:
        args.append("--no-use-smart-sim")
    return args


def _run_source_cli_command(
    source_root: Path,
    args: list[str],
    log_file: Path,
    *,
    heartbeat_cb: callable | None,
    heartbeat_every_s: float = 15.0,
) -> int:
    cmd_text = " ".join(shlex.quote(str(a)) for a in args)
    _append_log(log_file, f"$ source-cli {cmd_text}")

    cli_module = _load_source_cli(source_root)
    stop_event = threading.Event()
    heartbeat_thread = None
    if heartbeat_cb is not None:
        def _heartbeat_loop() -> None:
            while not stop_event.wait(max(1.0, float(heartbeat_every_s))):
                try:
                    heartbeat_cb()
                except Exception:
                    pass

        heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
        heartbeat_thread.start()

    previous_cwd = Path.cwd()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_file.open("a", encoding="utf-8", errors="ignore") as out:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                os.chdir(source_root)
                try:
                    cli_module.cli.main(args, standalone_mode=False)  # type: ignore[attr-defined]
                    return 0
                except SystemExit as exc:
                    code = exc.code
                    if code is None:
                        return 0
                    if isinstance(code, int):
                        return int(code)
                    return 1
                except Exception:
                    traceback.print_exc(file=out)
                    return 1
    finally:
        try:
            os.chdir(previous_cwd)
        except Exception:
            pass
        stop_event.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1.0)


def _run_refresh_via_cli(
    *,
    source_root: Path,
    date_str: str,
    regions: str,
    bookmakers: str,
    markets: str,
    do_edges: bool,
    do_export: bool,
    do_push: bool,
    smart_sim_overwrite: bool = False,
    log_file: Path,
    started_at: str | None = None,
    mode: str = "full",
) -> dict[str, object]:
    refresh_mode = str(mode or "full").strip().lower() or "full"
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    raw_fp = raw_root / f"odds_wnba_player_props_{date_str}.csv"
    pred_fp = processed_root / f"props_predictions_{date_str}.csv"
    edges_fp = processed_root / f"props_edges_{date_str}.csv"
    rec_fp = processed_root / f"props_recommendations_{date_str}.csv"
    started_iso = started_at or dt.datetime.utcnow().isoformat()
    state: dict[str, object] = {
        "date": str(date_str),
        "started_at": started_iso,
        "ended_at": None,
        "phase": "snapshot",
        "phase_started_at": started_iso,
        "heartbeat_at": dt.datetime.utcnow().isoformat(),
        "rc_snapshot": -1,
        "rc_edges": (-2 if do_edges else None),
        "rc_export": (-2 if do_export else None),
        "snapshot_rows": 0,
        "snapshot_bundle_rows": 0,
        "predictions_rows": 0,
        "prediction_bundle_rows": 0,
        "edges_rows": 0,
        "recs_rows": 0,
        "snapshot_path": str(raw_fp),
        "snapshot_bundle_path": str(raw_fp),
        "predictions_path": str(pred_fp),
        "prediction_bundle_path": str(pred_fp),
        "edges_path": str(edges_fp),
        "recs_path": str(rec_fp),
        "snapshot_alias_path": str(processed_root / f"oddsapi_player_props_{date_str}.csv"),
        "snapshot_alias_rows": 0,
        "duration_s": None,
        "error": None,
        "mode": refresh_mode,
    }
    started_ts = time.time()

    def _touch_progress() -> None:
        state["heartbeat_at"] = dt.datetime.utcnow().isoformat()

    py = _source_python(source_root)
    env = _source_worker_env(source_root)
    rc_snapshot = _run_to_file(
        _owned_snapshot_cli_args(
            date_str=date_str,
            out_path=raw_fp,
            regions=regions,
            bookmakers=bookmakers,
            markets=markets,
        ),
        log_file,
        cwd=REPO_ROOT,
        env=_local_worker_env(),
        timeout_s=15 * 60,
        heartbeat_cb=_touch_progress,
    )
    state["rc_snapshot"] = int(rc_snapshot)
    state["snapshot_rows"] = int(_count_csv_rows_quick(raw_fp))
    state["snapshot_bundle_rows"] = int(state["snapshot_rows"] or 0)
    alias_path, alias_rows, alias_error = _materialize_processed_snapshot_alias(
        processed_root=processed_root,
        date_str=date_str,
        snapshot_path=raw_fp,
        log_file=log_file,
    )
    state["snapshot_alias_path"] = str(alias_path)
    state["snapshot_alias_rows"] = int(alias_rows)
    if _env_bool("WNBA_ISOLATE_AFTER_SNAPSHOT", False): return state
    _append_log(log_file, f"Snapshot stage finished for {date_str}: rc_snapshot={state['rc_snapshot']}, rows={state['snapshot_rows']}, alias_rows={state['snapshot_alias_rows']}")
    if alias_error and int(state["snapshot_rows"] or 0) > 0:
        state["error"] = f"snapshot alias write failed: {alias_error}"

    pred_ready = False
    if refresh_mode == "full" and not state.get("error") and int(state["snapshot_rows"] or 0) > 0 and (do_edges or do_export):
        state["phase"] = "predictions"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        player_logs_ok, player_logs_error = _ensure_player_logs_for_props_refresh(
            source_root=source_root,
            date_str=date_str,
            log_file=log_file,
            heartbeat_cb=_touch_progress,
        )
        if not player_logs_ok:
            state["error"] = player_logs_error or f"player_logs missing before predict-props for {date_str}"
        else:
            if _env_bool("WNBA_ISOLATE_AFTER_PLAYER_LOGS", False): return state
            if _env_bool("WNBA_ISOLATE_BEFORE_PREDICTIONS", False): return state
            game_predictions_ok, game_predictions_error = _ensure_game_predictions_for_props_refresh(
                source_root=source_root,
                date_str=date_str,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_pred = 1
            if not game_predictions_ok:
                state["error"] = game_predictions_error or f"predictions missing before predict-props for {date_str}"
            else:
                try:
                    smart_sim_workers = max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1))
                    smart_sim_executor = "ProcessPoolExecutor" if smart_sim_workers > 1 else "sequential"
                    log_runtime_memory("before_smart_sim", phase=state["phase"], worker_count=smart_sim_workers, executor_type=smart_sim_executor)
                    print(f"SMART_SIM_WORKERS {json.dumps({'worker_count': smart_sim_workers, 'executor_type': smart_sim_executor}, sort_keys=True)}", file=sys.stderr, flush=True)
                    _touch_progress()
                    _, _ = export_props_predictions_local(
                        source_root=source_root,
                        date_str=date_str,
                        out_path=pred_fp,
                        calib_window=max(1, _env_int("REFRESH_PREDICT_PROPS_CALIB_WINDOW", 7)),
                        calibrate_player=_env_bool("REFRESH_PREDICT_PROPS_CALIBRATE_PLAYER", True),
                        player_calib_window=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_CALIB_WINDOW", 30)),
                        player_min_pairs=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_MIN_PAIRS", 6)),
                        player_shrink_k=max(1, _env_int("REFRESH_PREDICT_PROPS_PLAYER_SHRINK_K", 8)),
                        use_smart_sim=_env_bool("REFRESH_WNBA_USE_SMART_SIM", True),
                        smart_sim_n_sims=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_N_SIMS", 150)),
                        smart_sim_pbp=_env_bool("REFRESH_PREDICT_PROPS_SMART_SIM_PBP", True),
                        smart_sim_workers=max(1, _env_int("REFRESH_PREDICT_PROPS_SMART_SIM_WORKERS", 1)),
                        smart_sim_overwrite=bool(smart_sim_overwrite),
                        log_file=log_file,
                        heartbeat_cb=_touch_progress,
                        heartbeat_every_s=5.0,
                    )
                    _touch_progress()
                    log_runtime_memory("after_export_props_predictions_local", phase=state["phase"], worker_count=smart_sim_workers, executor_type=smart_sim_executor)
                    log_runtime_memory("after_smart_sim", phase=state["phase"], worker_count=smart_sim_workers, executor_type=smart_sim_executor)
                    rc_pred = 0
                except Exception:
                    _append_log(log_file, traceback.format_exc())
                    rc_pred = 1
            state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp))
            state["prediction_bundle_rows"] = int(state["predictions_rows"] or 0)
            _append_log(log_file, f"Predictions stage finished for {date_str}: rc_pred={int(rc_pred)}, rows={state['predictions_rows']}")
            existing_edges_rows = int(_count_csv_rows_quick(edges_fp))
            existing_recs_rows = int(_count_csv_rows_quick(rec_fp))
            existing_game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
            have_downstream_artifacts = (
                (not do_edges or existing_edges_rows > 0)
                and (not do_export or existing_recs_rows > 0)
                and (not do_export or existing_game_cards_rows > 0)
            )
            if int(rc_pred) != 0:
                state["error"] = f"predict-props failed with exit code {int(rc_pred)}"
                _append_log(log_file, state["error"])
            elif int(state["predictions_rows"] or 0) <= 0:
                state["error"] = f"predict-props wrote no rows to {pred_fp.name} for {date_str}"
                _append_log(log_file, state["error"])
            else:
                pred_ready = True
    elif int(state["snapshot_rows"] or 0) <= 0:
        state["rc_edges"] = None if do_edges else state.get("rc_edges")
        state["rc_export"] = None if do_export else state.get("rc_export")

    if refresh_mode == "full" and pred_ready and do_edges:
        state["phase"] = "edges"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        state["rc_edges"] = -1
        try:
            _touch_progress()
            _, _ = export_props_edges_local(
                source_root=source_root,
                date_str=date_str,
                raw_path=raw_fp,
                predictions_path=pred_fp,
                out_path=edges_fp,
                bookmakers=bookmakers,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
                heartbeat_every_s=5.0,
            )
            _touch_progress()
            log_runtime_memory("after_export_props_edges_local", phase=state["phase"], raw_rows=int(state.get("snapshot_rows") or 0), pred_rows=int(state.get("predictions_rows") or 0))
            rc_edges = 0
        except Exception:
            rc_edges = 1
        state["rc_edges"] = int(rc_edges)
        state["edges_rows"] = int(_count_csv_rows_quick(edges_fp))
        _append_log(log_file, f"Edges stage finished for {date_str}: rc_edges={int(rc_edges)}, rows={state['edges_rows']}")
        if int(rc_edges) != 0:
            if int(state.get("snapshot_rows") or 0) > 0 and int(state.get("predictions_rows") or 0) > 0 and int(state.get("edges_rows") or 0) <= 0:
                _append_log(log_file, f"Edges stage returned {int(rc_edges)} with no WNBA edge rows; treating as a warning for {date_str}")
                state["warning"] = f"WNBA props-edges produced no rows for {date_str}; continuing refresh"
                state["rc_edges"] = 0
                rc_edges = 0
            else:
                state["error"] = f"props-edges failed with exit code {int(rc_edges)}"
        elif int(state["snapshot_rows"] or 0) > 0 and int(state["edges_rows"] or 0) <= 0:
            _append_log(log_file, f"Edges stage produced no WNBA rows for {date_str}; treating as a warning")
            state["warning"] = f"WNBA props-edges produced no rows for {date_str}; continuing refresh"
            state["rc_edges"] = 0
            rc_edges = 0

    if refresh_mode == "full" and do_export and not state.get("error"):
        state["phase"] = "export"
        state["phase_started_at"] = dt.datetime.utcnow().isoformat()
        state["rc_export"] = -1
        log_runtime_memory("before_export", phase=state["phase"], pred_ready=bool(pred_ready))
        _append_log(log_file, f"Export stage starting for {date_str}: pred_ready={pred_ready}, snapshot_rows={int(state.get('snapshot_rows') or 0)}, edges_rows={int(state.get('edges_rows') or 0)}")
        game_cards_rows = 0
        local_game_cards_path = None
        rc_game_cards = 1
        local_recommendations_path = None
        rc_recommendations = 1
        rc_local_props_export = 0
        try:
            _touch_progress()
            game_input_rcs = _ensure_source_game_inputs(
                source_root=source_root,
                package_name="wnba_betting",
                date_str=date_str,
                log_file=log_file,
                heartbeat_cb=_touch_progress,
            )
            rc_local_props_export = 0
            if pred_ready:
                _, _ = export_props_recommendations_local(processed_root=processed_root, date_str=date_str)
                _touch_progress()
                log_runtime_memory("after_export_props_recommendations_local", phase=state["phase"], pred_ready=bool(pred_ready))
            else:
                _append_log(log_file, f"Skipping local props recommendations export for {date_str}: props predictions were not refreshed")
            game_cards_rows, local_game_cards_path = _build_local_game_cards_artifact(
                source_root=source_root,
                processed_root=processed_root,
                date_str=date_str,
                log_file=log_file,
            )
            rc_game_cards = 0 if local_game_cards_path is not None and int(game_cards_rows) > 0 else 1
            _, local_recommendations_path = _build_local_game_recommendations_artifact(processed_root=processed_root, date_str=date_str)
            rc_recommendations = 0 if local_recommendations_path is not None else 1
            log_runtime_memory("after_local_game_cards_and_recommendations", phase=state["phase"], game_cards_rows=game_cards_rows, rc_recommendations=rc_recommendations)
            if any(int(value) != 0 for value in game_input_rcs.values()):
                _append_log(log_file, f"WNBA source bootstrap returned non-zero input codes for {date_str}: {game_input_rcs}")
            rc_export = 0 if int(rc_local_props_export) == 0 and int(rc_game_cards) == 0 else 1
            if int(rc_export) == 0 and int(rc_recommendations) != 0:
                _append_log(log_file, f"Export stage missing WNBA recommendation artifacts for {date_str}; continuing with warning because core WNBA outputs are present")
                state["warning"] = f"WNBA recommendation artifacts were unavailable for {date_str}; continuing with core outputs"
        except Exception:
            _append_log(log_file, traceback.format_exc())
            rc_export = 1
            game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
            local_recommendations_path = processed_root / f"props_recommendations_{date_str}.csv"
        state["game_cards_rows"] = int(game_cards_rows)
        state["rc_export"] = int(rc_export)
        state["recs_rows"] = int(_count_csv_rows_quick(rec_fp))
        log_runtime_memory("after_export", phase=state["phase"], rc_export=state["rc_export"], game_cards_rows=game_cards_rows, recs_rows=state["recs_rows"])
        _append_log(log_file, f"Export stage finished for {date_str}: rc_export={state['rc_export']}, game_cards_rows={game_cards_rows}, recs_rows={state['recs_rows']}")
        source_game_cards_rows = int(_count_csv_rows_quick(source_root / 'data' / 'processed' / f'game_cards_{date_str}.csv'))
        if int(rc_export) != 0:
            no_data_export = (
                int(state.get("snapshot_rows") or 0) <= 0
                and int(state.get("predictions_rows") or 0) <= 0
                and int(state.get("edges_rows") or 0) <= 0
                and int(state.get("recs_rows") or 0) <= 0
                and int(game_cards_rows or 0) <= 0
                and source_game_cards_rows <= 0
            )
            if no_data_export:
                _append_log(log_file, f"Export stage returned {rc_export} with no WNBA input rows; treating as a warning for {date_str}")
                state["warning"] = f"WNBA odds refresh produced no rows for {date_str}; export was skipped as a no-data run"
                state["rc_export"] = 0
                rc_export = 0
            else:
                export_artifacts_ready = (
                    int(state.get("snapshot_rows") or 0) > 0
                    and int(state.get("predictions_rows") or 0) > 0
                    and int(game_cards_rows or 0) > 0
                )
                if export_artifacts_ready:
                    if do_edges and int(state.get("edges_rows") or 0) <= 0:
                        _append_log(log_file, f"Export stage missing WNBA edges rows for {date_str}; continuing with warning because core WNBA outputs are present")
                    if int(state.get("recs_rows") or 0) <= 0:
                        _append_log(log_file, f"Export stage missing WNBA recommendation rows for {date_str}; continuing with warning because core WNBA outputs are present")
                    _append_log(log_file, f"Export stage returned {rc_export} but required WNBA artifacts were present; treating as warning for {date_str}")
                    state["rc_export"] = 0
                    rc_export = 0
                else:
                    state["error"] = f"export-props-recommendations failed with exit code {int(rc_export)}"
    state["snapshot_rows"] = int(_count_csv_rows_quick(raw_fp))
    state["snapshot_bundle_rows"] = int(state.get("snapshot_rows") or 0)
    state["predictions_rows"] = int(_count_csv_rows_quick(pred_fp)) if refresh_mode == "full" else int(state.get("predictions_rows") or 0)
    state["prediction_bundle_rows"] = int(state.get("predictions_rows") or 0)
    state["edges_rows"] = int(_count_csv_rows_quick(edges_fp)) if refresh_mode == "full" else int(state.get("edges_rows") or 0)
    state["recs_rows"] = int(_count_csv_rows_quick(rec_fp)) if refresh_mode == "full" else int(state.get("recs_rows") or 0)
    state["snapshot_alias_rows"] = int(_count_csv_rows_quick(Path(str(state.get("snapshot_alias_path") or ""))))
    state["phase"] = "done"
    ended = dt.datetime.utcnow().isoformat()
    state["phase_started_at"] = ended
    state["heartbeat_at"] = ended
    state["ended_at"] = ended
    state["duration_s"] = float(max(0.0, time.time() - started_ts))
    if do_push:
        _append_log(log_file, "do_push requested but push is not implemented in the Syndicate-owned runner")
    return state


def _existing_refresh_state(*, source_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None, input_hash: str | None = None) -> dict[str, object] | None:
    raw_root = source_root / "data" / "raw"
    processed_root = source_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_wnba_player_props_{date_str}.csv"
    snapshot_alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    recs_path = processed_root / f"props_recommendations_{date_str}.csv"

    required_paths = [snapshot_path]
    if do_edges or do_export:
        required_paths.append(predictions_path)
    if do_edges:
        required_paths.append(edges_path)
    if any(not path.exists() or not path.is_file() for path in required_paths):
        return None

    started = str(started_at or "") or str(dt.datetime.utcnow().isoformat())
    ended = str(dt.datetime.utcnow().isoformat())
    return {
        "date": str(date_str),
        "started_at": started,
        "ended_at": ended,
        "phase": "done",
        "phase_started_at": ended,
        "heartbeat_at": ended,
        "rc_snapshot": 0,
        "rc_edges": (0 if do_edges else None),
        "rc_export": (0 if do_export else None),
        "snapshot_rows": int(_count_csv_rows_quick(snapshot_path)),
        "snapshot_bundle_rows": int(_count_csv_rows_quick(snapshot_path)),
        "predictions_rows": int(_count_csv_rows_quick(predictions_path)),
        "prediction_bundle_rows": int(_count_csv_rows_quick(predictions_path)),
        "edges_rows": int(_count_csv_rows_quick(edges_path)),
        "recs_rows": int(_count_csv_rows_quick(recs_path)),
        "snapshot_path": str(snapshot_path),
        "snapshot_bundle_path": str(snapshot_path),
        "predictions_path": str(predictions_path),
        "prediction_bundle_path": str(predictions_path),
        "edges_path": str(edges_path),
        "recs_path": str(recs_path),
        "snapshot_alias_path": str(snapshot_alias_path),
        "snapshot_alias_rows": int(_count_csv_rows_quick(snapshot_alias_path)),
        "duration_s": 0.0,
        "error": None,
        "reused_existing_outputs": True,
    }


def _existing_artifact_bundle_state(*, artifact_root: Path, date_str: str, do_edges: bool, do_export: bool, started_at: str | None = None, input_hash: str | None = None) -> dict[str, object] | None:
    raw_root = artifact_root / "data" / "raw"
    processed_root = artifact_root / "data" / "processed"
    snapshot_path = raw_root / f"odds_wnba_player_props_{date_str}.csv"
    snapshot_alias_path = processed_root / f"oddsapi_player_props_{date_str}.csv"
    predictions_path = processed_root / f"props_predictions_{date_str}.csv"
    edges_path = processed_root / f"props_edges_{date_str}.csv"
    recs_path = processed_root / f"props_recommendations_{date_str}.csv"
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    recommendations_slate_path = processed_root / f"recommendations_slate_{date_str}.json"
    cards_props_snapshot_path = processed_root / f"cards_props_snapshot_{date_str}.json"
    cards_sim_detail_path = processed_root / f"cards_sim_detail_{date_str}.json"
    top_by_game_path = processed_root / f"props_recommendations_top_by_game_{date_str}.json"

    required_paths = [snapshot_path]
    if do_edges or do_export:
        required_paths.append(predictions_path)
    if do_edges:
        required_paths.append(edges_path)
    if any(not path.exists() or not path.is_file() for path in required_paths):
        return None

    game_cards_rows = int(_count_csv_rows_quick(game_cards_path))
    cards_sim_detail_games = int(_count_cards_sim_detail_games(cards_sim_detail_path))
    smart_sim_files = int(_count_matching_files(processed_root, f"smart_sim_{date_str}_*.json"))

    started = str(started_at or "") or str(dt.datetime.utcnow().isoformat())
    ended = str(dt.datetime.utcnow().isoformat())
    return {
        "date": str(date_str),
        "started_at": started,
        "ended_at": ended,
        "phase": "done",
        "phase_started_at": ended,
        "heartbeat_at": ended,
        "rc_snapshot": 0,
        "rc_edges": (0 if do_edges else None),
        "rc_export": (0 if do_export else None),
        "snapshot_rows": int(_count_csv_rows_quick(snapshot_path)),
        "snapshot_bundle_rows": int(_count_csv_rows_quick(snapshot_path)),
        "predictions_rows": int(_count_csv_rows_quick(predictions_path)),
        "prediction_bundle_rows": int(_count_csv_rows_quick(predictions_path)),
        "edges_rows": int(_count_csv_rows_quick(edges_path)),
        "recs_rows": int(_count_csv_rows_quick(recs_path)),
        "game_cards_rows": game_cards_rows,
        "cards_sim_detail_games": cards_sim_detail_games,
        "smart_sim_files": smart_sim_files,
        "snapshot_path": str(snapshot_path),
        "snapshot_bundle_path": str(snapshot_path),
        "predictions_path": str(predictions_path),
        "prediction_bundle_path": str(predictions_path),
        "edges_path": str(edges_path),
        "recs_path": str(recs_path),
        "snapshot_alias_path": str(snapshot_alias_path),
        "snapshot_alias_rows": int(_count_csv_rows_quick(snapshot_alias_path)),
        "duration_s": 0.0,
        "error": None,
        "reused_existing_artifact_bundle": True,
        "artifact_bundle_root": str(artifact_root),
    }


def _processed_source_directory(state: dict[str, object]) -> Path | None:
    for key in ("predictions_path", "edges_path", "recs_path", "snapshot_alias_path", "snapshot_bundle_path", "snapshot_path"):
        source_text = str(state.get(key) or "").strip()
        if not source_text:
            continue
        source = Path(source_text)
        if source.exists():
            return source.resolve().parent
    return None


def _load_module_from_path(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _canon_boxscore_game_id(value: object) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        return f"00{digits}"
    if len(digits) == 9:
        return f"0{digits}"
    return digits or text


def _split_player_name(value: object) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    parts = text.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _materialize_local_boxscore_cache_for_player_artifacts(*, processed_root: Path, date_str: str) -> int:
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"
    if not boxscores_path.exists():
        return 0

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    team_to_game_id: dict[str, str] = {}
    if game_cards_path.exists():
        with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                game_id = _canon_boxscore_game_id((row or {}).get("game_id"))
                if not game_id:
                    continue
                for key in ("home_tri", "away_tri"):
                    team_tri = str((row or {}).get(key) or "").strip().upper()
                    if team_tri and team_tri not in team_to_game_id:
                        team_to_game_id[team_tri] = game_id

    rows_by_game: dict[str, list[dict[str, str]]] = {}
    with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
            team_tri = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
            game_id = _canon_boxscore_game_id(normalized.get("GAME_ID") or normalized.get("GAMEID") or team_to_game_id.get(team_tri))
            player_name = str(normalized.get("PLAYER_NAME") or normalized.get("PLAYER") or "").strip()
            if not game_id or not team_tri or not player_name:
                continue
            first_name, family_name = _split_player_name(player_name)
            rows_by_game.setdefault(game_id, []).append(
                {
                    "personId": str(normalized.get("PLAYER_ID") or normalized.get("PERSONID") or "").strip(),
                    "teamTricode": team_tri,
                    "position": str(normalized.get("START_POSITION") or normalized.get("POSITION") or "").strip(),
                    "minutes": str(normalized.get("MIN") or normalized.get("MINUTES") or "").strip(),
                    "points": str(normalized.get("PTS") or normalized.get("POINTS") or "").strip(),
                    "reboundsTotal": str(normalized.get("REB") or normalized.get("TREB") or normalized.get("REBOUNDSTOTAL") or "").strip(),
                    "assists": str(normalized.get("AST") or normalized.get("ASSISTS") or "").strip(),
                    "threePointersMade": str(normalized.get("FG3M") or normalized.get("THREEPOINTERSMADE") or "").strip(),
                    "threePointersAttempted": str(normalized.get("FG3A") or normalized.get("THREEPOINTERSATTEMPTED") or "").strip(),
                    "fieldGoalsMade": str(normalized.get("FGM") or normalized.get("FIELDGOALSMADE") or "").strip(),
                    "fieldGoalsAttempted": str(normalized.get("FGA") or normalized.get("FIELDGOALSATTEMPTED") or "").strip(),
                    "freeThrowsMade": str(normalized.get("FTM") or normalized.get("FREETHROWSMADE") or "").strip(),
                    "freeThrowsAttempted": str(normalized.get("FTA") or normalized.get("FREETHROWSATTEMPTED") or "").strip(),
                    "steals": str(normalized.get("STL") or normalized.get("STEALS") or "").strip(),
                    "blocks": str(normalized.get("BLK") or normalized.get("BLOCKS") or "").strip(),
                    "turnovers": str(normalized.get("TOV") or normalized.get("TURNOVERS") or normalized.get("TO") or "").strip(),
                    "foulsPersonal": str(normalized.get("PF") or normalized.get("FOULSPERSONAL") or "").strip(),
                    "reboundsOffensive": str(normalized.get("OREB") or normalized.get("REBOUNDSOFFENSIVE") or "").strip(),
                    "reboundsDefensive": str(normalized.get("DREB") or normalized.get("REBOUNDSDEFENSIVE") or "").strip(),
                    "plusMinusPoints": str(normalized.get("PLUS_MINUS") or normalized.get("PLUSMINUSPOINTS") or "").strip(),
                    "firstName": first_name,
                    "familyName": family_name,
                    "nameI": player_name,
                }
            )
    log_list_memory("refresh_wnba_oddsapi_props.rows_by_game_keys", list(rows_by_game.keys()))
    log_list_memory("refresh_wnba_oddsapi_props.rows_by_game_values", [row for group in rows_by_game.values() for row in group])

    if not rows_by_game:
        return 0

    boxscore_dir = processed_root / "boxscores"
    boxscore_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "personId",
        "teamTricode",
        "position",
        "minutes",
        "points",
        "reboundsTotal",
        "assists",
        "threePointersMade",
        "threePointersAttempted",
        "fieldGoalsMade",
        "fieldGoalsAttempted",
        "freeThrowsMade",
        "freeThrowsAttempted",
        "steals",
        "blocks",
        "turnovers",
        "foulsPersonal",
        "reboundsOffensive",
        "reboundsDefensive",
        "plusMinusPoints",
        "firstName",
        "familyName",
        "nameI",
    ]
    total_rows = 0
    for game_id, rows in rows_by_game.items():
        out_path = boxscore_dir / f"boxscore_{game_id}.csv"
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})
        total_rows += len(rows)
    return total_rows


def _build_local_optional_player_recon_artifacts(*, processed_root: Path, date_str: str) -> dict[str, str]:
    if _materialize_local_boxscore_cache_for_player_artifacts(processed_root=processed_root, date_str=date_str) <= 0:
        return {}

    copied: dict[str, str] = {}
    data_root = processed_root.parent
    vendor_root = REPO_ROOT / "vendor" / "wnba_betting_repo"
    tool_specs = (
        (
            vendor_root / "tools" / "build_recon_players.py",
            "syndicate_wnba_vendor_build_recon_players",
            "build_recon_players",
            processed_root / f"recon_players_{date_str}.csv",
            "recon_players_path",
        ),
        (
            vendor_root / "tools" / "build_live_player_lens_tuning.py",
            "syndicate_wnba_vendor_build_live_player_lens_tuning",
            "build_live_player_lens_tuning",
            processed_root / f"live_player_lens_tuning_{date_str}.csv",
            "live_player_lens_tuning_path",
        ),
    )
    original_nba_root = os.environ.get("NBA_BETTING_DATA_ROOT")
    original_wnba_root = os.environ.get("WNBA_BETTING_DATA_ROOT")
    try:
        os.environ["NBA_BETTING_DATA_ROOT"] = str(data_root)
        os.environ["WNBA_BETTING_DATA_ROOT"] = str(data_root)
        for module_path, module_name, function_name, out_path, copied_key in tool_specs:
            if not module_path.exists() or not module_path.is_file():
                continue
            try:
                module = _load_module_from_path(module_name, module_path)
                builder = getattr(module, function_name, None)
                if builder is None:
                    continue
                df = builder(date_str)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out_path, index=False)
                copied[copied_key] = str(out_path)
            except Exception:
                continue
    finally:
        if original_nba_root is None:
            os.environ.pop("NBA_BETTING_DATA_ROOT", None)
        else:
            os.environ["NBA_BETTING_DATA_ROOT"] = original_nba_root
        if original_wnba_root is None:
            os.environ.pop("WNBA_BETTING_DATA_ROOT", None)
        else:
            os.environ["WNBA_BETTING_DATA_ROOT"] = original_wnba_root
    return copied


def _target_refresh_dates(*, date_str: str, days_ahead: int) -> list[str]:
    parsed = dt.datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(parsed + dt.timedelta(days=offset)).isoformat() for offset in range(0, max(0, int(days_ahead)) + 1)]


def _run_playoff_transition_if_needed(*, source_root: Path, date_str: str) -> dict[str, object]:
    module_path = source_root / "src" / "wnba_betting" / "playoff_transition.py"
    if not module_path.exists() or not module_path.is_file():
        return {"status": "unavailable"}
    src_root = source_root / "src"
    try:
        src_root_text = str(src_root)
        inserted = False
        if src_root_text not in sys.path:
            sys.path.insert(0, src_root_text)
            inserted = True
        importlib.invalidate_caches()
        module = importlib.import_module("wnba_betting.playoff_transition")
        runner = getattr(module, "run_playoff_transition", None)
        if runner is None:
            return {"status": "unavailable"}
        summary = runner(target_date=dt.datetime.strptime(date_str, "%Y-%m-%d").date())
        return {"status": "ok", "summary": _json_ready(summary)}
    except Exception as exc:
        if isinstance(exc, ModuleNotFoundError):
            return {"status": "unavailable", "reason": f"missing dependency: {getattr(exc, 'name', 'unknown')}"}
        message = str(exc)
        lowered = message.lower()
        if "regular season has not completed" in lowered or "regular-season" in lowered:
            return {"status": "skipped", "reason": message}
        return {"status": "error", "error": message}
    finally:
        try:
            if inserted:
                sys.path.remove(src_root_text)
        except Exception:
            pass


def _load_source_app(source_root: Path):
    app_path = source_root / "app.py"
    if not app_path.exists() or not app_path.is_file():
        return None
    return _load_module_from_path("syndicate_wnba_source_app", app_path)


def _build_optional_player_recon_artifacts(*, source_root: Path, date_str: str, processed_root: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    existing_specs = (
        (f"recon_players_{date_str}.csv", "recon_players_path"),
        (f"live_player_lens_tuning_{date_str}.csv", "live_player_lens_tuning_path"),
    )
    for file_name, copied_key in existing_specs:
        existing = _copy_existing_processed_artifact(
            source_root=source_root,
            processed_root=processed_root,
            file_name=file_name,
        )
        if existing:
            copied[copied_key] = existing
    if len(copied) == len(existing_specs):
        return copied

    copied.update(_build_local_optional_player_recon_artifacts(processed_root=processed_root, date_str=date_str))
    return copied


def _export_top_by_game_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"props_recommendations_top_by_game_{date_str}.json",
    )
    if existing:
        return existing
    _, out_path = _build_local_top_by_game_snapshot(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _export_recommendations_slate_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recommendations_slate_{date_str}.json",
    )
    if existing:
        return existing
    _, out_path = _build_local_recommendations_slate_artifact(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _export_cards_props_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_props_snapshot_{date_str}.json",
    )
    if existing:
        return existing
    _, out_path = _build_local_cards_props_snapshot_artifact(processed_root=processed_root, date_str=date_str)
    return str(out_path) if out_path is not None else None


def _build_cards_sim_detail_from_local_smart_sim(*, processed_root: Path, date_str: str) -> list[dict[str, object]]:
    games_out: list[dict[str, object]] = []
    for path in sorted(processed_root.glob(f"smart_sim_{date_str}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        home_tri = str(payload.get("home") or "").strip().upper()
        away_tri = str(payload.get("away") or "").strip().upper()
        if not home_tri or not away_tri:
            stem = str(path.stem or "")
            prefix = f"smart_sim_{date_str}_"
            if stem.startswith(prefix):
                suffix = stem[len(prefix):]
                parts = suffix.split("_")
                if len(parts) >= 2:
                    home_tri = home_tri or str(parts[0] or "").strip().upper()
                    away_tri = away_tri or str(parts[1] or "").strip().upper()
        players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
        home_players = [row for row in (players.get("home") or []) if isinstance(row, dict)]
        away_players = [row for row in (players.get("away") or []) if isinstance(row, dict)]
        if not home_tri or not away_tri:
            continue
        missing = payload.get("missing_prop_players") if isinstance(payload.get("missing_prop_players"), dict) else {}
        injuries = payload.get("injuries") if isinstance(payload.get("injuries"), dict) else {}
        players_summary = payload.get("players_summary") if isinstance(payload.get("players_summary"), dict) else {}
        periods_payload = payload.get("periods") if isinstance(payload.get("periods"), dict) else {}
        quarters = []
        for quarter_number in range(1, 5):
            quarter_payload = periods_payload.get(f"q{quarter_number}") if isinstance(periods_payload.get(f"q{quarter_number}"), dict) else None
            if not isinstance(quarter_payload, dict):
                continue
            quarters.append(
                {
                    "q": int(quarter_number),
                    "away_pts_mu": quarter_payload.get("away_mean"),
                    "home_pts_mu": quarter_payload.get("home_mean"),
                    "total_mean": quarter_payload.get("total_mean"),
                    "margin_mean": quarter_payload.get("margin_mean"),
                    "p_home_win": quarter_payload.get("p_home_win"),
                }
            )
        summary = {
            "home": int(players_summary.get("home") or len(home_players)),
            "away": int(players_summary.get("away") or len(away_players)),
            "missing_home": int(players_summary.get("missing_home") or len(missing.get("home") or [])),
            "missing_away": int(players_summary.get("missing_away") or len(missing.get("away") or [])),
            "injured_home": int(players_summary.get("injured_home") or len(injuries.get("home") or [])),
            "injured_away": int(players_summary.get("injured_away") or len(injuries.get("away") or [])),
        }
        games_out.append(
            {
                "home_tri": home_tri,
                "away_tri": away_tri,
                "sim": {
                    "quarters": quarters,
                    "players_summary": summary,
                    "players": {
                        "home": home_players,
                        "away": away_players,
                    },
                    "missing_prop_players": {
                        "home": [row for row in (missing.get("home") or []) if isinstance(row, dict)],
                        "away": [row for row in (missing.get("away") or []) if isinstance(row, dict)],
                    },
                    "injuries": {
                        "home": [row for row in (injuries.get("home") or []) if isinstance(row, dict)],
                        "away": [row for row in (injuries.get("away") or []) if isinstance(row, dict)],
                    },
                },
            }
        )
    return games_out


def _export_cards_sim_detail_snapshot(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"cards_sim_detail_{date_str}.json",
    )
    if existing and _cards_sim_detail_has_quarter_content(Path(existing)):
        return existing
    out_path = processed_root / f"cards_sim_detail_{date_str}.json"
    games_out = _build_cards_sim_detail_from_local_smart_sim(processed_root=processed_root, date_str=date_str)
    if not games_out:
        source_app = _load_source_app(source_root)
        if source_app is not None:
            try:
                client = source_app.app.test_client()
                response = client.get(f"/api/cards?date={date_str}&include_players=1")
                payload = response.get_json() if response is not None else None
            except Exception:
                payload = None
            games = payload.get("games") if isinstance(payload, dict) and isinstance(payload.get("games"), list) else []
            for game in games:
                if not isinstance(game, dict):
                    continue
                home_tri = str(game.get("home_tri") or "").strip().upper()
                away_tri = str(game.get("away_tri") or "").strip().upper()
                sim = game.get("sim") if isinstance(game.get("sim"), dict) else None
                if not home_tri or not away_tri or not isinstance(sim, dict):
                    continue
                games_out.append(
                    {
                        "home_tri": home_tri,
                        "away_tri": away_tri,
                        "sim": sim,
                    }
                )
    if not games_out:
        return None

    out = {"date": date_str, "games": games_out}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return str(out_path)


def _build_local_recon_games_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"
    if not game_cards_path.exists() or not boxscores_path.exists():
        return 0, None

    games_by_id: dict[str, dict[str, str]] = {}
    with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            game_id = str((row or {}).get("game_id") or "").strip()
            if not game_id or game_id in games_by_id:
                continue
            games_by_id[game_id] = {
                "game_id": game_id,
                "home_team": str((row or {}).get("home_team") or "").strip(),
                "visitor_team": str((row or {}).get("visitor_team") or "").strip(),
                "home_tri": str((row or {}).get("home_tri") or "").strip().upper(),
                "away_tri": str((row or {}).get("away_tri") or "").strip().upper(),
            }

    if not games_by_id:
        return 0, None

    team_points_by_game: dict[str, dict[str, float]] = {}
    with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
            game_id = str(normalized.get("GAME_ID") or normalized.get("GAMEID") or "").strip()
            team_tri = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
            try:
                pts_value = float(normalized.get("PTS"))
            except (TypeError, ValueError):
                continue
            if not game_id or not team_tri:
                continue
            per_game = team_points_by_game.setdefault(game_id, {})
            per_game[team_tri] = float(per_game.get(team_tri, 0.0)) + pts_value

    rows: list[dict[str, str]] = []
    for game_id, game_row in games_by_id.items():
        home_tri = str(game_row.get("home_tri") or "").strip().upper()
        away_tri = str(game_row.get("away_tri") or "").strip().upper()
        points = team_points_by_game.get(game_id) or {}
        home_pts = points.get(home_tri)
        away_pts = points.get(away_tri)
        if not home_tri or not away_tri or home_pts is None or away_pts is None:
            continue
        total_actual = float(home_pts) + float(away_pts)
        rows.append(
            {
                "game_id": game_id,
                "home_team": str(game_row.get("home_team") or home_tri),
                "visitor_team": str(game_row.get("visitor_team") or away_tri),
                "home_tri": home_tri,
                "away_tri": away_tri,
                "home_pts": f"{home_pts:g}",
                "visitor_pts": f"{away_pts:g}",
                "total_actual": f"{total_actual:g}",
            }
        )

    if not rows:
        return 0, None

    out_path = processed_root / f"recon_games_{date_str}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["game_id", "home_team", "visitor_team", "home_tri", "away_tri", "home_pts", "visitor_pts", "total_actual"]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return len(rows), out_path


def _export_recon_games_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_games_{date_str}.csv",
    )
    if existing:
        return existing
    local_rows, local_path = _build_local_recon_games_artifact(processed_root=processed_root, date_str=date_str)
    if local_rows > 0 and local_path is not None:
        return str(local_path)
    if not _source_app_fallback_enabled():
        return None
    source_app = _load_source_app(source_root)
    if source_app is None:
        return None
    if hasattr(source_app, "_cron_auth_ok"):
        try:
            source_app._cron_auth_ok = lambda _request: True
        except Exception:
            pass
    client = source_app.app.test_client()
    response = client.get(f"/api/cron/reconcile-games?date={date_str}")
    try:
        payload = response.get_json() if response is not None else None
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        return None
    output_path = str(payload.get("output") or "").strip()
    if not output_path:
        return None
    source = Path(output_path)
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _build_local_live_lens_tuning_artifact(*, processed_root: Path, live_lens_root: Path) -> dict[str, str]:
    try:
        from syndicate.features.wnba.cards import build_live_lens_tuning_payload

        payload = build_live_lens_tuning_payload()
    except Exception:
        return {}
    if not isinstance(payload, dict) or not payload:
        return {}

    raw = json.dumps(payload, indent=2).encode("utf-8")
    outputs = (
        (processed_root / "live_lens_tuning_override.json", "live_lens_tuning_override_path"),
        (live_lens_root / "live_lens_tuning_override.json", "live_lens_tuning_override_live_lens_path"),
    )
    copied: dict[str, str] = {}
    for out_path, copied_key in outputs:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        copied[copied_key] = str(out_path)
    return copied


def _export_live_lens_artifacts(*, source_root: Path, date_str: str, processed_root: Path, live_lens_root: Path) -> dict[str, str]:
    exports = (
        (
            f"live_lens_signals_{date_str}.jsonl",
            f"/api/download_live_lens_signals?date={date_str}",
            (
                (processed_root / f"live_lens_signals_{date_str}.jsonl", "live_lens_signals_path"),
                (live_lens_root / f"live_lens_signals_{date_str}.jsonl", None),
            ),
        ),
        (
            f"live_lens_projections_{date_str}.jsonl",
            f"/api/download_live_lens_projections?date={date_str}",
            (
                (processed_root / f"live_lens_projections_{date_str}.jsonl", "live_lens_projections_path"),
                (live_lens_root / f"live_lens_projections_{date_str}.jsonl", None),
            ),
        ),
        (
            "live_lens_tuning_override.json",
            "/api/download_live_lens_tuning",
            (
                (processed_root / "live_lens_tuning_override.json", "live_lens_tuning_override_path"),
                (live_lens_root / "live_lens_tuning_override.json", "live_lens_tuning_override_live_lens_path"),
            ),
        ),
    )
    copied: dict[str, str] = {}
    missing_exports: list[tuple[str, str, tuple[tuple[Path, str | None], ...]]] = []
    for file_name, query, destinations in exports:
        existing = _copy_existing_live_lens_artifact(source_root=source_root, file_name=file_name, destinations=destinations)
        if existing:
            copied.update(existing)
            continue
        if file_name == f"live_lens_signals_{date_str}.jsonl":
            local = _build_local_live_lens_signals_artifact(processed_root=processed_root, date_str=date_str, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        if file_name == f"live_lens_projections_{date_str}.jsonl":
            local = _build_local_live_lens_projections_artifact(processed_root=processed_root, date_str=date_str, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        if file_name == "live_lens_tuning_override.json":
            local = _build_local_live_lens_tuning_artifact(processed_root=processed_root, live_lens_root=live_lens_root)
            if local:
                copied.update(local)
                continue
        missing_exports.append((file_name, query, destinations))
    if not missing_exports:
        return copied

    if not _source_app_fallback_enabled():
        return copied

    source_app = _load_source_app(source_root)
    if source_app is None:
        return copied
    client = source_app.app.test_client()
    for _file_name, query, destinations in missing_exports:
        try:
            response = client.get(query)
            status_code = int(getattr(response, "status_code", 0) or 0)
            if status_code != 200:
                continue
            raw = b""
            get_data = getattr(response, "get_data", None)
            if callable(get_data):
                raw = get_data()
            elif hasattr(response, "data"):
                raw = getattr(response, "data") or b""
            if not isinstance(raw, (bytes, bytearray)) or not raw:
                continue
            for out_path, copied_key in destinations:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(bytes(raw))
                if copied_key:
                    copied[copied_key] = str(out_path)
        except Exception:
            continue
    return copied


def _materialize_artifact_bundle(*, state: dict[str, object], artifact_root: Path, source_root: Path) -> dict[str, object]:
    processed_root = artifact_root / "data" / "processed"
    raw_root = artifact_root / "data" / "raw"
    live_lens_root = artifact_root / "data" / "live_lens"
    copied: dict[str, object] = {}
    artifact_map = {
        "snapshot_alias_path": processed_root / Path(str(state.get("snapshot_alias_path") or "")).name,
        "predictions_path": processed_root / Path(str(state.get("predictions_path") or "")).name,
        "edges_path": processed_root / Path(str(state.get("edges_path") or "")).name,
        "recs_path": processed_root / Path(str(state.get("recs_path") or "")).name,
        "snapshot_path": raw_root / Path(str(state.get("snapshot_path") or "")).name,
    }
    for key, destination in artifact_map.items():
        if _copy_if_exists(str(state.get(key) or ""), destination):
            copied[key] = str(destination)
    date_text = str(state.get("date") or "").strip()
    source_directory = _processed_source_directory(state)
    reuse_existing_run = bool(state.get("reused_existing_outputs") or state.get("reused_existing_artifact_bundle"))
    reuse_local_processed = False
    if source_directory is not None:
        try:
            reuse_local_processed = source_directory.resolve() == processed_root.resolve()
        except Exception:
            reuse_local_processed = source_directory == processed_root
    if date_text and source_directory is not None:
        smart_sim_files = _copy_matching_files(
            source_directory=source_directory,
            pattern=f"smart_sim_{date_text}_*.json",
            destination_directory=processed_root,
        )
        if smart_sim_files:
            copied["smart_sim_paths"] = smart_sim_files
        # Reused refresh states can still be incomplete, so always materialize the
        # render-facing WNBA exports into the published artifact tree.
        recon_games_path = _export_recon_games_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_games_path:
            copied["recon_games_path"] = recon_games_path
        recon_quarters_path = _export_recon_quarters_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_quarters_path:
            copied["recon_quarters_path"] = recon_quarters_path
        game_cards_path = _export_game_cards_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if game_cards_path:
            copied["game_cards_path"] = game_cards_path
        boxscores_path = _export_boxscores_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if boxscores_path:
            copied["boxscores_path"] = boxscores_path
        recommendations_path = _export_recommendations_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recommendations_path:
            copied["recommendations_path"] = recommendations_path
        recon_props_path = _export_recon_props_artifact(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recon_props_path:
            copied["recon_props_path"] = recon_props_path
        recommendations_slate_path = _export_recommendations_slate_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if recommendations_slate_path:
            copied["recommendations_slate_path"] = recommendations_slate_path
        cards_props_snapshot_path = _export_cards_props_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if cards_props_snapshot_path:
            copied["cards_props_snapshot_path"] = cards_props_snapshot_path
        cards_sim_detail_path = _export_cards_sim_detail_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if cards_sim_detail_path:
            copied["cards_sim_detail_path"] = cards_sim_detail_path
        top_by_game_path = _export_top_by_game_snapshot(source_root=source_root, date_str=date_text, processed_root=processed_root)
        if top_by_game_path:
            copied["top_by_game_path"] = top_by_game_path
        copied.update(_export_live_lens_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root, live_lens_root=live_lens_root))
        copied.update(_build_optional_player_recon_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
        if not reuse_existing_run:
            copied.update(_export_live_snapshot_artifacts(source_root=source_root, date_str=date_text, processed_root=processed_root))
    boxscores_history_path = _refresh_boxscores_history_artifact(source_root=source_root, processed_root=processed_root)
    if boxscores_history_path:
        copied["boxscores_history_path"] = boxscores_history_path
    advanced_stats_paths = _export_team_advanced_stats_artifacts(source_root=source_root, processed_root=processed_root)
    if advanced_stats_paths:
        copied["team_advanced_stats_paths"] = advanced_stats_paths
    for transition_path in sorted((source_root / "data" / "processed").glob(f"playoff_transition_*_{date_text}.json")):
        if not transition_path.is_file():
            continue
        destination = processed_root / transition_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(transition_path, destination)
        copied.setdefault("playoff_transition_paths", []).append(str(destination))
    return copied


def _load_source_cli(source_root: Path):
    raise RuntimeError("source CLI fallback removed; use local artifacts or local Syndicate builders")


def _export_recon_quarters_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_quarters_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"recon_quarters_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _build_local_recon_props_artifact(*, processed_root: Path, date_str: str) -> tuple[int, Path | None]:
    boxscores_path = processed_root / f"boxscores_{date_str}.csv"
    if not boxscores_path.exists():
        return 0, None

    game_cards_path = processed_root / f"game_cards_{date_str}.csv"
    team_to_game_id: dict[str, str] = {}
    if game_cards_path.exists():
        with game_cards_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                game_id = str((row or {}).get("game_id") or "").strip()
                if not game_id:
                    continue
                for team_key in ("home_tri", "away_tri"):
                    team_tri = str((row or {}).get(team_key) or "").strip().upper()
                    if team_tri and team_tri not in team_to_game_id:
                        team_to_game_id[team_tri] = game_id

    rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    with boxscores_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {str(key or "").strip().upper(): value for key, value in (row or {}).items()}
            game_id = str(normalized.get("GAME_ID") or normalized.get("GAMEID") or "").strip()
            team_abbr = str(normalized.get("TEAM_ABBREVIATION") or normalized.get("TEAM") or "").strip().upper()
            if not game_id and team_abbr:
                game_id = str(team_to_game_id.get(team_abbr) or "").strip()
            player_name = str(normalized.get("PLAYER_NAME") or normalized.get("PLAYER") or "").strip()
            player_id = str(normalized.get("PLAYER_ID") or "").strip()
            if not game_id or not player_name:
                continue

            dedupe_key = (game_id, team_abbr, player_name.casefold())
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            def _stat_value(*keys: str) -> str:
                for key in keys:
                    value = normalized.get(key)
                    if value is None:
                        continue
                    text = str(value).strip()
                    if text:
                        return text
                return ""

            pts = _stat_value("PTS")
            reb = _stat_value("REB")
            ast = _stat_value("AST")
            threes = _stat_value("FG3M", "FG3_M")
            stl = _stat_value("STL")
            blk = _stat_value("BLK")
            tov = _stat_value("TOV", "TO")

            pra = ""
            pr = ""
            pa = ""
            ra = ""
            try:
                pts_num = float(pts) if pts else None
                reb_num = float(reb) if reb else None
                ast_num = float(ast) if ast else None
            except ValueError:
                pts_num = reb_num = ast_num = None
            if pts_num is not None and reb_num is not None:
                pr = f"{pts_num + reb_num:g}"
            if pts_num is not None and ast_num is not None:
                pa = f"{pts_num + ast_num:g}"
            if reb_num is not None and ast_num is not None:
                ra = f"{reb_num + ast_num:g}"
            if pts_num is not None and reb_num is not None and ast_num is not None:
                pra = f"{pts_num + reb_num + ast_num:g}"

            rows.append(
                {
                    "game_id": game_id,
                    "player_id": player_id,
                    "player_name": player_name,
                    "team_abbr": team_abbr,
                    "pts": pts,
                    "reb": reb,
                    "ast": ast,
                    "threes": threes,
                    "stl": stl,
                    "blk": blk,
                    "tov": tov,
                    "pr": pr,
                    "pa": pa,
                    "ra": ra,
                    "pra": pra,
                }
            )

    if not rows:
        return 0, None

    out_path = processed_root / f"recon_props_{date_str}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["game_id", "player_id", "player_name", "team_abbr", "pts", "reb", "ast", "threes", "stl", "blk", "tov", "pr", "pa", "ra", "pra"]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return len(rows), out_path


def _export_recon_props_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recon_props_{date_str}.csv",
    )
    if existing:
        return existing
    local_rows, local_path = _build_local_recon_props_artifact(processed_root=processed_root, date_str=date_str)
    if local_rows > 0 and local_path is not None:
        return str(local_path)
    source = source_root / "data" / "processed" / f"recon_props_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _export_game_cards_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"game_cards_{date_str}.csv",
    )
    if existing:
        return existing
    local_rows, local_path = _build_local_game_cards_artifact(
        source_root=source_root,
        processed_root=processed_root,
        date_str=date_str,
        log_file=None,
    )
    if local_rows > 0 and local_path is not None:
        return str(local_path)
    source = source_root / "data" / "processed" / f"game_cards_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _export_boxscores_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"boxscores_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"boxscores_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _export_recommendations_artifact(*, source_root: Path, date_str: str, processed_root: Path) -> str | None:
    existing = _copy_existing_processed_artifact(
        source_root=source_root,
        processed_root=processed_root,
        file_name=f"recommendations_{date_str}.csv",
    )
    if existing:
        return existing
    source = source_root / "data" / "processed" / f"recommendations_{date_str}.csv"
    if not source.exists() or not source.is_file():
        return None
    destination = processed_root / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the WNBA OddsAPI props refresh job through a Syndicate-owned entrypoint.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--regions", default="us")
    parser.add_argument("--bookmakers", default="")
    parser.add_argument("--markets", default="")
    parser.add_argument("--source-root")
    parser.add_argument("--log-file", required=True)
    parser.add_argument("--artifact-root")
    parser.add_argument("--do-edges", action="store_true")
    parser.add_argument("--do-export", action="store_true")
    parser.add_argument("--do-push", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--days-ahead", type=int, default=0)
    parser.add_argument("--started-at")
    parser.add_argument("--mode", choices=("fast", "full"), default="full")
    args = parser.parse_args()

    source_root_arg = str(args.source_root or "").strip()
    source_root = Path(source_root_arg).resolve() if source_root_arg else None
    artifact_root = str(args.artifact_root or "").strip()
    fast_mode = str(args.mode or "full").strip().lower() == "fast"
    target_dates = _target_refresh_dates(date_str=args.date, days_ahead=int(args.days_ahead or 0))
    states: list[dict[str, object]] = []
    artifact_root_path = Path(artifact_root).resolve() if artifact_root else None
    for index, target_date in enumerate(target_dates):
        state = None
        started_at = args.started_at if index == 0 else None
        source_root_for_inputs = source_root if source_root is not None else (artifact_root_path or Path(artifact_root or ".")).resolve()
        refresh_input_hash = _refresh_step_input_hash(
            source_root=source_root_for_inputs,
            processed_root=(source_root_for_inputs / "data" / "processed"),
            date_str=target_date,
            do_edges=bool(args.do_edges),
            do_export=bool(args.do_export),
            artifact_root=artifact_root_path,
        )
        if source_root is not None and not bool(args.force_refresh):
            state = _existing_refresh_state(
                source_root=source_root,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
                input_hash=refresh_input_hash,
            )
        if state is None and artifact_root and not bool(args.force_refresh):
            state = _existing_artifact_bundle_state(
                artifact_root=artifact_root_path,
                date_str=target_date,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                started_at=started_at,
                input_hash=refresh_input_hash,
            )
        if state is None:
            if source_root is None:
                state = {
                    "date": str(target_date),
                    "error": "source-root is required when no reusable artifact bundle is available",
                    "artifact_bundle_root": str(artifact_root_path) if artifact_root_path else None,
                }
                states.append(state)
                continue
            state = _run_refresh_via_cli(
                source_root=source_root,
                date_str=target_date,
                regions=args.regions,
                bookmakers=args.bookmakers,
                markets=args.markets,
                do_edges=bool(args.do_edges),
                do_export=bool(args.do_export),
                do_push=bool(args.do_push),
                smart_sim_overwrite=bool(args.force_refresh),
                log_file=Path(args.log_file).resolve(),
                started_at=started_at,
                mode=str(args.mode or "full"),
            )
            if state is None:
                state = {
                    "date": str(target_date),
                    "error": f"refresh runner returned no state for {target_date}",
                    "artifact_bundle_root": str(artifact_root_path) if artifact_root_path else None,
                }
        if source_root is not None:
            state["playoff_transition"] = _run_playoff_transition_if_needed(source_root=source_root, date_str=target_date)
        if source_root is not None and artifact_root_path is not None:
            # Live game state (score/period/clock, ESPN-sourced) is cheap and has nothing
            # to do with whether odds/props inputs changed, so refresh it every tick
            # regardless of fast/full mode or whether the rest of this run reused a
            # cached bundle. Without this, live snapshots only ever get written once,
            # since _materialize_artifact_bundle below is skipped entirely in fast mode.
            try:
                _export_live_snapshot_artifacts(
                    source_root=source_root,
                    date_str=str(target_date),
                    processed_root=artifact_root_path / "data" / "processed",
                )
            except Exception as exc:
                print(f"[refresh_wnba_oddsapi_props] LIVE_SNAPSHOT_REFRESH_FAILED date={target_date} error={type(exc).__name__}: {exc}", flush=True)
        if not fast_mode and artifact_root_path and source_root is not None and not state.get("reused_existing_artifact_bundle"):
            copied = _materialize_artifact_bundle(
                state=state,
                artifact_root=artifact_root_path,
                source_root=source_root,
            )
            if copied:
                state["artifact_bundle_root"] = str(artifact_root_path)
                state["artifact_bundle_files"] = copied
        if state and not state.get("error"):
            record_refresh_state(
                f"wnba_artifact_bundle:{_refresh_state_scope_path(artifact_root_path)}:{target_date}:{int(bool(args.do_edges))}:{int(bool(args.do_export))}",
                refresh_input_hash,
                metadata={
                    "date": target_date,
                    "reused": bool(state.get("reused_existing_outputs") or state.get("reused_existing_artifact_bundle")),
                    "artifact_root": str(artifact_root_path) if artifact_root_path else None,
                },
            )
        states.append(state)
    log_list_memory("refresh_wnba_oddsapi_props.states", states)
    state = states[0] if states else {"date": str(args.date), "error": "no refresh states generated"}
    if len(states) > 1:
        state["lookahead_runs"] = states[1:]
    print(json.dumps(_json_ready(state), indent=2, sort_keys=True))

    snapshot_rows = int(state.get("snapshot_rows") or 0)
    alias_rows = int(state.get("snapshot_alias_rows") or 0)
    edges_rows = int(state.get("edges_rows") or 0)
    recs_rows = int(state.get("recs_rows") or 0)
    if state.get("error"):
        return 1
    for extra_state in states[1:]:
        if extra_state.get("error"):
            return 1
    if snapshot_rows > 0 and alias_rows <= 0:
        return 1
    if bool(args.do_edges) and snapshot_rows > 0 and edges_rows <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())