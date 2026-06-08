from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _copy_sequence_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _as_text_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return _copy_sequence_of_strings(value)
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


@dataclass(frozen=True)
class IntelligenceQueryRecord:
    schema_version: int = 1
    question: str | None = None
    selected_date: str | None = None
    query_type: str | None = None
    intent: str | None = None
    sport: str | None = None
    subject: str | None = None
    preview_subject: str | None = None
    player_subject: str | None = None
    requested_sports: tuple[str, ...] = ()
    requested_markets: tuple[str, ...] = ()
    limit: int | None = None
    timing: str | None = None
    mode: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> IntelligenceQueryRecord:
        payload = _copy_mapping(raw)
        subject = _first_text(payload.get("subject"), payload.get("preview_subject"), payload.get("player_subject"), payload.get("team"))
        return cls(
            question=_first_text(payload.get("question"), payload.get("query"), payload.get("prompt")),
            selected_date=_first_text(payload.get("selected_date"), payload.get("date")),
            query_type=_first_text(payload.get("query_type"), payload.get("intent")),
            intent=_first_text(payload.get("intent"), payload.get("query_type")),
            sport=_first_text(payload.get("sport"), payload.get("sport_slug")),
            subject=subject,
            preview_subject=_first_text(payload.get("preview_subject")),
            player_subject=_first_text(payload.get("player_subject")),
            requested_sports=_as_text_list(payload.get("requested_sports")),
            requested_markets=_as_text_list(payload.get("requested_markets")),
            limit=_parse_int(payload.get("limit")),
            timing=_first_text(payload.get("timing")),
            mode=_first_text(payload.get("mode")),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["schema_version"] = self.schema_version
        if self.question is not None:
            payload["question"] = self.question
        if self.selected_date is not None:
            payload["selected_date"] = self.selected_date
        if self.query_type is not None:
            payload["query_type"] = self.query_type
        if self.intent is not None:
            payload["intent"] = self.intent
        if self.sport is not None:
            payload["sport"] = self.sport
        if self.subject is not None:
            payload["subject"] = self.subject
        if self.preview_subject is not None:
            payload["preview_subject"] = self.preview_subject
        if self.player_subject is not None:
            payload["player_subject"] = self.player_subject
        if self.requested_sports:
            payload["requested_sports"] = list(self.requested_sports)
        if self.requested_markets:
            payload["requested_markets"] = list(self.requested_markets)
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.timing is not None:
            payload["timing"] = self.timing
        if self.mode is not None:
            payload["mode"] = self.mode
        return payload


@dataclass(frozen=True)
class IntelligenceEvaluationRecord:
    schema_version: int = 1
    query: IntelligenceQueryRecord = field(default_factory=IntelligenceQueryRecord)
    response: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    recommendation_count: int = 0
    top_recommendation: dict[str, Any] = field(default_factory=dict)
    analysis_focus: str | None = None
    headline: str | None = None
    summary: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["schema_version"] = self.schema_version
        payload["query"] = self.query.to_dict()
        payload["response"] = dict(self.response)
        payload["outcome"] = dict(self.outcome)
        payload["recommendation_count"] = self.recommendation_count
        payload["top_recommendation"] = dict(self.top_recommendation)
        if self.analysis_focus is not None:
            payload["analysis_focus"] = self.analysis_focus
        if self.headline is not None:
            payload["headline"] = self.headline
        if self.summary is not None:
            payload["summary"] = self.summary
        return payload

    @classmethod
    def from_payloads(
        cls,
        *,
        query: Any,
        response: Any,
        outcome: Any = None,
    ) -> IntelligenceEvaluationRecord:
        query_record = IntelligenceQueryRecord.from_raw(query)
        response_payload = _copy_mapping(response)
        recommendations = response_payload.get("recommendations") if isinstance(response_payload.get("recommendations"), list) else []
        recommendation_rows = [item for item in recommendations if isinstance(item, Mapping)]
        top_recommendation = dict(recommendation_rows[0]) if recommendation_rows else {}
        analysis_views = response_payload.get("analysis_views") if isinstance(response_payload.get("analysis_views"), Mapping) else {}
        response_summary = {
            "headline": _first_text(response_payload.get("headline")),
            "summary": _first_text(response_payload.get("summary")),
            "recommendation_count": len(recommendation_rows),
            "analysis_focus": _first_text(analysis_views.get("focus")),
            "top_recommendation": top_recommendation,
        }
        outcome_payload = _copy_mapping(outcome)
        return cls(
            query=query_record,
            response=response_summary,
            outcome=outcome_payload,
            recommendation_count=len(recommendation_rows),
            top_recommendation=top_recommendation,
            analysis_focus=_first_text(analysis_views.get("focus")),
            headline=_first_text(response_payload.get("headline")),
            summary=_first_text(response_payload.get("summary")),
            raw={"query": query_record.to_dict(), "response": response_summary, "outcome": outcome_payload},
        )


def build_intelligence_evaluation_record(*, query: Any, response: Any, outcome: Any = None) -> dict[str, Any]:
    return IntelligenceEvaluationRecord.from_payloads(query=query, response=response, outcome=outcome).to_dict()


__all__ = [
    "IntelligenceEvaluationRecord",
    "IntelligenceQueryRecord",
    "build_intelligence_evaluation_record",
]