from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re
import threading
import time

from flask import Blueprint
from flask import jsonify
from flask import request

from router.query_router import QueryRouter as IntelligenceQueryRouter
from pipeline.intelligence_state import read_latest_intelligence_board_snapshot_response
from pipeline.intelligence_state import read_latest_intelligence_state_response
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_data import collect_focused_evidence
from syndicate.blueprints.ask_the_syndicate_engine import generate_briefing
from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter
from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.features.intelligence_board import build_intelligence_board_contract


ask_the_syndicate_bp = Blueprint("ask_the_syndicate", __name__)
_QUERY_ROUTER = SyndicateQueryRouter()
_INTELLIGENCE_ROUTER = IntelligenceQueryRouter()
_REFRESH_QUEUE_LOCK = threading.Lock()
_REFRESH_QUEUE_DEDUPE_SECONDS = 15.0
_REFRESH_QUEUE_STATE: dict[str, float] = {}

# (sport, IDENTIFIERS, HINTS) -- and the split between the two columns is the
# whole point, not decoration.
#
# THE BUG THIS REPLACES. The old table was a flat keyword list and
# `_infer_sport` returned on the FIRST tuple that matched any keyword, so a
# question's sport was decided by the order the sports happened to be written
# in. Three measured consequences:
#
#   * `wnba` was a keyword INSIDE `nba`, so every WNBA question routed to NBA.
#   * `assists` sat in both `nba` and `nhl`, and `goals`/`shots` in `nhl`, so
#     those questions were resolved by list position rather than by evidence.
#   * `ncaaf` had to be physically placed above `nfl` to stop generic football
#     vocabulary stealing college questions -- a correct fix held together by
#     a comment telling future editors not to sort the list.
#
# IDENTIFIERS name the competition and are near-conclusive ("wnba", "epl").
# HINTS are stat/market nouns that a sport uses but does not own ("assists",
# "goals"). `_infer_sport` scores identifiers far above hints and takes the
# best total, so "wnba points props" resolves on `wnba` even though `points`
# is an NBA hint, and `ncaaf` beats `nfl` on "college football" by evidence
# rather than by position. Ties still fall back to table order, which is why
# `ncaaf` is still written above `nfl` -- but that is now a tie-breaker of
# last resort, not the mechanism.
_SPORT_HINTS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "mlb",
        ("mlb", "baseball"),
        (
            "strikeout",
            "strikeouts",
            "k's",
            "k's?",
            "home run",
            "home runs",
            "hr",
            "hits",
            "hit prop",
            "rbi",
            "total bases",
            "pitcher",
            "bullpen",
            "innings",
            "ohtani",
            "cubs",
            "yankees",
            "dodgers",
        ),
    ),
    (
        # `wnba` is NO LONGER a keyword inside `nba` -- it is its own sport
        # below. Leaving it here is why WNBA questions were answered with NBA
        # routing, and it is also why `_fetchers_for_sport`'s `nba` branch
        # still lists `_wnba_focused_evidence`.
        "nba",
        ("nba",),
        ("points", "rebounds", "assists", "pra", "basketball"),
    ),
    (
        "wnba",
        ("wnba",),
        ("caitlin clark", "aces", "liberty", "fever"),
    ),
    (
        "nhl",
        ("nhl", "hockey"),
        ("shots", "saves", "goals", "assists", "puck", "power play"),
    ),
    (
        # Kept ABOVE "nfl" as a tie-breaker only. The real separation is now
        # that "college football"/"ncaaf"/"cfb" are IDENTIFIERS while
        # "football"/"passing"/"rushing" are only NFL HINTS, so a college
        # question wins on score and no longer depends on this position. No
        # team/school names here -- they collide with NBA/NFL/NHL city names;
        # team identification happens inside the fetchers via the registry.
        "ncaaf",
        ("college football", "ncaaf", "cfb", "fbs"),
        ("heisman",),
    ),
    (
        "nfl",
        ("nfl",),
        ("passing", "rushing", "receiving", "touchdowns", "tds", "football"),
    ),
    (
        # NEW. Soccer is 100 of 200 published board rows and was previously
        # unnameable -- no entry here at all, so `_infer_sport` returned None
        # and the board fetcher could never filter to it. League names carry
        # the identification because club names are too many and too
        # collision-prone to list.
        "soccer",
        (
            "soccer",
            "epl",
            "premier league",
            "la liga",
            "bundesliga",
            "serie a",
            "ligue 1",
            "mls",
            "champions league",
            "ucl",
            "europa league",
        ),
        (
            "goals",
            "goalscorer",
            "clean sheet",
            "corners",
            "nil",
            "draw",
            "fixture",
            "fixtures",
            # Club shorthands. "United"/"City" are how these teams are ACTUALLY
            # named ("What is United's price?"), and without them a soccer
            # question carrying only "goals" loses the tie to NHL, which shares
            # that hint. They are the one real collision risk in this table, so
            # both are guarded rather than listed bare:
            #   * "city" must not fire on "Kansas City" -- that is an NFL team,
            #     and NFL questions frequently carry no other NFL vocabulary
            #     at all ("What does the model project for the Kansas City
            #     game?"), so an unguarded "city" would silently route them to
            #     soccer. Salt Lake City and Oklahoma City are excluded for the
            #     same reason.
            #   * "united" must not fire on "United States".
            # These stay HINTS, not identifiers: they are weak evidence that
            # should lose to any explicit league or sport name.
            r"re:(?<!kansas )(?<!salt lake )(?<!oklahoma )\bcity\b",
            r"re:\bunited\b(?! states)",
            "arsenal",
            "liverpool",
            "chelsea",
            "tottenham",
            "everton",
            "real madrid",
            "barcelona",
            "bayern",
            "juventus",
            "psg",
        ),
    ),
    (
        # NEW, same gap as soccer -- no entry meant no routing and no branch.
        "ncaab",
        ("college basketball", "ncaab", "cbb", "march madness"),
        ("bracket", "final four"),
    ),
)


def _coerce_context(payload: dict[str, Any]) -> dict[str, Any]:
    context = payload.get("context")
    return dict(context) if isinstance(context, dict) else {}


# An identifier is worth more than any realistic number of hints, so a single
# "wnba" beats "points rebounds assists" pointing at NBA. Not infinity: two
# identifiers still beat one, which is what makes "college football" (2 words,
# 1 identifier) lose to nothing and win against NFL's bare "football" hint.
_SPORT_IDENTIFIER_WEIGHT = 100
_SPORT_HINT_WEIGHT = 1


def _sport_keyword_matches(keyword: str, normalized_question: str) -> bool:
    """Whether a `_SPORT_HINTS` term fires.

    Terms are plain words and are escaped, so a keyword can never accidentally
    behave as a pattern. The `re:` prefix is a deliberate, narrow escape hatch
    for the handful of terms that need a guard the plain form cannot express --
    today only soccer's "city"/"united", which must not fire on "Kansas City"
    or "United States". Kept explicit so a raw pattern is always visible as one
    at the call site rather than being inferred from the string's contents.
    """
    if keyword.startswith("re:"):
        return bool(re.search(keyword[3:], normalized_question))
    return bool(re.search(rf"\b{re.escape(keyword.lower())}\b", normalized_question))


def _sport_scores(question: str) -> list[tuple[str, int, tuple[str, ...]]]:
    """(sport, score, matched terms) for every sport with any evidence,
    best first. Ties keep `_SPORT_HINTS` order -- `sorted` is stable."""
    normalized_question = f" {str(question or '').lower()} "
    scored: list[tuple[str, int, tuple[str, ...]]] = []
    for sport, identifiers, hints in _SPORT_HINTS:
        matched: list[str] = []
        score = 0
        for keyword in identifiers:
            if _sport_keyword_matches(keyword, normalized_question):
                score += _SPORT_IDENTIFIER_WEIGHT
                matched.append(keyword)
        for keyword in hints:
            if _sport_keyword_matches(keyword, normalized_question):
                score += _SPORT_HINT_WEIGHT
                matched.append(keyword)
        if score:
            scored.append((sport, score, tuple(matched)))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _infer_sport(question: str, context: dict[str, Any]) -> str | None:
    explicit = str(context.get("sport_slug") or context.get("sport") or payload_value(context, "sport") or "").strip().lower()
    if explicit:
        return explicit
    scored = _sport_scores(question)
    return scored[0][0] if scored else None


def _detect_sports(question: str) -> list[str]:
    return [sport for sport, _score, _matched in _sport_scores(question)]


def payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    return value


def _with_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept, Origin, X-Requested-With"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Vary"] = "Origin"
    return response


def _smart_route_payload(payload: dict[str, Any]) -> dict[str, Any]:
    intelligence_payload = _INTELLIGENCE_ROUTER.route_payload(payload)
    question = str(intelligence_payload.get("question") or payload.get("question") or "").strip()
    context = _coerce_context(payload)
    merged = dict(intelligence_payload)
    merged.update({key: value for key, value in context.items() if value is not None})
    merged["question"] = question
    merged["original_question"] = str(payload.get("question") or "").strip()
    sport = _infer_sport(question, merged)
    if sport:
        merged["sport"] = sport
        merged["sport_slug"] = sport
    query_type = str(merged.get("query_type") or "").strip()
    if query_type in {"game_preview", "player_analysis"}:
        merged.setdefault("mode", "pregame")
        merged.setdefault("include_games", True)
        merged.setdefault("include_props", True)
    elif query_type == "comparison":
        merged.setdefault("mode", "comparison")
        merged.setdefault("include_games", True)
        merged.setdefault("include_props", True)
    elif query_type == "live_analysis":
        merged.setdefault("mode", "live")
        merged.setdefault("include_games", True)
    return merged


def _build_artifact_response(shaped_payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any] | None:
    return None


def _empty_ask_result(shaped_payload: dict[str, Any], decision: RouteDecision, *, reason: str) -> dict[str, Any]:
    question = str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip()
    return {
        "query_type": decision.intent,
        "summary": "No saved intelligence snapshot is available yet.",
        "parsed_request": {
            "question": question,
        },
        "analysis_views": {},
        "recommendations": [],
        "top_opportunities": [],
        "board_notes": ["Ask is serving the latest intelligence snapshot only."],
        "reasoning_steps": [],
        "pipeline_context": {"routing_context": {"question": question}},
        "structured_response": {"context_awareness": {"reasoning": reason}},
        "analysis_brief": {
            "kind": "bundle",
            "title": "Snapshot unavailable",
            "summary": "No saved intelligence snapshot is available yet.",
        },
        "supporting_evidence": {
            "kind": "bundle",
            "title": "Snapshot unavailable",
            "summary": "The Ask endpoint only serves persisted intelligence snapshots.",
        },
    }


def _hydrate_intelligence_snapshot_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(snapshot or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    nested = dict(nested or {})

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        nested_top = nested.get("top_opportunities") if isinstance(nested.get("top_opportunities"), list) else []
        nested_recommendations = nested.get("recommendations") if isinstance(nested.get("recommendations"), list) else []
        if nested_top:
            current["top_opportunities"] = [dict(item) for item in nested_top if isinstance(item, dict)]
        elif nested_recommendations:
            current["top_opportunities"] = [dict(item) for item in nested_recommendations if isinstance(item, dict)]

    if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
        nested_recommendations = nested.get("recommendations") if isinstance(nested.get("recommendations"), list) else []
        if nested_recommendations:
            current["recommendations"] = [dict(item) for item in nested_recommendations if isinstance(item, dict)]

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            normalized_recommendations = [dict(item) for item in analysis_recommendations if isinstance(item, dict)]
            if normalized_recommendations:
                current["top_opportunities"] = normalized_recommendations
                if isinstance(nested, dict) and (not isinstance(nested.get("top_opportunities"), list) or not nested.get("top_opportunities")):
                    nested["top_opportunities"] = list(normalized_recommendations)
        if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            if analysis_recommendations:
                current["recommendations"] = [dict(item) for item in analysis_recommendations if isinstance(item, dict)]

    return current


def read_latest_intelligence_state(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # Plan item 1F ("one contract, not one pipeline per surface"): this was
    # a third parallel read cascade (board_snapshot -> worker state), with
    # its own precedence order, separate from _cached_intelligence_response_with_source
    # in syndicate/blueprints/intelligence.py. Try the canonical board state
    # first -- same as the Board's own read path -- before falling through
    # to this function's existing order unchanged. Behind
    # SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE (default off), so this is
    # a no-op today: _load_canonical_board_response returns None immediately
    # when the flag (and its shadow-compare sibling) are both off.
    try:
        from syndicate.blueprints.intelligence import _load_canonical_board_response

        canonical_response, _canonical_source = _load_canonical_board_response(payload or {})
    except Exception:
        canonical_response = None
    if isinstance(canonical_response, dict) and canonical_response:
        return _hydrate_intelligence_snapshot_payload(canonical_response)

    # Confirmed live 2026-08-04 ("Ask the Syndicate can't reach game-market
    # picks" in todo.md): the live board's own default read
    # (intelligence_query_api's combined_board_default_enabled branch)
    # unions each date's own per-date cached response across the whole
    # board window via read_combined_intelligence_response. This function's
    # fallback below instead reads board_snapshot.json -- a SINGLE global
    # "whatever the legacy background queue finished computing last" file,
    # overwritten by every payload it processes regardless of date/sport/
    # completeness -- not the same source, and confirmed to sometimes be a
    # much narrower snapshot (100% steam candidates, zero props, zero
    # game-markets) than what the board was showing at that same moment.
    # Try the board's own combined source first, same flag-gate, before
    # falling through to the older cascade unchanged.
    try:
        from syndicate.blueprints.intelligence import combined_board_default_enabled
        from pipeline.intelligence_state import read_combined_intelligence_response

        if combined_board_default_enabled():
            explicit_date = str((payload or {}).get("date") or (payload or {}).get("selected_date") or "").strip()
            requested_sport = str((payload or {}).get("sport") or "all").strip().lower() or "all"
            combined_response = read_combined_intelligence_response(
                dates=[explicit_date] if explicit_date else None,
                sport=requested_sport,
                limit=(payload or {}).get("limit"),
            )
            if isinstance(combined_response, dict) and combined_response.get("candidate_count"):
                return _hydrate_intelligence_snapshot_payload(combined_response)
    except Exception:
        pass

    board_snapshot = read_latest_intelligence_board_snapshot_response(payload or {}, force_refresh=False)
    if isinstance(board_snapshot, dict):
        return _hydrate_intelligence_snapshot_payload(board_snapshot)

    snapshot = read_latest_intelligence_state_response(payload or {}, force_refresh=False)
    if isinstance(snapshot, dict):
        return _hydrate_intelligence_snapshot_payload(snapshot)
    return {}


def _base_pipeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    question = str(payload.get("question") or "").strip()
    context = _coerce_context(payload)
    routed_payload = dict(context)
    routed_payload["question"] = question

    for key in ("selected_date", "date", "sport", "mode", "limit", "timing", "include_props", "include_games", "force_refresh"):
        if key in payload and payload.get(key) is not None:
            routed_payload[key] = payload.get(key)

    if context:
        routed_payload["context"] = context

    return routed_payload


def _query_cache_key(question: str, payload: dict[str, Any], decision: RouteDecision) -> str:
    cache_payload = _apply_intent_hints(_base_pipeline_payload(payload), decision.intent)
    cache_payload["question"] = question
    cache_payload["intent"] = decision.intent
    canonical = json.dumps(cache_payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_RESPONSE_CACHE_LOCK = threading.Lock()
_RESPONSE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_RESPONSE_CACHE_TTL_SECONDS = float(os.environ.get("SYNDICATE_ASK_CACHE_TTL_SECONDS", "600"))
_RESPONSE_CACHE_MAX_ENTRIES = 128


def _read_cached_response(cache_key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _RESPONSE_CACHE_LOCK:
        entry = _RESPONSE_CACHE.get(cache_key)
        if entry is None:
            return None
        stored_at, response = entry
        if now - stored_at > _RESPONSE_CACHE_TTL_SECONDS:
            _RESPONSE_CACHE.pop(cache_key, None)
            return None
        return response


def _store_cached_response(cache_key: str, response: dict[str, Any]) -> None:
    now = time.monotonic()
    with _RESPONSE_CACHE_LOCK:
        if len(_RESPONSE_CACHE) >= _RESPONSE_CACHE_MAX_ENTRIES:
            oldest_key = min(_RESPONSE_CACHE, key=lambda key: _RESPONSE_CACHE[key][0])
            _RESPONSE_CACHE.pop(oldest_key, None)
        _RESPONSE_CACHE[cache_key] = (now, response)


def _apply_intent_hints(pipeline_payload: dict[str, Any], intent: str) -> dict[str, Any]:
    enriched_payload = dict(pipeline_payload)
    if intent == "bet_analysis":
        enriched_payload.setdefault("mode", "pregame")
        enriched_payload.setdefault("include_props", True)
        enriched_payload.setdefault("include_games", True)
    elif intent in {"matchup_analysis", "comparison"}:
        enriched_payload.setdefault("mode", "comparison")
        enriched_payload.setdefault("include_games", True)
        enriched_payload.setdefault("include_props", True)
    elif intent == "market_summary":
        enriched_payload.setdefault("mode", "pregame")
    return enriched_payload


def _build_route_payload(payload: dict[str, Any], decision: RouteDecision) -> dict[str, Any]:
    pipeline_payload = _apply_intent_hints(payload, decision.intent)
    cached_result = read_latest_intelligence_state(pipeline_payload)
    result = cached_result if isinstance(cached_result, dict) and cached_result else _empty_ask_result(payload, decision, reason="snapshot_missing")
    return build_syndicate_query_response(
        question=str(payload.get("original_question") or payload.get("question") or "").strip(),
        context=_coerce_context(payload),
        decision=decision,
        result=result,
    )


def _apply_briefing_to_response(response: dict[str, Any], briefing_payload: dict[str, Any]) -> None:
    briefing = briefing_payload.get("briefing")
    if not isinstance(briefing, dict):
        return
    response["briefing"] = briefing
    response["answer_source"] = "llm"
    response["llm"] = {
        "model": briefing_payload.get("model"),
        "usage": briefing_payload.get("usage"),
    }

    # Surface the synthesized narrative through the fields the UI already renders.
    schema = response.get("schema")
    if not isinstance(schema, dict):
        return
    verdict = str(briefing.get("verdict") or briefing.get("headline") or "").strip()
    narrative = str(briefing.get("narrative") or "").strip()
    risks = [str(item) for item in briefing.get("risks") or [] if str(item).strip()]

    schema_type = schema.get("schema_type")
    if schema_type == "bet_analysis":
        if verdict:
            schema["recommendation"] = verdict
        explanation = schema.get("explanation")
        if isinstance(explanation, dict) and narrative:
            explanation["summary"] = narrative
    elif schema_type == "matchup_analysis":
        simulation_summary = schema.get("simulation_summary")
        if isinstance(simulation_summary, dict) and narrative:
            simulation_summary["summary"] = narrative
        market_insight = schema.get("market_insight")
        if isinstance(market_insight, dict) and verdict:
            market_insight["summary"] = verdict
        if risks:
            schema["hidden_factors"] = [{"factor": risk} for risk in risks]
    elif schema_type == "market_summary":
        rationale_summary = schema.get("rationale_summary")
        if isinstance(rationale_summary, dict) and narrative:
            rationale_summary["summary"] = narrative


def handle_bet_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


def handle_matchup_analysis(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


def handle_market_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = _QUERY_ROUTER.route(str(payload.get("question") or ""))
    return _build_route_payload(payload, decision)


_OUT_OF_SCOPE_CAPABILITIES: tuple[str, ...] = (
    "tonight's board and the edges on it",
    "a specific game, matchup or player prop",
    "what the model projects and how confident it is",
    "how the model has performed historically",
)

_OUT_OF_SCOPE_REASONS: dict[str, str] = {
    "personal_records": (
        "This is a board analytics surface with no user accounts, so there are "
        "no personal balances, wagers or history to look up."
    ),
    "no_domain_vocabulary": (
        "That question is outside what this surface covers -- it answers "
        "questions about the betting board, its games and its models."
    ),
}


def _out_of_scope_response(question: str, decision: RouteDecision) -> dict[str, Any]:
    """A decline that says WHY and WHAT IT CAN do instead.

    Returned before the snapshot read, so a declined question does no work --
    measured 2026-08-14, "What is the capital of France?" took 10.9 s to return
    five irrelevant betting opportunities.

    Shape deliberately mirrors the answering path (`ok`, `surface`, `intent`,
    `routing`, `structured_response`) so an existing consumer parses it without
    a new branch, and `top_opportunities` is an EMPTY LIST rather than absent --
    a caller that iterates it gets nothing, which is the intent, instead of a
    KeyError.

    `answered: false` is the discriminating field. It exists because a caller
    cannot otherwise distinguish "declined" from "answered with nothing found",
    and those have different meanings to a user and different fixes for us.
    """
    reason_key = decision.matched_terms[0] if decision.matched_terms else "no_domain_vocabulary"
    reason = _OUT_OF_SCOPE_REASONS.get(reason_key, _OUT_OF_SCOPE_REASONS["no_domain_vocabulary"])
    return {
        "ok": True,
        "answered": False,
        "surface": "syndicate",
        "question": question,
        "intent": decision.intent,
        "routing": {
            "handler": decision.handler_name,
            "matched_terms": list(decision.matched_terms),
            "score": decision.score,
        },
        "query_type": decision.intent,
        "schema_type": "out_of_scope",
        "structured_response": {
            "schema_type": "out_of_scope",
            "relevance_matched": False,
            "top_opportunities": [],
            "rationale_summary": {
                "summary": reason,
                "board_notes": [],
                "analysis_brief": {},
                "supporting_evidence": {},
            },
        },
        "declined_reason": reason,
        "can_answer": list(_OUT_OF_SCOPE_CAPABILITIES),
    }


@ask_the_syndicate_bp.route("/api/syndicate/query", methods=["POST", "OPTIONS"])
def ask_the_syndicate_query_api():
    if request.method == "OPTIONS":
        return _with_cors_headers(jsonify({"ok": True}))

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _with_cors_headers(jsonify({"ok": False, "error": "Request body must be a JSON object."})), 400

    question = str(payload.get("question") or "").strip()
    if not question:
        return _with_cors_headers(jsonify({"ok": False, "error": "question is required."})), 400

    shaped_payload = _smart_route_payload(payload)
    # shaped_payload already has the request's context (selection/
    # candidate_id/market/etc.) flattened into it by _smart_route_payload,
    # so it doubles as the context source for the per-pick routing fallback
    # in SyndicateQueryRouter.route -- see that function's own comment.
    decision = _QUERY_ROUTER.route(str(shaped_payload.get("question") or question), context=shaped_payload)

    if decision.intent == "out_of_scope":
        return _with_cors_headers(jsonify(_out_of_scope_response(question, decision)))

    cache_key = _query_cache_key(question, payload, decision)
    cached_response = _read_cached_response(cache_key)
    if isinstance(cached_response, dict):
        return _with_cors_headers(jsonify(cached_response))

    artifact_response = _build_artifact_response(shaped_payload, decision)
    if isinstance(artifact_response, dict):
        return _with_cors_headers(jsonify(artifact_response))

    snapshot = read_latest_intelligence_state(shaped_payload)
    has_snapshot = isinstance(snapshot, dict) and bool(snapshot)
    result = snapshot if has_snapshot else _empty_ask_result(shaped_payload, decision, reason="snapshot_missing")
    response = build_syndicate_query_response(
        question=str(shaped_payload.get("original_question") or shaped_payload.get("question") or "").strip(),
        context=_coerce_context(shaped_payload),
        decision=decision,
        result=result,
    )

    response["answer_source"] = "snapshot"

    # `K5`. What the router ASSUMED, surfaced. This was `None` on 52 of 52
    # regression questions, so neither a user nor the regression harness could
    # see which sport an answer had been scoped to -- which made every routing
    # bug invisible from the outside, including `wnba` resolving to `nba`.
    # Reported as `None` when nothing matched rather than omitted, because
    # "the router picked no sport" is itself the answer to why a cross-sport
    # answer came back.
    #
    # WRITTEN IN THREE PLACES ON PURPOSE, and the two nested ones are the ones
    # that matter. `context` and `routing_context` were served as `{}` on every
    # answer, and they are where a consumer already looks for the routed sport
    # -- `scripts/ask_syndicate_regression.py` reads exactly
    # `context.sport` / `routing_context.sport`, so a top-level key alone
    # would have left the field as invisible as it was before. Existing keys
    # are preserved rather than overwritten: this fills a blank, it does not
    # claim ownership of those dicts.
    _routed_sport = str(shaped_payload.get("sport") or "").strip().lower() or None
    response["routed_sport"] = _routed_sport
    for _key in ("context", "routing_context"):
        _existing = response.get(_key)
        _block = dict(_existing) if isinstance(_existing, dict) else {}
        if _routed_sport and not _block.get("sport"):
            _block["sport"] = _routed_sport
        response[_key] = _block

    # Question-specific sim evidence (tables/charts) is deterministic and
    # renders even when the LLM path is unavailable.
    request_context = dict(shaped_payload)
    request_context.update(_coerce_context(shaped_payload))
    focused_evidence = collect_focused_evidence(question, request_context)

    # `K6`. AN AS-OF ON EVERY ANSWER, not only the ones a sport branch matched.
    #
    # `visuals` used to be written ONLY inside `if isinstance(focused_evidence,
    # dict)`, so an answer with no matching fetcher carried no timestamp of any
    # kind -- 41 of 52 measured answers. On a product whose entire subject is
    # live odds, an answer that does not say how old it is is not a safe
    # answer, and it is exactly the unrouted questions (the ones with no
    # evidence) where a user has least other signal about staleness.
    #
    # The as-of is sourced from the snapshot's own freshness block, so it
    # describes THE DATA THE ANSWER WAS BUILT FROM rather than the moment the
    # request was served -- a served-at stamp on a 2-hour-old snapshot would be
    # actively misleading. Evidence `as_of` wins when present because it is more
    # specific. If nothing exists the key stays None: an absent timestamp is
    # honest, a fabricated one is not.
    #
    # THREE BLOCK NAMES, NOT ONE, AND THAT IS THE WHOLE BUG THIS FIXES.
    # The first version read only `freshness` and was INERT IN PRODUCTION while
    # passing locally, because `read_latest_intelligence_state` has four return
    # paths whose payload SHAPES differ:
    #   - the combined-board path (`read_combined_intelligence_response`) carries
    #     **`state_meta` and NO `freshness` key at all** -- measured, its
    #     `state_meta.computed_at` was a valid `2026-08-15T18:36:33Z`;
    #   - the board_snapshot / state paths carry `freshness` at top level.
    # Production runs the combined path (`SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE`
    # and `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT` are both `true` on web,
    # despite the comment at that call site claiming the flag is "default off, so
    # this is a no-op today"). This box takes the other path, so a local test
    # CANNOT reproduce it -- `as_of` was correct locally and None on production
    # for 24 of 52 questions.
    #
    # The key order matches `pipeline/intelligence_state.py`'s own scan
    # (`for key in ("state_meta", "freshness", "state_freshness")`) so the two
    # readers cannot disagree about which block wins.
    _snapshot_as_of = None
    for _container in (response, result if isinstance(result, dict) else None):
        if not isinstance(_container, dict):
            continue
        for _key in ("state_meta", "freshness", "state_freshness"):
            _source = _container.get(_key)
            if isinstance(_source, dict):
                _snapshot_as_of = _source.get("computed_at") or _source.get("as_of")
                if _snapshot_as_of:
                    break
        if _snapshot_as_of:
            break

    _evidence = focused_evidence if isinstance(focused_evidence, dict) else {}
    response["visuals"] = {
        "tables": _evidence.get("tables") or [],
        "charts": _evidence.get("charts") or [],
        "as_of": _evidence.get("as_of") or _snapshot_as_of or None,
        "sport": _evidence.get("sport") or _routed_sport,
    }
    response["as_of"] = response["visuals"]["as_of"]

    if has_snapshot:
        briefing_payload = generate_briefing(
            question=question,
            context=_coerce_context(shaped_payload),
            intent=decision.intent,
            snapshot=result,
            focused_evidence=focused_evidence,
        )
        if isinstance(briefing_payload, dict):
            _apply_briefing_to_response(response, briefing_payload)

    # Only LLM answers are worth caching -- snapshot shaping is cheap, and
    # caching it would serve stale boards for no cost savings.
    if response.get("answer_source") == "llm":
        _store_cached_response(cache_key, response)
    return _with_cors_headers(jsonify(response))