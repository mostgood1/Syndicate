"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Builds evaluation and reliability summaries for intelligence outputs.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import hashlib
import json
import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Mapping

from syndicate.features.shared.artifact_manifests import load_artifact_manifests
from syndicate.features.shared.odds_lifecycle import market_feature_summary
from syndicate.features.shared.request_path_guard import warn_if_compute_in_request_path
from syndicate.features.shared.source_roots import repo_root_from


SCHEMA_VERSION = 1
DEFAULT_LEDGER_PATH = repo_root_from(__file__) / "reports" / "intelligence" / "evaluation_ledger.jsonl"
DEFAULT_LEDGER_CHUNK_ROOT = DEFAULT_LEDGER_PATH.parent / "evaluation_ledger_chunks"
DEFAULT_LEDGER_INDEX_PATH = DEFAULT_LEDGER_CHUNK_ROOT / "index.json"
DEFAULT_LEDGER_MANIFEST_PATH = DEFAULT_LEDGER_CHUNK_ROOT / "manifest.json"


def _intel_trace(event: str, **fields: Any) -> None:
    try:
        print(f"[INTEL_TRACE] {json.dumps({'event': event, **fields}, sort_keys=True, default=str)}", flush=True)
    except Exception:
        print(f"[INTEL_TRACE] {event}", flush=True)


def _intel_trace_timed(event: str, started_at: float, **fields: Any) -> None:
    try:
        duration_ms = round((time.perf_counter() - float(started_at)) * 1000.0, 3)
    except Exception:
        duration_ms = None
    if duration_ms is not None:
        fields = {**fields, "duration_ms": duration_ms}
    _intel_trace(event, **fields)


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _copy_sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _canonical_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _stable_id(prefix: str, payload: Any) -> str:
    digest = hashlib.sha1(_canonical_payload(payload).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str))
        handle.write("\n")


def _is_chunked_ledger_path(path: Path | str | None) -> bool:
    if path is None:
        return True
    candidate = Path(path)
    try:
        return candidate.expanduser().resolve() == DEFAULT_LEDGER_PATH.resolve()
    except Exception:
        return str(candidate).replace("\\", "/").endswith("reports/intelligence/evaluation_ledger.jsonl")


def _ledger_chunk_root(path: Path | str | None = None) -> Path:
    candidate = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    if _is_chunked_ledger_path(candidate):
        return candidate.parent / "evaluation_ledger_chunks"
    return candidate.parent / f"{candidate.stem}_chunks"


def _ledger_chunk_path(path: Path | str | None, chunk_name: str) -> Path:
    return _ledger_chunk_root(path) / f"{chunk_name}.jsonl"


def _ledger_index_path(path: Path | str | None = None) -> Path:
    return _ledger_chunk_root(path) / "index.json"


def _ledger_manifest_path(path: Path | str | None = None) -> Path:
    return _ledger_chunk_root(path) / "manifest.json"


def _ledger_record_chunk_name(record: Mapping[str, Any]) -> str:
    query = _copy_mapping(record.get("query"))
    response = _copy_mapping(record.get("response"))
    artifact_metadata = _copy_mapping(record.get("artifact_metadata"))
    for value in (
        query.get("selected_date"),
        query.get("date"),
        response.get("selected_date"),
        response.get("date"),
        artifact_metadata.get("selected_date"),
        artifact_metadata.get("date"),
        record.get("settled_at"),
        record.get("created_at"),
        record.get("updated_at"),
    ):
        text = str(value or "").strip()
        if not text:
            continue
        normalized = text.replace("Z", "")[:10]
        if len(normalized) == 10 and normalized[4] == "-" and normalized[7] == "-":
            return normalized
    return "unknown"


def _ledger_record_identity(record: Mapping[str, Any]) -> str | None:
    for key in ("portfolio_event_id", "recommendation_id", "prediction_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return None


def _load_chunk_index(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    index_path = _ledger_index_path(path)
    if not index_path.exists():
        return {}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        index = payload.get("records")
        if isinstance(index, dict):
            return {str(key): value for key, value in index.items() if isinstance(value, dict)}
    return {}


def _write_chunk_index(path: Path | str | None, index: dict[str, dict[str, Any]]) -> None:
    index_path = _ledger_index_path(path)
    _ensure_parent(index_path)
    index_path.write_text(json.dumps({"records": index, "updated_at": _utc_now()}, indent=2, sort_keys=True), encoding="utf-8")


def _write_chunk_manifest(path: Path | str | None, *, chunk_name: str, record_count: int) -> None:
    manifest_path = _ledger_manifest_path(path)
    _ensure_parent(manifest_path)
    manifest: dict[str, Any] = {"chunks": []}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if isinstance(existing, dict) and isinstance(existing.get("chunks"), list):
            manifest = {"chunks": [item for item in existing.get("chunks") if isinstance(item, dict)]}
    chunks = {str(item.get("chunk") or ""): dict(item) for item in manifest.get("chunks", []) if isinstance(item, dict)}
    chunks[chunk_name] = {"chunk": chunk_name, "path": str(_ledger_chunk_path(path, chunk_name)), "record_count": int(record_count), "updated_at": _utc_now()}
    manifest = {"chunks": list(chunks.values()), "updated_at": _utc_now()}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _append_evaluation_ledger_record(path: Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    if not _is_chunked_ledger_path(target):
        _append_jsonl(target, payload)
        return
    record = dict(payload)
    chunk_name = _ledger_record_chunk_name(record)
    chunk_path = _ledger_chunk_path(target, chunk_name)
    identity = _ledger_record_identity(record)
    index = _load_chunk_index(target)
    if identity and identity in index:
        return
    _append_jsonl(chunk_path, record)
    if identity:
        index[identity] = {"chunk": chunk_name, "path": str(chunk_path), "updated_at": _utc_now()}
        _write_chunk_index(target, index)
    try:
        record_count = sum(1 for _ in chunk_path.read_text(encoding="utf-8").splitlines() if _.strip())
    except Exception:
        record_count = 1
    _write_chunk_manifest(target, chunk_name=chunk_name, record_count=record_count)


def _load_chunked_ledger_records(path: Path) -> list[dict[str, Any]]:
    chunk_root = _ledger_chunk_root(path)
    if not chunk_root.exists():
        return []
    manifest_path = _ledger_manifest_path(path)
    chunk_paths: list[Path] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
        if isinstance(manifest, dict):
            for chunk in manifest.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                chunk_path = Path(str(chunk.get("path") or "").strip())
                if chunk_path.exists() and chunk_path.is_file():
                    chunk_paths.append(chunk_path)
    if not chunk_paths:
        chunk_paths = sorted(item for item in chunk_root.glob("*.jsonl") if item.is_file())
    rows: list[dict[str, Any]] = []
    for chunk_path in chunk_paths:
        try:
            content = chunk_path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _ledger_index(path: Path) -> dict[str, dict[str, Any]]:
    if _is_chunked_ledger_path(path):
        return _load_chunk_index(path)
    if not path.exists():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for record in _iter_record_payloads(ledger_path=path):
        record_id = str(
            record.get("portfolio_event_id")
            or record.get("recommendation_id")
            or record.get("prediction_id")
            or ""
        ).strip()
        if record_id:
            index[record_id] = record
    return index


def _coerce_float(value: Any) -> float | None:
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


def _coerce_probability(value: Any) -> float | None:
    probability = _coerce_float(value)
    if probability is None:
        return None
    if 0.0 <= probability <= 1.0:
        return probability
    if 1.0 < probability <= 100.0:
        return probability / 100.0
    return None


def _result_label(value: Any) -> str:
    text = str(value or "pending").strip().lower()
    return text or "pending"


def _direction_from_recommendation(recommendation: Mapping[str, Any]) -> float | None:
    direction = recommendation.get("selection_direction")
    numeric_direction = _coerce_float(direction)
    if numeric_direction in {1.0, -1.0}:
        return numeric_direction
    pick = str(recommendation.get("pick") or recommendation.get("name") or "").strip().lower()
    if "under" in pick:
        return -1.0
    if "over" in pick or "yes" in pick:
        return 1.0
    return None


def _numeric_line(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("line")
    return _coerce_float(value)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _movement_context(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    movement = recommendation.get("movement") if isinstance(recommendation.get("movement"), Mapping) else {}
    odds_history = recommendation.get("odds_history") if isinstance(recommendation.get("odds_history"), Mapping) else {}

    delta = _first_present(
        _coerce_float(movement.get("delta")),
        _coerce_float(movement.get("edge_delta")),
        _coerce_float(recommendation.get("delta")),
        _coerce_float(odds_history.get("delta")),
    )
    trend = str(
        movement.get("trend")
        or movement.get("recent_movement_trend")
        or recommendation.get("recent_movement_trend")
        or odds_history.get("movement")
        or recommendation.get("movement")
        or ""
    ).strip().lower() or None

    last_odds_update_timestamp = (
        str(movement.get("last_updated") or "").strip()
        or str(recommendation.get("last_updated") or "").strip()
        or str(odds_history.get("last_updated") or "").strip()
        or None
    )

    return {
        "delta": delta,
        "trend": trend,
        "last_odds_update_timestamp": last_odds_update_timestamp,
    }


def _timestamp_key(value: Any) -> tuple[int, str]:
    text = str(value or "").strip()
    if not text:
        return (0, "")
    normalized = text.replace("Z", "+00:00")
    try:
        return (1, datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat())
    except Exception:
        return (1, text)


def _artifact_manifest_summary(*, selected_date: str | None = None, sport: str | None = None) -> dict[str, Any]:
    sport_slug = str(sport or "").strip().lower()
    sport_slugs = None if not sport_slug or sport_slug == "all" else [sport_slug]
    manifests = load_artifact_manifests(selected_date=selected_date, sport_slugs=sport_slugs)
    manifest_rows = [manifest.to_dict() for manifest in manifests]
    return {
        "selected_date": selected_date,
        "sport": sport,
        "manifest_count": len(manifest_rows),
        "sport_manifests": manifest_rows,
    }


def build_artifact_metadata(*, query: Any, response: Any) -> dict[str, Any]:
    query_payload = _copy_mapping(query)
    response_payload = _copy_mapping(response)
    sport = str(query_payload.get("sport") or response_payload.get("sport") or "").strip() or None
    selected_date = str(query_payload.get("selected_date") or response_payload.get("selected_date") or "").strip() or None
    recommendations = _copy_sequence(response_payload.get("recommendations"))
    analysis_views = _copy_mapping(response_payload.get("analysis_views"))
    supporting_evidence = response_payload.get("supporting_evidence") if isinstance(response_payload.get("supporting_evidence"), Mapping) else {}
    top_recommendation = recommendations[0] if recommendations and isinstance(recommendations[0], Mapping) else {}
    policy_comparison = top_recommendation.get("historical_profile", {}).get("policy_comparison") if isinstance(top_recommendation.get("historical_profile"), Mapping) else None
    movement_contexts = [_movement_context(item) for item in recommendations if isinstance(item, Mapping)]
    deltas = [abs(context["delta"]) for context in movement_contexts if context.get("delta") is not None]
    update_timestamps = [context["last_odds_update_timestamp"] for context in movement_contexts if context.get("last_odds_update_timestamp")]
    manifest_summary = _artifact_manifest_summary(selected_date=selected_date, sport=sport)
    _intel_trace(
        "evaluation_artifact_metadata",
        selected_date=selected_date,
        sport=sport,
        recommendation_count=len([item for item in recommendations if isinstance(item, Mapping)]),
        manifest_count=manifest_summary.get("manifest_count") if isinstance(manifest_summary, dict) else None,
        has_analysis_views=bool(analysis_views),
    )
    return {
        "selected_date": selected_date,
        "sport": sport,
        "query_type": query_payload.get("query_type") or response_payload.get("query_type"),
        "intent": query_payload.get("intent") or response_payload.get("intent"),
        "recommendation_count": len([item for item in recommendations if isinstance(item, Mapping)]),
        "decision_strategy": str(top_recommendation.get("decision_strategy") or "").strip() or None,
        "policy_comparison": policy_comparison if isinstance(policy_comparison, list) else None,
        "analysis_focus": analysis_views.get("focus"),
        "board_note_count": len(_copy_sequence(response_payload.get("board_notes"))),
        "supporting_evidence_title": supporting_evidence.get("title") if isinstance(supporting_evidence, Mapping) else None,
        "local_only": response_payload.get("local_only"),
        "has_line_movement": any((context.get("delta") not in (None, 0)) or context.get("trend") in {"up", "down"} for context in movement_contexts),
        "max_delta_detected": max(deltas) if deltas else None,
        "max_delta_line": max(deltas) if deltas else None,
        "last_odds_update_timestamp": max(update_timestamps, key=_timestamp_key) if update_timestamps else None,
        "manifest_summary": manifest_summary,
    }


def _portfolio_tracking_summary(*, response: Mapping[str, Any], recommendations: list[Mapping[str, Any]]) -> dict[str, Any]:
    portfolio = _copy_mapping(response.get("portfolio"))
    return {
        "open_exposure": _coerce_float(portfolio.get("total_exposure")),
        "risk_level": str(portfolio.get("risk_level") or "").strip() or None,
        "expected_return": _coerce_float(portfolio.get("expected_return")),
        "average_correlation": _coerce_float(portfolio.get("average_correlation")),
        "diversification_score": _coerce_float(portfolio.get("diversification_score")),
        "recommendation_count": len(recommendations),
        "wager_count": len(recommendations),
    }


def _portfolio_event_summary(*, response: Mapping[str, Any]) -> dict[str, Any]:
    event_rows = response.get("portfolio_events")
    if not isinstance(event_rows, list):
        event_rows = response.get("portfolio_actions")
    if not isinstance(event_rows, list):
        event_rows = response.get("watchlist_events")
    if not isinstance(event_rows, list):
        event_rows = []

    counts = {"added": 0, "removed": 0, "adjusted": 0, "open": 0, "closed": 0}
    for row in event_rows:
        if not isinstance(row, Mapping):
            continue
        action = str(row.get("action") or row.get("event_type") or row.get("type") or "").strip().lower()
        status = str(row.get("status") or row.get("state") or "").strip().lower()
        open_flag = row.get("open")
        if action in {"add", "added", "open", "opened"}:
            counts["added"] += 1
        elif action in {"remove", "removed", "close", "closed"}:
            counts["removed"] += 1
        elif action in {"adjust", "adjusted", "edit", "edited", "update", "updated"}:
            counts["adjusted"] += 1
        if status in {"open", "opened", "active"} or bool(open_flag) is True:
            counts["open"] += 1
        if status in {"closed", "settled", "removed"} or bool(open_flag) is False and status:
            counts["closed"] += 1

    return {
        "event_count": len(event_rows),
        "added_count": counts["added"],
        "removed_count": counts["removed"],
        "adjusted_count": counts["adjusted"],
        "open_count": counts["open"],
        "closed_count": counts["closed"],
    }


def _portfolio_event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(event.get("event_id") or event.get("id") or "").strip() or None,
        "prediction_id": str(event.get("prediction_id") or "").strip() or None,
        "recommendation_id": str(event.get("recommendation_id") or "").strip() or None,
        "action": str(event.get("action") or event.get("event_type") or event.get("type") or "").strip().lower() or None,
        "status": str(event.get("status") or event.get("state") or "").strip().lower() or None,
        "name": str(event.get("name") or event.get("market") or event.get("label") or "").strip() or None,
    }


def _policy_control_summary(*, response: Mapping[str, Any], recommendations: list[Mapping[str, Any]]) -> dict[str, Any]:
    top_recommendation = recommendations[0] if recommendations else {}
    historical_profile = top_recommendation.get("historical_profile") if isinstance(top_recommendation.get("historical_profile"), Mapping) else {}
    policy_comparison = historical_profile.get("policy_comparison") if isinstance(historical_profile, Mapping) else None
    selected_policy = str(top_recommendation.get("decision_strategy") or "").strip() or None
    if not selected_policy and isinstance(response.get("policy_control"), Mapping):
        selected_policy = str(response.get("policy_control", {}).get("selected_policy") or "").strip() or None
    comparison_rows = policy_comparison if isinstance(policy_comparison, list) else []
    leader_policy = str(comparison_rows[0].get("policy") or "").strip() if comparison_rows and isinstance(comparison_rows[0], Mapping) else None
    return {
        "selected_policy": selected_policy,
        "leader_policy": leader_policy,
        "policy_comparison": comparison_rows,
        "policy_status": "available" if comparison_rows or selected_policy else "empty",
    }


@dataclass(frozen=True)
class IntelligencePredictionRecord:
    prediction_id: str
    query: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    artifact_metadata: dict[str, Any] = field(default_factory=dict)
    recommendation_count: int = 0
    created_at: str = field(default_factory=_utc_now)
    record_type: str = "prediction"
    result: str = "pending"
    recommendation_id: str | None = None
    pnl: float | None = None
    closing_line: Any = None
    implied_probability: float | None = None
    stake: float | None = 1.0
    settled_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": self.record_type,
                "prediction_id": self.prediction_id,
                "recommendation_id": self.recommendation_id,
                "result": self.result,
                "pnl": self.pnl,
                "closing_line": self.closing_line,
                "implied_probability": self.implied_probability,
                "stake": self.stake,
                "query": dict(self.query),
                "response": dict(self.response),
                "artifact_metadata": dict(self.artifact_metadata),
                "recommendation_count": self.recommendation_count,
                "created_at": self.created_at,
            }
        )
        if self.settled_at is not None:
            payload["settled_at"] = self.settled_at
        return payload


@dataclass(frozen=True)
class IntelligenceRecommendationRecord:
    prediction_id: str
    recommendation_id: str
    query: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    recommendation: dict[str, Any] = field(default_factory=dict)
    artifact_metadata: dict[str, Any] = field(default_factory=dict)
    result: str = "pending"
    pnl: float | None = None
    closing_line: Any = None
    implied_probability: float | None = None
    stake: float | None = 1.0
    created_at: str = field(default_factory=_utc_now)
    settled_at: str | None = None
    record_type: str = "recommendation"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": self.record_type,
                "prediction_id": self.prediction_id,
                "recommendation_id": self.recommendation_id,
                "result": self.result,
                "pnl": self.pnl,
                "closing_line": self.closing_line,
                "implied_probability": self.implied_probability,
                "stake": self.stake,
                "query": dict(self.query),
                "response": dict(self.response),
                "recommendation": dict(self.recommendation),
                "artifact_metadata": dict(self.artifact_metadata),
                "created_at": self.created_at,
            }
        )
        if self.settled_at is not None:
            payload["settled_at"] = self.settled_at
        return payload


@dataclass(frozen=True)
class IntelligencePortfolioEventRecord:
    prediction_id: str
    portfolio_event_id: str
    recommendation_id: str | None = None
    query: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    portfolio_event: dict[str, Any] = field(default_factory=dict)
    artifact_metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    record_type: str = "portfolio_event"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": self.record_type,
                "prediction_id": self.prediction_id,
                "portfolio_event_id": self.portfolio_event_id,
                "recommendation_id": self.recommendation_id,
                "query": dict(self.query),
                "response": dict(self.response),
                "portfolio_event": dict(self.portfolio_event),
                "artifact_metadata": dict(self.artifact_metadata),
                "created_at": self.created_at,
            }
        )
        return payload


def _prediction_payload(*, query: Any, response: Any, artifact_metadata: Any = None) -> dict[str, Any]:
    query_payload = _copy_mapping(query)
    response_payload = _copy_mapping(response)
    recommendation_rows = [item for item in response_payload.get("recommendations") or [] if isinstance(item, Mapping)]
    recommendation_keys = [
        {
            "event_id": str(item.get("event_id") or "").strip() or None,
            "market": str(item.get("market") or "").strip().lower() or None,
            "name": str(item.get("name") or item.get("team") or item.get("player") or "").strip() or None,
        }
        for item in recommendation_rows
    ]
    recommendation_keys.sort(key=lambda item: _canonical_payload(item))
    return {
        "schema_version": SCHEMA_VERSION,
        "prediction_id": _stable_id(
            "pred",
            {
                "query": query_payload,
                "recommendations": recommendation_keys,
            },
        ),
        "recommendation_id": None,
        "result": "pending",
        "pnl": None,
        "closing_line": None,
        "implied_probability": None,
        "stake": 1.0,
        "query": query_payload,
        "response": response_payload,
        "artifact_metadata": _copy_mapping(artifact_metadata),
        "recommendation_count": len([item for item in response_payload.get("recommendations") or [] if isinstance(item, Mapping)]),
        "created_at": _utc_now(),
        "record_type": "prediction",
    }


def _recommendation_identity(recommendation: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_id": str(recommendation.get("event_id") or "").strip() or None,
        "market": str(recommendation.get("market") or "").strip().lower() or None,
        "selection": str(recommendation.get("selection") or recommendation.get("pick") or "").strip().lower() or None,
        "name": str(recommendation.get("name") or recommendation.get("player") or recommendation.get("team") or "").strip() or None,
    }


def record_prediction(*, query: Any, response: Any, artifact_metadata: Any = None, persist: bool = True, ledger_path: Path | str | None = None) -> dict[str, Any]:
    payload = _prediction_payload(query=query, response=response, artifact_metadata=artifact_metadata)
    record = IntelligencePredictionRecord(
        prediction_id=str(payload.get("prediction_id") or _new_id("pred")),
        query=_copy_mapping(payload.get("query")),
        response=_copy_mapping(payload.get("response")),
        artifact_metadata=_copy_mapping(payload.get("artifact_metadata")),
        recommendation_count=int(payload.get("recommendation_count") or 0),
        created_at=str(payload.get("created_at") or _utc_now()),
        record_type=str(payload.get("record_type") or "prediction"),
        result=str(payload.get("result") or "pending"),
        recommendation_id=payload.get("recommendation_id"),
        pnl=_coerce_float(payload.get("pnl")),
        closing_line=payload.get("closing_line"),
        implied_probability=_coerce_probability(payload.get("implied_probability")),
        stake=_coerce_float(payload.get("stake")) or 1.0,
        settled_at=payload.get("settled_at"),
        raw=payload,
    )
    payload = record.to_dict()
    if persist:
        target_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
        if _ledger_index(target_path).get(record.prediction_id) is None:
            _append_evaluation_ledger_record(target_path, payload)
    return payload


def record_recommendation(*, prediction_record: Mapping[str, Any], recommendation: Any, artifact_metadata: Any = None, persist: bool = True, ledger_path: Path | str | None = None) -> dict[str, Any]:
    prediction_payload = _copy_mapping(prediction_record)
    recommendation_payload = _copy_mapping(recommendation)
    prediction_id = str(prediction_payload.get("prediction_id") or _new_id("pred"))
    recommendation_identity = _recommendation_identity(recommendation_payload)
    payload = IntelligenceRecommendationRecord(
        prediction_id=prediction_id,
        recommendation_id=_stable_id(
            "rec",
            {
                "prediction_id": prediction_id,
                "identity": recommendation_identity,
                "recommendation": recommendation_payload,
                "artifact_metadata": _copy_mapping(artifact_metadata) or _copy_mapping(prediction_payload.get("artifact_metadata")),
            },
        ),
        query=_copy_mapping(prediction_payload.get("query")),
        response=_copy_mapping(prediction_payload.get("response")),
        recommendation=recommendation_payload,
        artifact_metadata=_copy_mapping(artifact_metadata) or _copy_mapping(prediction_payload.get("artifact_metadata")),
        result="pending",
        pnl=None,
        closing_line=None,
        implied_probability=_coerce_probability(recommendation_payload.get("implied_probability") or recommendation_payload.get("model_probability") or recommendation_payload.get("confidence")),
        stake=_coerce_float(recommendation_payload.get("stake")) or _coerce_float(prediction_payload.get("stake")) or 1.0,
        created_at=_utc_now(),
        raw={
            "prediction": prediction_payload,
            "recommendation": recommendation_payload,
        },
    ).to_dict()
    if persist:
        target_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
        if _ledger_index(target_path).get(str(payload.get("recommendation_id") or "")) is None:
            _append_evaluation_ledger_record(target_path, payload)
    return payload


def record_portfolio_event(*, prediction_record: Mapping[str, Any], portfolio_event: Any, artifact_metadata: Any = None, persist: bool = True, ledger_path: Path | str | None = None) -> dict[str, Any]:
    prediction_payload = _copy_mapping(prediction_record)
    portfolio_event_payload = _copy_mapping(portfolio_event)
    prediction_id = str(prediction_payload.get("prediction_id") or _new_id("pred"))
    recommendation_id = str(portfolio_event_payload.get("recommendation_id") or prediction_payload.get("recommendation_id") or "").strip() or None
    portfolio_event_identity = _portfolio_event_identity(portfolio_event_payload)
    payload = IntelligencePortfolioEventRecord(
        prediction_id=prediction_id,
        portfolio_event_id=_stable_id(
            "evt",
            {
                "prediction_id": prediction_id,
                "identity": portfolio_event_identity,
                "portfolio_event": portfolio_event_payload,
                "artifact_metadata": _copy_mapping(artifact_metadata) or _copy_mapping(prediction_payload.get("artifact_metadata")),
            },
        ),
        query=_copy_mapping(prediction_payload.get("query")),
        response=_copy_mapping(prediction_payload.get("response")),
        recommendation_id=recommendation_id,
        portfolio_event=portfolio_event_payload,
        artifact_metadata=_copy_mapping(artifact_metadata) or _copy_mapping(prediction_payload.get("artifact_metadata")),
        created_at=_utc_now(),
        raw={
            "prediction": prediction_payload,
            "portfolio_event": portfolio_event_payload,
            "recommendation_id": recommendation_id,
        },
    ).to_dict()
    if persist:
        target_path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
        if _ledger_index(target_path).get(str(payload.get("portfolio_event_id") or "")) is None:
            _append_evaluation_ledger_record(target_path, payload)
    return payload


def settle_result(*, record: Mapping[str, Any], result: Any, pnl: Any, closing_line: Any, implied_probability: Any | None = None, settled_at: str | None = None, persist: bool = True, ledger_path: Path | str | None = None) -> dict[str, Any]:
    payload = _copy_mapping(record)
    settled_record = {
        **payload,
        "result": _result_label(result),
        "pnl": _coerce_float(pnl),
        "closing_line": closing_line,
        "implied_probability": _coerce_probability(implied_probability if implied_probability is not None else payload.get("implied_probability")),
        "settled_at": settled_at or _utc_now(),
    }
    if persist:
        _append_evaluation_ledger_record(Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH, settled_record)
    return settled_record


def _iter_record_payloads(records: Iterable[Mapping[str, Any]] | None = None, *, ledger_path: Path | str | None = None) -> list[dict[str, Any]]:
    if records is not None:
        return [dict(item) for item in records if isinstance(item, Mapping)]
    path = Path(ledger_path) if ledger_path is not None else DEFAULT_LEDGER_PATH
    if _is_chunked_ledger_path(path):
        return _load_chunked_ledger_records(path)
    if not path.exists():
        return []
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
    return rows


def _record_sport(record: Mapping[str, Any]) -> str | None:
    recommendation = _copy_mapping(record.get("recommendation"))
    artifact_metadata = _copy_mapping(record.get("artifact_metadata"))
    response = _copy_mapping(record.get("response"))
    query = _copy_mapping(record.get("query"))
    return (
        str(recommendation.get("sport") or recommendation.get("sport_slug") or artifact_metadata.get("sport") or query.get("sport") or response.get("sport") or "").strip().lower()
        or None
    )


def _record_market_family(record: Mapping[str, Any]) -> str | None:
    recommendation = _copy_mapping(record.get("recommendation"))
    response = _copy_mapping(record.get("response"))
    market = str(
        recommendation.get("market")
        or recommendation.get("market_family")
        or recommendation.get("market_label")
        or response.get("market")
        or ""
    ).strip().lower()
    if not market:
        return None
    if any(token in market for token in ("prop", "player", "point", "rebound", "assist", "steal", "block", "shot")):
        return "props"
    if any(token in market for token in ("moneyline", "ml", "money line")):
        return "moneyline"
    if any(token in market for token in ("spread", "ats", "spreads")):
        return "spread"
    if any(token in market for token in ("total", "over", "under", "o/u")):
        return "totals"
    return market


def _latest_by_recommendation_id(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    fallback: dict[str, dict[str, Any]] = {}
    ordered_fallback: list[str] = []
    for record in records:
        if str(record.get("record_type") or "").strip().lower() == "portfolio_event":
            continue
        recommendation_id = str(record.get("recommendation_id") or "").strip()
        if not recommendation_id:
            prediction_id = str(record.get("prediction_id") or "").strip()
            fallback_key = prediction_id or f"fallback_{len(ordered_fallback)}"
            if fallback_key not in fallback:
                ordered_fallback.append(fallback_key)
            fallback[fallback_key] = record
            continue
        latest[recommendation_id] = record
    return [*(fallback[key] for key in ordered_fallback if key in fallback), *latest.values()]


def _settled_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if _result_label(record.get("result")) in {"win", "loss", "push", "void"}]


def _win_rate(records: list[dict[str, Any]]) -> float | None:
    decisive = [record for record in records if _result_label(record.get("result")) in {"win", "loss"}]
    if not decisive:
        return None
    wins = sum(1 for record in decisive if _result_label(record.get("result")) == "win")
    return wins / float(len(decisive))


def _roi(records: list[dict[str, Any]]) -> float | None:
    stakes = [(_coerce_float(record.get("stake")) or 1.0) for record in records if _coerce_float(record.get("stake")) is not None or record.get("stake") is None]
    if not stakes:
        stakes = [1.0 for _ in records]
    total_stake = sum(stakes)
    if not total_stake:
        return None
    total_pnl = sum(_coerce_float(record.get("pnl")) or 0.0 for record in records)
    return total_pnl / float(total_stake)


def _clv(records: list[dict[str, Any]]) -> float | None:
    values: list[float] = []
    for record in records:
        recommendation = _copy_mapping(record.get("recommendation"))
        open_line = _numeric_line(recommendation.get("line") or recommendation.get("projected") or record.get("line"))
        closing_line = _numeric_line(record.get("closing_line"))
        if open_line is None or closing_line is None:
            continue
        direction = _direction_from_recommendation(recommendation) or 1.0
        values.append(round((open_line - closing_line) * direction, 4))
    if not values:
        return None
    return mean(values)


def _calibration(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[float] = []
    brier_scores: list[float] = []
    for record in records:
        implied_probability = _coerce_probability(record.get("implied_probability"))
        result = _result_label(record.get("result"))
        if implied_probability is None or result not in {"win", "loss"}:
            continue
        actual = 1.0 if result == "win" else 0.0
        errors.append(abs(implied_probability - actual))
        brier_scores.append((implied_probability - actual) ** 2)
    if not errors:
        return {"mae": None, "brier_score": None, "sample_size": 0}
    return {"mae": mean(errors), "brier_score": mean(brier_scores), "sample_size": len(errors)}


def compute_metrics(*, records: Iterable[Mapping[str, Any]] | None = None, ledger_path: Path | str | None = None, sport: str | None = None) -> dict[str, Any]:
    warn_if_compute_in_request_path("compute_metrics")
    record_rows = _latest_by_recommendation_id(_iter_record_payloads(records, ledger_path=ledger_path))
    sport_slug = str(sport or "").strip().lower() or None
    if sport_slug:
        record_rows = [record for record in record_rows if _record_sport(record) in {sport_slug, None} or _record_sport(record) == sport_slug]
    settled_rows = _settled_records(record_rows)
    decisive_rows = [record for record in settled_rows if _result_label(record.get("result")) in {"win", "loss"}]
    win_rate = _win_rate(settled_rows)
    roi = _roi(settled_rows)
    clv = _clv(settled_rows)
    calibration = _calibration(settled_rows)
    return {
        "sample_size": len(record_rows),
        "settled_count": len(settled_rows),
        "decisive_count": len(decisive_rows),
        "win_rate": win_rate,
        "roi": roi,
        "clv": clv,
        "calibration": calibration,
        "pnl": sum(_coerce_float(record.get("pnl")) or 0.0 for record in settled_rows),
    }


def build_reliability_profile(*, records: Iterable[Mapping[str, Any]] | None = None, ledger_path: Path | str | None = None, sport: str | None = None) -> dict[str, Any]:
    metrics = compute_metrics(records=records, ledger_path=ledger_path, sport=sport)
    calibration = metrics.get("calibration") if isinstance(metrics.get("calibration"), Mapping) else {}
    calibration_error = _coerce_float(calibration.get("mae")) or 0.0
    win_rate = _coerce_float(metrics.get("win_rate"))
    roi = _coerce_float(metrics.get("roi"))
    sample_size = int(metrics.get("settled_count") or 0)
    calibration_penalty = min(0.14, calibration_error * 0.25)
    win_rate_adjustment = 0.0 if win_rate is None else max(-0.04, min(0.04, (win_rate - 0.5) * 0.08))
    roi_adjustment = 0.0 if roi is None else max(-0.03, min(0.03, roi * 0.12))
    reliability_multiplier = round(max(0.78, min(1.06, 1.0 - calibration_penalty + win_rate_adjustment + roi_adjustment)), 3)
    _intel_trace(
        "evaluation_reliability_profile",
        sport=sport,
        sample_size=sample_size,
        settled_count=metrics.get("settled_count"),
        calibration_error=calibration_error,
        reliability_multiplier=reliability_multiplier,
    )
    return {
        "sport": sport,
        "sample_size": sample_size,
        "metrics": metrics,
        "calibration_error": calibration_error,
        "calibration_penalty": calibration_penalty,
        "win_rate_adjustment": win_rate_adjustment,
        "roi_adjustment": roi_adjustment,
        "reliability_multiplier": reliability_multiplier,
    }


def build_evaluation_history_summary(*, records: Iterable[Mapping[str, Any]] | None = None, ledger_path: Path | str | None = None, sport: str | None = None, market_family: str | None = None) -> dict[str, Any]:
    record_rows = _latest_by_recommendation_id(_iter_record_payloads(records, ledger_path=ledger_path))
    sport_slug = str(sport or "").strip().lower() or None
    market_family_slug = str(market_family or "").strip().lower() or None
    if sport_slug:
        record_rows = [record for record in record_rows if _record_sport(record) in {sport_slug, None} or _record_sport(record) == sport_slug]
    if market_family_slug:
        record_rows = [record for record in record_rows if _record_market_family(record) in {market_family_slug, None} or _record_market_family(record) == market_family_slug]

    reliability_profile = build_reliability_profile(records=record_rows, sport=sport_slug)
    metrics = reliability_profile.get("metrics") if isinstance(reliability_profile.get("metrics"), Mapping) else {}
    settled_count = int(metrics.get("settled_count") or 0)
    decisive_count = int(metrics.get("decisive_count") or 0)
    summary = {
        "sport": sport_slug,
        "market_family": market_family_slug,
        "sample_size": int(metrics.get("sample_size") or 0),
        "settled_count": settled_count,
        "decisive_count": decisive_count,
        "win_rate": metrics.get("win_rate"),
        "roi": metrics.get("roi"),
        "clv": metrics.get("clv"),
        "calibration": metrics.get("calibration"),
        "reliability_multiplier": reliability_profile.get("reliability_multiplier"),
    }
    summary["history_status"] = "available" if summary["sample_size"] else "empty"
    return summary


def _recommendation_source(record: Mapping[str, Any]) -> dict[str, Any]:
    recommendation = _copy_mapping(record.get("recommendation"))
    if recommendation:
        return recommendation
    return _copy_mapping(record)


def _recommendation_publish_timestamp(record: Mapping[str, Any]) -> str | None:
    for key in ("created_at", "published_at", "published_timestamp", "publish_timestamp", "settled_at"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    recommendation = _recommendation_source(record)
    for key in ("created_at", "published_at", "published_timestamp", "publish_timestamp"):
        value = str(recommendation.get(key) or "").strip()
        if value:
            return value
    return None


def _recommendation_side(record: Mapping[str, Any]) -> str | None:
    recommendation = _recommendation_source(record)
    value = (
        recommendation.get("side")
        or recommendation.get("selection_side")
        or recommendation.get("lean")
        or recommendation.get("ev_side")
        or record.get("side")
    )
    text = str(value or "").strip().upper()
    return text or None


def _recommendation_market(record: Mapping[str, Any]) -> str | None:
    recommendation = _recommendation_source(record)
    value = (
        recommendation.get("market")
        or recommendation.get("market_key")
        or recommendation.get("market_label")
        or recommendation.get("market_family")
        or record.get("market")
        or record.get("market_key")
    )
    text = str(value or "").strip().lower()
    return text or None


def _recommendation_type(record: Mapping[str, Any]) -> str:
    recommendation = _recommendation_source(record)
    value = (
        recommendation.get("recommendation_type")
        or recommendation.get("type")
        or recommendation.get("candidate_type")
        or recommendation.get("kind")
        or recommendation.get("surface")
        or _record_market_family(record)
        or "unknown"
    )
    return str(value or "unknown").strip().lower() or "unknown"


def _confidence_tier(value: Any) -> str:
    confidence = _coerce_probability(value)
    if confidence is None:
        text = str(value or "").strip().lower()
        if not text:
            return "unrated"
        if text in {"a", "a+", "top", "high", "elite"}:
            return "elite"
        if text in {"b", "mid", "medium"}:
            return "medium"
        if text in {"c", "low"}:
            return "low"
        return text
    if confidence < 0.55:
        return "low"
    if confidence < 0.65:
        return "medium-low"
    if confidence < 0.75:
        return "medium-high"
    if confidence < 0.85:
        return "high"
    return "elite"


def _edge_bucket(value: Any) -> str:
    edge = _coerce_float(value)
    if edge is None:
        return "unrated"
    if edge < 0:
        return "negative"
    if edge < 2:
        return "0-2"
    if edge < 5:
        return "2-5"
    if edge < 8:
        return "5-8"
    return "8+"


def _record_stake(record: Mapping[str, Any]) -> float:
    recommendation = _recommendation_source(record)
    stake = _coerce_float(record.get("stake"))
    if stake is None:
        stake = _coerce_float(recommendation.get("stake"))
    return float(stake) if stake is not None and stake > 0 else 1.0


def _record_clv(record: Mapping[str, Any]) -> float | None:
    recommendation = _recommendation_source(record)
    open_line = _coerce_float(recommendation.get("line") or recommendation.get("projected") or record.get("line"))
    closing_line = _coerce_float(record.get("closing_line"))
    if open_line is None or closing_line is None:
        return None
    direction = _direction_from_recommendation(recommendation) or 1.0
    return round((open_line - closing_line) * direction, 4)


def _normalized_performance_record(record: Mapping[str, Any]) -> dict[str, Any]:
    recommendation = _recommendation_source(record)
    result = _result_label(record.get("result") or recommendation.get("result"))
    pnl = _coerce_float(record.get("pnl"))
    stake = _record_stake(record)
    roi = round(pnl / stake, 4) if pnl is not None else None
    edge_pct = _coerce_float(
        recommendation.get("edge_pct")
        or recommendation.get("adjusted_edge")
        or record.get("edge_pct")
        or record.get("expected_value")
    )
    if edge_pct is None:
        edge_value = _coerce_float(recommendation.get("edge") or record.get("edge"))
        if edge_value is not None:
            edge_pct = round(edge_value * 100.0, 2) if abs(edge_value) <= 1.0 else round(edge_value, 2)
    edge_bucket = _edge_bucket(edge_pct)
    model_probability = _coerce_probability(recommendation.get("model_probability") or record.get("model_probability") or recommendation.get("confidence") or record.get("confidence"))
    implied_probability = _coerce_probability(record.get("implied_probability") or recommendation.get("implied_probability"))
    confidence_value = recommendation.get("confidence") or record.get("confidence") or recommendation.get("tier") or recommendation.get("klass")
    normalized = {
        "prediction_id": str(record.get("prediction_id") or "").strip() or None,
        "recommendation_id": str(record.get("recommendation_id") or "").strip() or None,
        "sport": _record_sport(record),
        "market": _recommendation_market(record),
        "side": _recommendation_side(record),
        "line": _coerce_float(recommendation.get("line") or recommendation.get("market_line") or record.get("line")),
        "odds": _coerce_float(recommendation.get("odds") or record.get("odds")),
        "model_probability": model_probability,
        "implied_probability": implied_probability,
        "edge_pct": edge_pct,
        "edge_bucket": edge_bucket,
        "confidence": confidence_value,
        "confidence_tier": _confidence_tier(confidence_value),
        "publish_timestamp": _recommendation_publish_timestamp(record),
        "result": result,
        "pnl": pnl,
        "stake": stake,
        "roi": roi,
        "clv": _record_clv(record),
        "recommendation_type": _recommendation_type(record),
        "selection": str(recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name") or record.get("selection") or record.get("pick") or record.get("name") or "").strip() or None,
        "name": str(recommendation.get("name") or recommendation.get("player") or recommendation.get("team") or record.get("name") or record.get("player") or record.get("team") or "").strip() or None,
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _aggregate_performance_rows(rows: list[dict[str, Any]], *, bucket_key: str, label_key: str | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = str(row.get(bucket_key) or "unrated").strip().lower() or "unrated"
        label = str(row.get(label_key) or bucket).strip() if label_key else bucket
        bucket_row = grouped.setdefault(
            bucket,
            {
                "bucket": bucket,
                "label": label,
                "publish_count": 0,
                "settled_count": 0,
                "wins": 0,
                "losses": 0,
                "pushes": 0,
                "stake_total": 0.0,
                "pnl_total": 0.0,
                "clv_values": [],
                "edge_values": [],
                "model_prob_values": [],
                "implied_prob_values": [],
            },
        )
        bucket_row["publish_count"] += 1
        result = str(row.get("result") or "pending").strip().lower() or "pending"
        if result in {"win", "loss", "push", "void"}:
            bucket_row["settled_count"] += 1
            bucket_row["stake_total"] += float(row.get("stake") or 1.0)
            bucket_row["pnl_total"] += float(row.get("pnl") or 0.0)
        if result == "win":
            bucket_row["wins"] += 1
        elif result == "loss":
            bucket_row["losses"] += 1
        elif result in {"push", "void"}:
            bucket_row["pushes"] += 1
        clv_value = _coerce_float(row.get("clv"))
        if clv_value is not None:
            bucket_row["clv_values"].append(clv_value)
        edge_value = _coerce_float(row.get("edge_pct"))
        if edge_value is not None:
            bucket_row["edge_values"].append(edge_value)
        model_probability = _coerce_probability(row.get("model_probability"))
        if model_probability is not None:
            bucket_row["model_prob_values"].append(model_probability)
        implied_probability = _coerce_probability(row.get("implied_probability"))
        if implied_probability is not None:
            bucket_row["implied_prob_values"].append(implied_probability)

    summaries: list[dict[str, Any]] = []
    for bucket_row in grouped.values():
        decisive = bucket_row["wins"] + bucket_row["losses"]
        roi = round(bucket_row["pnl_total"] / bucket_row["stake_total"], 4) if bucket_row["stake_total"] > 0 else None
        summaries.append(
            {
                "bucket": bucket_row["bucket"],
                "label": bucket_row["label"],
                "publish_count": bucket_row["publish_count"],
                "settled_count": bucket_row["settled_count"],
                "wins": bucket_row["wins"],
                "losses": bucket_row["losses"],
                "pushes": bucket_row["pushes"],
                "win_rate": (bucket_row["wins"] / float(decisive)) if decisive else None,
                "roi": roi,
                "clv": mean(bucket_row["clv_values"]) if bucket_row["clv_values"] else None,
                "avg_edge": mean(bucket_row["edge_values"]) if bucket_row["edge_values"] else None,
                "avg_model_probability": mean(bucket_row["model_prob_values"]) if bucket_row["model_prob_values"] else None,
                "avg_implied_probability": mean(bucket_row["implied_prob_values"]) if bucket_row["implied_prob_values"] else None,
            }
        )

    def _sort_key(item: Mapping[str, Any]) -> tuple[int, float, str]:
        return (
            int(item.get("publish_count") or 0),
            float(item.get("roi") or -9999.0),
            str(item.get("label") or item.get("bucket") or ""),
        )

    return sorted(summaries, key=_sort_key, reverse=True)


def build_recommendation_performance_analytics(*, records: Iterable[Mapping[str, Any]] | None = None, ledger_path: Path | str | None = None) -> dict[str, Any]:
    raw_records = _latest_by_recommendation_id(_iter_record_payloads(records, ledger_path=ledger_path))
    normalized_records = [_normalized_performance_record(record) for record in raw_records]
    settled_records = [record for record in normalized_records if str(record.get("result") or "").strip().lower() in {"win", "loss", "push", "void"}]
    total_stake = sum(float(record.get("stake") or 1.0) for record in settled_records)
    total_pnl = sum(float(record.get("pnl") or 0.0) for record in settled_records)
    summary = {
        "publish_count": len(normalized_records),
        "settled_count": len(settled_records),
        "win_rate": None,
        "roi": round(total_pnl / total_stake, 4) if total_stake > 0 else None,
        "clv": mean([float(record.get("clv")) for record in settled_records if record.get("clv") is not None]) if any(record.get("clv") is not None for record in settled_records) else None,
        "total_pnl": round(total_pnl, 4),
    }
    decisive_records = [record for record in settled_records if str(record.get("result") or "").strip().lower() in {"win", "loss"}]
    if decisive_records:
        wins = sum(1 for record in decisive_records if str(record.get("result") or "").strip().lower() == "win")
        summary["win_rate"] = wins / float(len(decisive_records))

    return {
        "summary": summary,
        "records": normalized_records,
        "by_sport": _aggregate_performance_rows(normalized_records, bucket_key="sport"),
        "by_market": _aggregate_performance_rows(normalized_records, bucket_key="market"),
        "by_confidence_tier": _aggregate_performance_rows(normalized_records, bucket_key="confidence_tier"),
        "by_edge_bucket": _aggregate_performance_rows(normalized_records, bucket_key="edge_bucket"),
        "by_recommendation_type": _aggregate_performance_rows(normalized_records, bucket_key="recommendation_type"),
    }


def adjust_confidence(base_confidence: float, *, records: Iterable[Mapping[str, Any]] | None = None, ledger_path: Path | str | None = None, sport: str | None = None) -> tuple[float, dict[str, Any]]:
    profile = build_reliability_profile(records=records, ledger_path=ledger_path, sport=sport)
    adjusted = float(base_confidence)
    adjusted -= float(profile.get("calibration_penalty") or 0.0)
    adjusted += float(profile.get("win_rate_adjustment") or 0.0)
    adjusted += float(profile.get("roi_adjustment") or 0.0)
    adjusted = max(0.05, min(0.99, adjusted))
    return round(adjusted, 2), profile


def build_intelligence_evaluation_bundle(*, query: Any, response: Any, persist: bool = True, ledger_path: Path | str | None = None) -> dict[str, Any]:
    evaluation_started_at = time.perf_counter()
    query_payload = _copy_mapping(query)
    response_payload = _copy_mapping(response)
    recommendation_rows = [item for item in response_payload.get("recommendations") or [] if isinstance(item, Mapping)]
    artifact_metadata = build_artifact_metadata(query=query_payload, response=response_payload)
    policy_control = _policy_control_summary(response=response_payload, recommendations=recommendation_rows)
    portfolio_tracking = _portfolio_tracking_summary(response=response_payload, recommendations=recommendation_rows)
    portfolio_events = _portfolio_event_summary(response=response_payload)
    prediction_record = record_prediction(query=query_payload, response=response_payload, artifact_metadata=artifact_metadata, persist=persist, ledger_path=ledger_path)
    recommendation_records = [
        record_recommendation(
            prediction_record=prediction_record,
            recommendation=recommendation,
            artifact_metadata=artifact_metadata,
            persist=persist,
            ledger_path=ledger_path,
        )
        for recommendation in recommendation_rows
    ]
    portfolio_event_rows = [item for item in response_payload.get("portfolio_events") or [] if isinstance(item, Mapping)]
    portfolio_event_records = [
        record_portfolio_event(
            prediction_record=prediction_record,
            portfolio_event=portfolio_event,
            artifact_metadata=artifact_metadata,
            persist=persist,
            ledger_path=ledger_path,
        )
        for portfolio_event in portfolio_event_rows
    ]
    market_features = [
        recommendation.get("market_features")
        for recommendation in recommendation_rows
        if isinstance(recommendation.get("market_features"), Mapping)
    ]
    history_summary = build_evaluation_history_summary(
        records=None,
        ledger_path=ledger_path,
        sport=artifact_metadata.get("sport"),
        market_family=_record_market_family(recommendation_records[0]) if recommendation_records else None,
    )
    performance_analytics = build_recommendation_performance_analytics(records=None, ledger_path=ledger_path)
    _intel_trace(
        "evaluation_bundle",
        recommendation_count=len(recommendation_rows),
        recommendation_records=len(recommendation_records),
        portfolio_event_records=len(portfolio_event_records),
        market_features=len(market_features),
        history_status=history_summary.get("history_status") if isinstance(history_summary, dict) else None,
        performance_publish_count=performance_analytics.get("summary", {}).get("publish_count") if isinstance(performance_analytics, dict) else None,
    )
    _intel_trace_timed(
        "evaluation_bundle",
        evaluation_started_at,
        recommendation_count=len(recommendation_rows),
        recommendation_records=len(recommendation_records),
        portfolio_event_records=len(portfolio_event_records),
        market_features=len(market_features),
        history_status=history_summary.get("history_status") if isinstance(history_summary, dict) else None,
        performance_publish_count=performance_analytics.get("summary", {}).get("publish_count") if isinstance(performance_analytics, dict) else None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "prediction": prediction_record,
        "recommendations": recommendation_records,
        "artifact_metadata": artifact_metadata,
        "policy_control": policy_control,
        "portfolio_tracking": portfolio_tracking,
        "portfolio_events": portfolio_events,
        "portfolio_event_records": portfolio_event_records,
        "metrics": compute_metrics(records=recommendation_records),
        "market_summary": market_feature_summary(market_features),
        "history": history_summary,
        "performance_analytics": performance_analytics,
    }


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_LEDGER_CHUNK_ROOT",
    "build_artifact_metadata",
    "build_reliability_profile",
    "build_intelligence_evaluation_bundle",
    "build_evaluation_history_summary",
    "build_recommendation_performance_analytics",
    "adjust_confidence",
    "compute_metrics",
    "record_prediction",
    "record_recommendation",
    "record_portfolio_event",
    "settle_result",
]