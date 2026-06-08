from __future__ import annotations

"""Modular wrapper around the intelligence feature module.

The underlying intelligence implementation in syndicate.features.intelligence
is treated as a black box.

Documented black-box contract:
- run_intelligence_query(question, *, selected_date=None, mode=None, sport=None,
  limit=None, timing=None, include_props=None, include_games=None,
  force_refresh=False) -> dict[str, Any]
  Returns a response dict with keys such as selected_date, preferences,
  headline, summary, parsed_request, recommendations, parlays,
  analysis_views, analysis_brief, supporting_evidence, board_notes,
  readiness_gate, and local_only.
- build_intelligence_status(selected_date=None, force_refresh=False) -> dict[str, Any]
  Returns a status dict with keys such as selected_date, sports,
  tracked_summary, advanced_summary, readiness_gate, and local_only.

This module wraps the query path in four explicit stages and returns a
typed IntelligenceResult object:
1. input normalization
2. context enrichment placeholder
3. black-box intelligence call
4. post-processing
"""

import json
import logging
import re
import time
import traceback
from dataclasses import dataclass
from dataclasses import replace
from typing import Any, Mapping

from pipeline.evidence_builder import attach_evidence
from pipeline.intelligence_models import IntelligenceResult
from router.query_router import QueryRouter
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle


logger = logging.getLogger(__name__)
_QUERY_ROUTER = QueryRouter()

_VAGUE_PROMPT_PATTERNS = (
    re.compile(r"\bbest\b", re.IGNORECASE),
    re.compile(r"\bgood\b", re.IGNORECASE),
    re.compile(r"\bvalue\b", re.IGNORECASE),
    re.compile(r"\brecommend(?:ation|ations)?\b", re.IGNORECASE),
    re.compile(r"\bthoughts?\b", re.IGNORECASE),
    re.compile(r"\badvice\b", re.IGNORECASE),
    re.compile(r"\bhelp\b", re.IGNORECASE),
    re.compile(r"\bwhat do you think\b", re.IGNORECASE),
    re.compile(r"\bwhat should i\b", re.IGNORECASE),
    re.compile(r"\bwhat's good\b", re.IGNORECASE),
)

_SPORT_CONTEXT_PATTERNS = (
    re.compile(r"\bmlb\b|\bbaseball\b", re.IGNORECASE),
    re.compile(r"\bnba\b|\bbasketball\b", re.IGNORECASE),
    re.compile(r"\bwnba\b", re.IGNORECASE),
    re.compile(r"\bnhl\b|\bhockey\b", re.IGNORECASE),
    re.compile(r"\bnfl\b|\bfootball\b", re.IGNORECASE),
    re.compile(r"\bncaaf\b|\bcollege football\b|\bcfb\b", re.IGNORECASE),
    re.compile(r"\bncaab\b|\bcollege basketball\b|\bcbb\b", re.IGNORECASE),
)

_MARKET_CONTEXT_PATTERNS = (
    re.compile(r"\bpoints?\b", re.IGNORECASE),
    re.compile(r"\brebounds?\b", re.IGNORECASE),
    re.compile(r"\bassists?\b", re.IGNORECASE),
    re.compile(r"\bthrees?\b", re.IGNORECASE),
    re.compile(r"\bhome runs?\b|\bhr\b", re.IGNORECASE),
    re.compile(r"\bstrikeouts?\b|\bks\b", re.IGNORECASE),
    re.compile(r"\btotal bases?\b", re.IGNORECASE),
    re.compile(r"\bmoneyline\b|\bspread\b|\btotal\b", re.IGNORECASE),
    re.compile(r"\bshots?\b|\bgoals?\b|\bsaves?\b", re.IGNORECASE),
)


def _pipeline_mode_for_query_type(query_type: str | None) -> str | None:
    return {
        "player_analysis": "pregame",
        "game_preview": "pregame",
        "live_analysis": "live",
        "comparison": "comparison",
        "trend_analysis": "trend",
        "risk_evaluation": "explanation",
        "explanation": "explanation",
    }.get(str(query_type or "").strip() or None)


def _log_json_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, sort_keys=True, default=str))


def _time_stage(stage_name: str, callback, *args, **kwargs):
    started_at = time.perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
        _log_json_event("pipeline_stage_timing", stage=stage_name, duration_ms=elapsed_ms)


@dataclass(frozen=True)
class IntelligencePipelineRequest:
    question: str
    selected_date: str | None = None
    query_type: str | None = None
    mode: str | None = None
    preview_subject: str | None = None
    player_subject: str | None = None
    sport: str | None = None
    limit: int | None = None
    timing: str | None = None
    include_props: bool | None = None
    include_games: bool | None = None
    force_refresh: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "selected_date": self.selected_date,
            "query_type": self.query_type,
            "mode": self.mode,
            "preview_subject": self.preview_subject,
            "player_subject": self.player_subject,
            "sport": self.sport,
            "limit": self.limit,
            "timing": self.timing,
            "include_props": self.include_props,
            "include_games": self.include_games,
            "force_refresh": self.force_refresh,
        }


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _optional_int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def _payload_from_request(request_or_payload: Any) -> dict[str, Any]:
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


def _normalize_request(request_or_payload: Any) -> IntelligencePipelineRequest:
    payload = _payload_from_request(request_or_payload)
    question = str(payload.get("question") or getattr(request_or_payload, "question", "") or "").strip()
    routed = _QUERY_ROUTER.route_question(question) if question else None
    query_type = str(payload.get("query_type") or "").strip() or (routed.query_type if routed is not None else None)
    mode = str(payload.get("mode") or "").strip() or (routed.pipeline_mode if routed is not None else _pipeline_mode_for_query_type(query_type))
    return IntelligencePipelineRequest(
        question=question,
        selected_date=str(payload.get("date") or payload.get("selected_date") or "").strip() or (routed.selected_date if routed is not None else None),
        query_type=query_type,
        mode=mode,
        preview_subject=str(payload.get("preview_subject") or "").strip() or (routed.preview_subject if routed is not None else None),
        player_subject=str(payload.get("player_subject") or "").strip() or (routed.player_subject if routed is not None else None),
        sport=str(payload.get("sport") or "").strip() or None,
        limit=_optional_int(payload.get("limit")),
        timing=str(payload.get("timing") or "").strip() or None,
        include_props=_optional_bool(payload.get("include_props")),
        include_games=_optional_bool(payload.get("include_games")),
        force_refresh=_optional_bool(payload.get("force_refresh")) if payload.get("force_refresh") is not None else True,
    )


def _enrich_context(normalized_request: IntelligencePipelineRequest) -> dict[str, Any]:
    return {
        "enriched": False,
        "notes": ["context enrichment placeholder"],
        "selected_date": normalized_request.selected_date,
        "query_type": normalized_request.query_type,
        "preview_subject": normalized_request.preview_subject,
        "player_subject": normalized_request.player_subject,
        "sport": normalized_request.sport,
        "mode": normalized_request.mode,
        "timing": normalized_request.timing,
    }


def _build_structured_response(result: IntelligenceResult, context: dict[str, Any]) -> dict[str, Any]:
    recommendations = [item.to_dict() for item in result.recommendations[:3]]
    top_recommendation = recommendations[0] if recommendations else {}
    engine_structured_response = result.structured_response if isinstance(result.structured_response, dict) else {}
    context_awareness = _build_context_awareness(result, context, recommendations, result.reasoning_steps)
    evidence_sections: list[dict[str, Any]] = []
    if result.analysis_brief is not None:
        evidence_sections.append(result.analysis_brief.to_dict())
    if result.supporting_evidence is not None:
        evidence_sections.append(result.supporting_evidence.to_dict())
    if result.evidence:
        evidence_sections.append(
            {
                "kind": "bundle",
                "title": "Evidence records",
                "sections": [item.to_dict() for item in result.evidence[:6]],
            }
        )

    risks: list[str] = []
    if result.board_notes:
        risks.extend(note for note in result.board_notes if note)
    readiness_gate = result.readiness_gate or {}
    if readiness_gate and not bool(readiness_gate.get("ok", True)):
        status_text = str(readiness_gate.get("status") or "not ready").strip() or "not ready"
        risks.append(f"Readiness gate status: {status_text}.")
    if result.local_only:
        risks.append("This response was generated from local-only data.")
    if context.get("query_type") == "risk_evaluation":
        risks.append("The query was classified as a risk check, so uncertainty and failure modes were prioritized.")

    summary_text = result.summary or result.headline or ""
    interpretation_source = top_recommendation.get("summary") or top_recommendation.get("writeup") or top_recommendation.get("rationale") or top_recommendation.get("name") or "No actionable candidate surfaced."
    if context.get("query_type") == "risk_evaluation":
        recommended_interpretation = f"Treat this as a risk screen: {interpretation_source}"
    else:
        recommended_interpretation = interpretation_source

    clear_summary = summary_text or "No summary was returned, so the board should be read through the returned recommendations and evidence."
    if top_recommendation.get("summary") and top_recommendation.get("summary") not in clear_summary:
        clear_summary = f"{clear_summary.rstrip('.')} {str(top_recommendation.get('summary')).rstrip('.')}."

    evidence_titles = [str(item.get("title") or item.get("kind") or "Evidence").strip() for item in evidence_sections if isinstance(item, dict)]
    deep_analysis: list[str] = []
    if top_recommendation:
        deep_analysis.append(
            f"The strongest current read centers on {top_recommendation.get('name') or top_recommendation.get('pick') or 'the top candidate'}, because {interpretation_source}."
        )
    if evidence_titles:
        joined_titles = ", ".join(evidence_titles[:3])
        deep_analysis.append(
            f"Supporting detail is carried by {joined_titles}, which keeps the response tied to the returned evidence instead of a shallow headline-only answer."
        )
    if risks:
        deep_analysis.append(
            f"The main caution is that {risks[0].rstrip('.')}. That means the recommendation should be interpreted with the listed uncertainty rather than treated as a fixed outcome."
        )
    if result.reasoning_steps:
        step_labels = [str(step.get("step_label") or step.get("step_type") or "step").strip() for step in result.reasoning_steps if isinstance(step, Mapping)]
        if step_labels:
            deep_analysis.append(
                f"The reasoning path is explicit: {' -> '.join(step_labels[:4])}, so the answer shows how the model moved from decomposition to conclusion."
            )
    if not deep_analysis:
        deep_analysis.append("The returned board is being summarized at the candidate, evidence, and risk level so the answer stays actionable rather than superficial.")

    preview_response = None
    if context.get("query_type") == "game_preview":
        preview_response = _build_game_preview_response(result, context)
    player_response = None
    if context.get("query_type") == "player_analysis":
        player_response = _build_player_analysis_response(result, context)

    final_takeaway = (
        f"Best takeaway: {top_recommendation.get('name') or top_recommendation.get('pick') or 'the board'} is the primary angle, but size it against the reported risks and treat the evidence as directional, not absolute."
        if top_recommendation
        else "Best takeaway: use the returned evidence and risks to interpret the board directionally, since no single standout candidate was returned."
    )

    return {
        "intent": context.get("query_type") or result.query_type or "explanation",
        "summary": clear_summary,
        "clear_summary": clear_summary,
        "deep_analysis": deep_analysis,
        "context_awareness": context_awareness,
        "key_insights": [
            {
                "label": item.get("name") or item.get("pick") or f"Recommendation {index + 1}",
                "interpretation": item.get("summary") or item.get("writeup") or item.get("rationale") or item.get("market") or "Recommended by the current board state.",
                "confidence": item.get("confidence"),
                "score": item.get("score"),
            }
            for index, item in enumerate(recommendations)
        ],
        "supporting_evidence": evidence_sections,
        "risks_uncertainty": risks,
        "recommended_interpretation": final_takeaway if final_takeaway else recommended_interpretation,
        "final_takeaway": final_takeaway,
        "reasoning_steps": [dict(step) for step in result.reasoning_steps],
        **engine_structured_response,
        **({"preview": preview_response} if preview_response is not None else {}),
        **({"player_analysis": player_response} if player_response is not None else {}),
    }


def _normalize_preview_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _preview_candidate_score(candidate: Mapping[str, Any], preview_subject: str) -> float:
    score = float(candidate.get("score") or 0.0) / 100.0
    candidate_type = str(candidate.get("candidate_type") or "").strip().lower()
    if candidate_type == "game":
        score += 8.0
    elif candidate_type == "prop":
        score += 3.0
    subject_text = _normalize_preview_text(preview_subject)
    if not subject_text:
        return score

    fields = (
        candidate.get("name"),
        candidate.get("matchup"),
        candidate.get("summary"),
        candidate.get("writeup"),
        candidate.get("rationale"),
        candidate.get("team"),
        candidate.get("team_key"),
        candidate.get("sport"),
        candidate.get("sport_slug"),
        candidate.get("pick"),
        candidate.get("market"),
        candidate.get("surface"),
    )
    for field in fields:
        field_text = _normalize_preview_text(field)
        if not field_text:
            continue
        if field_text == subject_text:
            score += 10.0
        elif subject_text in field_text or field_text in subject_text:
            score += 6.0
    if candidate_type == "game" and subject_text in _normalize_preview_text(candidate.get("matchup")):
        score += 4.0
    if bool(candidate.get("is_live")):
        score += 0.5
    return score


def _preview_related_recommendations(recommendations: list[dict[str, Any]], preview_subject: str, *, candidate_type: str | None = None, matchup: str | None = None) -> list[dict[str, Any]]:
    subject_text = _normalize_preview_text(preview_subject)
    matchup_text = _normalize_preview_text(matchup)
    related: list[dict[str, Any]] = []
    for recommendation in recommendations:
        if not isinstance(recommendation, Mapping):
            continue
        recommendation_type = str(recommendation.get("candidate_type") or "").strip().lower()
        if candidate_type and recommendation_type != candidate_type:
            continue
        if subject_text:
            haystack = " ".join(
                _normalize_preview_text(recommendation.get(field))
                for field in ("name", "matchup", "summary", "writeup", "rationale", "team", "team_key", "sport", "sport_slug", "pick", "market", "surface")
            ).strip()
            if subject_text not in haystack and all(subject_text not in _normalize_preview_text(recommendation.get(field)) for field in ("name", "matchup", "summary", "writeup", "rationale", "team", "team_key", "sport", "sport_slug", "pick", "market", "surface")):
                continue
        if matchup_text:
            haystack = " ".join(_normalize_preview_text(recommendation.get(field)) for field in ("matchup", "name", "summary", "rationale", "writeup"))
            if matchup_text not in haystack:
                continue
        related.append(dict(recommendation))
    return related


def _same_game_parlay_matches(parlay: Mapping[str, Any], matchup: str | None) -> bool:
    if str(parlay.get("parlay_type") or "").strip().lower() == "same_game":
        if not matchup:
            return True
        leg_matchups = {
            _normalize_preview_text(leg.get("matchup"))
            for leg in (parlay.get("legs") or [])
            if isinstance(leg, Mapping)
        }
        return _normalize_preview_text(matchup) in leg_matchups or not leg_matchups
    if not matchup:
        return False
    leg_matchups = {
        _normalize_preview_text(leg.get("matchup"))
        for leg in (parlay.get("legs") or [])
        if isinstance(leg, Mapping)
    }
    return len(leg_matchups) == 1 and _normalize_preview_text(matchup) in leg_matchups


def _build_game_preview_response(result: IntelligenceResult, context: dict[str, Any]) -> dict[str, Any]:
    preview_subject = str(context.get("preview_subject") or result.pipeline_request.get("preview_subject") or "").strip()
    recommendations = [item.to_dict() for item in result.recommendations]
    recommendation_pool = [item for item in recommendations if isinstance(item, Mapping)]
    if not recommendation_pool:
        recommendation_pool = []

    selected_game = None
    game_candidates = [item for item in recommendation_pool if str(item.get("candidate_type") or "").strip().lower() == "game"]
    if game_candidates:
        selected_game = max(game_candidates, key=lambda candidate: _preview_candidate_score(candidate, preview_subject))
    elif recommendation_pool:
        selected_game = max(recommendation_pool, key=lambda candidate: _preview_candidate_score(candidate, preview_subject))

    matchup = str((selected_game or {}).get("matchup") or (selected_game or {}).get("name") or "").strip()
    game_recommendations = _preview_related_recommendations(recommendation_pool, preview_subject, candidate_type="game", matchup=matchup)
    prop_recommendations = _preview_related_recommendations(recommendation_pool, preview_subject, candidate_type="prop", matchup=matchup)
    if selected_game:
        selected_game_copy = dict(selected_game)
        if all(not isinstance(item, Mapping) or dict(item) != selected_game_copy for item in game_recommendations):
            game_recommendations = [selected_game_copy, *game_recommendations]
    if not prop_recommendations:
        prop_recommendations = [
            dict(candidate)
            for candidate in sorted(
                [item for item in recommendation_pool if str(item.get("candidate_type") or "").strip().lower() == "prop"],
                key=lambda candidate: _preview_candidate_score(candidate, preview_subject),
                reverse=True,
            )[:4]
        ]
    top_selected_single_plays = sorted(
        [dict(item) for item in recommendation_pool],
        key=lambda candidate: _preview_candidate_score(candidate, preview_subject),
        reverse=True,
    )[:5]

    same_game_parlays = [
        dict(parlay)
        for parlay in (result.parlays or ())
        if isinstance(parlay, Mapping) and _same_game_parlay_matches(parlay, matchup)
    ][:3]

    risks: list[str] = []
    if matchup:
        risks.append(f"The preview is anchored to {matchup}, so any late injury or lineup change on that game can shift the read quickly.")
    elif preview_subject:
        risks.append(f"The preview is anchored to {preview_subject}, but the current board did not return a single clear matchup match.")
    if result.board_notes:
        risks.extend(note for note in result.board_notes if note)
    readiness_gate = result.readiness_gate or {}
    if readiness_gate and not bool(readiness_gate.get("ok", True)):
        risks.append(f"Readiness gate status: {str(readiness_gate.get('status') or 'not ready').strip() or 'not ready' }.")
    if result.local_only:
        risks.append("This preview was built from local-only intelligence artifacts.")

    watch_items = [
        f"Check the starting lineup, goalie, or probable starters for {matchup or preview_subject or 'the selected game'} before lock.",
        "Watch the total and side movement for the selected game in case the market reprices late.",
        "Re-check the top correlated props if you plan to build a same-game parlay.",
    ]
    if readiness_gate and not bool(readiness_gate.get("ok", True)):
        watch_items.append("Confirm the readiness gate has no blocked inputs before sizing the play.")

    matchup_preview = {
        "subject": preview_subject or None,
        "matchup": matchup or None,
        "sport": (selected_game or {}).get("sport"),
        "summary": (selected_game or {}).get("summary") or (selected_game or {}).get("rationale") or (selected_game or {}).get("writeup") or result.summary or result.headline,
        "selected_game": selected_game,
        "game_recommendations": game_recommendations[:3],
        "prop_recommendations": prop_recommendations[:3],
    }

    return {
        "subject": preview_subject or None,
        "matchup": matchup or None,
        "matchup_preview": matchup_preview,
        "game_recommendation_recap": {
            "summary": (selected_game or {}).get("summary") or "Top game recommendation recap built from the current board.",
            "plays": game_recommendations[:3],
        },
        "prop_recommendation_recap": {
            "summary": (prop_recommendations[0] if prop_recommendations else {}).get("summary") or (prop_recommendations[0] if prop_recommendations else {}).get("rationale") or "Top prop recommendation recap built from the current board.",
            "plays": prop_recommendations[:4],
        },
        "top_selected_single_plays": top_selected_single_plays,
        "top_same_game_parlays": same_game_parlays,
        "risks_uncertainty": risks,
        "what_to_watch_before_lock": watch_items,
    }


def _build_player_analysis_response(result: IntelligenceResult, context: dict[str, Any]) -> dict[str, Any]:
    player_subject = str(context.get("player_subject") or result.pipeline_request.get("player_subject") or "").strip()
    recommendations = [item.to_dict() for item in result.recommendations]
    recommendation_pool = [item for item in recommendations if isinstance(item, Mapping)]
    sorted_recommendations = sorted(
        [dict(item) for item in recommendation_pool],
        key=lambda candidate: _preview_candidate_score(candidate, player_subject),
        reverse=True,
    )

    subject_text = _normalize_preview_text(player_subject)
    player_props = [
        item
        for item in sorted_recommendations
        if str(item.get("candidate_type") or "").strip().lower() == "prop"
        and subject_text
        and subject_text in " ".join(
            _normalize_preview_text(item.get(field))
            for field in ("name", "matchup", "summary", "writeup", "rationale", "team", "team_key", "pick", "market")
        )
    ]
    selected_prop = player_props[0] if player_props else (sorted_recommendations[0] if sorted_recommendations else None)
    matchup = str((selected_prop or {}).get("matchup") or "").strip()

    game_candidates = [item for item in sorted_recommendations if str(item.get("candidate_type") or "").strip().lower() == "game"]
    selected_game = None
    if matchup and game_candidates:
        matching_games = [item for item in game_candidates if _normalize_preview_text(item.get("matchup")) == _normalize_preview_text(matchup)]
        selected_game = matching_games[0] if matching_games else max(game_candidates, key=lambda candidate: _preview_candidate_score(candidate, player_subject))
    elif game_candidates:
        selected_game = max(game_candidates, key=lambda candidate: _preview_candidate_score(candidate, player_subject))

    game_recommendations = _preview_related_recommendations(sorted_recommendations, player_subject, candidate_type="game", matchup=matchup)
    prop_recommendations = _preview_related_recommendations(sorted_recommendations, player_subject, candidate_type="prop", matchup=matchup)
    if selected_game:
        selected_game_copy = dict(selected_game)
        if all(not isinstance(item, Mapping) or dict(item) != selected_game_copy for item in game_recommendations):
            game_recommendations = [selected_game_copy, *game_recommendations]
    if selected_prop and all(not isinstance(item, Mapping) or dict(item) != dict(selected_prop) for item in prop_recommendations):
        prop_recommendations = [dict(selected_prop), *prop_recommendations]

    same_game_parlays = [
        dict(parlay)
        for parlay in (result.parlays or ())
        if isinstance(parlay, Mapping) and _same_game_parlay_matches(parlay, matchup)
    ][:3]

    risks: list[str] = []
    if player_subject:
        risks.append(f"The analysis is anchored to {player_subject}, so lineup, usage, or foul trouble changes can move the read quickly.")
    if matchup:
        risks.append(f"The relevant game is {matchup}, and any market move there can change both the prop and the side view.")
    if result.board_notes:
        risks.extend(note for note in result.board_notes if note)
    readiness_gate = result.readiness_gate or {}
    if readiness_gate and not bool(readiness_gate.get("ok", True)):
        status_text = str(readiness_gate.get("status") or "not ready").strip() or "not ready"
        risks.append(f"Readiness gate status: {status_text}.")
    if result.local_only:
        risks.append("This player read was built from local-only intelligence artifacts.")

    final_recommendation_source = selected_prop or selected_game or (sorted_recommendations[0] if sorted_recommendations else {})
    final_recommendation = final_recommendation_source.get("summary") or final_recommendation_source.get("rationale") or final_recommendation_source.get("writeup") or final_recommendation_source.get("name") or "No clear player edge surfaced."

    return {
        "player": player_subject or None,
        "matchup": matchup or None,
        "player_outlook": {
            "summary": final_recommendation_source.get("summary") or final_recommendation_source.get("rationale") or final_recommendation_source.get("writeup") or "Top player outlook built from the current board.",
            "selected_player_play": selected_prop,
            "selected_game": selected_game,
        },
        "matchup_analysis": {
            "summary": (selected_game or {}).get("summary") or (selected_game or {}).get("rationale") or "Matchup analysis built from the current board.",
            "plays": game_recommendations[:3],
        },
        "prop_recap": {
            "summary": (selected_prop or {}).get("summary") or (selected_prop or {}).get("rationale") or (selected_prop or {}).get("writeup") or "Top prop recap built from the current board.",
            "plays": prop_recommendations[:4],
        },
        "top_single_plays": sorted_recommendations[:5],
        "same_game_parlays": same_game_parlays,
        "risks": risks,
        "final_recommendation": final_recommendation,
    }


def _strip_for_reasoning(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text


def _matches_any(patterns: tuple[re.Pattern[str], ...], value: str) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def _build_context_awareness(result: IntelligenceResult, context: dict[str, Any], recommendations: list[dict[str, Any]], reasoning_steps: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    pipeline_request = result.pipeline_request if isinstance(result.pipeline_request, Mapping) else {}
    question = str(pipeline_request.get("question") or "").strip()
    sport = str(pipeline_request.get("sport") or "").strip()
    mode = str(pipeline_request.get("mode") or "").strip()
    query_type = str(context.get("query_type") or result.query_type or "explanation").strip() or "explanation"

    has_sport = bool(sport) or _matches_any(_SPORT_CONTEXT_PATTERNS, question)
    has_market = _matches_any(_MARKET_CONTEXT_PATTERNS, question)
    vague_prompt = _matches_any(_VAGUE_PROMPT_PATTERNS, f" {question.lower()} ")
    vague = not has_sport or not has_market or vague_prompt
    if len(question.split()) >= 10 and (has_sport or has_market):
        vague = False
    if query_type == "comparison" and " vs " in f" {question.lower()} ":
        vague = False

    assumptions: list[str] = []
    clarifying_questions: list[str] = []
    if vague:
        assumptions.append("I assumed you want the strongest board-wide read because no specific sport or market was named.")
        assumptions.append(f"I treated the request as a {query_type.replace('_', ' ')} prompt so the engine could answer instead of waiting for more input.")
        if not has_sport:
            clarifying_questions.append("Which sport should I narrow this to?")
        if not has_market:
            clarifying_questions.append("Do you want props, game plays, or both?")
        if mode not in {"live", "pregame"}:
            clarifying_questions.append("Should I focus on live, pregame, or both?")
        if not clarifying_questions:
            clarifying_questions.append("If you want a narrower answer, tell me the sport, market, and timing window.")
    else:
        assumptions.append("I used the explicit sport and market signals in the question to keep the answer focused.")

    if query_type == "risk_evaluation":
        reasoning = "The request was handled as a risk-first question because the wording centered on uncertainty and downside."
    elif query_type == "comparison":
        reasoning = "The request was handled as a comparison because it asked for relative evaluation or side-by-side judgment."
    elif query_type == "trend_analysis":
        reasoning = "The request was handled as a trend question because it asked for recent direction, form, or rolling behavior."
    elif query_type == "live_analysis":
        reasoning = "The request was handled as a live question because it used live-state language or in-game timing cues."
    else:
        reasoning = "The request was handled as a general explanation because the prompt did not pin down a narrower market frame."

    if vague:
        reasoning = f"{reasoning} Because the prompt was vague, the pipeline also made best-effort assumptions and preserved clarifying questions for follow-up."

    confidence = "low" if vague else "medium" if not has_sport or not has_market else "high"
    return {
        "is_vague": vague,
        "confidence": confidence,
        "detected_signals": [signal for signal in [f"sport={sport}" if sport else "", f"mode={mode}" if mode else "", f"intent={query_type}" if query_type else "", "market-signal" if has_market else ""] if signal],
        "assumptions": assumptions,
        "clarifying_questions": clarifying_questions,
        "reasoning": reasoning,
        "recommendation_count": len(recommendations),
        "reasoning_step_count": len(reasoning_steps),
    }


def _decompose_reasoning_steps(normalized_request: IntelligencePipelineRequest) -> tuple[dict[str, Any], ...]:
    question = normalized_request.question
    query_type = str(normalized_request.query_type or "explanation").strip() or "explanation"
    normalized_question = question.lower()
    compound_markers = (
        ";",
        " compare ",
        " versus ",
        " vs ",
        " difference between ",
        " break down ",
        " step by step ",
        " first ",
        " second ",
        " and then ",
    )
    is_compound = len(question) > 120 or any(marker in f" {normalized_question} " for marker in compound_markers)
    steps: list[dict[str, Any]] = []

    def add_step(step_type: str, step_label: str, question_text: str) -> None:
        text = _strip_for_reasoning(question_text)
        if text:
            steps.append({
                "step_type": step_type,
                "step_label": step_label,
                "question": text,
            })

    if not is_compound:
        add_step("reasoning", "Direct answer", f"Answer the question directly and keep the explanation concise for: {question}")
        return tuple(steps)

    if query_type == "comparison":
        add_step("decompose", "Question frame", f"Identify the entities, markets, and comparison criteria in: {question}")
        add_step("analyze", "Compare sides", f"Compare the candidates or options in: {question}")
        add_step("aggregate", "Final comparison", f"Synthesize the better side and explain the deciding factors for: {question}")
    elif query_type == "trend_analysis":
        add_step("decompose", "Trend frame", f"Break down the recent trend drivers in: {question}")
        add_step("analyze", "Trend evidence", f"Assess the recent trend direction, sample, and stability for: {question}")
        add_step("aggregate", "Trend conclusion", f"Summarize the trend and what it means for the user question: {question}")
    elif query_type == "risk_evaluation":
        add_step("decompose", "Risk frame", f"Identify the main downside and uncertainty factors in: {question}")
        add_step("analyze", "Risk checks", f"Assess what could break the primary read for: {question}")
        add_step("aggregate", "Risk conclusion", f"Summarize the key risks and the safest interpretation for: {question}")
    elif query_type == "live_analysis":
        add_step("decompose", "Live frame", f"Identify live-state drivers and the current board context in: {question}")
        add_step("analyze", "Live pressure", f"Assess current live momentum, projection, and board pressure for: {question}")
        add_step("aggregate", "Live conclusion", f"Summarize the strongest live angle for: {question}")
    else:
        add_step("decompose", "Explanation frame", f"Identify the main subject, market, and explanation targets in: {question}")
        add_step("analyze", "Explanation evidence", f"Break down the evidence and reasoning behind: {question}")
        add_step("aggregate", "Final explanation", f"Summarize the best interpretation and recommendation for: {question}")

    return tuple(steps)


def _merge_reasoning_steps(*step_groups: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in step_groups:
        for step in group:
            if not isinstance(step, Mapping):
                continue
            key = (str(step.get("step_type") or "").strip(), str(step.get("question") or "").strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(dict(step))
    return tuple(merged)


def _dedupe_evidence_records(*groups: tuple[Any, ...]) -> tuple[Any, ...]:
    deduped: list[Any] = []
    seen: set[tuple[Any, ...]] = set()
    for group in groups:
        for item in group:
            if not isinstance(item, object):
                continue
            signature = (
                getattr(item, "source_type", None),
                getattr(item, "entity", None),
                getattr(item, "metric", None),
                getattr(item, "value", None),
                getattr(item, "context", None),
                getattr(item, "timestamp", None),
                getattr(item, "kind", None),
                getattr(item, "title", None),
                getattr(item, "label", None),
            )
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(item)
    return tuple(deduped)


def _summarize_step_result(step_question: str, step_result: IntelligenceResult) -> dict[str, Any]:
    recommendations = [item.to_dict() for item in step_result.recommendations[:2]]
    top_recommendation = recommendations[0] if recommendations else {}
    summary = step_result.summary or step_result.headline or ""
    explanation = top_recommendation.get("summary") or top_recommendation.get("writeup") or top_recommendation.get("rationale") or summary
    return {
        "question": step_question,
        "summary": summary,
        "answer": explanation,
        "top_recommendation": top_recommendation,
        "evidence": [item.to_dict() for item in step_result.evidence[:3]],
        "recommendations": recommendations,
        "board_notes": list(step_result.board_notes),
    }


def _run_reasoning_steps(normalized_request: IntelligencePipelineRequest) -> tuple[dict[str, Any], tuple[Evidence, ...]]:
    step_defs = _decompose_reasoning_steps(normalized_request)
    if len(step_defs) <= 1:
        return (), ()

    step_results: list[dict[str, Any]] = []
    step_evidence: list[Evidence] = []
    for index, step_def in enumerate(step_defs):
        step_request = replace(normalized_request, question=step_def["question"])
        raw_step_response = _time_stage(f"reasoning_step_call_{index + 1}", _run_intelligence_query_with_retry, step_request)
        step_result = _time_stage(
            f"reasoning_step_post_processing_{index + 1}",
            IntelligenceResult.from_raw,
            raw_step_response,
            pipeline_request=step_request.to_dict(),
            pipeline_context={"reasoning_step": step_def},
            pipeline_stages=("input_normalization", "context_enrichment", "intelligence_call", "post_processing"),
        )
        step_result = _time_stage("reasoning_step_evidence", attach_evidence, step_result, raw_step_response, selected_date=normalized_request.selected_date)
        summarized = _summarize_step_result(step_def["question"], step_result)
        step_summary = {
            **step_def,
            "summary": summarized["summary"],
            "answer": summarized["answer"],
            "top_recommendation": summarized["top_recommendation"],
            "evidence": summarized["evidence"],
            "recommendations": summarized["recommendations"],
            "board_notes": summarized["board_notes"],
        }
        step_results.append(step_summary)
        step_evidence.extend(step_result.evidence)

    return tuple(step_results), tuple(step_evidence)


def _call_intelligence(normalized_request: IntelligencePipelineRequest, context: dict[str, Any]) -> IntelligenceResult:
    if not normalized_request.question:
        raise ValueError("question is required")
    reasoning_steps, reasoning_step_evidence = _time_stage("reasoning_decomposition", _run_reasoning_steps, normalized_request)
    raw_response = _time_stage("intelligence_call", _run_intelligence_query_with_retry, normalized_request)
    result = _time_stage(
        "post_processing",
        IntelligenceResult.from_raw,
        raw_response,
        pipeline_request=normalized_request.to_dict(),
        pipeline_context=context,
        pipeline_stages=("input_normalization", "context_enrichment", "intelligence_call", "post_processing"),
    )
    result = _time_stage("post_processing_evidence", attach_evidence, result, raw_response, selected_date=normalized_request.selected_date)
    if reasoning_step_evidence:
        result = replace(result, evidence=_dedupe_evidence_records(result.evidence, reasoning_step_evidence))
    structured_response = _time_stage("post_processing_structured_response", _build_structured_response, result, context)
    if reasoning_steps:
        structured_response = {**structured_response, "reasoning_steps": [dict(step) for step in reasoning_steps]}
    result = replace(
        result,
        query_type=normalized_request.query_type or result.query_type,
        structured_response=structured_response,
        reasoning_steps=reasoning_steps,
    )
    if result.recommendations:
        evaluation_record = _time_stage(
            "evaluation_record_build",
            build_intelligence_evaluation_bundle,
            query=result.pipeline_request or normalized_request.to_dict(),
            response=result.to_dict(),
        )
        result = replace(result, evaluation_record=evaluation_record)
    return result


def _call_black_box_intelligence(normalized_request: IntelligencePipelineRequest) -> dict[str, Any]:
    return run_intelligence_query(
        normalized_request.question,
        selected_date=normalized_request.selected_date,
        mode=normalized_request.mode,
        sport=normalized_request.sport,
        limit=normalized_request.limit,
        timing=normalized_request.timing,
        include_props=normalized_request.include_props,
        include_games=normalized_request.include_games,
        force_refresh=bool(normalized_request.force_refresh),
    )


def _build_partial_raw_response(normalized_request: IntelligencePipelineRequest, error: Exception, *, retry_count: int) -> dict[str, Any]:
    error_message = str(error or "").strip() or error.__class__.__name__
    return {
        "headline": "Intelligence temporarily unavailable",
        "summary": "Returning partial results after an upstream failure.",
        "parsed_request": normalized_request.to_dict(),
        "preferences": normalized_request.to_dict(),
        "recommendations": [],
        "parlays": [],
        "analysis_views": {},
        "board_notes": [error_message],
        "readiness_gate": {"ok": False, "status": "partial"},
        "local_only": True,
        "supporting_evidence": {
            "kind": "bundle",
            "title": "Partial results",
            "sections": [
                {
                    "kind": "metrics",
                    "title": "Pipeline failure",
                    "items": [{"label": "error", "value": error_message}],
                }
            ],
        },
        "pipeline_partial": True,
        "pipeline_error": error_message,
        "pipeline_retry_attempted": retry_count > 0,
        "pipeline_retry_count": retry_count,
    }


def _run_intelligence_query_with_retry(normalized_request: IntelligencePipelineRequest) -> dict[str, Any]:
    retry_count = 0
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            if attempt:
                retry_count += 1
            return _call_black_box_intelligence(normalized_request)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt == 0:
                _log_json_event(
                    "pipeline_retry",
                    stage="intelligence_call",
                    retry_count=1,
                    error=str(exc or "").strip() or exc.__class__.__name__,
                    traceback=traceback.format_exc(),
                )
                continue
            _log_json_event(
                "pipeline_error",
                stage="intelligence_call",
                retry_count=1,
                error=str(exc or "").strip() or exc.__class__.__name__,
                traceback=traceback.format_exc(),
            )
            break
    if last_error is None:
        last_error = RuntimeError("intelligence query failed")
    return _build_partial_raw_response(normalized_request, last_error, retry_count=retry_count)


def run_intelligence_pipeline(request_or_payload: Any) -> IntelligenceResult:
    normalized_request = _time_stage("input_normalization", _normalize_request, request_or_payload)
    _log_json_event(
        "pipeline_query_received",
        question=normalized_request.question,
        selected_date=normalized_request.selected_date,
        mode=normalized_request.mode,
        sport=normalized_request.sport,
        limit=normalized_request.limit,
        timing=normalized_request.timing,
    )
    context = _time_stage("context_enrichment", _enrich_context, normalized_request)
    return _call_intelligence(normalized_request, context)
