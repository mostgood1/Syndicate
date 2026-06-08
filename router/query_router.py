from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import re


@dataclass(frozen=True)
class QueryRoute:
    question: str
    query_type: str
    pipeline_mode: str
    preview_subject: str | None = None
    player_subject: str | None = None
    bet_subject: str | None = None


class QueryRouter:
    _BET_EVALUATION_PATTERNS = (
        re.compile(r"\bshould i bet\s+(?P<subject>.+?)(?:\?|$)", re.IGNORECASE),
        re.compile(r"\bis\s+(?P<subject>.+?)\s+a good bet\b", re.IGNORECASE),
        re.compile(r"\bworth taking\s+(?P<subject>.+?)(?:\?|$)", re.IGNORECASE),
        re.compile(r"\bshould i take\s+(?P<subject>.+?)(?:\?|$)", re.IGNORECASE),
    )
    _PLAYER_ANALYSIS_PATTERNS = (
        re.compile(r"\banaly[sz]e\s+(?P<subject>.+?)(?:\s+tonight\b|$)", re.IGNORECASE),
        re.compile(r"\bbreak down\s+(?P<subject>.+?)(?:\s+tonight\b|$)", re.IGNORECASE),
    )
    _PREVIEW_PATTERNS = (
        re.compile(r"\bpreview\b.*\bgame\b", re.IGNORECASE),
        re.compile(r"\bgame preview\b", re.IGNORECASE),
    )
    _LIVE_PATTERNS = (
        re.compile(r"\blive\b", re.IGNORECASE),
        re.compile(r"\bin[- ]game\b", re.IGNORECASE),
        re.compile(r"\bcurrently\b", re.IGNORECASE),
        re.compile(r"\bnow\b", re.IGNORECASE),
        re.compile(r"\bhalftime\b", re.IGNORECASE),
        re.compile(r"\bovertime\b", re.IGNORECASE),
        re.compile(r"\b(?:1st|2nd|3rd|4th) quarter\b", re.IGNORECASE),
        re.compile(r"\bq[1-4]\b", re.IGNORECASE),
    )
    _COMPARISON_PATTERNS = (
        re.compile(r"\bcompare\b", re.IGNORECASE),
        re.compile(r"\bcomparison\b", re.IGNORECASE),
        re.compile(r"\bversus\b", re.IGNORECASE),
        re.compile(r"\bvs\.?\b", re.IGNORECASE),
        re.compile(r"\bdifference between\b", re.IGNORECASE),
        re.compile(r"\bwhich is better\b", re.IGNORECASE),
    )
    _TREND_PATTERNS = (
        re.compile(r"\btrend(?:s)?\b", re.IGNORECASE),
        re.compile(r"\brecent\b", re.IGNORECASE),
        re.compile(r"\blast\s+(?:\d+|five|ten)\b", re.IGNORECASE),
        re.compile(r"\bover the last\b", re.IGNORECASE),
        re.compile(r"\brolling\b", re.IGNORECASE),
        re.compile(r"\bstreak\b", re.IGNORECASE),
        re.compile(r"\bform\b", re.IGNORECASE),
        re.compile(r"\baverage\b", re.IGNORECASE),
    )
    _RISK_PATTERNS = (
        re.compile(r"\brisk\b", re.IGNORECASE),
        re.compile(r"\brisky\b", re.IGNORECASE),
        re.compile(r"\buncertain(?:ty)?\b", re.IGNORECASE),
        re.compile(r"\bvolatile\b", re.IGNORECASE),
        re.compile(r"\bvariance\b", re.IGNORECASE),
        re.compile(r"\bdownside\b", re.IGNORECASE),
        re.compile(r"\bfragile\b", re.IGNORECASE),
        re.compile(r"\bconfidence\b", re.IGNORECASE),
        re.compile(r"\bhedge\b", re.IGNORECASE),
    )
    _EXPLANATION_PATTERNS = (
        re.compile(r"\bwhy\b", re.IGNORECASE),
        re.compile(r"\bexplain\b", re.IGNORECASE),
        re.compile(r"\bexplanation\b", re.IGNORECASE),
        re.compile(r"\bbreakdown\b", re.IGNORECASE),
        re.compile(r"\banaly[sz]e\b", re.IGNORECASE),
        re.compile(r"\bmatchup\b", re.IGNORECASE),
        re.compile(r"\breason\b", re.IGNORECASE),
    )

    @staticmethod
    def _preview_subject_from_question(question: str) -> str | None:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return None
        patterns = (
            re.compile(r"\bpreview(?: the)? (?P<subject>.+?) game(?: tonight)?\b", re.IGNORECASE),
            re.compile(r"\bpreview(?: the)? (?P<subject>.+?) tonight\b", re.IGNORECASE),
        )
        for pattern in patterns:
            match = pattern.search(normalized_question)
            if not match:
                continue
            subject = str(match.group("subject") or "").strip().strip(" .?!,;:\"")
            if subject.lower().startswith("the "):
                subject = subject[4:].strip()
            return subject or None
        return None

    @staticmethod
    def _player_subject_from_question(question: str) -> str | None:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return None
        for pattern in QueryRouter._PLAYER_ANALYSIS_PATTERNS:
            match = pattern.search(normalized_question)
            if not match:
                continue
            subject = str(match.group("subject") or "").strip().strip(" .?!,;:\"")
            if subject.lower().startswith(("the ", "a ", "an ")):
                subject = re.sub(r"^(?:the|a|an)\s+", "", subject, flags=re.IGNORECASE).strip()
            return subject or None
        return None

    @staticmethod
    def _bet_subject_from_question(question: str) -> str | None:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return None
        for pattern in QueryRouter._BET_EVALUATION_PATTERNS:
            match = pattern.search(normalized_question)
            if not match:
                continue
            subject = str(match.group("subject") or "").strip().strip(" .?!,;:\"")
            if subject.lower().startswith(("the ", "a ", "an ")):
                subject = re.sub(r"^(?:the|a|an)\s+", "", subject, flags=re.IGNORECASE).strip()
            return subject or None
        return None

    def classify_query(self, question: str) -> str:
        normalized_question = str(question or "").strip()
        if self._matches(self._BET_EVALUATION_PATTERNS, normalized_question):
            return "bet_evaluation"
        if self._matches(self._PLAYER_ANALYSIS_PATTERNS, normalized_question):
            return "player_analysis"
        if self._matches(self._PREVIEW_PATTERNS, normalized_question):
            return "game_preview"
        if self._matches(self._LIVE_PATTERNS, normalized_question):
            return "live_analysis"
        if self._matches(self._COMPARISON_PATTERNS, normalized_question):
            return "comparison"
        if self._matches(self._TREND_PATTERNS, normalized_question):
            return "trend_analysis"
        if self._matches(self._RISK_PATTERNS, normalized_question):
            return "risk_evaluation"
        if self._matches(self._EXPLANATION_PATTERNS, normalized_question):
            return "explanation"
        return "explanation"

    def route_question(self, question: str) -> QueryRoute:
        normalized_question = str(question or "").strip()
        query_type = self.classify_query(normalized_question)
        pipeline_mode = {
            "bet_evaluation": "pregame",
            "player_analysis": "pregame",
            "game_preview": "pregame",
            "live_analysis": "live",
            "comparison": "comparison",
            "trend_analysis": "trend",
            "risk_evaluation": "explanation",
            "explanation": "explanation",
        }.get(query_type, "explanation")
        bet_subject = self._bet_subject_from_question(normalized_question) if query_type == "bet_evaluation" else None
        player_subject = self._player_subject_from_question(normalized_question) if query_type == "player_analysis" else None
        preview_subject = self._preview_subject_from_question(normalized_question) if query_type == "game_preview" else None
        return QueryRoute(question=normalized_question, query_type=query_type, pipeline_mode=pipeline_mode, preview_subject=preview_subject, player_subject=player_subject, bet_subject=bet_subject)

    def route_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        routed_payload = dict(payload or {})
        question = str(routed_payload.get("question") or "").strip()
        route = self.route_question(question)
        routed_payload["question"] = route.question
        routed_payload["mode"] = route.pipeline_mode
        routed_payload["query_type"] = route.query_type
        if route.preview_subject:
            routed_payload["preview_subject"] = route.preview_subject
        if route.player_subject:
            routed_payload["player_subject"] = route.player_subject
        if route.bet_subject:
            routed_payload["bet_subject"] = route.bet_subject
        if route.query_type in {"game_preview", "player_analysis", "bet_evaluation"}:
            routed_payload["include_games"] = True
            routed_payload["include_props"] = True
        return routed_payload

    def route_request(self, request_or_payload: Any) -> dict[str, Any]:
        payload = self._payload_from_request(request_or_payload)
        return self.route_payload(payload)

    def _payload_from_request(self, request_or_payload: Any) -> dict[str, Any]:
        if isinstance(request_or_payload, Mapping):
            return dict(request_or_payload)
        payload = getattr(request_or_payload, "get_json", None)
        if callable(payload):
            parsed = payload(silent=True)
            if isinstance(parsed, dict):
                return dict(parsed)
        form_payload = getattr(request_or_payload, "form", None)
        if form_payload is not None:
            try:
                return dict(form_payload)
            except Exception:
                pass
        return {}

    @staticmethod
    def _matches(patterns: tuple[re.Pattern[str], ...], question: str) -> bool:
        return any(pattern.search(question) for pattern in patterns)
