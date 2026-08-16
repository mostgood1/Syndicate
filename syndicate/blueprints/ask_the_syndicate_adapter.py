from __future__ import annotations

import math
import re
from datetime import datetime, timezone
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
    """Numeric, or None. **NaN and infinity are None, not numbers.**

    `float("nan")` survives every `is None` check, compares False against every
    threshold, and renders as the literal string "nan". Served on production
    2026-08-16 as `"draw nan (Indiana Fever @ Atlanta Dream)"` — a WNBA
    three-way row whose line was absent upstream and arrived here as NaN.

    Fixed at this choke point rather than at the label, because every caller
    inherits the same defect: a NaN edge renders "nan%", a NaN probability
    passes the `> 0` guards that are supposed to suppress it, and a NaN price
    formats as "+nan". One guard covers all of them.
    """
    try:
        if value is None or isinstance(value, bool):
            return None
        numeric = float(value)
    except Exception:
        return None
    return numeric if math.isfinite(numeric) else None


def _to_pct(value: Any) -> float | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    if numeric <= 1.0:
        return round(numeric * 100.0, 2)
    return round(numeric, 2)


# Found live 2026-08-04 verifying game-market picks (moneyline/ATS/totals):
# some of these candidates' "detail" is built from game.get("summary")
# (syndicate/blueprints/home.py's _append_game_bet_candidate), which is an
# internal placeholder value ("oddsapi_consensus market snapshot", confirmed
# by test_home.py) meaning "no real sim summary yet, just a market
# snapshot" -- not human-readable prose. _game_sim_vs_line_reasoning's own
# "Sim: {main}" half echoes the same placeholder when there's no real sim
# value either, producing the observed doubled string ("oddsapi_consensus
# market snapshot Sim: oddsapi_consensus market snapshot"). Player-prop
# candidates never hit this path (their detail is real generated prose),
# so this is scoped narrowly rather than touching home.py's shared
# candidate builder, which many other consumers (the board itself
# included) depend on.
#
# home.py's _game_bet_narrative (added 2026-08-04) is now the real,
# upstream fix for this -- it generates actual analysis prose for these
# candidates instead of leaving the placeholder in place. This filter
# stays as a safety net for any candidate that reaches Ask without going
# through that builder. "official pick(" also catches MLB cards.py's
# real-but-generic "{starter} vs {starter} | N official pick(s)" summary,
# not just the two internal sentinels.
_LOW_INFORMATION_PROSE_PHRASES = ("oddsapi_consensus market snapshot", "no game-bet summary available", "official pick(")


def _is_low_information_prose(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized:
        return True
    return any(phrase in normalized for phrase in _LOW_INFORMATION_PROSE_PHRASES) and len(normalized) < 120


def _candidate_prose(item: dict[str, Any]) -> str | None:
    """The same per-pick prose the main board already renders under each
    card (intelligence.html's client-side pickReasoning, same field
    priority) -- e.g. "The model lands on the over side in 54.5% of
    sims... Against SD, he has recorded a hit in 10 of 17 games."

    Reported live 2026-08-04: Ask the Syndicate never showed this prose
    for a real, correctly-matched pick, even though the exact same
    candidate object carries it and the board renders it right next to
    the same pick. Root cause: this schema's own text lookup only ever
    checked summary/rationale/writeup/why -- never "detail", which is
    where the real prose actually lives on a candidate. Not a missing
    generator, a missing field name.
    """
    for field in ("detail", "writeup", "reasoning", "summary", "rationale", "why", "basketball_summary"):
        value = str(item.get(field) or "").strip()
        if value and not _is_low_information_prose(value):
            return value
    return None


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
    # The snapshot's own computed_at, so the quote age advances with the
    # artifact instead of being frozen at build time. See `_bet_facts`.
    facts = _bet_facts(top, artifact_as_of=_result_as_of(result))
    sim = _sim_terms(top)

    # `selection` was `top.get("selection")`, which on a layer2-sourced
    # candidate is the bare player name. Reported live 2026-08-16: a question
    # about a specific prop was answered "Ryan Johnson" while the same dict
    # carried market="earned_runs", line=2.5, side="over". See `_bet_label`.
    selection = _bet_label(top) or top.get("selection") or top.get("pick") or top.get("name") or top.get("label")

    # **EDGE IS THE MODEL EDGE, IN PERCENT, ON BOTH SCHEMAS.**
    #
    # This read `adjusted_edge or edge or price_edge_pct`. On a layer2
    # candidate, `edge` is the **EV fraction**, not the model edge -- and
    # `_board_top_opportunities` publishes `model_edge_pct` under the same
    # field name. Measured on one pick at one instant, 2026-08-16:
    #
    #     briefing (market_summary)  edge 14.01   <- model_edge_pct, PERCENT
    #     per-pick (bet_analysis)    edge  0.0139 <- ev_pct/100, FRACTION
    #
    # Ask contradicted itself by a factor of ten on the same bet, and the two
    # schemas disagreed on the UNITS of a field with one name. `edge_pct` is
    # emitted alongside for readers that should not have to infer a scale from
    # a magnitude -- the same reason `_board_summary_sentence` needs it.
    edge_pct = _to_float(top.get("model_edge_pct"))
    if edge_pct is None:
        fraction = _to_float(top.get("adjusted_edge") or top.get("edge") or top.get("price_edge_pct"))
        edge_pct = fraction * 100.0 if fraction is not None else None

    # `market_probability` came back null on every measured answer while
    # `quote.fair_probability` sat on the same object; `EV` came back null
    # while `ev_pct` did. Neither was missing data -- both were the wrong key.
    # The harness has been reporting the first as a WARNING
    # (`edge_without_market_probability`) into a list nobody reads.
    #
    # **THE SOURCE ORDER IS LOAD-BEARING, AND READING `quote.fair_probability`
    # FIRST RE-CREATES THE BUG THIS LANE EXISTS TO FIX.** Caught in the first
    # replay over the live board: the briefing showed `Market 49.0%` and the
    # per-pick answer `Market 51.0%` for the same pick at the same instant.
    # They are two different quantities -- `_board_row_probabilities` derives
    # market from `projection.market_fair_prob_over` and RECONCILES it against
    # `model_edge_pct`, while `quote.fair_probability` is the no-vig price of
    # one specific quote. Only the first satisfies `model - market == edge`,
    # which is the identity the board itself publishes.
    #
    # So: derive from the identity when both terms are present. That is exact
    # arithmetic on two published numbers, not an estimate, and it guarantees
    # the three numbers in an answer cannot contradict each other. The quote's
    # fair price is the last resort, for rows carrying no model edge at all.
    # `confidence` used to fall back to `top["confidence"]`, which on a layer2
    # candidate is **book_confidence** -- a price-reliability term -- published
    # under a name every reader takes as model confidence. Model probability or
    # nothing.
    model_probability = _to_pct(top.get("model_probability"))

    quote = _mapping_or_empty(top.get("quote"))
    market_probability = _to_pct(top.get("market_probability") or top.get("implied_probability"))
    if market_probability is None and model_probability is not None and edge_pct is not None:
        market_probability = round(model_probability - edge_pct, 2)
    if market_probability is None:
        market_probability = _to_pct(quote.get("fair_probability"))
    ev = _to_float(top.get("expected_value") or top.get("ev_current") or top.get("ev_pct") or top.get("ev"))

    return {
        "schema_type": "bet_analysis",
        "selection": selection,
        **facts,
        **sim,
        "model_probability": model_probability,
        "market_probability": market_probability,
        "edge": edge_pct,
        "edge_pct": edge_pct,
        "EV": ev,
        "confidence": model_probability,
        "recommendation": (
            _candidate_prose(top)
            or _reason_sentences(
                top, facts, sim,
                model_pct=model_probability, market_pct=market_probability, edge_pct=edge_pct,
            )
            or explanation.get("summary")
        ),
        "relevance_matched": relevance_matched,
        "explanation": {
            "summary": _candidate_prose(top) or explanation.get("summary"),
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
                "recommendation": _candidate_prose(row),
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
            "summary": _candidate_prose(top) or explanation.get("summary"),
            "top_candidate": top,
            "analysis_focus": analysis_views.get("focus"),
            "rows_considered": len(rows),
        },
        "hidden_factors": hidden_factors,
        "market_insight": {
            "summary": top.get("market_fit_note") or _candidate_prose(top) or explanation.get("summary"),
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


def _excluded_clause(count: int) -> str:
    """Why rows were dropped, worded so it stays true for every drop reason.

    This said "priced against the model", which was already loose (it covered
    rows dropped for a non-positive `ev_pct`, where the model has no opinion at
    all) and became plainly wrong once eligibility started vetoing on EV as well
    as model edge: a row can now be dropped with the model FOR it and only the
    price against it. `_has_positive_edge` does not report which term objected,
    so the sentence must not claim to know.
    """
    plural = "s" if count != 1 else ""
    verb = "were" if count != 1 else "was"
    return f"{count} row{plural} with a non-positive edge {verb} left out."


def _board_summary_sentence(rows: Any, excluded_negative: int = 0) -> str:
    """A factual one-liner describing the opportunities actually returned.

    Everything here is read off the rows -- count, sports covered, and the
    best edge present. Nothing is inferred or narrated, so this stays true
    whether or not the optional LLM briefing is enabled.
    """
    items = [row for row in (rows or []) if isinstance(row, dict)]
    if not items:
        # AN EXPLAINED ABSENCE, NOT A BARE ONE. "No opportunities" reads as
        # "the board is empty" when the truth may be "the board is full and the
        # model likes none of it" -- two very different facts for a bettor.
        if excluded_negative > 0:
            return (
                f"No positive-edge opportunities on today's board right now — "
                f"{_excluded_clause(excluded_negative)}"
            )
        return "No opportunities are on the board right now."
    sports = []
    for row in items:
        label = str(row.get("sport") or row.get("sport_slug") or "").strip().upper()
        if label and label not in sports:
            sports.append(label)
    # `edge` is a FRACTION on snapshot rows and a PERCENT on board rows, and
    # this sentence used to multiply by 100 unconditionally. Live for 14
    # minutes on 2026-08-15: "Best edge 635.0%", from a board row carrying
    # `model_edge_pct = 6.35`. Rather than guess the scale from the magnitude
    # -- which is what the regression harness has to do, and which breaks for a
    # genuine sub-1.5% edge -- rows that already know their own units say so in
    # `edge_pct`, and only rows that do not get the fraction conversion.
    best_pct = None
    for row in items:
        pct = _to_float(row.get("edge_pct"))
        if pct is None:
            fraction = _to_float(row.get("edge"))
            pct = fraction * 100.0 if fraction is not None else None
        if pct is not None and (best_pct is None or pct > best_pct):
            best_pct = pct
    parts = [f"Showing the top {len(items)} opportunit{'y' if len(items) == 1 else 'ies'} on today's board"]
    if sports:
        shown = ", ".join(sports[:4])
        parts.append(f"across {shown}" if len(sports) > 1 else f"in {shown}")
    sentence = " ".join(parts) + "."
    if best_pct is not None:
        sentence += f" Best edge {best_pct:.1f}%."
    # Say why the list is short. Without this, "top 2" on a 70-row board reads
    # as thin data rather than as a deliberate exclusion.
    if excluded_negative > 0:
        sentence += f" {_excluded_clause(excluded_negative)}"
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


# Markets where `side` names the team you are betting AGAINST, not for.
# Mirrors `layer2_board._LAY_MARKETS`; see `_bet_label` for why this is
# duplicated rather than imported.
# An artifact older than this is not a plausible offset, it is a broken clock
# (wrong timezone, a date-only string parsed as midnight, a stale mirror). Adding
# it would invent hours of staleness, so the offset is dropped and the stamped
# age stands.
_MAX_PLAUSIBLE_ARTIFACT_AGE_SECONDS = 86_400.0

# When to tell a reader to re-check the price. **Raised 15min -> 45min in the
# same change that made the age REAL, because the old number was calibrated
# against an age that did not tick and became meaningless once it did.**
#
# Measured on the served board 2026-08-16 20:2xZ, real ages (stamped + the
# artifact's own 14.3 min), 70 rows carrying a seen-clock:
#
#     min 27.3 | p50 27.3 | p75 54.2 | p90 61.5 | max 61.5   (minutes)
#
#     threshold   warned          threshold   warned
#      15 min     70/70  100.0%    60 min     18/70   25.7%
#      30 min     19/70   27.1%    75 min      0/70    0.0%
#      45 min     19/70   27.1%
#
# **The MINIMUM real age on the board is 27 minutes**, so 15 min fired on every
# row -- an accurate warning that carries no information. 45 min sits above the
# normal rebuild+fetch cycle and flags the genuine tail (the slower-cadence
# sport and the older batch) at ~27%. It is one constant: raise it if the board
# gets faster, lower it if a sport needs tighter watching.
_STALE_QUOTE_SECONDS = 2_700.0


def _seconds_since(stamp: Any) -> float | None:
    """Seconds between an ISO-8601 stamp and now, or None if it is unusable.

    Naive stamps are read as UTC, which is what every artifact in this repo
    writes. A negative delta (clock skew) and an implausibly large one are both
    rejected rather than clamped -- see `_MAX_PLAUSIBLE_ARTIFACT_AGE_SECONDS`.
    """
    text = str(stamp or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = (datetime.now(timezone.utc) - parsed).total_seconds()
    if delta < 0 or delta > _MAX_PLAUSIBLE_ARTIFACT_AGE_SECONDS:
        return None
    return delta


def _result_as_of(result: Any) -> str | None:
    """When the snapshot behind `result` was computed.

    Key order mirrors `ask_the_syndicate.py`'s own scan, which mirrors
    `pipeline/intelligence_state.py`'s -- three names because
    `read_latest_intelligence_state` has four return paths whose payload shapes
    differ, and production runs the one carrying `state_meta` with no
    `freshness` key at all. Reading only `freshness` was inert in production
    while passing locally; do not narrow this.
    """
    payload = _result_payload(result)
    for container in (payload, result if isinstance(result, dict) else None):
        if not isinstance(container, dict):
            continue
        for key in ("state_meta", "freshness", "state_freshness"):
            source = container.get(key)
            if isinstance(source, dict):
                stamp = source.get("computed_at") or source.get("as_of")
                if stamp:
                    return str(stamp)
    return None


_LAY_MARKET_TOKENS = ("_lay",)

# Sides that ARE the whole selection with no number attached. Mirrors what
# `layer2_board._pick_label` reaches via `side.title()` when no team matches.
_SELF_CONTAINED_SIDES = frozenset({"draw", "tie"})

# Only the keys whose raw form reads badly mid-sentence. Everything else falls
# through to underscores-to-spaces, which is already readable
# ("batter_total_bases" -> "batter total bases").
_MARKET_LABELS = {
    "h2h": "moneyline",
    "h2h_lay": "moneyline (lay)",
    "spreads": "spread",
    "spreads_alt": "alt spread",
    "totals": "total",
    "totals_alt": "alt total",
}


def _is_lay_market(market: Any) -> bool:
    text = str(market or "").strip().lower()
    return any(token in text for token in _LAY_MARKET_TOKENS)


def _market_label(market: Any) -> str:
    key = str(market or "").strip().lower()
    if not key:
        return ""
    return _MARKET_LABELS.get(key) or key.replace("_", " ")


def _format_handicap(line: Any) -> str:
    """A team handicap always carries its sign; `+1.5` and `-1.5` are two bets."""
    value = _to_float(line)
    if value is None:
        return ""
    if value == 0:
        return "PK"
    return f"{value:+g}"


def _matchup_text(row: dict[str, Any]) -> str:
    explicit = str(row.get("matchup") or "").strip()
    if explicit:
        return explicit
    away, home = str(row.get("away_team") or "").strip(), str(row.get("home_team") or "").strip()
    return f"{away} @ {home}".strip(" @")


def _bet_label(row: dict[str, Any]) -> str | None:
    """The bet, as a string someone could carry to a betting slip.

    **A LABEL IS NOT A BET UNTIL IT NAMES THE SIDE YOU CAN PLACE.** The
    FORBIDDEN rule of 2026-08-15 (never treat equality of a LABEL as identity of
    a BET) and the CLOSED `spread-line-sign-convention` lane are both about this
    exact string. Three rules, in order:

    1. **A prop is the player, the direction AND the number** -- "Ryan Johnson
       over 2.5". This used to emit the bare `player_name`, which names no bet
       at all: reported live 2026-08-16, where the answer to a question about a
       specific prop read "Ryan Johnson" with no market, no line and no side,
       while the object it was reading carried all three.
    2. **A game side is the TEAM, never the word "home".** Served the same day:
       `"home -1.5 (Philadelphia Phillies @ Minnesota Twins)"` -- a reader has
       to already know the convention that home is the second name before they
       can place it. `line` is the row's OWN side's handicap (pinned by
       `spread-line-sign-convention`: 12 of 12 MLB spreads rows correct on the
       served shortlist, including the 3 home rows that were the broken case),
       so it pairs with that side's team directly.
    3. **A LAY market is a bet AGAINST the named team and must say so.**
       `side` still reads "home" on an `h2h_lay` row, so the market key is the
       only signal. Emitting a bare team name there is not vague, it is
       inverted -- a reader who acts on it takes the opposite position.

    Deliberately duplicated from `layer2_board._pick_label` rather than
    imported: that module's own header says it is a worker-side builder that
    must not be called from a request path, and this adapter renders every
    answer. `tests/test_ask_answer_substance.py` pins the two together so they
    cannot drift.
    """
    player = str(row.get("player_name") or row.get("player") or "").strip()
    side = str(row.get("side") or "").strip().lower()
    line = row.get("line")
    # Validate through `_to_float` (which now rejects NaN) but RENDER from the
    # original, so a valid line keeps its own formatting -- `10.0` stays "10.0"
    # rather than becoming "10" via a %g round-trip.
    line_text = "" if _to_float(line) is None else str(line)

    if player:
        return " ".join(part for part in (player, side, line_text) if part)

    team = ""
    if side == "home":
        team = str(row.get("home_team") or "").strip()
    elif side == "away":
        team = str(row.get("away_team") or "").strip()

    if team:
        label = f"{team} {_format_handicap(line)}".strip()
        if _is_lay_market(row.get("market") or row.get("market_key")):
            return f"LAY {label} (wins if {team} does not)"
        return label

    # **Everything below needs BOTH a side and a number.** Without them there is
    # no bet here to describe, and this must return None so the caller keeps
    # whatever `selection` it already had. Caught by
    # `test_adapter_promotes_question_relevant_recommendation`: a snapshot
    # candidate carrying only `name` and `matchup` turned
    # "Milwaukee Brewers ML" into "(Milwaukee Brewers vs Pittsburgh Pirates)" --
    # strictly worse than the string it replaced. This function improves a
    # label or leaves it alone; it never degrades one.
    matchup = _matchup_text(row)

    # A SIDE THAT IS A COMPLETE BET WITHOUT A NUMBER. "draw" on a three-way
    # market names the whole selection; "over" does not. Whitelisted rather than
    # inferred, because the failure directions differ: emitting "Over (A @ B)"
    # names no bet, while dropping the draw leg loses a real one.
    #
    # Found 2026-08-16 by the NaN fix, which turned the served
    # "draw nan (Indiana Fever @ Atlanta Dream)" into a `selection` of literally
    # None -- less wrong, still not a bet. `layer2_board._pick_label` renders
    # this row "Draw" (via `side.title()`), so returning None here was also a
    # DRIFT between the two labellers that
    # `test_bet_label_matches_layer2_pick_label_on_team_naming` did not catch:
    # it only exercised home/away rows.
    if side in _SELF_CONTAINED_SIDES:
        label = side.title()
        return f"{label} ({matchup})" if matchup else label

    if not side or not line_text:
        return None

    # over/under on a game total: the direction and number ARE the bet, and the
    # matchup is the only thing identifying which game.
    label = f"{side} {line_text}"
    return f"{label} ({matchup})" if matchup else label


def _bet_facts(row: dict[str, Any], *, artifact_as_of: Any = None) -> dict[str, Any]:
    """Market, line, side and the price you would actually get.

    Every field here was already on the candidate and was being dropped. An
    answer that names an edge without naming the price and book behind it is
    not actionable -- and `ev` is computed against that price, so the two
    belong together.
    """
    quote = _mapping_or_empty(row.get("quote"))
    price = _to_float(quote.get("price"))
    if price is None:
        price = _to_float(row.get("odds"))
    books = quote.get("books_quoting")
    # **TWO CLOCKS, AND THIS ONE WANTS THE SECOND.** `layer2_board`'s
    # `_row_quote_age_seconds` spells out the distinction and this originally
    # took the wrong half:
    #
    #   book_age_seconds       -- has the PRICE MOVED. `book_quotes` is a change
    #                             log, so an unchanged price writes no row and a
    #                             motionless market ages without limit.
    #   quote_seen_age_seconds -- how stale OUR OBSERVATION is, i.e. when we
    #                             last looked. This is the one that answers
    #                             "is this price still there".
    #
    # Measured on the served board 2026-08-16, 101 rows: warning off `book_age`
    # fired on 31 rows, off `seen_age` on 18, and **13 of the 31 were FALSE** --
    # worst case `book_age 217.4m` against `seen_age 3.0m`, which would have
    # told a reader a three-minute-old MLB price was three and a half hours
    # stale. A quiet market is not a stale one, and the false alarms all landed
    # on the freshest sport on the board.
    #
    # Gated the same way the board gates: seen first, book only as the fallback
    # for a source that never produced a seen-age (absence of a clock is not
    # evidence of staleness).
    age = _to_float(quote.get("quote_seen_age_seconds"))
    if age is None:
        age = _to_float(quote.get("book_age_seconds"))
    if age is None:
        age = _to_float(row.get("book_age_seconds"))

    # **THE STAMPED AGE DOES NOT TICK.** It is frozen at ARTIFACT BUILD time, so
    # reading it raw reports how old the quote was when the board was written,
    # not how old it is now. Measured 2026-08-16: three reads of the live
    # shortlist 45s apart returned byte-identical ages (`mlb=[12.9, 39.8]
    # wnba=[47.1]` at 20:18:34, 20:19:19, 20:20:04) while `written_at` sat at
    # 20:15:41Z -- so the true WNBA age at the last read was ~51.5 min, not 47.1.
    # Every consumer of this field understates age by the artifact's own age.
    #
    # Real age = stamped age + time since the artifact was written. The caller
    # supplies that timestamp because only the caller knows WHICH artifact the
    # row came from; `_seconds_since` rejects a skewed or implausible one rather
    # than inventing staleness.
    #
    # **This yields a LOWER BOUND, not an exact age, and deliberately so.** On
    # the board path `artifact_as_of` is the shortlist's own `written_at` and the
    # result is exact. On the snapshot path it is the intelligence state's
    # `computed_at`, which can POST-date the shortlist build the quote was
    # stamped in -- so the offset is real but may be short. Under-reporting
    # staleness by a bounded amount is the safe direction here; the alternative
    # is guessing at an artifact chain this function cannot see.
    elapsed = _seconds_since(artifact_as_of)
    if age is not None and elapsed:
        age += elapsed
    market = row.get("market") or row.get("market_key")
    return {
        "market": market,
        "market_label": _market_label(market) or None,
        "line": _to_float(row.get("line")),
        "side": str(row.get("side") or "").strip().lower() or None,
        "price": int(price) if price is not None and float(price).is_integer() else price,
        "bookmaker": str(quote.get("bookmaker") or "").strip() or None,
        "books_quoting": int(books) if isinstance(books, int) and not isinstance(books, bool) else None,
        "quote_age_seconds": round(age, 1) if age is not None else None,
        "matchup": _matchup_text(row) or None,
    }


def _sim_terms(row: dict[str, Any]) -> dict[str, Any]:
    """The simulation's own output, and whether it has ever been checked.

    **`score.sim_component` is deliberately NOT read here.** It is 0.0 on 108
    of 108 served rows (`_SCORE_SIM_WEIGHT` is zeroed pending settlement), so
    publishing it would report "the sim contributed nothing" as if it were a
    measurement of this bet. `projection.projected` is the sim term that is
    actually populated -- 86 of 108 rows.

    `model_skill` is carried because a user asked to trust a number is entitled
    to know that 88 of 108 rows say of themselves "model never backtested --
    projection is unvalidated". Under the standing decision that the LLM stays
    off, the system prompt's rules about surfacing uncertainty will never
    execute, so this is the only place they can live.
    """
    projection = _mapping_or_empty(row.get("projection"))
    projected = _to_float(projection.get("projected"))
    if projected is None:
        projected = _to_float(row.get("sim_projection"))
    if projected is None:
        projected = _to_float(row.get("projected"))

    # **A TEAM SIDE'S PROJECTION IS NOT PUBLISHED, AND THIS IS THE WHOLE
    # REASON.** On a spreads row the projection is a run margin
    # (`basis: "full/run_margin_dist"`) whose sign convention against the
    # handicap is not pinned anywhere in this payload. Caught in the first
    # replay of this change over the live board: a `Minnesota Twins -1.5` row
    # rendered "Sim 1.369" directly beside "Edge 14.8%", which invites the
    # reader to compare 1.369 against -1.5 -- a comparison nothing here
    # justifies. `_reason_sentences` already declines to write that clause for
    # the same reason; publishing the raw number in the numbers row would have
    # smuggled it back in. Over/under sides are safe: there the line and the
    # projection are the same quantity by construction.
    if str(row.get("side") or "").strip().lower() not in ("over", "under"):
        projected = None

    skill = _mapping_or_empty(projection.get("model_skill")) or _mapping_or_empty(row.get("model_skill"))
    sample = skill.get("sample_games")
    return {
        "projected": round(projected, 3) if projected is not None else None,
        "projection_basis": str(projection.get("basis") or "").strip() or None,
        "projection_source": str(projection.get("source") or "").strip() or None,
        "model_skill_status": str(skill.get("status") or "").strip() or None,
        "model_skill_verdict": str(skill.get("verdict") or "").strip() or None,
        "model_skill_sample_games": int(sample) if isinstance(sample, int) and not isinstance(sample, bool) else None,
    }


def _reason_sentences(
    row: dict[str, Any],
    facts: dict[str, Any],
    sim: dict[str, Any],
    *,
    model_pct: float | None,
    market_pct: float | None,
    edge_pct: float | None,
) -> str | None:
    """A deterministic reason built from fields the row already carries.

    **The MLB game lens is the shape this copies.** Its narrative
    (`vendor/mlb_bettingv2/tools/web/flask_frontend.py:15232-15244`) is plain
    string assembly -- "The live total still leans over because the projection
    sits at 7.42 against 5.0. There are 34 outs left..." -- with no model in the
    loop. Ask had every analogue on its own rows and generated nothing:
    `_candidate_prose` looks for a `detail`/`writeup` field, and layer2 rows do
    not have one, so `recommendation` came back `null` on 5 of 5 briefing rows
    and on every per-pick answer. The gap was a missing GENERATOR, not a
    missing source.

    Every clause is guarded independently. Absent renders as absent -- a row
    with no projection gets the price and freshness clauses and no invented
    sim term.
    """
    parts: list[str] = []
    side = facts.get("side")
    line = facts.get("line")
    projected = sim.get("projected")

    # 1. Sim vs line. **Over/under only.** For a team side the projection is a
    # run margin whose sign convention against the handicap is not pinned in
    # this payload, and the rule is that a published number is computed or
    # absent, never inferred. The model-vs-market clause below still covers
    # team sides, because `_board_row_probabilities` reconciles those against
    # the row's own stated edge and returns None when it cannot.
    if projected is not None and line is not None and side in ("over", "under"):
        # The market label is a UNIT only for a prop ("3.951 earned runs").
        # On a game total it is the word "total", and "9.494 total against a
        # line of 7.5" reads as a typo -- worse on `totals_alt`, which gave
        # "7.057 alt total against a line of 6.5". Both seen in the first
        # replay over the live board.
        unit = str(facts.get("market_label") or "").strip() if row.get("player_name") else ""
        unit_text = f" {unit}" if unit else ""
        # **DOES THE PROJECTION ACTUALLY SUPPORT THIS SIDE?** "which is why it
        # lands on the under" is a CAUSAL claim, and it was being made without
        # ever comparing the two numbers it names. Served 21:4xZ:
        #
        #     "The simulation projects 1.396 batter hits against a line of 0.5,
        #      which is why it lands on the under."
        #
        # 1.396 is above 0.5 -- that projection argues for the OVER. Wade
        # Meckler, `basis=live_resim`. The sibling row (Kyle Isbel, 0.256
        # against 0.5, under) was correct, which is exactly why this survived
        # review: the template only breaks when the projection falls on the
        # opposite side of the line from the bet.
        #
        # **A MEAN DOES NOT DETERMINE A SIDE ON A COUNT PROP, AND THE FIRST
        # VERSION OF THIS GUARD DID NOT KNOW THAT.** Fixing the causal claim, I
        # replaced it with "which does NOT support the {side}" — which is the
        # same category error pointing the other way. `projected` is a MEAN;
        # what picks a side is `P(X > line)`. For a low-line count prop those
        # diverge routinely and legitimately: a mean of 0.214 runs still implies
        # `P(>=1) ~ 19%`, which beats a market implying 15%, so `over 0.5` is a
        # perfectly good bet with the mean BELOW the line. Served examples that
        # the previous wording called unsupported and which are probably fine:
        # `Jake Cronenworth over 0.5` (mean 0.214), `Osleivis Basabe under 2.5`
        # (mean 2.829).
        #
        # So the directional CLAIM is now made only where the mean is the right
        # statistic:
        #
        #   * GAME rows (no `player_name`) — totals and margins, means in the
        #     7-9 range against nearby lines. This is exactly the comparison the
        #     MLB game lens makes ("the projection sits at 7.42 against 5.0"),
        #     and it is the reference this generator was modelled on.
        #   * PROP rows — the relationship is reported as a FACT ("above the 0.5
        #     line") and nothing is claimed about why the side was taken. The
        #     model-vs-market clause below already states the probability-space
        #     case when the row carries one, which is the number that actually
        #     picks the side.
        #
        # The original defect stays fixed: `1.396 batter hits` no longer reads
        # as the REASON for an under. It now reads as "above the 0.5 line",
        # which is true, useful, and not a claim about the bet.
        above = projected > line
        if row.get("player_name"):
            parts.append(
                f"The simulation projects {projected:g}{unit_text}, "
                f"{'above' if above else 'below'} the {line:g} line."
            )
        else:
            supports = above if side == "over" else not above
            clause = (
                f"which is why it lands on the {side}" if supports
                else f"which does NOT support the {side}"
            )
            parts.append(
                f"The simulation projects {projected:g}{unit_text} against a line of {line:g}, {clause}."
            )
    elif projected is not None and side in ("over", "under"):
        parts.append(f"The simulation projects {projected:g}, on the {side} side.")

    # 2. Model vs market.
    if model_pct is not None and market_pct is not None:
        edge_text = f" — a {edge_pct:.1f} point edge." if edge_pct is not None else "."
        parts.append(
            f"That prices at {model_pct:.1f}% against the market's {market_pct:.1f}%{edge_text}"
        )
    elif edge_pct is not None:
        parts.append(f"Model edge {edge_pct:.1f}% against the market's fair price.")

    # 3. The price you would actually get, and how many books agree.
    price, book = facts.get("price"), facts.get("bookmaker")
    if price is not None and book:
        books = facts.get("books_quoting")
        agree = f", {books} book{'s' if books != 1 else ''} quoting" if books else ""
        parts.append(f"Best bettable price {price:+g} at {book}{agree}.")

    # 4. Has this model ever been checked? See `_sim_terms`.
    status = sim.get("model_skill_status")
    if status == "unmeasured":
        parts.append("This model has never been backtested, so treat the projection as unvalidated.")
    elif status and sim.get("model_skill_verdict"):
        parts.append(f"Model skill {status}: {sim['model_skill_verdict']}.")

    # 5. Game situation and quote staleness -- the game lens's other half.
    game = _mapping_or_empty(row.get("game"))
    if row.get("is_live") or str(row.get("game_state") or "").strip().lower() == "live":
        away_score, home_score = game.get("away_score"), game.get("home_score")
        if away_score is not None and home_score is not None:
            parts.append(f"Live now at {away_score}-{home_score}.")
        else:
            parts.append("This game is already live.")
    age = facts.get("quote_age_seconds")
    if age is not None and age >= _STALE_QUOTE_SECONDS:
        # Says WHEN WE LOOKED, not "the price is old" -- see `_bet_facts` for
        # why those are different claims. The old wording ("The quote behind
        # this is N minutes old") was true of neither clock once the field was
        # corrected: it reads as a claim about the market when the number is a
        # claim about our own data.
        parts.append(
            f"Last checked {int(age // 60)} minutes ago, so confirm the price before betting."
        )

    return " ".join(parts) or None


def _board_row_probabilities(row: dict[str, Any]) -> tuple[float | None, float | None]:
    """Model and market probability FOR THE ROW'S OWN SIDE, or (None, None).

    **This is not a rename, and getting it wrong publishes a confident number
    that is wrong by construction.** Measured against the live shortlist
    2026-08-15: `projection.model_prob_over` is the probability of
    `projection.side`, NOT of the row's side. 10 of 19 model-bearing rows had a
    row side opposite their projection side ("under" rows carrying an "over"
    projection, an "away" row carrying a "home" one), and for every one of them
    `(model_prob_over - market_fair_prob_over)` came out at exactly the NEGATIVE
    of the row's stated `model_edge_pct`. Taking the field at its name would
    have shipped the wrong side's probability on more than half the rows.

    So the opposite side is complemented, and the result is then RECONCILED
    against the row's own `model_edge_pct`. If the two disagree, this returns
    None rather than a number it cannot justify -- the house rule is that a
    published probability is computed or absent, never invented.
    """
    projection = _mapping_or_empty(row.get("projection"))
    model_p = _to_float(projection.get("model_prob_over"))
    market_p = _to_float(projection.get("market_fair_prob_over"))
    if model_p is None or market_p is None:
        return (None, None)

    row_side = str(row.get("side") or "").strip().lower()
    projection_side = str(projection.get("side") or "").strip().lower()
    if row_side and projection_side and row_side != projection_side:
        model_p, market_p = 1.0 - model_p, 1.0 - market_p

    stated_edge = _to_float(row.get("model_edge_pct"))
    if stated_edge is not None and abs((model_p - market_p) * 100.0 - stated_edge) > 0.01:
        # The complement rule did not reproduce the row's own edge. Something
        # about this row's shape is not what was measured; say nothing.
        return (None, None)
    return (round(model_p * 100.0, 2), round(market_p * 100.0, 2))


def _has_positive_edge(row: dict[str, Any]) -> bool:
    """Is the number this row is RANKED ON actually positive?

    **A negative edge is the model saying "do not bet this".** Served
    2026-08-16 20:5xZ under the headline "Showing the top 5 opportunities on
    today's board in MLB. Best edge 4.9%": three of the five carried
    `model_edge_pct` of -1.83, -4.87 and -8.20. The ranker was not wrong -- the
    board had thinned to 70 rows with only 6 carrying a model edge and only 2 of
    those positive, so "the best 5" genuinely included four bad bets. Sorting
    correctly is not the same as having something to show.

    This is the second time this exact shape has shipped. `_market_summary_schema`
    already carries a note about 2026-08-03, when the summary "returned 4
    negative-edge rows with the only positive one (+16.9%) ranked LAST", and the
    fix then was to SORT. Sorting was necessary and never sufficient: it orders a
    pool, it does not decline to publish one.

    **ELIGIBILITY IS DELIBERATELY STRICTER THAN RANKING, and that is a change
    from the first cut.** `_board_rank_key` picks ONE term -- `model_edge_pct`
    when present, `ev_pct` otherwise -- and the first version of this function
    mirrored it, judging a row on the same single term it is ordered by. That
    published `Pittsburgh Pirates` at **model edge +9.18% with EV -2.18%**
    (production, 21:0xZ, found in the post-deploy read): the model liked the side
    while the offered price was worse than consensus fair. Ranking wants one
    number to sort on; eligibility is a veto, and a veto should hear every term
    that can object.

    So: every edge term the row actually carries must be positive. A row with
    both must satisfy both; a row with one must satisfy that one; a row with
    neither is not an opportunity. Ordering is untouched -- this only decides
    what is allowed into the pool being ordered.

    `ev_pct` is checked at all because it is NOT floored at zero: the served
    board's `min_value_pct` is **-2.0**, and 6 of 70 rows had `ev_pct <= 0`.

    `isinstance(True, int)` is True in Python, so bools are excluded explicitly
    -- a stray flag must not be read as an edge of 1.0.
    """
    terms = [
        float(value)
        for value in (row.get("model_edge_pct"), row.get("ev_pct"))
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return bool(terms) and all(term > 0.0 for term in terms)


def _board_rank_key(row: dict[str, Any]) -> tuple[int, float]:
    """The ranking M1 uses, kept identical on purpose.

    Rows carrying a model comparison sort above rows that only have EV -- only
    19 of 105 published rows carried `model_edge_pct` when this was written, so
    ranking on edge alone would drop most of the board. Because model-bearing
    rows sort first and by descending edge, the top row IS the board's maximum
    `model_edge_pct`, which is precisely what the divergence check compares.
    """
    edge = row.get("model_edge_pct")
    if isinstance(edge, (int, float)):
        return (1, float(edge))
    ev = row.get("ev_pct")
    return (0, float(ev) if isinstance(ev, (int, float)) else float("-inf"))


def _board_top_opportunities(context: dict[str, Any], result: Any) -> tuple[list[dict[str, Any]] | None, int]:
    """`top_opportunities` sourced from the SAME artifact the board serves.

    **Why this exists.** `M1` gave aggregation questions a board-wide table but
    left `structured_response.top_opportunities` reading the snapshot, so chat
    and the board still answered from two different pools and still disagreed --
    measured at one instant as 23.81% vs 14.09%. Adding a table did not fix
    that; only sharing the source does, which is what this does.

    Read-only: `read_layer2_shortlist` is a plain `read_json_file`, so this is
    legal on the web request path under the rule that handlers read precomputed
    artifacts and never recompute.

    Returns None -- never an empty list -- when the artifact is missing or the
    sport filter empties it, so the caller keeps the snapshot behaviour rather
    than serving an empty headline.
    """
    try:
        from pipeline.intelligence_state import read_layer2_shortlist
        from syndicate.features.shared.timezone import central_today_iso
    except Exception:
        return None

    selected_date = (
        str(_result_value(result, "selected_date", "") or "").strip()
        or str(context.get("selected_date") or "").strip()
    )
    try:
        payload = read_layer2_shortlist(selected_date or central_today_iso())
    except Exception:
        # A headline is worth degrading, not worth 500ing an answer over.
        return None, 0
    if not isinstance(payload, dict):
        return None, 0
    rows = [row for row in (payload.get("rows") or []) if isinstance(row, dict)]
    if not rows:
        return None, 0

    sport = str(context.get("sport_slug") or context.get("sport") or "").strip().lower()
    if sport:
        # EXACT match, not a substring test: `"nba" in "wnba"` is True and
        # would answer an NBA question with WNBA rows.
        scoped = [row for row in rows if str(row.get("sport") or "").strip().lower() == sport]
        # Unlike M1 -- which REPORTS an empty sport filter, because "no NHL rows
        # on the board" answers an aggregation question -- an empty headline
        # answers nothing. Fall back to the snapshot instead of emptying the
        # only rows a non-aggregation market summary has.
        if not scoped:
            return None, 0
        rows = scoped

    # DECLINE TO PUBLISH A BAD BET. Filtering before the slice, not after, so a
    # thin board returns fewer rows rather than padding the five out with
    # negatives. An EMPTY list here is a real answer ("nothing qualifies right
    # now") and is deliberately distinguished from the `None` returned above for
    # a missing artifact -- see the caller, which tests `is not None`.
    considered = len(rows)
    rows = [row for row in rows if _has_positive_edge(row)]
    excluded = considered - len(rows)

    rows.sort(key=_board_rank_key, reverse=True)
    top: list[dict[str, Any]] = []
    for row in rows[:5]:
        model_pct, market_pct = _board_row_probabilities(row)
        score = _mapping_or_empty(row.get("score"))
        # EXACT on this path: `written_at` is the timestamp of the very artifact
        # these rows were stamped in.
        facts = _bet_facts(row, artifact_as_of=payload.get("written_at"))
        sim = _sim_terms(row)
        edge_pct = _to_float(row.get("model_edge_pct"))
        top.append(
            {
                "selection": _bet_label(row) or row.get("selection"),
                **facts,
                **sim,
                "sport": row.get("sport"),
                "model_probability": model_pct,
                "market_probability": market_pct,
                # The field the board's own max is taken over. Same units
                # (already a percent), so chat and the board are comparing the
                # same number rather than two scalings of it.
                "edge": edge_pct,
                # Explicit units, so no downstream reader has to infer the
                # scale from the magnitude. See `_board_summary_sentence`.
                "edge_pct": edge_pct,
                "EV": _to_float(row.get("ev_pct")),
                "confidence": model_pct,
                "adjusted_score": _to_float(score.get("score")),
                "source": "layer2_shortlist",
                # Was hardcoded `None`, so every briefing row arrived with an
                # empty prose slot and the panel rendered a bare name over a
                # raw market key. Layer2 rows have no `detail` field for
                # `_candidate_prose` to find, so the sentence has to be
                # generated -- see `_reason_sentences`.
                "recommendation": _reason_sentences(
                    row, facts, sim,
                    model_pct=model_pct, market_pct=market_pct, edge_pct=edge_pct,
                ),
            }
        )
    # `top` may legitimately be EMPTY when every row was filtered out. That is a
    # published fact, not a missing one, so it is returned as-is; only the
    # missing-artifact paths above return None. The excluded count travels
    # BESIDE the rows rather than on them -- a private key stashed on a row would
    # be serialised straight into the API payload.
    return top, excluded


def _market_summary_schema(
    result: Any,
    *,
    question: str = "",
    relevance_matched: bool | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommendations = _items_to_dicts(_result_value(result, "recommendations", ()))
    # Was `recommendations[:5]` with no sort -- an arbitrary slice of
    # whatever order the payload happened to arrive in. Confirmed live
    # 2026-08-03: the summary returned 4 negative-edge rows with the only
    # positive one (+16.9%) ranked LAST, under a header claiming "best
    # edge". "Top opportunities" has to actually be the top ones.
    ranked = sorted(recommendations, key=_market_summary_rank_key, reverse=True)
    top_opportunities: list[dict[str, Any]] = []
    # THE BOARD REPLACES A POOL; IT MUST NEVER CREATE ONE.
    #
    # The headline and the board have to read from one source -- that is the
    # point. What the first cut of this got wrong is that an EMPTY
    # `recommendations` list is not missing data, it is the engine DECLINING,
    # and the served answer then says "No opportunities are on the board right
    # now", which is how a refusal reaches the user at all.
    #
    # Measured in production 2026-08-15, deployed and reverted: sourcing from
    # the board unconditionally answered "What are Shohei Ohtani's exact stats
    # for tomorrow's game?" with five unrelated NFL totals. Refusal went 4/8 ->
    # 3/8 against a same-slate control -- one case, F07, and this line is all of
    # it. So: replace a non-empty pool, never manufacture one.
    board_opportunities, board_excluded = (
        _board_top_opportunities(_mapping_or_empty(context), result) if recommendations else (None, 0)
    )
    # `is not None`, NOT truthiness. An EMPTY board list means "the board had
    # rows and none of them qualify", which is an answer; falling through to the
    # snapshot there would republish exactly the negative-edge rows the filter
    # just removed.
    if board_opportunities is not None:
        top_opportunities = board_opportunities
        ranked = []
    for item in ranked[:5]:
        # The snapshot fallback, reached only when the board artifact is
        # unavailable. Same label and same reason generator as the board path
        # above, so a degraded answer degrades in the DATA it has, not in the
        # shape a reader has to parse.
        facts = _bet_facts(item, artifact_as_of=_result_as_of(result))
        sim = _sim_terms(item)
        model_pct = _to_pct(item.get("model_probability") or item.get("confidence"))
        market_pct = _to_pct(item.get("market_probability") or item.get("implied_probability"))
        edge_pct = _to_float(item.get("model_edge_pct"))
        if edge_pct is None:
            fraction = _to_float(item.get("adjusted_edge") or item.get("edge") or item.get("price_edge_pct"))
            edge_pct = fraction * 100.0 if fraction is not None else None
        top_opportunities.append(
            {
                "selection": _bet_label(item) or item.get("selection") or item.get("pick") or item.get("name") or item.get("label"),
                **facts,
                "model_probability": model_pct,
                "market_probability": market_pct,
                "edge": edge_pct,
                "edge_pct": edge_pct,
                "EV": _to_float(item.get("expected_value") or item.get("ev_current") or item.get("ev_pct") or item.get("ev")),
                "confidence": _to_pct(item.get("confidence") or item.get("model_probability")),
                # Surfaced so the ordering is inspectable rather than
                # something a reader has to take on trust.
                "adjusted_score": _to_float(item.get("adjusted_score")),
                **sim,
                "recommendation": _candidate_prose(item) or _reason_sentences(
                    item, facts, sim,
                    model_pct=model_pct, market_pct=market_pct, edge_pct=edge_pct,
                ),
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
        summary_text = _board_summary_sentence(top_opportunities, board_excluded)
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
        schema = _market_summary_schema(
            result, question=question, relevance_matched=relevance_matched, context=context
        )
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