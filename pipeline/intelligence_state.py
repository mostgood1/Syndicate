from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping

from flask import Flask
from flask import current_app

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.intelligence import build_intelligence_overview
from syndicate.features.intelligence import _build_board_dictionary
from syndicate.features.intelligence import _balanced_recommendation_order
from syndicate.features.intelligence import collect_candidates
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import _apply_candidate_tier_penalty
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_roots_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import normalize_timestamped_payload


REPO_ROOT = repo_root_from(__file__)
STATE_PATH = reports_root() / "intelligence" / "query_state_cache.json"
BOARD_SNAPSHOT_PATH = reports_root() / "intelligence" / "board_snapshot.json"
STATUS_CACHE_PATH = reports_root() / "intelligence" / "status_response_cache.json"
INTELLIGENCE_STATE_PATH = reports_root() / "intelligence" / "intelligence_state.json"
INTELLIGENCE_HISTORY_PATH = reports_root() / "intelligence" / "intelligence_state_history.jsonl"
logger = logging.getLogger(__name__)
_INTELLIGENCE_EXECUTION_GUARD = threading.RLock()
_INTELLIGENCE_LAST_RUN_STARTED_AT: float = 0.0
_INTELLIGENCE_LAST_RUN_FINISHED_AT: float = 0.0
_INTELLIGENCE_LAST_RUN_KEY: str | None = None
_INTELLIGENCE_GUARD_OWNER = threading.local()


def _state_backend_kind() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_BACKEND") or "filesystem").strip().lower()
    if value in {"redis", "keyvalue", "valkey"}:
        return "keyvalue"
    return "filesystem"


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "t", "yes", "y", "on"}


def _stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.pop("user_profile", None)
    normalized.pop("force_refresh", None)
    return normalized


def _payload_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_stable_payload(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_from_epoch(epoch_seconds: float) -> str | None:
    if epoch_seconds <= 0.0:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _timestamp_age_seconds(timestamp: str | None) -> float | None:
    value = str(timestamp or "").strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=None)
        try:
            epoch = time.mktime(parsed.timetuple())
        except Exception:
            return None
    else:
        epoch = parsed.timestamp()
    return max(0.0, time.time() - float(epoch))


def _selected_date_from_payload(payload: dict[str, Any] | None) -> str | None:
    current = dict(payload or {})
    return str(current.get("date") or current.get("selected_date") or "").strip() or None


def _selected_date_from_response(response: dict[str, Any] | None) -> str | None:
    current = dict(response or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    nested = dict(nested or {})
    for key in ("selected_date", "date"):
        value = str(nested.get(key) or current.get(key) or "").strip()
        if value:
            return value
    return None


def _utc_timestamp_string(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _board_contract_cards(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    current = dict(state or {})
    sources: list[Mapping[str, Any]] = []

    def _collect(board_contract: Mapping[str, Any] | None) -> None:
        if not isinstance(board_contract, Mapping):
            return
        cards = board_contract.get("cards")
        if isinstance(cards, list) and cards:
            sources.extend(item for item in cards if isinstance(item, Mapping))
            return
        for key in ("top_overall", "live", "pregame"):
            items = board_contract.get(key)
            if isinstance(items, list):
                sources.extend(item for item in items if isinstance(item, Mapping))

    _collect(current.get("board_contract") if isinstance(current.get("board_contract"), Mapping) else None)
    if not sources:
        _collect(current.get("boardContract") if isinstance(current.get("boardContract"), Mapping) else None)

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in sources:
        key = "|".join(
            part
            for part in (
                str(item.get("recommendation_id") or "").strip().lower(),
                str(item.get("candidate_id") or "").strip().lower(),
                str(item.get("prediction_id") or "").strip().lower(),
                str(item.get("name") or item.get("player_name") or item.get("selection") or item.get("pick") or "").strip().lower(),
                str(item.get("market") or item.get("market_key") or "").strip().lower(),
            )
            if part
        )
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(dict(item))
    return deduped


def _promote_board_contract_cards(state: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(state or {})
    cards = _board_contract_cards(current)
    if not cards:
        return current

    live_cards = [dict(item) for item in cards if bool(item.get("is_live")) or str(item.get("lane") or "").strip().lower() == "live"]

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        current["top_opportunities"] = [dict(item) for item in cards]

    if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
        current["recommendations"] = [dict(item) for item in cards]

    if not isinstance(current.get("by_sport"), dict) or not current.get("by_sport"):
        by_sport: dict[str, list[dict[str, Any]]] = {}
        for item in cards:
            sport_key = str(item.get("sport") or item.get("sport_slug") or "unknown").strip().lower() or "unknown"
            by_sport.setdefault(sport_key, []).append(dict(item))
        current["by_sport"] = by_sport

    if not isinstance(current.get("top_live_opportunities"), list) or not current.get("top_live_opportunities"):
        current["top_live_opportunities"] = [dict(item) for item in live_cards]

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        analysis = dict(analysis)
        if not isinstance(analysis.get("recommendations"), list) or not analysis.get("recommendations"):
            analysis["recommendations"] = [dict(item) for item in cards]
        if not isinstance(analysis.get("picks"), list) or not analysis.get("picks"):
            analysis["picks"] = [dict(item) for item in cards]
        if not isinstance(analysis.get("top_live_opportunities"), list) or not analysis.get("top_live_opportunities"):
            analysis["top_live_opportunities"] = [dict(item) for item in live_cards]
        current["analysis"] = analysis

    response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(response, dict):
        response = dict(response)
        if not isinstance(response.get("top_opportunities"), list) or not response.get("top_opportunities"):
            response["top_opportunities"] = [dict(item) for item in cards]
        if not isinstance(response.get("recommendations"), list) or not response.get("recommendations"):
            response["recommendations"] = [dict(item) for item in cards]
        if not isinstance(response.get("top_live_opportunities"), list) or not response.get("top_live_opportunities"):
            response["top_live_opportunities"] = [dict(item) for item in live_cards]
        if isinstance(analysis, dict):
            response["analysis"] = analysis
        current["response"] = response

    return current


def _intelligence_state_candidate_count(state: dict[str, Any] | None) -> int:
    current = dict(state or {})
    opportunities = current.get("top_opportunities")
    if isinstance(opportunities, list) and opportunities:
        return len([item for item in opportunities if isinstance(item, Mapping)])
    recommendations = current.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        return len([item for item in recommendations if isinstance(item, Mapping)])
    board_cards = _board_contract_cards(current)
    if board_cards:
        return len(board_cards)
    return 0


def _normalize_intelligence_state_payload(state: dict[str, Any] | None) -> dict[str, Any] | None:
    current = dict(state or {})
    if not current:
        return None
    current = _promote_board_contract_cards(current)
    candidate_count = _intelligence_state_candidate_count(current)
    current["candidate_count"] = candidate_count
    nested_response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(nested_response, dict):
        nested_response = dict(nested_response)
        nested_response["candidate_count"] = candidate_count
        current["response"] = nested_response
    return current


def _freshness_status_from_age(age_seconds: float | None, sla_seconds: int) -> str:
    if age_seconds is None:
        return "unknown"
    return "fresh" if age_seconds <= float(sla_seconds) else "stale"


def _snapshot_state_meta(snapshot: "IntelligenceSnapshot | None", *, source: str | None = None, run_key: str | None = None, sla_seconds: int | None = None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "source": source,
            "computed_at": None,
            "age_seconds": None,
            "freshness_sla_seconds": int(sla_seconds or 0),
            "freshness_status": "unknown",
            "is_fresh": False,
            "source_fingerprint": None,
            "run_key": run_key,
            "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
            "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        }
    age_seconds = _timestamp_age_seconds(snapshot.computed_at)
    freshness_sla_seconds = int(sla_seconds if sla_seconds is not None else _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
    freshness_status = _freshness_status_from_age(age_seconds, freshness_sla_seconds)
    return {
        "source": source,
        "computed_at": snapshot.computed_at,
        "age_seconds": age_seconds,
        "freshness_sla_seconds": freshness_sla_seconds,
        "freshness_status": freshness_status,
        "is_fresh": freshness_status == "fresh",
        "source_fingerprint": snapshot.source_fingerprint,
        "run_key": run_key or snapshot.key,
        "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
        "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
    }


def _decorate_response_with_state_meta(response: dict[str, Any] | None, snapshot: "IntelligenceSnapshot | None", *, source: str | None = None, run_key: str | None = None, sla_seconds: int | None = None) -> dict[str, Any] | None:
    current = dict(response or {})
    if not current:
        return None
    if snapshot is None:
        computed_at = str(current.get("state_last_updated") or current.get("last_updated") or current.get("updated_at") or "").strip() or None
        age_seconds = _timestamp_age_seconds(computed_at)
        freshness_sla_seconds = int(sla_seconds if sla_seconds is not None else _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
        freshness_status = _freshness_status_from_age(age_seconds, freshness_sla_seconds)
        state_meta = {
            "source": source,
            "computed_at": computed_at,
            "age_seconds": age_seconds,
            "freshness_sla_seconds": freshness_sla_seconds,
            "freshness_status": freshness_status,
            "is_fresh": freshness_status == "fresh",
            "source_fingerprint": current.get("source_fingerprint"),
            "run_key": run_key,
            "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
            "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        }
    else:
        state_meta = _snapshot_state_meta(snapshot, source=source, run_key=run_key, sla_seconds=sla_seconds)
    current.setdefault("state_meta", state_meta)
    current.setdefault("freshness", dict(current.get("state_meta") or {}))
    current.setdefault("state_freshness", dict(current.get("state_meta") or {}))
    current.setdefault("state_last_updated", str(current.get("state_last_updated") or current.get("last_updated") or current.get("updated_at") or (snapshot.computed_at if snapshot else "")).strip() or None)
    current.setdefault("source_fingerprint", snapshot.source_fingerprint if snapshot is not None else current.get("source_fingerprint"))
    return current


def _intelligence_state_daily_suffix() -> str:
    return central_today_iso().replace("-", "_")


def _intelligence_state_daily_paths() -> dict[str, Path]:
    suffix = _intelligence_state_daily_suffix()
    base_dir = reports_root() / "intelligence"
    return {
        "state": base_dir / f"intelligence_state_{suffix}.json",
        "history": base_dir / f"intelligence_state_history_{suffix}.jsonl",
        "board_snapshot": base_dir / f"board_snapshot_{suffix}.json",
    }


def _intelligence_state_daily_candidates() -> dict[str, list[Path]]:
    base_dir = reports_root() / "intelligence"
    return {
        "state": [path for path in sorted(base_dir.glob("intelligence_state_*.json"), reverse=True) if path.is_file()],
        "history": [path for path in sorted(base_dir.glob("intelligence_state_history_*.jsonl"), reverse=True) if path.is_file()],
        "board_snapshot": [path for path in sorted(base_dir.glob("board_snapshot_*.json"), reverse=True) if path.is_file()],
    }


def _intelligence_state_read_path(artifact_name: str, fallback_path: Path) -> Path:
    daily_paths = _intelligence_state_daily_paths()
    daily_candidates = _intelligence_state_daily_candidates().get(artifact_name, [])
    for path in [daily_paths.get(artifact_name), *daily_candidates, fallback_path]:
        if isinstance(path, Path) and path.exists() and path.is_file():
            return path
    return fallback_path


def _intelligence_state_history_entry(state: dict[str, Any]) -> dict[str, Any]:
    response = state.get("response") if isinstance(state.get("response"), dict) else {}
    top_opportunities = response.get("top_opportunities") if isinstance(response, dict) and isinstance(response.get("top_opportunities"), list) else state.get("top_opportunities")
    opportunity_names = [str(item.get("name") or item.get("selection") or item.get("pick") or "").strip() for item in top_opportunities or [] if isinstance(item, Mapping)]
    opportunity_names = [name for name in opportunity_names if name]
    return normalize_timestamped_payload({
        "updated_at": _utc_now(),
        "last_updated": str(state.get("last_updated") or response.get("last_updated") or "").strip() or None,
        "selected_date": str(state.get("selected_date") or response.get("selected_date") or response.get("date") or "").strip() or None,
        "candidate_count": _intelligence_state_candidate_count(state),
        "top_opportunity_names": opportunity_names,
        "board_contract_schema": str((response.get("board_contract") or state.get("board_contract") or {}).get("schema") or "").strip() or None if isinstance((response.get("board_contract") or state.get("board_contract") or {}), dict) else None,
    })


def _is_intelligence_state_payload_valid(state: dict[str, Any] | None) -> bool:
    current = dict(state or {})
    if not current:
        return False
    if any(key in current for key in ("top_opportunities", "by_sport", "analysis", "portfolio", "parlays")):
        return True
    if _board_contract_cards(current):
        return True
    nested_response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(nested_response, dict) and any(key in nested_response for key in ("top_opportunities", "by_sport", "analysis", "portfolio", "parlays")):
        return True
    if _board_contract_cards(nested_response if isinstance(nested_response, dict) else None):
        return True
    return False


def read_intelligence_state() -> dict[str, Any] | None:
    path = _intelligence_state_read_path("state", INTELLIGENCE_STATE_PATH)
    print("[INTELLIGENCE STATE READ]", {"path": str(path)})
    payload = read_json_file(path)
    normalized = _normalize_intelligence_state_payload(payload if isinstance(payload, dict) else None)
    if not _is_intelligence_state_payload_valid(normalized):
        print("[INTELLIGENCE STATE READ]", {"path": str(path), "valid": False, "candidate_count": 0})
        return None
    print("[INTELLIGENCE STATE READ]", {"path": str(path), "valid": True, "candidate_count": int(normalized.get("candidate_count") or 0)})
    return normalized


def write_intelligence_state(state: dict[str, Any]) -> dict[str, Any] | None:
    return write_latest_intelligence_state(state)


def write_latest_intelligence_state(state: Any) -> dict[str, Any] | None:
    if hasattr(state, "to_dict") and callable(getattr(state, "to_dict")):
        state = state.to_dict()
    normalized = normalize_timestamped_payload(_normalize_intelligence_state_payload(state if isinstance(state, dict) else None))
    if not _is_intelligence_state_payload_valid(normalized):
        logger.info("STATE WRITTEN", extra={"written": False, "candidate_count": 0})
        return None
    candidate_count = int(normalized.get("candidate_count") or 0)
    logger.info("INTELLIGENCE STATE PERSIST BEFORE", extra={"candidate_count": candidate_count})
    daily_paths = _intelligence_state_daily_paths()
    state_meta = dict(normalized.get("state_meta") or {})
    board_snapshot_payload = {
        "updated_at": _utc_now(),
        "response": dict(normalized),
        "state_meta": state_meta,
        "board_contract": normalized.get("board_contract") if isinstance(normalized.get("board_contract"), dict) else None,
    }
    write_json_file(INTELLIGENCE_STATE_PATH, normalized)
    write_json_file(daily_paths["state"], normalized)
    history_entry = _intelligence_state_history_entry(normalized)
    INTELLIGENCE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INTELLIGENCE_HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(history_entry, sort_keys=True, ensure_ascii=False, default=str))
        history_file.write("\n")
    daily_paths["history"].parent.mkdir(parents=True, exist_ok=True)
    with daily_paths["history"].open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(history_entry, sort_keys=True, ensure_ascii=False, default=str))
        history_file.write("\n")
    write_json_file(BOARD_SNAPSHOT_PATH, board_snapshot_payload)
    write_json_file(daily_paths["board_snapshot"], board_snapshot_payload)
    logger.info("INTELLIGENCE STATE PERSIST AFTER", extra={"candidate_count": candidate_count})
    logger.info("STATE WRITTEN", extra={"written": True, "candidate_count": int(normalized.get("candidate_count") or 0)})
    return normalized


def _intelligence_guard_is_busy() -> bool:
    return bool(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0)) or _INTELLIGENCE_EXECUTION_GUARD._is_owned()  # type: ignore[attr-defined]


def acquire_intelligence_execution_guard() -> bool:
    acquired = _INTELLIGENCE_EXECUTION_GUARD.acquire(blocking=False)
    if acquired:
        _INTELLIGENCE_GUARD_OWNER.depth = int(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0)) + 1
    return acquired


def release_intelligence_execution_guard() -> None:
    depth = int(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0))
    if depth > 0:
        _INTELLIGENCE_GUARD_OWNER.depth = depth - 1
        _INTELLIGENCE_EXECUTION_GUARD.release()


def intelligence_guard_last_run_state() -> dict[str, Any]:
    return {
        "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
        "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        "last_run_key": _INTELLIGENCE_LAST_RUN_KEY,
        "busy": _intelligence_guard_is_busy(),
    }


def _update_intelligence_guard_run_state(*, key: str | None = None, started_at: float | None = None, finished_at: float | None = None) -> None:
    global _INTELLIGENCE_LAST_RUN_STARTED_AT
    global _INTELLIGENCE_LAST_RUN_FINISHED_AT
    global _INTELLIGENCE_LAST_RUN_KEY
    if started_at is not None:
        _INTELLIGENCE_LAST_RUN_STARTED_AT = float(started_at)
    if finished_at is not None:
        _INTELLIGENCE_LAST_RUN_FINISHED_AT = float(finished_at)
    if key is not None:
        _INTELLIGENCE_LAST_RUN_KEY = key


def get_latest_intelligence_cached_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    normalized_payload = payload or {"question": "top edges today", "date": central_today_iso()}
    service = _INTELLIGENCE_STATE_SERVICE
    response = service.read_latest_response(normalized_payload, force_refresh=False)
    return _promote_board_contract_cards(response) if isinstance(response, dict) else response


def _get_cached_or_latest_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return get_latest_intelligence_cached_response(payload)


def _log_stage_timing(stage_name: str, duration_ms: float) -> None:
    logger.info(json.dumps({"stage": stage_name, "duration_ms": round(duration_ms, 3)}, sort_keys=True, default=str))


def _profile_stage(stage_name: str, callback, *args, **kwargs):
    started_at = time.perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        _log_stage_timing(stage_name, (time.perf_counter() - started_at) * 1000.0)


@dataclass
class IntelligenceSnapshot:
    key: str
    payload: dict[str, Any]
    response: dict[str, Any]
    computed_at: str
    source_fingerprint: str


class IntelligenceStateService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._execution_guard = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._interval_seconds = max(10, _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
        self._wait_timeout_seconds = 30
        self._max_snapshots = max(5, _env_int("SYNDICATE_INTELLIGENCE_MAX_SNAPSHOTS", 12))
        self._snapshots: OrderedDict[str, IntelligenceSnapshot] = OrderedDict()
        self._watched_payloads: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending_keys: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._candidate_pools: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._source_fingerprints: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._latest_key: str | None = None
        self._last_run_started_at: float = 0.0
        self._last_run_finished_at: float = 0.0
        self._last_run_key: str | None = None
        self._loaded_from_disk = False
        self._app: Flask | None = None

    def _artifact_signature(self, relative_path: str | None) -> dict[str, Any]:
        path_text = str(relative_path or "").strip()
        if not path_text:
            return {"path": "", "exists": False, "size": None, "mtime_ns": None}
        path = Path(path_text)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            stat_result = path.stat()
        except OSError:
            return {"path": path_text, "exists": False, "size": None, "mtime_ns": None}
        return {
            "path": path_text,
            "exists": True,
            "size": int(stat_result.st_size),
            "mtime_ns": int(stat_result.st_mtime_ns),
        }

    def _sport_manifest_signature(self, sport_slug: str) -> dict[str, Any]:
        manifest_path = reports_root() / "manifests" / f"{str(sport_slug or '').strip().lower()}.json"
        signature = self._artifact_signature(str(manifest_path))
        manifest = read_json_file(manifest_path)
        if isinstance(manifest, dict):
            signature.update(
                {
                    "sport": str(manifest.get("sport") or "").strip().lower(),
                    "last_updated": str(manifest.get("last_updated") or "").strip(),
                    "status": str(manifest.get("status") or "").strip().lower(),
                    "artifact_path_count": len(manifest.get("artifact_paths") or []) if isinstance(manifest.get("artifact_paths"), list) else 0,
                }
            )
        signature["odds_history"] = self._odds_history_signature(sport_slug)
        return signature

    def _odds_history_signature(self, sport_slug: str) -> dict[str, Any]:
        candidate_paths = self._odds_history_paths_for_sport(sport_slug)
        active_path: Path | None = None
        active_payload: dict[str, Any] | None = None
        for candidate_path in candidate_paths:
            payload = read_json_file(candidate_path)
            if isinstance(payload, dict):
                active_path = candidate_path
                active_payload = payload
                break

        if active_payload is None:
            return {
                "path": None,
                "exists": False,
                "payload_hash": None,
                "updated_at": None,
                "market_count": 0,
            }

        canonical_payload = json.dumps(active_payload, sort_keys=True, separators=(",", ":"), default=str)
        markets = active_payload.get("markets") if isinstance(active_payload.get("markets"), dict) else {}
        market_count = len(markets) if isinstance(markets, dict) else 0
        return {
            "path": str(active_path) if active_path is not None else None,
            "exists": True,
            "payload_hash": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
            "updated_at": str(active_payload.get("updated_at") or "").strip() or None,
            "market_count": int(market_count),
        }

    def _available_sport_manifests(self, selected_date: str | None) -> OrderedDict[str, dict[str, Any]]:
        status = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date, force_refresh=False)
        manifests: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for sport in status.get("sports") if isinstance(status.get("sports"), list) else []:
            if not isinstance(sport, dict):
                continue
            sport_slug = str(sport.get("slug") or "").strip().lower()
            if not sport_slug or sport_slug in manifests:
                continue
            manifest_path = reports_root() / "manifests" / f"{sport_slug}.json"
            manifest = read_json_file(manifest_path)
            if not isinstance(manifest, dict):
                continue
            manifests[sport_slug] = manifest
        return manifests

    @staticmethod
    def _merge_candidate_pools(candidate_pools: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for sport_candidates in candidate_pools.values():
            for candidate in sport_candidates:
                if isinstance(candidate, Mapping):
                    merged.append(dict(candidate))
        return sorted(merged, key=lambda candidate: _numeric_hint(candidate.get("score")) or 0.0, reverse=True)

    @staticmethod
    def _candidate_numeric_value(candidate: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = candidate.get(key)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip()
            if not text:
                continue
            try:
                return float(text.replace("%", ""))
            except Exception:
                continue
        return None

    @staticmethod
    def _candidate_timestamp_value(candidate: dict[str, Any]) -> float | None:
        for key in ("updated_epoch", "timestamp_epoch"):
            value = candidate.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            try:
                text = str(value or "").strip()
                if text:
                    return float(text)
            except Exception:
                pass
        for key in ("updated_at", "last_updated", "last_updated_at", "timestamp", "generated_at", "created_at"):
            text = str(candidate.get(key) or "").strip()
            if not text:
                continue
            normalized = text.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized).timestamp()
            except Exception:
                continue
        return None

    @classmethod
    def _rank_fallback_candidates(cls, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float]:
            score = cls._candidate_numeric_value(
                candidate,
                "score",
                "adjusted_score",
                "source_summary_score",
                "ev_current",
                "expected_value",
                "normalized_edge",
                "edge",
            )
            confidence = cls._candidate_numeric_value(
                candidate,
                "confidence",
                "model_probability",
                "implied_probability",
            )
            timestamp = cls._candidate_timestamp_value(candidate)
            return (
                1.0 if score is not None else 0.0,
                float(score or 0.0),
                float(confidence or 0.0),
                float(timestamp or 0.0),
            )

        return sorted((dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)), key=sort_key, reverse=True)

    def _odds_history_roots_for_sport(self, sport_slug: str) -> list[Path]:
        return odds_history_roots_for_sport(sport_slug)

    def _odds_history_paths_for_sport(self, sport_slug: str) -> list[Path]:
        return odds_history_paths_for_sport(sport_slug)

    def _load_odds_history_payload_for_sport(self, sport_slug: str) -> dict[str, Any] | None:
        return load_odds_history_payload_for_sport(sport_slug)

    @staticmethod
    def _odds_history_market_states(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
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

    def _odds_history_payloads_by_sport(self, overview: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        for sport in overview:
            if not isinstance(sport, dict):
                continue
            slug = str(sport.get("slug") or "").strip().lower()
            if not slug or slug in payloads:
                continue
            payload = self._load_odds_history_payload_for_sport(slug)
            if isinstance(payload, dict):
                payloads[slug] = payload
        return payloads

    def _source_state_fingerprint_from_status(self, status: dict[str, Any], selected_date: str | None) -> str:
        refresh_status = status.get("refresh_status") if isinstance(status.get("refresh_status"), dict) else {}
        refresh_manifest = refresh_status.get("refresh_status", {}).get("manifest") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        refresh_runtime = refresh_status.get("refresh_status", {}).get("runtime") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        refresh_artifacts = refresh_status.get("refresh_status", {}).get("artifacts") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        sports_payload: list[dict[str, Any]] = []
        for sport in status.get("sports") if isinstance(status.get("sports"), list) else []:
            if not isinstance(sport, dict):
                continue
            artifact_signatures = []
            for artifact in sport.get("artifacts") if isinstance(sport.get("artifacts"), list) else []:
                if not isinstance(artifact, dict):
                    continue
                artifact_signatures.append(
                    {
                        "label": str(artifact.get("label") or "").strip(),
                        **self._artifact_signature(str(artifact.get("path") or "").strip()),
                        "tracked": bool(artifact.get("tracked")),
                        "inside_repo": bool(artifact.get("inside_repo")),
                    }
                )
            advanced_signatures = []
            for advanced_input in sport.get("advanced_inputs") if isinstance(sport.get("advanced_inputs"), list) else []:
                if not isinstance(advanced_input, dict):
                    continue
                advanced_signatures.append(
                    {
                        "label": str(advanced_input.get("label") or "").strip(),
                        **self._artifact_signature(str(advanced_input.get("path") or "").strip()),
                        "exists": bool(advanced_input.get("exists")),
                        "tracked": bool(advanced_input.get("tracked")),
                        "inside_repo": bool(advanced_input.get("inside_repo")),
                    }
                )
            sports_payload.append(
                {
                    "slug": str(sport.get("slug") or "").strip().lower(),
                    "name": str(sport.get("name") or "").strip(),
                    "context_label": str(sport.get("context_label") or "").strip(),
                    "data_health": str(sport.get("data_health") or "").strip(),
                    "active_today": bool(sport.get("active_today")),
                    "tracked_ready": bool(sport.get("tracked_ready")),
                    "advanced_ready": bool(sport.get("advanced_ready")),
                    "advanced_gate": sport.get("advanced_gate") if isinstance(sport.get("advanced_gate"), dict) else {},
                    "data_warnings": [str(item).strip() for item in (sport.get("data_warnings") or []) if str(item).strip()],
                    "artifacts": artifact_signatures,
                    "advanced_inputs": advanced_signatures,
                    "odds_history": self._odds_history_signature(str(sport.get("slug") or "")),
                }
            )
        payload = {
            "selected_date": status.get("selected_date") or selected_date,
            "refresh_run": {
                "run_stamp": refresh_manifest.get("runStamp") if isinstance(refresh_manifest, dict) else None,
                "state": refresh_manifest.get("state") if isinstance(refresh_manifest, dict) else None,
                "finished_at": refresh_manifest.get("finishedAt") if isinstance(refresh_manifest, dict) else None,
                "runtime_state": refresh_runtime.get("state") if isinstance(refresh_runtime, dict) else None,
                "runtime_detail": refresh_runtime.get("detail") if isinstance(refresh_runtime, dict) else None,
                "artifacts": {
                    key: {
                        "exists": bool(value.get("exists")),
                        "path": str(value.get("path") or ""),
                        "size": value.get("size"),
                        "payload_hash": hashlib.sha256(json.dumps(value.get("payload"), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest() if value.get("payload") is not None else None,
                    }
                    for key, value in refresh_artifacts.items()
                    if isinstance(value, dict)
                },
            },
            "tracked_summary": status.get("tracked_summary") if isinstance(status.get("tracked_summary"), dict) else {},
            "advanced_summary": status.get("advanced_summary") if isinstance(status.get("advanced_summary"), dict) else {},
            "readiness_gate": status.get("readiness_gate") if isinstance(status.get("readiness_gate"), dict) else {},
            "sport_manifests": [
                self._sport_manifest_signature(str(sport.get("slug") or ""))
                for sport in sports_payload
                if isinstance(sport, dict) and str(sport.get("slug") or "").strip()
            ],
            "sports": sports_payload,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_cached_status_payload(self, selected_date: str | None) -> dict[str, Any] | None:
        payload = read_json_file(STATUS_CACHE_PATH)
        if not isinstance(payload, dict):
            return None
        if str(payload.get("selected_date") or "").strip() != str(selected_date or "").strip():
            return None
        try:
            cached_at = float(payload.get("cached_at") or 0.0)
        except Exception:
            return None
        if cached_at <= 0.0 or (time.time() - cached_at) > float(self._interval_seconds):
            return None
        status = payload.get("status")
        return dict(status) if isinstance(status, dict) else None

    def _source_state_stamp(self, selected_date: str | None) -> str:
        sports = []
        if self._app is not None:
            with self._app.app_context():
                sports = current_app.config.get("SYNDICATE_SPORTS", [])
        if not sports:
            manifests_root = reports_root() / "manifests"
            if manifests_root.exists():
                sports = [
                    {"slug": path.stem}
                    for path in sorted(manifests_root.glob("*.json"))
                    if path.is_file()
                ]
        payload = {
            "selected_date": str(selected_date or "").strip(),
            "sports": [],
        }
        for sport in sports if isinstance(sports, list) else []:
            if not isinstance(sport, dict):
                continue
            slug = str(sport.get("slug") or "").strip().lower()
            if not slug:
                continue
            payload["sports"].append({"slug": slug, **self._sport_manifest_signature(slug)})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _source_state_fingerprint(self, selected_date: str | None) -> str:
        cache_key = self._source_state_stamp(selected_date)
        with self._condition:
            cached_fingerprint = self._source_fingerprints.get(cache_key)
            if cached_fingerprint is not None and (time.time() - float(cached_fingerprint[0])) <= float(self._interval_seconds):
                return str(cached_fingerprint[1])

        status = self._load_cached_status_payload(selected_date)
        if status is None:
            if self._app is not None:
                with self._app.app_context():
                    status = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date, force_refresh=False)
            else:
                status = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date, force_refresh=False)

        status_fingerprint = self._source_state_fingerprint_from_status(status if isinstance(status, dict) else {}, selected_date)
        fingerprint = hashlib.sha256(f"{cache_key}:{status_fingerprint}".encode("utf-8")).hexdigest()
        with self._condition:
            self._source_fingerprints[cache_key] = (time.time(), fingerprint)
            self._source_fingerprints.move_to_end(cache_key)
            self._trim_ordered_dict(self._source_fingerprints, self._max_snapshots)
        return fingerprint

    def _candidate_pool_key(self, selected_date: str | None, source_fingerprint: str) -> str:
        payload = {
            "selected_date": str(selected_date or "").strip(),
            "source_fingerprint": str(source_fingerprint or "").strip(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _candidate_id(self, candidate: dict[str, Any]) -> str:
        identifier = {
            "sport_slug": str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower(),
            "candidate_type": str(candidate.get("candidate_type") or "").strip().lower(),
            "event_id": str(candidate.get("event_id") or "").strip(),
            "game_pk": str(candidate.get("game_pk") or candidate.get("gamePk") or "").strip(),
            "subject_key": str(candidate.get("subject_key") or candidate.get("player_name") or candidate.get("name") or "").strip().lower(),
            "market_key": str(candidate.get("market_key") or candidate.get("market") or "").strip().lower(),
            "selection": str(candidate.get("selection") or candidate.get("pick") or "").strip().lower(),
            "line": str(candidate.get("line") or candidate.get("market_line") or candidate.get("prop_line") or "").strip().lower(),
            "odds": str(candidate.get("odds") or candidate.get("odds_current") or "").strip().lower(),
        }
        canonical = json.dumps(identifier, sort_keys=True, separators=(",", ":"), default=str)
        return f"cand_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"

    def _candidate_raw_inputs(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            key: candidate.get(key)
            for key in (
                "event_id",
                "game_pk",
                "sport",
                "sport_slug",
                "candidate_type",
                "market",
                "market_key",
                "selection",
                "pick",
                "line",
                "odds",
                "matchup",
                "player_name",
                "name",
                "team",
                "status_display",
                "status_context",
                "game_state",
                "timestamp",
                "updated_at",
                "live_projection",
                "live_total",
                "actual",
            )
        }

    def _candidate_precomputed_features(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "simulation": candidate.get("simulation") if isinstance(candidate.get("simulation"), dict) else None,
            "market_context": candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else None,
            "market_data": candidate.get("market_data") if isinstance(candidate.get("market_data"), dict) else None,
            "market_fit": candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else None,
            "historical_profile": candidate.get("historical_profile") if isinstance(candidate.get("historical_profile"), dict) else None,
            "sport_profile": candidate.get("sport_profile") if isinstance(candidate.get("sport_profile"), dict) else None,
            "performance_context": candidate.get("performance_context") if isinstance(candidate.get("performance_context"), dict) else None,
            "advanced_gate": candidate.get("advanced_gate") if isinstance(candidate.get("advanced_gate"), dict) else None,
            "advanced_context": [dict(item) for item in (candidate.get("advanced_context") or []) if isinstance(item, dict)],
            "advanced_inputs": [dict(item) for item in (candidate.get("advanced_inputs") or []) if isinstance(item, dict)],
        }

    def _candidate_preliminary_scores(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": candidate.get("score"),
            "adjusted_score": candidate.get("adjusted_score"),
            "source_summary_score": candidate.get("source_summary_score"),
            "edge": candidate.get("edge"),
            "adjusted_edge": candidate.get("adjusted_edge"),
            "ev_current": candidate.get("ev_current"),
            "ev_delta": candidate.get("ev_delta"),
            "confidence": candidate.get("confidence"),
            "model_probability": candidate.get("model_probability"),
            "implied_probability": candidate.get("implied_probability"),
        }

    def _serialize_candidate(self, candidate: Any) -> dict[str, Any]:
        if hasattr(candidate, "to_dict"):
            try:
                payload = candidate.to_dict()
                if isinstance(payload, Mapping):
                    candidate_payload = dict(payload)
                else:
                    candidate_payload = {}
            except Exception:
                candidate_payload = {}
        elif isinstance(candidate, Mapping):
            candidate_payload = dict(candidate)
        else:
            return {}

        if not candidate_payload:
            return {}

        sport_slug = str(candidate_payload.get("sport_slug") or candidate_payload.get("sport") or candidate_payload.get("league") or "").strip().lower()
        if sport_slug:
            candidate_payload.setdefault("sport_slug", sport_slug)
            candidate_payload.setdefault("sport", sport_slug)

        candidate_type = str(candidate_payload.get("candidate_type") or candidate_payload.get("type") or candidate_payload.get("kind") or "").strip().lower()
        if candidate_type:
            candidate_payload.setdefault("candidate_type", candidate_type)

        market = str(candidate_payload.get("market") or candidate_payload.get("market_type") or candidate_payload.get("market_name") or candidate_payload.get("prop") or candidate_payload.get("label") or "").strip()
        if market:
            candidate_payload.setdefault("market", market)
            candidate_payload.setdefault("market_type", market)

        selection = str(candidate_payload.get("selection") or candidate_payload.get("pick") or candidate_payload.get("side") or candidate_payload.get("choice") or "").strip()
        if selection:
            candidate_payload.setdefault("selection", selection)

        entity = str(candidate_payload.get("entity") or candidate_payload.get("player_name") or candidate_payload.get("player") or candidate_payload.get("team") or candidate_payload.get("subject") or candidate_payload.get("name") or "").strip()
        if entity:
            candidate_payload.setdefault("entity", entity)
            candidate_payload.setdefault("player_name", candidate_payload.get("player_name") or candidate_payload.get("player") or entity)
            candidate_payload.setdefault("name", candidate_payload.get("name") or entity)

        odds = candidate_payload.get("odds") or candidate_payload.get("odds_current") or candidate_payload.get("odds_display")
        if odds is not None and str(odds).strip():
            candidate_payload.setdefault("odds", odds)

        line = candidate_payload.get("line") or candidate_payload.get("market_line") or candidate_payload.get("prop_line")
        if line is not None and str(line).strip():
            candidate_payload.setdefault("line", line)

        subject_key = str(candidate_payload.get("subject_key") or candidate_payload.get("player_name") or candidate_payload.get("name") or candidate_payload.get("entity") or "").strip().lower()
        if subject_key:
            candidate_payload.setdefault("subject_key", subject_key)

        market_key = str(candidate_payload.get("market_key") or candidate_payload.get("market") or candidate_payload.get("selection") or "").strip().lower()
        if market_key:
            candidate_payload.setdefault("market_key", market_key)

        return candidate_payload

    def _build_candidate_pool(self, selected_date: str | None, source_fingerprint: str) -> dict[str, Any]:
        cache_key = self._candidate_pool_key(selected_date, source_fingerprint)
        with self._condition:
            cached_pool = self._candidate_pools.get(cache_key)
            if cached_pool is not None:
                return json.loads(json.dumps(cached_pool, default=str))

        overview = None
        if self._app is not None:
            try:
                with self._app.app_context():
                    overview = _profile_stage("data_ingestion", build_intelligence_overview, selected_date=selected_date, force_refresh=True)
            except RuntimeError:
                overview = None
        if overview is None:
            overview = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date)
            if isinstance(overview, dict):
                overview = overview.get("sports") if isinstance(overview.get("sports"), list) else []
            if not isinstance(overview, list):
                overview = []
        preferences = _query_preferences(
            "top edges today",
            mode="recommendation",
            sport="all",
            timing="all",
            include_props=True,
            include_games=True,
        )
        odds_history_by_sport = self._odds_history_payloads_by_sport(overview)
        raw_candidates = _profile_stage(
            "simulation_aggregation",
            collect_candidates,
            overview,
            preferences,
            odds_history_by_sport,
        )
        if not raw_candidates:
            try:
                raw_candidates = _profile_stage(
                    "simulation_aggregation_fallback",
                    collect_all_recommendations,
                    selected_date=selected_date,
                    force_refresh=True,
                    log_pipeline=False,
                )
            except TypeError:
                raw_candidates = []

        raw_candidates = [candidate for candidate in raw_candidates if isinstance(candidate, Mapping)]
        candidate_build_started_at = time.perf_counter()
        candidate_entries: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            candidate_entry = self._serialize_candidate(candidate)
            if not candidate_entry:
                continue
            _apply_candidate_tier_penalty(candidate_entry)
            candidate_entry["candidate_id"] = self._candidate_id(candidate_entry)
            candidate_entry["raw_inputs"] = self._candidate_raw_inputs(candidate_entry)
            candidate_entry["precomputed_features"] = self._candidate_precomputed_features(candidate_entry)
            candidate_entry["preliminary_scores"] = self._candidate_preliminary_scores(candidate_entry)
            candidate_entry["source_fingerprint"] = source_fingerprint
            candidate_entry = attach_market_id(
                candidate_entry,
                sport=candidate_entry.get("sport_slug") or candidate_entry.get("sport"),
                event_id=candidate_entry.get("event_id") or candidate_entry.get("matchup") or candidate_entry.get("game_id"),
                market_type=candidate_entry.get("market_type") or candidate_entry.get("market") or candidate_entry.get("selection") or candidate_entry.get("period"),
                entity=candidate_entry.get("entity") or candidate_entry.get("player_name") or candidate_entry.get("player") or candidate_entry.get("team") or candidate_entry.get("selection"),
                line=candidate_entry.get("line") or candidate_entry.get("market_line") or candidate_entry.get("prop_line"),
            )
            candidate_entries.append(candidate_entry)
        _log_stage_timing("candidate_building", (time.perf_counter() - candidate_build_started_at) * 1000.0)

        manifests = self._available_sport_manifests(selected_date)
        candidate_pools: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        for sport_slug, manifest in manifests.items():
            odds_history_payload = self._load_odds_history_payload_for_sport(sport_slug)
            odds_history_markets = self._odds_history_market_states(odds_history_payload)
            sport_candidates: list[dict[str, Any]] = []
            for candidate in candidate_entries:
                candidate_sport = str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower()
                if candidate_sport != sport_slug:
                    continue
                sport_candidate = dict(candidate)
                sport_candidate["sport_manifest_last_updated"] = str(manifest.get("last_updated") or "").strip() or None
                sport_candidate["sport_manifest_status"] = str(manifest.get("status") or "").strip() or None
                sport_candidate["sport_manifest_artifact_paths"] = [str(path).strip() for path in (manifest.get("artifact_paths") or []) if str(path).strip()] if isinstance(manifest.get("artifact_paths"), list) else []
                sport_candidate["sport_manifest_metadata"] = dict(manifest.get("metadata") or {}) if isinstance(manifest.get("metadata"), dict) else {}
                market_id = str(sport_candidate.get("market_id") or "").strip()
                history_state = odds_history_markets.get(market_id) if market_id else None
                if history_state:
                    history_rows = history_state.get("history") if isinstance(history_state.get("history"), list) else []
                    sport_candidate["delta_line"] = history_state.get("delta_line")
                    sport_candidate["movement"] = history_state.get("movement")
                    sport_candidate["last_updated"] = history_state.get("last_updated")
                    sport_candidate["odds_history"] = {
                        "market_id": market_id,
                        "last_line": history_state.get("last_line"),
                        "last_odds": history_state.get("last_odds"),
                        "delta_line": history_state.get("delta_line"),
                        "movement": history_state.get("movement"),
                        "last_updated": history_state.get("last_updated"),
                        "recent_trend": history_rows[-3:],
                    }
                sport_candidates.append(sport_candidate)
            if not sport_candidates:
                continue
            candidate_pools[sport_slug] = sport_candidates

        global_pool = self._merge_candidate_pools(candidate_pools)
        if not candidate_pools:
            global_pool = []

        pool = {
            "selected_date": selected_date,
            "source_fingerprint": source_fingerprint,
            "candidate_count": len(global_pool),
            "candidate_pools": {
                sport_slug: {
                    "sport": sport_slug,
                    "last_updated": str(manifest.get("last_updated") or "").strip() or None,
                    "status": str(manifest.get("status") or "").strip() or None,
                    "artifact_paths": [str(path).strip() for path in (manifest.get("artifact_paths") or []) if str(path).strip()] if isinstance(manifest.get("artifact_paths"), list) else [],
                    "metadata": dict(manifest.get("metadata") or {}) if isinstance(manifest.get("metadata"), dict) else {},
                    "candidate_count": len(candidate_pools.get(sport_slug, [])),
                    "candidates": candidate_pools.get(sport_slug, []),
                    "odds_history": self._load_odds_history_payload_for_sport(sport_slug),
                }
                for sport_slug, manifest in manifests.items()
                if sport_slug in candidate_pools
            },
            "global_pool": global_pool,
            "candidates": global_pool,
        }
        with self._condition:
            self._candidate_pools[cache_key] = pool
            self._candidate_pools.move_to_end(cache_key)
            self._trim_ordered_dict(self._candidate_pools, self._max_snapshots)
        return json.loads(json.dumps(pool, default=str))

    def start(self, app: Flask | None = None) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if app is not None:
                self._app = app
            self._load_persisted_state_locked()
            self._stop.clear()
            self._thread = threading.Thread(target=self._background_loop, name="syndicate-intelligence-state-loop", daemon=True)
            self._thread.start()
            self._running = True
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            if not self._snapshots or latest_snapshot is None or self._is_stale(latest_snapshot):
                self._enqueue_locked(self._default_payload())
            return True

    def status(self, *, force_refresh: bool = True) -> dict[str, Any]:
        with self._lock:
            self._sync_persisted_state_locked(force=force_refresh)
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            latest_age_seconds = self._snapshot_age_seconds(latest_snapshot)
            freshness_sla_seconds = int(self._interval_seconds)
            return {
                "enabled": True,
                "intervalSeconds": int(self._interval_seconds),
                "waitTimeoutSeconds": int(self._wait_timeout_seconds),
                "threadAlive": bool(self._thread is not None and self._thread.is_alive()),
                "running": bool(self._running),
                "latestKey": self._latest_key,
                "cachedSnapshots": len(self._snapshots),
                "cachedCandidatePools": len(self._candidate_pools),
                "latestComputedAt": latest_snapshot.computed_at if latest_snapshot else None,
                "latestSourceFingerprint": latest_snapshot.source_fingerprint if latest_snapshot else None,
                "latestSnapshotAgeSeconds": latest_age_seconds,
                "lastRunStartedAt": _utc_from_epoch(self._last_run_started_at),
                "lastRunFinishedAt": _utc_from_epoch(self._last_run_finished_at),
                "lastRunKey": self._last_run_key,
                "freshnessSlaSeconds": freshness_sla_seconds,
                "freshnessStatus": "fresh" if latest_age_seconds is not None and latest_age_seconds <= freshness_sla_seconds else "stale",
                "isFresh": bool(latest_age_seconds is not None and latest_age_seconds <= freshness_sla_seconds),
            }

    def get_response(self, payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload)
        key = _payload_key(normalized_payload)
        with self._condition:
            self._sync_persisted_state_locked(force=force_refresh)
            self._watched_payloads[key] = normalized_payload
            self._watched_payloads.move_to_end(key)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
            snapshot = self._snapshots.get(key)
            if refresh or snapshot is None:
                self._enqueue_locked(normalized_payload)
            elif self._is_stale(snapshot):
                self._enqueue_locked(normalized_payload)
            if snapshot is not None and not refresh and not self._is_stale(snapshot):
                return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
            if wait:
                self._condition.wait_for(lambda: key in self._snapshots and not self._is_stale(self._snapshots[key]), timeout=self._wait_timeout_seconds)
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
            if self._latest_key and self._latest_key in self._snapshots:
                latest_snapshot = self._snapshots[self._latest_key]
                return _decorate_response_with_state_meta(dict(latest_snapshot.response), latest_snapshot, source="worker", run_key=latest_snapshot.key, sla_seconds=self._interval_seconds)
        return None

    def read_latest_response(
        self,
        payload: dict[str, Any] | None = None,
        *,
        force_refresh: bool = True,
        allow_latest_fallback: bool = False,
    ) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload or self._default_payload())
        key = _payload_key(normalized_payload)
        requested_date = _selected_date_from_payload(normalized_payload)
        with self._lock:
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return dict(snapshot.response)
            if self._latest_key and self._latest_key in self._snapshots:
                latest_snapshot = self._snapshots[self._latest_key]
                latest_date = _selected_date_from_payload(latest_snapshot.payload)
                if allow_latest_fallback or requested_date is None or latest_date is None or latest_date == requested_date:
                    return dict(latest_snapshot.response)
            self._sync_persisted_state_locked(force=force_refresh)
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return dict(snapshot.response)
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            if latest_snapshot is not None:
                latest_date = _selected_date_from_payload(latest_snapshot.payload)
                if allow_latest_fallback or requested_date is None or latest_date is None or latest_date == requested_date:
                    return dict(latest_snapshot.response)
            return None

    def queue_refresh(self, payload: dict[str, Any]) -> str:
        normalized_payload = self._normalize_payload(payload)
        with self._condition:
            self._watched_payloads[_payload_key(normalized_payload)] = normalized_payload
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
            key = self._enqueue_locked(normalized_payload)
            self._persist_locked()
            return key

    def _default_payload(self) -> dict[str, Any]:
        return {
            "question": "top edges today",
            "date": central_today_iso(),
            "mode": "live",
            "sport": "all",
            "timing": "",
            "limit": 10,
            "include_props": True,
            "include_games": True,
            "force_refresh": True,
        }

    def _sync_persisted_state_locked(self, *, force: bool = True) -> None:
        self._load_persisted_state_locked(force=force or _state_backend_kind() == "keyvalue")

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized.pop("user_profile", None)
        normalized.pop("force_refresh", None)
        if not str(normalized.get("question") or "").strip():
            normalized["question"] = "top edges today"
        if not str(normalized.get("date") or normalized.get("selected_date") or "").strip():
            normalized["date"] = central_today_iso()
        normalized.setdefault("mode", "live")
        normalized.setdefault("sport", "all")
        normalized.setdefault("limit", 10)
        normalized["force_refresh"] = True
        return normalized

    def _enqueue_locked(self, payload: dict[str, Any]) -> str:
        key = _payload_key(payload)
        snapshot = self._snapshots.get(key)
        if snapshot is not None and not self._is_stale(snapshot):
            return key
        if key in self._pending_keys:
            self._pending_keys[key] = payload
            self._pending_keys.move_to_end(key)
            return key
        if self._last_run_key == key and self._last_run_finished_at > 0.0 and (time.time() - self._last_run_finished_at) < float(self._interval_seconds):
            return key
        self._pending_keys[key] = payload
        self._pending_keys.move_to_end(key)
        self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        self._condition.notify_all()
        return key

    def _background_loop(self) -> None:
        while not self._stop.is_set():
            payload_to_process: dict[str, Any] | None = None
            with self._condition:
                self._sync_persisted_queue_locked()
                if not self._pending_keys:
                    for key, watched_payload in list(self._watched_payloads.items()):
                        snapshot = self._snapshots.get(key)
                        if snapshot is None or self._is_stale(snapshot):
                            self._pending_keys[key] = watched_payload
                    self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
                if self._pending_keys:
                    _, payload_to_process = self._pending_keys.popitem(last=False)
                else:
                    self._condition.wait(timeout=self._interval_seconds)
                    continue
            if payload_to_process is None:
                continue
            guard_acquired = False
            run_started_at = time.time()
            try:
                guard_acquired = self._execution_guard.acquire(blocking=False)
                if not guard_acquired:
                    with self._condition:
                        self._pending_keys[_payload_key(payload_to_process)] = payload_to_process
                        self._pending_keys.move_to_end(_payload_key(payload_to_process))
                        self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
                        self._condition.wait(timeout=min(1.0, float(self._interval_seconds)))
                    continue
                logger.info("WORKER RUN", extra={"payload_key": _payload_key(payload_to_process)})
                state = run_routed_intelligence_pipeline(payload_to_process)
                written_state = write_latest_intelligence_state(state)
                if written_state is None:
                    response = {
                        "ok": False,
                        "error": "invalid worker state",
                        "response": {},
                        "top_opportunities": [],
                        "by_sport": {},
                        "analysis": None,
                    }
                else:
                    response = dict(written_state)
            except Exception as exc:
                response = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "response": {},
                    "top_opportunities": [],
                    "by_sport": {},
                    "analysis": None,
                }
            snapshot = IntelligenceSnapshot(
                key=_payload_key(payload_to_process),
                payload=dict(payload_to_process),
                response=response,
                computed_at=_utc_now(),
                source_fingerprint=str(response.get("source_fingerprint") or response.get("latestSourceFingerprint") or "") if isinstance(response, dict) else "",
            )
            with self._condition:
                self._snapshots[snapshot.key] = snapshot
                self._snapshots.move_to_end(snapshot.key)
                self._latest_key = snapshot.key
                self._last_run_key = snapshot.key
                self._last_run_started_at = run_started_at
                self._last_run_finished_at = time.time()
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                self._persist_locked()
                self._condition.notify_all()
                self._condition.wait(timeout=self._interval_seconds)
            if guard_acquired:
                self._execution_guard.release()

    def _compute_response(self, payload: dict[str, Any], *, force_refresh: bool = False) -> dict[str, Any]:
        request_started_at = time.perf_counter()
        request_payload = dict(payload)
        question = str(request_payload.get("question") or "").strip() or "top edges today"
        selected_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip() or None
        limit = request_payload.get("limit")
        try:
            limit_value = int(limit) if limit is not None and str(limit).strip() else 10
        except Exception:
            limit_value = 10

        source_fingerprint = self._source_state_fingerprint(selected_date)
        cache_key = _payload_key(request_payload)
        with self._condition:
            snapshot = self._snapshots.get(cache_key)
            if not force_refresh and snapshot is not None and snapshot.source_fingerprint == source_fingerprint and not self._is_stale(snapshot):
                _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                return dict(snapshot.response)

        guard_acquired = self._execution_guard.acquire(blocking=False)
        if not guard_acquired:
            with self._condition:
                snapshot = self._snapshots.get(cache_key)
                if snapshot is not None:
                    _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                    return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
                if self._latest_key and self._latest_key in self._snapshots:
                    _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                    latest_snapshot = self._snapshots[self._latest_key]
                    return _decorate_response_with_state_meta(dict(latest_snapshot.response), latest_snapshot, source="worker", run_key=latest_snapshot.key, sla_seconds=self._interval_seconds)
            return {"ok": False, "error": "intelligence worker busy", "response": {}, "top_opportunities": [], "by_sport": {}, "analysis": None}

        try:
            with self._condition:
                self._last_run_key = cache_key
                self._last_run_started_at = time.time()

            candidate_pool = self._build_candidate_pool(selected_date, source_fingerprint)
            candidates = [self._serialize_candidate(candidate) for candidate in candidate_pool.get("candidates") if isinstance(candidate, Mapping)]

            ranked_candidates = _profile_stage("candidate_scoring", _balanced_recommendation_order, candidates)
            if ranked_candidates:
                top_candidates = [dict(candidate) for candidate in ranked_candidates if isinstance(candidate, Mapping)]
            elif candidates:
                top_candidates = self._rank_fallback_candidates(candidates)
            else:
                top_candidates = []
            opportunity_limit = max(int(limit_value), 1) if top_candidates else max(int(limit_value), 0)
            top_opportunities = top_candidates[:opportunity_limit]
            by_sport: dict[str, list[dict[str, object]]] = {}
            for recommendation in top_opportunities:
                sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
                by_sport.setdefault(sport_key, []).append(dict(recommendation))

            response_build_started_at = time.perf_counter()
            if self._app is not None:
                with self._app.app_context():
                    analysis_result = run_routed_intelligence_pipeline(request_payload)
            else:
                analysis_result = run_routed_intelligence_pipeline(request_payload)
            if hasattr(analysis_result, "to_dict"):
                analysis = analysis_result.to_dict()
            elif isinstance(analysis_result, dict):
                analysis = dict(analysis_result)
            else:
                analysis = {}

            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            if not any(isinstance(item, dict) for item in analysis_recommendations):
                fallback_recommendations = [self._serialize_candidate(item) for item in top_opportunities if isinstance(item, Mapping)]
                if fallback_recommendations:
                    analysis["recommendations"] = fallback_recommendations
                    if not isinstance(analysis.get("picks"), list) or not analysis.get("picks"):
                        analysis["picks"] = [self._serialize_candidate(item) for item in fallback_recommendations]
                    if not isinstance(analysis.get("top_live_opportunities"), list) or not analysis.get("top_live_opportunities"):
                        analysis["top_live_opportunities"] = [self._serialize_candidate(item) for item in fallback_recommendations]

            response: dict[str, Any] = {
                "ok": True,
                "top_opportunities": top_opportunities,
                "by_sport": by_sport,
                "analysis": analysis,
                "candidate_pool": candidate_pool,
            }
            response_last_updated = _utc_now()
            response_candidate_count = len(candidates)
            response["state_last_updated"] = response_last_updated
            response["last_updated"] = response_last_updated
            response["candidate_count"] = response_candidate_count
            if analysis:
                analysis["state_last_updated"] = response_last_updated
                analysis["last_updated"] = response_last_updated
                analysis["candidate_count"] = response_candidate_count
                response["response"] = analysis
            board_payload = dict(response)
            board_payload["board"] = _build_board_dictionary(ranked_candidates)
            response["board_contract"] = build_intelligence_board_contract(board_payload)
            response = _promote_board_contract_cards(response)
            _log_stage_timing("response_building", (time.perf_counter() - response_build_started_at) * 1000.0)
            response = _decorate_response_with_state_meta(dict(response), None, source="worker", run_key=cache_key, sla_seconds=self._interval_seconds) or dict(response)
            persist_on_request_path = not _env_bool("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False)
            with self._condition:
                snapshot = IntelligenceSnapshot(
                    key=cache_key,
                    payload=dict(request_payload),
                    response=dict(response),
                    computed_at=_utc_now(),
                    source_fingerprint=source_fingerprint,
                )
                self._snapshots[snapshot.key] = snapshot
                self._snapshots.move_to_end(snapshot.key)
                self._latest_key = snapshot.key
                self._last_run_finished_at = time.time()
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                if persist_on_request_path:
                    logger.info("before _persist_locked", extra={"candidate_count": response_candidate_count})
                    self._persist_locked()
                    logger.info("after _persist_locked", extra={"candidate_count": response_candidate_count})
                else:
                    logger.info("COMPUTE_RESPONSE PERSIST DEFERRED", extra={"candidate_count": response_candidate_count})
            _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
            logger.info("before return", extra={"candidate_count": response_candidate_count})
            return response
        finally:
            if guard_acquired:
                self._execution_guard.release()

    def _is_stale(self, snapshot: IntelligenceSnapshot) -> bool:
        try:
            computed_at = time.strptime(snapshot.computed_at, "%Y-%m-%dT%H:%M:%SZ")
            computed_epoch = time.mktime(computed_at)
        except Exception:
            return True
        return (time.time() - computed_epoch) >= self._interval_seconds

    @staticmethod
    def _snapshot_age_seconds(snapshot: IntelligenceSnapshot | None) -> float | None:
        if snapshot is None:
            return None
        try:
            computed_at = time.strptime(snapshot.computed_at, "%Y-%m-%dT%H:%M:%SZ")
            computed_epoch = time.mktime(computed_at)
        except Exception:
            return None
        return round(max(0.0, time.time() - computed_epoch), 3)

    @staticmethod
    def _trim_ordered_dict(items: OrderedDict[str, Any], limit: int) -> None:
        while len(items) > limit:
            items.popitem(last=False)

    def _load_persisted_state_locked(self, *, force: bool = False) -> None:
        if self._loaded_from_disk and not force and _state_backend_kind() != "keyvalue":
            return
        if force or _state_backend_kind() == "keyvalue":
            self._snapshots.clear()
            self._latest_key = None
            self._watched_payloads.clear()
            self._pending_keys.clear()
        payload = read_json_file(STATE_PATH)
        self._loaded_from_disk = True
        if not isinstance(payload, dict):
            return
        snapshots = payload.get("snapshots")
        if isinstance(snapshots, dict):
            for key, raw_snapshot in snapshots.items():
                if not isinstance(raw_snapshot, dict):
                    continue
                response = raw_snapshot.get("response")
                if not isinstance(response, dict):
                    continue
                snapshot = IntelligenceSnapshot(
                    key=str(key),
                    payload=dict(raw_snapshot.get("payload") or {}),
                    response=dict(response),
                    computed_at=str(raw_snapshot.get("computed_at") or _utc_now()),
                    source_fingerprint=str(raw_snapshot.get("source_fingerprint") or ""),
                )
                self._snapshots[snapshot.key] = snapshot
        watched_payloads = payload.get("watched_payloads")
        if isinstance(watched_payloads, dict):
            for key, raw_payload in watched_payloads.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._watched_payloads[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
        pending_keys = payload.get("pending_keys")
        if isinstance(pending_keys, dict):
            for key, raw_payload in pending_keys.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._pending_keys[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        self._latest_key = str(payload.get("latest_key") or "").strip() or (next(reversed(self._snapshots)) if self._snapshots else None)

    def _sync_persisted_queue_locked(self) -> None:
        payload = read_json_file(STATE_PATH)
        if not isinstance(payload, dict):
            return
        watched_payloads = payload.get("watched_payloads")
        if isinstance(watched_payloads, dict):
            self._watched_payloads.clear()
            for key, raw_payload in watched_payloads.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._watched_payloads[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
        pending_keys = payload.get("pending_keys")
        if isinstance(pending_keys, dict):
            self._pending_keys.clear()
            for key, raw_payload in pending_keys.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._pending_keys[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._pending_keys, self._max_snapshots)

    def _persist_locked(self) -> None:
        latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
        payload = {
            "latest_key": self._latest_key,
            "updated_at": _utc_now(),
            "watched_payloads": dict(self._watched_payloads),
            "pending_keys": dict(self._pending_keys),
            "snapshots": {
                key: {
                    "key": snapshot.key,
                    "payload": snapshot.payload,
                    "response": snapshot.response,
                    "computed_at": snapshot.computed_at,
                    "source_fingerprint": snapshot.source_fingerprint,
                }
                for key, snapshot in self._snapshots.items()
            },
        }
        write_json_file(STATE_PATH, payload)
        if latest_snapshot is not None:
            write_json_file(
                BOARD_SNAPSHOT_PATH,
                {
                    "latest_key": latest_snapshot.key,
                    "updated_at": _utc_now(),
                    "response": latest_snapshot.response,
                    "state_meta": latest_snapshot.response.get("state_meta") if isinstance(latest_snapshot.response, dict) else None,
                    "board_contract": latest_snapshot.response.get("board_contract") if isinstance(latest_snapshot.response, dict) else None,
                },
            )


_INTELLIGENCE_STATE_SERVICE = IntelligenceStateService()


def start_intelligence_state_background_loop(app: Flask | None = None) -> bool:
    return _INTELLIGENCE_STATE_SERVICE.start(app)


def queue_intelligence_state_refresh(payload: dict[str, Any]) -> str:
    return _INTELLIGENCE_STATE_SERVICE.queue_refresh(payload)


def get_latest_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.read_latest_response(payload, force_refresh=force_refresh)


def get_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.get_response(payload, refresh=refresh, wait=wait, force_refresh=force_refresh)


def compute_intelligence_state_response(payload: dict[str, Any], *, force_refresh: bool = True) -> dict[str, Any] | None:
    started_at = time.time()
    logger.info("before _compute_response")
    response = _INTELLIGENCE_STATE_SERVICE._compute_response(payload, force_refresh=force_refresh)
    logger.info("after _compute_response", extra={"elapsed_ms": round((time.time() - started_at) * 1000.0, 3)})
    return response


def read_latest_intelligence_state_response(
    payload: dict[str, Any] | None = None,
    *,
    force_refresh: bool = True,
    allow_latest_fallback: bool = False,
) -> dict[str, Any] | None:
    response = _INTELLIGENCE_STATE_SERVICE.read_latest_response(
        payload,
        force_refresh=force_refresh,
        allow_latest_fallback=allow_latest_fallback,
    )
    return _promote_board_contract_cards(response) if isinstance(response, dict) else response


def _decorate_intelligence_board_snapshot_response(
    snapshot: dict[str, Any],
    *,
    requested_date: str | None,
    source_label: str,
    strict_date: bool,
) -> dict[str, Any] | None:
    updated_at = str(snapshot.get("updated_at") or "").strip() or None
    response = snapshot.get("response")
    if isinstance(response, dict):
        if strict_date and requested_date and _selected_date_from_response(response) not in {None, requested_date}:
            return None
        decorated = _promote_board_contract_cards(dict(response))
        candidate_count = _intelligence_state_candidate_count(decorated)
        state_meta = dict(decorated.get("state_meta") or {})
        if not state_meta:
            freshness_sla_seconds = _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30)
            normalized_updated_at = _utc_timestamp_string(updated_at or decorated.get("state_last_updated") or decorated.get("last_updated") or decorated.get("updated_at"))
            state_meta = {
                "source": source_label,
                "computed_at": normalized_updated_at,
                "age_seconds": 0.0,
                "freshness_sla_seconds": freshness_sla_seconds,
                "freshness_status": "fresh",
                "is_fresh": True,
                "source_fingerprint": decorated.get("source_fingerprint"),
                "run_key": snapshot.get("latest_key"),
                "last_run_started_at": None,
                "last_run_finished_at": None,
            }
        decorated.setdefault("state_meta", state_meta)
        decorated.setdefault("freshness", dict(state_meta))
        decorated.setdefault("state_freshness", dict(state_meta))
        decorated["state_last_updated"] = _utc_timestamp_string(updated_at or decorated.get("state_last_updated") or decorated.get("last_updated") or decorated.get("updated_at"))
        decorated["candidate_count"] = candidate_count
        return decorated if candidate_count > 0 else None
    if all(key in snapshot for key in ("ok", "analysis", "top_opportunities")):
        if strict_date and requested_date and _selected_date_from_response(snapshot) not in {None, requested_date}:
            return None
        decorated = _promote_board_contract_cards(dict(snapshot))
        updated_at = str(decorated.get("updated_at") or decorated.get("state_last_updated") or "").strip() or None
        freshness_sla_seconds = _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30)
        state_meta = decorated.get("state_meta") if isinstance(decorated.get("state_meta"), dict) else {}
        candidate_count = _intelligence_state_candidate_count(decorated)
        if not state_meta:
            state_meta = {
                "source": source_label,
                "computed_at": _utc_timestamp_string(updated_at),
                "age_seconds": 0.0,
                "freshness_sla_seconds": freshness_sla_seconds,
                "freshness_status": "fresh",
                "is_fresh": True,
                "source_fingerprint": decorated.get("source_fingerprint"),
                "run_key": snapshot.get("latest_key"),
                "last_run_started_at": None,
                "last_run_finished_at": None,
            }
        decorated.setdefault("state_meta", state_meta)
        decorated.setdefault("freshness", dict(state_meta))
        decorated.setdefault("state_freshness", dict(state_meta))
        decorated["state_last_updated"] = _utc_timestamp_string(updated_at)
        decorated["candidate_count"] = candidate_count
        return decorated if candidate_count > 0 else None
    return None


def _latest_non_empty_intelligence_board_snapshot_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    requested_date = _selected_date_from_payload(payload)
    candidate_paths: list[Path] = []
    seen_paths: set[str] = set()
    for path in [
        _intelligence_state_read_path("board_snapshot", BOARD_SNAPSHOT_PATH),
        *_intelligence_state_daily_candidates().get("board_snapshot", []),
        BOARD_SNAPSHOT_PATH,
    ]:
        if not isinstance(path, Path):
            continue
        normalized = str(path)
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        candidate_paths.append(path)

    for path in candidate_paths:
        snapshot = read_json_file(path)
        if not isinstance(snapshot, dict):
            continue
        decorated = _decorate_intelligence_board_snapshot_response(snapshot, requested_date=requested_date, source_label="board_snapshot_latest", strict_date=False)
        if isinstance(decorated, dict):
            return decorated
    return None


def read_latest_intelligence_board_snapshot_response(payload: dict[str, Any] | None = None, *, force_refresh: bool = True) -> dict[str, Any] | None:
    requested_date = _selected_date_from_payload(payload)
    _ = force_refresh
    snapshot_path = _intelligence_state_read_path("board_snapshot", BOARD_SNAPSHOT_PATH)
    snapshot = read_json_file(snapshot_path)
    if isinstance(snapshot, dict):
        decorated = _decorate_intelligence_board_snapshot_response(snapshot, requested_date=requested_date, source_label="board_snapshot", strict_date=False)
        if isinstance(decorated, dict):
            if requested_date and _selected_date_from_response(decorated) not in {None, requested_date}:
                return None
            return decorated
    return _latest_non_empty_intelligence_board_snapshot_response(payload)


def intelligence_state_status(*, force_refresh: bool = True) -> dict[str, Any]:
    return _INTELLIGENCE_STATE_SERVICE.status(force_refresh=force_refresh)