from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask
from flask import current_app

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_today_iso


REPO_ROOT = repo_root_from(__file__)
STATE_PATH = reports_root() / "intelligence" / "query_state_cache.json"
STATUS_CACHE_PATH = reports_root() / "intelligence" / "status_response_cache.json"
logger = logging.getLogger(__name__)


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


def _log_worker_state_write(state: dict[str, Any]) -> None:
    print(
        "[WORKER WRITE]",
        {
            "timestamp": _utc_now(),
            "state_last_updated": state.get("last_updated"),
            "candidate_count": len(state.get("candidates", [])),
        },
    )


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
        manifest = read_json_file(manifest_path) if manifest_path.exists() else None
        if isinstance(manifest, dict):
            signature.update(
                {
                    "sport": str(manifest.get("sport") or "").strip().lower(),
                    "last_updated": str(manifest.get("last_updated") or "").strip(),
                    "status": str(manifest.get("status") or "").strip().lower(),
                    "artifact_path_count": len(manifest.get("artifact_paths") or []) if isinstance(manifest.get("artifact_paths"), list) else 0,
                }
            )
        return signature

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
            if not manifest_path.exists():
                continue
            manifest = read_json_file(manifest_path)
            if not isinstance(manifest, dict):
                continue
            manifests[sport_slug] = manifest
        return manifests

    @staticmethod
    def _merge_candidate_pools(candidate_pools: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for sport_candidates in candidate_pools.values():
            merged.extend(dict(candidate) for candidate in sport_candidates if isinstance(candidate, dict))
        return merged

    def _odds_history_roots_for_sport(self, sport_slug: str) -> list[Path]:
        roots: list[Path] = []
        for base in (REPO_ROOT / "data" / f"{sport_slug}_source", REPO_ROOT / f"{sport_slug}_source"):
            if base.exists() and base not in roots:
                roots.append(base)
        return roots

    def _odds_history_paths_for_sport(self, sport_slug: str) -> list[Path]:
        paths: list[Path] = []
        for root in self._odds_history_roots_for_sport(sport_slug):
            for candidate in (root / "artifacts" / sport_slug / "odds_history.json", root / "tracking" / "odds_history.json"):
                if candidate not in paths:
                    paths.append(candidate)
        return paths

    def _load_odds_history_payload_for_sport(self, sport_slug: str) -> dict[str, Any] | None:
        for path in self._odds_history_paths_for_sport(sport_slug):
            if not path.exists():
                continue
            payload = read_json_file(path)
            if isinstance(payload, dict):
                return payload
        return None

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

    def _build_candidate_pool(self, selected_date: str | None, source_fingerprint: str) -> dict[str, Any]:
        cache_key = self._candidate_pool_key(selected_date, source_fingerprint)
        with self._condition:
            cached_pool = self._candidate_pools.get(cache_key)
            if cached_pool is not None:
                return json.loads(json.dumps(cached_pool, default=str))

        if self._app is not None:
            with self._app.app_context():
                raw_candidates = _profile_stage("simulation_aggregation", collect_all_recommendations, selected_date=selected_date, force_refresh=True, log_pipeline=False)
        else:
            raw_candidates = _profile_stage("simulation_aggregation", collect_all_recommendations, selected_date=selected_date, force_refresh=True, log_pipeline=False)
        candidate_build_started_at = time.perf_counter()
        candidate_entries: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_entry = dict(candidate)
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
            if not self._snapshots:
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
                return dict(snapshot.response)
            if wait:
                self._condition.wait_for(lambda: key in self._snapshots and not self._is_stale(self._snapshots[key]), timeout=self._wait_timeout_seconds)
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return dict(snapshot.response)
            if self._latest_key and self._latest_key in self._snapshots:
                return dict(self._snapshots[self._latest_key].response)
        return None

    def read_latest_response(self, payload: dict[str, Any] | None = None, *, force_refresh: bool = True) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload or self._default_payload())
        key = _payload_key(normalized_payload)
        with self._lock:
            self._sync_persisted_state_locked(force=force_refresh)
            snapshot = self._snapshots.get(key)
            if snapshot is not None and not self._is_stale(snapshot):
                return dict(snapshot.response)
            if self._latest_key and self._latest_key in self._snapshots:
                return dict(self._snapshots[self._latest_key].response)
            return None

    def queue_refresh(self, payload: dict[str, Any]) -> str:
        normalized_payload = self._normalize_payload(payload)
        with self._condition:
            self._watched_payloads[_payload_key(normalized_payload)] = normalized_payload
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
            return self._enqueue_locked(normalized_payload)

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
        self._pending_keys[key] = payload
        self._pending_keys.move_to_end(key)
        self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        self._condition.notify_all()
        return key

    def _background_loop(self) -> None:
        while not self._stop.is_set():
            payload_to_process: dict[str, Any] | None = None
            source_fingerprint: str | None = None
            with self._condition:
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
            try:
                selected_date = str(payload_to_process.get("date") or payload_to_process.get("selected_date") or "").strip() or None
                source_fingerprint = self._source_state_fingerprint(selected_date)
                candidate_pool = self._build_candidate_pool(selected_date, source_fingerprint)
                with self._condition:
                    current_snapshot = self._snapshots.get(_payload_key(payload_to_process))
                if self._app is not None:
                    with self._app.app_context():
                        response = self._compute_response(payload_to_process, force_refresh=True)
                else:
                    response = self._compute_response(payload_to_process, force_refresh=True)
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
                source_fingerprint=source_fingerprint or "",
            )
            worker_state = {
                "last_updated": snapshot.computed_at,
                "candidates": candidate_pool.get("candidates", []) if isinstance(candidate_pool, dict) else [],
            }
            with self._condition:
                self._snapshots[snapshot.key] = snapshot
                self._snapshots.move_to_end(snapshot.key)
                self._latest_key = snapshot.key
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                _log_worker_state_write(worker_state)
                self._persist_locked()
                self._condition.notify_all()
                self._condition.wait(timeout=self._interval_seconds)

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
            if not force_refresh and snapshot is not None and snapshot.source_fingerprint == source_fingerprint:
                _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                return dict(snapshot.response)

        candidate_pool = self._build_candidate_pool(selected_date, source_fingerprint)
        candidates = [dict(candidate) for candidate in candidate_pool.get("candidates") if isinstance(candidate, dict)]

        top_opportunities = _profile_stage("candidate_scoring", rank_global_recommendations, candidates, limit=limit_value)
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

        response: dict[str, Any] = {
            "ok": True,
            "top_opportunities": top_opportunities,
            "by_sport": by_sport,
            "analysis": analysis,
            "candidate_pool": candidate_pool,
        }
        if analysis:
            response["response"] = analysis
        _log_stage_timing("response_building", (time.perf_counter() - response_build_started_at) * 1000.0)
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
            self._trim_ordered_dict(self._snapshots, self._max_snapshots)
            self._persist_locked()
        _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
        return response

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
        payload = read_json_file(STATE_PATH)
        self._loaded_from_disk = True
        if not isinstance(payload, dict):
            return
        snapshots = payload.get("snapshots")
        if not isinstance(snapshots, dict):
            return
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
        self._latest_key = str(payload.get("latest_key") or "").strip() or (next(reversed(self._snapshots)) if self._snapshots else None)

    def _persist_locked(self) -> None:
        payload = {
            "latest_key": self._latest_key,
            "updated_at": _utc_now(),
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


_INTELLIGENCE_STATE_SERVICE = IntelligenceStateService()


def start_intelligence_state_background_loop(app: Flask | None = None) -> bool:
    return _INTELLIGENCE_STATE_SERVICE.start(app)


def queue_intelligence_state_refresh(payload: dict[str, Any]) -> str:
    return _INTELLIGENCE_STATE_SERVICE.queue_refresh(payload)


def get_latest_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.read_latest_response(payload, force_refresh=force_refresh)


def get_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.get_response(payload, refresh=refresh, wait=wait, force_refresh=force_refresh)


def compute_intelligence_state_response(payload: dict[str, Any]) -> dict[str, Any]:
    return _INTELLIGENCE_STATE_SERVICE._compute_response(payload)


def read_latest_intelligence_state_response(payload: dict[str, Any] | None = None, *, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.read_latest_response(payload, force_refresh=force_refresh)


def intelligence_state_status(*, force_refresh: bool = True) -> dict[str, Any]:
    return _INTELLIGENCE_STATE_SERVICE.status(force_refresh=force_refresh)