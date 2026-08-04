from __future__ import annotations

import re
from typing import Any

from pipeline.intelligence_models import IntelligenceResult

from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.features.intelligence_board import build_intelligence_board_contract


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    if isinstance(result, IntelligenceResult):
        return result.to_dict()
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, dict):
            return payload
    return {}


def _result_value(result: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(result, IntelligenceResult) and hasattr(result, field_name):
        value = getattr(result, field_name)
        return default if value is None else value
    payload = _result_payload(result)
    return payload.get(field_name, default)


def _items_to_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if hasattr(item, "to_dict"):
            items.append(dict(item.to_dict()))
        elif isinstance(item, dict):
            items.append(dict(item))
    return items


def _evidence_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, dict):
            return dict(payload)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except Exception:
        return None


def _to_pct(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if numeric <= 1.0:
        return round(numeric * 100.0, 2)
    return round(numeric, 2)


def _first_recommendation(result: Any) -> dict[str, Any]:
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    if recommendations:
        return recommendations[0]
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))
    table = _mapping_or_empty(analysis_views.get("table"))
    rows = table.get("rows") if isinstance(table.get("rows"), list) else []
    if rows:
        first_row = rows[0]
        if isinstance(first_row, dict):
            return dict(first_row)
    return {}


def _analysis_rows(result: Any) -> list[dict[str, Any]]:
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))
    table = _mapping_or_empty(analysis_views.get("table"))
    return _items_to_dicts(table.get("rows"))


def _explanation_payload(result: Any) -> dict[str, Any]:
    analysis_brief = _result_value(result, "analysis_brief", None)
    supporting_evidence = _result_value(result, "supporting_evidence", None)
    return {
        "summary": _result_value(result, "summary", None),
        "analysis_brief": _evidence_to_dict(analysis_brief),
        "supporting_evidence": _evidence_to_dict(supporting_evidence),
        "reasoning_steps": _items_to_dicts(_result_value(result, "reasoning_steps", ())),
        "board_notes": list(_result_value(result, "board_notes", ())),
        "readiness_gate": _mapping_or_empty(_result_value(result, "readiness_gate", {})),
    }


def _supporting_evidence_sections(result: Any, structured_response: dict[str, Any]) -> list[dict[str, Any]]:
    sections = structured_response.get("supporting_evidence")
    if isinstance(sections, list) and sections:
        return _items_to_dicts(sections)

    explanation = _explanation_payload(result)
    fallback_sections: list[dict[str, Any]] = []

    analysis_brief = explanation.get("analysis_brief")
    if analysis_brief:
        fallback_sections.append(dict(analysis_brief))

    supporting_evidence = explanation.get("supporting_evidence")
    if supporting_evidence:
        fallback_sections.append(dict(supporting_evidence))

    if _items_to_dicts(_result_value(result, "recommendations", ())):
        fallback_sections.append({"kind": "bundle", "title": "Recommendation evidence"})

    return fallback_sections


_MAX_SUPPORTING_POINTS = 6


def _evidence_bullets(evidence: dict[str, Any]) -> list[str]:
    """Flatten an Evidence-shaped dict (title/summary/detail/items[]/sections[])
    into short strings. Falls back to the bare title only when nothing more
    specific is present -- title-only evidence (e.g. {"kind": "bundle",
    "title": "Brief"}) is common (see pipeline/evidence_builder.py's own
    nested-container extraction, which treats title the same way).
    """
    bullets: list[str] = []
    for key in ("summary", "detail"):
        text = str(evidence.get(key) or "").strip()
        if text:
            bullets.append(text)
    items = evidence.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                text = str(item.get("note") or item.get("label") or item.get("title") or item.get("summary") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                bullets.append(text)
    sections = evidence.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict):
                text = str(section.get("title") or section.get("summary") or section.get("label") or "").strip()
                if text:
                    bullets.append(text)
    if not bullets:
        title = str(evidence.get("title") or "").strip()
        if title:
            bullets.append(title)
    return bullets


def _supporting_points(explanation: dict[str, Any]) -> list[str]:
    """Flatten reasoning_steps/analysis_brief/supporting_evidence/board_notes into
    plain-text bullets for the bet-analysis "supporting detail" chip row.

    reasoning_steps is structurally empty for almost every Ask the Syndicate
    query (gated behind enable_reasoning_steps=False and a compound-question
    heuristic single-player questions never satisfy), but analysis_brief /
    supporting_evidence / board_notes are populated on real snapshots -- this
    is what lets the chip row show real content instead of a fixed
    "No supporting steps returned" placeholder.
    """
    points: list[str] = []
    steps = explanation.get("reasoning_steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                text = str(step.get("note") or step.get("reasoning") or step.get("label") or step.get("title") or "").strip()
            else:
                text = str(step or "").strip()
            if text:
                points.append(text)

    analysis_brief = explanation.get("analysis_brief")
    if isinstance(analysis_brief, dict):
        points.extend(_evidence_bullets(analysis_brief))

    supporting_evidence = explanation.get("supporting_evidence")
    if isinstance(supporting_evidence, dict):
        points.extend(_evidence_bullets(supporting_evidence))

    board_notes = explanation.get("board_notes")
    if isinstance(board_notes, list):
        points.extend(str(note).strip() for note in board_notes if str(note or "").strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for point in points:
        if point not in seen:
            seen.add(point)
            deduped.append(point)
    return deduped[:_MAX_SUPPORTING_POINTS]


def _bet_analysis_schema(result: Any, *, question: str = "", relevance_matched: bool | None = None) -> dict[str, Any]:
    explanation = _explanation_payload(result)

    if relevance_matched is False:
        # The question named something specific (a player/team/market) but
        # nothing in today's actual board recommendations mentions it. Don't
        # show the board's unrelated top pick as if it were the answer --
        # a bettor skimming "Los Angeles Dodgers steam move — 100% model
        # probability" right under a question about a specific player could
        # easily read it as being about that player (reported live,
        # 2026-07-31: annotating the pick with a caveat note still wasn't
        # enough -- it needs to not be presented as the answer at all).
        # See _reorder_by_relevance.
        note = f"No board recommendation matches “{question.strip()}” specifically — nothing to show for this question."
        return {
            "schema_type": "bet_analysis",
            "selection": None,
            "model_probability": None,
            "market_probability": None,
            "edge": None,
            "EV": None,
            "confidence": None,
            "recommendation": None,
            "relevance_matched": False,
            "explanation": {
                "summary": note,
                "analysis_brief": {},
                "supporting_evidence": {},
                "reasoning_steps": [],
                "supporting_points": [],
                "board_notes": explanation.get("board_notes", []),
                "readiness_gate": explanation.get("readiness_gate", {}),
                "top_candidate": {},
            },
        }

    top = _first_recommendation(result)
    selection = top.get("selection") or top.get("pick") or top.get("name") or top.get("label")
    return {
        "schema_type": "bet_analysis",
        "selection": selection,
        "model_probability": _to_pct(top.get("model_probability") or top.get("confidence")),
        "market_probability": _to_pct(top.get("market_probability") or top.get("implied_probability")),
        "edge": _to_float(top.get("adjusted_edge") or top.get("edge") or top.get("price_edge_pct")),
        "EV": _to_float(top.get("expected_value") or top.get("ev_current") or top.get("ev")),
        "confidence": _to_pct(top.get("confidence") or top.get("model_probability")),
        "recommendation": top.get("summary") or top.get("rationale") or top.get("writeup") or top.get("why") or explanation.get("summary"),
        "relevance_matched": relevance_matched,
        "explanation": {
            "summary": explanation.get("summary"),
            "analysis_brief": explanation.get("analysis_brief", {}),
            "supporting_evidence": explanation.get("supporting_evidence", {}),
            "reasoning_steps": explanation.get("reasoning_steps", []),
            "supporting_points": _supporting_points(explanation),
            "board_notes": explanation.get("board_notes", []),
            "readiness_gate": explanation.get("readiness_gate", {}),
            "top_candidate": top,
        },
    }


def _teams_from_question(question: str, result: Any) -> list[str]:
    matchup_text = str(_first_recommendation(result).get("matchup") or question or "").strip()
    if " versus " in matchup_text.lower():
        matchup_text = matchup_text.replace("versus", "vs")
    if " vs " in matchup_text.lower():
        parts = matchup_text.split("vs", 1)
        teams = [part.strip(" .,!?") for part in parts if part.strip(" .,!?")]
        if len(teams) >= 2:
            return teams[:2]
    if " at " in matchup_text.lower():
        parts = matchup_text.split(" at ", 1)
        teams = [part.strip(" .,!?") for part in parts if part.strip(" .,!?")]
        if len(teams) >= 2:
            return teams[:2]
    parsed_request = _mapping_or_empty(_result_value(result, "parsed_request", {}))
    requested_subjects = parsed_request.get("requested_subjects") if isinstance(parsed_request.get("requested_subjects"), list) else []
    teams = [str(item).strip() for item in requested_subjects if str(item).strip()]
    return teams[:2]


def _matchup_analysis_schema(question: str, result: Any, *, relevance_matched: bool | None = None) -> dict[str, Any]:
    if relevance_matched is False:
        # Same bug class as _bet_analysis_schema, same fix: the question
        # named something specific but nothing in today's recommendations
        # mentions it. _first_recommendation(result) below would otherwise
        # feed an unrelated pick's matchup/win-probability/edges straight
        # into this schema as if they answered the question.
        note = f"No board recommendation matches “{question.strip()}” specifically — nothing to show for this question."
        return {
            "schema_type": "matchup_analysis",
            "teams": [],
            "win_probability": None,
            "key_edges": [],
            "simulation_summary": {"summary": note, "top_candidate": {}, "analysis_focus": None, "rows_considered": 0},
            "hidden_factors": [],
            "market_insight": {"summary": note, "analysis_views": {}, "supporting_evidence": {}},
            "relevance_matched": False,
            "explanation": _explanation_payload(result),
        }

    top = _first_recommendation(result)
    rows = _analysis_rows(result)
    explanation = _explanation_payload(result)
    analysis_views = _mapping_or_empty(_result_value(result, "analysis_views", {}))

    key_edges: list[dict[str, Any]] = []
    for row in rows[:3]:
        key_edges.append(
            {
                "selection": row.get("selection") or row.get("pick") or row.get("name") or row.get("label"),
                "model_probability": _to_pct(row.get("model_probability") or row.get("confidence")),
                "market_probability": _to_pct(row.get("market_probability") or row.get("implied_probability")),
                "edge": _to_float(row.get("adjusted_edge") or row.get("edge") or row.get("price_edge_pct")),
                "EV": _to_float(row.get("expected_value") or row.get("ev_current") or row.get("ev")),
                "confidence": _to_pct(row.get("confidence") or row.get("model_probability")),
                "recommendation": row.get("summary") or row.get("rationale") or row.get("why"),
            }
        )

    hidden_factors = [
        {"factor": note}
        for note in explanation.get("board_notes", [])
        if note
    ]
    if analysis_views.get("focus"):
        hidden_factors.append({"factor": f"analysis_focus:{analysis_views.get('focus')}"})

    return {
        "schema_type": "matchup_analysis",
        "teams": _teams_from_question(question, result),
        "win_probability": _to_pct(top.get("model_probability") or top.get("confidence")),
        "key_edges": key_edges,
        "simulation_summary": {
            "summary": explanation.get("summary"),
            "top_candidate": top,
            "analysis_focus": analysis_views.get("focus"),
            "rows_considered": len(rows),
        },
        "hidden_factors": hidden_factors,
        "market_insight": {
            "summary": top.get("market_fit_note") or top.get("summary") or top.get("rationale") or explanation.get("summary"),
            "analysis_views": analysis_views,
            "supporting_evidence": explanation.get("supporting_evidence", {}),
        },
        "relevance_matched": relevance_matched,
        "explanation": explanation,
    }


# A board-summary question with no specific subject to match. "Summarize
# today's board" is asking for exactly the opportunities the summary shows,
# so the not-matched note would contradict a correct answer. Deliberately
# narrow: anything naming a player, team or single market still counts as
# subject-bearing and keeps the note.
_GENERAL_BOARD_QUESTION_PATTERNS = (
    re.compile(r"\bsummar(?:ise|ize|y)\b", re.IGNORECASE),
    re.compile(r"\b(?:best|top)\s+(?:opportunit(?:y|ies)|plays?|bets?|edges?|picks?)\b", re.IGNORECASE),
    re.compile(r"\bacross the board\b", re.IGNORECASE),
    re.compile(r"\bwhat to watch\b", re.IGNORECASE),
    re.compile(r"\b(?:the|today'?s)\s+board\b", re.IGNORECASE),
    re.compile(r"\bwhat should i (?:bet|play|back)\b", re.IGNORECASE),
    re.compile(r"\b(?:overview|rundown|slate)\b", re.IGNORECASE),
    re.compile(r"\b(?:what'?s|anything|any)\s+(?:good|worth|interesting)\b", re.IGNORECASE),
)


def _board_summary_sentence(rows: Any) -> str:
    """A factual one-liner describing the opportunities actually returned.

    Everything here is read off the rows -- count, sports covered, and the
    best edge present. Nothing is inferred or narrated, so this stays true
    whether or not the optional LLM briefing is enabled.
    """
    items = [row for row in (rows or []) if isinstance(row, dict)]
    if not items:
        return "No opportunities are on the board right now."
    sports = []
    for row in items:
        label = str(row.get("sport") or row.get("sport_slug") or "").strip().upper()
        if label and label not in sports:
            sports.append(label)
    best_edge = None
    for row in items:
        edge = _to_float(row.get("edge"))
        if edge is not None and (best_edge is None or edge > best_edge):
            best_edge = edge
    parts = [f"Showing the top {len(items)} opportunit{'y' if len(items) == 1 else 'ies'} on today's board"]
    if sports:
        shown = ", ".join(sports[:4])
        parts.append(f"across {shown}" if len(sports) > 1 else f"in {shown}")
    sentence = " ".join(parts) + "."
    if best_edge is not None:
        sentence += f" Best edge {best_edge * 100:.1f}%."
    return sentence


def _is_general_board_question(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        # No question at all -> nothing to claim a mismatch against.
        return True
    return any(pattern.search(text) for pattern in _GENERAL_BOARD_QUESTION_PATTERNS)


def _market_summary_rank_key(item: dict[str, Any]) -> tuple[float, float]:
    """Rank by the board's own ranker output, falling back to raw edge.

    `adjusted_score` is what rank_recommendations produces (reliability,
    ROI, calibration, CLV and policy weights folded in) and is the same key
    the main board orders by, so using it keeps Ask and the board telling
    the same story. Edge is the tiebreak and the fallback for any payload
    that predates the ranker being wired onto this path.
    """
    score = _to_float(item.get("adjusted_score"))
    edge = _to_float(item.get("adjusted_edge") or item.get("edge") or item.get("price_edge_pct"))
    # -inf, not 0.0: an unscored row must sort BELOW a genuinely negative
    # one rather than landing mid-pack as if it were neutral.
    return (score if score is not None else float("-inf"), edge if edge is not None else float("-inf"))


def _market_summary_schema(result: Any, *, question: str = "", relevance_matched: bool | None = None) -> dict[str, Any]:
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    # Was `recommendations[:5]` with no sort -- an arbitrary slice of
    # whatever order the payload happened to arrive in. Confirmed live
    # 2026-08-03: the summary returned 4 negative-edge rows with the only
    # positive one (+16.9%) ranked LAST, under a header claiming "best
    # edge". "Top opportunities" has to actually be the top ones.
    ranked = sorted(recommendations, key=_market_summary_rank_key, reverse=True)
    top_opportunities: list[dict[str, Any]] = []
    for item in ranked[:5]:
        top_opportunities.append(
            {
                "selection": item.get("selection") or item.get("pick") or item.get("name") or item.get("label"),
                "market": item.get("market") or item.get("market_label") or item.get("market_key"),
                "model_probability": _to_pct(item.get("model_probability") or item.get("confidence")),
                "market_probability": _to_pct(item.get("market_probability") or item.get("implied_probability")),
                "edge": _to_float(item.get("adjusted_edge") or item.get("edge") or item.get("price_edge_pct")),
                "EV": _to_float(item.get("expected_value") or item.get("ev_current") or item.get("ev")),
                "confidence": _to_pct(item.get("confidence") or item.get("model_probability")),
                # Surfaced so the ordering is inspectable rather than
                # something a reader has to take on trust.
                "adjusted_score": _to_float(item.get("adjusted_score")),
                "recommendation": item.get("summary") or item.get("rationale") or item.get("writeup") or item.get("why"),
            }
        )

    explanation = _explanation_payload(result)
    summary_text = _result_value(result, "summary", None)
    if relevance_matched is False and not _is_general_board_question(question):
        # Unlike bet_analysis/matchup_analysis (a single framed "answer"),
        # a market summary is inherently a plural "here's today's board" --
        # less likely to be misread as being about the question's subject,
        # so the opportunities list stays. Still say plainly that none of
        # them are specifically about what was asked, rather than silently
        # implying they are.
        #
        # Suppressed for questions with no subject to match ("summarize
        # today's board"): there, the opportunities ARE what was asked for,
        # and leading with "No board opportunity matches ..." makes a
        # working answer read as a failure -- reported live 2026-08-03. The
        # guard still fires for subject-bearing questions ("how does Jokic
        # look tonight"), which is the case it was written for.
        note = f"No board opportunity matches “{question.strip()}” specifically — showing today's top opportunities instead."
        summary_text = f"{note} {summary_text}".strip() if summary_text else note
    if not summary_text:
        # The not-matched note used to be the only thing populating this
        # field, so suppressing it for general board questions left the
        # summary empty. Describe what is actually being shown instead,
        # entirely from the rows themselves -- no narration, no LLM, and
        # nothing asserted that the data does not support.
        summary_text = _board_summary_sentence(top_opportunities)
    return {
        "schema_type": "market_summary",
        "top_opportunities": top_opportunities,
        "relevance_matched": relevance_matched,
        "rationale_summary": {
            "summary": summary_text,
            "analysis_brief": explanation.get("analysis_brief", {}),
            "board_notes": explanation.get("board_notes", []),
            "supporting_evidence": explanation.get("supporting_evidence", {}),
        },
    }


# Ask is a pure consumer of the cached board snapshot -- recommendations
# there are ranked by score across the WHOLE board, unrelated to what any
# given question asked about. Without this, "How do the Brewers look
# against the Pirates?" would surface whatever's #1 board-wide (observed:
# an unrelated WNBA player prop) instead of anything about that game.
# Deliberately narrow: only reorders when a question word actually matches
# a recommendation field, so generic questions ("what's the best bet
# today") keep today's "top board pick" behavior unchanged.
_ASK_RELEVANCE_STOPWORDS = {
    "the", "how", "what", "who", "do", "does", "did", "you", "think", "of", "is", "are",
    "for", "with", "this", "that", "today", "tonight", "look", "looks", "looking",
    "will", "get", "and", "against", "vs", "versus", "in", "on", "at", "to", "a", "an",
    "about", "best", "top", "good", "any", "some", "there", "it", "its", "was", "were",
    # Generic betting/question vocabulary -- present in almost every question
    # regardless of subject, so it must not count as "names something
    # specific" (see _relevance_matched below: without this, "What do you
    # think of this spread?" leaves "spread" as the only word, which
    # doesn't match any recommendation and wrongly reads as "the question
    # named a subject that isn't on the board" instead of "generic
    # question, leave the board's top pick alone" -- confirmed live,
    # 2026-07-31).
    "spread", "spreads", "bet", "bets", "betting", "pick", "picks", "line", "lines",
    "odds", "moneyline", "total", "totals", "analysis", "game", "games", "match",
    "matchup", "over", "under", "player", "players", "team", "teams", "market",
    "markets", "edge", "edges", "prop", "props",
}


def _relevance_words(text: Any) -> set[str]:
    words = set(re.findall(r"[a-z0-9']+", str(text or "").lower()))
    return {word for word in words if len(word) >= 3 and word not in _ASK_RELEVANCE_STOPWORDS}


def _recommendation_relevance_score(item: dict[str, Any], words: set[str]) -> int:
    if not words:
        return 0
    text_fields = (
        item.get("selection"), item.get("pick"), item.get("name"), item.get("label"),
        item.get("matchup"), item.get("team"), item.get("market"), item.get("market_label"),
    )
    score = 0
    for field in text_fields:
        if not field:
            continue
        score += len(_relevance_words(field) & words)
    return score


def _reorder_by_relevance(items: list[dict[str, Any]], question: str) -> tuple[list[dict[str, Any]], bool | None]:
    """Returns (items, matched).

    matched is None when the question had no specific-subject words to
    check (generic question, e.g. "best bets today" -- leave board order
    alone, nothing to flag). False when the question named something
    specific but NOTHING in today's recommendations mentions it at all --
    the caller should say so rather than silently presenting an unrelated
    board pick as if it answered the question (confirmed live, 2026-07-31:
    "antony volpe bet analysis" silently returned an unrelated Dodgers
    steam move with no indication it wasn't about Volpe at all).
    """
    words = _relevance_words(question)
    if not words or not items:
        return items, None
    scored = [(item, _recommendation_relevance_score(item, words)) for item in items]
    if max(score for _, score in scored) <= 0:
        return items, False  # nothing in the snapshot names anything from the question -- leave as-is
    ranked = sorted(scored, key=lambda pair: pair[1], reverse=True)  # stable: ties keep board order
    return [item for item, _ in ranked], True


def build_syndicate_query_response(*, question: str, context: dict[str, Any], decision: RouteDecision, result: Any) -> dict[str, Any]:
    query_type = _result_value(result, "query_type", None) or decision.intent or "bet_analysis"
    pipeline_context = _mapping_or_empty(_result_value(result, "pipeline_context", {}))
    structured_response = _mapping_or_empty(_result_value(result, "structured_response", {}))
    routing_context = _mapping_or_empty(pipeline_context.get("routing_context")) or _mapping_or_empty(context)
    board_contract = build_intelligence_board_contract(_result_payload(result))
    daily_update = _mapping_or_empty(_result_value(result, "daily_update", {}))
    simulation_contract = _mapping_or_empty(daily_update.get("simulation_contract"))

    # Only the schema below needs the question-relevant ordering -- board_contract
    # above (a different rendering surface) and the metadata already extracted
    # keep using the original result, so nothing computed from it is lost by
    # the payload conversion this triggers (IntelligenceResult.to_dict() does
    # not serialize pipeline_context, for one).
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    relevance_matched: bool | None = None
    if recommendations:
        reordered, relevance_matched = _reorder_by_relevance(recommendations, question)
        if reordered is not recommendations:
            result = _result_payload(result)
            result["recommendations"] = reordered

    if decision.intent in {"matchup_analysis", "comparison"}:
        schema = _matchup_analysis_schema(question, result, relevance_matched=relevance_matched)
    elif decision.intent == "market_summary":
        schema = _market_summary_schema(result, question=question, relevance_matched=relevance_matched)
    else:
        schema = _bet_analysis_schema(result, question=question, relevance_matched=relevance_matched)

    return {
        "ok": True,
        "surface": "syndicate",
        "question": question,
        "context": dict(context),
        "routing_context": routing_context,
        "context_awareness": _mapping_or_empty(structured_response.get("context_awareness")),
        "supporting_evidence": _supporting_evidence_sections(result, structured_response),
        "evaluation_record": _mapping_or_empty(_result_value(result, "evaluation_record", {})),
        "evaluation_history": _mapping_or_empty(_result_value(result, "evaluation_history", {})),
        "intent": decision.intent,
        "routing": {
            "handler": decision.handler_name,
            "matched_terms": list(decision.matched_terms),
            "score": decision.score,
        },
        "query_type": query_type,
        "schema_type": schema.get("schema_type", decision.intent),
        "schema": schema,
        "structured_response": schema,
        "board_contract": board_contract,
        "daily_update": daily_update,
        "simulation_contract": simulation_contract,
        "engine": {
            "selected_date": _result_value(result, "selected_date", None),
            "query_type": _result_value(result, "query_type", None),
            "preferences": _mapping_or_empty(_result_value(result, "preferences", {})),
            "parsed_request": _mapping_or_empty(_result_value(result, "parsed_request", {})),
            "analysis_views": _mapping_or_empty(_result_value(result, "analysis_views", {})),
            "routing_context": routing_context,
            "context_awareness": _mapping_or_empty(structured_response.get("context_awareness")),
            "evaluation_record": _mapping_or_empty(_result_value(result, "evaluation_record", {})),
            "evaluation_history": _mapping_or_empty(_result_value(result, "evaluation_history", {})),
            "readiness_gate": _mapping_or_empty(_result_value(result, "readiness_gate", {})),
            "local_only": _result_value(result, "local_only", None),
            "board_contract": board_contract,
            "daily_update": daily_update,
            "simulation_contract": simulation_contract,
        },
    }