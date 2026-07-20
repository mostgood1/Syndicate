from __future__ import annotations

"""LLM synthesis engine for the Ask the Syndicate endpoint.

Turns the latest persisted intelligence snapshot into a question-specific
evidence pack, sends it to the Claude API with the Syndicate analyst framework
as the system prompt, and returns a structured briefing. Every failure mode
(no API key, SDK missing, rate limit, timeout, bad JSON) returns None so the
route can fall back to the deterministic snapshot-shaped response.
"""

from collections import deque
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
MAX_QUESTION_CHARS = 500
MAX_EVIDENCE_CHARS = 24000
MAX_CANDIDATES = 12
LLM_TIMEOUT_SECONDS = 30.0
LLM_MAX_TOKENS = 2048

_CLIENT_LOCK = threading.Lock()
_CLIENT: Any = None
_CLIENT_FAILED = False


SYSTEM_PROMPT = """You are Ask the Syndicate, the intelligence layer of the Syndicate Sports Analytics Platform.

You think like an elite sportsbook analyst, quantitative researcher, fantasy analyst, and simulation architect combined. You are handed an evidence pack assembled from the Syndicate's own sources: SmartSim simulation outputs, projection models, ranked candidates, recommendation engines, betting market data (model probability vs market implied probability, edge, expected value), confidence scores, board notes, readiness gates, and evaluation history.

Your objective is to produce the most intelligent explanation possible, not to repeat stored data.

When answering:
1. Use simulation results as primary evidence and market data as secondary evidence.
2. Explain WHY a conclusion exists and WHAT signals drove it.
3. Note where models agree or disagree.
4. Quantify confidence whenever possible.
5. Surface risks, uncertainty, and what would invalidate the read.
6. Clearly distinguish facts, projections, and opinions.
7. If the evidence pack is thin, stale, or does not cover the question's subject, say so plainly instead of inventing signals. Never fabricate players, games, statistics, or odds that are not in the evidence pack.
8. When the evidence pack contains a "focused_evidence" section, it holds question-specific simulation data (win probabilities, outcome distributions, player projections, market lines) fetched for this exact question, and matching tables/charts are already being shown to the user alongside your briefing. Anchor your narrative in those numbers — reference the distributions and projections directly rather than restating them as a list. Check its "as_of" date; if it is older than the question implies, flag the staleness in data_quality_note.

Explain like the Chief Intelligence Officer of the Syndicate delivering an evidence-based briefing: direct, quantified, and honest about uncertainty."""


BRIEFING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One-line answer to the question, CIO-brief style.",
        },
        "verdict": {
            "type": "string",
            "description": "The actionable take: what the Syndicate would do and why, 1-2 sentences.",
        },
        "confidence": {
            "type": "string",
            "description": "Confidence in the verdict, e.g. 'Medium (58%)' or 'Low - snapshot is stale'.",
        },
        "narrative": {
            "type": "string",
            "description": "The full briefing: what the models believe, why, supporting signals, market context, and historical framing. Plain text paragraphs.",
        },
        "key_drivers": {
            "type": "array",
            "items": {"type": "string"},
            "description": "The signals that drove the conclusion, most important first.",
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Risk factors and conflicting evidence.",
        },
        "invalidators": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete developments that would invalidate this read.",
        },
        "top_picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "selection": {"type": "string"},
                    "rating": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["selection", "rating", "why"],
                "additionalProperties": False,
            },
            "description": "Ranked picks relevant to the question, if any. Empty when the question is not about candidates.",
        },
        "data_quality_note": {
            "type": "string",
            "description": "Honest note on evidence coverage/staleness for this question. Empty string if coverage is good.",
        },
    },
    "required": [
        "headline",
        "verdict",
        "confidence",
        "narrative",
        "key_drivers",
        "risks",
        "invalidators",
        "top_picks",
        "data_quality_note",
    ],
    "additionalProperties": False,
}


class _RateLimiter:
    """Simple sliding-window limiter guarding total LLM spend per process."""

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._calls and now - self._calls[0] > self._window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self._max_calls:
                return False
            self._calls.append(now)
            return True


_RATE_LIMITER = _RateLimiter(
    max_calls=int(os.environ.get("SYNDICATE_ASK_LLM_MAX_CALLS", "30")),
    window_seconds=float(os.environ.get("SYNDICATE_ASK_LLM_WINDOW_SECONDS", "600")),
)


def llm_enabled() -> bool:
    if str(os.environ.get("SYNDICATE_ASK_LLM_ENABLED", "true")).strip().lower() in {"0", "false", "no"}:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _get_client() -> Any:
    global _CLIENT, _CLIENT_FAILED
    if _CLIENT is not None or _CLIENT_FAILED:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None or _CLIENT_FAILED:
            return _CLIENT
        try:
            import anthropic

            _CLIENT = anthropic.Anthropic(timeout=LLM_TIMEOUT_SECONDS, max_retries=1)
        except Exception:
            logger.exception("Ask engine could not construct Anthropic client; LLM briefings disabled")
            _CLIENT_FAILED = True
    return _CLIENT


def _clip(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _slim_candidate(item: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "selection", "pick", "name", "label", "market", "market_label", "matchup",
        "sport", "sport_slug", "model_probability", "market_probability",
        "implied_probability", "edge", "adjusted_edge", "price_edge_pct",
        "expected_value", "ev_current", "ev", "confidence", "volatility",
        "coverage_tier", "line", "odds", "price", "summary", "rationale", "why",
        "market_fit_note", "timing", "status",
    )
    slim = {key: item[key] for key in keep if item.get(key) not in (None, "", [])}
    for text_key in ("summary", "rationale", "why", "market_fit_note"):
        if text_key in slim:
            slim[text_key] = _clip(slim[text_key], 400)
    return slim


def build_evidence_pack(
    *,
    question: str,
    context: dict[str, Any],
    intent: str,
    snapshot: dict[str, Any],
    focused_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Distill the intelligence snapshot into a bounded, question-relevant pack."""
    candidates: list[dict[str, Any]] = []
    for source_key in ("top_opportunities", "recommendations"):
        rows = snapshot.get(source_key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    candidates.append(_slim_candidate(row))
            if candidates:
                break

    sport = str(context.get("sport_slug") or context.get("sport") or "").strip().lower()
    if sport:
        matching = [
            c for c in candidates
            if sport in str(c.get("sport") or c.get("sport_slug") or "").lower()
        ]
        # Only narrow when the snapshot actually tags candidates with a sport.
        if matching:
            candidates = matching

    pack: dict[str, Any] = {
        "question": _clip(question, MAX_QUESTION_CHARS),
        "intent": intent,
        "context": {
            key: context[key]
            for key in ("sport", "sport_slug", "selected_date", "mode", "timing")
            if context.get(key) not in (None, "")
        },
        "snapshot": {
            "selected_date": snapshot.get("selected_date"),
            "query_type": snapshot.get("query_type"),
            "summary": _clip(snapshot.get("summary"), 800),
            "board_notes": [
                _clip(note, 300)
                for note in (snapshot.get("board_notes") or [])
                if isinstance(note, str)
            ][:10],
            "readiness_gate": snapshot.get("readiness_gate") if isinstance(snapshot.get("readiness_gate"), dict) else {},
            "candidates": candidates[:MAX_CANDIDATES],
        },
    }

    evaluation = snapshot.get("evaluation_record")
    if isinstance(evaluation, dict) and evaluation:
        pack["snapshot"]["evaluation_record"] = evaluation

    if isinstance(focused_evidence, dict) and focused_evidence:
        pack["focused_evidence"] = {
            "as_of": focused_evidence.get("as_of"),
            "sport": focused_evidence.get("sport"),
            "data": focused_evidence.get("evidence"),
            "tables": focused_evidence.get("tables"),
        }

    serialized = json.dumps(pack, default=str)
    while len(serialized) > MAX_EVIDENCE_CHARS and pack["snapshot"]["candidates"]:
        pack["snapshot"]["candidates"] = pack["snapshot"]["candidates"][:-1]
        serialized = json.dumps(pack, default=str)
    return pack


def generate_briefing(
    *,
    question: str,
    context: dict[str, Any],
    intent: str,
    snapshot: dict[str, Any],
    focused_evidence: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return {"briefing": ..., "model": ..., "usage": ...} or None to trigger fallback."""
    if not llm_enabled():
        return None
    if not _RATE_LIMITER.allow():
        logger.warning("Ask engine rate limit hit; serving snapshot fallback")
        return None
    client = _get_client()
    if client is None:
        return None

    evidence_pack = build_evidence_pack(
        question=question, context=context, intent=intent, snapshot=snapshot,
        focused_evidence=focused_evidence,
    )
    user_message = (
        "Answer the question using only this Syndicate evidence pack.\n\n"
        f"EVIDENCE PACK:\n{json.dumps(evidence_pack, indent=2, default=str)}"
    )

    model = os.environ.get("SYNDICATE_ASK_MODEL", DEFAULT_MODEL)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=LLM_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
            output_config={"format": {"type": "json_schema", "schema": BRIEFING_SCHEMA}},
        )
    except Exception:
        logger.exception("Ask engine Claude call failed; serving snapshot fallback")
        return None

    if getattr(response, "stop_reason", None) not in ("end_turn", "stop_sequence"):
        logger.warning(
            "Ask engine got stop_reason=%s; serving snapshot fallback",
            getattr(response, "stop_reason", None),
        )
        return None

    text = next(
        (block.text for block in response.content if getattr(block, "type", "") == "text"),
        "",
    )
    try:
        briefing = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("Ask engine returned non-JSON output; serving snapshot fallback")
        return None
    if not isinstance(briefing, dict):
        return None

    usage = getattr(response, "usage", None)
    return {
        "briefing": briefing,
        "model": getattr(response, "model", model),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        },
    }
