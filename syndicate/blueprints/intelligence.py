from __future__ import annotations

import logging
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from flask import Blueprint, jsonify, make_response, render_template, request
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
from syndicate.features.intelligence import _market_focus_labels
from syndicate.features.intelligence import _parlay_request_summary
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import _attach_intelligence_response_aliases
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.shared.json_safety import json_safe_value
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
from syndicate.features.prediction_ledger import delete_prediction
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


def _json_safe_value(value: object) -> object:
    # Moved to syndicate/features/shared/json_safety.py 2026-08-04 and wired
    # into the Flask app's own JSON provider (syndicate/app.py) after the
    # same NaN-in-JSON failure this was built for (2026-07-31, see that
    # module's docstring) recurred in a second, unrelated blueprint
    # (ask_the_syndicate.py) that this call-site-scoped version never
    # covered. Kept as a thin alias -- this module's own call sites and
    # tests still import the name from here.
    return json_safe_value(value)


def _response_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _versioned_query_response(response_payload: dict[str, object]) -> dict[str, object]:
    response_payload = _json_safe_value(dict(response_payload))
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
    # Imported here, not at module load, so this always sees whatever object
    # pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE currently names
    # -- a top-level `from ... import _INTELLIGENCE_STATE_SERVICE` would bind
    # the name ONCE at blueprint-import time, silently ignoring any later
    # `patch("pipeline.intelligence_state._INTELLIGENCE_STATE_SERVICE", ...)`
    # (tests need real isolation here; ops.py's admin candidate-trace debug
    # endpoint already imports it the same lazy way for this exact reason).
    from pipeline.intelligence_state import _INTELLIGENCE_STATE_SERVICE

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
            # _parsed_request_for_question builds the UI-facing summary shape
            # (timing/board_scope/chips/sports/etc, see _parlay_request_summary)
            # -- this is always the base. The engine's OWN parsed_request
            # (run_intelligence_query's final_response["parsed_request"]) is a
            # different, raw-preferences shape with none of those display
            # fields, but its requested_subjects/requested_markets ARE
            # resolved against the real candidate pool and can't be
            # reproduced by re-parsing the question text alone (#74) -- so
            # overlay just those two fields when the engine actually
            # resolved something, rather than replacing the whole dict
            # wholesale (confirmed live 2026-07-28: wholesale replacement
            # silently dropped timing/sports/chips from every query response,
            # since the engine's dict never carried them in the first place).
            analysis_payload = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
            analysis_parsed = analysis_payload.get("parsed_request") if isinstance(analysis_payload.get("parsed_request"), dict) else None
            parsed_request = _parsed_request_for_question(
                str(payload.get("question") or "").strip(),
                payload,
            )
            if isinstance(analysis_parsed, dict):
                for engine_field in ("requested_subjects", "requested_markets"):
                    engine_value = analysis_parsed.get(engine_field)
                    if engine_value:
                        parsed_request[engine_field] = engine_value
            response["parsed_request"] = parsed_request
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


# The row lists a board response can carry. Named explicitly rather than
# discovered by walking the payload: a loose "does it look like a row?" walk
# over this response descends into every nested quote and alternatives entry and
# reported 101,648 "rows" for a 150-row board, which is how you end up
# annotating a price as if it were an opportunity.
_BOARD_ROW_LIST_KEYS = (
    "recommendations",
    "top_opportunities",
    "top_live_opportunities",
    "ranked_all",
)


def _regate_board_rows(payload: dict[str, object]) -> None:
    """Re-run the eligibility gate over every row, at SERVE time (#245).

    This is what removes the need for the board's client-side copy of the
    staleness rule. `board_lane` is stamped during enrichment, but a candidate
    pool can be republished from cache for a long time -- measured: capture age
    pinned at 7,806s across four polls eight minutes apart -- so a lane decided
    at build time can be badly out of date by the time anyone reads it. The gate
    is a pure function over the row, so running it again here costs nothing and
    means the answer is always current as of the request.

    Mutates in place, over explicitly named lists, including the duplicated
    `response.*` copies. Never raises.
    """
    try:
        from syndicate.features.shared.opportunity_gate import annotate

        seen: list[dict[str, object]] = []
        for container in (payload, payload.get("response") if isinstance(payload.get("response"), dict) else {}):
            if not isinstance(container, dict):
                continue
            for key in _BOARD_ROW_LIST_KEYS:
                rows = container.get(key)
                if isinstance(rows, list):
                    seen.extend(row for row in rows if isinstance(row, dict))
            by_sport = container.get("by_sport")
            if isinstance(by_sport, dict):
                for rows in by_sport.values():
                    if isinstance(rows, list):
                        seen.extend(row for row in rows if isinstance(row, dict))
        for row in seen:
            annotate(row)
    except Exception:
        return


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

    _refresh_live_columns_from_artifact(current)

    # #245: the gate is the LAST word on which lane a row is in, and it runs
    # here so the answer is current as of this request rather than as of
    # whenever the pool was last built.
    _regate_board_rows(current)
    return current


# Only the two columns that go stale by the minute. Everything else on a
# card is a property of the bet, not of the game clock, and stays owned by
# the worker's build.
_LIVE_ARTIFACT_COLUMNS = ("live_projection", "actual")


def _matchup_key(value: object) -> str:
    return " ".join(str(value or "").upper().replace("@", " ").split())


def _live_lens_game_index(context_label: str, report_cache: dict, index_cache: dict) -> dict | None:
    """Index the live-lens report once per request: pk -> game, matchup -> game.

    Built here rather than per candidate because a busy slate has hundreds of
    candidates over ~15 games, and the report is the same document for all of
    them.
    """
    if context_label in index_cache:
        return index_cache[context_label]
    try:
        from syndicate.features.intelligence import _mlb_live_lens_report_cached
        from syndicate.features.intelligence import _safe_int

        report = _mlb_live_lens_report_cached(context_label, report_cache)
        games = report.get("games") if isinstance(report, dict) else None
        if not isinstance(games, list):
            index_cache[context_label] = None
            return None
        by_pk: dict[int, dict] = {}
        by_matchup: dict[str, dict] = {}
        for game in games:
            if not isinstance(game, dict):
                continue
            status = game.get("status") if isinstance(game.get("status"), dict) else {}
            is_live = str(status.get("abstract") or "").strip().lower() == "live"
            rows = game.get("trackedProps")
            if not (isinstance(rows, list) and rows):
                rows = game.get("props") if isinstance(game.get("props"), list) else []
            entry = {"is_live": is_live, "rows": [row for row in rows if isinstance(row, dict)]}
            game_pk = _safe_int(game.get("gamePk"))
            if game_pk:
                by_pk[game_pk] = entry
            matchup = game.get("matchup") if isinstance(game.get("matchup"), dict) else {}
            away = (matchup.get("away") or {}).get("abbr") if isinstance(matchup.get("away"), dict) else None
            home = (matchup.get("home") or {}).get("abbr") if isinstance(matchup.get("home"), dict) else None
            if away and home:
                by_matchup[_matchup_key(f"{away} {home}")] = entry
        index_cache[context_label] = {"by_pk": by_pk, "by_matchup": by_matchup}
    except Exception:
        index_cache[context_label] = None
    return index_cache[context_label]


def _refresh_live_columns_from_artifact(payload: dict[str, object]) -> None:
    """Re-read LIVE PROJ. / LIVE ACTUAL from the live-lens artifact at read time.

    These two columns were only ever written during refresh-worker's board
    build, so they aged at the build cadence -- minutes -- while the values
    they display change every pitch. Confirmed live 2026-08-05: the board
    showed live_projection on 1 of 9 live MLB props for over 15 minutes,
    while web's OWN live-lens artifact was 3 minutes old and carried 329
    tracked props with real actual/liveProjection for every live game. The
    numbers were already sitting on this box; nothing was reading them.

    This is a read-path refresh of two display fields from an artifact the
    web service already has, which is the "light transformation for display"
    the runtime split allows -- not a recompute. It does NOT call
    run_intelligence_query, rebuild a candidate pool, or touch the sim. If
    the artifact is missing or unreadable the card keeps whatever the build
    gave it, exactly as before.

    Deliberately narrow: only candidates already flagged is_live, only the
    two clock-sensitive columns, and one cached artifact read per request
    regardless of how many candidates match.
    """
    try:
        from syndicate.features.intelligence import _mlb_hydrate_live_prop_projection
        from syndicate.features.intelligence import _mlb_live_lens_prop_rows_for_game
        from syndicate.features.intelligence import _safe_int
    except Exception:
        return

    collections = [key for key in ("top_opportunities", "top_live_opportunities", "recommendations", "ranked_all") if isinstance(payload.get(key), list)]
    by_sport = payload.get("by_sport") if isinstance(payload.get("by_sport"), dict) else {}

    report_cache: dict[str, dict | None] = {}
    index_cache: dict[str, dict | None] = {}
    refreshed = 0
    promoted = 0

    def _visit(candidate: object) -> None:
        nonlocal refreshed, promoted
        if not isinstance(candidate, dict):
            return
        if str(candidate.get("sport_slug") or "").lower() != "mlb":
            return
        context_label = str(candidate.get("game_date") or candidate.get("source_board_date") or "").strip()
        if not context_label:
            return
        index = _live_lens_game_index(context_label, report_cache, index_cache)
        if not index:
            return

        # Resolve the game by pk, falling back to the matchup abbreviations.
        # Confirmed live 2026-08-05: game_pk is blank on a fifth of MLB
        # candidates (4 of 12 present for CWS @ BOS), and a candidate with no
        # game identity could be matched to nothing at all.
        game_pk = _safe_int(candidate.get("game_pk") or candidate.get("gamePk") or candidate.get("game_id"))
        entry = index["by_pk"].get(game_pk) if game_pk else None
        if entry is None:
            entry = index["by_matchup"].get(_matchup_key(candidate.get("matchup")))
        if entry is None:
            return

        # is_live was set per candidate during the build and disagreed with
        # reality both across and WITHIN games: 8 MLB games were live while
        # only 4 matchups had any candidate flagged, and PIT @ MIL had live
        # numbers on 4 candidates with zero flagged live. The artifact's own
        # per-game status is the authoritative, minutes-fresh answer, so use
        # it rather than whatever the build happened to stamp. Only promotes
        # to live -- demoting a card the build considers live is a bigger
        # behaviour change than this read-path refresh should make.
        if entry["is_live"] and not candidate.get("is_live"):
            candidate["is_live"] = True
            candidate.setdefault("lane", "live")
            promoted += 1

        rows = entry["rows"]
        if not rows:
            return
        before = {column: candidate.get(column) for column in _LIVE_ARTIFACT_COLUMNS}
        _mlb_hydrate_live_prop_projection(candidate, rows)
        if any(candidate.get(column) != before[column] for column in _LIVE_ARTIFACT_COLUMNS):
            refreshed += 1

    try:
        for key in collections:
            for candidate in payload.get(key) or []:
                _visit(candidate)
        for items in by_sport.values():
            if isinstance(items, list):
                for candidate in items:
                    _visit(candidate)
    except Exception as exc:  # never break the board over a display refresh
        _LOGGER.warning("LIVE_COLUMN_REFRESH_FAILED %s: %s", type(exc).__name__, exc)
        return

    if refreshed:
        print(f"[intelligence] LIVE_COLUMNS_REFRESHED_FROM_ARTIFACT candidates={refreshed}", flush=True)


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
    # #93 follow-up, extended alongside intelligence_query_api's identical
    # fix (see that function's comment for the full "why"): an explicit
    # ?date= now still uses the combined-board reader, just windowed to that
    # one date, instead of dropping to the older single-date cascade below.
    explicit_date_value = str(request.args.get("date") or "").strip()
    explicit_date = bool(explicit_date_value)
    selected_date = explicit_date_value or central_today_iso()
    if combined_board_default_enabled():
        try:
            requested_dates = [explicit_date_value] if explicit_date else None
            initial_response = read_combined_intelligence_response(dates=requested_dates, sport="all")
            initial_response = _hydrate_board_response_payload(initial_response)
        except Exception:
            _LOGGER.exception("COMBINED_BOARD_RESPONSE_FAILURE")
            initial_response = _empty_default_intelligence_response()
        return render_template(
            "intelligence.html",
            initial_intelligence_response=initial_response,
            initial_intelligence_selected_date=selected_date if explicit_date else None,
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
    # question, so checking here (rather than after) is what keeps a caller
    # that always passes its own date (e.g. ask_the_syndicate.py) scoped to
    # exactly that date below: explicit_date_value carries the caller's real
    # requested date into the combined-board branch's `dates=[...]` window,
    # instead of `_normalize_default_query_payload`'s stamped default
    # silently widening it to the full cross-date window.
    explicit_date_value = str(raw_payload.get("date") or raw_payload.get("selected_date") or "").strip()
    explicit_date = bool(explicit_date_value)
    payload = _normalize_default_query_payload(raw_payload)
    question = str(payload.get("question") or "").strip()
    if not question:
        response = jsonify({"ok": False, "error": "question is required."})
        response.status_code = 400
        return _no_cache_response(response)
    if combined_board_default_enabled():
        # Serves the cross-date, cross-sport combined board instead of the
        # older single-date snapshot_read/board_snapshot cascade below. #114
        # (todo.md) closed one accidental trigger into that older cascade
        # (a background poll silently carrying a stale client-side date);
        # #111/#113 closed two more -- all three were different ways an
        # explicit date snuck in, and every one of them was fixed by keeping
        # the request off this branch entirely rather than by making this
        # branch handle a date. That whack-a-mole was the actual bug: this
        # branch could always serve a single explicit date too --
        # read_combined_intelligence_response already takes a `dates` list,
        # windowed to exactly one date when the caller wants exactly one
        # date -- so there was never a structural reason for an explicit
        # date to leave this path. Confirmed live 2026-07-28 that skipping
        # this branch on any explicit date was the actual root cause of the
        # user-visible "different sources, varying numbers" complaint: the
        # same nominal "today" query returned 72 candidates
        # (combined_board_window, no date) vs. 54 (snapshot_read, explicit
        # date=today) from the live API, not a UI artifact. See
        # read_combined_intelligence_response's own docstring for why it is
        # safe to call directly from a request handler: it never computes,
        # only reads what the background loop's board-window watch set
        # (_ensure_default_board_window_watched) has already built.
        try:
            requested_sport = str(payload.get("sport") or "all").strip().lower() or "all"
            requested_dates = [explicit_date_value] if explicit_date else None
            response_payload = read_combined_intelligence_response(dates=requested_dates, sport=requested_sport, limit=payload.get("limit"))
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
            # Was unconditionally None -- correct back when this branch was
            # only ever reached for the dateless default query. Now that an
            # explicit single date also routes here (see the comment above),
            # leaving this None would un-fix #113/#114: both of those wired
            # intelligence.html's board-freshness-chip and #board-date input
            # sync off this exact field, and a None here for an explicit-date
            # request would read as "no date selected" again.
            versioned_response["selected_date"] = explicit_date_value if explicit_date else None
            versioned_response["dates_covered"] = response_payload.get("dates_covered")
            _LOGGER.info(
                "BETTING_BOARD_REFRESH_COMPLETE",
                extra={"selected_date": versioned_response["selected_date"], "candidate_count": _response_candidate_count(response_payload), "source": "query_api_combined"},
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
            # slate). #109 follow-up, 2026-07-27: this used to fall through to
            # a synchronous _compute_intelligence_response(...) call right
            # here -- i.e. a full candidate-pool build running INSIDE the web
            # request handler, on the memory-constrained web container.
            # Confirmed live: a single request with a novel question/payload
            # (never matching the background loop's own cached key) drove web
            # to 100% memory / 0MB headroom. That directly violates this
            # repo's load-bearing rule -- web does no heavy computation,
            # intelligence runs on refresh-worker (4GB) via the background
            # loop, web only ever reads what it already computed. Always
            # return the queued/empty placeholder on a cache miss instead;
            # the caller's own _safe_queue_intelligence_state_refresh call
            # just above already told refresh-worker to build this payload,
            # and the next poll will get a real answer once that lands.
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


def _quote_ref_for_payload(source: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any] | None:
    """Look up the per-book quote behind one logged bet (or one parlay leg).

    Never raises: failing to resolve a quote must not stop a bet being logged.
    A bet with no quote is worse than one with a quote, but a bet that silently
    404s because the odds log was mid-write is worse than both.
    """
    try:
        from syndicate.features.shared.odds_book_quotes import quote_ref_for_bet

        date_str = (
            source.get("game_date")
            or fallback.get("game_date")
            or fallback.get("selected_date")
            or central_today_iso()
        )
        return quote_ref_for_bet(
            sport=source.get("sport") or fallback.get("sport"),
            date_str=str(date_str)[:10],
            event_id=source.get("event_id") or fallback.get("event_id"),
            market=source.get("market") or fallback.get("market"),
            selection=source.get("pick") or source.get("selection"),
            line=source.get("line"),
            player_name=source.get("player_name") or source.get("player"),
            bookmaker=source.get("bookmaker") or source.get("book"),
        )
    except Exception:
        _LOGGER.exception("PORTFOLIO BET QUOTE LOOKUP FAILURE")
        return None


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
        # Key names match what prediction_reconciliation.py's _prediction_keys/
        # _prediction_date already read from features_snapshot (event_id/
        # game_id/line/selected_date/date/game_date) -- no reconciliation
        # read-side changes needed for those. "pick" (the wagered Over/Under
        # side) is new: without it, a straight prop bet's ledger entry has no
        # way to be graded even once real actual/line data exists, since
        # `selection` is the player's name, not the side.
        features_snapshot_fields = {
            "recommendation_id": recommendation_id,
            "pick": payload.get("pick"),
            "line": payload.get("line"),
            "event_id": payload.get("event_id"),
            "game_date": payload.get("game_date"),
        }
        features_snapshot = {key: value for key, value in features_snapshot_fields.items() if value not in (None, "")} or None

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

        # Record the price we struck at, across every book quoting it. This is
        # the OPENING half of CLV; nothing else in the system captures it, and a
        # bet logged without it can never have a closing-line value no matter
        # what settlement does later. Unrecorded here is unrecoverable -- the
        # same failure as #208, where the books were lost not by decision but
        # because nothing wrote them down. Per-leg for a parlay, since each leg
        # has its own market and its own close.
        if bet_type == "parlay":
            for leg in legs or []:
                if not isinstance(leg, dict) or leg.get("quote"):
                    continue
                resolved = _quote_ref_for_payload(leg, fallback=payload)
                # Only stamp a leg when a quote actually resolved -- writing
                # `quote: None` onto every leg would change the stored shape of
                # legs that have nothing to say, for no gain.
                if resolved:
                    leg["quote"] = resolved
            quote = None
        else:
            quote = _quote_ref_for_payload(payload, fallback=payload)

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
            quote=quote,
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


_GAME_CHIP_DEFAULT_SPORTS = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]


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


def _attach_book_grid_game_state(grid: list, *, sport: str, selected_date: str) -> dict:
    """Stamp start time (pregame) or live status (in-progress) onto grid rows.

    Joined on the TEAM PAIR through `team_aliases`, not on string equality:
    quote rows carry full club names ("Baltimore Orioles") while the scoreboard
    carries tri-codes ("BAL"). `#218` established that a pure string heuristic
    cannot do this -- "chc" is neither a prefix of "chicago" nor the initials of
    "chicago cubs" -- and that single gap is why 0 of 108 board candidates
    carried a quote on 2026-08-06.
    """
    matched = 0
    try:
        from syndicate.features.shared.game_chip_scoreboard import build_game_chips
        from syndicate.features.shared.team_aliases import teams_match

        chips = build_game_chips(selected_date, [sport]) or []
    except Exception:
        _LOGGER.exception("BOOK_GRID_GAME_STATE_FAILURE sport=%s date=%s", sport, selected_date)
        return {"chips": 0, "rows_matched": 0}

    for row in grid:
        home = row.get("home_team")
        away = row.get("away_team")
        if not home or not away:
            continue
        for chip in chips:
            chip_home = ((chip.get("home") or {}) or {}).get("abbr")
            chip_away = ((chip.get("away") or {}) or {}).get("abbr")
            if not chip_home or not chip_away:
                continue
            try:
                if teams_match(sport, home, chip_home) and teams_match(sport, away, chip_away):
                    row["game"] = {
                        "state": chip.get("state"),
                        "start_time_utc": chip.get("start_time_utc"),
                        "status_token": chip.get("status_token"),
                        "matchup": chip.get("matchup"),
                        "home_score": (chip.get("home") or {}).get("score"),
                        "away_score": (chip.get("away") or {}).get("score"),
                    }
                    matched += 1
                    break
            except Exception:
                continue
    return {"chips": len(chips), "rows_matched": matched}


def _attach_book_grid_projections(grid: list, *, sport: str, selected_date: str) -> dict:
    """Stamp the sim's projection and edge onto player-prop rows (S3).

    MLB only for now, and that is stated rather than silently returning zero:
    the daily-summary shape this reads is MLB's. Other sports return a coverage
    payload saying so, so a blank column is attributable instead of mysterious.
    """
    if sport != "mlb":
        return {"supported": False, "reason": f"no projection source wired for {sport}"}
    try:
        from syndicate.features.mlb.sources import daily_artifact_path
        from syndicate.features.shared.prop_projections import (
            attach_projections,
            load_prop_projections,
        )

        summary_path = daily_artifact_path(selected_date)
        snapshot_dir = Path(summary_path).parent / "snapshots" / selected_date
        index = load_prop_projections(summary_path, roster_snapshot_dir=snapshot_dir)
        coverage = attach_projections(grid, index)
        coverage["supported"] = True
        coverage["summary_artifact"] = str(summary_path)
        coverage["games_in_summary"] = index.games
        return coverage
    except Exception:
        _LOGGER.exception("BOOK_GRID_PROJECTION_FAILURE sport=%s date=%s", sport, selected_date)
        return {"supported": True, "error": "projection join failed", "rows_with_projection": 0}


def _attach_book_grid_margin_model(grid: list) -> dict:
    """Fill fair value on one-sided rows from each book's measured margin (S4).

    The profile is built from THIS slate's two-sided markets rather than carried
    as a constant: holds move with the book, the sport and the day, and a stale
    constant is the defect class this codebase has paid for most often (a 900MB
    floor sized for a 2GB container; a 2.3MB payload figure describing a system
    that had changed underneath it).

    Never displaces a measured two-sided fair value -- it only fills rows that
    have none, and everything it writes is labelled
    `fair_method: "book_margin_model"`.
    """
    try:
        from syndicate.features.shared.book_margin_model import (
            apply_margin_model,
            build_margin_profile,
        )

        profile = build_margin_profile(grid)
        return apply_margin_model(grid, profile)
    except Exception:
        _LOGGER.exception("BOOK_GRID_MARGIN_MODEL_FAILURE")
        return {"rows_modelled": 0, "error": "margin model failed"}


@intelligence_bp.get("/api/board/book-grid")
def board_book_grid_api():
    """L1-A: every book's price for every market on a sport/date (S1).

    A SERVE-TIME PIVOT over `book_quotes`, which already holds every book -- 11
    captured on MLB while the board rendered one "best" price. It reads one
    shard and reshapes it; it computes no simulation, generates no artifact and
    adds nothing to any worker. That is what let S1 ship while refresh-worker
    was under a memory observation hold.

    Rows are NOT filtered by quality. This is the Layer 1 research surface: a
    single-book row, or one whose best price is a stale line, still belongs here
    and arrives carrying `gaps` explaining why it is thin. Layer 2 is the
    shortlist; filtering here would make the board look complete when the
    capture is not.
    """
    from syndicate.features.shared.book_grid import book_grid_summary, build_book_grid
    from syndicate.features.shared.odds_book_quotes import read_book_quotes

    sport = str(request.args.get("sport") or "mlb").strip().lower()
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    market_filter = str(request.args.get("market") or "").strip().lower()
    try:
        limit = max(1, min(2000, int(str(request.args.get("limit") or "300").strip())))
    except ValueError:
        limit = 300

    try:
        rows = read_book_quotes(sport, selected_date)
    except Exception:
        _LOGGER.exception("BOARD_BOOK_GRID_READ_FAILURE sport=%s date=%s", sport, selected_date)
        rows = []

    try:
        grid = build_book_grid(rows)
    except Exception:
        _LOGGER.exception("BOARD_BOOK_GRID_BUILD_FAILURE sport=%s date=%s", sport, selected_date)
        grid = []

    # Game state: a start time for pregames, a live status for in-progress
    # games. Not decoration -- it is what makes `age_seconds` readable. A
    # 40-minute-old price on a game that starts in six hours is normal; the same
    # age on a game in the 7th is a dead line, and #244/#245 already drop those
    # from Layer 2 for exactly that reason. Layer 1 shows them and says why.
    game_state_coverage = _attach_book_grid_game_state(grid, sport=sport, selected_date=selected_date)

    # S3: the sim's projection next to the market's price -- the differentiator.
    # Reads the daily-summary artifact directly rather than going through
    # build_cards_page_context, which is the call that OOM-killed the worker.
    projection_coverage = _attach_book_grid_projections(grid, sport=sport, selected_date=selected_date)

    # S4: fair value for markets the feed only ever quotes ONE side of, from the
    # book's own measured margin. De-vig needs both sides, so ~24% of rows had
    # no fair value at all -- `batter_home_runs` is 100% `over` across all 11
    # books, so the other side cannot be captured at any cadence. Measured from
    # this slate's two-sided markets, never a carried constant.
    margin_coverage = _attach_book_grid_margin_model(grid)

    # Summarise BEFORE the market filter and the limit, so the coverage numbers
    # describe the slate rather than the current view. A summary computed after
    # filtering would report "100% of rows have 3+ books" on a filtered view and
    # be technically true and completely misleading.
    summary = book_grid_summary(grid)

    # Market taxonomy for the board's game/prop selector. Computed HERE, before
    # the market filter, for the same reason the summary is: it must describe the
    # slate, not the current view, or selecting one market would empty the
    # selector that got you there.
    #
    # Served rather than re-derived on the client. Every row already carries the
    # `kind` this pivots on, so a client-side "is this market a game line?" name
    # test would be the same rule written twice in two languages -- which is #244,
    # removed in #245 for exactly this reason.
    market_kinds: dict[str, str] = {}
    for row in grid:
        market_name = str(row.get("market") or "")
        row_kind = str(row.get("kind") or "")
        if market_name and row_kind:
            market_kinds.setdefault(market_name, row_kind)

    if market_filter:
        grid = [row for row in grid if str(row.get("market") or "").lower() == market_filter]

    markets = sorted({str(row.get("market") or "") for row in grid if row.get("market")})
    return _no_cache_response(
        jsonify(
            {
                "ok": True,
                "sport": sport,
                "date": selected_date,
                "market": market_filter or None,
                "markets": markets,
                "market_kinds": market_kinds,
                "summary": summary,
                "game_state": game_state_coverage,
                "projections": projection_coverage,
                "margin_model": margin_coverage,
                "returned": min(len(grid), limit),
                "total_rows": len(grid),
                "rows": grid[:limit],
                "server_time": _server_timestamp(),
            }
        )
    )


@intelligence_bp.get("/api/board/cross-book")
def board_cross_book_api():
    """L2-B (arbitrage) and L2-C (low hold), over prices that COEXISTED (#261).

    A SERVE-TIME pivot on the same `market_row` the book grid serves -- §3's
    one-row-contract rule. It computes no simulation and adds nothing to any
    worker.

    Both boards come from ONE search, because arb profit is `1/overround - 1`
    and hold is `overround - 1`: "best arb" and "lowest hold" are the same
    question. `view` filters the result; it does not run a second pipeline.

    The two guards live in `board_cross_book` and both are load-bearing:
    SIMULTANEITY (an all-day append log otherwise pairs an 08:33Z price with an
    18:43Z one) and COMPLEMENTARITY (books disagree on line sign within a row,
    which is `#262`). Without the second, this endpoint reported a +250.88%
    arbitrage on production; with it, two real ones at +3.88% and +1.10%.

    `max_skew_seconds` is exposed because it is a judgement, not a constant: at
    a ~26-minute capture cadence a window tighter than the cadence returns
    nothing. Every row reports the skew it actually used.
    """
    from syndicate.features.shared.board_cross_book import (
        DEFAULT_MAX_SKEW_SECONDS,
        cross_book_opportunities,
        cross_book_summary,
    )
    from syndicate.features.shared.book_grid import build_book_grid
    from syndicate.features.shared.odds_book_quotes import read_book_quotes

    sport = str(request.args.get("sport") or "mlb").strip().lower()
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    view = str(request.args.get("view") or "all").strip().lower()
    try:
        limit = max(1, min(2000, int(str(request.args.get("limit") or "300").strip())))
    except ValueError:
        limit = 300
    try:
        max_skew = float(str(request.args.get("max_skew_seconds") or DEFAULT_MAX_SKEW_SECONDS).strip())
    except ValueError:
        max_skew = DEFAULT_MAX_SKEW_SECONDS
    max_skew = max(0.0, min(86400.0, max_skew))
    try:
        low_hold_threshold = float(str(request.args.get("low_hold_pct") or "2.0").strip())
    except ValueError:
        low_hold_threshold = 2.0

    try:
        rows = read_book_quotes(sport, selected_date)
    except Exception:
        _LOGGER.exception("BOARD_CROSS_BOOK_READ_FAILURE sport=%s date=%s", sport, selected_date)
        rows = []

    try:
        grid = build_book_grid(rows)
    except Exception:
        _LOGGER.exception("BOARD_CROSS_BOOK_BUILD_FAILURE sport=%s date=%s", sport, selected_date)
        grid = []

    # Game state before the pivot, so each opportunity carries live/pregame with
    # it. A live arb and a pregame arb are not the same product, and #245 drops
    # dead markets on exactly this signal.
    game_state_coverage = _attach_book_grid_game_state(grid, sport=sport, selected_date=selected_date)

    try:
        opportunities = cross_book_opportunities(
            grid, max_skew_seconds=max_skew, low_hold_threshold_pct=low_hold_threshold
        )
    except Exception:
        _LOGGER.exception("BOARD_CROSS_BOOK_PIVOT_FAILURE sport=%s date=%s", sport, selected_date)
        opportunities = []

    # Summarise BEFORE the view filter, same rule as the book grid: the counts
    # describe the slate, so "2 arbs of 829 priced" stays legible on the arb tab.
    summary = cross_book_summary(opportunities)

    if view == "arb":
        selected = [row for row in opportunities if row.get("is_arbitrage")]
    elif view in {"low_hold", "low-hold"}:
        selected = [row for row in opportunities if row.get("is_low_hold")]
    else:
        selected = list(opportunities)

    return _no_cache_response(
        jsonify(
            {
                "ok": True,
                "sport": sport,
                "date": selected_date,
                "view": view,
                "max_skew_seconds": max_skew,
                "low_hold_pct": low_hold_threshold,
                "summary": summary,
                "game_state": game_state_coverage,
                "returned": min(len(selected), limit),
                "total_rows": len(selected),
                "rows": selected[:limit],
                "server_time": _server_timestamp(),
            }
        )
    )


@intelligence_bp.get("/market-board/books")
def market_board_books_page():
    """L1-A, the book grid — the BOOK VIEW of the Layer 1 market board (S1).

    Lives under `/market-board` on purpose. That hub already is the Layer 1
    family — its own copy reads "every quoted line for every game … not just
    the recommendation engine's picks" — and routes to `/<sport>/market-board`
    per sport. This is the same inventory pivoted by BOOK instead of by game, so
    it belongs in that family rather than as an orphan page.

    It is NOT part of Layer 2 and does not replace it. `/` is the consolidated
    L2 recommendation surface; that answers "what should I bet". This answers
    "show me every price". Collapsing them would lose the shortlist, which is
    the product.

    Sport-switchable in one page rather than one route per sport, because the
    grid is identical across sports — only the market vocabulary differs, and
    that comes from the data.
    """
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    sport = str(request.args.get("sport") or "mlb").strip().lower()
    sports = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]
    if sport not in sports:
        sport = "mlb"
    return _no_cache_response(
        make_response(
            render_template(
                "book_grid.html",
                sport=sport,
                sports=sports,
                selected_date=selected_date,
                nav_path=request.path,
            )
        )
    )


@intelligence_bp.get("/market-board/opportunities")
def market_board_opportunities_page():
    """L2-B (arbitrage) and L2-C (low hold) — the two cross-book shortlists (S5).

    Sits beside `/market-board/books` rather than inside it: the book grid is
    Layer 1 and shows everything, while these are Layer 2 and show only what
    survives a gate. Same `market_row`, opposite jobs.

    Three tabs over ONE fetch, because arb and hold are the same search ordered
    two ways. Refetching per tab would re-run an identical pivot.
    """
    selected_date = str(request.args.get("date") or "").strip() or central_today_iso()
    sport = str(request.args.get("sport") or "mlb").strip().lower()
    sports = ["mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"]
    if sport not in sports:
        sport = "mlb"
    return _no_cache_response(
        make_response(
            render_template(
                "cross_book.html",
                sport=sport,
                sports=sports,
                selected_date=selected_date,
                nav_path=request.path,
            )
        )
    )


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


@intelligence_bp.post("/portfolio/bets/<prediction_id>/delete")
def portfolio_bet_delete(prediction_id: str):
    # Plain page-form action, not a /api/ JSON endpoint -- /portfolio is
    # currently 100% server-rendered with no client-side JS at all, so a
    # plain HTML form fits its existing style better than adding a
    # fetch-based flow for just this one action. Manual escape hatch for
    # predictions that can never settle automatically (see
    # prediction_ledger.delete_prediction's own docstring).
    delete_prediction(prediction_id)
    return redirect("/portfolio", code=303)