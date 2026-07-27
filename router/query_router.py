from __future__ import annotations

from datetime import date
from datetime import timedelta
from dataclasses import dataclass
from typing import Any, Mapping
import re

from syndicate.features.shared.timezone import central_today_iso


@dataclass(frozen=True)
class QueryRoute:
    question: str
    query_type: str
    pipeline_mode: str
    selected_date: str | None = None
    preview_subject: str | None = None
    player_subject: str | None = None


class QueryRouter:
    _PLAYER_ANALYSIS_PATTERNS = (
        re.compile(r"\banaly[sz]e\s+(?P<subject>.+?)(?:\s+(?:tonight|today|right now)\b|$)", re.IGNORECASE),
        re.compile(r"\bbreak down\s+(?P<subject>.+?)(?:\s+(?:tonight|today|right now)\b|$)", re.IGNORECASE),
        re.compile(r"\bhow does\s+(?P<subject>.+?)\s+look(?:\s+(?:tonight|today|right now))?\b", re.IGNORECASE),
        re.compile(r"\bhow is\s+(?P<subject>.+?)\s+looking(?:\s+(?:tonight|today|right now))?\b", re.IGNORECASE),
        re.compile(r"\bbest\s+(?P<subject>.+?\btargets?)(?:\s+(?:tonight|today|right now)\b|$)", re.IGNORECASE),
        re.compile(r"\b(?:best|top)\s+(?:strikeout|strikeouts|k's?|home run|home runs|hr|hit|hits|rbi|total bases?|saves?|shots?|points?|rebounds?|assists?).*", re.IGNORECASE),
        re.compile(r"\b(?:strikeout|strikeouts|k's?|home run|home runs|hr|hit|hits|rbi|total bases?|saves?|shots?|points?|rebounds?|assists?)\s+props?\b", re.IGNORECASE),
    )
    _PREVIEW_PATTERNS = (
        re.compile(r"\bpreview\b.*\bgame\b", re.IGNORECASE),
        re.compile(r"\bgame preview\b", re.IGNORECASE),
        re.compile(r"\bwhat should i know about\b.*\bgame\b", re.IGNORECASE),
        re.compile(r"\bwhat do you think (?:of|about)\s+(?P<subject>.+?)(?:\s+(?:tonight|today|right now)\b|\s+game\b|$)", re.IGNORECASE),
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
            re.compile(r"\bwhat do you think (?:of|about)\s+(?P<subject>.+?)(?:\s+(?:tonight|today|right now)\b|\s+game\b|$)", re.IGNORECASE),
            re.compile(r"\bpreview(?: the)? (?P<subject>.+?) game(?: tonight)?\b", re.IGNORECASE),
            re.compile(r"\bpreview(?: the)? (?P<subject>.+?) tonight\b", re.IGNORECASE),
            re.compile(r"\bwhat should i know about(?: the)? (?P<subject>.+?) game(?: tonight| today)?\b", re.IGNORECASE),
            re.compile(r"\bwhat should i know about(?: the)? (?P<subject>.+?)\b(?: game)?(?: tonight| today)?\b", re.IGNORECASE),
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
        prop_patterns = (
            re.compile(r"\bbest\s+(?P<subject>.+?\btargets?)(?:\s+(?:tonight|today|right now)\b|$)", re.IGNORECASE),
            re.compile(r"\b(?:strikeout|strikeouts|k's?|home run|home runs|hr|hit|hits|rbi|total bases?|saves?|shots?|points?|rebounds?|assists?)\s+props?\b", re.IGNORECASE),
        )
        for pattern in prop_patterns:
            match = pattern.search(normalized_question)
            if not match:
                continue
            subject = str(match.groupdict().get("subject") or match.group(0) or "").strip().strip(" .?!,;:\"")
            if subject.lower().startswith(("the ", "a ", "an ")):
                subject = re.sub(r"^(?:the|a|an)\s+", "", subject, flags=re.IGNORECASE).strip()
            return subject or None
        for pattern in QueryRouter._PLAYER_ANALYSIS_PATTERNS:
            match = pattern.search(normalized_question)
            if not match:
                continue
            subject = str(match.groupdict().get("subject") or match.group(0) or "").strip().strip(" .?!,;:\"")
            if subject.lower().startswith(("the ", "a ", "an ")):
                subject = re.sub(r"^(?:the|a|an)\s+", "", subject, flags=re.IGNORECASE).strip()
            return subject or None
        return None

    @staticmethod
    def _resolve_selected_date(question: str, selected_date: str | None = None) -> str | None:
        explicit_date = str(selected_date or "").strip()
        if explicit_date:
            return explicit_date
        normalized_question = f" {str(question or '').strip().lower()} "
        if not normalized_question.strip():
            return None
        if "tomorrow" in normalized_question:
            return (date.fromisoformat(central_today_iso()) + timedelta(days=1)).isoformat()
        if "today" in normalized_question or "tonight" in normalized_question:
            return central_today_iso()
        return None

    def classify_query(self, question: str) -> str:
        normalized_question = str(question or "").strip()
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
            "player_analysis": "pregame",
            "game_preview": "pregame",
            "live_analysis": "live",
            "comparison": "comparison",
            "trend_analysis": "trend",
            "risk_evaluation": "explanation",
            "explanation": "explanation",
        }.get(query_type, "explanation")
        selected_date = self._resolve_selected_date(normalized_question)
        player_subject = self._player_subject_from_question(normalized_question) if query_type == "player_analysis" else None
        preview_subject = self._preview_subject_from_question(normalized_question) if query_type == "game_preview" else None
        return QueryRoute(question=normalized_question, query_type=query_type, pipeline_mode=pipeline_mode, selected_date=selected_date, preview_subject=preview_subject, player_subject=player_subject)

    def route_payload(self, payload: Mapping[str, Any] | None) -> dict[str, Any]:
        routed_payload = dict(payload or {})
        question = str(routed_payload.get("question") or "").strip()
        explicit_date = str(routed_payload.get("selected_date") or routed_payload.get("date") or "").strip()
        explicit_mode = str(routed_payload.get("mode") or "").strip().lower()
        route = self.route_question(question)
        routed_payload["question"] = route.question
        routed_payload["query_type"] = route.query_type
        # mode_inferred (#74): once mode is stamped here, downstream cannot
        # tell a caller-chosen mode from a routed guess -- and _query_preferences
        # treats mode as an instruction, so a guessed "pregame" silently
        # overrides intent the question itself expresses (e.g. filtering the
        # live legs out of an explicitly requested parlay). The flag lets
        # consumers keep inferred modes advisory.
        if route.query_type in {"game_preview", "player_analysis", "comparison"} or not explicit_mode:
            routed_payload["mode"] = route.pipeline_mode
            routed_payload["mode_inferred"] = True
        else:
            routed_payload["mode"] = explicit_mode
            routed_payload["mode_inferred"] = False
        if not explicit_date and route.selected_date:
            routed_payload["selected_date"] = route.selected_date
            routed_payload["date"] = route.selected_date
        if route.preview_subject:
            routed_payload["preview_subject"] = route.preview_subject
        if route.player_subject:
            routed_payload["player_subject"] = route.player_subject
        if route.query_type in {"game_preview", "player_analysis", "comparison"}:
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
