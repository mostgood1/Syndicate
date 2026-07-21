from __future__ import annotations

import logging
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from flask import Blueprint, jsonify, render_template, request
from flask import redirect

from pipeline.intelligence_state import read_latest_intelligence_board_snapshot_response
from pipeline.intelligence_state import read_latest_intelligence_state_response
from pipeline.intelligence_state import queue_intelligence_state_refresh
from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE
from syndicate.features.intelligence import _market_focus_labels
from syndicate.features.intelligence import _parlay_request_summary
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import _attach_intelligence_response_aliases
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.shared.artifact_manifests import load_artifact_manifests
from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.timezone import normalize_timestamped_payload
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_status
from syndicate.features.portfolio_summary import build_portfolio_summary


intelligence_bp = Blueprint("syndicate_intelligence", __name__)
_LOGGER = logging.getLogger(__name__)

DEFAULT_QUESTION = "top edges today"

LAST_RESULT = {
    "recommendations": [],
    "portfolio": {},
    "parlays": [],
}


def _server_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _log_intelligence_timing(step: str, started_at: float, **fields: Any) -> None:
    payload = {
        "event": step,
        "timestamp": _server_timestamp(),
        "elapsed_ms": round((time.perf_counter() - started_at) * 1000.0, 3),
        **fields,
    }
    print("[INTEL_STATUS_TIMING]", payload, flush=True)


def _log_api_state_read(state: dict[str, object] | None) -> None:
    state = state if isinstance(state, dict) else {}
    print(
        "[API READ]",
        {
            "timestamp": _server_timestamp(),
            "state_last_updated": state.get("last_updated"),
            "candidate_count": len(state.get("candidates", [])),
        },
    )


def _api_error_response(error: Exception):
    print("[API ERROR]", str(error))
    response = jsonify({"error": str(error)})
    response.status_code = 500
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _date_string_from_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except Exception:
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            return text[:10]
    return text


def _latest_available_intelligence_date() -> str:
    latest_date = ""
    intelligence_root = reports_root() / "intelligence"
    for path in (
        intelligence_root / "board_snapshot.json",
        intelligence_root / "intelligence_state.json",
    ):
        if not path.is_file():
            continue
        candidate = ""
        try:
            payload = read_json_file(path)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            candidate = _date_string_from_value(
                payload.get("selected_date")
                or payload.get("date")
                or (payload.get("response") or {}).get("selected_date")
                or (payload.get("response") or {}).get("date")
                or payload.get("updated_at")
                or payload.get("last_updated")
                or payload.get("state_last_updated")
                or ""
            ).strip()
        if not candidate:
            try:
                candidate = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
            except Exception:
                candidate = ""
        if candidate and candidate > latest_date:
            latest_date = candidate

    for pattern in ("board_snapshot_*.json", "intelligence_state_*.json"):
        if not intelligence_root.exists():
            break
        for path in sorted(intelligence_root.glob(pattern), reverse=True):
            if not path.is_file():
                continue
            candidate = ""
            try:
                payload = read_json_file(path)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                candidate = _date_string_from_value(
                    payload.get("selected_date")
                    or payload.get("date")
                    or (payload.get("response") or {}).get("selected_date")
                    or (payload.get("response") or {}).get("date")
                    or payload.get("updated_at")
                    or payload.get("last_updated")
                    or payload.get("state_last_updated")
                    or ""
                ).strip()
            if not candidate:
                stem_parts = path.stem.rsplit("_", 3)
                if len(stem_parts) >= 4:
                    candidate = "-".join(stem_parts[-3:])
            if not candidate:
                try:
                    candidate = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
                except Exception:
                    candidate = ""
            if candidate and candidate > latest_date:
                latest_date = candidate
    try:
        manifests = load_artifact_manifests()
    except Exception:
        manifests = []
    for manifest in manifests:
        for collection_name in ("predictions", "edges", "recommendations", "live_data"):
            collection = getattr(manifest, collection_name, ())
            for artifact in collection or ():
                artifact_date = str(getattr(artifact, "date", "") or "").strip()
                if artifact_date and artifact_date > latest_date:
                    latest_date = artifact_date
    return latest_date or central_today_iso()


def _no_cache_response(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _render_hosted_request() -> bool:
    raw_value = str(os.environ.get("RENDER") or os.environ.get("SYNDICATE_REQUIRE_HOSTED_STORAGE") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _query_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "t", "yes", "y", "on"}


def _response_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _versioned_query_response(response_payload: dict[str, object]) -> dict[str, object]:
    payload_hash = _response_hash(dict(response_payload))
    return {
        "version": payload_hash,
        "timestamp": _server_timestamp(),
        "response_hash": payload_hash,
        "response": response_payload,
    }


def _unwrap_response_payload(payload: dict[str, object] | None) -> dict[str, object]:
    current = dict(payload or {})
    while isinstance(current.get("response"), dict) and (
        "version" in current or "timestamp" in current
    ):
        current = dict(current.get("response") or {})
    return current


def _board_headline_for_question(question: str, response_payload: dict[str, object]) -> str | None:
    headline = str(response_payload.get("headline") or "").strip()
    if headline:
        return headline

    preferences: dict[str, object] = {}
    try:
        preferences = _query_preferences(question)
    except Exception:
        preferences = {}

    intent = str(preferences.get("intent") or response_payload.get("preferences", {}).get("intent") or "").strip().lower()
    if intent == "parlay":
        return "The Syndicate parlay builder"
    if intent == "live_bets":
        return "The Syndicate live board brief"
    if intent == "pregame_bets":
        return "The Syndicate pregame board brief"

    requested_markets = preferences.get("requested_markets") if isinstance(preferences.get("requested_markets"), list) else []
    if requested_markets:
        first_market = str(requested_markets[0] or "").strip().lower()
        if first_market:
            return f"The Syndicate {first_market} board"

    requested_subjects = preferences.get("requested_subjects") if isinstance(preferences.get("requested_subjects"), list) else []
    if bool(preferences.get("comparison_requested")) and len(requested_subjects) >= 2:
        first_subject = " ".join(part.capitalize() for part in str(requested_subjects[0]).split())
        second_subject = " ".join(part.capitalize() for part in str(requested_subjects[1]).split())
        if first_subject and second_subject:
            return f"The Syndicate comparison: {first_subject} vs {second_subject}"

    return "The Syndicate brief"


def _parsed_request_for_question(question: str, payload: dict[str, object]) -> dict[str, object]:
    try:
        preferences = dict(_query_preferences(
            question,
            mode=payload.get("mode"),
            sport=payload.get("sport"),
            limit=payload.get("limit"),
            timing=payload.get("timing"),
            include_props=payload.get("include_props"),
            include_games=payload.get("include_games"),
        ))
        parsed_request = dict(_parlay_request_summary(preferences))
    except Exception:
        parsed_request = {}
    if question and not parsed_request.get("question"):
        parsed_request["question"] = question
    return parsed_request


def _is_board_response(payload: dict[str, object] | None) -> bool:
    current = dict(payload or {})
    if not current:
        return False
    if any(key in current for key in ("top_opportunities", "by_sport", "portfolio", "parlays")):
        return True
    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict) and any(key in analysis for key in ("recommendations", "picks", "top_live_opportunities", "parlays", "portfolio")):
        return True
    return False


def _response_has_content(payload: dict[str, object] | None) -> bool:
    current = dict(payload or {})
    if not current:
        return False
    if _response_candidate_count(current) > 0:
        return True
    for key in ("top_opportunities", "by_sport", "portfolio", "parlays"):
        value = current.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, list) and value:
            return True
    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        for key in ("recommendations", "picks", "top_live_opportunities", "parlays", "portfolio"):
            value = analysis.get(key)
            if isinstance(value, dict) and value:
                return True
            if isinstance(value, list) and value:
                return True
    return False


def _response_has_board_content(payload: dict[str, object] | None) -> bool:
    current = dict(payload or {})
    if not current:
        return False
    if _response_candidate_count(current) <= 0:
        return False
    candidate_pool = current.get("candidate_pool") if isinstance(current.get("candidate_pool"), dict) else None
    if isinstance(candidate_pool, dict):
        candidates = candidate_pool.get("candidates")
        if isinstance(candidates, list) and any(isinstance(item, dict) for item in candidates):
            return True
    candidates = current.get("candidates")
    if isinstance(candidates, list) and any(isinstance(item, dict) for item in candidates):
        return True
    for key in ("top_opportunities", "recommendations"):
        value = current.get(key)
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return True
    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        for key in ("recommendations", "top_live_opportunities"):
            value = analysis.get(key)
            if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                return True
    board_contract = current.get("board_contract") if isinstance(current.get("board_contract"), dict) else None
    if isinstance(board_contract, dict):
        for key in ("top_overall", "live", "pregame"):
            value = board_contract.get(key)
            if isinstance(value, list) and any(isinstance(item, dict) for item in value):
                return True
    return False


def _status_candidate_count_from_response(payload: dict[str, object] | None) -> int:
    current = dict(payload or {})
    board_candidate_count = current.get("candidate_count")
    if isinstance(board_candidate_count, int) and board_candidate_count >= 0:
        return board_candidate_count

    candidate_pool = current.get("candidate_pool") if isinstance(current.get("candidate_pool"), dict) else None
    if isinstance(candidate_pool, dict):
        candidate_count = candidate_pool.get("candidate_count")
        if isinstance(candidate_count, int) and candidate_count >= 0:
            return candidate_count
        candidates = candidate_pool.get("candidates")
        if isinstance(candidates, list):
            return len([candidate for candidate in candidates if isinstance(candidate, Mapping)])

    candidates = current.get("candidates")
    if isinstance(candidates, list):
        return len([candidate for candidate in candidates if isinstance(candidate, Mapping)])

    top_opportunities = current.get("top_opportunities")
    if isinstance(top_opportunities, list):
        return len([opportunity for opportunity in top_opportunities if isinstance(opportunity, Mapping)])

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        recommendations = analysis.get("recommendations")
        if isinstance(recommendations, list):
            return len([recommendation for recommendation in recommendations if isinstance(recommendation, dict)])

    return 0


def _response_contains_unhydrated_live_items(payload: dict[str, object] | None) -> bool:
    current = dict(payload or {})
    sources: list[dict[str, object]] = []

    for key in ("top_opportunities", "recommendations"):
        items = current.get(key)
        if isinstance(items, list):
            sources.extend(item for item in items if isinstance(item, dict))

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        for key in ("recommendations", "top_live_opportunities"):
            items = analysis.get(key)
            if isinstance(items, list):
                sources.extend(item for item in items if isinstance(item, dict))

    for item in sources:
        status_text = " ".join(
            str(part or "").strip().lower()
            for part in (
                item.get("status_display"),
                item.get("status_context"),
                item.get("game_state"),
            )
        )
        if not (
            bool(item.get("is_live"))
            or "live" in status_text
            or "in progress" in status_text
        ):
            continue
        has_live_projection = item.get("live_projection") is not None and str(item.get("live_projection") or item.get("liveProjection") or "").strip() not in {"", "-"}
        has_actual = item.get("actual") is not None
        live_state = item.get("live_state") if isinstance(item.get("live_state"), dict) else {}
        has_live_state = bool(live_state) and any(bool(live_state.get(key)) for key in ("in_progress", "final", "period", "clock", "players", "boxscore"))
        if not has_actual and not has_live_projection and not has_live_state:
            return True
    return False


def _response_selected_date(payload: dict[str, object] | None) -> str | None:
    current = dict(payload or {})
    for key in ("selected_date", "date"):
        value = str(current.get(key) or "").strip()
        if value:
            return value
    for container in (
        current.get("response") if isinstance(current.get("response"), dict) else None,
        current.get("analysis") if isinstance(current.get("analysis"), dict) else None,
    ):
        if not isinstance(container, dict):
            continue
        for key in ("selected_date", "date"):
            value = str(container.get(key) or "").strip()
            if value:
                return value
        evaluation_record = container.get("evaluation_record") if isinstance(container.get("evaluation_record"), dict) else None
        if isinstance(evaluation_record, dict):
            artifact_metadata = evaluation_record.get("artifact_metadata") if isinstance(evaluation_record.get("artifact_metadata"), dict) else None
            if isinstance(artifact_metadata, dict):
                for key in ("selected_date", "date"):
                    value = str(artifact_metadata.get(key) or "").strip()
                    if value:
                        return value
                manifest_summary = artifact_metadata.get("manifest_summary") if isinstance(artifact_metadata.get("manifest_summary"), dict) else None
                if isinstance(manifest_summary, dict):
                    for key in ("selected_date", "date"):
                        value = str(manifest_summary.get(key) or "").strip()
                        if value:
                            return value
    return None


def _response_age_seconds(payload: dict[str, object] | None) -> float | None:
    current = dict(payload or {})
    for key in ("last_updated", "updated_at", "computed_at", "latestComputedAt", "timestamp"):
        raw_value = str(current.get(key) or "").strip()
        if not raw_value:
            continue
        normalized = raw_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    return None


def _response_item_latest_timestamp(item: dict[str, object] | None) -> datetime | None:
    current = dict(item or {})
    candidates: list[str] = []
    for key in ("last_updated", "updated_at", "computed_at", "latestComputedAt", "timestamp", "generated_at", "odds_refreshed_at"):
        value = str(current.get(key) or "").strip()
        if value:
            candidates.append(value)

    movement = current.get("movement") if isinstance(current.get("movement"), dict) else None
    if isinstance(movement, dict):
        for key in ("last_updated", "updated_at", "computed_at", "timestamp", "generated_at"):
            value = str(movement.get(key) or "").strip()
            if value:
                candidates.append(value)

    movement_history = current.get("movement_history") if isinstance(current.get("movement_history"), list) else None
    if isinstance(movement_history, list) and movement_history:
        tail = movement_history[-1] if isinstance(movement_history[-1], dict) else None
        if isinstance(tail, dict):
            for key in ("timestamp", "last_updated", "updated_at", "computed_at", "generated_at"):
                value = str(tail.get(key) or "").strip()
                if value:
                    candidates.append(value)

    parsed_values: list[datetime] = []
    for raw_value in candidates:
        normalized = raw_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed_values.append(parsed.astimezone(timezone.utc))
    if not parsed_values:
        return None
    return max(parsed_values)


def _response_has_live_hydration(item: dict[str, object] | None) -> bool:
    current = dict(item or {})
    live_projection = current.get("live_projection") if current.get("live_projection") is not None else current.get("liveProjection")
    actual = current.get("actual")
    if actual is not None:
        return True
    if live_projection is not None and str(live_projection).strip() not in {"", "-"}:
        return True
    live_state = current.get("live_state") if isinstance(current.get("live_state"), dict) else None
    if isinstance(live_state, dict) and bool(live_state):
        return any(
            bool(live_state.get(key))
            for key in ("in_progress", "final", "period", "clock", "players", "boxscore")
        )
    return False


def _board_response_needs_refresh(
    request_payload: dict[str, object],
    response_payload: dict[str, object] | None,
    *,
    live_freshness_seconds: float = 45.0,
    pregame_freshness_seconds: float = 300.0,
) -> bool:
    if not _response_has_content(response_payload):
        return True
    if _response_contains_unhydrated_live_items(response_payload):
        return True
    request_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip()
    response_date = _response_selected_date(response_payload)
    if request_date and response_date and request_date != response_date:
        return True

    response_age_seconds = _response_age_seconds(response_payload)
    try:
        sources = _recommendation_sources(response_payload)
    except Exception:
        sources = []

    live_sources = [item for item in sources if isinstance(item, dict) and _recommendation_lane(item) == "live"]
    if live_sources:
        live_event_ids = {
            str(item.get("event_id") or item.get("game_id") or "").strip()
            for item in live_sources
            if str(item.get("event_id") or item.get("game_id") or "").strip()
        }
        if not live_event_ids:
            return True
        hydrated_live_sources = [item for item in live_sources if _response_has_live_hydration(item)]
        if not hydrated_live_sources:
            return True
        if response_age_seconds is not None and response_age_seconds > float(live_freshness_seconds):
            return True
        latest_signal = max(
            (timestamp for item in live_sources if (timestamp := _response_item_latest_timestamp(item)) is not None),
            default=None,
        )
        if latest_signal is not None:
            latest_signal_age = max(0.0, (datetime.now(timezone.utc) - latest_signal).total_seconds())
            if latest_signal_age > float(live_freshness_seconds):
                return True
        return False

    if response_age_seconds is not None and response_age_seconds > float(pregame_freshness_seconds):
        return True
    return False


def _response_needs_refresh(request_payload: dict[str, object], response_payload: dict[str, object] | None, *, freshness_seconds: float = 90.0) -> bool:
    _ = freshness_seconds
    return _board_response_needs_refresh(request_payload, response_payload)


def _cached_intelligence_response_with_source(payload: dict[str, object], *, force_refresh: bool = True) -> tuple[dict[str, object] | None, str]:
    cached_response = read_latest_intelligence_state_response(payload, force_refresh=force_refresh, allow_latest_fallback=False)
    if _is_board_response(cached_response) and _response_has_board_content(cached_response) and not _response_needs_refresh(payload, cached_response):
        return _hydrate_board_response_payload(cached_response), "worker"
    board_snapshot_response = read_latest_intelligence_board_snapshot_response(payload, force_refresh=force_refresh)
    if _is_board_response(board_snapshot_response) and _response_has_board_content(board_snapshot_response) and not _response_needs_refresh(payload, board_snapshot_response):
        return _hydrate_board_response_payload(board_snapshot_response), "board_snapshot"
    question_text = str(payload.get("question") or "").strip().lower()
    if question_text == DEFAULT_QUESTION.lower() and not str(payload.get("date") or payload.get("selected_date") or "").strip():
        latest_board_snapshot = read_latest_intelligence_board_snapshot_response(None, force_refresh=force_refresh)
        if _is_board_response(latest_board_snapshot) and _response_has_board_content(latest_board_snapshot):
            return _hydrate_board_response_payload(latest_board_snapshot), "board_snapshot_latest"
    return None, "fallback"


def _cached_intelligence_response(payload: dict[str, object]) -> dict[str, object] | None:
    cached_response, _ = _cached_intelligence_response_with_source(payload)
    return cached_response


def _compute_intelligence_response(payload: dict[str, object], *, source: str = "query_api") -> dict[str, object] | None:
    try:
        read_latest_intelligence_state_response(payload, force_refresh=False, allow_latest_fallback=False)
        computed_response = _INTELLIGENCE_STATE_SERVICE._compute_response(
            {
                "question": str(payload.get("question") or "").strip(),
                "date": str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso(),
                "mode": str(payload.get("mode") or "").strip() or None,
                "sport": str(payload.get("sport") or "").strip() or None,
                "game_state": str(payload.get("game_state") or "").strip() or None,
                "limit": payload.get("limit"),
                "timing": str(payload.get("timing") or "").strip() or None,
                "include_props": payload.get("include_props"),
                "include_games": payload.get("include_games"),
                "policy": str(payload.get("policy") or "").strip() or None,
            },
            force_refresh=True,
        )
        if not isinstance(computed_response, dict):
            return None
        state_payload = dict(computed_response)
        state_payload["candidate_count"] = len(state_payload.get("recommendations") or [])
        response = dict(state_payload)
        response.setdefault("ok", True)
        response.setdefault("response", dict(response))
        response.setdefault(
            "board_contract",
            {
                "schema": "intelligence_board_v1",
                "top_overall": [],
                "by_sport": {},
                "live": [],
                "pregame": [],
                "portfolio": {},
                "parlays": [],
            },
        )
        _attach_intelligence_response_aliases(response)
        global LAST_RESULT
        LAST_RESULT = dict(response.get("response") or response.get("analysis") or {})
        versioned_response = _versioned_query_response(response)
        versioned_response.update(_debug_state_fields(response, source=source))
        versioned_response["selected_date"] = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
        return versioned_response
    except Exception:
        _LOGGER.exception("BETTING_BOARD_REFRESH_FAILURE")
        return None


def _hydrate_board_response_payload(response_payload: dict[str, object] | None) -> dict[str, object]:
    current = dict(response_payload or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    nested = dict(nested or {})

    def _copy_items(key: str) -> list[dict[str, object]]:
        items = nested.get(key) if isinstance(nested.get(key), list) else []
        return [dict(item) for item in items if isinstance(item, dict)]

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        nested_top = _copy_items("top_opportunities")
        nested_recommendations = _copy_items("recommendations")
        if nested_top:
            current["top_opportunities"] = nested_top
        elif nested_recommendations:
            current["top_opportunities"] = nested_recommendations

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        current_recommendations = current.get("recommendations") if isinstance(current.get("recommendations"), list) else []
        normalized_current_recommendations = [dict(item) for item in current_recommendations if isinstance(item, dict)]
        if normalized_current_recommendations:
            current["top_opportunities"] = normalized_current_recommendations

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
        if isinstance(analysis, dict):
            analysis_recommendations = analysis.get("recommendations")
            if isinstance(analysis_recommendations, list):
                normalized_recommendations = [dict(item) for item in analysis_recommendations if isinstance(item, dict)]
                if normalized_recommendations:
                    current["top_opportunities"] = normalized_recommendations
                    if isinstance(nested, dict) and (not isinstance(nested.get("top_opportunities"), list) or not nested.get("top_opportunities")):
                        nested["top_opportunities"] = list(normalized_recommendations)

    if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
        nested_recommendations = _copy_items("recommendations")
        if nested_recommendations:
            current["recommendations"] = nested_recommendations

    if not isinstance(current.get("top_live_opportunities"), list) or not current.get("top_live_opportunities"):
        nested_live = _copy_items("top_live_opportunities")
        if nested_live:
            current["top_live_opportunities"] = nested_live

    if not isinstance(current.get("parlays"), list) or not current.get("parlays"):
        nested_parlays = _copy_items("parlays")
        if nested_parlays:
            current["parlays"] = nested_parlays

    if not isinstance(current.get("portfolio"), dict) or not current.get("portfolio"):
        nested_portfolio = nested.get("portfolio") if isinstance(nested.get("portfolio"), dict) else {}
        if nested_portfolio:
            current["portfolio"] = dict(nested_portfolio)

    if not isinstance(current.get("recommendation_history"), dict) or not current.get("recommendation_history"):
        nested_history = nested.get("recommendation_history") if isinstance(nested.get("recommendation_history"), dict) else {}
        if nested_history:
            current["recommendation_history"] = dict(nested_history)

    if not isinstance(current.get("portfolio_tracking"), dict) or not current.get("portfolio_tracking"):
        nested_tracking = nested.get("portfolio_tracking") if isinstance(nested.get("portfolio_tracking"), dict) else {}
        if nested_tracking:
            current["portfolio_tracking"] = dict(nested_tracking)

    if not isinstance(current.get("portfolio_events"), dict) or not current.get("portfolio_events"):
        nested_events = nested.get("portfolio_events") if isinstance(nested.get("portfolio_events"), dict) else {}
        if nested_events:
            current["portfolio_events"] = dict(nested_events)

    if not isinstance(current.get("portfolio_event_records"), list) or not current.get("portfolio_event_records"):
        nested_records = nested.get("portfolio_event_records") if isinstance(nested.get("portfolio_event_records"), list) else []
        if nested_records:
            current["portfolio_event_records"] = [dict(item) for item in nested_records if isinstance(item, dict)]

    if not isinstance(current.get("board_contract"), dict) or not current.get("board_contract"):
        try:
            current["board_contract"] = build_intelligence_board_contract(current)
        except Exception:
            current.setdefault("board_contract", {"schema": "intelligence_board_v1", "waterfall": []})

    if not isinstance(current.get("boardContract"), dict) or not current.get("boardContract"):
        current["boardContract"] = dict(current.get("board_contract") or {})

    return current


def _response_candidate_count(response_payload: dict[str, object] | None) -> int:
    current = dict(response_payload or {})
    candidate_pool = current.get("candidate_pool") if isinstance(current.get("candidate_pool"), dict) else {}
    candidates = candidate_pool.get("candidates") if isinstance(candidate_pool, dict) else current.get("candidates")
    if isinstance(candidates, list) and candidates:
        return len(candidates)
    top_opportunities = current.get("top_opportunities") if isinstance(current.get("top_opportunities"), list) else []
    if isinstance(top_opportunities, list) and top_opportunities:
        return len(top_opportunities)
    recommendations = current.get("recommendations") if isinstance(current.get("recommendations"), list) else []
    if isinstance(recommendations, list) and recommendations:
        return len(recommendations)
    return 0


def _line_move_tracking_fields(response_payload: dict[str, object] | None) -> dict[str, object]:
    current = dict(response_payload or {})
    recommendations = current.get("recommendations") if isinstance(current.get("recommendations"), list) else []
    candidate_pool = current.get("candidate_pool") if isinstance(current.get("candidate_pool"), dict) else {}
    candidates = candidate_pool.get("candidates") if isinstance(candidate_pool, dict) else current.get("candidates")
    if not isinstance(candidates, list):
        candidates = []

    tracked_recommendations = 0
    tracked_histories = 0
    tracked_sources = 0
    seen_tracking_keys: set[str] = set()

    def _tracking_key(item: dict[str, object]) -> str:
        candidate_id = str(item.get("candidate_id") or "").strip().lower()
        prediction_id = str(item.get("prediction_id") or "").strip().lower()
        recommendation_id = str(item.get("recommendation_id") or "").strip().lower()
        name = str(item.get("name") or item.get("display_name") or item.get("selection") or item.get("market") or "").strip().lower()
        market = str(item.get("market_key") or item.get("market") or "").strip().lower()
        return "|".join(part for part in (candidate_id, prediction_id, recommendation_id, name, market) if part)

    for item in [*recommendations, *candidates]:
        if not isinstance(item, dict):
            continue
        tracking_key = _tracking_key(item)
        if tracking_key and tracking_key in seen_tracking_keys:
            continue
        if tracking_key:
            seen_tracking_keys.add(tracking_key)
        movement = item.get("movement") if isinstance(item.get("movement"), dict) else {}
        movement_history = item.get("movement_history") if isinstance(item.get("movement_history"), list) else []
        market_data = item.get("market_data") if isinstance(item.get("market_data"), dict) else {}
        market_history = market_data.get("movement_history") if isinstance(market_data, dict) and isinstance(market_data.get("movement_history"), list) else []
        line_delta = movement.get("line_delta") if isinstance(movement, dict) else None
        line_movement_impact = item.get("line_movement_impact")
        if movement_history or market_history or line_delta not in (None, 0) or line_movement_impact not in (None, 0):
            tracked_sources += 1
        if movement_history:
            tracked_histories += len(movement_history)
        elif market_history:
            tracked_histories += len(market_history)
        if movement_history or market_history or line_delta not in (None, 0) or line_movement_impact not in (None, 0):
            tracked_recommendations += 1

    return {
        "line_moves_tracked": tracked_recommendations,
        "line_move_history_count": tracked_histories,
        "line_move_source_count": tracked_sources,
    }


def _debug_state_fields(response_payload: dict[str, object] | None, *, source: str, state_last_updated: str | None = None) -> dict[str, object]:
    current = dict(response_payload or {})
    state_meta = current.get("state_meta") if isinstance(current.get("state_meta"), dict) else {}
    derived_last_updated = str(
        state_last_updated
        or state_meta.get("computed_at")
        or state_meta.get("latestComputedAt")
        or current.get("snapshot_generated_at")
        or current.get("timestamp")
        or current.get("state_last_updated")
        or current.get("computed_at")
        or current.get("updated_at")
        or current.get("last_updated")
        or current.get("latestComputedAt")
        or ""
    ).strip() or None
    debug_fields = {
        "state_last_updated": derived_last_updated,
        "candidate_count": _response_candidate_count(current),
        "selected_date": str(current.get("selected_date") or current.get("date") or "").strip() or None,
        "snapshot_generated_at": str(current.get("snapshot_generated_at") or derived_last_updated or "").strip() or None,
        "debug_source": source,
    }
    debug_fields.update(_line_move_tracking_fields(current))
    return debug_fields


def _store_response_cache_state(state: dict[str, object]) -> None:
    return None


def _load_status_response_cache_state() -> dict[str, object] | None:
    return None


def _status_source_fingerprint(selected_date: str) -> str:
    worker_state = read_latest_intelligence_state({"date": selected_date})
    if isinstance(worker_state, dict):
        fingerprint = str(worker_state.get("latestSourceFingerprint") or worker_state.get("sourceFingerprint") or "").strip()
        if fingerprint:
            return fingerprint
    return _response_hash({"selected_date": str(selected_date or "").strip()})


def _cached_intelligence_status(selected_date: str, *, force_refresh: bool = False, cache_ttl_seconds: int = 60) -> dict[str, object]:
    _ = force_refresh
    _ = cache_ttl_seconds
    return read_latest_intelligence_state({"date": selected_date})


def _number_value(value: object) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _normalize_user_profile(payload: dict[str, object]) -> dict[str, object] | None:
    raw_profile = payload.get("user_profile")
    if not isinstance(raw_profile, dict):
        return None
    bankroll = _number_value(raw_profile.get("bankroll"))
    if bankroll is not None and bankroll <= 0.0:
        bankroll = None
    risk_tolerance = str(raw_profile.get("risk_tolerance") or "medium").strip().lower()
    if risk_tolerance not in {"low", "medium", "high"}:
        risk_tolerance = "medium"
    preferred_sports = []
    for sport in raw_profile.get("preferred_sports") or []:
        sport_key = str(sport).strip().lower()
        if sport_key:
            preferred_sports.append(sport_key)
    return {
        "bankroll": bankroll,
        "risk_tolerance": risk_tolerance,
        "preferred_sports": sorted(set(preferred_sports)),
    }


def _risk_multiplier(risk_tolerance: str) -> float:
    return {
        "low": 0.8,
        "medium": 1.0,
        "high": 1.2,
    }.get(risk_tolerance, 1.0)


def _candidate_sport_key(candidate: dict[str, object]) -> str:
    return str(candidate.get("sport") or candidate.get("sport_slug") or "unknown").strip().lower() or "unknown"


def _matches_preferred_sports(candidate: dict[str, object], preferred_sports: list[str]) -> bool:
    if not preferred_sports:
        return True
    return _candidate_sport_key(candidate) in set(preferred_sports)


def _adjust_pick_for_profile(candidate: dict[str, object], user_profile: dict[str, object]) -> dict[str, object]:
    adjusted = dict(candidate)
    bet_size = _number_value(adjusted.get("recommended_bet_size"))
    if bet_size is not None:
        bet_size *= _risk_multiplier(str(user_profile.get("risk_tolerance") or "medium"))
        bankroll = _number_value(user_profile.get("bankroll"))
        if bankroll is not None:
            bet_size *= bankroll
        adjusted["recommended_bet_size"] = round(bet_size, 4)
    return adjusted


def _adjust_portfolio_for_profile(portfolio: dict[str, object], user_profile: dict[str, object]) -> dict[str, object]:
    adjusted = dict(portfolio)
    total_exposure = _number_value(adjusted.get("total_exposure"))
    if total_exposure is not None:
        multiplier = _risk_multiplier(str(user_profile.get("risk_tolerance") or "medium"))
        bankroll = _number_value(user_profile.get("bankroll"))
        if bankroll is not None:
            total_exposure *= bankroll
        total_exposure *= multiplier
        adjusted["total_exposure"] = round(total_exposure, 4)
    adjusted["engine_risk_level"] = adjusted.get("risk_level")
    adjusted["risk_level"] = str(user_profile.get("risk_tolerance") or adjusted.get("risk_level") or "medium").strip().lower() or "medium"
    if user_profile.get("bankroll") is not None:
        adjusted["bankroll"] = _number_value(user_profile.get("bankroll"))
    return adjusted


def _filter_parlay_for_profile(parlay: dict[str, object], preferred_sports: list[str]) -> bool:
    if not preferred_sports:
        return True
    legs = parlay.get("legs") if isinstance(parlay.get("legs"), list) else []
    if not legs:
        return _matches_preferred_sports(parlay, preferred_sports)
    preferred = set(preferred_sports)
    return all(_candidate_sport_key(leg) in preferred for leg in legs if isinstance(leg, dict))


def _apply_user_profile_to_response(response_payload: dict[str, object], user_profile: dict[str, object] | None) -> dict[str, object]:
    if not user_profile:
        return response_payload

    preferred_sports = list(user_profile.get("preferred_sports") or [])

    top_opportunities = response_payload.get("top_opportunities") if isinstance(response_payload.get("top_opportunities"), list) else []
    if preferred_sports:
        response_payload["top_opportunities"] = [
            dict(item)
            for item in top_opportunities
            if isinstance(item, dict) and _matches_preferred_sports(item, preferred_sports)
        ]

        by_sport = response_payload.get("by_sport") if isinstance(response_payload.get("by_sport"), dict) else {}
        response_payload["by_sport"] = {
            str(key): [dict(item) for item in items if isinstance(item, dict) and _matches_preferred_sports(item, preferred_sports)]
            for key, items in by_sport.items()
            if str(key).strip().lower() in set(preferred_sports)
        }

    analysis = response_payload.get("analysis") if isinstance(response_payload.get("analysis"), dict) else None
    if analysis is None:
        return response_payload

    for key in ("recommendations", "picks", "top_live_opportunities"):
        items = analysis.get(key)
        if not isinstance(items, list):
            continue
        processed_items: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if preferred_sports and not _matches_preferred_sports(item, preferred_sports):
                continue
            if key in {"recommendations", "picks"}:
                item = _adjust_pick_for_profile(item, user_profile)
            processed_items.append(dict(item))
        analysis[key] = processed_items

    parlay_items = analysis.get("parlays")
    if isinstance(parlay_items, list):
        analysis["parlays"] = [
            dict(item)
            for item in parlay_items
            if isinstance(item, dict) and _filter_parlay_for_profile(item, preferred_sports)
        ]

    portfolio = analysis.get("portfolio") if isinstance(analysis.get("portfolio"), dict) else None
    if portfolio is not None:
        analysis["portfolio"] = _adjust_portfolio_for_profile(portfolio, user_profile)

    response_payload["analysis"] = analysis
    if "response" in response_payload:
        response_payload["response"] = analysis
    return response_payload


def _intelligence_page_payload(selected_date: str, *, sport: str | None = None, force_refresh: bool = False) -> dict[str, object]:
    return {
        "question": DEFAULT_QUESTION,
        "date": selected_date,
        "mode": "recommendation",
        "sport": str(sport or "").strip().lower() or "all",
        "game_state": "all",
        "timing": "all",
        "limit": 5,
        "include_props": True,
        "include_games": True,
        "force_refresh": force_refresh,
    }


def _safe_queue_intelligence_state_refresh(payload: dict[str, object]) -> None:
    try:
        queue_intelligence_state_refresh(dict(payload))
    except Exception:
        _LOGGER.warning("Intelligence refresh queue failed; serving cached or empty state instead.", exc_info=True)


def _normalize_default_query_payload(payload: dict[str, object]) -> dict[str, object]:
    normalized = dict(payload or {})
    if str(normalized.get("question") or "").strip() == DEFAULT_QUESTION:
        normalized["date"] = str(normalized.get("date") or normalized.get("selected_date") or central_today_iso()).strip() or central_today_iso()
        normalized.setdefault("mode", "recommendation")
        normalized.setdefault("timing", "all")
    return normalized


def _empty_default_intelligence_response() -> dict[str, object]:
    empty_analysis = {
        "recommendations": [],
        "picks": [],
        "top_live_opportunities": [],
        "portfolio": {},
        "parlays": [],
        "movement": {},
    }
    return {
        "ok": True,
        "top_opportunities": [],
        "by_sport": {},
        "analysis": dict(empty_analysis),
        "response": {
            **empty_analysis,
            "top_opportunities": [],
        },
        "board_contract": {
            "schema": "intelligence_board_v1",
            "top_overall": [],
            "by_sport": {},
            "live": [],
            "pregame": [],
            "portfolio": {},
            "parlays": [],
        },
    }


def read_latest_intelligence_state(payload: dict[str, object] | None = None) -> dict[str, object]:
    started_at = time.perf_counter()
    snapshot = read_latest_intelligence_state_response(payload, force_refresh=False, allow_latest_fallback=False)
    _log_intelligence_timing(
        "read_latest_intelligence_state_response",
        started_at,
        has_snapshot=isinstance(snapshot, dict),
        snapshot_candidate_count=_response_candidate_count(snapshot) if isinstance(snapshot, dict) else 0,
    )
    hydrated_snapshot = _hydrate_board_response_payload(snapshot) if isinstance(snapshot, dict) else None
    hydrated_candidate_count = _response_candidate_count(hydrated_snapshot) if isinstance(hydrated_snapshot, dict) else 0
    if isinstance(hydrated_snapshot, dict) and _response_has_content(hydrated_snapshot) and hydrated_candidate_count > 0 and not (str(hydrated_snapshot.get("query_type") or "").strip().lower() == "explanation" and hydrated_candidate_count <= 0):
        return hydrated_snapshot
    board_started_at = time.perf_counter()
    board_snapshot = read_latest_intelligence_board_snapshot_response(payload, force_refresh=False)
    _log_intelligence_timing(
        "read_latest_intelligence_board_snapshot_response",
        board_started_at,
        has_snapshot=isinstance(board_snapshot, dict),
        snapshot_candidate_count=_response_candidate_count(board_snapshot) if isinstance(board_snapshot, dict) else 0,
    )
    if not (isinstance(board_snapshot, dict) and _response_candidate_count(board_snapshot) > 0):
        from pipeline.intelligence_state import _latest_non_empty_intelligence_board_snapshot_response

        latest_started_at = time.perf_counter()
        board_snapshot = _latest_non_empty_intelligence_board_snapshot_response(payload)
        _log_intelligence_timing(
            "_latest_non_empty_intelligence_board_snapshot_response",
            latest_started_at,
            has_snapshot=isinstance(board_snapshot, dict),
            snapshot_candidate_count=_response_candidate_count(board_snapshot) if isinstance(board_snapshot, dict) else 0,
        )
    if isinstance(board_snapshot, dict):
        return _hydrate_board_response_payload(board_snapshot)
    return _empty_default_intelligence_response()


@intelligence_bp.get("/intelligence")
def intelligence_home():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    payload = _intelligence_page_payload(selected_date, force_refresh=True)
    initial_response: dict[str, Any] = {}
    try:
        cached_loader = _cached_intelligence_response_with_source
        if hasattr(cached_loader, "call_count"):
            cached_response, _ = cached_loader(payload, force_refresh=False)
            cached_response_is_usable = isinstance(cached_response, dict) and _response_has_content(cached_response) and not _response_needs_refresh(payload, cached_response)
            if cached_response_is_usable:
                initial_response = dict(cached_response)
            else:
                _safe_queue_intelligence_state_refresh(dict(payload))
                initial_response = _empty_default_intelligence_response()
        else:
            board_snapshot_response = read_latest_intelligence_board_snapshot_response(payload, force_refresh=True)
            state_response = read_latest_intelligence_state_response(payload, force_refresh=False, allow_latest_fallback=False)
            for response_candidate in (state_response, board_snapshot_response):
                if not isinstance(response_candidate, dict):
                    continue
                if not _response_has_board_content(response_candidate):
                    continue
                if _response_needs_refresh(payload, response_candidate):
                    continue
                initial_response = dict(response_candidate)
                break
            if not initial_response:
                _safe_queue_intelligence_state_refresh(dict(payload))
                initial_response = _empty_default_intelligence_response()
    except Exception:
        initial_response = _empty_default_intelligence_response()
    return render_template(
        "intelligence.html",
        initial_intelligence_response=initial_response,
        initial_intelligence_selected_date=selected_date,
    )


@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    global LAST_RESULT
    payload = request.get_json(silent=True) or {}
    payload = _normalize_default_query_payload(payload)
    question = str(payload.get("question") or "").strip()
    if not question:
        response = jsonify({"ok": False, "error": "question is required."})
        response.status_code = 400
        return _no_cache_response(response)
    force_refresh = _query_bool(payload.get("force_refresh"))
    _LOGGER.info("BETTING_BOARD_REFRESH_START", extra={"selected_date": str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or None, "force_refresh": force_refresh, "source": "query_api"})
    if force_refresh:
        if _render_hosted_request():
            queued = True
            try:
                _safe_queue_intelligence_state_refresh(dict(payload))
            except Exception:
                queued = False
                _LOGGER.exception("BETTING_BOARD_REFRESH_FAILURE")

            cached_response, execution_source = _cached_intelligence_response_with_source(payload, force_refresh=True)
            if isinstance(cached_response, dict) and _response_has_board_content(cached_response):
                response_payload = dict(cached_response)
                response_payload["queued_refresh"] = True
                response_payload["execution_source"] = execution_source
                response_payload.setdefault("queued", queued)
                response_payload.setdefault("ok", True)
                response_payload.setdefault("response", dict(response_payload))
                _attach_intelligence_response_aliases(response_payload)
                global LAST_RESULT
                LAST_RESULT = dict(response_payload.get("response") or response_payload.get("analysis") or {})
                versioned_response = _versioned_query_response(response_payload)
                versioned_response.update(_debug_state_fields(response_payload, source="snapshot_read"))
                versioned_response["selected_date"] = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
                _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
                _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
                return _no_cache_response(jsonify(versioned_response))

            response_payload = dict(_empty_default_intelligence_response())
            response_payload["queued_refresh"] = True
            response_payload["execution_source"] = execution_source
            response_payload.setdefault("queued", queued)
            response_payload.setdefault("ok", True)
            response_payload.setdefault("response", dict(response_payload))
            _attach_intelligence_response_aliases(response_payload)
            LAST_RESULT = dict(response_payload.get("response") or response_payload.get("analysis") or {})
            versioned_response = _versioned_query_response(response_payload)
            versioned_response.update(_debug_state_fields(response_payload, source="snapshot_read"))
            versioned_response["selected_date"] = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
            _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
            _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
            return _no_cache_response(jsonify(versioned_response))
        else:
            try:
                read_latest_intelligence_state_response(payload, force_refresh=False, allow_latest_fallback=False)
                computed_response = _compute_intelligence_response(payload, source="compute_refresh")
                if isinstance(computed_response, dict):
                    _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": computed_response.get("selected_date"), "candidate_count": _response_candidate_count(computed_response), "source": "query_api"})
                    _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": computed_response.get("selected_date"), "candidate_count": _response_candidate_count(computed_response), "source": "query_api"})
                    return _no_cache_response(jsonify(computed_response))
            except Exception:
                _LOGGER.exception("BETTING_BOARD_REFRESH_FAILURE")
    state_payload = read_latest_intelligence_state(dict(payload))
    if force_refresh:
        _safe_queue_intelligence_state_refresh(dict(payload))
    board_snapshot_payload = read_latest_intelligence_board_snapshot_response(payload, force_refresh=False)

    # "Has board content" alone only checks that a candidate carries *some*
    # recommendations -- it says nothing about whether that content is for
    # the date/lane actually requested. _response_needs_refresh() already
    # catches a date mismatch (among other staleness signals) but was never
    # consulted here, which let a cached response for a completely
    # different day (observed: a request for today served candidates
    # stamped six weeks earlier) get accepted as-is with no indication
    # anything was wrong. Prefer a candidate that is both non-empty AND
    # date-matched before ever falling back to a stale one.
    #
    # _response_needs_refresh only checks date/hydration/age -- it has no
    # concept of sport. read_latest_intelligence_board_snapshot_response's
    # board_snapshot.json fallback is *also* sport-agnostic (unlike
    # pipeline.intelligence_state's IntelligenceStateService, which does
    # track sport per snapshot). Observed: requesting sport="wnba" on a day
    # WNBA has no games returned MLB-tagged candidates instead of an honest
    # empty result, because nothing here ever checked which sport the
    # cached candidates actually belonged to.
    def _response_sport_slugs(response_payload: dict[str, object] | None) -> set[str]:
        # Deliberately self-contained: _recommendation_sources (used
        # elsewhere in this file, e.g. _board_response_needs_refresh) is
        # referenced but never actually defined anywhere in this repo --
        # every call site wraps it in a bare try/except, so it has always
        # silently evaluated to an empty list rather than raising. Extract
        # candidates directly instead of depending on that phantom name.
        current = dict(response_payload or {})
        nested = current.get("response") if isinstance(current.get("response"), dict) else {}
        analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else (nested.get("analysis") if isinstance(nested.get("analysis"), dict) else {})
        candidates: list[object] = []
        for container in (current, nested, analysis):
            if not isinstance(container, dict):
                continue
            for key in ("recommendations", "top_opportunities"):
                value = container.get(key)
                if isinstance(value, list):
                    candidates.extend(value)
        slugs: set[str] = set()
        for item in candidates:
            if not isinstance(item, dict):
                continue
            value = str(item.get("sport_slug") or item.get("sport") or "").strip().lower()
            if value:
                slugs.add(value)
        return slugs

    def _matches_requested_sport(candidate: dict[str, object] | None) -> bool:
        requested_sport = str(payload.get("sport") or "").strip().lower()
        if not requested_sport or requested_sport == "all":
            return True
        candidate_sports = _response_sport_slugs(candidate)
        if not candidate_sports:
            # No sport tag found on any candidate -- can't confirm a match,
            # but can't prove a mismatch either; do not block on an absent
            # field the same way the date check treats a missing date.
            return True
        return requested_sport in candidate_sports

    def _fresh_enough(candidate: dict[str, object] | None) -> bool:
        return (
            isinstance(candidate, dict)
            and _response_has_board_content(candidate)
            and not _response_needs_refresh(payload, candidate)
            and _matches_requested_sport(candidate)
        )

    # A confirmed synchronous recompute for a genuinely stale slate can
    # return zero candidates (there just isn't a game today) -- so a
    # "stale" cached candidate isn't always secretly hiding fresher data
    # somewhere; sometimes it's just old. Old-but-recent (e.g. yesterday's
    # board, still refreshing) is still useful labeled as stale; a cached
    # response from weeks ago is not "today's board, a bit behind" -- it's
    # a different day's settled slate, and showing it (even labeled) would
    # be misleading for a "today" board. Cap how old a stale fallback can
    # be before we'd rather show honestly empty.
    def _stale_within_threshold(candidate: dict[str, object] | None, *, max_age_days: int = 2) -> bool:
        request_date_text = str(payload.get("date") or payload.get("selected_date") or "").strip()
        candidate_date_text = _response_selected_date(candidate) if isinstance(candidate, dict) else None
        if not request_date_text or not candidate_date_text:
            return True
        try:
            request_dt = datetime.fromisoformat(request_date_text)
            candidate_dt = datetime.fromisoformat(candidate_date_text)
        except Exception:
            return True
        return abs((request_dt - candidate_dt).days) <= max_age_days

    if not _fresh_enough(state_payload):
        if _fresh_enough(board_snapshot_payload):
            state_payload = board_snapshot_payload
        else:
            _safe_queue_intelligence_state_refresh(dict(payload))
            queued_state = read_latest_intelligence_state(dict(payload))
            if _fresh_enough(queued_state):
                state_payload = queued_state
            else:
                # Nothing date-matched is available yet -- a background
                # refresh was just queued above. Serve the best
                # content-bearing, not-too-old candidate we do have rather
                # than an empty board, but say so explicitly instead of
                # presenting it as current.
                stale_fallback = next(
                    (
                        candidate
                        for candidate in (queued_state, state_payload, board_snapshot_payload)
                        if isinstance(candidate, dict) and _response_has_board_content(candidate) and _stale_within_threshold(candidate) and _matches_requested_sport(candidate)
                    ),
                    None,
                )
                if stale_fallback is not None:
                    state_payload = dict(stale_fallback)
                    state_payload["stale"] = True
                    state_payload["freshness_state"] = "stale"
                else:
                    state_payload = _empty_default_intelligence_response()
                    state_payload["queued"] = True
    candidate_count = _response_candidate_count(state_payload) if isinstance(state_payload, dict) else 0
    if candidate_count <= 0 or not isinstance(state_payload, dict) or not _response_has_board_content(state_payload):
        _safe_queue_intelligence_state_refresh(dict(payload))
        queued_state = read_latest_intelligence_state(dict(payload))
        # This is the same re-fetch-after-queuing pattern as above, so it
        # needs the same discipline: "has content" alone previously let this
        # block re-accept the identical stale, wrong-date cache it was just
        # rejected for above, silently undoing that rejection.
        if _fresh_enough(queued_state):
            state_payload = queued_state
        elif isinstance(queued_state, dict) and _response_has_board_content(queued_state) and _stale_within_threshold(queued_state) and _matches_requested_sport(queued_state):
            state_payload = dict(queued_state)
            state_payload["stale"] = True
            state_payload["freshness_state"] = "stale"
        else:
            state_payload = _empty_default_intelligence_response()
            state_payload["queued"] = True
    response = dict(state_payload)
    response.setdefault("ok", True)
    response.setdefault("response", dict(response))
    response.setdefault(
        "board_contract",
        {
            "schema": "intelligence_board_v1",
            "top_overall": [],
            "by_sport": {},
            "live": [],
            "pregame": [],
            "portfolio": {},
            "parlays": [],
        },
    )
    _attach_intelligence_response_aliases(response)
    LAST_RESULT = dict(response.get("response") or response.get("analysis") or {})
    versioned_response = _versioned_query_response(response)
    versioned_response.update(_debug_state_fields(response, source="snapshot_read"))
    versioned_response["selected_date"] = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
    _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": candidate_count, "source": "query_api"})
    _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": candidate_count, "source": "query_api"})
    return _no_cache_response(jsonify(versioned_response))


@intelligence_bp.post("/api/intelligence/portfolio-event")
def intelligence_portfolio_event_api():
    try:
        payload = request.get_json(silent=True) or {}
        portfolio_event = payload.get("portfolio_event")
        if not isinstance(portfolio_event, dict):
            portfolio_event = payload.get("event") if isinstance(payload.get("event"), dict) else None
        if not isinstance(portfolio_event, dict):
            response = jsonify({"ok": False, "error": "portfolio_event is required."})
            response.status_code = 400
            return _no_cache_response(response)

        selected_date = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
        question = str(payload.get("question") or "manual portfolio event").strip() or "manual portfolio event"
        sport = str(payload.get("sport") or "").strip() or None
        persist = bool(payload.get("persist", True))

        bundle = build_intelligence_evaluation_bundle(
            query={"question": question, "selected_date": selected_date, "sport": sport},
            response={
                "selected_date": selected_date,
                "sport": sport,
                "recommendations": [],
                "portfolio_events": [dict(portfolio_event)],
            },
            persist=persist,
        )
        response_payload = {
            "ok": True,
            "selected_date": selected_date,
            "question": question,
            "portfolio_event": dict(portfolio_event),
            "evaluation_bundle": bundle,
            "evaluationBundle": dict(bundle),
            "portfolio_tracking": dict(bundle.get("portfolio_tracking") or {}),
            "portfolioTracking": dict(bundle.get("portfolio_tracking") or {}),
            "portfolio_events": dict(bundle.get("portfolio_events") or {}),
            "portfolioEvents": dict(bundle.get("portfolio_events") or {}),
            "portfolio_event_records": list(bundle.get("portfolio_event_records") or []),
            "portfolioEventRecords": list(bundle.get("portfolio_event_records") or []),
            "recommendation_history": dict(bundle.get("history") or {}),
            "recommendationHistory": dict(bundle.get("history") or {}),
            "performance_analytics": dict(bundle.get("performance_analytics") or {}),
            "performanceAnalytics": dict(bundle.get("performance_analytics") or {}),
        }
        return _no_cache_response(jsonify(response_payload))
    except Exception:
        _LOGGER.exception("INTELLIGENCE STATUS FAILURE")
        raise


@intelligence_bp.get("/intelligence/run")
def run_intelligence():
    selected_date = central_today_iso()
    launch_result: dict[str, Any] | None = None
    launched = False
    try:
        launch_result = launch_refresh_run(
            date=selected_date,
            mode=None,
            phase=None,
            regions=None,
            execution_mode=None,
            skip_mirror=None,
        )
        launched = True
    except Exception:
        launch_result = load_latest_refresh_status()
    _safe_queue_intelligence_state_refresh(_intelligence_page_payload(selected_date, force_refresh=True))
    return jsonify({"ok": True, "selected_date": selected_date, "launched": launched, "refresh": normalize_timestamped_payload(launch_result), "queued": True})


@intelligence_bp.get("/api/intelligence/status")
def intelligence_status_api():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    selected_sport = str(request.args.get("sport") or "").strip() or "all"
    refresh_requested = str(request.args.get("refresh") or request.args.get("force_refresh") or "").strip().lower() in {"1", "true", "yes", "on"}
    if refresh_requested:
        _LOGGER.info("BETTING_BOARD_REFRESH_START", extra={"selected_date": selected_date, "source": "status_api", "refresh_requested": True})
    status_payload = _intelligence_page_payload(selected_date, sport=selected_sport, force_refresh=False)
    stale_snapshot = False
    current_snapshot = read_latest_intelligence_state(dict(status_payload))
    state_candidate_count = _response_candidate_count(current_snapshot) if isinstance(current_snapshot, dict) else 0
    has_snapshot = isinstance(current_snapshot, dict) and _response_has_board_content(current_snapshot)
    if not refresh_requested:
        stale_snapshot = bool(_response_selected_date(current_snapshot) and _response_selected_date(current_snapshot) != selected_date)
    if refresh_requested:
        _safe_queue_intelligence_state_refresh(_intelligence_page_payload(selected_date, sport=selected_sport, force_refresh=True))
    elif not has_snapshot:
        _safe_queue_intelligence_state_refresh(_intelligence_page_payload(selected_date, sport=selected_sport, force_refresh=True))
    elif stale_snapshot:
        _safe_queue_intelligence_state_refresh(_intelligence_page_payload(selected_date, sport=selected_sport, force_refresh=True))
    status = read_latest_intelligence_state(dict(status_payload))
    board_snapshot = read_latest_intelligence_board_snapshot_response(status_payload, force_refresh=False)
    if state_candidate_count <= 0 and _response_candidate_count(board_snapshot) > 0 and _response_has_board_content(board_snapshot):
        status = board_snapshot
    elif not isinstance(status, dict) or not _response_has_board_content(status):
        if _response_candidate_count(current_snapshot) > 0 and _response_has_board_content(current_snapshot):
            status = current_snapshot
        elif _response_candidate_count(board_snapshot) > 0 and _response_has_board_content(board_snapshot):
            status = board_snapshot
        else:
            queued_state = read_latest_intelligence_state(dict(status_payload))
            if _response_candidate_count(queued_state) > 0 and _response_has_board_content(queued_state):
                status = queued_state
            else:
                status = _empty_default_intelligence_response()
    state_snapshot = dict(status)
    response_payload = {"ok": True, "status": state_snapshot}
    if isinstance(status, dict) and _response_has_board_content(status):
        for key, value in status.items():
            if key == "ok":
                continue
            response_payload[key] = normalize_timestamped_payload(value)
    response_payload.update(_debug_state_fields(state_snapshot, source="snapshot_read"))
    response_payload["selected_date"] = selected_date
    _LOGGER.info("BETTING_BOARD_REFRESH_DATE", extra={"selected_date": selected_date, "candidate_count": _response_candidate_count(state_snapshot), "source": "status_api"})
    _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": selected_date, "candidate_count": _response_candidate_count(state_snapshot), "source": "status_api"})
    return _no_cache_response(jsonify(response_payload))


@intelligence_bp.get("/intelligence/status")
def intelligence_status_page():
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    selected_sport = str(request.args.get("sport") or "").strip()
    redirect_target = f"/api/intelligence/status?date={selected_date}"
    if selected_sport:
        redirect_target = f"{redirect_target}&sport={selected_sport}"
    return redirect(redirect_target, code=302)


def _portfolio_summary_limit() -> int:
    raw = str(request.args.get("limit") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return 60
    return max(1, min(value, 500))


@intelligence_bp.get("/api/portfolio/summary")
def portfolio_summary_api():
    summary = build_portfolio_summary(limit=_portfolio_summary_limit())
    return _no_cache_response(jsonify({"ok": True, **summary}))


@intelligence_bp.get("/portfolio")
def portfolio_home():
    summary = build_portfolio_summary(limit=100)
    return render_template("portfolio.html", portfolio_summary=summary)