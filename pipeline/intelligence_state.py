from __future__ import annotations

import calendar
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from datetime import date
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping

from flask import Flask
from flask import current_app

from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline
from pipeline.intelligence_pipeline import run_intelligence_pipeline
from syndicate.features.intelligence import build_intelligence_status
from syndicate.features.intelligence import build_intelligence_overview
from syndicate.features.intelligence import _build_board_dictionary
from syndicate.features.intelligence import _balanced_recommendation_order
from syndicate.features.intelligence import candidate_identity_key
from syndicate.features.intelligence import collect_candidates_with_fallback_merge
from syndicate.features.intelligence import _apply_candidate_tier_penalty
from syndicate.features.intelligence import _greedy_low_correlation_selection
from syndicate.features.intelligence import _query_preferences
from syndicate.features.intelligence import rank_global_recommendations
from syndicate.features.intelligence import _shard_key_from_context_label
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence_board import dedupe_recommendation_items
from syndicate.features.intelligence.signals.normalization import _numeric_hint
from syndicate.features.intelligence.signals.normalization import _safe_text
from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_roots_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_paths_for_sport
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.shared.refresh_state_store import KeyValuePayloadTooLarge
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file
from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import normalize_timestamped_payload
from syndicate.features.mlb.sources import available_daily_summary_dates as mlb_available_daily_summary_dates
from syndicate.features.nba.sources import available_dates as nba_available_dates
from syndicate.features.ncaab.sources import available_dates as ncaab_available_dates
from syndicate.features.nhl.sources import available_dates as nhl_available_dates
from syndicate.features.wnba.sources import available_dates as wnba_available_dates


REPO_ROOT = repo_root_from(__file__)
STATE_PATH = reports_root() / "intelligence" / "query_state_cache.json"
BOARD_SNAPSHOT_PATH = reports_root() / "intelligence" / "board_snapshot.json"
STATUS_CACHE_PATH = reports_root() / "intelligence" / "status_response_cache.json"
INTELLIGENCE_STATE_PATH = reports_root() / "intelligence" / "intelligence_state.json"
INTELLIGENCE_HISTORY_PATH = reports_root() / "intelligence" / "intelligence_state_history.jsonl"
LIVE_PIPELINE_LAST_SUCCESSFUL_PATH = reports_root() / "intelligence" / "live_pipeline_last_successful.json"
logger = logging.getLogger(__name__)
_INTELLIGENCE_EXECUTION_GUARD = threading.RLock()
_INTELLIGENCE_LAST_RUN_STARTED_AT: float = 0.0
_INTELLIGENCE_LAST_RUN_FINISHED_AT: float = 0.0
_INTELLIGENCE_LAST_RUN_KEY: str | None = None
_INTELLIGENCE_GUARD_OWNER = threading.local()


def _supported_intelligence_dates() -> list[str]:
    dates: set[str] = set()
    for loader in (
        mlb_available_daily_summary_dates,
        nba_available_dates,
        wnba_available_dates,
        ncaab_available_dates,
        nhl_available_dates,
    ):
        try:
            for value in loader():
                text = str(value or "").strip()
                if len(text) != 10:
                    continue
                try:
                    date.fromisoformat(text)
                except Exception:
                    continue
                dates.add(text)
        except Exception:
            continue
    return sorted(dates)


def _next_supported_intelligence_date(current_date: str | None) -> str | None:
    reference = str(current_date or "").strip() or central_today_iso()
    try:
        reference_date = date.fromisoformat(reference)
    except Exception:
        return None
    future_dates = [value for value in _supported_intelligence_dates() if date.fromisoformat(value) > reference_date]
    return future_dates[0] if future_dates else None


def _state_backend_kind() -> str:
    value = str(os.environ.get("SYNDICATE_REFRESH_STATE_BACKEND") or "filesystem").strip().lower()
    if value in {"redis", "keyvalue", "valkey"}:
        return "keyvalue"
    return "filesystem"


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "t", "yes", "y", "on"}


def _stable_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.pop("user_profile", None)
    normalized.pop("force_refresh", None)
    return normalized


def _payload_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_stable_payload(payload), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_from_epoch(epoch_seconds: float) -> str | None:
    if epoch_seconds <= 0.0:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _timestamp_age_seconds(timestamp: str | None) -> float | None:
    value = str(timestamp or "").strip()
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=None)
        try:
            epoch = time.mktime(parsed.timetuple())
        except Exception:
            return None
    else:
        epoch = parsed.timestamp()
    return max(0.0, time.time() - float(epoch))


def _selected_date_from_payload(payload: dict[str, Any] | None) -> str | None:
    current = dict(payload or {})
    return str(current.get("date") or current.get("selected_date") or "").strip() or None


def intelligence_pipeline_busy() -> bool:
    """True while the board build is actively computing in THIS process.

    The other half of #55. Deferring the pipeline to a resident sim is not
    enough on its own: at boot the pipeline starts first and the sim fires
    ~5s later, so the pipeline's own check sees no sim and both run anyway.
    That is exactly what happened in production on 2026-07-25 --
    `pipeline_defers=0` while the worker OOM-looped.

    The two guards together produce strict alternation rather than overlap,
    and neither can starve the other: each waits only for a finite run of the
    other to end.

    Reads the service's execution guard because that is the lock the
    background loop actually holds while computing. The module-level
    _INTELLIGENCE_EXECUTION_GUARD is a different, effectively unused lock --
    nothing acquires it, so _intelligence_guard_is_busy() would always say
    False and silently disable this protection.
    """
    guard = getattr(_INTELLIGENCE_STATE_SERVICE, "_execution_guard", None)
    try:
        return bool(guard is not None and guard.locked())
    except Exception:
        return False


def _defer_to_mlb_sim_enabled() -> bool:
    return _env_bool("SYNDICATE_INTELLIGENCE_DEFER_TO_MLB_SIM", default=True)


def _mlb_sim_subprocess_running() -> bool:
    """True while an MLB daily-sim subprocess is resident on this worker.

    #55: the sim (~1.1GB) and this pipeline both run on refresh-worker, and
    together they exceed the 2GB container. On 2026-07-25 that produced an
    OOM crash loop -- the sim fires ~5s after every boot inside the tip-off
    window, the board build is already running, and the instance dies about
    once a minute.

    Deferring the SIM to the pipeline would not have fixed it: the sim runs
    ~15 minutes while this loop wakes every ~60s, so avoiding a simultaneous
    START just moves the collision a minute later. The bound has to be this
    way round -- the pipeline yields for as long as a sim is resident.

    The cost is real and worth stating: the board can go up to a sim's
    duration without recomputing. It serves last-known-good state meanwhile,
    which is a degraded board rather than no board -- and the alternative
    measured in production is a worker that OOMs before either finishes.

    Mirrors the existing protection in the other direction: the odds refresh
    already defers to a resident sim via the same helper.
    """
    if not _defer_to_mlb_sim_enabled():
        return False
    try:
        from syndicate.features.shared.live_refresh_loop import _mlb_daily_sim_process_still_running

        return bool(_mlb_daily_sim_process_still_running())
    except Exception:
        # Never let this check be the reason the board stops updating.
        return False


def _odds_refresh_in_flight() -> bool:
    """True while this service has an odds-refresh run in flight.

    #57: the board build is moving off refresh-worker (where it no longer
    fits alongside the MLB sim) onto live-odds-worker. That box's own hazard
    is different -- its odds refresh can spawn WNBA SmartSim and is
    documented spiking to ~1.3-1.5GB in the same 2048MB container
    (live_refresh_loop.py). Stacking the board build on top of that is the
    same mistake that caused today's outage, just relocated.

    is_refresh_run_active() is deliberately conservative: a false negative
    means occasional stacking, which is what happens today anyway, while a
    false positive would stall the board indefinitely.

    NOTE: this signal alone must never gate the build -- see
    _board_build_deferral_reason for why it starves without a bound.
    """
    # Defaults OFF as of the 2026-07-25 refresh-worker upgrade to 4GB. This
    # branch only ever existed because the board build had been pushed onto a
    # 2GB live-odds-worker alongside its odds refresh, and it caused more harm
    # than it prevented: the refresh there is effectively continuous, so the
    # deferral starved the board completely (8 defers / 13 iterations, zero
    # candidates) until it was bounded.
    #
    # At 4GB the arithmetic no longer justifies it: board build ~1479MB peak
    # plus an odds-refresh tree ~532MB is ~2.0GB, comfortably inside the
    # container. The SIM deferral (#55) stays on, because sim ~1674MB plus
    # board ~1479MB is ~3.2GB before the refresh tree and genuinely does not
    # fit.
    #
    # Kept rather than deleted, with its bound intact, so it can be switched
    # back on if the board build ever has to share a 2GB box again.
    if not _env_bool("SYNDICATE_INTELLIGENCE_DEFER_TO_ODDS_REFRESH", default=False):
        return False
    try:
        from syndicate.features.shared.ops_refresh import is_refresh_run_active

        return bool(is_refresh_run_active())
    except Exception:
        return False


# How many consecutive odds-refresh deferrals before the board build stops
# waiting politely and checks whether it can actually run.
_MAX_CONSECUTIVE_ODDS_REFRESH_DEFERS = 5

# Bounds the wait on a RESIDENT SIM. Separate constant from the odds one
# because the two hazards have different durations: a sim run is long
# (~15 min) but chains, so a slightly larger bound still bounds it.
_MAX_CONSECUTIVE_SIM_DEFERS = 5


def _board_build_deferral_reason(*, consecutive_odds_defers: int, consecutive_sim_defers: int = 0) -> str | None:
    """Why this iteration should skip the board build, or None to run it.

    The two hazards are NOT symmetric, and treating them as if they were is
    what took the board down on 2026-07-25 after it moved to
    live-odds-worker:

    - An MLB sim is FINITE (~15 min) and occasional, so waiting for one
      always terminates. Deferring to it needs no bound.
    - An odds refresh on this host is effectively CONTINUOUS -- the tick runs
      every 60s and a refresh regularly outruns it, which is why
      "a refresh run is already active" appears on consecutive ticks. So
      "defer while a refresh is in flight" degenerates into "never run":
      measured 8 deferrals across 13 iterations with candidate_count 0 and
      snapshot_generated_at never set.

    So the odds-refresh wait is bounded. Past the bound the build stops
    treating "a refresh exists" as disqualifying and asks the question that
    actually matters -- is there memory for this right now -- because the
    refresh's footprint varies enormously by sport and phase (a soccer odds
    pull is nothing like a WNBA SmartSim leg).

    Returning None means run. Starvation is now impossible from the
    odds-refresh branch: either headroom is sufficient and it runs, or the
    box genuinely cannot host it and that is a capacity fact worth logging
    rather than hiding behind an unbounded wait.
    """
    if _mlb_sim_subprocess_running():
        # BOUNDED, after getting this wrong three times. The original comment
        # here claimed a sim is "finite (~15 min) and occasional, so waiting
        # for one always terminates". The first half is true and the second is
        # not: live_refresh_loop.py's own comment states that "sims chain
        # back-to-back for hours on a live slate", so a resident sim is a
        # near-continuous condition, not an occasional one.
        #
        # Measured consequence: DEFERRED_BOARD_BUILD reason=
        # sim_subprocess_resident on 17 consecutive cycles with no
        # CANDIDATE_POOL_READY at all -- the board build simply stopped
        # running, which is the third time this session that an unbounded wait
        # on a near-continuous producer was mistaken for a safe one.
        #
        # Same bound as the other two: past the limit, ask the question that
        # matters. At 4GB there is room -- sim ~1674MB plus board ~1479MB is
        # ~3.2GB of 4096MB -- which is exactly the headroom the upgrade bought,
        # so the answer is usually yes.
        if consecutive_sim_defers < _MAX_CONSECUTIVE_SIM_DEFERS:
            return "sim_subprocess_resident"
        if _board_build_has_memory_headroom():
            print(
                f"[intelligence_state] BOARD_BUILD_PROCEEDING_DESPITE_SIM defers={consecutive_sim_defers}",
                flush=True,
            )
            return None
        return "sim_subprocess_resident_and_no_headroom"
    if not _odds_refresh_in_flight():
        return None
    if consecutive_odds_defers < _MAX_CONSECUTIVE_ODDS_REFRESH_DEFERS:
        return "odds_refresh_in_flight"
    if _board_build_has_memory_headroom():
        return None
    return "odds_refresh_in_flight_and_no_headroom"


def _board_build_has_memory_headroom() -> bool:
    """Real measured headroom, not a proxy. None/unmeasurable counts as
    insufficient -- this is the branch that overrides a safety wait, so it
    must not override on a guess.
    """
    try:
        from syndicate.features.shared.memory_observability import memory_headroom_snapshot

        snapshot = memory_headroom_snapshot(_board_build_min_headroom_bytes())
        return bool(snapshot and snapshot.get("sufficient"))
    except Exception:
        return False


def _board_build_min_headroom_bytes() -> int:
    # 900MB: the build was measured idling ~700MB and spiking past 1479MB on
    # a live slate, so anything under this is not a real window.
    raw = str(os.environ.get("SYNDICATE_BOARD_BUILD_MIN_HEADROOM_MB") or "").strip()
    try:
        megabytes = int(raw or 900)
    except ValueError:
        megabytes = 900
    return max(128, megabytes) * 1024 * 1024


def _watched_payload_eviction_reason(payload: dict[str, Any] | None, today_iso: str) -> str | None:
    """Why this watched payload should be dropped from the replay queue
    instead of being recomputed forever, or None to keep it.

    _watched_payloads survives restarts through the shared store, and
    _background_loop re-queues any entry whose snapshot is stale -- so an
    entry that can never produce a useful result is not merely useless, it
    recomputes every interval and clobbers self._latest_key with its empty
    response for every other caller.

    Two such entries exist:

    - "limit": no real caller sends one anymore (see intelligence.html's
      intelligenceQueryPayload); a leftover from an old queued request
      (e.g. scripts/run_refresh_odds_job.py's since-fixed hardcoded
      limit:10) replays a truncated response indefinitely. See
      _snapshot_limit_matches.
    - an older "date": recomputes against artifacts that have since rolled
      over and yields zero candidates. This took down the entire Layer 2
      board on 2026-07-25, where every sport reported context_label
      2026-07-24 and generated=0 in ~0.004ms -- an instant no-data bail --
      while MLB had 15 games and a fresh sim that same day.

    Strictly-older only: a payload with no date is the legitimate "today"
    default (see get_latest_intelligence_cached_response), and a
    future-dated one is a real look-ahead request.
    """
    current = dict(payload or {})
    if current.get("limit") is not None:
        return "stale_limit"
    payload_date = _selected_date_from_payload(current)
    if payload_date and _is_iso_date_only(payload_date):
        if payload_date < today_iso:
            return f"stale_date:{payload_date}"
        # #65. Future dates were originally kept on the reasoning that one is
        # "a real look-ahead request". That is only true when look-ahead is
        # actually enabled, and it is off in production -- so a stray
        # future-dated payload was being processed instead, and it is the
        # reason the board served nothing all evening.
        #
        # What it does: after ~19:00 CT a payload dated TOMORROW gets built.
        # Tomorrow has a schedule but no odds and no sim artifacts yet (soccer
        # reported data_health=missing, MLB generated=0 off 15 dashboard
        # games), so every candidate produced for it lacks both odds and
        # projection and is correctly rejected by classify_candidate as
        # missing_projection_or_odds. Generation looked healthy, 16 candidates
        # survived every filter, and the pool still came out empty -- which is
        # #64's symptom with this as its cause.
        #
        # Only evicted while look-ahead is disabled, so enabling it restores
        # the original behaviour deliberately rather than by accident.
        if payload_date > today_iso and not _look_ahead_board_builds_enabled():
            return f"future_date:{payload_date}"
    return None


def _empty_board_protection_window_seconds() -> int:
    raw = str(os.environ.get("SYNDICATE_EMPTY_BOARD_PROTECTION_SECONDS") or "").strip()
    try:
        value = int(raw or 1800)
    except ValueError:
        value = 1800
    return max(0, value)


def _empty_write_would_clobber_good_board(incoming: dict[str, Any]) -> bool:
    """True when writing this empty state would erase a populated board that
    is still recent enough to trust.

    Fails OPEN on any doubt -- if the existing state cannot be read or its age
    cannot be established, the write proceeds. A guard that blocks writes on
    ambiguity would be a much worse failure than the one it prevents: it could
    freeze the board permanently.
    """
    window = _empty_board_protection_window_seconds()
    if window <= 0:
        return False
    try:
        selected_date = str(incoming.get("selected_date") or "").strip()
        existing = read_json_file(_intelligence_state_daily_paths()["state"]) if selected_date else None
        if not isinstance(existing, dict):
            return False
        if str(existing.get("selected_date") or "").strip() != selected_date:
            # A different date's board is not this one's to protect.
            return False
        if int(existing.get("candidate_count") or 0) <= 0:
            return False
        # Reuses the module's existing helper rather than adding a second ISO
        # parser: it already handles the naive-timestamp case these payloads
        # sometimes carry.
        age_seconds = _timestamp_age_seconds(existing.get("state_last_updated") or existing.get("last_updated"))
        if age_seconds is None:
            return False
        return 0 <= age_seconds < window
    except Exception:
        return False


def _look_ahead_board_builds_enabled() -> bool:
    # Same flag the refresh loop's look-ahead uses, read here so the two
    # cannot disagree about whether building a future date is intended.
    return _env_bool("SYNDICATE_LOOK_AHEAD_ENABLED", default=False)


def _is_iso_date_only(value: str | None) -> bool:
    """True only for a bare YYYY-MM-DD. The length check matters: on 3.11
    date.fromisoformat also accepts fuller ISO forms, and callers here rely
    on the value being lexicographically comparable to central_today_iso().
    """
    text = str(value or "").strip()
    if len(text) != 10:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True

def _requested_sport_from_payload(payload: dict[str, Any] | None) -> str | None:
    current = dict(payload or {})
    return str(current.get("sport") or current.get("selected_sport") or current.get("sport_slug") or "").strip().lower() or None


def _response_has_sport_data(response: dict[str, Any] | None, requested_sport: str | None) -> bool:
    if not requested_sport or requested_sport == "all":
        return True
    current = dict(response or {})
    by_sport = current.get("by_sport")
    if isinstance(by_sport, Mapping) and by_sport:
        # by_sport reflects the true full pool (see _intelligence_state_candidate_count),
        # so when present it's authoritative: absence/emptiness for the
        # requested sport means this particular cached response genuinely
        # doesn't cover it, not that the sport itself has no data anywhere.
        entries = by_sport.get(requested_sport)
        return isinstance(entries, list) and len(entries) > 0
    # Legacy/older snapshot shapes without by_sport at all -- don't block on
    # sport in that case, only date-match as before (avoids regressing
    # responses that predate by_sport being populated).
    return True


def _snapshot_sport(snapshot: "IntelligenceSnapshot") -> str | None:
    payload = dict(snapshot.payload or {}) if isinstance(snapshot.payload, dict) else {}
    for key in ("sport", "selected_sport", "sport_slug"):
        value = str(payload.get(key) or "").strip().lower()
        if value:
            return value
    response = dict(snapshot.response or {}) if isinstance(snapshot.response, dict) else {}
    for key in ("top_opportunities", "recommendations"):
        entries = response.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            value = str(entry.get("sport") or entry.get("sport_slug") or entry.get("source_sport") or "").strip().lower()
            if value:
                return value
    board_contract = response.get("board_contract")
    if isinstance(board_contract, dict):
        cards = board_contract.get("cards")
        if isinstance(cards, list):
            for card in cards:
                if not isinstance(card, Mapping):
                    continue
                value = str(card.get("sport") or card.get("sport_slug") or "").strip().lower()
                if value:
                    return value
    return None


def _snapshot_limit_matches(snapshot: "IntelligenceSnapshot", payload: dict[str, Any]) -> bool:
    # A background job (e.g. scripts/run_refresh_odds_job.py) queuing its own
    # payload with a different "limit" than the frontend's own request used
    # to be able to win the self._latest_key fallback race below and clobber
    # every other caller's response with its own truncated recommendations
    # list, even though the two payloads were never asking for the same
    # thing. date/sport already gate this fallback; limit should too.
    def _limit_of(source: dict[str, Any] | None) -> int | None:
        raw = dict(source or {}).get("limit")
        try:
            return int(raw) if raw is not None and str(raw).strip() else None
        except (TypeError, ValueError):
            return None

    requested_limit = _limit_of(payload)
    snapshot_limit = _limit_of(snapshot.payload if isinstance(snapshot.payload, dict) else None)
    return requested_limit == snapshot_limit


def _snapshot_matches_payload(snapshot: "IntelligenceSnapshot", payload: dict[str, Any]) -> bool:
    requested_date = _selected_date_from_payload(payload)
    snapshot_date = _selected_date_from_payload(snapshot.payload if isinstance(snapshot.payload, dict) else None)
    if requested_date and snapshot_date and snapshot_date != requested_date:
        return False
    requested_sport = _requested_sport_from_payload(payload)
    if not requested_sport or requested_sport == "all":
        return True
    snapshot_sport = _snapshot_sport(snapshot)
    return snapshot_sport == requested_sport


def _selected_date_from_response(response: dict[str, Any] | None) -> str | None:
    current = dict(response or {})
    nested = current.get("response") if isinstance(current.get("response"), dict) else {}
    nested = dict(nested or {})
    for key in ("selected_date", "date"):
        value = str(nested.get(key) or current.get(key) or "").strip()
        if value:
            return value
    return None


def _utc_timestamp_string(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _board_contract_cards(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    current = dict(state or {})
    sources: list[Mapping[str, Any]] = []

    def _collect(board_contract: Mapping[str, Any] | None) -> None:
        if not isinstance(board_contract, Mapping):
            return
        cards = board_contract.get("cards")
        if isinstance(cards, list) and cards:
            sources.extend(item for item in cards if isinstance(item, Mapping))
            return
        for key in ("top_overall", "live", "pregame"):
            items = board_contract.get(key)
            if isinstance(items, list):
                sources.extend(item for item in items if isinstance(item, Mapping))

    _collect(current.get("board_contract") if isinstance(current.get("board_contract"), Mapping) else None)
    if not sources:
        _collect(current.get("boardContract") if isinstance(current.get("boardContract"), Mapping) else None)

    # #29. This had its own copy of the same broken dedup key as
    # intelligence_board._recommendation_sources -- id/name/market parts joined
    # with `if part`, so empty components collapsed the key instead of holding
    # position and the full candidate (carries recommendation_id) could never
    # match the reduced blotter row (does not). One shared implementation now,
    # so the two cannot drift apart again.
    return [dict(item) for item in dedupe_recommendation_items(sources)]


def _promote_board_contract_cards(state: dict[str, Any] | None) -> dict[str, Any]:
    current = dict(state or {})
    cards = _board_contract_cards(current)
    if not cards:
        return current

    live_cards = [dict(item) for item in cards if bool(item.get("is_live")) or str(item.get("lane") or "").strip().lower() == "live"]

    if not isinstance(current.get("top_opportunities"), list) or not current.get("top_opportunities"):
        current["top_opportunities"] = [dict(item) for item in cards]

    if not isinstance(current.get("recommendations"), list) or not current.get("recommendations"):
        current["recommendations"] = [dict(item) for item in cards]

    if not isinstance(current.get("by_sport"), dict) or not current.get("by_sport"):
        by_sport: dict[str, list[dict[str, Any]]] = {}
        for item in cards:
            sport_key = str(item.get("sport") or item.get("sport_slug") or "unknown").strip().lower() or "unknown"
            by_sport.setdefault(sport_key, []).append(dict(item))
        current["by_sport"] = by_sport

    if not isinstance(current.get("top_live_opportunities"), list) or not current.get("top_live_opportunities"):
        current["top_live_opportunities"] = [dict(item) for item in live_cards]

    analysis = current.get("analysis") if isinstance(current.get("analysis"), dict) else None
    if isinstance(analysis, dict):
        analysis = dict(analysis)
        if not isinstance(analysis.get("recommendations"), list) or not analysis.get("recommendations"):
            analysis["recommendations"] = [dict(item) for item in cards]
        if not isinstance(analysis.get("picks"), list) or not analysis.get("picks"):
            analysis["picks"] = [dict(item) for item in cards]
        if not isinstance(analysis.get("top_live_opportunities"), list) or not analysis.get("top_live_opportunities"):
            analysis["top_live_opportunities"] = [dict(item) for item in live_cards]
        current["analysis"] = analysis

    response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(response, dict):
        response = dict(response)
        if not isinstance(response.get("top_opportunities"), list) or not response.get("top_opportunities"):
            response["top_opportunities"] = [dict(item) for item in cards]
        if not isinstance(response.get("recommendations"), list) or not response.get("recommendations"):
            response["recommendations"] = [dict(item) for item in cards]
        if not isinstance(response.get("top_live_opportunities"), list) or not response.get("top_live_opportunities"):
            response["top_live_opportunities"] = [dict(item) for item in live_cards]
        if isinstance(analysis, dict):
            response["analysis"] = analysis
        current["response"] = response

    return current


def _intelligence_state_candidate_count(state: dict[str, Any] | None) -> int:
    current = dict(state or {})
    # by_sport is built from the full ranked candidate pool BEFORE any
    # per-request sport-scoping or limit slicing is applied (see
    # _compute_response/_compute_board_publication_response), so its total is
    # the only field here that reflects true pool size. Confirmed live
    # 2026-07-21: a persisted snapshot had by_sport.mlb with 181 candidates
    # but top_opportunities/recommendations sliced to 10 (whatever limit that
    # particular cached request happened to carry) -- checking
    # top_opportunities first silently overwrote the real 181 with a
    # request-specific display count every time this ran (on every read AND
    # write), which is the actual mechanism behind the "stuck at 10" board.
    by_sport_total = 0
    by_sport = current.get("by_sport")
    if isinstance(by_sport, Mapping) and by_sport:
        by_sport_total = sum(len(items) for items in by_sport.values() if isinstance(items, list))
    opportunities = current.get("top_opportunities")
    opportunities_total = len([item for item in opportunities if isinstance(item, Mapping)]) if isinstance(opportunities, list) else 0
    # Take whichever is larger rather than strictly preferring by_sport: in
    # real responses by_sport is always >= top_opportunities (it's built
    # before any per-request sport-scoping/limit slice is applied), but
    # falling back to max() here also tolerates hand-built/legacy state
    # shapes where that invariant doesn't hold, without reintroducing the
    # original bug of trusting a request-scoped slice as the true total.
    if by_sport_total > 0 or opportunities_total > 0:
        return max(by_sport_total, opportunities_total)
    recommendations = current.get("recommendations")
    if isinstance(recommendations, list) and recommendations:
        return len([item for item in recommendations if isinstance(item, Mapping)])
    board_cards = _board_contract_cards(current)
    if board_cards:
        return len(board_cards)
    return 0


def _pipeline_row_counts(rows: list[dict[str, Any]] | list[Mapping[str, Any]] | None) -> dict[str, int]:
    materialized = [row for row in rows or [] if isinstance(row, Mapping)]
    live_count = sum(1 for row in materialized if bool(row.get("is_live")))
    total = len(materialized)
    return {
        "total": total,
        "live": live_count,
        "pregame": max(0, total - live_count),
    }


def _item_latest_timestamp(item: Mapping[str, Any] | None) -> datetime | None:
    # Local port of syndicate.blueprints.intelligence._response_item_latest_timestamp.
    # _latest_item_timestamp below called that name directly without ever
    # importing it -- a NameError that only fires when the row list is
    # non-empty, i.e. exactly when the board has live games/props to
    # summarize. Confirmed live 2026-07-25 as the exception that failed
    # every board publication and (via _background_loop's silent except)
    # replaced a fully computed board with an empty one. Defined here rather
    # than imported because syndicate.blueprints.intelligence imports this
    # module, so importing it back would be circular.
    current = dict(item or {})
    candidates: list[str] = []
    for key in ("last_updated", "updated_at", "computed_at", "latestComputedAt", "timestamp", "generated_at", "odds_refreshed_at"):
        value = str(current.get(key) or "").strip()
        if value:
            candidates.append(value)

    movement = current.get("movement") if isinstance(current.get("movement"), Mapping) else None
    if isinstance(movement, Mapping):
        for key in ("last_updated", "updated_at", "computed_at", "timestamp", "generated_at"):
            value = str(movement.get(key) or "").strip()
            if value:
                candidates.append(value)

    movement_history = current.get("movement_history") if isinstance(current.get("movement_history"), list) else None
    if isinstance(movement_history, list) and movement_history:
        tail = movement_history[-1] if isinstance(movement_history[-1], Mapping) else None
        if isinstance(tail, Mapping):
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


def _latest_item_timestamp(rows: list[dict[str, Any]] | list[Mapping[str, Any]] | None) -> str | None:
    latest_timestamp = None
    latest_epoch = -1.0
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        timestamp_value = _item_latest_timestamp(row)
        if timestamp_value is None:
            continue
        try:
            epoch_value = timestamp_value.timestamp()
        except Exception:
            continue
        if epoch_value > latest_epoch:
            latest_epoch = epoch_value
            latest_timestamp = timestamp_value
    if latest_timestamp is None:
        return None
    return latest_timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _live_pipeline_has_activity(live_pipeline: dict[str, Any] | None) -> bool:
    current = dict(live_pipeline or {})
    numeric_keys = ("live_games", "live_props", "live_prop_items", "live_odds_game_ids", "live_candidates", "live_recommendations", "board_live_count", "top_live_opportunities")
    return any(int(current.get(key) or 0) > 0 for key in numeric_keys)


def _load_last_successful_live_pipeline() -> dict[str, Any] | None:
    payload = read_json_file(LIVE_PIPELINE_LAST_SUCCESSFUL_PATH)
    return dict(payload) if isinstance(payload, dict) else None


def _normalize_intelligence_state_payload(state: dict[str, Any] | None) -> dict[str, Any] | None:
    current = dict(state or {})
    if not current:
        return None
    current = _promote_board_contract_cards(current)
    live_pipeline = current.get("live_pipeline") if isinstance(current.get("live_pipeline"), dict) else {}
    if not isinstance(live_pipeline, dict):
        live_pipeline = {}
    last_successful_live_pipeline = _load_last_successful_live_pipeline()
    if last_successful_live_pipeline and not live_pipeline.get("last_successful_live_cycle"):
        live_pipeline["last_successful_live_cycle"] = dict(last_successful_live_pipeline)
    current["live_pipeline"] = live_pipeline
    candidate_count = _intelligence_state_candidate_count(current)
    current["candidate_count"] = candidate_count
    nested_response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(nested_response, dict):
        nested_response = dict(nested_response)
        nested_response["candidate_count"] = candidate_count
        if live_pipeline:
            nested_response["live_pipeline"] = dict(live_pipeline)
        current["response"] = nested_response
    return current


def _freshness_status_from_age(age_seconds: float | None, sla_seconds: int) -> str:
    if age_seconds is None:
        return "unknown"
    return "fresh" if age_seconds <= float(sla_seconds) else "stale"


def _snapshot_state_meta(snapshot: "IntelligenceSnapshot | None", *, source: str | None = None, run_key: str | None = None, sla_seconds: int | None = None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "source": source,
            "computed_at": None,
            "age_seconds": None,
            "freshness_sla_seconds": int(sla_seconds or 0),
            "freshness_status": "unknown",
            "is_fresh": False,
            "source_fingerprint": None,
            "run_key": run_key,
            "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
            "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        }
    age_seconds = _timestamp_age_seconds(snapshot.computed_at)
    freshness_sla_seconds = int(sla_seconds if sla_seconds is not None else _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
    freshness_status = _freshness_status_from_age(age_seconds, freshness_sla_seconds)
    return {
        "source": source,
        "computed_at": snapshot.computed_at,
        "age_seconds": age_seconds,
        "freshness_sla_seconds": freshness_sla_seconds,
        "freshness_status": freshness_status,
        "is_fresh": freshness_status == "fresh",
        "source_fingerprint": snapshot.source_fingerprint,
        "run_key": run_key or snapshot.key,
        "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
        "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
    }


def _decorate_response_with_state_meta(response: dict[str, Any] | None, snapshot: "IntelligenceSnapshot | None", *, source: str | None = None, run_key: str | None = None, sla_seconds: int | None = None) -> dict[str, Any] | None:
    current = dict(response or {})
    if not current:
        return None
    if snapshot is None:
        computed_at = str(current.get("state_last_updated") or current.get("last_updated") or current.get("updated_at") or "").strip() or None
        age_seconds = _timestamp_age_seconds(computed_at)
        freshness_sla_seconds = int(sla_seconds if sla_seconds is not None else _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
        freshness_status = _freshness_status_from_age(age_seconds, freshness_sla_seconds)
        state_meta = {
            "source": source,
            "computed_at": computed_at,
            "age_seconds": age_seconds,
            "freshness_sla_seconds": freshness_sla_seconds,
            "freshness_status": freshness_status,
            "is_fresh": freshness_status == "fresh",
            "source_fingerprint": current.get("source_fingerprint"),
            "run_key": run_key,
            "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
            "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        }
    else:
        state_meta = _snapshot_state_meta(snapshot, source=source, run_key=run_key, sla_seconds=sla_seconds)
    current.setdefault("state_meta", state_meta)
    current.setdefault("freshness", dict(current.get("state_meta") or {}))
    current.setdefault("state_freshness", dict(current.get("state_meta") or {}))
    current.setdefault("state_last_updated", str(current.get("state_last_updated") or current.get("last_updated") or current.get("updated_at") or (snapshot.computed_at if snapshot else "")).strip() or None)
    current.setdefault("source_fingerprint", snapshot.source_fingerprint if snapshot is not None else current.get("source_fingerprint"))
    return current


def _intelligence_state_daily_suffix() -> str:
    return central_today_iso().replace("-", "_")


def _intelligence_state_daily_paths() -> dict[str, Path]:
    suffix = _intelligence_state_daily_suffix()
    base_dir = reports_root() / "intelligence"
    return {
        "state": base_dir / f"intelligence_state_{suffix}.json",
        "history": base_dir / f"intelligence_state_history_{suffix}.jsonl",
        "board_snapshot": base_dir / f"board_snapshot_{suffix}.json",
    }


def _intelligence_state_daily_candidates() -> dict[str, list[Path]]:
    base_dir = reports_root() / "intelligence"
    return {
        "state": [path for path in sorted(base_dir.glob("intelligence_state_*.json"), reverse=True) if path.is_file()],
        "history": [path for path in sorted(base_dir.glob("intelligence_state_history_*.jsonl"), reverse=True) if path.is_file()],
        "board_snapshot": [path for path in sorted(base_dir.glob("board_snapshot_*.json"), reverse=True) if path.is_file()],
    }


def _intelligence_board_snapshot_payload(state: dict[str, Any], *, selected_date: str | None = None) -> dict[str, Any]:
    normalized = dict(state or {})
    response_selected_date = str(normalized.get("selected_date") or normalized.get("date") or selected_date or "").strip() or None
    return {
        "updated_at": _utc_now(),
        "snapshot_generated_at": normalized.get("snapshot_generated_at") or normalized.get("state_last_updated") or normalized.get("last_updated") or _utc_now(),
        "selected_date": response_selected_date,
        "candidate_count": int(normalized.get("candidate_count") or 0),
        "response": dict(normalized),
        "state_meta": dict(normalized.get("state_meta") or {}),
        "board_contract": normalized.get("board_contract") if isinstance(normalized.get("board_contract"), dict) else None,
    }


SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE_FLAG = "SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE"
SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE_SHADOW_COMPARE_FLAG = "SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE_SHADOW_COMPARE"


def canonical_board_state_enabled() -> bool:
    return _env_bool(SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE_FLAG, default=False)


def canonical_board_state_shadow_compare_enabled() -> bool:
    # Separate from the serving flag above: lets an operator watch
    # canonical-vs-legacy comparison logs in production (migration step 4's
    # validation window) while the legacy cascade still serves every real
    # request -- i.e. "shadow-compare without serving it yet", per the
    # rebuild plan. Turning this on alone never changes what a user sees.
    return _env_bool(SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE_SHADOW_COMPARE_FLAG, default=False)


def _intelligence_board_state_path(selected_date: str) -> Path:
    # One file per date -- an O(1) lookup by construction, unlike
    # _intelligence_state_daily_candidates() above, which has to glob every
    # board_snapshot_*.json under reports/intelligence/ and sort by filename
    # to find "the latest one". Callers that don't know the date should use
    # read_latest_intelligence_board_state()/the pointer file below instead.
    suffix = str(selected_date or "").strip().replace("-", "_") or _intelligence_state_daily_suffix()
    return reports_root() / "intelligence" / f"board_state_{suffix}.json"


def _intelligence_board_state_latest_pointer_path() -> Path:
    return reports_root() / "intelligence" / "board_state_latest_pointer.json"


def write_intelligence_board_state(state: dict[str, Any]) -> dict[str, Any] | None:
    normalized = dict(state or {})
    selected_date = str(normalized.get("selected_date") or "").strip()
    if not selected_date:
        return None
    write_json_file(_intelligence_board_state_path(selected_date), normalized)
    write_json_file(
        _intelligence_board_state_latest_pointer_path(),
        {"selected_date": selected_date, "updated_at": _utc_now()},
    )
    return normalized


def read_intelligence_board_state(selected_date: str | None) -> dict[str, Any] | None:
    normalized_date = str(selected_date or "").strip()
    if not normalized_date:
        return None
    payload = read_json_file(_intelligence_board_state_path(normalized_date))
    return payload if isinstance(payload, dict) else None


def read_latest_intelligence_board_state() -> dict[str, Any] | None:
    pointer = read_json_file(_intelligence_board_state_latest_pointer_path())
    pointer_date = str(pointer.get("selected_date") or "").strip() if isinstance(pointer, dict) else ""
    if pointer_date:
        state = read_intelligence_board_state(pointer_date)
        if state is not None:
            return state
    # Pointer missing/stale (e.g. nothing has ever been written yet, or the
    # pointer file itself was lost) -- today's date is the only reasonable
    # guess left, matching every other "no explicit date" default in this
    # module (see central_today_iso() usage elsewhere).
    return read_intelligence_board_state(central_today_iso())


def slice_intelligence_board_state_for_request(
    state: dict[str, Any] | None,
    *,
    sport: str | None = "all",
    limit: int | None = None,
) -> dict[str, Any]:
    # Pure function: the canonical per-date state is always built unsliced
    # (every covered sport, full ranked_all) -- sport/limit narrowing for a
    # specific request happens only here, at read time, never before
    # persistence. Replaces the sport/limit-slicing logic that used to be
    # duplicated inline in _compute_response and
    # _compute_board_publication_response.
    normalized_state = dict(state or {})
    requested_sport = str(sport or "all").strip().lower() or "all"
    by_sport = dict(normalized_state.get("by_sport") or {})
    ranked_all = [item for item in (normalized_state.get("ranked_all") or []) if isinstance(item, Mapping)]
    sport_scoped = ranked_all if requested_sport == "all" else [item for item in by_sport.get(requested_sport, []) if isinstance(item, Mapping)]

    if limit is None:
        top_opportunities = list(sport_scoped)
    else:
        try:
            limit_value = int(limit)
        except Exception:
            limit_value = None
        if limit_value is None:
            top_opportunities = list(sport_scoped)
        else:
            opportunity_limit = max(limit_value, 1) if sport_scoped else max(limit_value, 0)
            top_opportunities = sport_scoped[:opportunity_limit]

    response = dict(normalized_state)
    response["top_opportunities"] = [dict(item) for item in top_opportunities]
    response["recommendations"] = [dict(item) for item in top_opportunities]
    return response


def _intelligence_state_read_path(artifact_name: str, fallback_path: Path) -> Path:
    daily_paths = _intelligence_state_daily_paths()
    daily_candidates = _intelligence_state_daily_candidates().get(artifact_name, [])
    for path in [daily_paths.get(artifact_name), *daily_candidates, fallback_path]:
        if isinstance(path, Path) and path.exists() and path.is_file():
            return path
    return fallback_path


def _intelligence_state_history_entry(state: dict[str, Any]) -> dict[str, Any]:
    response = state.get("response") if isinstance(state.get("response"), dict) else {}
    top_opportunities = response.get("top_opportunities") if isinstance(response, dict) and isinstance(response.get("top_opportunities"), list) else state.get("top_opportunities")
    opportunity_names = [str(item.get("name") or item.get("selection") or item.get("pick") or "").strip() for item in top_opportunities or [] if isinstance(item, Mapping)]
    opportunity_names = [name for name in opportunity_names if name]
    return normalize_timestamped_payload({
        "updated_at": _utc_now(),
        "last_updated": str(state.get("last_updated") or response.get("last_updated") or "").strip() or None,
        "selected_date": str(state.get("selected_date") or response.get("selected_date") or response.get("date") or "").strip() or None,
        "candidate_count": _intelligence_state_candidate_count(state),
        "top_opportunity_names": opportunity_names,
        "board_contract_schema": str((response.get("board_contract") or state.get("board_contract") or {}).get("schema") or "").strip() or None if isinstance((response.get("board_contract") or state.get("board_contract") or {}), dict) else None,
    })


def _is_intelligence_state_payload_valid(state: dict[str, Any] | None) -> bool:
    current = dict(state or {})
    if not current:
        return False
    if any(key in current for key in ("top_opportunities", "by_sport", "analysis", "portfolio", "parlays")):
        return True
    if _board_contract_cards(current):
        return True
    nested_response = current.get("response") if isinstance(current.get("response"), dict) else None
    if isinstance(nested_response, dict) and any(key in nested_response for key in ("top_opportunities", "by_sport", "analysis", "portfolio", "parlays")):
        return True
    if _board_contract_cards(nested_response if isinstance(nested_response, dict) else None):
        return True
    return False


# Marker left in place of response.analysis when it is byte-identical to the
# top-level analysis, so _expand_persisted_state can restore it on read.
_ANALYSIS_ALIAS_MARKER = {"__alias_of__": "analysis"}


def _alias_marker(target: str) -> dict[str, str]:
    return {"__alias_of__": target}


# #43/#66. The same generalisation, applied to the candidate list rather than
# analysis. Production composition of a rejected 26,397,826-byte payload:
#
#   board_contract         3,592,276   (of which cards 3,591,228)
#   by_sport               3,527,200
#   top_opportunities      3,527,179
#   recommendations        3,527,179
#   top_live_opportunities 3,314,088
#
# i.e. the candidate list stored about five times over. Verified against a real
# persisted payload: top_live_opportunities is BYTE-IDENTICAL to
# recommendations, and every board_contract.cards row appears verbatim in
# recommendations with an identical field set. response.top_opportunities and
# response.top_live_opportunities duplicate their top-level twins the same way.
#
# top_opportunities and by_sport are NOT byte-identical (they were 88,057 and
# 88,076 against recommendations' 89,534 on the sample) so they are deliberately
# left alone -- the equality guard below would skip them anyway. A wrong board
# beats a small one.
_CANDIDATE_ALIAS_TOP_LEVEL = ("top_live_opportunities",)
_CANDIDATE_ALIAS_RESPONSE = ("top_opportunities", "top_live_opportunities", "recommendations")


def _compact_state_for_persist(state: dict[str, Any]) -> dict[str, Any]:
    """Shrink the state before it crosses the keyvalue boundary.

    Root cause of #43. The board computed 222 candidates correctly every
    cycle and then lost them here: this payload reached 8.9MB compact
    (16.9MB on disk, 393k lines) and Redis answered a SET that size with
    "Connection closed by server". The retry is sound -- it clears the
    client cache and reconnects -- but a fresh connection cannot fix an
    oversized value, so it failed twice and the whole build was discarded.
    Nothing upstream was broken, which is why every other signal looked
    healthy while candidate_count sat at 0.

    Two reductions, both provably lossless for readers:

    - response.analysis is BYTE-IDENTICAL to the top-level analysis
      (verified against production state). Storing both doubled the largest
      object in the payload. It is replaced with an alias marker and
      restored on read, so consumers still see state["response"]["analysis"].
    - analysis.evaluation_record.recommendations is 1.98MB and has NO
      reader: nothing in syndicate/ or pipeline/ accesses it. The fields
      that are consumed (artifact_metadata for date resolution, metrics,
      history) are kilobytes and are kept. It is also handed wholesale into
      ask_the_syndicate's LLM prompt pack, where 1.98MB of recommendations
      would be actively harmful.

    Together these take the payload from ~8.9MB to ~2.4MB.
    """
    compact = dict(state or {})
    analysis = compact.get("analysis")

    if isinstance(analysis, dict):
        record = analysis.get("evaluation_record")
        if isinstance(record, dict) and "recommendations" in record:
            trimmed_record = {k: v for k, v in record.items() if k != "recommendations"}
            analysis = {**analysis, "evaluation_record": trimmed_record}
            compact["analysis"] = analysis

    response = compact.get("response")
    if isinstance(response, dict) and "analysis" in response:
        same = json.dumps(response.get("analysis"), sort_keys=True, default=str) == json.dumps(
            state.get("analysis"), sort_keys=True, default=str
        )
        # Only alias when they genuinely match. If they ever diverge, keeping
        # the real value is correct -- a wrong board beats a small one.
        compact["response"] = {
            **response,
            "analysis": dict(_ANALYSIS_ALIAS_MARKER) if same else response.get("analysis"),
        }

    # #43/#66: collapse the duplicate candidate lists. Same equality guard as
    # above -- alias only what provably matches, byte for byte.
    recommendations_blob = json.dumps(state.get("recommendations"), sort_keys=True, default=str)

    # An alias marker is ~26 bytes, so aliasing a small or empty list makes the
    # payload BIGGER. Measured: every quiet-slate payload on disk grew by 33
    # bytes before this guard, because an empty top_live_opportunities matches
    # an empty recommendations. Only collapse duplicates worth collapsing.
    _ALIAS_MIN_BYTES = 4096
    recommendations_worth_aliasing = len(recommendations_blob) >= _ALIAS_MIN_BYTES

    def _matches_recommendations(value: Any) -> bool:
        if not recommendations_worth_aliasing:
            return False
        return json.dumps(value, sort_keys=True, default=str) == recommendations_blob

    for key in _CANDIDATE_ALIAS_TOP_LEVEL:
        if key in compact and _matches_recommendations(compact.get(key)):
            compact[key] = _alias_marker("recommendations")

    nested = compact.get("response")
    if isinstance(nested, dict):
        updated = dict(nested)
        for key in _CANDIDATE_ALIAS_RESPONSE:
            if key in updated and _matches_recommendations(updated.get(key)):
                updated[key] = _alias_marker("recommendations")
        compact["response"] = updated

    board_contract = compact.get("board_contract")
    if isinstance(board_contract, dict) and _matches_recommendations(board_contract.get("cards")):
        compact["board_contract"] = {**board_contract, "cards": _alias_marker("recommendations")}

    return compact


def _expand_persisted_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Restore response.analysis from its alias marker. Inverse of
    _compact_state_for_persist, so every existing consumer is unaffected.
    Tolerates un-aliased payloads written before this change.
    """
    if not isinstance(state, dict):
        return state
    expanded = dict(state)
    recommendations = expanded.get("recommendations")
    marker = _alias_marker("recommendations")

    for key in _CANDIDATE_ALIAS_TOP_LEVEL:
        if expanded.get(key) == marker:
            expanded[key] = recommendations

    board_contract = expanded.get("board_contract")
    if isinstance(board_contract, dict) and board_contract.get("cards") == marker:
        expanded["board_contract"] = {**board_contract, "cards": recommendations}

    response = expanded.get("response")
    if isinstance(response, dict):
        restored = dict(response)
        if restored.get("analysis") == _ANALYSIS_ALIAS_MARKER:
            restored["analysis"] = expanded.get("analysis")
        for key in _CANDIDATE_ALIAS_RESPONSE:
            if restored.get(key) == marker:
                restored[key] = recommendations
        expanded["response"] = restored

    return expanded


def _state_payload_timestamp(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("state_last_updated", "last_updated", "snapshot_generated_at"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _read_state_payload(path: Path) -> dict[str, Any] | None:
    """Read the board state from the keyvalue store or the published artifact.

    #43. The write side diverts oversized payloads to the artifact transport
    because the keyvalue store cannot carry them (15.5MB measured against an
    8.4MB ceiling). This is the matching read: on the keyvalue backend
    read_json_file consults the store ONLY, so without this the worker
    publishes an artifact nobody reads.

    Both sources are consulted and the FRESHER one wins, rather than preferring
    either. Preferring the store would keep serving a small stale board over a
    fresh large one -- which is the bug being fixed. Preferring the file would
    do the reverse the moment the payload shrinks back under the ceiling and
    the store resumes being authoritative.
    """
    keyvalue_payload = read_json_file(path)
    disk_payload: dict[str, Any] | None = None
    try:
        if path.is_file():
            candidate = json.loads(path.read_text(encoding="utf-8-sig"))
            disk_payload = candidate if isinstance(candidate, dict) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[intelligence_state] STATE_DISK_READ_FAILED path={path.name} error={type(exc).__name__}: {exc}", flush=True)

    if disk_payload is None:
        return keyvalue_payload
    if keyvalue_payload is None:
        print(f"[intelligence_state] STATE_READ_FROM_ARTIFACT path={path.name} reason=no_keyvalue_copy", flush=True)
        return disk_payload

    keyvalue_at = _state_payload_timestamp(keyvalue_payload)
    disk_at = _state_payload_timestamp(disk_payload)
    if disk_at > keyvalue_at:
        print(
            f"[intelligence_state] STATE_READ_FROM_ARTIFACT path={path.name} "
            f"artifact_at={disk_at} keyvalue_at={keyvalue_at}",
            flush=True,
        )
        return disk_payload
    return keyvalue_payload


def read_intelligence_state() -> dict[str, Any] | None:
    path = _intelligence_state_read_path("state", INTELLIGENCE_STATE_PATH)
    print("[INTELLIGENCE STATE READ]", {"path": str(path)})
    payload = _read_state_payload(path)
    payload = _expand_persisted_state(payload if isinstance(payload, dict) else None)
    normalized = _normalize_intelligence_state_payload(payload if isinstance(payload, dict) else None)
    if not _is_intelligence_state_payload_valid(normalized):
        print("[INTELLIGENCE STATE READ]", {"path": str(path), "valid": False, "candidate_count": 0})
        return None
    print("[INTELLIGENCE STATE READ]", {"path": str(path), "valid": True, "candidate_count": int(normalized.get("candidate_count") or 0)})
    return normalized


def _write_state_payload(path: Path, persisted: dict[str, Any]) -> None:
    """Write the board state, falling back to the artifact transport when it is
    too large for the keyvalue store.

    #43. The keyvalue store is a coordination channel and cannot carry this:
    production measured 15,532,051 bytes for 150 candidates against an
    8,388,608 ceiling, and the ceiling cannot simply be raised -- the store
    closes the connection above roughly 9MB, which is what made this present as
    an unrelated ConnectionError for hours. Deduplication did not close the gap
    either: the payload is five near-copies of the candidate list, and they are
    differently enriched (`recommendations` carries 7 fields the others lack and
    4 whose values differ), so they cannot be aliased losslessly.

    So the bulk goes the way the architecture already says bulk should go --
    worker writes an artifact, web reads it. That path routinely moves tens of
    megabytes and has no ceiling problem.

    The keyvalue write is still attempted first, so every payload small enough
    keeps its existing, faster path and nothing changes for quiet slates.
    """
    try:
        write_json_file(path, persisted)
        return
    except KeyValuePayloadTooLarge as exc:
        print(f"[intelligence_state] STATE_TOO_LARGE_FOR_KEYVALUE path={path.name} falling_back_to_artifact: {exc}", flush=True)

    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact
        from syndicate.features.shared.refresh_state_store import _atomic_write_text

        path.parent.mkdir(parents=True, exist_ok=True)
        # Compact, NOT indent=2. Measured against the publish endpoint: 14.70MB
        # publishes in 1.5s, 19.61MB drops the connection. This payload is
        # ~15.5MB compact, so indenting it (~+70%) would push the artifact over
        # the transport limit -- failing for precisely the payload the fallback
        # exists to carry. Nothing reads this file by eye.
        _atomic_write_text(path, json.dumps(persisted, separators=(",", ":")))
        published = publish_hot_artifact(path)
        print(
            f"[intelligence_state] STATE_PUBLISHED_AS_ARTIFACT path={path.name} published={published}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        # Never re-raise: the caller's whole cycle is discarded on an exception
        # here, which is precisely the failure mode #43 is about.
        print(f"[intelligence_state] STATE_ARTIFACT_FALLBACK_FAILED path={path.name} error={type(exc).__name__}: {exc}", flush=True)


def write_intelligence_state(state: dict[str, Any]) -> dict[str, Any] | None:
    return write_latest_intelligence_state(state)


def write_latest_intelligence_state(state: Any) -> dict[str, Any] | None:
    if hasattr(state, "to_dict") and callable(getattr(state, "to_dict")):
        state = state.to_dict()
    normalized = normalize_timestamped_payload(_normalize_intelligence_state_payload(state if isinstance(state, dict) else None))
    if not _is_intelligence_state_payload_valid(normalized):
        logger.info("STATE WRITTEN", extra={"written": False, "candidate_count": 0})
        print("[intelligence_state] STATE_WRITE_SKIPPED_INVALID_PAYLOAD", flush=True)
        return None
    candidate_count = int(normalized.get("candidate_count") or 0)
    if candidate_count <= 0 and _empty_write_would_clobber_good_board(normalized):
        # Observed 2026-07-26: one cycle produced 84 candidates and a later
        # cycle building TOMORROW's date produced 0 (every candidate rejected
        # as missing_projection_or_odds, because tomorrow has a schedule but no
        # odds or sim artifacts yet) and overwrote the good board with the
        # empty one. Net effect: a working board replaced by nothing.
        #
        # This is the same failure class as #8, where an exception handler
        # published a hardcoded empty board over a good one. #65 removes the
        # cause by refusing to build future dates; this refuses the SYMPTOM, so
        # any future source of an empty build cannot erase a populated board.
        #
        # Bounded by staleness on purpose: an empty board is legitimately
        # correct at the end of a slate, so refusing forever would freeze a
        # stale board instead. Past the window the empty write proceeds.
        print(
            f"[intelligence_state] STATE_WRITE_SKIPPED_EMPTY_OVER_GOOD "
            f"date={normalized.get('selected_date')} incoming=0",
            flush=True,
        )
        return None
    logger.info("INTELLIGENCE STATE PERSIST BEFORE", extra={"candidate_count": candidate_count})
    print(f"[intelligence_state] STATE_PERSIST_BEGIN candidate_count={candidate_count}", flush=True)
    daily_paths = _intelligence_state_daily_paths()
    state_meta = dict(normalized.get("state_meta") or {})
    live_pipeline = dict(normalized.get("live_pipeline") or {})
    board_snapshot_payload = _intelligence_board_snapshot_payload(normalized)
    # #43: shrink before crossing the keyvalue boundary. Redis closed the
    # connection on the full ~8.9MB payload, discarding a correctly computed
    # board every cycle. See _compact_state_for_persist.
    persisted = _compact_state_for_persist(normalized)
    _write_state_payload(INTELLIGENCE_STATE_PATH, persisted)
    _write_state_payload(daily_paths["state"], persisted)
    history_entry = _intelligence_state_history_entry(normalized)
    INTELLIGENCE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INTELLIGENCE_HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(history_entry, sort_keys=True, ensure_ascii=False, default=str))
        history_file.write("\n")
    daily_paths["history"].parent.mkdir(parents=True, exist_ok=True)
    with daily_paths["history"].open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(history_entry, sort_keys=True, ensure_ascii=False, default=str))
        history_file.write("\n")
    write_json_file(BOARD_SNAPSHOT_PATH, board_snapshot_payload)
    write_json_file(daily_paths["board_snapshot"], board_snapshot_payload)
    if _live_pipeline_has_activity(live_pipeline):
        live_pipeline["generated_at"] = str(live_pipeline.get("generated_at") or state_meta.get("computed_at") or normalized.get("snapshot_generated_at") or _utc_now()).strip() or _utc_now()
        write_json_file(LIVE_PIPELINE_LAST_SUCCESSFUL_PATH, live_pipeline)
    logger.info("INTELLIGENCE STATE PERSIST AFTER", extra={"candidate_count": candidate_count})
    logger.info("STATE WRITTEN", extra={"written": True, "candidate_count": int(normalized.get("candidate_count") or 0)})
    return normalized


def _intelligence_guard_is_busy() -> bool:
    return bool(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0)) or _INTELLIGENCE_EXECUTION_GUARD._is_owned()  # type: ignore[attr-defined]


def acquire_intelligence_execution_guard() -> bool:
    acquired = _INTELLIGENCE_EXECUTION_GUARD.acquire(blocking=False)
    if acquired:
        _INTELLIGENCE_GUARD_OWNER.depth = int(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0)) + 1
    return acquired


def release_intelligence_execution_guard() -> None:
    depth = int(getattr(_INTELLIGENCE_GUARD_OWNER, "depth", 0))
    if depth > 0:
        _INTELLIGENCE_GUARD_OWNER.depth = depth - 1
        _INTELLIGENCE_EXECUTION_GUARD.release()


def intelligence_guard_last_run_state() -> dict[str, Any]:
    return {
        "last_run_started_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_STARTED_AT),
        "last_run_finished_at": _utc_from_epoch(_INTELLIGENCE_LAST_RUN_FINISHED_AT),
        "last_run_key": _INTELLIGENCE_LAST_RUN_KEY,
        "busy": _intelligence_guard_is_busy(),
    }


def _update_intelligence_guard_run_state(*, key: str | None = None, started_at: float | None = None, finished_at: float | None = None) -> None:
    global _INTELLIGENCE_LAST_RUN_STARTED_AT
    global _INTELLIGENCE_LAST_RUN_FINISHED_AT
    global _INTELLIGENCE_LAST_RUN_KEY
    if started_at is not None:
        _INTELLIGENCE_LAST_RUN_STARTED_AT = float(started_at)
    if finished_at is not None:
        _INTELLIGENCE_LAST_RUN_FINISHED_AT = float(finished_at)
    if key is not None:
        _INTELLIGENCE_LAST_RUN_KEY = key


def get_latest_intelligence_cached_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    normalized_payload = payload or {"question": "top edges today", "date": central_today_iso()}
    service = _INTELLIGENCE_STATE_SERVICE
    response = service.read_latest_response(normalized_payload, force_refresh=False)
    return _promote_board_contract_cards(response) if isinstance(response, dict) else response


def _get_cached_or_latest_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return get_latest_intelligence_cached_response(payload)


def _log_stage_timing(stage_name: str, duration_ms: float) -> None:
    logger.info(json.dumps({"stage": stage_name, "duration_ms": round(duration_ms, 3)}, sort_keys=True, default=str))


_DIAG_MEMORY_DUMP_MAX_RECORDS = 60


def _diag_memory_dump_path() -> Path:
    return reports_root() / "live_refresh_loop" / "memory_diagnostics.json"


def _diag_dump_checkpoint_to_disk(stage: str, payload: dict[str, Any]) -> None:
    # Confirmed live: this background thread's print/stderr output does not
    # reliably reach Render's log collector before a SIGKILL once memory
    # pressure gets severe -- checkpoints that definitely executed (proven by
    # the container-level memory delta between them) never showed up in the
    # platform logs. Routes through write_json_file/read_json_file (the same
    # SYNDICATE_REFRESH_STATE_BACKEND=keyvalue-routed helpers every other
    # cross-service artifact in this file already uses) instead of the local
    # filesystem specifically so this is readable from the web service too,
    # via a dedicated ops endpoint -- refresh-worker has no HTTP server of
    # its own to expose it directly. Bounded ring buffer (last N records);
    # remove this whole mechanism once resolved.
    try:
        path = _diag_memory_dump_path()
        existing = read_json_file(path)
        records = list(existing.get("records") or []) if isinstance(existing, dict) else []
        records.append({"stage": stage, "wall_clock": time.time(), "pid": os.getpid(), **payload})
        records = records[-_DIAG_MEMORY_DUMP_MAX_RECORDS:]
        write_json_file(path, {"records": records})
    except Exception as exc:
        print(f"[intelligence_state] DIAG_MEMORY_DUMP_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)


def _diag_log_all_process_memory(stage: str) -> None:
    # Temporary boot-crash diagnostic (see matching helper in
    # scripts/run_refresh_worker.py): confirmed the refresh-worker's OOM
    # crashes happen inside this background thread's own candidate-collection
    # work, not the main tick loop -- that thread's own diagnostic samples
    # stayed flat (~150-235MB) right up to each crash, meaning the spike
    # happens somewhere in _build_candidate_pool. Remove once resolved.
    try:
        from syndicate.features.shared.memory_observability import log_all_process_memory

        payload = log_all_process_memory(stage)
        _diag_dump_checkpoint_to_disk(stage, payload)
    except Exception as exc:
        print(f"[intelligence_state] DIAG_MEMORY_LOG_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)


# The container's hard limit is 2GB. Confirmed via live production diagnostics
# that a single stage transition inside _build_candidate_pool can add
# 350-450MB in well under a minute (page cache + heap combined, cgroup-
# accounted) -- and that stdout/stderr from this background thread doesn't
# reliably reach the platform's log collector before a SIGKILL under that
# much memory pressure, so print-based diagnostics alone couldn't pinpoint
# which exact stage. Rather than keep guessing, treat this as a circuit
# breaker: check real, cheap (single cgroup file read, not full process
# enumeration) headroom before each expensive stage and bail out to an
# empty-but-valid pool (never cached -- see the `if pool["candidate_count"]
# > 0` cache guard below) the moment it's not safe, instead of letting the
# OS kill the whole process. A skipped cycle is far cheaper than a crash
# loop: the process stays warm and the next cycle gets a fresh attempt
# after this one's allocations are released.
_MIN_SAFE_MEMORY_HEADROOM_BYTES = 900 * 1024 * 1024


def _abort_build_candidate_pool_if_memory_critical(stage: str) -> bool:
    try:
        from syndicate.features.shared.memory_observability import memory_headroom_snapshot

        snapshot = memory_headroom_snapshot(_MIN_SAFE_MEMORY_HEADROOM_BYTES)
    except Exception as exc:
        print(f"[intelligence_state] MEMORY_GUARD_CHECK_FAILED stage={stage} {type(exc).__name__}: {exc}", flush=True)
        return False
    if snapshot is None or snapshot.get("sufficient", True):
        return False
    print(f"[intelligence_state] MEMORY_GUARD_ABORT stage={stage} snapshot={snapshot}", flush=True)
    try:
        import gc

        gc.collect()
    except Exception:
        pass
    return True


def _profile_stage(stage_name: str, callback, *args, **kwargs):
    started_at = time.perf_counter()
    try:
        return callback(*args, **kwargs)
    finally:
        _log_stage_timing(stage_name, (time.perf_counter() - started_at) * 1000.0)


@dataclass
class IntelligenceSnapshot:
    key: str
    payload: dict[str, Any]
    response: dict[str, Any]
    computed_at: str
    source_fingerprint: str


class IntelligenceStateService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._execution_guard = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._interval_seconds = max(10, _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30))
        self._wait_timeout_seconds = 30
        self._max_snapshots = max(5, _env_int("SYNDICATE_INTELLIGENCE_MAX_SNAPSHOTS", 12))
        self._snapshots: OrderedDict[str, IntelligenceSnapshot] = OrderedDict()
        self._watched_payloads: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending_keys: OrderedDict[str, dict[str, Any]] = OrderedDict()
        # Separate from _watched_payloads/_pending_keys above (which are keyed
        # by a hash of the whole request payload, incl. free-text "question" --
        # see _payload_key). This is the additive, date-only-keyed registry for
        # the canonical board-state rebuild (SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE),
        # deliberately not merged into the payload-keyed queue above.
        self._watched_board_dates: OrderedDict[str, str] = OrderedDict()
        # Confirmed live 2026-07-22: _build_intelligence_board_state
        # (sport="all", no limit -- the maximally broad request by design)
        # can run past 10 minutes for a single date. It used to be called
        # inline at the top of _background_loop, so that entire duration
        # also blocked the SAME loop's legacy queue processing -- the thing
        # that keeps the real, currently-served board fresh. Tracks the
        # one background drain thread so _drain_one_watched_board_date_async
        # can run it off the main loop without ever risking two overlapping
        # canonical builds.
        self._board_state_drain_thread: threading.Thread | None = None
        self._candidate_pools: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._source_fingerprints: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._latest_key: str | None = None
        self._last_run_started_at: float = 0.0
        self._last_run_finished_at: float = 0.0
        self._last_run_key: str | None = None
        self._loaded_from_disk = False
        self._app: Flask | None = None

    def _artifact_signature(self, relative_path: str | None) -> dict[str, Any]:
        path_text = str(relative_path or "").strip()
        if not path_text:
            return {"path": "", "exists": False, "size": None, "mtime_ns": None}
        path = Path(path_text)
        if not path.is_absolute():
            path = REPO_ROOT / path
        try:
            stat_result = path.stat()
        except OSError:
            return {"path": path_text, "exists": False, "size": None, "mtime_ns": None}
        return {
            "path": path_text,
            "exists": True,
            "size": int(stat_result.st_size),
            "mtime_ns": int(stat_result.st_mtime_ns),
        }

    def _sport_manifest_signature(self, sport_slug: str, selected_date: str | None = None) -> dict[str, Any]:
        manifest_path = reports_root() / "manifests" / f"{str(sport_slug or '').strip().lower()}.json"
        signature = self._artifact_signature(str(manifest_path))
        manifest = read_json_file(manifest_path)
        if isinstance(manifest, dict):
            signature.update(
                {
                    "sport": str(manifest.get("sport") or "").strip().lower(),
                    "last_updated": str(manifest.get("last_updated") or "").strip(),
                    "status": str(manifest.get("status") or "").strip().lower(),
                    "artifact_path_count": len(manifest.get("artifact_paths") or []) if isinstance(manifest.get("artifact_paths"), list) else 0,
                }
            )
        signature["odds_history"] = self._odds_history_signature(sport_slug, selected_date)
        return signature

    def _odds_history_signature(self, sport_slug: str, selected_date: str | None = None) -> dict[str, Any]:
        shard_key = resolve_current_shard_key(sport_slug, selected_date or central_today_iso())
        candidate_paths = self._odds_history_paths_for_sport(sport_slug, shard_key)
        active_path: Path | None = None
        active_payload: dict[str, Any] | None = None
        for candidate_path in candidate_paths:
            payload = read_json_file(candidate_path)
            if isinstance(payload, dict):
                active_path = candidate_path
                active_payload = payload
                break

        if active_payload is None:
            return {
                "path": None,
                "exists": False,
                "payload_hash": None,
                "updated_at": None,
                "market_count": 0,
            }

        canonical_payload = json.dumps(active_payload, sort_keys=True, separators=(",", ":"), default=str)
        markets = active_payload.get("markets") if isinstance(active_payload.get("markets"), dict) else {}
        market_count = len(markets) if isinstance(markets, dict) else 0
        return {
            "path": str(active_path) if active_path is not None else None,
            "exists": True,
            "payload_hash": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
            "updated_at": str(active_payload.get("updated_at") or "").strip() or None,
            "market_count": int(market_count),
        }

    def _available_sport_manifests(self, selected_date: str | None) -> OrderedDict[str, dict[str, Any]]:
        # Root-caused 2026-07-25: this only ever reads sport.get("slug") below,
        # but was calling build_intelligence_status -- which, unlike this
        # method's other overview call sites, was never given
        # skip_game_hydration=True, so it ran a full home-page card hydration
        # pass (both lanes, every sport) just to list sport slugs. Confirmed
        # live: this was the dominant cost of the ~3-minute gap between
        # _build_candidate_pool's post_candidate_building and
        # post_pool_assembled checkpoints, called on every single manifest
        # loop even after the source-fingerprint and simulation-context fixes
        # landed. Same fix shape as _source_state_fingerprint's own
        # build_intelligence_status calls.
        overview = _profile_stage("data_ingestion", build_intelligence_overview, selected_date=selected_date, force_refresh=False, skip_game_hydration=True)
        manifests: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for sport in overview if isinstance(overview, list) else []:
            if not isinstance(sport, dict):
                continue
            sport_slug = str(sport.get("slug") or "").strip().lower()
            if not sport_slug or sport_slug in manifests:
                continue
            manifest_path = reports_root() / "manifests" / f"{sport_slug}.json"
            manifest = read_json_file(manifest_path)
            if not isinstance(manifest, dict):
                continue
            manifests[sport_slug] = manifest
        return manifests

    @staticmethod
    def _merge_candidate_pools(candidate_pools: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for sport_candidates in candidate_pools.values():
            for candidate in sport_candidates:
                if isinstance(candidate, Mapping):
                    merged.append(dict(candidate))
        return sorted(merged, key=lambda candidate: _numeric_hint(candidate.get("score")) or 0.0, reverse=True)

    @staticmethod
    def _candidate_numeric_value(candidate: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = candidate.get(key)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip()
            if not text:
                continue
            try:
                return float(text.replace("%", ""))
            except Exception:
                continue
        return None

    @staticmethod
    def _candidate_timestamp_value(candidate: dict[str, Any]) -> float | None:
        for key in ("updated_epoch", "timestamp_epoch"):
            value = candidate.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            try:
                text = str(value or "").strip()
                if text:
                    return float(text)
            except Exception:
                pass
        for key in ("updated_at", "last_updated", "last_updated_at", "timestamp", "generated_at", "created_at"):
            text = str(candidate.get(key) or "").strip()
            if not text:
                continue
            normalized = text.replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(normalized).timestamp()
            except Exception:
                continue
        return None

    @classmethod
    def _rank_fallback_candidates(cls, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def sort_key(candidate: dict[str, Any]) -> tuple[float, float, float, float]:
            score = cls._candidate_numeric_value(
                candidate,
                "score",
                "adjusted_score",
                "source_summary_score",
                "ev_current",
                "expected_value",
                "normalized_edge",
                "edge",
            )
            confidence = cls._candidate_numeric_value(
                candidate,
                "confidence",
                "model_probability",
                "implied_probability",
            )
            timestamp = cls._candidate_timestamp_value(candidate)
            return (
                1.0 if score is not None else 0.0,
                float(score or 0.0),
                float(confidence or 0.0),
                float(timestamp or 0.0),
            )

        return sorted((dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)), key=sort_key, reverse=True)

    def _odds_history_roots_for_sport(self, sport_slug: str) -> list[Path]:
        return odds_history_roots_for_sport(sport_slug)

    def _odds_history_paths_for_sport(self, sport_slug: str, shard_key: str) -> list[Path]:
        return odds_history_paths_for_sport(sport_slug, shard_key)

    def _load_odds_history_payload_for_sport(self, sport_slug: str, shard_key: str) -> dict[str, Any] | None:
        return load_odds_history_payload_for_sport(sport_slug, shard_key)

    @staticmethod
    def _odds_history_market_states(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not isinstance(payload, dict):
            return {}
        markets = payload.get("markets")
        if isinstance(markets, dict) and markets:
            return {str(key): value for key, value in markets.items() if isinstance(value, dict)}
        states: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if key in {"sport", "date", "updated_at", "history_limit", "markets"}:
                continue
            if isinstance(value, dict) and isinstance(value.get("history"), list):
                states[str(key)] = value
        return states

    def _odds_history_payloads_by_sport(self, overview: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {}
        for sport in overview:
            if not isinstance(sport, dict):
                continue
            slug = str(sport.get("slug") or "").strip().lower()
            if not slug or slug in payloads:
                continue
            shard_key = _shard_key_from_context_label(slug, str(sport.get("context_label") or ""))
            payload = self._load_odds_history_payload_for_sport(slug, shard_key)
            if isinstance(payload, dict):
                payloads[slug] = payload
        return payloads

    def _source_state_fingerprint_from_status(self, status: dict[str, Any], selected_date: str | None) -> str:
        refresh_status = status.get("refresh_status") if isinstance(status.get("refresh_status"), dict) else {}
        refresh_manifest = refresh_status.get("refresh_status", {}).get("manifest") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        refresh_runtime = refresh_status.get("refresh_status", {}).get("runtime") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        refresh_artifacts = refresh_status.get("refresh_status", {}).get("artifacts") if isinstance(refresh_status.get("refresh_status"), dict) else {}
        sports_payload: list[dict[str, Any]] = []
        for sport in status.get("sports") if isinstance(status.get("sports"), list) else []:
            if not isinstance(sport, dict):
                continue
            artifact_signatures = []
            for artifact in sport.get("artifacts") if isinstance(sport.get("artifacts"), list) else []:
                if not isinstance(artifact, dict):
                    continue
                artifact_signatures.append(
                    {
                        "label": str(artifact.get("label") or "").strip(),
                        **self._artifact_signature(str(artifact.get("path") or "").strip()),
                        "tracked": bool(artifact.get("tracked")),
                        "inside_repo": bool(artifact.get("inside_repo")),
                    }
                )
            advanced_signatures = []
            for advanced_input in sport.get("advanced_inputs") if isinstance(sport.get("advanced_inputs"), list) else []:
                if not isinstance(advanced_input, dict):
                    continue
                advanced_signatures.append(
                    {
                        "label": str(advanced_input.get("label") or "").strip(),
                        **self._artifact_signature(str(advanced_input.get("path") or "").strip()),
                        "exists": bool(advanced_input.get("exists")),
                        "tracked": bool(advanced_input.get("tracked")),
                        "inside_repo": bool(advanced_input.get("inside_repo")),
                    }
                )
            sports_payload.append(
                {
                    "slug": str(sport.get("slug") or "").strip().lower(),
                    "name": str(sport.get("name") or "").strip(),
                    "context_label": str(sport.get("context_label") or "").strip(),
                    "data_health": str(sport.get("data_health") or "").strip(),
                    "active_today": bool(sport.get("active_today")),
                    "tracked_ready": bool(sport.get("tracked_ready")),
                    "advanced_ready": bool(sport.get("advanced_ready")),
                    "advanced_gate": sport.get("advanced_gate") if isinstance(sport.get("advanced_gate"), dict) else {},
                    "data_warnings": [str(item).strip() for item in (sport.get("data_warnings") or []) if str(item).strip()],
                    "artifacts": artifact_signatures,
                    "advanced_inputs": advanced_signatures,
                    "odds_history": self._odds_history_signature(str(sport.get("slug") or "")),
                }
            )
        payload = {
            "selected_date": status.get("selected_date") or selected_date,
            "refresh_run": {
                "run_stamp": refresh_manifest.get("runStamp") if isinstance(refresh_manifest, dict) else None,
                "state": refresh_manifest.get("state") if isinstance(refresh_manifest, dict) else None,
                "finished_at": refresh_manifest.get("finishedAt") if isinstance(refresh_manifest, dict) else None,
                "runtime_state": refresh_runtime.get("state") if isinstance(refresh_runtime, dict) else None,
                "runtime_detail": refresh_runtime.get("detail") if isinstance(refresh_runtime, dict) else None,
                "artifacts": {
                    key: {
                        "exists": bool(value.get("exists")),
                        "path": str(value.get("path") or ""),
                        "size": value.get("size"),
                        "payload_hash": hashlib.sha256(json.dumps(value.get("payload"), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest() if value.get("payload") is not None else None,
                    }
                    for key, value in refresh_artifacts.items()
                    if isinstance(value, dict)
                },
            },
            "tracked_summary": status.get("tracked_summary") if isinstance(status.get("tracked_summary"), dict) else {},
            "advanced_summary": status.get("advanced_summary") if isinstance(status.get("advanced_summary"), dict) else {},
            "readiness_gate": status.get("readiness_gate") if isinstance(status.get("readiness_gate"), dict) else {},
            "sport_manifests": [
                self._sport_manifest_signature(str(sport.get("slug") or ""), selected_date)
                for sport in sports_payload
                if isinstance(sport, dict) and str(sport.get("slug") or "").strip()
            ],
            "sports": sports_payload,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_cached_status_payload(self, selected_date: str | None) -> dict[str, Any] | None:
        payload = read_json_file(STATUS_CACHE_PATH)
        if not isinstance(payload, dict):
            return None
        if str(payload.get("selected_date") or "").strip() != str(selected_date or "").strip():
            return None
        try:
            cached_at = float(payload.get("cached_at") or 0.0)
        except Exception:
            return None
        if cached_at <= 0.0 or (time.time() - cached_at) > float(self._interval_seconds):
            return None
        status = payload.get("status")
        return dict(status) if isinstance(status, dict) else None

    def _source_state_stamp(self, selected_date: str | None) -> str:
        sports = []
        if self._app is not None:
            with self._app.app_context():
                sports = current_app.config.get("SYNDICATE_SPORTS", [])
        if not sports:
            manifests_root = reports_root() / "manifests"
            if manifests_root.exists():
                sports = [
                    {"slug": path.stem}
                    for path in sorted(manifests_root.glob("*.json"))
                    if path.is_file()
                ]
        payload = {
            "selected_date": str(selected_date or "").strip(),
            "sports": [],
        }
        for sport in sports if isinstance(sports, list) else []:
            if not isinstance(sport, dict):
                continue
            slug = str(sport.get("slug") or "").strip().lower()
            if not slug:
                continue
            payload["sports"].append({"slug": slug, **self._sport_manifest_signature(slug, selected_date)})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _source_state_fingerprint(self, selected_date: str | None) -> str:
        cache_key = self._source_state_stamp(selected_date)
        with self._condition:
            cached_fingerprint = self._source_fingerprints.get(cache_key)
            if cached_fingerprint is not None and (time.time() - float(cached_fingerprint[0])) <= float(self._interval_seconds):
                return str(cached_fingerprint[1])

        status = self._load_cached_status_payload(selected_date)
        if status is None:
            # skip_game_hydration=True: this status build only feeds
            # _source_state_fingerprint_from_status below, which reads each
            # sport's artifacts/advanced_inputs (computed separately inside
            # build_intelligence_status's own loop) -- never
            # dashboard_games/home_rails from the raw overview, so it's safe
            # to skip that expensive game/prop hydration here. Root-caused
            # 2026-07-24: this unconditional call was confirmed live to
            # single-handedly exceed the refresh-worker's 2GB memory limit.
            if self._app is not None:
                with self._app.app_context():
                    status = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date, force_refresh=False, skip_game_hydration=True)
            else:
                status = _profile_stage("data_ingestion", build_intelligence_status, selected_date=selected_date, force_refresh=False, skip_game_hydration=True)

        status_fingerprint = self._source_state_fingerprint_from_status(status if isinstance(status, dict) else {}, selected_date)
        fingerprint = hashlib.sha256(f"{cache_key}:{status_fingerprint}".encode("utf-8")).hexdigest()
        with self._condition:
            self._source_fingerprints[cache_key] = (time.time(), fingerprint)
            self._source_fingerprints.move_to_end(cache_key)
            self._trim_ordered_dict(self._source_fingerprints, self._max_snapshots)
        return fingerprint

    def _candidate_pool_key(self, selected_date: str | None, source_fingerprint: str) -> str:
        payload = {
            "selected_date": str(selected_date or "").strip(),
            "source_fingerprint": str(source_fingerprint or "").strip(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _candidate_id(self, candidate: dict[str, Any]) -> str:
        # Delegates to the standalone syndicate.features.intelligence.candidate_identity_key
        # so collect_candidates_with_fallback_merge can dedupe/union candidates
        # without needing a service instance. Kept as a thin wrapper so
        # existing callers/tests referencing self._candidate_id keep working.
        return candidate_identity_key(candidate)

    def _candidate_raw_inputs(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            key: candidate.get(key)
            for key in (
                "event_id",
                "game_pk",
                "sport",
                "sport_slug",
                "candidate_type",
                "market",
                "market_key",
                "selection",
                "pick",
                "line",
                "odds",
                "matchup",
                "player_name",
                "name",
                "team",
                "status_display",
                "status_context",
                "game_state",
                "timestamp",
                "updated_at",
                "live_projection",
                "live_total",
                "actual",
            )
        }

    def _candidate_precomputed_features(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "simulation": candidate.get("simulation") if isinstance(candidate.get("simulation"), dict) else None,
            "market_context": candidate.get("market_context") if isinstance(candidate.get("market_context"), dict) else None,
            "market_data": candidate.get("market_data") if isinstance(candidate.get("market_data"), dict) else None,
            "market_fit": candidate.get("market_fit") if isinstance(candidate.get("market_fit"), dict) else None,
            "historical_profile": candidate.get("historical_profile") if isinstance(candidate.get("historical_profile"), dict) else None,
            "sport_profile": candidate.get("sport_profile") if isinstance(candidate.get("sport_profile"), dict) else None,
            "performance_context": candidate.get("performance_context") if isinstance(candidate.get("performance_context"), dict) else None,
            "advanced_gate": candidate.get("advanced_gate") if isinstance(candidate.get("advanced_gate"), dict) else None,
            "advanced_context": [dict(item) for item in (candidate.get("advanced_context") or []) if isinstance(item, dict)],
            "advanced_inputs": [dict(item) for item in (candidate.get("advanced_inputs") or []) if isinstance(item, dict)],
        }

    def _candidate_preliminary_scores(self, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": candidate.get("score"),
            "adjusted_score": candidate.get("adjusted_score"),
            "source_summary_score": candidate.get("source_summary_score"),
            "edge": candidate.get("edge"),
            "adjusted_edge": candidate.get("adjusted_edge"),
            "ev_current": candidate.get("ev_current"),
            "ev_delta": candidate.get("ev_delta"),
            "confidence": candidate.get("confidence"),
            "model_probability": candidate.get("model_probability"),
            "implied_probability": candidate.get("implied_probability"),
        }

    @staticmethod
    def _stage_row_counts(rows: list[dict[str, Any]] | list[Mapping[str, Any]] | None) -> dict[str, int]:
        materialized = [row for row in rows or [] if isinstance(row, Mapping)]
        live_count = sum(1 for row in materialized if bool(row.get("is_live")))
        total = len(materialized)
        return {
            "total": total,
            "live": live_count,
            "pregame": max(0, total - live_count),
        }

    def _live_pipeline_summary(
        self,
        *,
        candidate_pool: dict[str, Any],
        candidates: list[dict[str, Any]],
        top_candidates: list[dict[str, Any]],
        top_opportunities: list[dict[str, Any]],
        board_contract: dict[str, Any],
        selected_date: str | None,
        sport: str | None,
    ) -> dict[str, Any]:
        overview = candidate_pool.get("overview") if isinstance(candidate_pool.get("overview"), list) else []
        overview_by_slug = {
            _safe_text(row.get("slug"), "sport").lower(): row
            for row in overview
            if isinstance(row, Mapping)
        }
        sport_slugs = sorted({*overview_by_slug.keys(), *{str(candidate.get("sport") or candidate.get("sport_slug") or "").strip().lower() for candidate in candidates if str(candidate.get("sport") or candidate.get("sport_slug") or "").strip()}})
        sport_slugs = [slug for slug in sport_slugs if slug]
        by_sport: dict[str, dict[str, Any]] = {}
        board_cards = board_contract.get("cards") if isinstance(board_contract.get("cards"), list) else []

        for sport_slug in sport_slugs:
            sport_overview = overview_by_slug.get(sport_slug) or {}
            home_rails = sport_overview.get("home_rails") if isinstance(sport_overview.get("home_rails"), dict) else {}
            live_items = (home_rails.get("live") or {}).get("items") if isinstance(home_rails.get("live"), dict) else []
            live_items = [item for item in live_items if isinstance(item, Mapping)]
            dashboard_games = sport_overview.get("dashboard_games") if isinstance(sport_overview.get("dashboard_games"), list) else []
            live_games = [game for game in dashboard_games if isinstance(game, Mapping) and bool(game.get("is_live"))]
            sport_candidates = [row for row in candidates if _safe_text(row.get("sport") or row.get("sport_slug"), "").lower() == sport_slug]
            sport_ranked = [row for row in top_candidates if _safe_text(row.get("sport") or row.get("sport_slug"), "").lower() == sport_slug]
            sport_selected = [row for row in top_opportunities if _safe_text(row.get("sport") or row.get("sport_slug"), "").lower() == sport_slug]
            sport_board = [card for card in board_cards if isinstance(card, Mapping) and _safe_text(card.get("sport") or card.get("sport_slug"), "").lower() == sport_slug]
            by_sport[sport_slug] = {
                "live_games": len(live_games),
                "live_props": len(live_items),
                "live_prop_items": len(live_items),
                "live_odds_game_ids": len({str(item.get("game_id") or item.get("event_id") or item.get("id") or "").strip() for item in live_items if str(item.get("game_id") or item.get("event_id") or item.get("id") or "").strip()}),
                "live_candidates": sum(1 for row in sport_candidates if bool(row.get("is_live"))),
                "live_recommendations": sum(1 for row in sport_selected if bool(row.get("is_live"))),
                "board_live_count": sum(1 for row in sport_board if bool(row.get("is_live"))),
                "top_live_opportunities": sum(1 for row in sport_selected if bool(row.get("is_live"))),
                "live_mirror_exists": bool(live_games or live_items),
                "live_mirror_timestamp": _latest_item_timestamp([*live_games, *live_items]),
            }

        live_games = sum(item["live_games"] for item in by_sport.values())
        live_props = sum(item["live_props"] for item in by_sport.values())
        live_prop_items = sum(item["live_prop_items"] for item in by_sport.values())
        live_odds_game_ids = sum(item["live_odds_game_ids"] for item in by_sport.values())
        live_candidates = sum(item["live_candidates"] for item in by_sport.values())
        live_recommendations = sum(item["live_recommendations"] for item in by_sport.values())
        board_live_count = int((board_contract.get("board_summary") or {}).get("live_count") or sum(item["board_live_count"] for item in by_sport.values()))
        top_live_opportunities = sum(1 for row in top_opportunities if bool(row.get("is_live")))
        live_mirror_exists = any(item["live_mirror_exists"] for item in by_sport.values())
        live_mirror_timestamp = max((str(item.get("live_mirror_timestamp") or "") for item in by_sport.values()), default="") or None
        current_pipeline = {
            "generated_at": _utc_now(),
            "sport": _safe_text(sport, "all") or "all",
            "selected_date": _safe_text(selected_date, central_today_iso()),
            "live_games": live_games,
            "live_props": live_props,
            "live_prop_items": live_prop_items,
            "live_odds_game_ids": live_odds_game_ids,
            "live_candidates": live_candidates,
            "live_recommendations": live_recommendations,
            "board_live_count": board_live_count,
            "top_live_opportunities": top_live_opportunities,
            "live_mirror_exists": live_mirror_exists,
            "live_mirror_timestamp": live_mirror_timestamp,
            "stage_counts": {
                "raw_candidates": self._stage_row_counts(candidates),
                "ranked_candidates": self._stage_row_counts(top_candidates),
                "selected_recommendations": self._stage_row_counts(top_opportunities),
                "board_payload": self._stage_row_counts(board_cards),
            },
            "by_sport": by_sport,
        }
        last_successful_live_pipeline = _load_last_successful_live_pipeline()
        if _live_pipeline_has_activity(current_pipeline):
            current_pipeline["last_successful_live_cycle"] = dict(current_pipeline)
        elif last_successful_live_pipeline:
            current_pipeline["last_successful_live_cycle"] = last_successful_live_pipeline
        return current_pipeline

    def _serialize_candidate(self, candidate: Any) -> dict[str, Any]:
        if hasattr(candidate, "to_dict"):
            try:
                payload = candidate.to_dict()
                if isinstance(payload, Mapping):
                    candidate_payload = dict(payload)
                else:
                    candidate_payload = {}
            except Exception:
                candidate_payload = {}
        elif isinstance(candidate, Mapping):
            candidate_payload = dict(candidate)
        else:
            return {}

        if not candidate_payload:
            return {}

        sport_slug = str(candidate_payload.get("sport_slug") or candidate_payload.get("sport") or candidate_payload.get("league") or "").strip().lower()
        if sport_slug:
            candidate_payload.setdefault("sport_slug", sport_slug)
            candidate_payload.setdefault("sport", sport_slug)

        candidate_type = str(candidate_payload.get("candidate_type") or candidate_payload.get("type") or candidate_payload.get("kind") or "").strip().lower()
        if candidate_type:
            candidate_payload.setdefault("candidate_type", candidate_type)

        market = str(candidate_payload.get("market") or candidate_payload.get("market_type") or candidate_payload.get("market_name") or candidate_payload.get("prop") or candidate_payload.get("label") or "").strip()
        if market:
            candidate_payload.setdefault("market", market)
            candidate_payload.setdefault("market_type", market)

        selection = str(candidate_payload.get("selection") or candidate_payload.get("pick") or candidate_payload.get("side") or candidate_payload.get("choice") or "").strip()
        if selection:
            candidate_payload.setdefault("selection", selection)

        entity = str(candidate_payload.get("entity") or candidate_payload.get("player_name") or candidate_payload.get("player") or candidate_payload.get("team") or candidate_payload.get("subject") or candidate_payload.get("name") or "").strip()
        if entity:
            candidate_payload.setdefault("entity", entity)
            candidate_payload.setdefault("player_name", candidate_payload.get("player_name") or candidate_payload.get("player") or entity)
            candidate_payload.setdefault("name", candidate_payload.get("name") or entity)

        odds = candidate_payload.get("odds") or candidate_payload.get("odds_current") or candidate_payload.get("odds_display")
        if odds is not None and str(odds).strip():
            candidate_payload.setdefault("odds", odds)

        line = candidate_payload.get("line") or candidate_payload.get("market_line") or candidate_payload.get("prop_line")
        if line is not None and str(line).strip():
            candidate_payload.setdefault("line", line)

        subject_key = str(candidate_payload.get("subject_key") or candidate_payload.get("player_name") or candidate_payload.get("name") or candidate_payload.get("entity") or "").strip().lower()
        if subject_key:
            candidate_payload.setdefault("subject_key", subject_key)

        market_key = str(candidate_payload.get("market_key") or candidate_payload.get("market") or candidate_payload.get("selection") or "").strip().lower()
        if market_key:
            candidate_payload.setdefault("market_key", market_key)

        return candidate_payload

    @staticmethod
    def _empty_candidate_pool(selected_date: str | None, source_fingerprint: str) -> dict[str, Any]:
        # Deliberately not cached by the caller (candidate_count == 0 skips
        # the `if pool["candidate_count"] > 0` cache-write below), so a
        # memory-guard abort never poisons a later, healthier cycle.
        return {
            "selected_date": selected_date,
            "source_fingerprint": source_fingerprint,
            "overview": [],
            "candidate_count": 0,
            "candidate_pools": {},
            "global_pool": [],
            "candidates": [],
        }

    def _build_candidate_pool(self, selected_date: str | None, source_fingerprint: str) -> dict[str, Any]:
        cache_key = self._candidate_pool_key(selected_date, source_fingerprint)
        with self._condition:
            cached_pool = self._candidate_pools.get(cache_key)
            if cached_pool is not None:
                return json.loads(json.dumps(cached_pool, default=str))

        # 2026-07-20: this process's own Render disk doesn't have the sport
        # artifacts build_intelligence_overview below is about to read --
        # live-odds-worker (or an on-demand web request) writes them to a
        # different, unshared disk. Only publish_hot_artifact's push
        # (worker -> web) existed before; pull the same allowlist back down
        # here so this computation has fresh data instead of silently
        # reading nothing every time. Best-effort/never-raises by design, so
        # a network blip just means this cycle reads stale local data.
        _diag_log_all_process_memory("build_candidate_pool_start")
        if _abort_build_candidate_pool_if_memory_critical("build_candidate_pool_start"):
            return self._empty_candidate_pool(selected_date, source_fingerprint)
        try:
            from syndicate.features.shared.artifact_publisher import pull_hot_artifacts

            pull_hot_artifacts(date_str=selected_date)
        except Exception as exc:
            print(f"[intelligence_state] PULL_HOT_ARTIFACTS_FAILED error={exc}", flush=True)
        _diag_log_all_process_memory("post_pull_hot_artifacts")
        if _abort_build_candidate_pool_if_memory_critical("post_pull_hot_artifacts"):
            return self._empty_candidate_pool(selected_date, source_fingerprint)

        overview = None
        if self._app is not None:
            try:
                with self._app.app_context():
                    overview = _profile_stage("data_ingestion", build_intelligence_overview, selected_date=selected_date, force_refresh=True)
            except RuntimeError:
                overview = None
        if overview is None:
            # Was build_intelligence_status(...) with only .get("sports")
            # ever used from its return -- confirmed root cause of today's
            # OOM crashes: refresh-worker never has self._app set (see
            # start_intelligence_state_background_loop() call in
            # scripts/run_refresh_worker.py, no app passed), so this branch
            # runs on every single cycle. build_intelligence_status wraps
            # build_intelligence_overview and then does a second full
            # per-sport pass (tracked/advanced summary counts, calling
            # _advanced_input_rows_for_sport again, plus readiness_gate and
            # a simulation-contract file read) -- all of it computed and
            # immediately discarded here, since only the flat sports list
            # was ever read. Calling build_intelligence_overview directly
            # skips that entire redundant pass.
            overview = _profile_stage("data_ingestion", build_intelligence_overview, selected_date=selected_date, force_refresh=True)
            if not isinstance(overview, list):
                overview = []
        _diag_log_all_process_memory("post_build_overview")
        if _abort_build_candidate_pool_if_memory_critical("post_build_overview"):
            return self._empty_candidate_pool(selected_date, source_fingerprint)
        preferences = _query_preferences(
            "top edges today",
            mode="recommendation",
            sport="all",
            timing="all",
            include_props=True,
            include_games=True,
        )
        odds_history_by_sport = self._odds_history_payloads_by_sport(overview)
        # collect_candidates_with_fallback_merge (syndicate/features/intelligence.py)
        # is the shared collect-with-fallback entry point extracted from this
        # function so run_intelligence_query gets the same
        # thin-pool/empty-pool fallback-and-merge behavior instead of only
        # this board-publication path having it. apply_edge_filter mirrors
        # this path's own SYNDICATE_BOARD_APPLY_EDGE_FILTER toggle (default
        # on) -- a kill-switch for the edge-quality gate without a code
        # revert if published-candidate volume drops more than expected.
        raw_candidates = _profile_stage(
            "candidate_collection_with_fallback",
            collect_candidates_with_fallback_merge,
            overview,
            preferences,
            odds_history_by_sport,
            selected_date=selected_date,
            apply_edge_filter=_env_bool("SYNDICATE_BOARD_APPLY_EDGE_FILTER", default=True),
        )
        _diag_log_all_process_memory("post_collect_candidates_with_fallback_merge")
        if _abort_build_candidate_pool_if_memory_critical("post_collect_candidates_with_fallback_merge"):
            return self._empty_candidate_pool(selected_date, source_fingerprint)

        raw_candidates = [candidate for candidate in raw_candidates if isinstance(candidate, Mapping)]
        candidate_build_started_at = time.perf_counter()
        candidate_entries: list[dict[str, Any]] = []
        for candidate in raw_candidates:
            candidate_entry = self._serialize_candidate(candidate)
            if not candidate_entry:
                continue
            _apply_candidate_tier_penalty(candidate_entry)
            candidate_entry["candidate_id"] = self._candidate_id(candidate_entry)
            candidate_entry["raw_inputs"] = self._candidate_raw_inputs(candidate_entry)
            candidate_entry["precomputed_features"] = self._candidate_precomputed_features(candidate_entry)
            candidate_entry["preliminary_scores"] = self._candidate_preliminary_scores(candidate_entry)
            candidate_entry["source_fingerprint"] = source_fingerprint
            candidate_entry = attach_market_id(
                candidate_entry,
                sport=candidate_entry.get("sport_slug") or candidate_entry.get("sport"),
                event_id=candidate_entry.get("event_id") or candidate_entry.get("matchup") or candidate_entry.get("game_id"),
                market_type=candidate_entry.get("market_type") or candidate_entry.get("market") or candidate_entry.get("selection") or candidate_entry.get("period"),
                entity=candidate_entry.get("entity") or candidate_entry.get("player_name") or candidate_entry.get("player") or candidate_entry.get("team") or candidate_entry.get("selection"),
                line=candidate_entry.get("line") or candidate_entry.get("market_line") or candidate_entry.get("prop_line"),
            )
            candidate_entries.append(candidate_entry)
        _log_stage_timing("candidate_building", (time.perf_counter() - candidate_build_started_at) * 1000.0)
        _diag_log_all_process_memory("post_candidate_building")
        if _abort_build_candidate_pool_if_memory_critical("post_candidate_building"):
            return self._empty_candidate_pool(selected_date, source_fingerprint)

        manifests = self._available_sport_manifests(selected_date)
        candidate_pools: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
        manifest_shard_keys = {sport_slug: resolve_current_shard_key(sport_slug, selected_date) for sport_slug in manifests}
        for sport_slug, manifest in manifests.items():
            if _abort_build_candidate_pool_if_memory_critical(f"manifest_loop_sport={sport_slug}"):
                return self._empty_candidate_pool(selected_date, source_fingerprint)
            odds_history_payload = self._load_odds_history_payload_for_sport(sport_slug, manifest_shard_keys[sport_slug])
            odds_history_markets = self._odds_history_market_states(odds_history_payload)
            sport_candidates: list[dict[str, Any]] = []
            for candidate in candidate_entries:
                candidate_sport = str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower()
                if candidate_sport != sport_slug:
                    continue
                sport_candidate = dict(candidate)
                sport_candidate["sport_manifest_last_updated"] = str(manifest.get("last_updated") or "").strip() or None
                sport_candidate["sport_manifest_status"] = str(manifest.get("status") or "").strip() or None
                sport_candidate["sport_manifest_artifact_paths"] = [str(path).strip() for path in (manifest.get("artifact_paths") or []) if str(path).strip()] if isinstance(manifest.get("artifact_paths"), list) else []
                sport_candidate["sport_manifest_metadata"] = dict(manifest.get("metadata") or {}) if isinstance(manifest.get("metadata"), dict) else {}
                market_id = str(sport_candidate.get("market_id") or "").strip()
                history_state = odds_history_markets.get(market_id) if market_id else None
                if history_state:
                    history_rows = history_state.get("history") if isinstance(history_state.get("history"), list) else []
                    sport_candidate["delta_line"] = history_state.get("delta_line")
                    sport_candidate["movement"] = history_state.get("movement")
                    sport_candidate["last_updated"] = history_state.get("last_updated")
                    sport_candidate["odds_history"] = {
                        "market_id": market_id,
                        "last_line": history_state.get("last_line"),
                        "last_odds": history_state.get("last_odds"),
                        "delta_line": history_state.get("delta_line"),
                        "movement": history_state.get("movement"),
                        "last_updated": history_state.get("last_updated"),
                        "recent_trend": history_rows[-3:],
                    }
                sport_candidates.append(sport_candidate)
            if not sport_candidates:
                continue
            candidate_pools[sport_slug] = sport_candidates

        global_pool = self._merge_candidate_pools(candidate_pools)
        if not candidate_pools:
            global_pool = []

        pool = {
            "selected_date": selected_date,
            "source_fingerprint": source_fingerprint,
            "overview": [dict(item) for item in overview if isinstance(item, Mapping)],
            "candidate_count": len(global_pool),
            "candidate_pools": {
                sport_slug: {
                    "sport": sport_slug,
                    "last_updated": str(manifest.get("last_updated") or "").strip() or None,
                    "status": str(manifest.get("status") or "").strip() or None,
                    "artifact_paths": [str(path).strip() for path in (manifest.get("artifact_paths") or []) if str(path).strip()] if isinstance(manifest.get("artifact_paths"), list) else [],
                    "metadata": dict(manifest.get("metadata") or {}) if isinstance(manifest.get("metadata"), dict) else {},
                    "candidate_count": len(candidate_pools.get(sport_slug, [])),
                    "candidates": candidate_pools.get(sport_slug, []),
                    # Pointer, not payload (see manifest.py's publish_sport_manifest
                    # for the same contract): nothing downstream ever read a full
                    # embedded odds_history copy here -- individual candidates
                    # already carry their own market-scoped odds_history slice
                    # (set above, from the same shard load at line ~1552). This
                    # used to load and embed the ENTIRE sport odds-history
                    # payload a second time, which then got cached up to
                    # _max_snapshots deep and JSON-round-tripped on every read --
                    # the dominant memory driver once odds-history grew ~100x.
                    "odds_history_shard_key": manifest_shard_keys.get(sport_slug),
                }
                for sport_slug, manifest in manifests.items()
                if sport_slug in candidate_pools
            },
            "global_pool": global_pool,
            "candidates": global_pool,
        }
        _diag_log_all_process_memory("post_pool_assembled")
        if pool["candidate_count"] > 0:
            # 2026-07-20: only cache non-empty pools. This cache has no
            # staleness check on the read side (see _build_candidate_pool
            # above), keyed on (selected_date, source_fingerprint) -- and
            # source_fingerprint doesn't change for hours at a time when
            # odds-history data is quiet, so a single empty computation
            # early in a long-running worker's life (e.g. right after
            # restart, before manifests/artifacts existed yet) would get
            # cached and then served for the rest of the day even once the
            # underlying data was fine, since nothing ever invalidates it.
            # Confirmed in production: refresh-worker kept publishing a
            # zero-candidate board for hours while the same computation,
            # run fresh on a freshly-restarted process, produced 72 real
            # candidates. Not caching empty results means a bad early read
            # just gets retried next cycle instead of sticking forever.
            with self._condition:
                self._candidate_pools[cache_key] = pool
                self._candidate_pools.move_to_end(cache_key)
                self._trim_ordered_dict(self._candidate_pools, self._max_snapshots)
        return json.loads(json.dumps(pool, default=str))

    def start(self, app: Flask | None = None) -> bool:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if app is not None:
                self._app = app
            self._load_persisted_state_locked()
            self._stop.clear()
            self._thread = threading.Thread(target=self._background_loop, name="syndicate-intelligence-state-loop", daemon=True)
            self._thread.start()
            self._running = True
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            if not self._snapshots or latest_snapshot is None or self._is_stale(latest_snapshot):
                self._enqueue_locked(self._default_payload())
                # 2026-07-20: _enqueue_locked only updates in-memory state.
                # _background_loop's very first iteration calls
                # _sync_persisted_queue_locked(), which overwrites
                # self._pending_keys/self._watched_payloads FROM the shared
                # store -- so this boot-time enqueue was getting silently
                # wiped before the loop thread ever got a chance to process
                # it, unless the store already happened to have a matching
                # entry. Confirmed in production: a freshly restarted
                # refresh-worker with an empty/stale persisted queue never
                # computed anything at all until manually re-queued from an
                # external request. Persist immediately so the loop's first
                # sync reads this entry back instead of losing it.
                self._persist_locked()
            return True

    def status(self, *, force_refresh: bool = True) -> dict[str, Any]:
        with self._lock:
            self._sync_persisted_state_locked(force=force_refresh)
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            latest_age_seconds = self._snapshot_age_seconds(latest_snapshot)
            freshness_sla_seconds = int(self._interval_seconds)
            return {
                "enabled": True,
                "intervalSeconds": int(self._interval_seconds),
                "waitTimeoutSeconds": int(self._wait_timeout_seconds),
                "threadAlive": bool(self._thread is not None and self._thread.is_alive()),
                "running": bool(self._running),
                "latestKey": self._latest_key,
                "cachedSnapshots": len(self._snapshots),
                "cachedCandidatePools": len(self._candidate_pools),
                "latestComputedAt": latest_snapshot.computed_at if latest_snapshot else None,
                "latestSourceFingerprint": latest_snapshot.source_fingerprint if latest_snapshot else None,
                "latestSnapshotAgeSeconds": latest_age_seconds,
                "lastRunStartedAt": _utc_from_epoch(self._last_run_started_at),
                "lastRunFinishedAt": _utc_from_epoch(self._last_run_finished_at),
                "lastRunKey": self._last_run_key,
                "freshnessSlaSeconds": freshness_sla_seconds,
                "freshnessStatus": "fresh" if latest_age_seconds is not None and latest_age_seconds <= freshness_sla_seconds else "stale",
                "isFresh": bool(latest_age_seconds is not None and latest_age_seconds <= freshness_sla_seconds),
            }

    def get_response(self, payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload)
        key = _payload_key(normalized_payload)
        with self._condition:
            self._sync_persisted_state_locked(force=force_refresh)
            self._watched_payloads[key] = normalized_payload
            self._watched_payloads.move_to_end(key)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
            snapshot = self._snapshots.get(key)
            if refresh or snapshot is None:
                self._enqueue_locked(normalized_payload)
            elif self._is_stale(snapshot):
                self._enqueue_locked(normalized_payload)
            if snapshot is not None and not refresh and not self._is_stale(snapshot):
                return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
            if wait:
                self._condition.wait_for(lambda: key in self._snapshots and not self._is_stale(self._snapshots[key]), timeout=self._wait_timeout_seconds)
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
            if self._latest_key and self._latest_key in self._snapshots:
                latest_snapshot = self._snapshots[self._latest_key]
                return _decorate_response_with_state_meta(dict(latest_snapshot.response), latest_snapshot, source="worker", run_key=latest_snapshot.key, sla_seconds=self._interval_seconds)
        return None

    def read_latest_response(
        self,
        payload: dict[str, Any] | None = None,
        *,
        force_refresh: bool = True,
        allow_latest_fallback: bool = False,
    ) -> dict[str, Any] | None:
        normalized_payload = self._normalize_payload(payload or self._default_payload())
        key = _payload_key(normalized_payload)
        requested_date = _selected_date_from_payload(normalized_payload)
        requested_sport = _requested_sport_from_payload(normalized_payload)
        with self._lock:
            # 2026-07-19: this in-process self._snapshots cache is per-process
            # (web service vs refresh-worker each hold their own), so on a
            # process that doesn't compute snapshots itself (the web service,
            # SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false), a hit
            # here used to return unconditionally -- once populated for a given
            # key (e.g. at process start), it was served forever, even hours
            # stale, because nothing ever re-synced from the shared persisted
            # store for that exact key again. Confirmed in production: the
            # default board query stayed frozen on a snapshot from before a
            # same-day candidate-classification fix landed, for 3+ hours after
            # the fix was live and refresh-worker was producing fresh
            # snapshots the whole time. Now falls through to
            # _sync_persisted_state_locked() below when the local copy is
            # stale, same threshold _enqueue_locked already uses to decide
            # whether a snapshot needs recomputing.
            snapshot = self._snapshots.get(key)
            if snapshot is not None and not self._is_stale(snapshot):
                return dict(snapshot.response)
            if requested_sport and requested_sport != "all":
                for candidate_snapshot in reversed(list(self._snapshots.values())):
                    if _snapshot_matches_payload(candidate_snapshot, normalized_payload) and not self._is_stale(candidate_snapshot):
                        return dict(candidate_snapshot.response)
            if self._latest_key and self._latest_key in self._snapshots:
                latest_snapshot = self._snapshots[self._latest_key]
                latest_date = _selected_date_from_payload(latest_snapshot.payload)
                latest_sport = _snapshot_sport(latest_snapshot)
                if (
                    not self._is_stale(latest_snapshot)
                    and (allow_latest_fallback or requested_date is None or latest_date is None or latest_date == requested_date)
                    and _snapshot_limit_matches(latest_snapshot, normalized_payload)
                ):
                    if not requested_sport or requested_sport == "all" or latest_sport == requested_sport:
                        return dict(latest_snapshot.response)
            if requested_sport and requested_sport != "all":
                self._sync_persisted_state_locked(force=force_refresh)
                for candidate_snapshot in reversed(list(self._snapshots.values())):
                    if _snapshot_matches_payload(candidate_snapshot, normalized_payload):
                        return dict(candidate_snapshot.response)
                return None
            self._sync_persisted_state_locked(force=force_refresh)
            snapshot = self._snapshots.get(key)
            if snapshot is not None:
                return dict(snapshot.response)
            latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
            if latest_snapshot is not None:
                latest_date = _selected_date_from_payload(latest_snapshot.payload)
                latest_sport = _snapshot_sport(latest_snapshot)
                if (
                    (allow_latest_fallback or requested_date is None or latest_date is None or latest_date == requested_date)
                    and _snapshot_limit_matches(latest_snapshot, normalized_payload)
                ):
                    if not requested_sport or requested_sport == "all" or latest_sport == requested_sport:
                        return dict(latest_snapshot.response)
            return None

    def queue_refresh(self, payload: dict[str, Any]) -> str:
        normalized_payload = self._normalize_payload(payload)
        with self._condition:
            self._watched_payloads[_payload_key(normalized_payload)] = normalized_payload
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
            key = self._enqueue_locked(normalized_payload)
            self._persist_locked()
            return key

    def _default_payload(self) -> dict[str, Any]:
        return {
            "question": "top edges today",
            "date": central_today_iso(),
            "mode": "live",
            "sport": "all",
            "timing": "",
            "include_props": True,
            "include_games": True,
            "force_refresh": True,
        }

    def _sync_persisted_state_locked(self, *, force: bool = True) -> None:
        self._load_persisted_state_locked(force=force or _state_backend_kind() == "keyvalue")

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized.pop("user_profile", None)
        normalized.pop("force_refresh", None)
        if not str(normalized.get("question") or "").strip():
            normalized["question"] = "top edges today"
        if not str(normalized.get("date") or normalized.get("selected_date") or "").strip():
            normalized["date"] = central_today_iso()
        normalized.setdefault("mode", "live")
        normalized.setdefault("sport", "all")
        normalized["force_refresh"] = True
        return normalized

    def _enqueue_locked(self, payload: dict[str, Any]) -> str:
        key = _payload_key(payload)
        snapshot = self._snapshots.get(key)
        if snapshot is not None and not self._is_stale(snapshot):
            return key
        if key in self._pending_keys:
            self._pending_keys[key] = payload
            self._pending_keys.move_to_end(key)
            return key
        if self._last_run_key == key and self._last_run_finished_at > 0.0 and (time.time() - self._last_run_finished_at) < float(self._interval_seconds):
            return key
        self._pending_keys[key] = payload
        self._pending_keys.move_to_end(key)
        self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        self._condition.notify_all()
        return key

    def _background_loop(self) -> None:
        loop_started_at = time.time()
        logger.info("BACKGROUND_LOOP_START", extra={"elapsed_ms": 0.0})
        print("[intelligence_state] BACKGROUND_LOOP_START", flush=True)
        # Bounds how long the odds-refresh hazard may hold off the build; see
        # _board_build_deferral_reason. Local to the loop, so a restart starts
        # the count fresh rather than inheriting a stale wait.
        consecutive_odds_refresh_defers = 0
        consecutive_sim_defers = 0
        while not self._stop.is_set():
            iteration_started_at = time.time()
            # Temporary diagnostic (see _diag_log_all_process_memory): every
            # _build_candidate_pool checkpoint went silent for the full
            # ~30s gap before the last several OOM crashes, meaning this
            # loop may never be reaching that call at all on a fresh boot
            # (e.g. sitting in the condition.wait() below with an empty
            # _pending_keys). This unconditional print on every iteration
            # -- to stdout, not the memory helper's stderr, in case that's
            # a factor -- settles whether the thread is genuinely idle or
            # actually working. Remove once resolved.
            print(f"[intelligence_state] LOOP_ITERATION pending_keys={len(self._pending_keys)} watched_payloads={len(self._watched_payloads)}", flush=True)
            if canonical_board_state_enabled() or canonical_board_state_shadow_compare_enabled():
                # Additive dual-write during the migration-step-2 validation
                # window: drains _watched_board_dates and writes the new
                # canonical board_state_*.json alongside the legacy
                # board_snapshot_*.json/intelligence_state_*.json writes
                # below. Gated by either flag, not just the serving one --
                # shadow-compare's whole point is to observe what canonical
                # WOULD produce without serving it, which requires this
                # write step to actually run. Confirmed live 2026-07-22:
                # with only shadow-compare on, dates got queued (queue side
                # already checked either flag) but never drained/written
                # here (this check used to be serving-flag-only), so
                # shadow-compare could never see anything but
                # "canonical_miss" -- the read side (_load_canonical_board_response)
                # already checked either flag correctly; only this write
                # gate was inconsistent with it.
                # Runs off the main loop entirely (see
                # _drain_one_watched_board_date_async/_board_state_drain_thread) --
                # confirmed live 2026-07-22 that _build_intelligence_board_state
                # can run past 10 minutes for a single date, and calling it
                # inline here used to block this same loop's legacy queue
                # processing below for that whole duration.
                self._drain_one_watched_board_date_async()
            payload_to_process: dict[str, Any] | None = None
            with self._condition:
                self._sync_persisted_queue_locked()
                if not self._pending_keys:
                    evictable_keys: dict[str, str] = {}
                    today_iso = central_today_iso()
                    for key, watched_payload in list(self._watched_payloads.items()):
                        # See _watched_payload_eviction_reason for why an
                        # entry can be unreplayable, and why letting one sit
                        # here is actively harmful rather than merely wasteful.
                        eviction_reason = _watched_payload_eviction_reason(watched_payload, today_iso)
                        if eviction_reason is not None:
                            evictable_keys[key] = eviction_reason
                            continue
                        snapshot = self._snapshots.get(key)
                        if snapshot is None or self._is_stale(snapshot):
                            self._pending_keys[key] = watched_payload
                    for key in evictable_keys:
                        self._watched_payloads.pop(key, None)
                        self._snapshots.pop(key, None)
                        self._pending_keys.pop(key, None)
                        if self._latest_key == key:
                            self._latest_key = None
                    if evictable_keys:
                        # print, not logger.info -- logger output does not reach
                        # Render's log collector, which is how the stale-date
                        # replay stayed invisible for a full day.
                        print(
                            f"[intelligence_state] EVICTED_WATCHED_PAYLOADS today={today_iso} "
                            f"{json.dumps(evictable_keys, sort_keys=True)}",
                            flush=True,
                        )
                        self._persist_locked()
                    self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
                if self._pending_keys:
                    _, payload_to_process = self._pending_keys.popitem(last=False)
                else:
                    self._condition.wait(timeout=self._interval_seconds)
                    continue
            if payload_to_process is None:
                continue
            # Checked at the point of USE, not only during queue maintenance.
            # The eviction sweep above sits inside `if not self._pending_keys`,
            # so it only runs when the queue is EMPTY -- and production is
            # never empty (observed pending_keys=3, watched_payloads=4). That
            # is why the #65 future-date eviction shipped and then never fired
            # once: the payload was popped straight past the sweep that was
            # supposed to remove it. Guarding here cannot be bypassed by a
            # backlog.
            unbuildable = _watched_payload_eviction_reason(payload_to_process, central_today_iso())
            if unbuildable is not None:
                key = _payload_key(payload_to_process)
                print(f"[intelligence_state] SKIPPED_UNBUILDABLE_PAYLOAD reason={unbuildable} key={key}", flush=True)
                with self._condition:
                    # Drop it from BOTH maps, or _sync_persisted_queue_locked
                    # re-reads it from the shared store next iteration and this
                    # becomes a hot loop that never computes anything.
                    self._watched_payloads.pop(key, None)
                    self._pending_keys.pop(key, None)
                    self._snapshots.pop(key, None)
                    if self._latest_key == key:
                        self._latest_key = None
                    self._persist_locked()
                continue
            guard_acquired = False
            run_failed = False
            run_started_at = time.time()
            print(f"[intelligence_state] LOOP_POPPED_PAYLOAD key={_payload_key(payload_to_process)}", flush=True)
            # #55: yield the container to a resident MLB sim. Re-queue rather
            # than drop -- this payload still needs computing, just not while
            # 1.1GB of sim is resident in a 2GB container.
            deferral_reason = _board_build_deferral_reason(
                consecutive_odds_defers=consecutive_odds_refresh_defers,
                consecutive_sim_defers=consecutive_sim_defers,
            )
            if deferral_reason == "sim_subprocess_resident":
                consecutive_sim_defers += 1
            elif deferral_reason == "odds_refresh_in_flight":
                consecutive_odds_refresh_defers += 1
            elif deferral_reason is None:
                # Reset only on an actual run: a sim deferral must not clear
                # the odds counter, or alternating hazards would hold it
                # below the bound forever and reintroduce the starvation.
                consecutive_odds_refresh_defers = 0
                consecutive_sim_defers = 0
            if deferral_reason is not None:
                # Deliberately NOT named DEFERRED_TO_MLB_SIM: this fires for
                # the odds-refresh case too, and a sim-specific name would
                # send whoever greps it on 2026-07-25's wrong trail again.
                print(f"[intelligence_state] DEFERRED_BOARD_BUILD reason={deferral_reason}", flush=True)
                with self._condition:
                    self._pending_keys[_payload_key(payload_to_process)] = payload_to_process
                    self._pending_keys.move_to_end(_payload_key(payload_to_process))
                    self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
                    self._condition.wait(timeout=float(self._interval_seconds))
                continue
            try:
                guard_acquired = self._execution_guard.acquire(blocking=False)
                print(f"[intelligence_state] GUARD_ACQUIRE_RESULT acquired={guard_acquired}", flush=True)
                if not guard_acquired:
                    with self._condition:
                        self._pending_keys[_payload_key(payload_to_process)] = payload_to_process
                        self._pending_keys.move_to_end(_payload_key(payload_to_process))
                        self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
                        self._condition.wait(timeout=min(1.0, float(self._interval_seconds)))
                    continue
                logger.info("WORKER RUN", extra={"payload_key": _payload_key(payload_to_process)})
                logger.info("BACKGROUND_LOOP_PRE_BOARD_PUBLISH", extra={"elapsed_ms": round((time.time() - iteration_started_at) * 1000.0, 3)})
                print("[intelligence_state] CALLING_COMPUTE_BOARD_PUBLICATION_RESPONSE", flush=True)
                state = self._compute_board_publication_response(payload_to_process)
                print("[intelligence_state] RETURNED_FROM_COMPUTE_BOARD_PUBLICATION_RESPONSE", flush=True)
                logger.info("BACKGROUND_LOOP_POST_BOARD_PUBLISH", extra={"elapsed_ms": round((time.time() - iteration_started_at) * 1000.0, 3)})
                logger.info("BACKGROUND_LOOP_PRE_PERSIST", extra={"elapsed_ms": round((time.time() - iteration_started_at) * 1000.0, 3)})
                written_state = write_latest_intelligence_state(state)
                logger.info("BACKGROUND_LOOP_POST_PERSIST", extra={"elapsed_ms": round((time.time() - iteration_started_at) * 1000.0, 3)})
                if written_state is None:
                    response = {
                        "ok": False,
                        "error": "invalid worker state",
                        "response": {},
                        "top_opportunities": [],
                        "by_sport": {},
                        "analysis": None,
                    }
                else:
                    response = dict(written_state)
            except Exception as exc:
                # Root-caused 2026-07-25: this handler swallowed the only
                # evidence that anything went wrong. It logged nothing at
                # all, then built a hardcoded zero-candidate response which
                # the code below unconditionally installs as self._latest_key
                # -- so a throw anywhere in _compute_board_publication_response
                # silently replaced a good, fully-computed board with an empty
                # one, every single cycle, and the only externally visible
                # symptom was "board shows 0 candidates". Confirmed live: the
                # checkpoint prints showed pool/serialize/rank all succeeding
                # with 67-71 candidates, then BUILDING_LIVE_PIPELINE_SUMMARY,
                # then nothing -- no BOARD_PUBLICATION_RESPONSE_READY, no
                # error -- straight to the persist of an empty snapshot.
                print(f"[intelligence_state] BOARD_PUBLICATION_FAILED {type(exc).__name__}: {exc}", flush=True)
                try:
                    import traceback

                    print(f"[intelligence_state] BOARD_PUBLICATION_TRACEBACK {traceback.format_exc()}", flush=True)
                except Exception:
                    pass
                run_failed = True
                response = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "response": {},
                    "top_opportunities": [],
                    "by_sport": {},
                    "analysis": None,
                }
            snapshot = IntelligenceSnapshot(
                key=_payload_key(payload_to_process),
                payload=dict(payload_to_process),
                response=response,
                computed_at=_utc_now(),
                source_fingerprint=str(response.get("source_fingerprint") or response.get("latestSourceFingerprint") or "") if isinstance(response, dict) else "",
            )
            with self._condition:
                # A run that raised (see the except above) produces a
                # hardcoded zero-candidate response. Publishing that -- both
                # by replacing this key's previous good snapshot and by
                # taking over self._latest_key, which every board read
                # resolves through -- is what silently replaced a fully
                # computed 67-candidate board with an empty one on every
                # cycle. Keep serving the last good result instead; the next
                # cycle retries from scratch either way. Same "don't regress
                # published state on a transient failure" rule already
                # applied to the rollover decision in
                # _compute_board_publication_response and to the
                # candidate-pool cache in _build_candidate_pool.
                previous_snapshot = self._snapshots.get(snapshot.key)
                previous_count = _intelligence_state_candidate_count(previous_snapshot.response) if previous_snapshot is not None and isinstance(previous_snapshot.response, dict) else 0
                if run_failed and previous_count > 0:
                    print(
                        f"[intelligence_state] SNAPSHOT_UPDATE_SKIPPED_AFTER_FAILURE key={snapshot.key} kept_candidate_count={previous_count}",
                        flush=True,
                    )
                else:
                    self._snapshots[snapshot.key] = snapshot
                    self._snapshots.move_to_end(snapshot.key)
                    existing_latest = self._snapshots.get(self._latest_key or "") if self._latest_key else None
                    existing_latest_count = _intelligence_state_candidate_count(existing_latest.response) if existing_latest is not None and isinstance(existing_latest.response, dict) else 0
                    snapshot_count = _intelligence_state_candidate_count(response) if isinstance(response, dict) else 0
                    if snapshot_count > 0 or existing_latest_count <= 0 or self._latest_key == snapshot.key:
                        self._latest_key = snapshot.key
                    else:
                        print(
                            f"[intelligence_state] LATEST_KEY_PROMOTION_SKIPPED key={snapshot.key} snapshot_count={snapshot_count} existing_latest_count={existing_latest_count}",
                            flush=True,
                        )
                self._last_run_key = snapshot.key
                self._last_run_started_at = run_started_at
                self._last_run_finished_at = time.time()
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                self._persist_locked()
                self._condition.notify_all()
                self._condition.wait(timeout=self._interval_seconds)
            if guard_acquired:
                self._execution_guard.release()

    def _compute_board_publication_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_started_at = time.perf_counter()
        request_payload = dict(payload)
        question = str(request_payload.get("question") or "").strip() or "top edges today"
        selected_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip() or None
        requested_sport = str(request_payload.get("sport") or "all").strip().lower() or "all"
        limit = request_payload.get("limit")
        try:
            limit_value = int(limit) if limit is not None and str(limit).strip() else None
        except Exception:
            limit_value = None

        # Root-caused 2026-07-24: this is the *actual* earliest expensive
        # step, upstream of every _build_candidate_pool checkpoint and guard
        # added earlier today. _source_state_fingerprint calls (via
        # _load_cached_status_payload returning None on a fresh boot, before
        # self._source_fingerprints has anything cached) the full, expensive
        # build_intelligence_status() -- unconditionally, on every single
        # call. Confirmed live: the crash consistently happens after
        # "CALLING_COMPUTE_BOARD_PUBLICATION_RESPONSE" prints but before ANY
        # _build_candidate_pool checkpoint ever fires, meaning this call is
        # where the memory actually goes. Same guard pattern as
        # _build_candidate_pool below.
        print("[intelligence_state] CALLING_SOURCE_STATE_FINGERPRINT", flush=True)
        _diag_log_all_process_memory("pre_source_state_fingerprint")
        if _abort_build_candidate_pool_if_memory_critical("pre_source_state_fingerprint"):
            return _decorate_response_with_state_meta(
                {
                    "ok": False,
                    "error": "memory_guard_abort",
                    "top_opportunities": [],
                    "recommendations": [],
                    "by_sport": {},
                    "selected_date": selected_date,
                    "candidate_count": 0,
                },
                None,
                source="worker",
                run_key=_payload_key(request_payload),
                sla_seconds=self._interval_seconds,
            ) or {}
        source_fingerprint = self._source_state_fingerprint(selected_date)
        print("[intelligence_state] RETURNED_FROM_SOURCE_STATE_FINGERPRINT", flush=True)
        cache_key = _payload_key(request_payload)
        logger.info("BETTING_BOARD_PUBLISH_START", extra={"selected_date": selected_date, "question": question})

        candidate_pool = self._build_candidate_pool(selected_date, source_fingerprint)
        candidate_pool_count = int(candidate_pool.get("candidate_count") or 0)
        # 2026-07-25: everything below this point (through the final return)
        # was only ever traced via logger.info/_log_stage_timing -- confirmed
        # those calls never reach Render's log collector for this process
        # (zero occurrences across hours of pulled logs, unlike the plain
        # print() checkpoints elsewhere in this file, which always show up).
        # That made this whole stretch invisible: _build_candidate_pool's own
        # post_pool_assembled print was firing, but nothing downstream of it
        # ever printed again, so a hang or slow spot here was indistinguishable
        # from one anywhere else in the function. Bounding it with plain
        # prints to find out which part it actually is.
        print(f"[intelligence_state] CANDIDATE_POOL_READY date={selected_date} count={candidate_pool_count}", flush=True)
        if candidate_pool_count <= 0 and selected_date == central_today_iso():
            rollover_date = _next_supported_intelligence_date(selected_date)
            if rollover_date and rollover_date != selected_date:
                # print, not logger.info: BETTING_BOARD_PUBLISH_DATE below
                # records the same decision but never reaches Render's log
                # collector (#37), so from production logs there has been no
                # way to tell today's build from the probe that follows it.
                # Both halves emit their own overview_counts/artifact_status/
                # candidate_generation traces carrying context_label, so the
                # label cannot discriminate them and a tail of the logs shows
                # only the probe. That ambiguity has now been misread into
                # three separate investigations (#65, #68, #78). These two
                # prints bracket the probe explicitly so the next reader does
                # not have to infer it from ordering.
                print(
                    f"[intelligence_state] ROLLOVER_PROBE_BEGIN today={selected_date} probing={rollover_date}",
                    flush=True,
                )
                rollover_fingerprint = self._source_state_fingerprint(rollover_date)
                rollover_pool = self._build_candidate_pool(rollover_date, rollover_fingerprint)
                rollover_count = int(rollover_pool.get("candidate_count") or 0)
                # 2026-07-20: only actually commit to the rollover if it
                # produced more than today did -- otherwise a merely
                # transient zero for today (e.g. an artifact-pull hiccup on
                # this one cycle, not "today's slate is over") permanently
                # switches the published board to tomorrow's date, which is
                # guaranteed to also be zero since tomorrow hasn't started
                # yet, and nothing here ever switches back to today even
                # once today's real data becomes available on a later
                # cycle. Confirmed in production: today had real WNBA/MLB
                # games the whole time; a single zero reading rolled the
                # board over to a permanently-empty tomorrow.
                print(
                    f"[intelligence_state] ROLLOVER_PROBE_END probed={rollover_date} "
                    f"probe_count={rollover_count} today_count={candidate_pool_count} "
                    f"committed={rollover_count > candidate_pool_count}",
                    flush=True,
                )
                if rollover_count > candidate_pool_count:
                    logger.info("BETTING_BOARD_PUBLISH_DATE", extra={"requested_date": selected_date, "selected_date": rollover_date, "rollover": True})
                    selected_date = rollover_date
                    request_payload["date"] = rollover_date
                    source_fingerprint = rollover_fingerprint
                    cache_key = _payload_key(request_payload)
                    candidate_pool = rollover_pool
                    candidate_pool_count = rollover_count

        logger.info("BETTING_BOARD_PUBLISH_DATE", extra={"requested_date": str(payload.get("date") or payload.get("selected_date") or "").strip() or None, "selected_date": selected_date, "candidate_count": candidate_pool_count})
        candidates = [self._serialize_candidate(candidate) for candidate in candidate_pool.get("candidates") if isinstance(candidate, Mapping)]
        print(f"[intelligence_state] CANDIDATES_SERIALIZED count={len(candidates)}", flush=True)

        ranked_candidates = _profile_stage("candidate_scoring", _balanced_recommendation_order, candidates)
        print(f"[intelligence_state] CANDIDATES_RANKED count={len(ranked_candidates)}", flush=True)
        if ranked_candidates:
            top_candidates = [dict(candidate) for candidate in ranked_candidates if isinstance(candidate, Mapping)]
        elif candidates:
            top_candidates = self._rank_fallback_candidates(candidates)
        else:
            top_candidates = []

        # Group by sport from the full ranked pool (not the sport-scoped/
        # limited slice below) so by_sport always reflects true per-sport
        # availability, even when the request asks for one specific sport.
        by_sport: dict[str, list[dict[str, object]]] = {}
        for recommendation in top_candidates:
            sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
            by_sport.setdefault(sport_key, []).append(dict(recommendation))

        # _build_candidate_pool always builds a sport="all" pool (it's cached
        # by date only, not by sport), so without this the requested "sport"
        # filter was applied nowhere: a request for sport=nba or sport=wnba
        # silently got back the same MLB-dominated global ranking as
        # sport=mlb or sport=all. Confirmed live in production: sport=nba and
        # sport=wnba queries returned identical MLB-tagged candidates.
        sport_scoped_candidates = top_candidates if requested_sport == "all" else by_sport.get(requested_sport, [])

        if limit_value is None:
            top_opportunities = list(sport_scoped_candidates)
        else:
            opportunity_limit = max(int(limit_value), 1) if sport_scoped_candidates else max(int(limit_value), 0)
            top_opportunities = sport_scoped_candidates[:opportunity_limit]

        response_last_updated = _utc_now()
        response_candidate_count = len(candidates)
        response: dict[str, Any] = {
            "ok": True,
            "top_opportunities": top_opportunities,
            "recommendations": [dict(item) for item in top_opportunities],
            "by_sport": by_sport,
            "analysis": None,
            "portfolio": {},
            "parlays": [],
            "selected_date": selected_date,
            "state_last_updated": response_last_updated,
            "last_updated": response_last_updated,
            "snapshot_generated_at": response_last_updated,
            "candidate_count": response_candidate_count,
        }
        print("[intelligence_state] BUILDING_BOARD_CONTRACT", flush=True)
        response["board_contract"] = build_intelligence_board_contract(response)
        print("[intelligence_state] BUILDING_LIVE_PIPELINE_SUMMARY", flush=True)
        response["live_pipeline"] = self._live_pipeline_summary(
            candidate_pool=candidate_pool,
            candidates=candidates,
            top_candidates=top_candidates,
            top_opportunities=top_opportunities,
            board_contract=response["board_contract"],
            selected_date=selected_date,
            sport=str(request_payload.get("sport") or "all").strip().lower() or "all",
        )
        response = _decorate_response_with_state_meta(dict(response), None, source="worker", run_key=cache_key, sla_seconds=self._interval_seconds) or dict(response)
        _log_stage_timing("board_publication", (time.perf_counter() - request_started_at) * 1000.0)
        logger.info("BETTING_BOARD_PUBLISH_COMPLETE", extra={"selected_date": selected_date, "candidate_count": response_candidate_count, "snapshot_generated_at": response_last_updated})
        print(
            f"[intelligence_state] BOARD_PUBLICATION_RESPONSE_READY "
            f"selected_date={selected_date} candidate_count={response_candidate_count}",
            flush=True,
        )
        return response

    def _build_intelligence_board_state(self, selected_date: str | None) -> dict[str, Any]:
        # Canonical, per-date, unsliced board state (migration step 2). Built
        # on top of _compute_board_publication_response with sport="all" and
        # no limit -- exactly what that method already computes internally
        # before it (re-)applies a per-request sport/limit slice -- so this
        # doesn't duplicate the candidate-pool/ranking/rollover logic, only
        # the shape of what gets persisted. covered_sports/by_sport are
        # widened to include every sport this pool considered, even ones with
        # zero candidates, which _compute_board_publication_response's own
        # by_sport does not: it only contains sports that actually produced
        # candidates (see _build_candidate_pool's candidate_pools dict, which
        # skips a sport entirely via `if not sport_candidates: continue`).
        base_response = self._compute_board_publication_response(
            {"date": selected_date, "sport": "all", "question": "top edges today"}
        )
        resolved_date = str(base_response.get("selected_date") or selected_date or central_today_iso()).strip() or central_today_iso()
        covered_sports = sorted(self._available_sport_manifests(resolved_date).keys())
        by_sport = {sport_slug: list(candidates) for sport_slug, candidates in dict(base_response.get("by_sport") or {}).items()}
        for sport_slug in covered_sports:
            by_sport.setdefault(sport_slug, [])
        return {
            "selected_date": resolved_date,
            "source_fingerprint": self._source_state_fingerprint(resolved_date),
            "computed_at": _utc_now(),
            "candidate_count": int(base_response.get("candidate_count") or 0),
            "covered_sports": covered_sports,
            "by_sport": by_sport,
            "ranked_all": [dict(item) for item in (base_response.get("top_opportunities") or []) if isinstance(item, Mapping)],
            "board_contract": base_response.get("board_contract"),
            "live_pipeline": base_response.get("live_pipeline"),
            "state_meta": base_response.get("state_meta"),
        }

    def queue_board_state_refresh(self, selected_date: str | None = None) -> str:
        # Separate from queue_refresh()/_watched_payloads below -- see the
        # _watched_board_dates comment in __init__. Collapses however many
        # distinct sport-scoped/question-scoped payloads requested a refresh
        # for the same date into one watched date.
        #
        # Persisted immediately (mirroring queue_refresh below), not just
        # held in memory: the web service (SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false)
        # is where real requests queue a date, but refresh-worker (=true) is
        # the process whose _background_loop actually drains and writes
        # canonical board state -- two separate processes, two separate
        # IntelligenceStateService instances. Confirmed live 2026-07-22:
        # queuing on web never reached refresh-worker's in-memory
        # _watched_board_dates at all until this was persisted through the
        # same shared STATE_PATH store _sync_persisted_queue_locked already
        # re-reads every background-loop iteration.
        normalized_date = str(selected_date or "").strip() or central_today_iso()
        with self._condition:
            self._watched_board_dates[normalized_date] = normalized_date
            self._watched_board_dates.move_to_end(normalized_date)
            self._trim_ordered_dict(self._watched_board_dates, self._max_snapshots)
            self._persist_locked()
            self._condition.notify_all()
        return normalized_date

    def _drain_one_watched_board_date_async(self) -> None:
        # Never block _background_loop's own legacy queue processing on
        # this -- see the _board_state_drain_thread comment in __init__.
        # Skips launching a second drain while one is already running
        # rather than queueing up overlapping canonical builds; the next
        # loop iteration will try again, and _watched_board_dates isn't
        # touched by this check so nothing queued is lost in the meantime.
        with self._condition:
            existing_thread = self._board_state_drain_thread
            if existing_thread is not None and existing_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._drain_one_watched_board_date,
                name="syndicate-board-state-drain",
                daemon=True,
            )
            self._board_state_drain_thread = thread
            thread.start()

    def _drain_one_watched_board_date(self) -> None:
        selected_date: str | None = None
        with self._condition:
            if self._watched_board_dates:
                selected_date, _ = self._watched_board_dates.popitem(last=False)
                # Persist the pop immediately -- otherwise the next
                # _sync_persisted_queue_locked() call (top of every
                # _background_loop iteration) re-reads the still-stale
                # persisted copy and resurrects the date this process just
                # drained, redraining it every single iteration forever.
                self._persist_locked()
        if not selected_date:
            return
        try:
            state = self._build_intelligence_board_state(selected_date)
            write_intelligence_board_state(state)
            logger.info("BOARD_STATE_WRITTEN", extra={"selected_date": selected_date, "candidate_count": state.get("candidate_count")})
        except Exception as exc:
            logger.info("BOARD_STATE_DRAIN_FAILED", extra={"selected_date": selected_date, "error": f"{type(exc).__name__}: {exc}"})
            print(f"[intelligence_state] BOARD_STATE_DRAIN_FAILED selected_date={selected_date} error={exc}", flush=True)

    def _compute_response(self, payload: dict[str, Any], *, force_refresh: bool = False) -> dict[str, Any]:
        request_started_at = time.perf_counter()
        request_payload = dict(payload)
        question = str(request_payload.get("question") or "").strip() or "top edges today"
        selected_date = str(request_payload.get("date") or request_payload.get("selected_date") or "").strip() or None
        requested_sport = str(request_payload.get("sport") or "all").strip().lower() or "all"
        limit = request_payload.get("limit")
        try:
            limit_value = int(limit) if limit is not None and str(limit).strip() else None
        except Exception:
            limit_value = None

        source_fingerprint = self._source_state_fingerprint(selected_date)
        cache_key = _payload_key(request_payload)
        logger.info("BETTING_BOARD_REFRESH_START", extra={"selected_date": selected_date, "force_refresh": bool(force_refresh), "question": question})
        with self._condition:
            snapshot = self._snapshots.get(cache_key)
            if not force_refresh and snapshot is not None and snapshot.source_fingerprint == source_fingerprint and not self._is_stale(snapshot):
                _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                return dict(snapshot.response)

        guard_acquired = self._execution_guard.acquire(blocking=False)
        if not guard_acquired:
            with self._condition:
                snapshot = self._snapshots.get(cache_key)
                if snapshot is not None:
                    _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                    return _decorate_response_with_state_meta(dict(snapshot.response), snapshot, source="worker", run_key=snapshot.key, sla_seconds=self._interval_seconds)
                if self._latest_key and self._latest_key in self._snapshots:
                    _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
                    latest_snapshot = self._snapshots[self._latest_key]
                    return _decorate_response_with_state_meta(dict(latest_snapshot.response), latest_snapshot, source="worker", run_key=latest_snapshot.key, sla_seconds=self._interval_seconds)
            return {"ok": False, "error": "intelligence worker busy", "response": {}, "top_opportunities": [], "by_sport": {}, "analysis": None}

        try:
            with self._condition:
                self._last_run_key = cache_key
                self._last_run_started_at = time.time()

            candidate_pool = self._build_candidate_pool(selected_date, source_fingerprint)
            candidate_pool_count = int(candidate_pool.get("candidate_count") or 0)
            if candidate_pool_count <= 0 and selected_date == central_today_iso():
                rollover_date = _next_supported_intelligence_date(selected_date)
                if rollover_date and rollover_date != selected_date:
                    rollover_fingerprint = self._source_state_fingerprint(rollover_date)
                    rollover_pool = self._build_candidate_pool(rollover_date, rollover_fingerprint)
                    rollover_count = int(rollover_pool.get("candidate_count") or 0)
                    # See the matching comment in _compute_board_publication_response:
                    # only commit to the rollover if it actually beats today,
                    # otherwise a transient zero for today permanently pins
                    # the board to a guaranteed-empty tomorrow.
                    if rollover_count > candidate_pool_count:
                        logger.info("BETTING_BOARD_REFRESH_DATE", extra={"requested_date": selected_date, "selected_date": rollover_date, "rollover": True})
                        selected_date = rollover_date
                        request_payload["date"] = rollover_date
                        source_fingerprint = rollover_fingerprint
                        cache_key = _payload_key(request_payload)
                        candidate_pool = rollover_pool
                        candidate_pool_count = rollover_count
            logger.info("BETTING_BOARD_REFRESH_DATE", extra={"requested_date": str(payload.get("date") or payload.get("selected_date") or "").strip() or None, "selected_date": selected_date, "candidate_count": candidate_pool_count})
            candidates = [self._serialize_candidate(candidate) for candidate in candidate_pool.get("candidates") if isinstance(candidate, Mapping)]

            ranked_candidates = _profile_stage("candidate_scoring", _balanced_recommendation_order, candidates)
            if ranked_candidates:
                top_candidates = [dict(candidate) for candidate in ranked_candidates if isinstance(candidate, Mapping)]
            elif candidates:
                top_candidates = self._rank_fallback_candidates(candidates)
            else:
                top_candidates = []

            by_sport: dict[str, list[dict[str, object]]] = {}
            for recommendation in top_candidates:
                sport_key = str(recommendation.get("sport") or recommendation.get("sport_slug") or "unknown").strip().lower() or "unknown"
                by_sport.setdefault(sport_key, []).append(dict(recommendation))

            # See the matching comment in _compute_board_publication_response:
            # _build_candidate_pool always builds a sport="all" pool, so
            # without this the requested sport filter was never actually
            # applied to the flat recommendations/top_opportunities list.
            sport_scoped_candidates = top_candidates if requested_sport == "all" else by_sport.get(requested_sport, [])

            if limit_value is None:
                top_opportunities = list(sport_scoped_candidates)
            else:
                opportunity_limit = max(int(limit_value), 1) if sport_scoped_candidates else max(int(limit_value), 0)
                top_opportunities = sport_scoped_candidates[:opportunity_limit]

            response_build_started_at = time.perf_counter()
            if self._app is not None:
                with self._app.app_context():
                    analysis_result = run_routed_intelligence_pipeline(request_payload)
            else:
                analysis_result = run_routed_intelligence_pipeline(request_payload)
            if hasattr(analysis_result, "to_dict"):
                analysis = analysis_result.to_dict()
            elif isinstance(analysis_result, dict):
                analysis = dict(analysis_result)
            else:
                analysis = {}

            analysis_recommendations = analysis.get("recommendations") if isinstance(analysis.get("recommendations"), list) else []
            if not any(isinstance(item, dict) for item in analysis_recommendations):
                fallback_recommendations = [self._serialize_candidate(item) for item in top_opportunities if isinstance(item, Mapping)]
                if fallback_recommendations:
                    analysis["recommendations"] = fallback_recommendations
                    if not isinstance(analysis.get("picks"), list) or not analysis.get("picks"):
                        analysis["picks"] = [self._serialize_candidate(item) for item in fallback_recommendations]
                    if not isinstance(analysis.get("top_live_opportunities"), list) or not analysis.get("top_live_opportunities"):
                        analysis["top_live_opportunities"] = [self._serialize_candidate(item) for item in fallback_recommendations]

            response: dict[str, Any] = {
                "ok": True,
                "top_opportunities": top_opportunities,
                "by_sport": by_sport,
                "analysis": analysis,
                "candidate_pool": candidate_pool,
                "selected_date": selected_date,
            }
            response_last_updated = _utc_now()
            response_candidate_count = len(candidates)
            response["state_last_updated"] = response_last_updated
            response["last_updated"] = response_last_updated
            response["snapshot_generated_at"] = response_last_updated
            response["candidate_count"] = response_candidate_count
            if analysis:
                analysis["state_last_updated"] = response_last_updated
                analysis["last_updated"] = response_last_updated
                analysis["snapshot_generated_at"] = response_last_updated
                analysis["candidate_count"] = response_candidate_count
                response["response"] = analysis
            board_payload = dict(response)
            board_payload["board"] = _build_board_dictionary(ranked_candidates)
            response["board_contract"] = build_intelligence_board_contract(board_payload)
            response["live_pipeline"] = self._live_pipeline_summary(
                candidate_pool=candidate_pool,
                candidates=candidates,
                top_candidates=top_candidates,
                top_opportunities=top_opportunities,
                board_contract=response["board_contract"],
                selected_date=selected_date,
                sport=str(request_payload.get("sport") or "all").strip().lower() or "all",
            )
            response = _promote_board_contract_cards(response)
            _log_stage_timing("response_building", (time.perf_counter() - response_build_started_at) * 1000.0)
            response = _decorate_response_with_state_meta(dict(response), None, source="worker", run_key=cache_key, sla_seconds=self._interval_seconds) or dict(response)
            logger.info("BETTING_BOARD_REFRESH_CANDIDATE_COUNT", extra={"selected_date": selected_date, "candidate_count": response_candidate_count})
            persist_on_request_path = not _env_bool("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False)
            with self._condition:
                snapshot = IntelligenceSnapshot(
                    key=cache_key,
                    payload=dict(request_payload),
                    response=dict(response),
                    computed_at=_utc_now(),
                    source_fingerprint=source_fingerprint,
                )
                self._snapshots[snapshot.key] = snapshot
                self._snapshots.move_to_end(snapshot.key)
                self._latest_key = snapshot.key
                self._last_run_finished_at = time.time()
                self._trim_ordered_dict(self._snapshots, self._max_snapshots)
                if persist_on_request_path:
                    logger.info("before _persist_locked", extra={"candidate_count": response_candidate_count})
                    self._persist_locked()
                    logger.info("after _persist_locked", extra={"candidate_count": response_candidate_count})
                else:
                    logger.info("COMPUTE_RESPONSE PERSIST DEFERRED", extra={"candidate_count": response_candidate_count})
            _log_stage_timing("request_total", (time.perf_counter() - request_started_at) * 1000.0)
            logger.info("before return", extra={"candidate_count": response_candidate_count})
            logger.info("BETTING_BOARD_REFRESH_COMPLETE", extra={"selected_date": selected_date, "candidate_count": response_candidate_count, "snapshot_generated_at": response_last_updated})
            return response
        finally:
            if guard_acquired:
                self._execution_guard.release()

    def _is_stale(self, snapshot: IntelligenceSnapshot) -> bool:
        try:
            computed_at = time.strptime(snapshot.computed_at, "%Y-%m-%dT%H:%M:%SZ")
            # 2026-07-20: time.mktime() interprets its struct_time argument
            # as LOCAL time -- but computed_at is a "...Z"-suffixed UTC
            # timestamp (see _utc_now()), and every service here runs with
            # TZ=America/Chicago. That mismatch made computed_epoch land
            # ~5-6 hours ahead of the true value, so
            # time.time() - computed_epoch came out deeply negative and
            # never crossed _interval_seconds -- every snapshot silently
            # read as "fresh" for ~5-6 hours after it was actually computed,
            # regardless of the configured interval. Confirmed in
            # production: this is very likely why refresh-worker's own
            # stale-snapshot re-queue check never fired, and why an
            # earlier staleness fix on the read side (345dd3d3) didn't
            # actually resolve serving hours-old snapshots -- the
            # staleness check itself was broken. calendar.timegm()
            # interprets the struct_time as UTC, matching how it was built.
            computed_epoch = calendar.timegm(computed_at)
        except Exception:
            return True
        return (time.time() - computed_epoch) >= self._interval_seconds

    @staticmethod
    def _snapshot_age_seconds(snapshot: IntelligenceSnapshot | None) -> float | None:
        if snapshot is None:
            return None
        try:
            computed_at = time.strptime(snapshot.computed_at, "%Y-%m-%dT%H:%M:%SZ")
            computed_epoch = calendar.timegm(computed_at)
        except Exception:
            return None
        return round(max(0.0, time.time() - computed_epoch), 3)

    @staticmethod
    def _trim_ordered_dict(items: OrderedDict[str, Any], limit: int) -> None:
        while len(items) > limit:
            items.popitem(last=False)

    def _load_persisted_state_locked(self, *, force: bool = False) -> None:
        if self._loaded_from_disk and not force and _state_backend_kind() != "keyvalue":
            return
        if force or _state_backend_kind() == "keyvalue":
            self._snapshots.clear()
            self._latest_key = None
            self._watched_payloads.clear()
            self._pending_keys.clear()
            self._watched_board_dates.clear()
        payload = read_json_file(STATE_PATH)
        self._loaded_from_disk = True
        if not isinstance(payload, dict):
            return
        snapshots = payload.get("snapshots")
        if isinstance(snapshots, dict):
            for key, raw_snapshot in snapshots.items():
                if not isinstance(raw_snapshot, dict):
                    continue
                response = raw_snapshot.get("response")
                if not isinstance(response, dict):
                    continue
                snapshot = IntelligenceSnapshot(
                    key=str(key),
                    payload=dict(raw_snapshot.get("payload") or {}),
                    response=dict(response),
                    computed_at=str(raw_snapshot.get("computed_at") or _utc_now()),
                    source_fingerprint=str(raw_snapshot.get("source_fingerprint") or ""),
                )
                self._snapshots[snapshot.key] = snapshot
        watched_payloads = payload.get("watched_payloads")
        if isinstance(watched_payloads, dict):
            for key, raw_payload in watched_payloads.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._watched_payloads[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
        pending_keys = payload.get("pending_keys")
        if isinstance(pending_keys, dict):
            for key, raw_payload in pending_keys.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._pending_keys[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        watched_board_dates = payload.get("watched_board_dates")
        if isinstance(watched_board_dates, dict):
            for key, raw_date in watched_board_dates.items():
                self._watched_board_dates[str(key)] = str(raw_date)
            self._trim_ordered_dict(self._watched_board_dates, self._max_snapshots)
        self._latest_key = str(payload.get("latest_key") or "").strip() or (next(reversed(self._snapshots)) if self._snapshots else None)

    def _sync_persisted_queue_locked(self) -> None:
        payload = read_json_file(STATE_PATH)
        if not isinstance(payload, dict):
            return
        watched_payloads = payload.get("watched_payloads")
        if isinstance(watched_payloads, dict):
            self._watched_payloads.clear()
            for key, raw_payload in watched_payloads.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._watched_payloads[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._watched_payloads, self._max_snapshots)
        pending_keys = payload.get("pending_keys")
        if isinstance(pending_keys, dict):
            self._pending_keys.clear()
            for key, raw_payload in pending_keys.items():
                if not isinstance(raw_payload, dict):
                    continue
                self._pending_keys[str(key)] = dict(raw_payload)
            self._trim_ordered_dict(self._pending_keys, self._max_snapshots)
        watched_board_dates = payload.get("watched_board_dates")
        if isinstance(watched_board_dates, dict):
            self._watched_board_dates.clear()
            for key, raw_date in watched_board_dates.items():
                self._watched_board_dates[str(key)] = str(raw_date)
            self._trim_ordered_dict(self._watched_board_dates, self._max_snapshots)

    def _persist_locked(self) -> None:
        print(f"[intelligence_state] PERSIST_LOCKED_BEGIN latest_key={self._latest_key} snapshot_count={len(self._snapshots)}", flush=True)
        latest_snapshot = self._snapshots.get(self._latest_key or "") if self._latest_key else None
        latest_key_to_write = self._latest_key
        snapshots_payload = {
            key: {
                "key": snapshot.key,
                "payload": snapshot.payload,
                "response": snapshot.response,
                "computed_at": snapshot.computed_at,
                "source_fingerprint": snapshot.source_fingerprint,
            }
            for key, snapshot in self._snapshots.items()
        }
        if not self._snapshots:
            # This process's own in-memory view has no real computed
            # snapshots -- e.g. a freshly booted worker (a deploy, or
            # gunicorn respawning a crashed/timed-out worker) whose
            # boot-time _load_persisted_state_locked() call raced with, or
            # simply hasn't yet synced, a sibling process's (refresh-worker)
            # already-persisted state. STATE_PATH is a single shared
            # key/file across every process, so blindly writing an empty
            # "snapshots"/"latest_key" here -- which start() does
            # unconditionally on every boot to make its own boot-time queue
            # enqueue durable -- was confirmed in production to wipe a
            # perfectly good board the instant any worker restarted,
            # independent of whether refresh-worker itself was healthy.
            # Preserve whatever the shared store currently has instead of
            # regressing it to empty; the queue-related fields below still
            # get written from this process's own state either way.
            existing = read_json_file(STATE_PATH)
            existing_snapshots = existing.get("snapshots") if isinstance(existing, dict) else None
            if isinstance(existing_snapshots, dict) and existing_snapshots:
                snapshots_payload = existing_snapshots
                latest_key_to_write = existing.get("latest_key")
                existing_latest = snapshots_payload.get(latest_key_to_write) if latest_key_to_write else None
                if isinstance(existing_latest, dict) and isinstance(existing_latest.get("response"), dict):
                    latest_snapshot = IntelligenceSnapshot(
                        key=str(existing_latest.get("key") or latest_key_to_write),
                        payload=dict(existing_latest.get("payload") or {}),
                        response=dict(existing_latest.get("response") or {}),
                        computed_at=str(existing_latest.get("computed_at") or _utc_now()),
                        source_fingerprint=str(existing_latest.get("source_fingerprint") or ""),
                    )
        payload = {
            "latest_key": latest_key_to_write,
            "updated_at": _utc_now(),
            "watched_payloads": dict(self._watched_payloads),
            "pending_keys": dict(self._pending_keys),
            "watched_board_dates": dict(self._watched_board_dates),
            "snapshots": snapshots_payload,
        }
        write_json_file(STATE_PATH, payload)
        if latest_snapshot is not None:
            daily_paths = _intelligence_state_daily_paths()
            latest_response = dict(latest_snapshot.response or {}) if isinstance(latest_snapshot.response, dict) else {}
            board_snapshot_payload = _intelligence_board_snapshot_payload(
                latest_response,
                selected_date=str(latest_snapshot.payload.get("date") or latest_snapshot.payload.get("selected_date") or "").strip() or None,
            )
            write_json_file(
                BOARD_SNAPSHOT_PATH,
                {
                    "latest_key": latest_snapshot.key,
                    **board_snapshot_payload,
                },
            )
            write_json_file(
                daily_paths["board_snapshot"],
                {
                    "latest_key": latest_snapshot.key,
                    **board_snapshot_payload,
                },
            )


_INTELLIGENCE_STATE_SERVICE = IntelligenceStateService()


def start_intelligence_state_background_loop(app: Flask | None = None) -> bool:
    return _INTELLIGENCE_STATE_SERVICE.start(app)


def queue_intelligence_state_refresh(payload: dict[str, Any]) -> str:
    return _INTELLIGENCE_STATE_SERVICE.queue_refresh(payload)


def queue_board_state_refresh(selected_date: str | None = None) -> str:
    return _INTELLIGENCE_STATE_SERVICE.queue_board_state_refresh(selected_date)


def get_latest_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.read_latest_response(payload, force_refresh=force_refresh)


def get_intelligence_state_response(payload: dict[str, Any], *, refresh: bool = False, wait: bool = True, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE.get_response(payload, refresh=refresh, wait=wait, force_refresh=force_refresh)


def compute_intelligence_state_response(payload: dict[str, Any], *, force_refresh: bool = True) -> dict[str, Any] | None:
    return _INTELLIGENCE_STATE_SERVICE._compute_response(payload, force_refresh=force_refresh)


def read_latest_intelligence_state_response(
    payload: dict[str, Any] | None = None,
    *,
    force_refresh: bool = True,
    allow_latest_fallback: bool = False,
) -> dict[str, Any] | None:
    response = _INTELLIGENCE_STATE_SERVICE.read_latest_response(
        payload,
        force_refresh=force_refresh,
        allow_latest_fallback=allow_latest_fallback,
    )
    return _promote_board_contract_cards(response) if isinstance(response, dict) else response


def _decorate_intelligence_board_snapshot_response(
    snapshot: dict[str, Any],
    *,
    requested_date: str | None,
    source_label: str,
    strict_date: bool,
    requested_sport: str | None = None,
) -> dict[str, Any] | None:
    updated_at = str(snapshot.get("updated_at") or "").strip() or None
    response = snapshot.get("response")
    if isinstance(response, dict):
        if strict_date and requested_date and _selected_date_from_response(response) not in {None, requested_date}:
            return None
        # BOARD_SNAPSHOT_PATH/intelligence_state.json are single global files
        # that every watched-payload cycle overwrites, regardless of which
        # sport that particular cycle was scoped for -- so this fallback read
        # (used whenever the sport-aware in-memory snapshot happens to be
        # momentarily stale) could silently hand a sport=mlb request whatever
        # an unrelated sport=wnba (or otherwise-scoped) cycle last wrote here.
        # Confirmed live 2026-07-21: candidate_count stayed correct (from
        # by_sport) across writes, but the visible board_input/cards count
        # swung 181 -> 10 -> 0 across consecutive background-loop cycles,
        # each one a different watched payload clobbering the same file.
        if not _response_has_sport_data(response, requested_sport):
            return None
        decorated = _promote_board_contract_cards(dict(response))
        candidate_count = _intelligence_state_candidate_count(decorated)
        state_meta = dict(decorated.get("state_meta") or {})
        if not state_meta:
            freshness_sla_seconds = _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30)
            normalized_updated_at = _utc_timestamp_string(updated_at or decorated.get("state_last_updated") or decorated.get("last_updated") or decorated.get("updated_at"))
            state_meta = {
                "source": source_label,
                "computed_at": normalized_updated_at,
                "age_seconds": 0.0,
                "freshness_sla_seconds": freshness_sla_seconds,
                "freshness_status": "fresh",
                "is_fresh": True,
                "source_fingerprint": decorated.get("source_fingerprint"),
                "run_key": snapshot.get("latest_key"),
                "last_run_started_at": None,
                "last_run_finished_at": None,
            }
        decorated.setdefault("state_meta", state_meta)
        decorated.setdefault("freshness", dict(state_meta))
        decorated.setdefault("state_freshness", dict(state_meta))
        decorated["state_last_updated"] = _utc_timestamp_string(updated_at or decorated.get("state_last_updated") or decorated.get("last_updated") or decorated.get("updated_at"))
        decorated["candidate_count"] = candidate_count
        return decorated if candidate_count > 0 else None
    if all(key in snapshot for key in ("ok", "analysis", "top_opportunities")):
        if strict_date and requested_date and _selected_date_from_response(snapshot) not in {None, requested_date}:
            return None
        if not _response_has_sport_data(snapshot, requested_sport):
            return None
        decorated = _promote_board_contract_cards(dict(snapshot))
        updated_at = str(decorated.get("updated_at") or decorated.get("state_last_updated") or "").strip() or None
        freshness_sla_seconds = _env_int("SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS", 30)
        state_meta = decorated.get("state_meta") if isinstance(decorated.get("state_meta"), dict) else {}
        candidate_count = _intelligence_state_candidate_count(decorated)
        if not state_meta:
            state_meta = {
                "source": source_label,
                "computed_at": _utc_timestamp_string(updated_at),
                "age_seconds": 0.0,
                "freshness_sla_seconds": freshness_sla_seconds,
                "freshness_status": "fresh",
                "is_fresh": True,
                "source_fingerprint": decorated.get("source_fingerprint"),
                "run_key": snapshot.get("latest_key"),
                "last_run_started_at": None,
                "last_run_finished_at": None,
            }
        decorated.setdefault("state_meta", state_meta)
        decorated.setdefault("freshness", dict(state_meta))
        decorated.setdefault("state_freshness", dict(state_meta))
        decorated["state_last_updated"] = _utc_timestamp_string(updated_at)
        decorated["candidate_count"] = candidate_count
        return decorated if candidate_count > 0 else None
    return None


def _latest_non_empty_intelligence_board_snapshot_response(payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    requested_date = _selected_date_from_payload(payload)
    requested_sport = _requested_sport_from_payload(payload)
    candidate_paths: list[Path] = []
    seen_paths: set[str] = set()
    for path in [
        _intelligence_state_read_path("board_snapshot", BOARD_SNAPSHOT_PATH),
        *_intelligence_state_daily_candidates().get("board_snapshot", []),
        BOARD_SNAPSHOT_PATH,
    ]:
        if not isinstance(path, Path):
            continue
        normalized = str(path)
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        candidate_paths.append(path)

    for path in candidate_paths:
        snapshot = read_json_file(path)
        if not isinstance(snapshot, dict):
            continue
        decorated = _decorate_intelligence_board_snapshot_response(snapshot, requested_date=requested_date, source_label="board_snapshot_latest", strict_date=False, requested_sport=requested_sport)
        if isinstance(decorated, dict):
            return decorated
    return None


def read_latest_intelligence_board_snapshot_response(payload: dict[str, Any] | None = None, *, force_refresh: bool = True) -> dict[str, Any] | None:
    requested_date = _selected_date_from_payload(payload)
    requested_sport = _requested_sport_from_payload(payload)
    _ = force_refresh
    snapshot_path = _intelligence_state_read_path("board_snapshot", BOARD_SNAPSHOT_PATH)
    snapshot = read_json_file(snapshot_path)
    if isinstance(snapshot, dict):
        decorated = _decorate_intelligence_board_snapshot_response(snapshot, requested_date=requested_date, source_label="board_snapshot", strict_date=False, requested_sport=requested_sport)
        if isinstance(decorated, dict):
            if requested_date and _selected_date_from_response(decorated) not in {None, requested_date}:
                return None
            return decorated
    return _latest_non_empty_intelligence_board_snapshot_response(payload)


def intelligence_state_status(*, force_refresh: bool = True) -> dict[str, Any]:
    return _INTELLIGENCE_STATE_SERVICE.status(force_refresh=force_refresh)