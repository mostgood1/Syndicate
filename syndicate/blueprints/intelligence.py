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
from pipeline.intelligence_state import queue_board_state_refresh
from pipeline.intelligence_state import canonical_board_state_enabled
from pipeline.intelligence_state import canonical_board_state_shadow_compare_enabled
from pipeline.intelligence_state import read_intelligence_board_state
from pipeline.intelligence_state import read_latest_intelligence_board_state
from pipeline.intelligence_state import slice_intelligence_board_state_for_request
from pipeline.intelligence_state import read_combined_intelligence_response
from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE
from syndicate.features.intelligence import _market_focus_labels
from syndicate.features.intelligence import _parlay_request_summary
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import _attach_intelligence_response_aliases
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence_board import _recommendation_lane
from syndicate.features.shared.artifact_manifests import load_artifact_manifests
from syndicate.features.shared.game_chip_scoreboard import build_game_chips
from syndicate.features.shared.intelligence_evaluation import build_intelligence_evaluation_bundle
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.timezone import normalize_timestamped_payload
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.ops_refresh import launch_refresh_run
from syndicate.features.shared.ops_refresh import load_latest_refresh_status
from syndicate.features.portfolio_summary import build_portfolio_summary
from syndicate.features.prediction_ledger import record_prediction


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


def combined_board_default_enabled() -> bool:
    # Dark-launched like SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE: ships
    # off, flips on once production logs confirm it behaves as expected. See
    # #93 follow-up -- "no explicit date" becomes "everything currently
    # relevant across sports/dates" instead of "today only", with date
    # turning into a client-side filter (syndicate/templates/intelligence.html)
    # rather than the primary query key.
    raw_value = str(os.environ.get("SYNDICATE_INTELLIGENCE_COMBINED_BOARD_DEFAULT") or "").strip().lower()
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


def _recommendation_sources(response_payload: dict[str, object] | None) -> list[dict[str, object]]:
    # Referenced by _board_response_needs_refresh below for a long time
    # without ever being defined anywhere in this repo -- every call site
    # wrapped it in a bare try/except, so live-vs-pregame freshness
    # classification always silently saw an empty list. Checks every shape a
    # response can take (top-level, nested under "response", or nested under
    # "analysis") since callers pass all three across this file.
    current = dict(response_payload or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else (nested.get("analysis") if isinstance(nested.get("analysis"), dict) else {})
    sources: list[dict[str, object]] = []
    for container in (current, nested, analysis):
        if not isinstance(container, dict):
            continue
        for key in ("recommendations", "top_opportunities"):
            value = container.get(key)
            if isinstance(value, list):
                sources.extend(item for item in value if isinstance(item, dict))
    return sources


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


def _response_unsafe_to_display(request_payload: dict[str, object], response_payload: dict[str, object] | None) -> bool:
    # Narrower than _response_needs_refresh: that answers "should a fresh
    # compute be triggered" (age, live-hydration completeness, date match --
    # all reasonable reasons to refresh in the background). This answers a
    # different question -- "would showing this response actively mislead
    # the viewer" -- so intelligence_home can serve a merely-aged, same-date
    # pregame board (strictly better than an empty page while a post-deploy
    # compute cycle catches up, which can take several minutes before any
    # fresh state has been persisted) while still refusing to show a
    # different date's picks as if they were today's, or a live game's
    # odds/state without proper hydration (which can be badly wrong
    # mid-game, not just stale).
    if _response_contains_unhydrated_live_items(response_payload):
        return True
    request_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip()
    response_date = _response_selected_date(response_payload)
    return bool(request_date and response_date and request_date != response_date)


def _load_canonical_board_response(payload: dict[str, object]) -> tuple[dict[str, object] | None, str]:
    # Migration step 3 (intelligence-state rebuild plan): tried first in
    # _cached_intelligence_response_with_source below, behind
    # SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE. Falls through to the
    # existing multi-layer cascade (unchanged) whenever the flag is off or
    # this read misses -- so with the flag off (the default) this is a
    # no-op and behavior is identical to before this function existed.
    #
    # Also computed (but never served) when only the shadow-compare flag is
    # on -- that's what lets _cached_intelligence_response_with_source below
    # log a canonical-vs-legacy diff during the validation window without
    # actually switching what gets served.
    if not (canonical_board_state_enabled() or canonical_board_state_shadow_compare_enabled()):
        return None, "canonical_disabled"
    requested_date = str(payload.get("date") or payload.get("selected_date") or "").strip()
    state = read_intelligence_board_state(requested_date) if requested_date else read_latest_intelligence_board_state()
    if not isinstance(state, dict):
        return None, "canonical_miss"
    requested_sport = str(payload.get("sport") or "all").strip().lower() or "all"
    covered_sports = state.get("covered_sports") if isinstance(state.get("covered_sports"), list) else []
    # Direct membership check against the canonical state's own
    # covered_sports list, in place of the legacy cascade's
    # _response_has_sport_data guessing (which infers sport coverage from
    # whatever candidates happen to be present, since the legacy
    # board_snapshot/intelligence_state artifacts never recorded which
    # sports a cycle actually considered).
    if requested_sport != "all" and requested_sport not in covered_sports:
        return None, "canonical_miss"
    raw_limit = payload.get("limit")
    try:
        limit_value = int(raw_limit) if raw_limit is not None and str(raw_limit).strip() else None
    except Exception:
        limit_value = None
    sliced = slice_intelligence_board_state_for_request(state, sport=requested_sport, limit=limit_value)
    response = dict(sliced)
    response.setdefault("ok", True)
    response["selected_date"] = state.get("selected_date")
    response.setdefault("candidate_count", state.get("candidate_count"))
    response.setdefault("board_contract", state.get("board_contract"))
    if not _is_board_response(response) or not _response_has_board_content(response):
        return None, "canonical_miss"
    return _hydrate_board_response_payload(response), "canonical_board_state"


def _cached_intelligence_response_from_legacy_cascade(payload: dict[str, object], *, force_refresh: bool = True) -> tuple[dict[str, object] | None, str]:
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


def _log_canonical_board_state_shadow_diff(
    payload: dict[str, object],
    *,
    canonical_response: dict[str, object] | None,
    canonical_source: str,
    served_response: dict[str, object] | None,
    served_source: str,
) -> None:
    # Best-effort/never-raises: this is purely an observability aid for the
    # migration step 4 validation window, watched via logs while the legacy
    # cascade still serves every real request. A logging bug here must never
    # be able to affect what a user actually sees.
    try:
        canonical_count = _status_candidate_count_from_response(canonical_response)
        served_count = _status_candidate_count_from_response(served_response)

        def _names(response: dict[str, object] | None) -> set[str]:
            items = (response or {}).get("top_opportunities")
            if not isinstance(items, list):
                return set()
            return {str(item.get("name") or "").strip() for item in items if isinstance(item, dict) and item.get("name")}

        canonical_names = _names(canonical_response)
        served_names = _names(served_response)
        _LOGGER.info(
            "CANONICAL_BOARD_STATE_SHADOW_DIFF",
            extra={
                "requested_date": str(payload.get("date") or payload.get("selected_date") or "").strip() or None,
                "requested_sport": str(payload.get("sport") or "all").strip().lower() or "all",
                "canonical_source": canonical_source,
                "served_source": served_source,
                "served_is_canonical": served_source == canonical_source and canonical_response is not None,
                "canonical_candidate_count": canonical_count,
                "served_candidate_count": served_count,
                "candidate_count_delta": canonical_count - served_count,
                "names_only_in_canonical": sorted(name for name in (canonical_names - served_names) if name),
                "names_only_in_served": sorted(name for name in (served_names - canonical_names) if name),
            },
        )
    except Exception:
        _LOGGER.exception("CANONICAL_BOARD_STATE_SHADOW_DIFF_FAILED")


def _cached_intelligence_response_with_source(payload: dict[str, object], *, force_refresh: bool = True) -> tuple[dict[str, object] | None, str]:
    canonical_response, canonical_source = _load_canonical_board_response(payload)
    canonical_fresh = canonical_response is not None and not _response_needs_refresh(payload, canonical_response)
    shadow_compare = canonical_board_state_shadow_compare_enabled()

    if canonical_board_state_enabled() and canonical_fresh:
        if shadow_compare:
            _log_canonical_board_state_shadow_diff(
                payload,
                canonical_response=canonical_response,
                canonical_source=canonical_source,
                served_response=canonical_response,
                served_source=canonical_source,
            )
        return canonical_response, canonical_source

    legacy_response, legacy_source = _cached_intelligence_response_from_legacy_cascade(payload, force_refresh=force_refresh)
    if shadow_compare:
        _log_canonical_board_state_shadow_diff(
            payload,
            canonical_response=canonical_response if canonical_fresh else None,
            canonical_source=canonical_source if canonical_fresh else "canonical_miss",
            served_response=legacy_response,
            served_source=legacy_source,
        )
    return legacy_response, legacy_source


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
        # _compute_response returns board state, which has never carried
        # parsed_request -- so the query API stopped reporting how it interpreted
        # the question (risk profile, requested sports/subjects, parlay shape).
        # _parsed_request_for_question exists precisely for this and was dead
        # code: defined, never called. Real consumer impact, not just tests --
        # ask_the_syndicate_adapter.py:171 reads parsed_request off this result
        # and was silently getting {}.
        #
        # Set before the "response" copy below, so the nested alias carries it
        # too; callers read either shape.
        if not isinstance(response.get("parsed_request"), dict):
            # Prefer the engine's own parsed_request: requested_subjects is
            # resolved against the real candidate pool inside
            # run_intelligence_query and cannot be reproduced by re-parsing
            # the question (#74 -- safe to promote now that the router
            # threads mode_inferred and no longer overwrites parsed intent).
            analysis_payload = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
            analysis_parsed = analysis_payload.get("parsed_request") if isinstance(analysis_payload.get("parsed_request"), dict) else None
            response["parsed_request"] = analysis_parsed or _parsed_request_for_question(
                str(payload.get("question") or "").strip(),
                payload,
            )
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
        # Every cached read path hydrates before returning (see
        # _cached_intelligence_response_with_source) -- a fresh compute must
        # too, or top-level parlays/recommendations/portfolio only exist on
        # the nested analysis and the two branches serve different shapes.
        response = _hydrate_board_response_payload(response)
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

    if not isinstance(current.get("structured_response"), dict) or not current.get("structured_response"):
        nested_structured = nested.get("structured_response") if isinstance(nested.get("structured_response"), dict) else {}
        if not nested_structured:
            nested_analysis = nested.get("analysis") if isinstance(nested.get("analysis"), dict) else {}
            nested_structured = nested_analysis.get("structured_response") if isinstance(nested_analysis.get("structured_response"), dict) else {}
        if nested_structured:
            current["structured_response"] = dict(nested_structured)

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
        "include_props": True,
        "include_games": True,
        "force_refresh": force_refresh,
    }


def _safe_queue_intelligence_state_refresh(payload: dict[str, object]) -> None:
    try:
        queue_intelligence_state_refresh(dict(payload))
    except Exception:
        _LOGGER.warning("Intelligence refresh queue failed; serving cached or empty state instead.", exc_info=True)
    # Additive, separate from the payload-keyed queue above (see the
    # _watched_board_dates comment in pipeline/intelligence_state.py) --
    # without this, _background_loop's canonical-state drain never has
    # anything queued to write, regardless of whether
    # SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE is on. Gated behind the
    # same flag (or its shadow-compare sibling) so this is a genuine no-op
    # while both are off, matching every other canonical-store call site.
    if canonical_board_state_enabled() or canonical_board_state_shadow_compare_enabled():
        try:
            selected_date = str(payload.get("date") or payload.get("selected_date") or "").strip() or None
            queue_board_state_refresh(selected_date)
        except Exception:
            _LOGGER.warning("Canonical board-state refresh queue failed.", exc_info=True)


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
    # #93 follow-up. Same explicit-date-first check as intelligence_query_api:
    # captured before any default-injection, so a caller that passes ?date=
    # gets byte-for-byte the existing single-date page, unchanged, regardless
    # of this flag.
    explicit_date = bool(str(request.args.get("date") or "").strip())
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    if not explicit_date and combined_board_default_enabled():
        try:
            initial_response = read_combined_intelligence_response(sport="all")
            initial_response = _hydrate_board_response_payload(initial_response)
        except Exception:
            _LOGGER.exception("COMBINED_BOARD_RESPONSE_FAILURE")
            initial_response = _empty_default_intelligence_response()
        return render_template(
            "intelligence.html",
            initial_intelligence_response=initial_response,
            initial_intelligence_selected_date=None,
            initial_intelligence_today_iso=central_today_iso(),
        )
    payload = _intelligence_page_payload(selected_date, force_refresh=True)
    initial_response: dict[str, Any] = {}
    try:
        cached_loader = _cached_intelligence_response_with_source
        if hasattr(cached_loader, "call_count"):
            cached_response, _ = cached_loader(payload, force_refresh=False)
            # A stale-but-present, same-date response is still shown below --
            # only its staleness triggers a background refresh here. Showing
            # nothing while that refresh runs (which can take several minutes
            # right after a deploy, before any fresh state has been
            # persisted) is strictly worse than showing the last real board.
            if _response_needs_refresh(payload, cached_response):
                _safe_queue_intelligence_state_refresh(dict(payload))
            if isinstance(cached_response, dict) and _response_has_content(cached_response) and not _response_unsafe_to_display(payload, cached_response):
                initial_response = dict(cached_response)
            else:
                initial_response = _empty_default_intelligence_response()
        else:
            board_snapshot_response = read_latest_intelligence_board_snapshot_response(payload, force_refresh=True)
            state_response = read_latest_intelligence_state_response(payload, force_refresh=False, allow_latest_fallback=False)
            refresh_queued = False
            for response_candidate in (state_response, board_snapshot_response):
                if not isinstance(response_candidate, dict):
                    continue
                if not _response_has_board_content(response_candidate):
                    continue
                if not refresh_queued and _response_needs_refresh(payload, response_candidate):
                    _safe_queue_intelligence_state_refresh(dict(payload))
                    refresh_queued = True
                if not _response_unsafe_to_display(payload, response_candidate):
                    initial_response = dict(response_candidate)
                    break
            if not initial_response:
                if not refresh_queued:
                    _safe_queue_intelligence_state_refresh(dict(payload))
                initial_response = _empty_default_intelligence_response()
    except Exception:
        initial_response = _empty_default_intelligence_response()
    return render_template(
        "intelligence.html",
        initial_intelligence_response=initial_response,
        initial_intelligence_selected_date=selected_date,
        initial_intelligence_today_iso=selected_date,
    )


@intelligence_bp.post("/api/intelligence/query")
def intelligence_query_api():
    global LAST_RESULT
    raw_payload = request.get_json(silent=True) or {}
    # #93 follow-up. Captured from the RAW body, before _normalize_default_query_payload
    # runs below -- that function only stamps a date onto the DEFAULT
    # question, so checking here (rather than after) is what keeps this
    # backward compatible: any caller that always passes its own date (e.g.
    # ask_the_syndicate.py) is completely unaffected by anything past this
    # point, because explicit_date is True for them and the branch below is
    # never entered.
    explicit_date = bool(str(raw_payload.get("date") or raw_payload.get("selected_date") or "").strip())
    payload = _normalize_default_query_payload(raw_payload)
    question = str(payload.get("question") or "").strip()
    if not question:
        response = jsonify({"ok": False, "error": "question is required."})
        response.status_code = 400
        return _no_cache_response(response)
    if not explicit_date and combined_board_default_enabled():
        # Serves the cross-date, cross-sport combined board instead of
        # today-only -- a completely separate, read-only path from
        # everything below (which stays byte-for-byte unchanged for any
        # explicit-date request, or when this flag is off). See
        # read_combined_intelligence_response's own docstring for why it is
        # safe to call directly from a request handler: it never computes,
        # only reads what the background loop's board-window watch set
        # (_ensure_default_board_window_watched) has already built.
        try:
            requested_sport = str(payload.get("sport") or "all").strip().lower() or "all"
            response_payload = read_combined_intelligence_response(sport=requested_sport, limit=payload.get("limit"))
        except Exception:
            _LOGGER.exception("COMBINED_BOARD_RESPONSE_FAILURE")
            response_payload = None
        if isinstance(response_payload, dict):
            response_payload = _hydrate_board_response_payload(response_payload)
            response_payload.setdefault("ok", True)
            response_payload.setdefault("response", dict(response_payload))
            _attach_intelligence_response_aliases(response_payload)
            LAST_RESULT = dict(response_payload.get("response") or response_payload.get("analysis") or {})
            versioned_response = _versioned_query_response(response_payload)
            versioned_response.update(_debug_state_fields(response_payload, source="combined_board_window"))
            versioned_response["selected_date"] = None
            versioned_response["dates_covered"] = response_payload.get("dates_covered")
            _LOGGER.info(
                "BETTING_BOARD_REFRESH_COMPLETE",
                extra={"selected_date": None, "candidate_count": _response_candidate_count(response_payload), "source": "query_api_combined"},
            )
            return _no_cache_response(jsonify(versioned_response))
        # A combined-reader failure falls through to the existing today-only
        # path below rather than ever surfacing a 500.
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
                # global LAST_RESULT already declared at the top of this
                # function -- a second nested declaration here is now a
                # SyntaxError, since the new combined-board branch above
                # assigns to LAST_RESULT earlier in the function body.
                LAST_RESULT = dict(response_payload.get("response") or response_payload.get("analysis") or {})
                versioned_response = _versioned_query_response(response_payload)
                versioned_response.update(_debug_state_fields(response_payload, source="snapshot_read"))
                versioned_response["selected_date"] = str(payload.get("date") or payload.get("selected_date") or central_today_iso()).strip() or central_today_iso()
                _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
                _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": _response_candidate_count(response_payload), "source": "query_api"})
                return _no_cache_response(jsonify(versioned_response))

            # No cached snapshot exists yet for this exact payload (e.g. a
            # never-before-requested date, such as tomorrow's day-ahead
            # slate) -- the hosted branch used to stop here and always hand
            # back an empty placeholder, even though the same synchronous
            # compute path the non-hosted branch below already uses is
            # perfectly capable of answering this directly (it already
            # threads the requested date all the way through
            # build_intelligence_overview/collect_candidates, and it
            # persists its result into the same per-payload-keyed snapshot
            # store the cache read above just missed on, so this also warms
            # the cache for every subsequent request). Try it before giving
            # up -- only reached on a genuine cache miss, not on every
            # request, since a populated cache always returns above.
            try:
                computed_response = _compute_intelligence_response(payload, source="compute_refresh")
            except Exception:
                computed_response = None
                _LOGGER.exception("BETTING_BOARD_REFRESH_FAILURE")
            # Unlike the cache-hit branch above, _compute_intelligence_response's
            # return value is already the fully-versioned final response
            # shape (it calls _versioned_query_response/_debug_state_fields
            # internally, same as the non-hosted branch below relies on) --
            # re-running it through that same wrapping a second time here
            # was a bug in an earlier version of this fix, not a
            # simplification; just add the queued-refresh markers directly.
            # _response_has_board_content/_response_candidate_count expect
            # the RAW (pre-versioning) shape -- top_opportunities/
            # recommendations end up nested under "response" once versioned,
            # so they'd always read 0 here. _compute_intelligence_response
            # already computed and set a top-level "candidate_count" from
            # that same raw shape before wrapping it; use that directly
            # instead of re-deriving it from a shape that no longer has it.
            if isinstance(computed_response, dict) and int(computed_response.get("candidate_count") or 0) > 0:
                # "queued_refresh"/"execution_source"/"queued" live on the
                # NESTED "response" sub-dict in every other branch of this
                # endpoint (that's simply where _versioned_query_response
                # puts whatever fields the raw payload carried) -- computed_
                # response already carries its own "response" key from
                # _compute_intelligence_response's internal wrap, so the
                # markers have to go there too, not just on the outer dict,
                # or callers reading payload["response"]["queued_refresh"]
                # (the same place every other branch here puts it) see
                # nothing.
                versioned_response = dict(computed_response)
                nested_response = dict(versioned_response.get("response") or {})
                nested_response["queued_refresh"] = True
                nested_response["execution_source"] = "compute_refresh"
                nested_response.setdefault("queued", queued)
                versioned_response["response"] = nested_response
                LAST_RESULT = dict(nested_response.get("analysis") or nested_response)
                _LOGGER.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": versioned_response.get("candidate_count"), "source": "query_api"})
                _LOGGER.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": versioned_response.get("selected_date"), "candidate_count": versioned_response.get("candidate_count"), "source": "query_api"})
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
        slugs: set[str] = set()
        for item in _recommendation_sources(response_payload):
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


@intelligence_bp.post("/api/portfolio/bets")
def portfolio_bets_api():
    # Writes into data/prediction_ledger.json -- the same store /portfolio
    # reads (syndicate/features/prediction_ledger.py) -- unlike
    # /api/intelligence/portfolio-event above, which writes into a
    # separate evaluation ledger the Portfolio page never reads. The bet
    # slip's "Log to portfolio" action needs THIS endpoint to actually
    # show up as a position.
    try:
        payload = request.get_json(silent=True) or {}
        bet_type = str(payload.get("bet_type") or "straight").strip().lower() or "straight"
        stake = payload.get("stake")
        odds = payload.get("odds")
        recommendation_id = payload.get("recommendation_id")
        features_snapshot = {"recommendation_id": recommendation_id} if recommendation_id else None

        if bet_type == "parlay":
            legs = payload.get("legs")
            if not isinstance(legs, list) or not legs:
                response = jsonify({"ok": False, "error": "legs is required for a parlay bet."})
                response.status_code = 400
                return _no_cache_response(response)
            sport = "multi"
            market = "parlay"
            selection = f"{len(legs)}-leg parlay"
        else:
            legs = None
            sport = payload.get("sport")
            market = payload.get("market")
            selection = payload.get("selection")
            if not sport or not market or not selection:
                response = jsonify({"ok": False, "error": "sport, market, and selection are required for a straight bet."})
                response.status_code = 400
                return _no_cache_response(response)

        record = record_prediction(
            sport=sport,
            market=market,
            selection=selection,
            odds=odds,
            edge=payload.get("edge"),
            confidence=payload.get("confidence"),
            model_probability=payload.get("model_probability"),
            implied_probability=payload.get("implied_probability"),
            stake=stake,
            bet_type=bet_type,
            legs=legs,
            prediction_id=payload.get("prediction_id"),
            features_snapshot=features_snapshot,
        )
        return _no_cache_response(jsonify({"ok": True, "bet": record}))
    except Exception:
        _LOGGER.exception("PORTFOLIO BET RECORD FAILURE")
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


_GAME_CHIP_DEFAULT_SPORTS = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab"]


@intelligence_bp.get("/api/board/game-chips")
def board_game_chips_api():
    # Shared scoreboard hydration for the Layer 1 and Layer 2 mini game
    # cards: team abbreviations, live scores, and an inning/quarter/clock or
    # scheduled-start status token per game. Read-only over the same
    # artifact-backed provider payloads the home page rails use.
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    sports_raw = str(request.args.get("sports") or "").strip()
    sports = [part.strip().lower() for part in sports_raw.split(",") if part.strip()] or list(_GAME_CHIP_DEFAULT_SPORTS)
    try:
        chips = build_game_chips(selected_date, sports)
    except Exception:
        _LOGGER.exception("BOARD_GAME_CHIPS_FAILURE")
        chips = []
    return _no_cache_response(jsonify({"ok": True, "date": selected_date, "chips": chips}))


def _steam_format_odds(value: Any) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return f"{number:+.0f}"


def _steam_format_line(value: Any) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return f"{number:g}"


def _steam_event_subject(event: dict[str, Any]) -> str:
    # Confirmed live 2026-07-27: production's raw prop rows carry
    # player_name lowercase ("willy adames", not "Willy Adames") -- display
    # only, mlb_normalize_player_name's headshot-lookup key is already
    # case-insensitive so this doesn't touch matching.
    name = str(event.get("player_name") or "").strip()
    if name:
        return name.title()
    fallback = str(event.get("player_id") or event.get("game_id") or "").strip()
    return fallback or "Market"


def _steam_event_market_text(event: dict[str, Any]) -> str:
    # market_type is a raw stat slug ("batter_runs_scored") -- humanize it
    # rather than exposing OddsAPI's own vocabulary.
    market = str(event.get("market_type") or "").strip().replace("_", " ").strip()
    return market[:1].upper() + market[1:] if market else "Market"


_STEAM_NO_LINE_MARKET_TYPES = {"h2h", "moneyline"}


def _steam_event_has_real_line(event: dict[str, Any]) -> bool:
    # h2h (moneyline) rows have no genuine line -- _primary_line_value falls
    # back to the odds field itself when line/point/spread/total are all
    # absent, so current_line/current_odds (and their deltas) end up
    # numerically identical. Confirmed live 2026-07-27: "Detroit Tigers
    # H2h" showed a fabricated "-198 -> 159 line" move (really just the
    # moneyline price) outranking genuine prop line moves because
    # line_delta == odds_delta exactly matched the "real line move" test.
    # Named-market exclusion for h2h; the delta-equality check is a second,
    # market-agnostic guard for any other market shaped the same way.
    market_type = str(event.get("market_type") or "").strip().lower()
    if market_type in _STEAM_NO_LINE_MARKET_TYPES:
        return False
    steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
    line_delta = steam.get("line_delta")
    odds_delta = steam.get("odds_delta")
    if (
        isinstance(line_delta, (int, float))
        and isinstance(odds_delta, (int, float))
        and line_delta == odds_delta
        and line_delta != 0
    ):
        return False
    return True


def _steam_event_has_line_move(event: dict[str, Any]) -> bool:
    # _steam_event_has_real_line answers "can this market type have a real
    # line at all" (excludes h2h) -- a separate question from "did the line
    # actually move on THIS event." A market with a real line concept but
    # line_delta==0 (only the price moved) must not be treated as a line
    # move by significance ranking or dedup, or an odds-only move on a
    # normal prop market would wrongly collapse with its opposite side.
    steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
    line_delta = steam.get("line_delta")
    return isinstance(line_delta, (int, float)) and line_delta != 0 and _steam_event_has_real_line(event)


def _steam_event_line_text(event: dict[str, Any]) -> str:
    # selection (over/under) and line are separate fields on props
    # (_flatten_mlb_props), absent on game markets (h2h/totals/spreads), so
    # both are optional -- the card's third line is blank rather than
    # showing a bare "Line" placeholder when neither is there.
    selection = str(event.get("selection") or "").strip().capitalize()
    line = _steam_format_line(event.get("line")) if _steam_event_has_real_line(event) else None
    if selection and line:
        return f"{selection} {line}"
    return selection or line or ""


def _steam_event_dedupe_key(event: dict[str, Any]) -> tuple:
    # A real line move is one book decision, not two -- both the over and
    # the under necessarily reprice when the book moves the number, so
    # OddsAPI's two rows (one per side) produce two steam events for what a
    # viewer experiences as a single move. Confirmed live 2026-07-27 (user
    # screenshot): "Tj Friedl Over 1.5" and "Tj Friedl Under 1.5" both
    # showing the identical "0.5 -> 1.5 line" move. For a real line move,
    # selection is deliberately left OUT of the key so both sides collapse
    # together. An odds-only move (no line change) is a genuine per-side
    # signal -- one side can get bet up without the other moving at all --
    # so selection stays part of the key there and both can still show.
    subject = _steam_event_subject(event).lower()
    market_type = str(event.get("market_type") or "").strip().lower()
    game_id = str(event.get("game_id") or "").strip()
    if _steam_event_has_line_move(event):
        steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
        return (subject, market_type, game_id, "line-move", steam.get("previous_line"), event.get("line"))
    selection = str(event.get("selection") or "").strip().lower()
    return (subject, market_type, game_id, selection, event.get("price"))


def _steam_event_side_priority(event: dict[str, Any]) -> int:
    # Tiebreak for which side survives dedup when a real line move produces
    # an identical key for both -- "over" is the conventional default a
    # sportsbook leads with, so it wins the tie deterministically rather
    # than depending on which row happened to sort/arrive first.
    selection = str(event.get("selection") or "").strip().lower()
    return {"over": 0, "under": 1}.get(selection, 2)


def _steam_event_significance(event: dict[str, Any]) -> tuple[int, float]:
    # User-directed ranking (2026-07-27): a move that actually shifted the
    # line outranks every odds-only move regardless of size -- a real line
    # move is the harder, more informative signal (the book adjusted the
    # number, not just repriced around it). Within each tier, biggest
    # magnitude first.
    steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
    if _steam_event_has_line_move(event):
        return (1, abs(steam.get("line_delta")))
    odds_delta = steam.get("odds_delta")
    magnitude = abs(odds_delta) if isinstance(odds_delta, (int, float)) else 0.0
    return (0, magnitude)


def _steam_event_movement_lines(event: dict[str, Any]) -> list[str]:
    # Two separate lines (odds move, line move), not one joined string -- a
    # card with both ("-147 -> +220 · 0.5 -> 1.5 line") overflowed the
    # narrow movement column (confirmed live 2026-07-27, user screenshot).
    # Each one is short enough to fit its own line; only the combined
    # string wasn't.
    steam = event.get("steam") if isinstance(event.get("steam"), dict) else {}
    parts = []
    prev_odds = _steam_format_odds(steam.get("previous_odds"))
    curr_odds = _steam_format_odds(event.get("price"))
    if prev_odds and curr_odds and prev_odds != curr_odds:
        parts.append(f"{prev_odds} → {curr_odds}")
    if _steam_event_has_real_line(event):
        prev_line = _steam_format_line(steam.get("previous_line"))
        curr_line = _steam_format_line(event.get("line"))
        if prev_line and curr_line and prev_line != curr_line:
            parts.append(f"{prev_line} → {curr_line} line")
    return parts or ["Movement detected"]


@intelligence_bp.get("/api/board/steam")
def board_steam_api():
    # #83's actuator surface: the bounded per-date steam record
    # (odds_refresh_tracking.py's _record_steam_events, capped at 200) read
    # back for the Layer 2 board's steam rail. Deliberately reads the same
    # small file the ops artifact-export debug endpoint already serves
    # rather than the raw per-observation lifecycle log -- see the pattern
    # note in artifact_publisher.py's HOT_ARTIFACT_PATTERNS.
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    try:
        limit = max(1, min(50, int(request.args.get("limit") or 12)))
    except (TypeError, ValueError):
        limit = 12
    events: list[dict[str, Any]] = []
    try:
        path = reports_root() / "steam" / f"steam_events_{selected_date}.json"
        payload = read_json_file(path)
        raw_events = payload.get("events") if isinstance(payload, dict) else None
        if isinstance(raw_events, list):
            events = [event for event in raw_events if isinstance(event, dict)]
    except Exception:
        _LOGGER.exception("BOARD_STEAM_READ_FAILURE")
        events = []
    # Ranked by significance (real line move first, then magnitude), not
    # recency -- the whole bounded 200-event set is in play, not just the
    # newest `limit`, since a big move from a few cycles ago should still
    # outrank a tiny move that happened a minute later. The timestamp on
    # each card is what tells the viewer how fresh it is. Side priority
    # ("over" before "under") only breaks ties between events that will
    # collapse to the same dedupe key below -- it doesn't otherwise affect
    # ranking, since significance is compared first.
    ranked = sorted(events, key=lambda event: (_steam_event_significance(event), -_steam_event_side_priority(event)), reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple] = set()
    for event in ranked:
        key = _steam_event_dedupe_key(event)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(event)
    recent = deduped[:limit]
    # Headshots need a real MLBAM player ID, which the raw OddsAPI prop rows
    # never carry (only a display name) -- resolved via the day's roster
    # snapshots (hr_targets.mlb_player_id_lookup_for_date), same source
    # hr_targets/k_ladder_targets already use for headshots elsewhere. Only
    # built if this batch actually has an MLB event to look up, and only
    # once per request regardless of how many MLB events are in it.
    mlb_id_lookup: dict[str, int] | None = None
    for event in recent:
        subject = _steam_event_subject(event)
        market_text = _steam_event_market_text(event)
        line_text = _steam_event_line_text(event)
        event["subject"] = subject
        event["market_text"] = market_text
        event["line_text"] = line_text
        event["label"] = f"{subject} — {market_text}" if subject != "Market" else market_text
        movement_lines = _steam_event_movement_lines(event)
        event["movement_lines"] = movement_lines
        event["movement_text"] = " · ".join(movement_lines)
        event["headshot_url"] = None
        if str(event.get("sport") or "").strip().lower() == "mlb" and event.get("player_name"):
            if mlb_id_lookup is None:
                try:
                    from syndicate.features.mlb.hr_targets import mlb_player_id_lookup_for_date

                    mlb_id_lookup = mlb_player_id_lookup_for_date(selected_date)
                except Exception:
                    _LOGGER.exception("BOARD_STEAM_HEADSHOT_LOOKUP_FAILURE")
                    mlb_id_lookup = {}
            from syndicate.features.mlb.hr_targets import mlb_headshot_url_for_player, mlb_normalize_player_name

            player_id = mlb_id_lookup.get(mlb_normalize_player_name(event.get("player_name")))
            if player_id:
                event["headshot_url"] = mlb_headshot_url_for_player(player_id)
    return _no_cache_response(jsonify({"ok": True, "date": selected_date, "count": len(recent), "events": recent}))


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