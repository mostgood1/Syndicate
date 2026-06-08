from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _copy_sequence_of_mappings(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _copy_sequence_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


@dataclass(frozen=True)
class Evidence:
    source_type: str | None = None
    entity: str | None = None
    metric: str | None = None
    value: Any = None
    context: str | None = None
    timestamp: str | None = None
    kind: str | None = None
    title: str | None = None
    focus: str | None = None
    summary: str | None = None
    detail: str | None = None
    label: str | None = None
    columns: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    sections: tuple[Evidence, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> Evidence | None:
        payload = _copy_mapping(raw)
        if not payload:
            return None
        return cls(
            source_type=str(payload.get("source_type") or payload.get("source") or payload.get("kind") or payload.get("type") or "").strip() or None,
            entity=str(payload.get("entity") or payload.get("team") or payload.get("player") or payload.get("subject") or payload.get("name") or "").strip() or None,
            metric=str(payload.get("metric") or payload.get("market") or payload.get("focus") or payload.get("label") or "").strip() or None,
            value=payload.get("value") if "value" in payload else payload.get("result") if "result" in payload else payload.get("projected") if "projected" in payload else payload.get("line") if "line" in payload else payload.get("score"),
            context=str(payload.get("context") or payload.get("why") or payload.get("summary") or payload.get("detail") or payload.get("description") or payload.get("note") or "").strip() or None,
            timestamp=str(payload.get("timestamp") or payload.get("generated_at") or payload.get("generatedAt") or payload.get("selected_date") or payload.get("date") or "").strip() or None,
            kind=str(payload.get("kind") or payload.get("type") or "").strip() or None,
            title=str(payload.get("title") or "").strip() or None,
            focus=str(payload.get("focus") or "").strip() or None,
            summary=str(payload.get("summary") or "").strip() or None,
            detail=str(payload.get("detail") or "").strip() or None,
            label=str(payload.get("label") or "").strip() or None,
            columns=_copy_sequence_of_strings(payload.get("columns")),
            items=_copy_sequence_of_mappings(payload.get("items")),
            rows=_copy_sequence_of_mappings(payload.get("rows")),
            sections=tuple(item for item in (cls.from_raw(section) for section in payload.get("sections") or []) if item is not None),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        if self.source_type is not None:
            payload["source_type"] = self.source_type
        if self.entity is not None:
            payload["entity"] = self.entity
        if self.metric is not None:
            payload["metric"] = self.metric
        if self.value is not None:
            payload["value"] = self.value
        if self.context is not None:
            payload["context"] = self.context
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        if self.kind is not None:
            payload["kind"] = self.kind
        if self.title is not None:
            payload["title"] = self.title
        if self.focus is not None:
            payload["focus"] = self.focus
        if self.summary is not None:
            payload["summary"] = self.summary
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.label is not None:
            payload["label"] = self.label
        if self.columns:
            payload["columns"] = list(self.columns)
        if self.items:
            payload["items"] = [dict(item) for item in self.items]
        if self.rows:
            payload["rows"] = [dict(row) for row in self.rows]
        if self.sections:
            payload["sections"] = [section.to_dict() for section in self.sections]
        return payload


@dataclass(frozen=True)
class Insight:
    name: str | None = None
    sport_slug: str | None = None
    market: str | None = None
    pick: str | None = None
    matchup: str | None = None
    candidate_type: str | None = None
    analysis_focus: str | None = None
    rationale: str | None = None
    writeup: str | None = None
    summary: str | None = None
    confidence: str | None = None
    odds: str | None = None
    line: Any = None
    projected: Any = None
    live_projection: Any = None
    edge: Any = None
    score: float | None = None
    market_fit_score: float | None = None
    advanced_signal_score: float | None = None
    source_summary_score: float | None = None
    advanced_ready: bool | None = None
    is_live: bool | None = None
    href: str | None = None
    display_pills: tuple[str, ...] = ()
    advanced_inputs: tuple[dict[str, Any], ...] = ()
    advanced_signals: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> Insight | None:
        payload = _copy_mapping(raw)
        if not payload:
            return None
        return cls(
            name=str(payload.get("name") or "").strip() or None,
            sport_slug=str(payload.get("sport_slug") or "").strip() or None,
            market=str(payload.get("market") or "").strip() or None,
            pick=str(payload.get("pick") or "").strip() or None,
            matchup=str(payload.get("matchup") or "").strip() or None,
            candidate_type=str(payload.get("candidate_type") or "").strip() or None,
            analysis_focus=str(payload.get("analysis_focus") or "").strip() or None,
            rationale=str(payload.get("rationale") or "").strip() or None,
            writeup=str(payload.get("writeup") or "").strip() or None,
            summary=str(payload.get("summary") or "").strip() or None,
            confidence=str(payload.get("confidence") or "").strip() or None,
            odds=str(payload.get("odds") or "").strip() or None,
            line=payload.get("line"),
            projected=payload.get("projected"),
            live_projection=payload.get("live_projection"),
            edge=payload.get("edge"),
            score=_parse_float(payload.get("score")),
            market_fit_score=_parse_float(payload.get("market_fit_score")),
            advanced_signal_score=_parse_float(payload.get("advanced_signal_score")),
            source_summary_score=_parse_float(payload.get("source_summary_score")),
            advanced_ready=_parse_bool(payload.get("advanced_ready")),
            is_live=_parse_bool(payload.get("is_live")),
            href=str(payload.get("href") or "").strip() or None,
            display_pills=_copy_sequence_of_strings(payload.get("display_pills")),
            advanced_inputs=_copy_sequence_of_mappings(payload.get("advanced_inputs")),
            advanced_signals=_copy_sequence_of_mappings(payload.get("advanced_signals")),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        for key, value in (
            ("name", self.name),
            ("sport_slug", self.sport_slug),
            ("market", self.market),
            ("pick", self.pick),
            ("matchup", self.matchup),
            ("candidate_type", self.candidate_type),
            ("analysis_focus", self.analysis_focus),
            ("rationale", self.rationale),
            ("writeup", self.writeup),
            ("summary", self.summary),
            ("confidence", self.confidence),
            ("odds", self.odds),
            ("line", self.line),
            ("projected", self.projected),
            ("live_projection", self.live_projection),
            ("edge", self.edge),
            ("score", self.score),
            ("market_fit_score", self.market_fit_score),
            ("advanced_signal_score", self.advanced_signal_score),
            ("source_summary_score", self.source_summary_score),
            ("advanced_ready", self.advanced_ready),
            ("is_live", self.is_live),
            ("href", self.href),
        ):
            if value is not None:
                payload[key] = value
        if self.display_pills:
            payload["display_pills"] = list(self.display_pills)
        if self.advanced_inputs:
            payload["advanced_inputs"] = [dict(item) for item in self.advanced_inputs]
        if self.advanced_signals:
            payload["advanced_signals"] = [dict(item) for item in self.advanced_signals]
        return payload


@dataclass(frozen=True)
class IntelligenceResult:
    selected_date: str | None = None
    query_type: str | None = None
    preferences: dict[str, Any] = field(default_factory=dict)
    headline: str | None = None
    summary: str | None = None
    parsed_request: dict[str, Any] = field(default_factory=dict)
    recommendations: tuple[Insight, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    parlays: tuple[dict[str, Any], ...] = ()
    analysis_views: dict[str, Any] = field(default_factory=dict)
    analysis_brief: Evidence | None = None
    supporting_evidence: Evidence | None = None
    structured_response: dict[str, Any] = field(default_factory=dict)
    reasoning_steps: tuple[dict[str, Any], ...] = ()
    board_notes: tuple[str, ...] = ()
    readiness_gate: dict[str, Any] = field(default_factory=dict)
    local_only: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    pipeline_request: dict[str, Any] = field(default_factory=dict, repr=False)
    pipeline_context: dict[str, Any] = field(default_factory=dict, repr=False)
    pipeline_stages: tuple[str, ...] = field(default_factory=tuple, repr=False)

    @classmethod
    def from_raw(cls, raw: Any, *, pipeline_request: Mapping[str, Any] | None = None, pipeline_context: Mapping[str, Any] | None = None, pipeline_stages: tuple[str, ...] | None = None, evidence: tuple[Evidence, ...] | None = None) -> IntelligenceResult:
        payload = _copy_mapping(raw)
        recommendations = tuple(item for item in (Insight.from_raw(item) for item in payload.get("recommendations") or []) if item is not None)
        evidence_items = tuple(item for item in (evidence or ()) if item is not None)
        analysis_brief = Evidence.from_raw(payload.get("analysis_brief"))
        supporting_evidence = Evidence.from_raw(payload.get("supporting_evidence"))
        parlays = tuple(dict(item) for item in (payload.get("parlays") or []) if isinstance(item, Mapping))
        reasoning_steps = tuple(dict(item) for item in (payload.get("reasoning_steps") or []) if isinstance(item, Mapping))
        board_notes = _copy_sequence_of_strings(payload.get("board_notes"))
        return cls(
            selected_date=str(payload.get("selected_date") or "").strip() or None,
            query_type=str(payload.get("query_type") or "").strip() or None,
            preferences=_copy_mapping(payload.get("preferences")),
            headline=str(payload.get("headline") or "").strip() or None,
            summary=str(payload.get("summary") or "").strip() or None,
            parsed_request=_copy_mapping(payload.get("parsed_request")),
            recommendations=recommendations,
            evidence=evidence_items,
            parlays=parlays,
            analysis_views=_copy_mapping(payload.get("analysis_views")),
            analysis_brief=analysis_brief,
            supporting_evidence=supporting_evidence,
            structured_response=_copy_mapping(payload.get("structured_response")),
            reasoning_steps=reasoning_steps,
            board_notes=board_notes,
            readiness_gate=_copy_mapping(payload.get("readiness_gate")),
            local_only=_parse_bool(payload.get("local_only")),
            raw=payload,
            pipeline_request=_copy_mapping(pipeline_request),
            pipeline_context=_copy_mapping(pipeline_context),
            pipeline_stages=tuple(str(item).strip() for item in (pipeline_stages or ()) if str(item).strip()),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        if self.selected_date is not None:
            payload["selected_date"] = self.selected_date
        if self.query_type is not None:
            payload["query_type"] = self.query_type
        payload["preferences"] = dict(self.preferences)
        if self.headline is not None:
            payload["headline"] = self.headline
        if self.summary is not None:
            payload["summary"] = self.summary
        payload["parsed_request"] = dict(self.parsed_request)
        payload["recommendations"] = [item.to_dict() for item in self.recommendations]
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        payload["parlays"] = [dict(item) for item in self.parlays]
        payload["analysis_views"] = dict(self.analysis_views)
        if self.analysis_brief is not None:
            payload["analysis_brief"] = self.analysis_brief.to_dict()
        if self.supporting_evidence is not None:
            payload["supporting_evidence"] = self.supporting_evidence.to_dict()
        payload["structured_response"] = dict(self.structured_response)
        payload["reasoning_steps"] = [dict(item) for item in self.reasoning_steps]
        payload["board_notes"] = list(self.board_notes)
        payload["readiness_gate"] = dict(self.readiness_gate)
        if self.local_only is not None:
            payload["local_only"] = self.local_only
        return payload


__all__ = ["Evidence", "Insight", "IntelligenceResult"]
