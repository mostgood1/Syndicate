from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_today_iso


REPO_ROOT = repo_root_from(__file__)
STATE_PATH = REPO_ROOT / "reports" / "intelligence" / "query_state_cache.json"


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


@dataclass
class IntelligenceSnapshot:
    key: str
    payload: dict[str, Any]
    response: dict[str, Any]
    computed_at: str


class IntelligenceStateService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._interval_seconds = max(10, _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 15))
        self._wait_timeout_seconds = max(10, self._interval_seconds * 2)
        self._max_snapshots = max(5, _env_int("SYNDICATE_INTELLIGENCE_MAX_SNAPSHOTS", 12))
        self._snapshots: OrderedDict[str, IntelligenceSnapshot] = OrderedDict()
        self._watched_payloads: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending_keys: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._latest_key: str | None = None
        self._loaded_from_disk = False
        self._app: Flask | None = None

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

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            return {
                "enabled": True,
                "intervalSeconds": int(self._interval_seconds),
                "waitTimeoutSeconds": int(self._wait_timeout_seconds),
                "threadAlive": bool(self._thread is not None and self._thread.is_alive()),
                "running": bool(self._running),
                "latestKey": self._latest_key,
                "cachedSnapshots": len(self._snapshots),
                "latestComputedAt": latest_snapshot.computed_at if latest_snapshot else None,
            }

    def get_response(self, payload: dict[str, Any], *, refresh: bool = False, wait: bool = True) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload)
        key = _payload_key(normalized_payload)
        with self._condition:
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
                if self._app is not None:
                    with self._app.app_context():
                        response = self._compute_response(payload_to_process)
                else:
                    response = self._compute_response(payload_to_process)
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
            )
            with self._condition:
                self._snapshots[snapshot.key] = snapshot
                self._snapshots.move_to_end(snapshot.key)
                self._latest_key = snapshot.key
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                self._persist_locked()
                self._condition.notify_all()
            self._condition.wait(timeout=self._interval_seconds)

    def _compute_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        question = str(request_payload.get("question") or "").strip() or "top edges today"
        selected_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip() or None
        limit = request_payload.get("limit")
        try:
            limit_value = int(limit) if limit is not None and str(limit).strip() else 10
        except Exception:
            limit_value = 10

        shared_recommendations = collect_all_recommendations(selected_date=selected_date, force_refresh=True)
        top_opportunities = rank_global_recommendations(shared_recommendations, limit=limit_value)
        by_sport: dict[str, list[dict[str, object]]] = {}
        for recommendation in top_opportunities:
            sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
            by_sport.setdefault(sport_key, []).append(dict(recommendation))

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
        }
        if analysis:
            response["response"] = analysis
        return response

    def _is_stale(self, snapshot: IntelligenceSnapshot) -> bool:
        try:
            computed_at = time.strptime(snapshot.computed_at, "%Y-%m-%dT%H:%M:%SZ")
            computed_epoch = time.mktime(computed_at)
        except Exception:
            return True
        return (time.time() - computed_epoch) >= self._interval_seconds

    @staticmethod
    def _trim_ordered_dict(items: OrderedDict[str, Any], limit: int) -> None:
        while len(items) > limit:
            items.popitem(last=False)

    def _load_persisted_state_locked(self) -> None:
        if self._loaded_from_disk:
            return
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


def get_latest_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.get_response(payload, refresh=refresh, wait=wait)


def intelligence_state_status() -> dict[str, Any]:
    return _INTELLIGENCE_STATE_SERVICE.status()