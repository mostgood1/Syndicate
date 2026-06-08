from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pipeline.intelligence_models import Evidence
from pipeline.intelligence_models import IntelligenceResult


_SOURCE_KEYS = ("source_type", "source", "kind", "type", "origin")
_ENTITY_KEYS = ("entity", "subject", "name", "player", "team", "matchup")
_METRIC_KEYS = ("metric", "market", "label", "focus", "title")
_VALUE_KEYS = ("value", "result", "projected", "live_projection", "line", "score", "confidence", "odds")
_CONTEXT_KEYS = ("context", "why", "summary", "detail", "description", "note", "rationale")
_TIMESTAMP_KEYS = ("timestamp", "generated_at", "generatedAt", "updated_at", "updatedAt", "selected_date", "selectedDate", "date")


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return None


def _first_value(payload: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return None


def _evidence_from_payload(payload: Mapping[str, Any], *, source_type: str | None = None, default_timestamp: str | None = None) -> Evidence | None:
    data = _copy_mapping(payload)
    if not data:
        return None
    normalized_source = _first_text(data, _SOURCE_KEYS) or source_type
    normalized_entity = _first_text(data, _ENTITY_KEYS)
    normalized_metric = _first_text(data, _METRIC_KEYS)
    normalized_value = _first_value(data, _VALUE_KEYS)
    normalized_context = _first_text(data, _CONTEXT_KEYS)
    normalized_timestamp = _first_text(data, _TIMESTAMP_KEYS) or default_timestamp
    if not any((normalized_source, normalized_entity, normalized_metric, normalized_value, normalized_context, normalized_timestamp)):
        return None
    return Evidence(
        source_type=normalized_source,
        entity=normalized_entity,
        metric=normalized_metric,
        value=normalized_value,
        context=normalized_context,
        timestamp=normalized_timestamp,
        kind=str(data.get("kind") or data.get("type") or "").strip() or None,
        title=str(data.get("title") or "").strip() or None,
        focus=str(data.get("focus") or "").strip() or None,
        summary=str(data.get("summary") or "").strip() or None,
        detail=str(data.get("detail") or "").strip() or None,
        label=str(data.get("label") or "").strip() or None,
        columns=tuple(str(item).strip() for item in data.get("columns") or [] if str(item).strip()) if isinstance(data.get("columns"), list) else (),
        items=tuple(dict(item) for item in data.get("items") or [] if isinstance(item, Mapping)) if isinstance(data.get("items"), list) else (),
        rows=tuple(dict(item) for item in data.get("rows") or [] if isinstance(item, Mapping)) if isinstance(data.get("rows"), list) else (),
        sections=tuple(item for item in (Evidence.from_raw(section) for section in data.get("sections") or []) if item is not None),
        raw=data,
    )


def _maybe_append(records: list[Evidence], record: Evidence | None) -> None:
    if record is not None:
        records.append(record)


def _extract_from_nested_container(records: list[Evidence], value: Any, *, source_type: str, timestamp: str | None = None) -> None:
    if isinstance(value, Mapping):
        _maybe_append(records, _evidence_from_payload(value, source_type=source_type, default_timestamp=timestamp))
        for nested_key in ("sections", "items", "rows"):
            nested_value = value.get(nested_key)
            if isinstance(nested_value, list):
                for item in nested_value:
                    _extract_from_nested_container(records, item, source_type=source_type, timestamp=timestamp)
        return
    if isinstance(value, list):
        for item in value:
            _extract_from_nested_container(records, item, source_type=source_type, timestamp=timestamp)


def _extract_reasoning_step_records(records: list[Evidence], raw_steps: Any, *, selected_date: str | None = None) -> None:
    if not isinstance(raw_steps, list):
        return
    for step in raw_steps:
        if not isinstance(step, Mapping):
            continue
        step_timestamp = str(step.get("timestamp") or selected_date or "").strip() or None
        _maybe_append(
            records,
            _evidence_from_payload(
                {
                    "source_type": "reasoning_step",
                    "entity": step.get("step_label") or step.get("label") or step.get("question") or "Reasoning step",
                    "metric": step.get("step_type") or step.get("kind") or "step",
                    "value": step.get("result_count") if step.get("result_count") is not None else step.get("score"),
                    "context": step.get("summary") or step.get("answer") or step.get("question"),
                    "timestamp": step_timestamp,
                },
                source_type="reasoning_step",
                default_timestamp=step_timestamp,
            ),
        )
        for nested_key in ("evidence", "supporting_evidence", "results"):
            nested_value = step.get(nested_key)
            if isinstance(nested_value, Mapping):
                _extract_from_nested_container(records, nested_value, source_type="reasoning_step", timestamp=step_timestamp)
            elif isinstance(nested_value, list):
                for item in nested_value:
                    _extract_from_nested_container(records, item, source_type="reasoning_step", timestamp=step_timestamp)


def build_evidence_records(raw_output: Any, *, selected_date: str | None = None) -> tuple[Evidence, ...]:
    payload = _copy_mapping(raw_output.raw if isinstance(raw_output, IntelligenceResult) else raw_output)
    if not payload and isinstance(raw_output, IntelligenceResult):
        payload = raw_output.to_dict()
    default_timestamp = selected_date or _first_text(payload, _TIMESTAMP_KEYS)
    records: list[Evidence] = []

    for recommendation in payload.get("recommendations") or []:
        if isinstance(recommendation, Mapping):
            _maybe_append(records, _evidence_from_payload(recommendation, source_type="recommendation", default_timestamp=default_timestamp))

    for key, source_type in (
        ("analysis_brief", "analysis_brief"),
        ("supporting_evidence", "supporting_evidence"),
    ):
        container = payload.get(key)
        if isinstance(container, Mapping):
            _extract_from_nested_container(records, container, source_type=source_type, timestamp=default_timestamp)

    for parlay in payload.get("parlays") or []:
        if isinstance(parlay, Mapping):
            _maybe_append(records, _evidence_from_payload(parlay, source_type="parlay", default_timestamp=default_timestamp))

    if isinstance(payload.get("analysis_views"), Mapping):
        _extract_from_nested_container(records, payload.get("analysis_views"), source_type="analysis_view", timestamp=default_timestamp)

    _extract_reasoning_step_records(records, payload.get("reasoning_steps"), selected_date=selected_date)

    deduped: list[Evidence] = []
    seen: set[tuple[Any, ...]] = set()
    for item in records:
        signature = (item.source_type, item.entity, item.metric, item.value, item.context, item.timestamp, item.kind, item.title, item.label)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(item)
    return tuple(deduped)


def attach_evidence(result: IntelligenceResult, raw_output: Any, *, selected_date: str | None = None) -> IntelligenceResult:
    return replace(result, evidence=build_evidence_records(raw_output, selected_date=selected_date))