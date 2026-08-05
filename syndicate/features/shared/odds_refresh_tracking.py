from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from syndicate.features.shared.basketball_props_tracking import sync_basketball_props_tracking_for_source_root
from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import shared_odds_history_root
from syndicate.features.shared.odds_framework import normalize_odds_entry
from syndicate.features.shared.odds_lifecycle import append_odds_lifecycle_events
from syndicate.features.shared.odds_lifecycle import odds_lifecycle_path
from syndicate.features.shared.refresh_state_store import _atomic_write_text
from syndicate.features.shared.timezone import central_date_from_iso
from syndicate.features.shared.recommendation_engine import build_recommendation_output
from syndicate.features.shared.week_calendar import shard_key_for_week
from syndicate.features.shared.week_calendar import week_for_date


def _odds_history_limit() -> int:
    # #112. Reduced default from 50: the row/normalized strip (see the
    # shard-wide sweep before each shard write) cut per-entry weight, but
    # MLB's real growth driver is BREADTH -- thousands of distinct prop
    # markets on a full slate -- and even lightweight entries at 50/market
    # across that many markets still exceeded the #60 8MB ceiling in
    # production (confirmed live 2026-07-28: KeyValuePayloadTooLarge
    # recurred on a cycle that ran after the sweep fix was already live).
    # 20 entries covers 5 hours at props' 15-min cold cadence and 30 min at
    # live/hot 90s cadence -- narrower than the steam detector's stated
    # 45-min window for hot markets, but a real, immediate size cut beats
    # an unbounded write failure that drops the data anyway. Env-tunable so
    # it can be adjusted without another deploy if this still isn't enough.
    raw = str(os.environ.get("SYNDICATE_ODDS_HISTORY_LIMIT") or "").strip()
    try:
        return max(1, int(raw)) if raw else 20
    except ValueError:
        return 20


_ODDS_HISTORY_LIMIT = _odds_history_limit()


def _odds_history_market_staleness_ceiling_seconds() -> int:
    # #112 follow-up (breadth, not depth). _ODDS_HISTORY_LIMIT/the shard-wide
    # sweep bound per-market history DEPTH -- but this file's own #112
    # comment already named the real growth driver as market COUNT (breadth):
    # thousands of distinct MLB prop markets on a full slate, each one
    # persisting forever once created, whether or not the game it belongs to
    # is still relevant. Confirmed live 2026-07-28: even with depth bounding
    # deployed and working, the MLB shard grew from 21.6MB (3,452 markets) to
    # 51.1MB (3,713 markets) over about two hours -- monotonic growth, never
    # reclaimed, because nothing ever removes a market once quoted, only
    # trims its history. That size made every write/publish attempt slower
    # and less reliable, which surfaced as MLB prop candidates specifically
    # (the largest share of the market count) failing #120's freshness SLA
    # gate: their odds_history-derived last_updated genuinely was stale,
    # because the growing shard was struggling to write reliably.
    #
    # A market untouched for this long is almost certainly for a game that
    # has already finished, or a price no longer being quoted -- evict it
    # outright rather than let it sit forever.
    #
    # 8h default, deliberately NOT 24h: a same-day ceiling has no effect at
    # all on the CURRENT day's already-oversized shard -- every market
    # created today is, by definition, under 24h old on the very next cycle,
    # so a 24h ceiling only ever prevents growth ACROSS days, never shrinks
    # today's. 8h safely covers any single game's real duration (including
    # extra innings or a doubleheader's first game) with real margin, while
    # actually being short enough to evict markets from games that started
    # early today and have since gone final -- which is exactly what's
    # needed to bring today's 51.1MB/3,713-market MLB shard back down
    # without waiting for the date to roll over.
    raw = str(os.environ.get("SYNDICATE_ODDS_HISTORY_MARKET_STALENESS_CEILING_SECONDS") or "").strip()
    try:
        return max(3600, int(raw)) if raw else 8 * 3600
    except ValueError:
        return 8 * 3600


def _trace_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _trace_file_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except Exception:
        return None


def _trace_log(stage: str, **payload: Any) -> None:
    record = {"stage": stage, **payload}
    print(f"[refresh_odds_tracking] TRACE {json.dumps(record, default=str, sort_keys=True)}", flush=True)


def _trace_path_payload(path: Path, *, rows: int | None = None) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": _trace_file_size(path),
        "rows": rows,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_csv(path: Path) -> pd.DataFrame:
    started = time.perf_counter()
    try:
        if not path.exists():
            _trace_log("after_read_csv", **_trace_path_payload(path, rows=0), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=True)
            return pd.DataFrame()
        frame = pd.read_csv(path)
        _trace_log("after_read_csv", **_trace_path_payload(path, rows=int(len(frame))), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=False)
        return frame
    except Exception:
        _trace_log("after_read_csv", **_trace_path_payload(path, rows=None), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=True)
        return pd.DataFrame()


def _read_json(path: Path) -> Any:
    started = time.perf_counter()
    try:
        if not path.exists():
            _trace_log("after_read_json", **_trace_path_payload(path), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=True)
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = None
        if isinstance(payload, list):
            rows = len(payload)
        elif isinstance(payload, dict):
            maybe_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else payload.get("games") if isinstance(payload.get("games"), list) else None
            if isinstance(maybe_rows, list):
                rows = len(maybe_rows)
        _trace_log("after_read_json", **_trace_path_payload(path, rows=rows), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=False)
        return payload
    except Exception:
        _trace_log("after_read_json", **_trace_path_payload(path), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=True)
        return None


def _write_json(path: Path, payload: Any) -> None:
    # Atomic (temp-file + os.replace) rather than a plain write_text -- this
    # writes the odds-history artifacts that feed the Betting Board's
    # line-movement/CLV display. Overlapping refresh_odds_sources.py runs
    # (see docs/fix_notes_log.md) can call this concurrently for the same
    # path; a non-atomic write there can leave a truncated/corrupted file,
    # which is the likely cause of the board's "Move" column going blank.
    started = time.perf_counter()
    payload_rows = len(payload) if isinstance(payload, list) else len(payload.get("rows", [])) if isinstance(payload, dict) else None
    _trace_log("before_write_json_payload", **_trace_path_payload(path, rows=payload_rows))
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True))
    _trace_log("after_write_json", **_trace_path_payload(path), elapsed_ms=round((time.perf_counter() - started) * 1000, 3))


def _odds_history_path(tracking_root: Path, shard_key: str) -> Path:
    return tracking_root / "odds_history" / f"{shard_key}.json"


def _odds_history_artifact_path(source_root: Path, sport: str, shard_key: str) -> Path:
    return source_root / "artifacts" / sport / "odds_history" / f"{shard_key}.json"


def _shared_odds_history_path(sport: str, shard_key: str) -> Path:
    return shared_odds_history_root() / str(sport or "").strip().lower() / f"{shard_key}.json"


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


def _is_final_status_row(row: Mapping[str, Any], normalized_entry: Mapping[str, Any] | None = None) -> bool:
    text_parts = [
        row.get("status"),
        row.get("state"),
        row.get("game_state"),
        row.get("period"),
        row.get("result"),
        row.get("outcome"),
        row.get("market_status"),
    ]
    if isinstance(normalized_entry, Mapping):
        text_parts.extend([normalized_entry.get("market_type"), normalized_entry.get("selection")])
    text = " ".join(str(value or "").strip().lower() for value in text_parts if str(value or "").strip())
    return any(marker in text for marker in ("final", "closed", "close", "finale", "completed", "finished"))


# #83 steam detector. The market is the best-aggregated news feed this system
# will ever have access to: by the time news is public, sharp money has moved
# the line, and this pipeline already observes every move. "Steam" = a
# significant move between two observations close together in time -- the
# after-image of information arriving. Detection is free (every input already
# exists where deltas are computed); the ACTUATOR is deliberately just a flag,
# a bounded per-date record and a print, because the cheap reaction (re-price
# without a full Monte Carlo) is #62 and does not exist yet, and a false
# trigger that forces a re-sim blocks the board via the mutual-deferral guard.
_STEAM_DEFAULT_LINE_MOVE = 0.5
_STEAM_DEFAULT_ODDS_MOVE = 15.0
_STEAM_DEFAULT_WINDOW_SECONDS = 45 * 60
# ramp/closing get a lower odds bar: late money is the most informed money.
_STEAM_LATE_PHASE_ODDS_MOVE = 10.0
_STEAM_EVENTS_KEEP = 200


def _implied_probability_from_american(value: Any) -> float | None:
    """American price -> implied probability (vig included, single side)."""
    try:
        odds = float(value)
    except (TypeError, ValueError):
        return None
    if odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return abs(odds) / (abs(odds) + 100.0)


def _steam_thresholds(capture_phase: str | None) -> tuple[float, float, float]:
    def _env_float(name: str, fallback: float) -> float:
        raw = str(os.environ.get(name) or "").strip()
        try:
            return float(raw) if raw else fallback
        except ValueError:
            return fallback

    line_move = _env_float("SYNDICATE_STEAM_LINE_MOVE", _STEAM_DEFAULT_LINE_MOVE)
    odds_move = _env_float("SYNDICATE_STEAM_ODDS_MOVE", _STEAM_DEFAULT_ODDS_MOVE)
    window_seconds = _env_float("SYNDICATE_STEAM_WINDOW_SECONDS", float(_STEAM_DEFAULT_WINDOW_SECONDS))
    if capture_phase in ("ramp", "closing"):
        odds_move = min(odds_move, _env_float("SYNDICATE_STEAM_LATE_ODDS_MOVE", _STEAM_LATE_PHASE_ODDS_MOVE))
    return line_move, odds_move, window_seconds


def _parse_utc_datetime(value: Any) -> datetime | None:
    """Parses an ISO timestamp, treating a naive result as UTC.

    Every timestamp this pipeline generates itself is aware (_utc_now() uses
    datetime.now(timezone.utc)), but raw odds-fetch snapshots stamp their own
    retrieved_at with a naive datetime.utcnow() -- the value IS UTC, it is
    only missing the offset. Rejecting it outright (the previous behavior:
    "if parsed.tzinfo is None: return None") silently disabled steam
    detection for every observation sourced from those snapshots -- confirmed
    2026-07-27: zero STEAM_DETECTED prints all day on either worker despite
    real production odds carrying >200pt swings and >1.0 line moves well past
    the steam thresholds. Treating naive as UTC (not discarding it) is what
    fixes that without needing every fetch script's timestamp writer fixed
    first.
    """
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _steam_signal(
    *,
    previous_line: float | None,
    current_line: float | None,
    previous_odds: float | None,
    current_odds: float | None,
    previous_ts: str | None,
    observed_ts: str,
    capture_phase: str | None,
) -> dict[str, Any] | None:
    """Steam metadata for this observation, or None.

    Requires BOTH a big-enough move and a small-enough gap between the two
    observations: the same 0.5-line change spread over four drift hours is
    ordinary drift, not steam. No previous observation, no timestamps, or an
    unparseable gap all fail open to None -- a detector this cheap must never
    invent a signal.
    """
    if previous_ts is None:
        return None
    prev = _parse_utc_datetime(previous_ts)
    curr = _parse_utc_datetime(observed_ts)
    if prev is None or curr is None:
        return None
    gap_seconds = (curr - prev).total_seconds()
    line_move, odds_move, window_seconds = _steam_thresholds(capture_phase)
    if gap_seconds <= 0 or gap_seconds > window_seconds:
        return None
    line_delta = None
    if previous_line is not None and current_line is not None:
        line_delta = current_line - previous_line
    odds_delta = None
    if previous_odds is not None and current_odds is not None:
        odds_delta = current_odds - previous_odds
    line_hit = line_delta is not None and abs(line_delta) >= line_move
    odds_hit = odds_delta is not None and abs(odds_delta) >= odds_move
    if not (line_hit or odds_hit):
        return None
    # Recorded, NOT yet used as a threshold. Raw American-odds deltas are not
    # comparable across sports or markets -- 30 points on a -110 NBA total and
    # 30 on a +450 soccer goalscorer are wildly different amounts of
    # information -- so a single fixed SYNDICATE_STEAM_ODDS_MOVE is
    # simultaneously too loose for liquid markets and too tight for thin
    # ones. Probability movement per minute is the comparable unit, and is
    # what a threshold SHOULD key on.
    #
    # Deliberately not switched over in this change: re-basing the trigger
    # blind would silently change what counts as steam across every sport at
    # once, with no measurement to say whether the new cut is better. Record
    # it first, grade it against closing lines (steam -> CLV hit rate per
    # sport/market), then move the threshold onto the graded number. This
    # field is the input that makes that possible.
    #
    # Single-sided, so it still carries the book's vig -- a true de-vig needs
    # both sides of the market, which this per-row detector never sees. Named
    # accordingly rather than claiming more than it is.
    prob_delta = None
    prob_delta_per_minute = None
    previous_prob = _implied_probability_from_american(previous_odds)
    current_prob = _implied_probability_from_american(current_odds)
    if previous_prob is not None and current_prob is not None:
        prob_delta = current_prob - previous_prob
        if gap_seconds > 0:
            prob_delta_per_minute = prob_delta * 60.0 / gap_seconds
    return {
        "line_delta": round(line_delta, 3) if line_delta is not None else None,
        "odds_delta": round(odds_delta, 1) if odds_delta is not None else None,
        "window_seconds": round(gap_seconds, 1),
        "capture_phase": capture_phase,
        "implied_prob_delta": round(prob_delta, 5) if prob_delta is not None else None,
        "implied_prob_delta_per_minute": round(prob_delta_per_minute, 5) if prob_delta_per_minute is not None else None,
    }


def _steam_events_path(date_str: str) -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "steam" / f"steam_events_{date_str}.json"


def steam_events_path_for_sport(sport: str, date_str: str) -> Path:
    """Per-sport steam record. Still matches HOT_ARTIFACT_PATTERNS'
    reports/steam/steam_events_*.json, so cross-service reach is unchanged.
    """
    from syndicate.features.shared.refresh_state_store import reports_root

    slug = str(sport or "").strip().lower() or "unknown"
    return reports_root() / "steam" / f"steam_events_{slug}_{date_str}.json"


def _annotate_steam_book_confirmation(events: list[dict[str, Any]]) -> None:
    """Stamp each steam event with how many books moved the SAME way.

    One book moving is that book's own position; a correlated move across
    several books is the thing "steam" is actually supposed to name. The
    detector is per-row (one market, one book, two consecutive
    observations), so it structurally cannot see this -- but by the time a
    refresh has finished, every book's row for that cycle is in hand, and
    grouping them is cheap.

    Recorded, not enforced: nothing filters on it yet, for the same reason
    the probability delta above isn't a threshold yet -- requiring N books
    without first measuring how single-book steam actually grades against
    closing lines would be swapping one guess for another. Consumers can
    rank on it immediately; a threshold should wait for the CLV numbers.
    """
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        steam = event.get("steam") if isinstance(event.get("steam"), dict) else None
        if not steam:
            continue
        key = (
            str(event.get("sport") or "").strip().lower(),
            str(event.get("game_id") or event.get("event_id") or "").strip(),
            str(event.get("market_type") or "").strip().lower(),
            str(event.get("selection") or event.get("player_name") or "").strip().lower(),
        )
        groups.setdefault(key, []).append(event)

    for grouped in groups.values():
        books_up: set[str] = set()
        books_down: set[str] = set()
        for event in grouped:
            steam = event.get("steam") or {}
            book = str(event.get("bookmaker") or event.get("book") or "").strip().lower()
            if not book:
                continue
            direction = steam.get("implied_prob_delta")
            if direction is None:
                direction = steam.get("odds_delta")
            if direction is None:
                direction = steam.get("line_delta")
            if direction is None:
                continue
            (books_up if direction > 0 else books_down).add(book)
        for event in grouped:
            steam = event.get("steam") or {}
            direction = steam.get("implied_prob_delta")
            if direction is None:
                direction = steam.get("odds_delta")
            if direction is None:
                direction = steam.get("line_delta")
            agreeing = books_up if (direction or 0) > 0 else books_down
            steam["books_confirming"] = len(agreeing)
            steam["books_opposing"] = len(books_down if (direction or 0) > 0 else books_up)


def _record_steam_events(date_str: str, events: list[dict[str, Any]]) -> None:
    """Bounded per-date, PER-SPORT steam record. Never raises.

    Was one shared file per date holding `merged[-_STEAM_EVENTS_KEEP:]` --
    a single newest-200 window across every sport, appended to by each
    sport's refresh in turn. Two consequences, both confirmed live
    2026-08-04:

    1. Starvation. MLB detects far more steam than anything else (3,400+
       tracked markets on a 15-game night, props included), so one MLB
       refresh evicted every other sport's events. The board showed 164
       steam candidates, ALL MLB -- WNBA and soccer had zero despite both
       carrying candidates. "Steam for all active sports" was structurally
       impossible, not merely unlucky.
    2. A lost-update race. Every sport's refresh read-modify-wrote the same
       key, so two concurrent refreshes silently dropped one's events.

    Writing per sport fixes both: the cap becomes per-sport by construction,
    and a sport only ever touches its own key. The consumer reads the sport
    it is building (see intelligence._load_steam_events_for_date), so no
    globbing is needed -- which matters because with the keyvalue backend
    these are store keys, not files, and cannot be globbed.
    """
    if not events:
        return
    try:
        from syndicate.features.shared.refresh_state_store import read_json_file as _read
        from syndicate.features.shared.refresh_state_store import write_json_file as _write

        by_sport: dict[str, list[dict[str, Any]]] = {}
        for event in events:
            if not isinstance(event, dict):
                continue
            slug = str(event.get("sport") or "").strip().lower() or "unknown"
            by_sport.setdefault(slug, []).append(event)

        for slug, sport_events in by_sport.items():
            path = steam_events_path_for_sport(slug, date_str)
            payload = _read(path)
            existing = payload.get("events") if isinstance(payload, dict) else None
            merged = (existing if isinstance(existing, list) else []) + sport_events
            _write(path, {"date": date_str, "sport": slug, "events": merged[-_STEAM_EVENTS_KEEP:]})
            # Steam is written by whichever service ran the refresh and read
            # by whichever service builds the board -- different Render
            # services, different disks. Confirmed live 2026-08-05: the board
            # carried 164 MLB steam candidates and nothing else, because
            # refresh-worker (which builds the board) runs MLB's refresh
            # itself via _launch_autorun_mlb_refresh, while WNBA/soccer/NBA
            # refresh on live-odds-worker -- so their steam was written to a
            # disk the board build never reads. Per-sport retention was
            # necessary but not sufficient: nothing was transporting these at
            # all. Neither the legacy nor the per-sport file was even present
            # on web, while the board still showed MLB steam.
            #
            # Cheap to publish, unlike the odds_history shards next to it:
            # capped at _STEAM_EVENTS_KEEP events per sport per day, so this
            # is kilobytes. The path is already in HOT_ARTIFACT_PATTERNS, and
            # the filename carries the date, so refresh-worker's own
            # date-scoped pull_hot_artifacts picks it back up.
            try:
                from syndicate.features.shared.artifact_publisher import publish_hot_artifact

                published = publish_hot_artifact(path)
            except Exception as publish_exc:
                published = False
                print(f"STEAM_PUBLISH_FAILED sport={slug} error={type(publish_exc).__name__}: {publish_exc}", flush=True)
            print(
                f"STEAM_DETECTED sport={slug} date={date_str} new={len(sport_events)} "
                f"total_kept={min(len(merged), _STEAM_EVENTS_KEEP)} published={published}",
                flush=True,
            )
    except Exception as exc:
        print(f"STEAM_RECORD_FAILED error={type(exc).__name__}: {exc}", flush=True)



# #82 Phase 3. Boundaries of the pregame capture phases, chosen with the
# T-window sweep scheduler in live_refresh_loop.py: the ramp window opens just
# beyond the T-75m post-lineup sweep and the closing window just beyond the
# T-10m closing sweep, so the observations those sweeps produce land inside
# the phase they exist to capture.
_RAMP_WINDOW_SECONDS = 80 * 60
_CLOSING_WINDOW_SECONDS = 12 * 60


def _capture_phase(*, commence_time: Any, observed_at: str, is_live: bool) -> str | None:
    """Which pregame phase this observation belongs to, or None if unknowable.

    #82: makes opening/closing lines LOOKUPS instead of timestamp inference.
    CLV's closing line is "the last observation tagged closing (or ramp/drift
    if no sweep landed closer)"; the movement curve is the drift series;
    event_type="open" already marks the opener. Fail-open to None -- an
    observation with no commence time is still a real observation, and the
    dict comprehension below drops None values rather than inventing a phase.
    """
    if is_live:
        return "live"
    try:
        start = datetime.fromisoformat(str(commence_time or "").replace("Z", "+00:00"))
        observed = datetime.fromisoformat(str(observed_at or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None or observed.tzinfo is None:
        return None
    seconds_to_start = (start - observed).total_seconds()
    if seconds_to_start <= 0:
        return "live"
    if seconds_to_start <= _CLOSING_WINDOW_SECONDS:
        return "closing"
    if seconds_to_start <= _RAMP_WINDOW_SECONDS:
        return "ramp"
    return "drift"


def _market_lifecycle_event(
    *,
    row: Mapping[str, Any],
    normalized_entry: Mapping[str, Any],
    event_type: str,
    sport: str,
    timestamp: str,
    market_key: str,
    current_line: float | None,
    current_odds: float | None,
    is_live: bool,
) -> dict[str, Any]:
    event = {
        "capture_phase": _capture_phase(
            commence_time=row.get("commence_time") or normalized_entry.get("commence_time") or row.get("gameDate") or row.get("game_time"),
            observed_at=timestamp,
            is_live=is_live,
        ),
        "timestamp": timestamp,
        "game_id": normalized_entry.get("event_id") or row.get("event_id") or row.get("game_id") or row.get("game_pk"),
        "sport": sport,
        "market_id": normalized_entry.get("market_id") or market_key,
        "player_id": row.get("player_id") or row.get("athlete_id"),
        # #83 steam rail: props (_flatten_mlb_props' output rows) carry a
        # real display-cased player_name and an explicit over/under
        # selection, neither of which player_id/market_type above capture --
        # player_id is always empty for props (OddsAPI has no MLBAM id),
        # and selection was only ever read as a last-resort market_type
        # fallback. Additive: nothing downstream reads these yet except the
        # new steam rail, so no existing consumer is affected.
        "player_name": row.get("player_name") or normalized_entry.get("entity") or row.get("entity") or row.get("player") or None,
        "selection": row.get("selection") or normalized_entry.get("selection") or None,
        "market_type": normalized_entry.get("market_type") or row.get("market_type") or row.get("market") or row.get("selection"),
        # #137 follow-up: soccer's raw fetch rows (scripts/fetch_soccer_
        # oddsapi_{odds,props}_local.py) already carry these two columns --
        # confirmed live: the board's steam-move candidates for soccer
        # showed a real, consistent OddsAPI event_id but no way to tell
        # which match it was (that id is an OddsAPI hash, unrelated to the
        # sim's own ESPN-numeric event_id used elsewhere on the board, so a
        # dashboard-games lookup by id can never match it). Stamping these
        # here means every NEW steam event carries a real matchup with no
        # separate resolver needed; harmless no-op for sports whose rows
        # don't have these columns.
        "home_team": row.get("home_team") or normalized_entry.get("home_team"),
        "away_team": row.get("away_team") or normalized_entry.get("away_team"),
        "event_type": event_type,
        "line": current_line,
        "price": current_odds,
        "implied_prob": normalized_entry.get("market_probability") or normalized_entry.get("implied_probability"),
        "source": normalized_entry.get("source_path") or row.get("source_path") or row.get("book") or row.get("bookmaker"),
        "is_live": bool(is_live),
    }
    if event_type == "final":
        event["result"] = row.get("result") or row.get("outcome") or row.get("market_status") or "final"
        event["closing_line"] = current_line
        event["closing_price"] = current_odds
    return {key: value for key, value in event.items() if value is not None}


def _is_live_odds_row(row: Mapping[str, Any], normalized_entry: Mapping[str, Any] | None = None) -> bool:
    text_parts = [
        row.get("market_type"),
        row.get("market"),
        row.get("selection"),
        row.get("period"),
        row.get("status"),
        row.get("state"),
        row.get("game_state"),
        row.get("live"),
        row.get("is_live"),
    ]
    if isinstance(normalized_entry, Mapping):
        text_parts.extend([
            normalized_entry.get("market_type"),
            normalized_entry.get("selection"),
        ])
    text = " ".join(str(value or "").strip().lower() for value in text_parts if str(value or "").strip())
    return any(marker in text for marker in ("live", "in_play", "in play", "in-progress", "in progress"))


def _row_commence_time_has_passed(row: Mapping[str, Any], *, now_iso: str) -> bool:
    """True once a row's own scheduled start time is at or before `now_iso`.

    Fallback signal for _is_live_odds_row -- see its caller's comment for
    why MLB's standard game-line feed needs this at all (no live/in-play
    text of any kind on that row shape, live game or not).
    """
    commence_raw = row.get("commence_time") or row.get("commenceTime") or row.get("start_time") or row.get("startTime")
    if not commence_raw:
        return False
    try:
        commence_dt = datetime.fromisoformat(str(commence_raw).replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if commence_dt.tzinfo is None:
        commence_dt = commence_dt.replace(tzinfo=timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return now_dt >= commence_dt


def _row_elapsed_game_time_indicates_live(row: Mapping[str, Any]) -> bool:
    """True when a row carries a real, nonzero in-game elapsed-time signal.

    Confirmed live 2026-07-31: NBA/WNBA's player-prop and live-lens feeds
    (live_lens_signals_*.jsonl etc.) carry no commence_time at all -- unlike
    game_cards.csv's game-level rows -- so _row_commence_time_has_passed
    can't help them. Those rows DO carry "elapsed"/"remaining" (minutes
    played / minutes left in the game), e.g. {"elapsed": 0, "remaining": 40}
    for a still-pregame WNBA row observed directly against production data.
    elapsed > 0 is a reasonable proxy for "the game has actually tipped
    off" -- same role commence_time plays for game markets, just sourced
    from the game clock instead of the schedule.
    """
    elapsed = _line_number(row.get("elapsed"))
    return elapsed is not None and elapsed > 0


def _line_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    # A pandas column that's blank for every row of a CSV (e.g. soccer's
    # h2h rows never populate "line", only "price") reads back as NaN, not
    # None/"" -- without this check NaN silently passed the guard above and
    # got treated as a real captured line value.
    return None if number != number else number


def _movement_direction(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "flat"
    return "up" if delta > 0 else "down"


def _percent_change(current_line: float | None, previous_line: float | None) -> float | None:
    if current_line is None or previous_line in (None, 0):
        return None
    try:
        return ((current_line - previous_line) / abs(previous_line)) * 100.0
    except Exception:
        return None


def _primary_line_value(row: Mapping[str, Any]) -> float | None:
    for key in (
        "line",
        "point",
        "spread",
        "total",
        "price",
        "odds",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_line",
        "away_line",
        "home_puck_line",
        "away_puck_line",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        current_value = _line_number(row.get(key))
        if current_value is not None:
            return current_value
    return None


def _primary_odds_value(row: Mapping[str, Any]) -> float | None:
    for key in (
        "odds",
        "price",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_spread_price",
        "away_spread_price",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        current_value = _line_number(row.get(key))
        if current_value is not None:
            return current_value
    return None


def _odds_history_market_states(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping):
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


def _canonical_market_type(row: Mapping[str, Any]) -> str | None:
    for key in ("market_type", "market", "selection", "period"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def _canonical_entity(row: Mapping[str, Any]) -> str | None:
    for key in (
        "entity",
        "player_name",
        "player",
        "team",
        "team_key",
        "subject_key",
        "selection",
        "matchup",
        "home_team",
        "away_team",
        "name",
        "title",
        "label",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return None


def _canonical_event_id(row: Mapping[str, Any]) -> str | None:
    for key in ("event_id", "event_key", "game_id", "game_pk"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    matchup = str(row.get("matchup") or "").strip()
    if matchup:
        return matchup
    home_team = str(row.get("home_team") or "").strip()
    away_team = str(row.get("away_team") or "").strip()
    if home_team and away_team:
        return f"{away_team}@{home_team}"
    return None


def _canonical_odds_record(*, row: Mapping[str, Any], market_key: str, sport: str, timestamp: str, current_line: float | None) -> dict[str, Any]:
    event_id = _canonical_event_id(row)
    market_type = _canonical_market_type(row)
    entity = _canonical_entity(row)
    market_id = str(row.get("market_id") or "").strip() or market_key
    odds_value = _primary_odds_value(row)
    return {
        "market_id": market_id,
        "sport": sport,
        "event_id": event_id,
        "market_type": market_type,
        "entity": entity,
        "line": current_line,
        "odds": odds_value,
        "timestamp": timestamp,
    }


def _odds_history_line_snapshot(row: Mapping[str, Any]) -> dict[str, Any] | None:
    snapshot: dict[str, Any] = {}
    for key in (
        "line",
        "point",
        "spread",
        "total",
        "price",
        "odds",
        "home_odds",
        "away_odds",
        "over_odds",
        "under_odds",
        "home_ml",
        "away_ml",
        "home_line",
        "away_line",
        "home_puck_line",
        "away_puck_line",
        "home_puck_odds",
        "away_puck_odds",
        "over_price",
        "under_price",
    ):
        value = row.get(key)
        if value in (None, "", "-"):
            continue
        snapshot[key] = _json_safe(value)
    return snapshot or None


def _odds_history_market_key(row: Mapping[str, Any]) -> str | None:
    # Soccer's raw props feed (scripts/fetch_soccer_oddsapi_props_local.py)
    # already writes a fully-formed disambiguated key under "market_key"
    # (player+market+line) -- distinct column name from every other
    # sport's "market_id", so it needs its own fallback here.
    market_id = str(row.get("market_id") or row.get("market_key") or "").strip()
    if market_id:
        return market_id
    parts: list[str] = []
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "home_team",
        "away_team",
        # WNBA/NBA's live_lens_projections_*.jsonl rows (log_pregame_prop_signals.py,
        # the vendored live-lens pregame signal logger) use "home"/"away" for
        # team names, not "home_team"/"away_team" -- confirmed live 2026-07-29:
        # without these, every player prop for the same game collapsed onto
        # the same history entry (every distinguishing field below silently
        # missed too), showing several different players' line movement as
        # one shared, wrong movement badge on the board.
        "home",
        "away",
        "player_key",
        "player_name",
        # Same schema mismatch as home/away above -- these rows carry the
        # player under "player" or "entity", never "player_name".
        "player",
        "entity",
        "team_key",
        "team",
        # "team_tri" (e.g. "PHX") is this schema's own team-code field --
        # "team"/"team_key" above never match it.
        "team_tri",
        "market",
        # The generic "market" value on these rows is just the category
        # ("player_prop"), not the specific stat -- "stat" (e.g. "pra"/"pts")
        # is what actually distinguishes one player's several simultaneous
        # props from each other. Without it, a player's points prop and
        # rebounds prop would still collide even after the player-name fix
        # above.
        "stat",
        "selection",
        # Soccer's raw game-odds CSV (scripts/fetch_soccer_oddsapi_odds_local.py)
        # names its selection column "side" (home/draw/away, over/under)
        # rather than "selection" -- without this, every side of the same
        # market would collapse into one history entry.
        "side",
        "book",
        "bookmaker",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    if not parts:
        fallback = str(row.get("name") or row.get("title") or row.get("label") or "").strip()
        if fallback:
            parts.append(f"name={fallback}")
    return "|".join(parts) if parts else None


def _market_rows_from_mapping(payload: Mapping[str, Any], *, context: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    merged_context = dict(context or {})
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "home_team",
        "away_team",
        "player_key",
        "player_name",
        "team_key",
        "team",
        "market",
        "selection",
        "book",
        "bookmaker",
        "date",
        "sport",
        "commence_time",
    ):
        value = payload.get(key)
        if value in (None, ""):
            continue
        merged_context.setdefault(key, value)

    rows: list[dict[str, Any]] = []
    if _odds_history_line_snapshot(payload):
        rows.append({**merged_context, **dict(payload)})

    for key in ("games", "rows", "items"):
        nested = payload.get(key)
        if isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item, context=merged_context))

    for key in ("lines", "markets", "props", "player_props", "team_odds", "hitter_props", "pitcher_props"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            for nested_key, nested_value in nested.items():
                nested_context = dict(merged_context)
                if nested_key and not nested_context.get("market"):
                    nested_context["market"] = str(nested_key)
                if isinstance(nested_value, Mapping):
                    rows.extend(_market_rows_from_mapping(nested_value, context=nested_context))
                elif isinstance(nested_value, list):
                    for item in nested_value:
                        if isinstance(item, Mapping):
                            rows.extend(_market_rows_from_mapping(item, context=nested_context))
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item, context=merged_context))

    return rows


def _odds_history_rows_from_json(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        rows: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, Mapping):
                rows.extend(_market_rows_from_mapping(item))
        return rows
    if isinstance(payload, Mapping):
        return _market_rows_from_mapping(payload)
    return []


def _odds_history_rows_from_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return rows
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, Mapping):
            rows.extend(_market_rows_from_mapping(payload))
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, Mapping):
                    rows.extend(_market_rows_from_mapping(item))
    return rows


def _odds_history_rows_from_csv(path: Path) -> list[dict[str, Any]]:
    try:
        frame = pd.read_csv(path)
    except Exception:
        return []
    if frame.empty:
        return []
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    snapshot_ts = _to_snapshot_ts(frame, fallback_ts=fallback_ts)
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(frame.to_dict(orient="records")):
        if isinstance(row, Mapping):
            item = dict(row)
            item.setdefault("snapshot_ts", str(snapshot_ts.iloc[index]) if index < len(snapshot_ts) else fallback_ts)
            rows.append(item)
    return rows


def _odds_history_candidate_snapshot_ts(path: Path) -> str:
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                timestamp = str(payload.get("retrieved_at") or payload.get("retrievedAt") or payload.get("fetched_at") or payload.get("snapshot_ts") or "").strip()
                if timestamp:
                    return timestamp
        elif path.suffix.lower() == ".jsonl":
            lines = path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except Exception:
                    continue
                if isinstance(payload, Mapping):
                    timestamp = str(payload.get("retrieved_at") or payload.get("retrievedAt") or payload.get("fetched_at") or payload.get("snapshot_ts") or "").strip()
                    if timestamp:
                        return timestamp
    except Exception:
        pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def _odds_history_snapshot_paths(*, sport: str, source_root: Path, date_str: str) -> list[Path]:
    slug = str(sport or "").strip().lower()
    date_slug = str(date_str or "").strip().replace("-", "_")
    candidates: list[Path] = []

    def add(*parts: str) -> None:
        candidate = source_root.joinpath(*parts)
        if candidate not in candidates:
            candidates.append(candidate)

    if slug == "mlb":
        for snapshot_dir in (
            source_root / "source_artifacts" / "data" / "daily" / "snapshots" / date_str,
            source_root / "data" / "daily" / "snapshots" / date_str,
        ):
            rel_parts = snapshot_dir.relative_to(source_root).parts
            add(*rel_parts, f"oddsapi_game_lines_{date_slug}.json")
            add(*rel_parts, f"oddsapi_hitter_props_{date_slug}.json")
            add(*rel_parts, f"oddsapi_pitcher_props_{date_slug}.json")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug in {"nba", "wnba"}:
        for prefix_root in (
            source_root / "data" / "processed",
            source_root / "source_artifacts" / "data" / "processed",
        ):
            rel_parts = prefix_root.relative_to(source_root).parts
            add(*rel_parts, "live_snapshots", f"live_lines_{date_str}.jsonl")
            add(*rel_parts, f"live_lens_signals_{date_str}.jsonl")
            add(*rel_parts, f"live_lens_projections_{date_str}.jsonl")
            # game_cards_{date}.csv (confirmed live 2026-07-31: home_team/
            # visitor_team/commence_time/home_ml/away_ml/home_spread/
            # away_spread/total/bookmaker/home_tri/away_tri) is the ONLY one
            # of these four sources that carries real game-level lines with
            # commence_time and full team names -- the other three (checked
            # against real production files the same session) either
            # produce zero rows through the generic per-row parser (nested
            # scalar "lines" dict, or a "live_line" key the parser doesn't
            # recognize) or are player-prop-only. Routed through
            # _flatten_basketball_game_cards below, not the generic CSV
            # reader, since one CSV row here holds 3 markets as columns.
            add(*rel_parts, f"game_cards_{date_str}.csv")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "nhl":
        for base_parts in (
            ("data", "odds", "games", f"date={date_str}", "scoreboard.csv"),
            ("data", "odds", "team", f"date={date_str}", "oddsapi.csv"),
            ("data", "props", "player_props_lines", f"date={date_str}", "oddsapi.csv"),
        ):
            add(*base_parts)
            add("source_artifacts", *base_parts)
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "nfl":
        season, week = _infer_nfl_week_scope(source_root)
        add(f"real_betting_lines_{date_str.replace('-', '_')}.json")
        add("source_artifacts", f"real_betting_lines_{date_str.replace('-', '_')}.json")
        add(f"oddsapi_player_props_{season}_wk{week}.csv")
        add("source_artifacts", f"oddsapi_player_props_{season}_wk{week}.csv")
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "ncaab":
        for base_parts in (
            ("raw_outputs", "by_date", date_str, f"odds_{date_str}.csv"),
            ("source_artifacts", "raw_outputs", "by_date", date_str, f"odds_{date_str}.csv"),
            ("api", "live_lines", f"live_lines_{date_str}.json"),
            ("data", "api", "live_lines", f"live_lines_{date_str}.json"),
            ("source_artifacts", "api", "live_lines", f"live_lines_{date_str}.json"),
        ):
            add(*base_parts)
        return [path for path in candidates if path.exists() and path.is_file()]

    if slug == "ncaaf":
        artifact_root = source_root / "source_artifacts"
        if artifact_root.exists():
            for candidate in sorted(artifact_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv")):
                if candidate.is_file():
                    candidates.append(candidate)
        return candidates

    if slug == "soccer":
        # source_root is the multi-league bundle root (data/soccer_source);
        # every league writes to its own subdirectory, so glob across
        # whatever leagues are present rather than hardcoding a league list
        # in this shared module.
        if source_root.exists():
            for league_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
                add(league_dir.name, "api", "odds", "game_odds_current.csv")
                add(league_dir.name, "props", f"{date_str}.csv")
        return [path for path in candidates if path.exists() and path.is_file()]

    return []


def _mlb_props_root_key_for_path(path: Path) -> str | None:
    name = path.name
    if name.startswith("oddsapi_hitter_props_"):
        return "hitter_props"
    if name.startswith("oddsapi_pitcher_props_"):
        return "pitcher_props"
    return None


def _is_basketball_game_cards_path(path: Path) -> bool:
    return path.name.startswith("game_cards_") and path.suffix.lower() == ".csv"


def _parse_game_date_token(value: Any) -> date | None:
    """Which BETTING day (Central) a game-time token falls on.

    Was `.date()` on the parsed timestamp, i.e. the UTC calendar day. A 7:40pm
    Central first pitch is 00:40 UTC the NEXT day, so every West Coast and
    late-evening game sharded to date+1 while the board asks for
    central_today_iso(). Confirmed live 2026-08-04: the 2026-08-04 MLB shard
    held 9 of 15 games -- all of them East/Central afternoon or early-evening
    starts -- while LAD@CHC, SF@TEX, TB@COL and TOR@HOU sat in the 2026-08-05
    shard where nothing looks for them, and SD@AZ/DET@SEA (the latest starts)
    had not been captured at all. That is the same "18 of 30 teams" coverage
    gap logged earlier as an unexplained book-coverage mystery: it is not a
    book gap, it is a timezone gap, and the covered 18 were exactly the teams
    whose games start before 00:00 UTC.

    central_date_from_iso is the existing helper for precisely this, and its
    own docstring already documents the identical bug found 2026-07-21 in
    WNBA game-card filtering. A date-only token ("2026-08-05") is naive, gets
    read as Central midnight, and so still resolves to itself.
    """
    text = str(value or "").strip()
    if not text:
        return None
    parsed = central_date_from_iso(text)
    if parsed is not None:
        return parsed
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


def _row_game_date(row: Mapping[str, Any], *, sport: str) -> date | None:
    slug = str(sport or "").strip().lower()
    if slug == "mlb":
        return _parse_game_date_token(row.get("commence_time"))
    if slug in {"nba", "wnba"}:
        # Only game_cards_*.csv rows (_flatten_basketball_game_cards) carry
        # commence_time -- prop/live-lens rows have none, so this falls
        # through to date_str for them (_shard_key_for_row's existing
        # behavior), same as any other sport with no game-date signal.
        return _parse_game_date_token(row.get("commence_time"))
    if slug == "nhl":
        return _parse_game_date_token(row.get("commence_time") or row.get("gameDate"))
    if slug == "ncaab":
        return _parse_game_date_token(row.get("commence_time"))
    if slug == "nfl":
        return _parse_game_date_token(row.get("game_time"))
    if slug == "ncaaf":
        return _parse_game_date_token(row.get("start_date") or row.get("start_date_api"))
    if slug == "soccer":
        return _parse_game_date_token(row.get("commence_time") or row.get("game_time"))
    return None


def _row_week_scope(row: Mapping[str, Any], *, sport: str, date_str: str, source_root: Path) -> str:
    slug = str(sport or "").strip().lower()
    if slug == "ncaaf":
        try:
            season = int(row.get("season") or 0)
            week = int(row.get("week") or 0)
        except Exception:
            season = week = 0
        if season and week:
            return shard_key_for_week(season, week)
    game_date = _row_game_date(row, sport=slug)
    if game_date is not None:
        resolved = week_for_date(slug, game_date, source_root=source_root)
        if resolved is not None:
            return shard_key_for_week(*resolved)
    if slug == "nfl":
        scope, _ = _infer_nfl_week_scope(source_root)
        if scope and scope != "unknown":
            return scope
    # No reliable season/week signal at all (e.g. an NCAAF format without
    # season/week columns) -- degrade to a date-keyed bucket rather than
    # losing the row.
    return f"unscoped_{date_str}"


def _shard_key_for_row(row: Mapping[str, Any], *, sport: str, date_str: str, source_root: Path) -> str:
    slug = str(sport or "").strip().lower()
    if slug in {"nfl", "ncaaf"}:
        return _row_week_scope(row, sport=slug, date_str=date_str, source_root=source_root)
    game_date = _row_game_date(row, sport=slug)
    if game_date is not None:
        return game_date.isoformat()
    return date_str


def _write_odds_history_artifact(path: Path, payload: dict[str, Any]) -> None:
    """odds_history shards are routinely tens of MB on a real slate
    (measured live 2026-07-28: 51.1MB / 3,713 markets for one MLB day) --
    not an occasional edge case exceeding the keyvalue store's 8MB
    ceiling, the ordinary case always exceeding it. Per explicit user
    direction the same day ("the file size limit is frankly unrealistic
    from keyvalue - we need this to be artifact written/artifact read
    based"): this writes straight to local disk and publishes for
    cross-service reach, with no keyvalue attempt at all -- unlike
    pipeline/intelligence_state.py's _write_state_payload (#43/#108),
    which tries keyvalue first because ITS payloads (board_snapshot/
    intelligence_state) are usually small enough to fit and only
    occasionally overflow. odds_history never fits, so trying first is
    pure overhead with no chance of succeeding.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(payload, separators=(",", ":")))
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(path)
        _trace_log("odds_history_artifact_published", path=str(path), published=published)
    except Exception as exc:
        _trace_log("odds_history_artifact_publish_failed", path=str(path), error=f"{type(exc).__name__}: {exc}")


def _read_odds_history_candidate(path: Path) -> dict[str, Any] | None:
    """Pure local-disk read, no keyvalue involved -- the read-side match
    to _write_odds_history_artifact's artifact-only write. Whichever
    service ran the sync loop writes here directly; publish_hot_artifact
    is what gets a worker's write onto web's own local disk for THIS read
    to then pick up, not a keyvalue round-trip.
    """
    try:
        if not path.is_file():
            return None
        candidate = json.loads(path.read_text(encoding="utf-8-sig"))
        return candidate if isinstance(candidate, dict) else None
    except Exception:
        return None


def _load_shard_existing_markets(*, source_root: Path, tracking_root: Path, slug: str, shard_key: str) -> dict[str, dict[str, Any]]:
    # Read through the same keyvalue-aware helper the write side below
    # (and the board's own odds_control_plane.load_odds_history_payload_for_sport)
    # uses -- reading candidate_path.read_text() directly only ever sees
    # this process's own local disk, which is exactly the gap that left
    # the Betting Board's "Move" column blank in production: every write
    # here went straight to local disk (_atomic_write_text) while the
    # board reads through Redis when SYNDICATE_REFRESH_STATE_BACKEND=keyvalue
    # is active, so the board never saw any of this history no matter how
    # many times a refresh run wrote it.
    shared_path = _shared_odds_history_path(slug, shard_key)
    artifact_path = _odds_history_artifact_path(source_root, slug, shard_key)
    tracking_path = _odds_history_path(tracking_root, shard_key)
    existing: dict[str, Any] = {}
    for candidate_path in (shared_path, artifact_path, tracking_path):
        _trace_log("before_odds_history_existing_read", sport=slug, shard_key=shard_key, **_trace_path_payload(candidate_path))
        try:
            read_started = time.perf_counter()
            payload = _read_odds_history_candidate(candidate_path)
            if isinstance(payload, dict):
                existing = payload
                _trace_log("after_odds_history_existing_read", sport=slug, shard_key=shard_key, **_trace_path_payload(candidate_path, rows=int(len(payload) if hasattr(payload, "__len__") else 0)), elapsed_ms=round((time.perf_counter() - read_started) * 1000, 3), hit=True)
                break
        except Exception:
            _trace_log("after_odds_history_existing_read", sport=slug, shard_key=shard_key, **_trace_path_payload(candidate_path), error=True)
            continue
    return _odds_history_market_states(existing)


def _row_h2h_matchup_label(row: Mapping[str, Any]) -> str | None:
    # Diagnostic-only (2026-08-04): "away@home" label for a moneyline/h2h
    # row, used to compare which games survive each stage of the sync
    # pipeline. Reads the exact context fields _market_rows_from_mapping
    # already propagates onto every row (home_team/away_team), so this
    # never changes what the real pipeline sees -- it only labels it.
    market = str(row.get("market") or row.get("market_type") or "").strip().lower()
    if market not in {"h2h", "moneyline", "ml"}:
        return None
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    if not home or not away:
        return None
    return f"{away}@{home}"


def _sync_odds_history_for_refresh(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    tracking_root = source_root / "tracking"
    candidates = _odds_history_snapshot_paths(sport=slug, source_root=source_root, date_str=date_str)
    # #150 diagnostic (2026-08-04): only 18/30 MLB teams got h2h odds-history
    # captured on a 15-game day, and the captured stdout of the run that
    # would explain it is too large for the ops log-read endpoint's 64KB
    # tail to reach (todo.md "MLB odds-history: 18/30-team coverage gap").
    # These three sets pin exactly which stage of the pipeline a matchup
    # falls out at -- source extraction, the market_key/line gate, or the
    # shard write -- instead of guessing from a truncated log again.
    h2h_matchups_in_source: set[str] = set()
    h2h_matchups_passed_gate: set[str] = set()
    h2h_matchups_written: set[str] = set()
    _trace_log("before_sync_odds_history", sport=slug, date=date_str, candidates=[str(path) for path in candidates], candidate_count=len(candidates))
    if not candidates:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_odds_snapshots",
            "sport": slug,
            "date": date_str,
            "files_scanned": 0,
            "entries_appended": 0,
            "shards": {},
        }

    now = _utc_now()
    entries_appended = 0
    count_live = 0
    count_pregame = 0
    files_scanned = 0
    seen_current_snapshots: set[tuple[str, float, float | None]] = set()
    lifecycle_events: list[dict[str, Any]] = []
    steam_events: list[dict[str, Any]] = []
    shards: dict[str, dict[str, dict[str, Any]]] = {}
    shard_seen_market_keys: dict[str, set[str]] = {}
    shard_seen_live_market_keys: dict[str, set[str]] = {}
    shard_entries_appended: dict[str, int] = {}

    def _shard_markets(shard_key: str) -> dict[str, dict[str, Any]]:
        if shard_key not in shards:
            shards[shard_key] = _load_shard_existing_markets(source_root=source_root, tracking_root=tracking_root, slug=slug, shard_key=shard_key)
            shard_seen_market_keys[shard_key] = set()
            shard_seen_live_market_keys[shard_key] = set()
            shard_entries_appended[shard_key] = 0
        return shards[shard_key]

    for candidate in candidates:
        files_scanned += 1
        suffix = candidate.suffix.lower()
        candidate_snapshot_ts = _odds_history_candidate_snapshot_ts(candidate)
        _trace_log("before_odds_history_candidate_read", sport=slug, path=str(candidate), suffix=suffix, size_bytes=_trace_file_size(candidate))
        candidate_read_started = time.perf_counter()
        mlb_props_root_key = _mlb_props_root_key_for_path(candidate) if slug == "mlb" else None
        if mlb_props_root_key:
            # oddsapi_hitter_props/oddsapi_pitcher_props are nested TWO
            # levels deep (player_name -> market_name -> {line, over_odds,
            # under_odds}), unlike every other odds snapshot this generic
            # reader handles (one level: container_key -> {market_name:
            # value}). _market_rows_from_mapping's recursion only descends
            # through known container-key names, so the dynamic player-name
            # level stops it before it ever reaches the market/line data --
            # confirmed live 2026-07-24: these 2 files were being scanned
            # (files_scanned counted them) but produced zero usable rows,
            # leaving MLB prop odds with no history tracked at all. Reuse
            # _flatten_mlb_props (already correct -- it's what feeds the
            # separate CSV props-tracking snapshot) instead of trying to
            # teach the generic parser a second nesting level that no other
            # sport's shape needs.
            rows = _flatten_mlb_props(candidate, mlb_props_root_key).to_dict("records")
        elif slug in {"nba", "wnba"} and _is_basketball_game_cards_path(candidate):
            # game_cards_{date}.csv holds 3 markets per row as columns --
            # see _flatten_basketball_game_cards's own docstring. Without
            # this, the generic CSV reader would only ever surface one
            # market per game (whichever column _primary_line_value checks
            # first), silently dropping the other two.
            rows = _flatten_basketball_game_cards(candidate).to_dict("records")
        elif suffix == ".csv":
            rows = _odds_history_rows_from_csv(candidate)
        elif suffix == ".jsonl":
            rows = _odds_history_rows_from_jsonl(candidate)
        else:
            rows = _odds_history_rows_from_json(candidate)
        _trace_log("after_odds_history_candidate_read", sport=slug, path=str(candidate), suffix=suffix, size_bytes=_trace_file_size(candidate), rows=int(len(rows)), elapsed_ms=round((time.perf_counter() - candidate_read_started) * 1000, 3))
        if not rows:
            continue

        for row in rows:
            if not isinstance(row, Mapping):
                continue
            matchup_label = _row_h2h_matchup_label(row)
            if matchup_label:
                h2h_matchups_in_source.add(matchup_label)
            market_key = _odds_history_market_key(row)
            line_snapshot = _odds_history_line_snapshot(row)
            current_line = _primary_line_value(row)
            if not market_key or not line_snapshot or current_line is None:
                continue
            if matchup_label:
                h2h_matchups_passed_gate.add(matchup_label)
            current_odds = _primary_odds_value(row)
            row_snapshot_ts = str(row.get("snapshot_ts") or row.get("retrieved_at") or row.get("retrievedAt") or row.get("fetched_at") or candidate_snapshot_ts).strip() or candidate_snapshot_ts
            dedupe_key = (market_key, current_line, current_odds, row_snapshot_ts)
            if dedupe_key in seen_current_snapshots:
                continue
            seen_current_snapshots.add(dedupe_key)

            shard_key = _shard_key_for_row(row, sport=slug, date_str=date_str, source_root=source_root)
            row_game_date = _row_game_date(row, sport=slug)
            markets = _shard_markets(shard_key)
            seen_market_keys = shard_seen_market_keys[shard_key]
            seen_live_market_keys = shard_seen_live_market_keys[shard_key]
            seen_market_keys.add(market_key)
            if matchup_label:
                h2h_matchups_written.add(matchup_label)

            market_state = markets.get(market_key)
            if not isinstance(market_state, dict):
                market_state = {"history": []}
            history = market_state.get("history")
            if not isinstance(history, list):
                history = []

            previous_line = _line_number(market_state.get("last_line"))
            if previous_line is None and history:
                previous_line = _line_number((history[-1] or {}).get("current_line"))
            previous_odds = _line_number(market_state.get("last_odds"))
            if previous_odds is None and history:
                previous_odds = _line_number((history[-1] or {}).get("last_odds"))
            previous_snapshot_ts = str(market_state.get("last_snapshot_ts") or "").strip() or None
            if previous_snapshot_ts is None and history:
                previous_snapshot_ts = str((history[-1] or {}).get("captured_at") or (history[-1] or {}).get("snapshot_ts") or "").strip() or None
            # Confirmed live 2026-07-30, right after this deploy: for a market
            # ALREADY mid-live-game the first time this code runs against it,
            # market_state carries no "is_live" history at all (it predates
            # this field), so a naive "is_live and not seen this call" check
            # can't tell "genuinely just went live" apart from "has been live
            # for hours, we just never recorded it" -- and would stamp
            # whatever line happened to be sitting there (an arbitrary
            # already-in-play number) as if it were the real pregame close.
            # Require an EXPLICIT prior `is_live: False` observation before
            # trusting previous_line as a real closing candidate; markets
            # that predate this field (key absent) get none, by design --
            # no closing line is better than a wrong one. Read BEFORE
            # updating market_state["is_live"] just below, and updated
            # unconditionally (ahead of the dedupe short-circuit right
            # after) so a market whose line sits unchanged for many ticks
            # while pregame still gets its pregame observation recorded --
            # otherwise the transition tick, when the line finally DOES
            # move, would find no prior "is_live: False" to trust.
            was_confirmed_pregame = market_state.get("is_live") is False
            # Confirmed live 2026-07-30, same deploy: _is_live_odds_row returns
            # False for MLB's standard game-line feed (h2h/spreads/totals)
            # EVEN WHILE THE GAME IS ACTUALLY LIVE -- that row shape carries
            # no status/state/period/selection text at all, only team names
            # and numbers, so the heuristic's text markers structurally never
            # match it. Without a second signal the closing-line stamp could
            # never fire for the exact market type the board displays.
            # commence_time vs now is not just a workaround here -- "the last
            # line before scheduled kickoff" is the textbook definition of a
            # closing line anyway, arguably more correct than gating on a
            # feed-specific live tag at all. A first version of this fix
            # scoped the new signal to JUST this is_live tracking, on the
            # theory that broadening it further was a separate, larger
            # change -- that turned out to be unworkable: the stamp lives
            # inside the `is_live_row and ...` branch below, so a market
            # this signal alone marks is_live could still never actually
            # reach the stamp while is_live_row (unchanged) stayed False.
            # The two checks have to agree, so this now also feeds
            # event_type="live" tagging and count_live/count_pregame below --
            # a real fix for those too (they had the identical blind spot),
            # not scope creep.
            row_is_live_cheap = _is_live_odds_row(row) or _row_commence_time_has_passed(row, now_iso=now) or _row_elapsed_game_time_indicates_live(row)
            market_state["is_live"] = True if (row_is_live_cheap or market_state.get("is_live") is True) else False

            if previous_line is not None and current_line == previous_line and previous_odds is not None and current_odds == previous_odds and previous_snapshot_ts == row_snapshot_ts and history:
                markets[market_key] = market_state
                continue

            try:
                source_path = str(candidate.relative_to(source_root))
            except Exception:
                source_path = str(candidate)

            delta = current_line - previous_line if previous_line is not None else None
            movement = _movement_direction(delta)
            percent_change = _percent_change(current_line, previous_line)
            canonical_record = _canonical_odds_record(
                row=row,
                market_key=market_key,
                sport=slug,
                timestamp=now,
                current_line=current_line,
            )
            canonical_row = attach_market_id(
                {key: value for key, value in row.items() if key not in {"history", "markets"}},
                sport=slug,
                event_id=canonical_record.get("event_id"),
                market_type=canonical_record.get("market_type"),
                entity=canonical_record.get("entity"),
                line=current_line,
            )
            normalized_entry = normalize_odds_entry(
                row=row,
                sport=slug,
                market_key=market_key,
                timestamp=now,
                source_path=source_path,
                market_id=canonical_row.get("market_id"),
                event_id=canonical_record.get("event_id"),
                market_type=canonical_record.get("market_type"),
                entity=canonical_record.get("entity"),
                line=current_line,
                odds=current_odds,
                selection=str(row.get("selection") or "").strip() or None,
            )
            # row_is_live_cheap (commence_time-aware, computed above) covers
            # the blind spot _is_live_odds_row alone has for MLB's standard
            # game-line feed -- OR'd in here too so a market past its own
            # kickoff is treated as live for tagging/counting purposes even
            # when the row itself carries no live/in-play text at all.
            is_live_row = _is_live_odds_row(row, normalized_entry) or row_is_live_cheap
            is_final_row = _is_final_status_row(row, normalized_entry)
            if is_live_row:
                count_live += 1
            else:
                count_pregame += 1

            previous_market_type = None
            if history:
                previous_market_type = str((history[-1] or {}).get("normalized", {}).get("market_type") or (history[-1] or {}).get("market_type") or "").strip().lower() or None

            event_type = "open" if previous_line is None and not history else "update"
            if is_live_row and market_key not in seen_live_market_keys:
                event_type = "live"
                seen_live_market_keys.add(market_key)
                # Stamp the true closing line/price exactly once, on the
                # transition into live, using the value observed the tick
                # BEFORE this one (previous_line/previous_odds) -- not
                # current_line/current_odds, which is already the in-play
                # number. Guarded on closing_line being unset rather than on
                # seen_live_market_keys (which is rebuilt empty every call to
                # this function, so it cannot by itself prove "first ever"
                # across ticks) -- market_state itself persists across ticks
                # via the shard file, so this is the only check that actually
                # makes the stamp idempotent. Left unset (never backfilled)
                # when previous_line is None -- e.g. a market first observed
                # already live has no real pregame value to record.
                if was_confirmed_pregame and market_state.get("closing_line") is None and previous_line is not None:
                    market_state["closing_line"] = previous_line
                    market_state["closing_price"] = previous_odds
                    market_state["closing_captured_at"] = now
            elif is_final_row:
                event_type = "final"
            elif previous_market_type is not None and str(normalized_entry.get("market_type") or "").strip().lower() != previous_market_type:
                event_type = "update"

            lifecycle_event = _market_lifecycle_event(
                row=row,
                normalized_entry=normalized_entry,
                event_type=event_type,
                sport=slug,
                timestamp=now,
                market_key=market_key,
                current_line=current_line,
                current_odds=_primary_odds_value(row),
                is_live=is_live_row,
            )
            # #83. Steam rides the lifecycle event (downstream consumers see
            # it wherever they already read movement) AND a bounded per-date
            # record for surfaces that want only the steam.
            steam = _steam_signal(
                previous_line=previous_line,
                current_line=current_line,
                previous_odds=previous_odds,
                current_odds=current_odds,
                previous_ts=previous_snapshot_ts,
                observed_ts=now,
                capture_phase=lifecycle_event.get("capture_phase"),
            )
            if steam is not None:
                # Absolute prior values, not just the delta -- the steam
                # rail wants "prev -> current", and previous_line/
                # previous_odds are already in scope here from the same
                # comparison _steam_signal just made.
                steam["previous_line"] = previous_line
                steam["previous_odds"] = previous_odds
                lifecycle_event["steam"] = steam
                steam_events.append({**lifecycle_event})
            lifecycle_events.append(lifecycle_event)

            history.append(
                {
                    "captured_at": now,
                    "timestamp": now,
                    "sport": slug,
                    "date": date_str,
                    "game_date": row_game_date.isoformat() if row_game_date is not None else None,
                    "source_path": source_path,
                    "market_key": market_key,
                    "market_id": canonical_row.get("market_id"),
                    **canonical_record,
                    "previous_line": previous_line,
                    "current_line": current_line,
                    "last_odds": current_odds,
                    "snapshot_ts": row_snapshot_ts,
                    "delta": delta,
                    "delta_line": delta,
                    "percent_change": percent_change,
                    "movement": movement,
                    "line": _json_safe(line_snapshot),
                    "row": _json_safe(canonical_row),
                    "normalized": normalized_entry,
                }
            )
            if len(history) > _ODDS_HISTORY_LIMIT:
                history = history[-_ODDS_HISTORY_LIMIT:]
            # #112. row/normalized (the heaviest two fields per entry) get
            # stripped from every history entry except each market's own
            # true latest -- see the shard-wide sweep right before this
            # shard gets written, a few hundred lines down. Not done here:
            # this branch only runs for markets that got a NEW entry THIS
            # cycle (the dedupe check above skips it otherwise), and most of
            # an oversized shard turned out to be quiet/cold markets sitting
            # on old, never-revisited history -- stripping only here would
            # never have touched them.
            market_state["history"] = history
            market_state["last_line"] = current_line
            market_state["previous_line"] = previous_line
            market_state["last_odds"] = current_odds
            market_state["last_snapshot_ts"] = row_snapshot_ts
            market_state["delta"] = delta
            market_state["delta_line"] = delta
            market_state["percent_change"] = percent_change
            market_state["movement"] = movement
            market_state["last_updated"] = now
            market_state["last_source_path"] = source_path
            markets[market_key] = market_state
            entries_appended += 1
            shard_entries_appended[shard_key] += 1

    for shard_key, markets in shards.items():
        seen_market_keys = shard_seen_market_keys.get(shard_key, set())
        missing_market_keys = [key for key in markets.keys() if key not in seen_market_keys]
        for market_key in missing_market_keys:
            market_state = markets.get(market_key)
            if not isinstance(market_state, dict):
                continue
            history = market_state.get("history") if isinstance(market_state.get("history"), list) else []
            latest = history[-1] if history else {}
            if not isinstance(latest, Mapping):
                continue
            normalized_entry = latest.get("normalized") if isinstance(latest.get("normalized"), Mapping) else {}
            lifecycle_events.append(
                _market_lifecycle_event(
                    row=latest.get("row") if isinstance(latest.get("row"), Mapping) else latest,
                    normalized_entry=normalized_entry,
                    event_type="close",
                    sport=slug,
                    timestamp=now,
                    market_key=market_key,
                    current_line=_line_number(latest.get("current_line")),
                    current_odds=_line_number(latest.get("last_odds")),
                    is_live=bool(normalized_entry.get("is_live") if isinstance(normalized_entry, Mapping) else False),
                )
            )

    _annotate_steam_book_confirmation(steam_events)
    _record_steam_events(date_str, steam_events)
    if lifecycle_events:
        _trace_log("before_append_odds_lifecycle_events", sport=slug, date=date_str, events=len(lifecycle_events), path=str(odds_lifecycle_path(date_str)))
        append_odds_lifecycle_events(date_str, lifecycle_events)
        _trace_log("after_append_odds_lifecycle_events", sport=slug, date=date_str, events=len(lifecycle_events), path=str(odds_lifecycle_path(date_str)), size_bytes=_trace_file_size(odds_lifecycle_path(date_str)))

    if not entries_appended:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_line_or_odds_changes",
            "sport": slug,
            "date": date_str,
            "files_scanned": int(files_scanned),
            "entries_appended": 0,
            "shards": {},
        }

    shard_results: dict[str, dict[str, Any]] = {}
    for shard_key, shard_markets in shards.items():
        if shard_entries_appended.get(shard_key, 0) <= 0:
            continue
        # #112 follow-up (breadth). Evict entire markets that haven't been
        # touched in _odds_history_market_staleness_ceiling_seconds() BEFORE
        # the depth-bounding sweep below -- depth bounding trims how much
        # history a market carries, this bounds how many markets exist at
        # all, which is the actual driver of the shard's monotonic growth
        # (see that function's own comment for the live measurements).
        # Mutating shard_markets in place via a materialized key list, since
        # deleting during iteration over .values() would raise.
        staleness_ceiling = _odds_history_market_staleness_ceiling_seconds()
        now_dt = datetime.now(timezone.utc)
        evicted_market_count = 0
        for market_key in list(shard_markets.keys()):
            market_state = shard_markets.get(market_key)
            if not isinstance(market_state, dict):
                continue
            market_last_updated = _parse_utc_datetime(market_state.get("last_updated") or market_state.get("last_snapshot_ts"))
            if market_last_updated is None:
                continue
            if (now_dt - market_last_updated).total_seconds() > staleness_ceiling:
                del shard_markets[market_key]
                evicted_market_count += 1
        if evicted_market_count:
            _trace_log("odds_history_market_eviction", sport=slug, shard_key=shard_key, evicted=evicted_market_count, remaining=len(shard_markets), staleness_ceiling_seconds=staleness_ceiling)

        # #112 correction: the strip at append time only ever touched
        # markets that got a NEW entry THIS cycle -- a market whose price
        # hasn't moved hits the dedupe short-circuit above and skips the
        # append path entirely, so it never got swept, and it turns out
        # most of an 18.9MB shard is exactly that: quiet/cold markets sitting
        # on old fully-loaded history from earlier in the day. Confirmed
        # live 2026-07-28: the append-time-only version of this fix did not
        # stop KeyValuePayloadTooLarge from recurring post-deploy. Sweeping
        # every market in the shard being written -- not just the ones that
        # changed this cycle -- actually bounds it. Still keeps the one real
        # consumer's need intact: each market's OWN true last entry is
        # never touched, whether or not it was updated this cycle.
        for market_state in shard_markets.values():
            if not isinstance(market_state, dict):
                continue
            history = market_state.get("history")
            if not isinstance(history, list) or not history:
                continue
            # Same gap, second dimension: the entry-COUNT trim
            # (history[-_ODDS_HISTORY_LIMIT:]) only ever ran in the
            # per-row append branch too, so a quiet market sitting on 50
            # entries from before _ODDS_HISTORY_LIMIT was cut to 20 would
            # never get trimmed down -- only its fields would get
            # stripped, not its count. Confirmed live 2026-07-28:
            # KeyValuePayloadTooLarge recurred on a cycle that ran AFTER
            # both the field-strip sweep and the 50->20 limit cut were
            # deployed and confirmed live via /api/ops/version, on a run
            # that started after that deploy -- the only remaining
            # explanation was quiet markets never being trimmed either.
            if len(history) > _ODDS_HISTORY_LIMIT:
                history = history[-_ODDS_HISTORY_LIMIT:]
                market_state["history"] = history
            if len(history) <= 1:
                continue
            for old_entry in history[:-1]:
                if isinstance(old_entry, dict):
                    old_entry.pop("row", None)
                    old_entry.pop("normalized", None)
        history_path = _odds_history_path(tracking_root, shard_key)
        artifact_history_path = _odds_history_artifact_path(source_root, slug, shard_key)
        shared_history_path = _shared_odds_history_path(slug, shard_key)
        payload = {
            "schema_version": 1,
            "sport": slug,
            "shard_key": shard_key,
            "date": date_str,
            "updated_at": now,
            "history_limit": _ODDS_HISTORY_LIMIT,
            "markets": shard_markets,
        }
        # Every market used to also be flattened onto the payload's own
        # top level (payload.update(shard_markets)) -- an exact duplicate
        # of what's already under "markets", roughly doubling this
        # payload's size for every reader/cache that holds it. Confirmed
        # every consumer (odds_lifecycle.py's _market_state_from_payload,
        # mlb/cards.py, soccer/market_board.py,
        # intelligence_state.py's _odds_history_market_states) reads
        # payload["markets"] as the primary path; the top-level flattened
        # keys were only ever a fallback for payloads predating the
        # "markets" key existing, which this writer hasn't produced in a
        # long time.
        _trace_log("before_write_odds_history_json", sport=slug, shard_key=shard_key, history_path=str(history_path), shared_history_path=str(shared_history_path), artifact_history_path=str(artifact_history_path), markets=len(shard_markets), entries_appended=shard_entries_appended[shard_key])
        # #112/#120, per explicit user direction 2026-07-28 ("the file size
        # limit is frankly unrealistic from keyvalue - we need this to be
        # artifact written/artifact read based"): odds_history shards are
        # routinely tens of MB on a real slate (measured live: 51.1MB,
        # 3,713 markets, for a single MLB day) -- not an edge case
        # occasionally exceeding the keyvalue store's 8MB ceiling, but the
        # ordinary case always exceeding it. Treating keyvalue as the
        # primary transport and the artifact-publish fallback
        # (_write_state_payload, #43/#108's pattern) as an occasional
        # backstop was backwards for a payload shape that's essentially
        # guaranteed to need the fallback every single cycle -- go straight
        # to the artifact transport (local-disk write + cross-service
        # publish) unconditionally, never attempt the keyvalue write at
        # all. The board reads these exact paths (odds_control_plane.py's
        # load_odds_history_payload_for_sport) directly off local disk to
        # match -- no keyvalue read on that side either.
        _write_odds_history_artifact(history_path, payload)
        _write_odds_history_artifact(shared_history_path, payload)
        _write_odds_history_artifact(artifact_history_path, payload)
        _trace_log("after_write_odds_history_json", sport=slug, shard_key=shard_key, history_path=str(history_path), shared_history_path=str(shared_history_path), artifact_history_path=str(artifact_history_path), markets=len(shard_markets), entries_appended=shard_entries_appended[shard_key])
        shard_results[shard_key] = {
            "history_path": str(history_path),
            "shared_history_path": str(shared_history_path),
            "artifact_history_path": str(artifact_history_path),
            "markets_tracked": len(shard_markets),
            "entries_appended": shard_entries_appended[shard_key],
        }

    primary_shard_key = next(iter(shard_results), None)
    primary = shard_results.get(primary_shard_key, {}) if primary_shard_key else {}
    h2h_matchup_coverage = {
        "in_source": sorted(h2h_matchups_in_source),
        "passed_gate": sorted(h2h_matchups_passed_gate),
        "written": sorted(h2h_matchups_written),
        # The two diffs are the whole point: non-empty dropped_at_gate means
        # the market_key/line_snapshot/current_line gate rejected a real
        # row (missing/malformed fields for that specific matchup);
        # non-empty dropped_after_gate means the row passed that gate but
        # never reached seen_market_keys.add (should be structurally
        # impossible today -- nothing continues between the two -- so a
        # non-empty result here would itself be the finding).
        "dropped_at_gate": sorted(h2h_matchups_in_source - h2h_matchups_passed_gate),
        "dropped_after_gate": sorted(h2h_matchups_passed_gate - h2h_matchups_written),
    }
    if h2h_matchups_in_source:
        _trace_log(
            "odds_history_h2h_matchup_coverage",
            sport=slug,
            date=date_str,
            in_source=len(h2h_matchups_in_source),
            passed_gate=len(h2h_matchups_passed_gate),
            written=len(h2h_matchups_written),
            dropped_at_gate=h2h_matchup_coverage["dropped_at_gate"],
            dropped_after_gate=h2h_matchup_coverage["dropped_after_gate"],
        )
        try:
            from syndicate.features.shared.refresh_state_store import reports_root as _reports_root
            from syndicate.features.shared.refresh_state_store import write_json_file as _write_status

            status_path = _reports_root() / "refresh_status" / "latest" / "odds_history_h2h_matchup_coverage_status.json"
            existing = {}
            try:
                from syndicate.features.shared.refresh_state_store import read_json_file as _read_status

                existing = _read_status(status_path) or {}
            except Exception:
                existing = {}
            if not isinstance(existing, dict):
                existing = {}
            existing[slug] = {"date": date_str, "updated_at": now, **h2h_matchup_coverage}
            _write_status(status_path, existing)
        except Exception as exc:
            _trace_log("odds_history_h2h_matchup_coverage_status_write_failed", sport=slug, error=f"{type(exc).__name__}: {exc}")
    return {
        "ok": True,
        "skipped": False,
        "reason": None,
        "sport": slug,
        "date": date_str,
        "history_path": primary.get("history_path"),
        "shared_history_path": primary.get("shared_history_path"),
        "artifact_history_path": primary.get("artifact_history_path"),
        "files_scanned": int(files_scanned),
        "entries_appended": int(entries_appended),
        "markets_tracked": sum(result["markets_tracked"] for result in shard_results.values()),
        "shards": shard_results,
        "h2h_matchup_coverage": h2h_matchup_coverage if h2h_matchups_in_source else None,
    }


def _read_json_payload(path: Path) -> Any:
    started = time.perf_counter()
    _trace_log("before_read_json_payload", **_trace_path_payload(path))
    try:
        if not path.exists():
            _trace_log("after_read_json_payload", **_trace_path_payload(path, rows=0), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=True)
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = None
        if isinstance(payload, list):
            rows = len(payload)
        elif isinstance(payload, dict):
            for key in ("rows", "recommendations", "items"):
                maybe_rows = payload.get(key)
                if isinstance(maybe_rows, list):
                    rows = len(maybe_rows)
                    break
        _trace_log("after_read_json_payload", **_trace_path_payload(path, rows=rows), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), skipped=False)
        return payload
    except Exception:
        _trace_log("after_read_json_payload", **_trace_path_payload(path), elapsed_ms=round((time.perf_counter() - started) * 1000, 3), error=True)
        return None


def _choose_existing(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _movement_signal_paths_from_meta(meta: Mapping[str, Any] | None) -> list[Path]:
    paths: list[Path] = []
    if not isinstance(meta, Mapping):
        return paths
    direct_path = meta.get("signals_path") or meta.get("movement_path")
    if isinstance(direct_path, str) and direct_path.strip():
        paths.append(Path(direct_path).expanduser())
    artifacts = meta.get("artifacts")
    if isinstance(artifacts, Mapping):
        for artifact in artifacts.values():
            if not isinstance(artifact, Mapping):
                continue
            for key in ("signals_path", "movement_path"):
                value = artifact.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(Path(value).expanduser())
    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.resolve()) if path.exists() else str(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(path)
    return unique_paths


def _normalize_signal_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text


def _candidate_signal_tokens(row: Mapping[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for key in (
        "event_key",
        "event_id",
        "game_id",
        "game_pk",
        "matchup",
        "subject_key",
        "player_name",
        "player_key",
        "team",
        "team_key",
        "market",
        "selection",
        "name",
    ):
        token = _normalize_signal_token(row.get(key))
        if token:
            tokens.add(token)
    return tokens


def _payload_rows(payload: Any) -> tuple[list[dict[str, Any]], str]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)], "list"
    if isinstance(payload, dict):
        for key in ("data", "recommendations", "rows", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, Mapping)], key
    return [], ""


def _update_payload_rows(payload: Any, rows: list[dict[str, Any]], container_key: str) -> Any:
    if isinstance(payload, list):
        return rows
    if isinstance(payload, dict) and container_key:
        updated = dict(payload)
        updated[container_key] = rows
        return updated
    return payload


def _recommendation_paths_for_refresh(*, source_root: Path, sport: str, date_str: str) -> list[Path]:
    candidates = [
        source_root / "data" / "processed" / f"recommendations_slate_{date_str}.json",
        source_root / "data" / "processed" / f"props_recommendations_top_by_game_{date_str}.json",
        source_root / "data" / "processed" / f"recommendations_{date_str}.json",
        source_root / "api" / "recommendations" / f"recommendations_{date_str}.json",
        source_root / "data" / "api" / "recommendations" / f"recommendations_{date_str}.json",
        source_root / "source_artifacts" / "api" / "recommendations" / f"recommendations_{date_str}.json",
    ]
    if sport in {"nba", "wnba"}:
        candidates.extend(
            [
                source_root / "data" / "processed" / f"recommendations_slate_{date_str}.json",
                source_root / "data" / "processed" / f"props_recommendations_top_by_game_{date_str}.json",
            ]
        )
    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists():
            unique_candidates.append(candidate)
    return unique_candidates


def refresh_impacted_recommendations_for_tracking(*, sport: str, source_root: Path, date_str: str, tracking_meta: Mapping[str, Any] | None = None) -> dict[str, Any]:
    signal_paths = _movement_signal_paths_from_meta(tracking_meta)
    _trace_log("before_refresh_impacted_recommendations", sport=str(sport or "").strip().lower(), date=date_str, signal_paths=[str(path) for path in signal_paths], signal_count=len(signal_paths))
    if not signal_paths:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_movement_signals",
            "files_updated": 0,
            "rows_updated": 0,
            "signals_rows": 0,
        }

    signal_tokens: set[str] = set()
    signals_rows = 0
    for path in signal_paths:
        _trace_log("before_read_movement_signals", sport=str(sport or "").strip().lower(), **_trace_path_payload(path))
        read_started = time.perf_counter()
        try:
            frame = pd.read_csv(path)
        except Exception:
            _trace_log("after_read_movement_signals", sport=str(sport or "").strip().lower(), **_trace_path_payload(path), elapsed_ms=round((time.perf_counter() - read_started) * 1000, 3), error=True)
            continue
        _trace_log("after_read_movement_signals", sport=str(sport or "").strip().lower(), **_trace_path_payload(path, rows=int(len(frame))), elapsed_ms=round((time.perf_counter() - read_started) * 1000, 3))
        if frame.empty:
            continue
        if "movement_signals" not in path.name:
            candidate_mask = pd.Series(False, index=frame.index)
            if "movement_significant" in frame.columns:
                candidate_mask = candidate_mask | frame["movement_significant"].fillna(False).astype(bool)
            if "line_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["line_move"], errors="coerce").abs().fillna(0.0).ge(0.5)
            if "implied_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["implied_move"], errors="coerce").abs().fillna(0.0).ge(0.02)
            if "price_move" in frame.columns:
                candidate_mask = candidate_mask | pd.to_numeric(frame["price_move"], errors="coerce").abs().fillna(0.0).ge(10.0)
            frame = frame.loc[candidate_mask].copy()
        if frame.empty:
            continue
        signals_rows += int(len(frame))
        for _, row in frame.iterrows():
            signal_tokens.update(_candidate_signal_tokens(row))

    if not signal_tokens:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_signal_tokens",
            "files_updated": 0,
            "rows_updated": 0,
            "signals_rows": int(signals_rows),
        }

    files_updated = 0
    rows_updated = 0
    updated_files: list[str] = []
    recommendation_paths = _recommendation_paths_for_refresh(source_root=source_root, sport=sport, date_str=date_str)
    for recommendation_path in recommendation_paths:
        _trace_log("before_read_recommendation_json", sport=sport, **_trace_path_payload(recommendation_path))
        read_started = time.perf_counter()
        payload = _read_json_payload(recommendation_path)
        _trace_log("after_read_recommendation_json", sport=sport, **_trace_path_payload(recommendation_path), elapsed_ms=round((time.perf_counter() - read_started) * 1000, 3), has_payload=bool(payload))
        rows, container_key = _payload_rows(payload)
        if not rows:
            continue

        changed = False
        for index, row in enumerate(rows):
            row_tokens = _candidate_signal_tokens(row)
            if not row_tokens or signal_tokens.isdisjoint(row_tokens):
                continue
            rows[index] = build_recommendation_output(row, sport=sport)
            changed = True
            rows_updated += 1

        if not changed:
            continue

        updated_payload = _update_payload_rows(payload, rows, container_key)
        if isinstance(updated_payload, dict):
            updated_payload["lightweight_refresh"] = {
                "sport": sport,
                "date": date_str,
                "updated_at": _utc_now(),
                "signals_rows": int(signals_rows),
                "rows_updated": int(rows_updated),
            }
        _trace_log("before_write_recommendation_json", sport=sport, **_trace_path_payload(recommendation_path, rows=int(len(rows))))
        _write_json(recommendation_path, updated_payload)
        _trace_log("after_write_recommendation_json", sport=sport, **_trace_path_payload(recommendation_path, rows=int(len(rows))))
        files_updated += 1
        try:
            updated_files.append(str(recommendation_path.relative_to(source_root)))
        except Exception:
            updated_files.append(str(recommendation_path))

    return {
        "ok": True,
        "skipped": False,
        "reason": None,
        "files_updated": int(files_updated),
        "rows_updated": int(rows_updated),
        "signals_rows": int(signals_rows),
        "signal_paths": [str(path) for path in signal_paths],
        "updated_files": updated_files,
    }


def _coalesce_series(df: pd.DataFrame, candidates: list[str], default: Any = "") -> pd.Series:
    for column in candidates:
        if column in df.columns:
            return df[column]
    return pd.Series(default, index=df.index)


def _to_snapshot_ts(df: pd.DataFrame, *, fallback_ts: str) -> pd.Series:
    for column in ("snapshot_ts", "last_seen_at", "first_seen_at", "retrieved_at", "pulled_at"):
        if column in df.columns:
            values = pd.to_datetime(df[column], errors="coerce", utc=True)
            if values.notna().any():
                return values.fillna(pd.Timestamp(fallback_ts, tz="UTC")).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return pd.Series(fallback_ts, index=df.index)


def _persist_tracking_snapshot(
    *,
    tracking_root: Path,
    prefix: str,
    scope: str,
    snapshot_df: pd.DataFrame,
    key_cols: list[str],
    line_col: str | None,
    price_cols: list[str],
    label_cols: list[str] | None = None,
) -> dict[str, Any]:
    _trace_log("before_persist_tracking_snapshot", prefix=prefix, scope=scope, tracking_root=str(tracking_root))
    tracking_root.mkdir(parents=True, exist_ok=True)
    opening_path = tracking_root / f"{prefix}_opening_{scope}.csv"
    history_path = tracking_root / f"{prefix}_history_{scope}.csv"
    movement_path = tracking_root / f"{prefix}_movement_signals_{scope}.csv"

    normalized = snapshot_df.copy() if isinstance(snapshot_df, pd.DataFrame) else pd.DataFrame()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "empty_snapshot",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    required_cols = list(dict.fromkeys(key_cols + ([line_col] if line_col else []) + price_cols + ["snapshot_ts"]))
    if label_cols:
        required_cols.extend([col for col in label_cols if col not in required_cols])
    for column in required_cols:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    normalized = normalized[required_cols].copy()
    normalized["snapshot_ts"] = pd.to_datetime(normalized["snapshot_ts"], errors="coerce", utc=True)
    normalized = normalized[normalized["snapshot_ts"].notna()].copy()
    if normalized.empty:
        return {
            "ok": True,
            "skipped": True,
            "reason": "missing_snapshot_ts",
            "opening_path": str(opening_path),
            "history_path": str(history_path),
            "movement_path": str(movement_path),
            "signals_rows": 0,
        }

    normalized = normalized.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").reset_index(drop=True)
    history_rows = normalized.copy()
    history_rows["snapshot_ts"] = history_rows["snapshot_ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    _trace_log("before_write_history_csv", path=str(history_path), rows=int(len(history_rows)), size_bytes=_trace_file_size(history_path))
    if history_path.exists():
        history_rows.to_csv(history_path, mode="a", header=False, index=False)
    else:
        history_rows.to_csv(history_path, index=False)
    _trace_log("after_write_history_csv", path=str(history_path), rows=int(len(history_rows)), size_bytes=_trace_file_size(history_path))

    _trace_log("before_read_opening_csv", path=str(opening_path), size_bytes=_trace_file_size(opening_path))
    existing_open = _read_csv(opening_path)
    _trace_log("after_read_opening_csv", path=str(opening_path), rows=int(len(existing_open)) if isinstance(existing_open, pd.DataFrame) else None, size_bytes=_trace_file_size(opening_path))
    if not existing_open.empty:
        for column in normalized.columns:
            if column not in existing_open.columns:
                existing_open[column] = pd.NA
        existing_open = existing_open[normalized.columns].copy()
        existing_open["snapshot_ts"] = pd.to_datetime(existing_open["snapshot_ts"], errors="coerce", utc=True)

    opening_source = pd.concat([existing_open, normalized], ignore_index=True, sort=False) if not existing_open.empty else normalized.copy()
    _trace_log("before_opening_groupby", path=str(opening_path), rows=int(len(opening_source)))
    combined_open = opening_source.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).first()
    _trace_log("after_opening_groupby", path=str(opening_path), rows=int(len(combined_open)))

    opening_to_write = combined_open.copy()
    opening_to_write["snapshot_ts"] = pd.to_datetime(opening_to_write["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    _trace_log("before_write_opening_csv", path=str(opening_path), rows=int(len(opening_to_write)), size_bytes=_trace_file_size(opening_path))
    opening_to_write.to_csv(opening_path, index=False)
    _trace_log("after_write_opening_csv", path=str(opening_path), rows=int(len(opening_to_write)), size_bytes=_trace_file_size(opening_path))

    _trace_log("before_latest_groupby", path=str(movement_path), rows=int(len(normalized)))
    latest = normalized.sort_values(key_cols + ["snapshot_ts"], kind="mergesort").groupby(key_cols, dropna=False, as_index=False).last()
    _trace_log("after_latest_groupby", path=str(movement_path), rows=int(len(latest)))
    movement = latest.merge(
        combined_open[key_cols + ([line_col] if line_col else []) + price_cols].rename(
            columns={
                **({line_col: "open_line"} if line_col else {}),
                **{column: f"open_{column}" for column in price_cols},
            }
        ),
        on=key_cols,
        how="left",
    )
    movement = movement.rename(columns={line_col: "current_line"} if line_col else {})
    for column in price_cols:
        movement = movement.rename(columns={column: f"current_{column}"})
    if line_col:
        movement["line_move"] = pd.to_numeric(movement.get("current_line"), errors="coerce") - pd.to_numeric(movement.get("open_line"), errors="coerce")
    for column in price_cols:
        movement[f"{column}_move"] = pd.to_numeric(movement.get(f"current_{column}"), errors="coerce") - pd.to_numeric(movement.get(f"open_{column}"), errors="coerce")
    movement["latest_snapshot_ts"] = pd.to_datetime(movement["snapshot_ts"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    movement = movement.drop(columns=["snapshot_ts"], errors="ignore")
    _trace_log("before_write_movement_csv", path=str(movement_path), rows=int(len(movement)), size_bytes=_trace_file_size(movement_path))
    movement.to_csv(movement_path, index=False)
    _trace_log("after_write_movement_csv", path=str(movement_path), rows=int(len(movement)), size_bytes=_trace_file_size(movement_path))

    return {
        "ok": True,
        "skipped": False,
        "opening_path": str(opening_path),
        "history_path": str(history_path),
        "movement_path": str(movement_path),
        "opening_rows": int(len(combined_open)),
        "history_rows": int(len(history_rows)),
        "signals_rows": int(len(movement)),
    }


def _build_nhl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event_id", "game_id", "date"], default="")
    out["player_key"] = _coalesce_series(df, ["player_id", "_merge_key", "player_name", "player"], default="")
    out["player_name"] = _coalesce_series(df, ["player_name", "player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book", "bookmaker"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line", "point"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_ncaab_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    home = _coalesce_series(df, ["home_team", "home", "team_home"], default="")
    away = _coalesce_series(df, ["away_team", "away", "team_away"], default="")
    event_id = _coalesce_series(df, ["event_id", "id"], default="")
    out["event_key"] = event_id.where(event_id.astype(str).str.strip().ne(""), away.astype(str) + " @ " + home.astype(str))
    out["book"] = _coalesce_series(df, ["bookmaker_key", "bookmaker", "provider", "book"], default="")
    out["market"] = _coalesce_series(df, ["market", "market_key"], default="")
    out["selection"] = _coalesce_series(df, ["outcome_name", "name", "team"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["point", "line", "spread", "overUnder"], default=pd.NA), errors="coerce")
    out["price"] = pd.to_numeric(_coalesce_series(df, ["price", "odds", "homeMoneyline", "awayMoneyline"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _build_soccer_game_odds_snapshot(source_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if source_root.exists():
        for league_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
            candidate = league_dir / "api" / "odds" / "game_odds_current.csv"
            df = _read_csv(candidate)
            if df.empty:
                continue
            fallback_ts = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            df = df.copy()
            df["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _build_soccer_props_snapshot(source_root: Path, date_str: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if source_root.exists():
        for league_dir in sorted(path for path in source_root.iterdir() if path.is_dir()):
            candidate = league_dir / "props" / f"{date_str}.csv"
            df = _read_csv(candidate)
            if df.empty:
                continue
            fallback_ts = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            df = df.copy()
            df["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _build_nfl_props_snapshot(path: Path) -> pd.DataFrame:
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = pd.DataFrame()
    out["event_key"] = _coalesce_series(df, ["event", "event_id"], default="")
    out["player_name"] = _coalesce_series(df, ["player"], default="")
    out["market"] = _coalesce_series(df, ["market"], default="")
    out["book"] = _coalesce_series(df, ["book"], default="")
    out["line"] = pd.to_numeric(_coalesce_series(df, ["line"], default=pd.NA), errors="coerce")
    out["over_price"] = pd.to_numeric(_coalesce_series(df, ["over_price"], default=pd.NA), errors="coerce")
    out["under_price"] = pd.to_numeric(_coalesce_series(df, ["under_price"], default=pd.NA), errors="coerce")
    out["snapshot_ts"] = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    return out


def _flatten_team_lines_payload(payload: dict[str, Any], *, fallback_ts: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    lines = ((payload or {}).get("lines") or {}) if isinstance(payload, dict) else {}
    snapshot_ts = str((payload or {}).get("fetched_at") or fallback_ts)
    for event_key, event_payload in lines.items():
        event_data = event_payload or {}
        moneyline = event_data.get("moneyline") or {}
        for side in ("home", "away"):
            price = moneyline.get(side)
            if price is not None:
                rows.append({
                    "event_key": event_key,
                    "market": "moneyline",
                    "selection": side,
                    "line": pd.NA,
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
        total_runs = event_data.get("total_runs") or {}
        if total_runs:
            for side in ("over", "under"):
                price = total_runs.get(side)
                if price is not None:
                    rows.append({
                        "event_key": event_key,
                        "market": "total",
                        "selection": side,
                        "line": total_runs.get("line"),
                        "price": price,
                        "snapshot_ts": snapshot_ts,
                    })
        run_line = event_data.get("run_line") or {}
        if run_line:
            rows.append({
                "event_key": event_key,
                "market": "spread",
                "selection": "home",
                "line": run_line.get("home"),
                "price": pd.NA,
                "snapshot_ts": snapshot_ts,
            })
    return pd.DataFrame(rows)


def _flatten_mlb_game_lines(path: Path) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for game in payload.get("games") or []:
        event_key = f"{game.get('away_team', '')} @ {game.get('home_team', '')}".strip()
        segments = ((game.get("markets") or {}).get("segments") or {"full": game.get("markets") or {}})
        for segment_name, segment_payload in segments.items():
            if not isinstance(segment_payload, dict):
                continue
            h2h = segment_payload.get("h2h") or {}
            for side in ("home", "away"):
                odds_key = f"{side}_odds"
                if odds_key in h2h:
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "moneyline",
                        "selection": side,
                        "line": pd.NA,
                        "price": h2h.get(odds_key),
                        "snapshot_ts": snapshot_ts,
                    })
            spreads = segment_payload.get("spreads") or {}
            if spreads:
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_home",
                    "selection": "home",
                    "line": spreads.get("home_line"),
                    "price": spreads.get("home_odds"),
                    "snapshot_ts": snapshot_ts,
                })
                rows.append({
                    "event_key": event_key,
                    "segment": segment_name,
                    "market": "spread_away",
                    "selection": "away",
                    "line": spreads.get("away_line"),
                    "price": spreads.get("away_odds"),
                    "snapshot_ts": snapshot_ts,
                })
            totals = segment_payload.get("totals") or {}
            if totals:
                for side in ("over", "under"):
                    rows.append({
                        "event_key": event_key,
                        "segment": segment_name,
                        "market": "total",
                        "selection": side,
                        "line": totals.get("line"),
                        "price": totals.get(f"{side}_odds"),
                        "snapshot_ts": snapshot_ts,
                    })
    return pd.DataFrame(rows)


def _flatten_mlb_props(path: Path, root_key: str) -> pd.DataFrame:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    snapshot_ts = str(payload.get("retrieved_at") or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat())
    for player_name, markets in (payload.get(root_key) or {}).items():
        for market_name, market_payload in (markets or {}).items():
            if not isinstance(market_payload, dict):
                continue
            for side in ("over", "under"):
                price = market_payload.get(f"{side}_odds")
                if price is None:
                    continue
                rows.append({
                    "player_name": player_name,
                    "market": market_name,
                    "selection": side,
                    "line": market_payload.get("line"),
                    "price": price,
                    "snapshot_ts": snapshot_ts,
                })
    return pd.DataFrame(rows)


def _flatten_basketball_game_cards(path: Path) -> pd.DataFrame:
    """game_cards_{date}.csv is one row per GAME with all 3 game markets as
    columns (home_ml/away_ml, home_spread/away_spread, total) -- unlike
    every other odds snapshot this file's generic per-row parser handles
    (one row = one market), so each source row melts into up to 3 output
    rows here, one per market, matching MLB's h2h/spreads/totals vocabulary
    and entity=home_team convention so the same downstream matching logic
    (_odds_history_market_key, board-side team-name hydration) works
    unchanged for basketball.
    """
    df = _read_csv(path)
    if df.empty:
        return df
    fallback_ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    snapshot_ts = _to_snapshot_ts(df, fallback_ts=fallback_ts)
    rows: list[dict[str, Any]] = []
    def _clean_str(value: Any) -> str:
        # A blank CSV cell reads back from pandas as float NaN, not None/""
        # -- str(nan) is the truthy string "nan", which would otherwise
        # silently pass through as a real (wrong) team name.
        if value is None or (isinstance(value, float) and value != value):
            return ""
        return str(value).strip()

    for index, record in enumerate(df.to_dict(orient="records")):
        home_team = _clean_str(record.get("home_team"))
        away_team = _clean_str(record.get("visitor_team")) or _clean_str(record.get("away_team"))
        if not home_team or not away_team:
            continue
        row_snapshot_ts = str(snapshot_ts.iloc[index]) if index < len(snapshot_ts) else fallback_ts
        base = {
            "event_id": record.get("game_id"),
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": record.get("commence_time"),
            "entity": home_team,
            "bookmaker": str(record.get("bookmaker") or "").strip() or "oddsapi_consensus",
            "snapshot_ts": row_snapshot_ts,
        }
        home_ml = _line_number(record.get("home_ml"))
        if home_ml is not None:
            rows.append({**base, "market": "h2h", "market_type": "h2h", "line": home_ml, "home_odds": home_ml, "away_odds": _line_number(record.get("away_ml"))})
        home_spread = _line_number(record.get("home_spread"))
        if home_spread is not None:
            rows.append({**base, "market": "spreads", "market_type": "spreads", "line": home_spread, "home_line": home_spread, "away_line": _line_number(record.get("away_spread"))})
        total = _line_number(record.get("total"))
        if total is not None:
            rows.append({**base, "market": "totals", "market_type": "totals", "line": total})
    return pd.DataFrame(rows)


def _sync_csv_tracking(*, tracking_root: Path, prefix: str, scope: str, snapshot_df: pd.DataFrame, key_cols: list[str], line_col: str, price_cols: list[str], label_cols: list[str] | None = None) -> dict[str, Any]:
    return _persist_tracking_snapshot(
        tracking_root=tracking_root,
        prefix=prefix,
        scope=scope,
        snapshot_df=snapshot_df,
        key_cols=key_cols,
        line_col=line_col,
        price_cols=price_cols,
        label_cols=label_cols,
    )


def _infer_nfl_week_scope(source_root: Path) -> tuple[str, Path | None]:
    current_week_path = _choose_existing([source_root / "current_week.json", source_root / "source_artifacts" / "current_week.json"])
    if current_week_path is not None and current_week_path.exists():
        payload = _read_json(current_week_path)
        if isinstance(payload, dict):
            season = payload.get("season")
            week = payload.get("week")
            if season and week:
                path = _choose_existing([
                    source_root / f"oddsapi_player_props_{season}_wk{week}.csv",
                    source_root / "source_artifacts" / f"oddsapi_player_props_{season}_wk{week}.csv",
                ])
                return f"{season}_wk{week}", path
    candidates = sorted(
        list(source_root.glob("oddsapi_player_props_*.csv")) + list((source_root / "source_artifacts").glob("oddsapi_player_props_*.csv")),
        key=lambda candidate: candidate.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        stem = candidates[0].stem.replace("oddsapi_player_props_", "")
        return stem, candidates[0]
    return "unknown", None


def sync_sport_post_refresh_tracking(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    slug = str(sport or "").strip().lower()
    _trace_log("before_sync_sport_post_refresh_tracking", sport=slug, source_root=str(source_root), date=date_str)
    if slug in {"nba", "wnba"}:
        _trace_log("before_sync_basketball_props_tracking", sport=slug, source_root=str(source_root), date=date_str)
        results = sync_basketball_props_tracking_for_source_root(sport=slug, source_root=source_root, date_str=date_str)
        _trace_log("after_sync_basketball_props_tracking", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results.get("ok")))
        if bool(results.get("ok")):
            _trace_log("before_refresh_impacted_recommendations", sport=slug, source_root=str(source_root), date=date_str)
            results["artifacts"] = dict(results.get("artifacts") or {})
            results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
                sport=slug,
                source_root=source_root,
                date_str=date_str,
                tracking_meta=results,
            )
            _trace_log("after_refresh_impacted_recommendations", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results["artifacts"]["recommendations_refresh"].get("ok")))
            _trace_log("before_sync_odds_history", sport=slug, source_root=str(source_root), date=date_str)
            results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
            _trace_log("after_sync_odds_history", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results["artifacts"]["odds_history"].get("ok")))
        _trace_log("after_sync_sport_post_refresh_tracking", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results.get("ok")))
        return results

    tracking_root = source_root / "tracking"
    results: dict[str, Any] = {"ok": True, "sport": slug, "date": date_str, "tracking_root": str(tracking_root), "artifacts": {}}

    if slug == "nhl":
        props_path = source_root / "data" / "props" / "player_props_lines" / f"date={date_str}" / "oddsapi.csv"
        team_path = source_root / "data" / "odds" / "team" / f"date={date_str}" / "oddsapi.csv"
        props_df = _build_nhl_props_snapshot(props_path)
        team_df = _build_ncaab_snapshot(team_path)
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_player_props",
            scope=date_str,
            snapshot_df=props_df,
            key_cols=["event_key", "player_key", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
            label_cols=["player_name"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nhl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "nfl":
        scope, props_path = _infer_nfl_week_scope(source_root)
        props_df = _build_nfl_props_snapshot(props_path) if props_path is not None else pd.DataFrame()
        team_candidates = sorted(
            list(source_root.glob("real_betting_lines_*.json")) + list((source_root / "source_artifacts").glob("real_betting_lines_*.json")),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        team_df = _flatten_team_lines_payload(_read_json(team_candidates[0]), fallback_ts=_utc_now()) if team_candidates else pd.DataFrame()
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_player_props",
            scope=scope,
            snapshot_df=props_df,
            key_cols=["event_key", "player_name", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
        )
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_nfl_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "mlb":
        snapshot_root = source_root / "source_artifacts" / "data" / "daily" / "snapshots" / date_str
        if not snapshot_root.exists():
            snapshot_root = source_root / "data" / "daily" / "snapshots" / date_str
        date_slug = date_str.replace("-", "_")
        game_df = _flatten_mlb_game_lines(snapshot_root / f"oddsapi_game_lines_{date_slug}.json")
        hitter_df = _flatten_mlb_props(snapshot_root / f"oddsapi_hitter_props_{date_slug}.json", "hitter_props")
        pitcher_df = _flatten_mlb_props(snapshot_root / f"oddsapi_pitcher_props_{date_slug}.json", "pitcher_props")
        _trace_log("before_sync_csv_tracking_game_lines", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_game_lines", scope=date_str, rows=int(len(game_df)), snapshot_root=str(snapshot_root))
        results["artifacts"]["game_lines"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_game_lines",
            scope=date_str,
            snapshot_df=game_df,
            key_cols=["event_key", "segment", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        _trace_log("after_sync_csv_tracking_game_lines", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_game_lines", scope=date_str, rows=int(len(game_df)), result_ok=bool(results["artifacts"]["game_lines"].get("ok")))
        _trace_log("before_sync_csv_tracking_hitter_props", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_hitter_props", scope=date_str, rows=int(len(hitter_df)), snapshot_root=str(snapshot_root))
        results["artifacts"]["hitter_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_hitter_props",
            scope=date_str,
            snapshot_df=hitter_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        _trace_log("after_sync_csv_tracking_hitter_props", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_hitter_props", scope=date_str, rows=int(len(hitter_df)), result_ok=bool(results["artifacts"]["hitter_props"].get("ok")))
        _trace_log("before_sync_csv_tracking_pitcher_props", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_pitcher_props", scope=date_str, rows=int(len(pitcher_df)), snapshot_root=str(snapshot_root))
        results["artifacts"]["pitcher_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_mlb_pitcher_props",
            scope=date_str,
            snapshot_df=pitcher_df,
            key_cols=["player_name", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        _trace_log("after_sync_csv_tracking_pitcher_props", sport=slug, tracking_root=str(tracking_root), prefix="odds_mlb_pitcher_props", scope=date_str, rows=int(len(pitcher_df)), result_ok=bool(results["artifacts"]["pitcher_props"].get("ok")))
        _trace_log("before_refresh_impacted_recommendations", sport=slug, source_root=str(source_root), date=date_str)
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        _trace_log("after_refresh_impacted_recommendations", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results["artifacts"]["recommendations_refresh"].get("ok")))
        _trace_log("before_sync_odds_history", sport=slug, source_root=str(source_root), date=date_str)
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        _trace_log("after_sync_odds_history", sport=slug, source_root=str(source_root), date=date_str, ok=bool(results["artifacts"]["odds_history"].get("ok")))
        return results

    if slug == "ncaab":
        odds_path = source_root / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        if not odds_path.exists():
            odds_path = source_root / "data" / "ncaab_source" / "raw_outputs" / "by_date" / date_str / f"odds_{date_str}.csv"
        team_df = _build_ncaab_snapshot(odds_path)
        results["artifacts"]["team_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_ncaab_team_odds",
            scope=date_str,
            snapshot_df=team_df,
            key_cols=["event_key", "book", "market", "selection"],
            line_col="line",
            price_cols=["price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "ncaaf":
        artifact_root = source_root / "source_artifacts"
        latest_predicted = sorted(artifact_root.glob("college_football_schedule_*_predicted_totals_enhanced*.csv"), key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        manifest = {
            "sport": slug,
            "date": date_str,
            "generated_at": _utc_now(),
            "latest_predicted_totals": str(latest_predicted[0]) if latest_predicted else None,
            "predicted_totals_files": [str(path) for path in latest_predicted[:10]],
            "notes": "NCAAF currently mirrors schedule-enhanced totals snapshots rather than per-market odds rows; this manifest keeps the central post-refresh contract owned by Syndicate until a normalized lines snapshot is added.",
        }
        manifest_path = tracking_root / f"odds_ncaaf_source_manifest_{date_str}.json"
        _write_json(manifest_path, manifest)
        results["artifacts"]["source_manifest"] = {
            "ok": True,
            "skipped": False,
            "manifest_path": str(manifest_path),
            "predicted_totals_files": len(latest_predicted),
        }
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    if slug == "soccer":
        game_odds_df = _build_soccer_game_odds_snapshot(source_root)
        results["artifacts"]["game_odds"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_soccer_game_odds",
            scope=date_str,
            snapshot_df=game_odds_df,
            key_cols=["event_id", "market", "side", "book"],
            line_col="line",
            price_cols=["price"],
        )
        props_df = _build_soccer_props_snapshot(source_root, date_str)
        results["artifacts"]["player_props"] = _sync_csv_tracking(
            tracking_root=tracking_root,
            prefix="odds_soccer_player_props",
            scope=date_str,
            snapshot_df=props_df,
            key_cols=["event_id", "player", "market", "book"],
            line_col="line",
            price_cols=["over_price", "under_price"],
        )
        results["artifacts"]["recommendations_refresh"] = refresh_impacted_recommendations_for_tracking(
            sport=slug,
            source_root=source_root,
            date_str=date_str,
            tracking_meta=results,
        )
        results["artifacts"]["odds_history"] = _sync_odds_history_for_refresh(sport=slug, source_root=source_root, date_str=date_str)
        return results

    return {"ok": False, "sport": slug, "date": date_str, "error": f"unsupported_sport:{slug}"}


def sync_post_refresh_tracking_for_source_root(*, sport: str, source_root: Path, date_str: str) -> dict[str, Any]:
    return sync_sport_post_refresh_tracking(sport=sport, source_root=source_root, date_str=date_str)