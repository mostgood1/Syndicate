from __future__ import annotations

import json
import os
import uuid
from collections import deque
from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from syndicate.features.shared.market_id import attach_market_id
from syndicate.features.shared.odds_control_plane import load_odds_history_payload_for_sport
from syndicate.features.shared.odds_control_plane import odds_history_lookback_shard_keys
from syndicate.features.shared.odds_control_plane import resolve_current_shard_key
from syndicate.features.shared.refresh_state_store import data_root
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.shared.timezone import central_today


_ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT = 1

# Per-day cap on how many jsonl rows _load_jsonl_rows keeps in memory. Without
# this, a day's odds-event log (appended to on every market movement, all day,
# every day the app has been live) gets read back in full -- and
# load_recent_odds_events multiplies that by a 7-day lookback, with no caching
# between calls. Confirmed in production: a single call surfaced a retained
# list of 1,046,551 dicts and spiked the live-odds-worker's own RSS from
# ~100MB to ~1.86GB in one tick. Rows are append-ordered, so keeping the most
# recent N preserves exactly the "recent market history" this data is for.
_MAX_JSONL_ROWS_PER_FILE = 2000

# #76. The cap above bounds what a READ costs; nothing bounded the file, and on
# 2026-07-26 odds_events/2026-07-26.jsonl reached 1,238,217,572 bytes in a
# single day. With a 7-day lookback that is ~8GB of disk at steady state
# against a 50GB volume, and it is also the whole of the "2.7GB memory plateau"
# that #79 chased: reading a 1.24GB file fills the cgroup's page cache, which
# memory.current counts. Measured on refresh-worker after #79 landed: container
# 2842MB with only 381MB owned by any process.
#
# What makes trimming SAFE rather than lossy-in-practice: every consumer of
# this data already discards all but the tail. _load_jsonl_rows streams into a
# deque(maxlen=_MAX_JSONL_ROWS_PER_FILE), and it is the only path that reads
# these files in production (load_recent_odds_events -> _recent_history_rows;
# load_odds_lifecycle_events below has no caller outside tests). So everything
# before the last 2000 rows of a given day is already read by nothing at all.
#
# Retained rows are therefore 10x what any reader can see, so a reader cannot
# be starved by compaction even if the read cap is raised substantially later.
_MAX_PERSISTED_ROWS_PER_FILE = 20000

# Compaction rewrites the file, so it must be rare relative to appends. This is
# the number of bytes a file must GROW before it is compacted again -- not an
# absolute size ceiling, which is what it was first written as.
#
# The absolute version is subtly wrong and a local run caught it: if the
# retained rows are themselves larger than the ceiling, every append lands
# above it, so compaction runs on EVERY append and rewrites the whole retained
# set each time. Measured at 300 compactions for 80,000 appended rows. Today's
# production numbers (20k rows ~= 12MB, against 64MB) would not have tripped
# it, so this would have shipped as a latent CPU sink waiting for a bigger row
# or a raised retention.
#
# Framing it as growth-since-last-compaction makes the cost O(1) compactions
# per this many bytes written, whatever the row size: a day that would have
# reached 1.24GB instead peaks at retained + 64MB and compacts ~19 times.
_COMPACTION_TRIGGER_BYTES = 64 * 1024 * 1024

# Per-path size the file must exceed before its next compaction, set to
# (post-compaction size + trigger) each time one runs. In-process only: losing
# it on restart just means one extra compaction, never a missed one.
_COMPACTION_NEXT_THRESHOLD: dict[str, int] = {}


def _odds_history_shard_lookback() -> int:
    raw = str(os.environ.get("SYNDICATE_ODDS_HISTORY_SHARD_LOOKBACK") or "").strip()
    if not raw:
        return _ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT
    try:
        return max(0, int(raw))
    except Exception:
        return _ODDS_HISTORY_SHARD_LOOKBACK_DEFAULT


def _resolve_shard_key_for_candidate(candidate_row: Mapping[str, Any], *, sport: str | None, shard_key: str | None, end_date: str | None) -> str | None:
    if shard_key:
        return shard_key
    if not sport:
        return None
    candidate_date = str(candidate_row.get("date") or candidate_row.get("game_date") or candidate_row.get("event_date") or "").strip()
    if candidate_date:
        return resolve_current_shard_key(sport, candidate_date[:10])
    if end_date:
        return resolve_current_shard_key(sport, str(end_date)[:10])
    return resolve_current_shard_key(sport, central_today_iso())


def _market_state_from_payload(payload: Mapping[str, Any] | None, *, market_id: str | None) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping) or not market_id:
        return None
    markets = payload.get("markets")
    if not isinstance(markets, Mapping):
        return None
    state = markets.get(market_id) if isinstance(markets.get(market_id), Mapping) else None
    if state is not None:
        return state
    for value in markets.values():
        if isinstance(value, Mapping) and str(value.get("market_id") or "").strip() == market_id:
            return value
    return None


def _resolve_market_state_across_shards(*, sport: str, market_id: str | None, shard_key: str, shard_lookback: int, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any] | None:
    # #75: an ODDS_SHARD_SIZE probe lived here briefly and was removed. It was
    # also misleading -- it only printed for files that exist, so its silence
    # read as "this code never runs" when it actually meant "no shard files".
    # The real cost was the odds_events read in _load_jsonl_rows, not here.
    shard_keys = [shard_key] + odds_history_lookback_shard_keys(sport, shard_key, shard_lookback)
    merged_history: list[dict[str, Any]] = []
    found = False
    for key in shard_keys:
        state = _market_state_from_payload(load_odds_history_payload_for_sport(sport, key, cache=payload_cache), market_id=market_id)
        if state is None:
            continue
        history = state.get("history")
        if isinstance(history, list):
            merged_history.extend(item for item in history if isinstance(item, Mapping))
            found = True
    if not found:
        return None
    return {"history": merged_history}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text == "-":
        return None
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return None


def _coerce_probability(value: Any) -> float | None:
    probability = _coerce_float(value)
    if probability is None:
        return None
    if 0.0 <= probability <= 1.0:
        return probability
    if 1.0 < probability <= 100.0:
        return probability / 100.0
    return None


def _parse_date_token(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for token in (text, text.replace("Z", "")):
        try:
            return datetime.fromisoformat(token).date()
        except Exception:
            pass
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _trace_file_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except Exception:
        return None


def _trace_log(stage: str, **payload: Any) -> None:
    record = {"stage": stage, **payload}
    print(f"[odds_lifecycle] TRACE {json.dumps(record, default=str, sort_keys=True)}", flush=True)


def odds_lifecycle_root() -> Path:
    override = str(os.environ.get("SYNDICATE_ODDS_EVENTS_ROOT") or os.environ.get("SYNDICATE_ODDS_EVENT_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    mounted_root = Path("/mnt/data")
    if mounted_root.exists():
        return mounted_root / "odds_events"
    return data_root() / "odds_events"


def odds_lifecycle_path(date_str: str) -> Path:
    date_token = str(date_str or "").strip()
    if not date_token:
        date_token = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return odds_lifecycle_root() / f"{date_token}.jsonl"


# load_recent_odds_events queries at most a handful of distinct date files per
# call (days_back defaults to 7); this process has been up for days at a time
# in production, so without a bound this cache would itself become another
# unbounded, ever-growing structure. Once full, drop the whole cache rather
# than tracking real LRU.
#
# #75: the sentence that used to end this comment -- "a miss just means one
# full re-read of a file already capped to _MAX_JSONL_ROWS_PER_FILE" -- was
# FALSE, and believing it is most of why the refresh-worker OOM stayed open for
# a day. The cap was applied to the *result*, after read_text() had already
# pulled the whole file into a string, splitlines() had built a list of every
# line, and json.loads had parsed every one of them. The cap bounded what the
# caller got, never what the read cost.
#
# It matters most exactly when it hurts most: on a live slate the odds refresh
# appends to today's file continuously, so the mtime below changes constantly,
# every lookup misses, and the full re-read happens again -- once per game, per
# board build. The read is now streamed and bounded to the same last-N rows.
_JSONL_ROWS_CACHE_MAX_ENTRIES = 32
_JSONL_ROWS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    cache_key = str(path)
    try:
        mtime = path.stat().st_mtime
    except Exception:
        mtime = None
    if mtime is not None:
        cached = _JSONL_ROWS_CACHE.get(cache_key)
        if cached is not None and cached[0] == mtime:
            return cached[1]
    try:
        size_bytes = path.stat().st_size
    except Exception:
        size_bytes = -1
    if size_bytes > 8_000_000:
        print(f"ODDS_JSONL_LARGE path={path} bytes={size_bytes}", flush=True)
    # deque(maxlen=...) keeps the last N parsed rows with the same semantics as
    # the old rows[-N:] slice, but never holds more than N at once.
    bounded: deque[dict[str, Any]] = deque(maxlen=_MAX_JSONL_ROWS_PER_FILE)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                bounded.append(payload)
    rows = list(bounded)
    if mtime is not None:
        # This file only changes when the odds-refresh subprocess appends new
        # lifecycle events -- read-only callers (live lens snapshot building,
        # one call per game/candidate) hit this dozens to hundreds of times
        # per pass with an unchanged file. Without this cache, capping the
        # per-call row count above still leaves every one of those calls
        # re-reading and re-parsing the whole file from disk; CPython's
        # allocator doesn't reliably return that churn to the OS between
        # calls, so RSS ratchets upward across a single pass even though each
        # individual call's retained memory is bounded.
        if len(_JSONL_ROWS_CACHE) >= _JSONL_ROWS_CACHE_MAX_ENTRIES:
            _JSONL_ROWS_CACHE.clear()
        _JSONL_ROWS_CACHE[cache_key] = (mtime, rows)
    return rows


def load_recent_odds_events(*, days_back: int = 7, end_date: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    # #76 backlog. Hooked here as well as on the append path, because the
    # service that HOLDS the backlog is not the one that writes it. Measured
    # 2026-07-27: refresh-worker carries 2.66GB of these logs and emitted zero
    # append traces across 19 minutes -- the odds refresh appends on
    # live-odds-worker, while refresh-worker only reads them through this
    # function. An append-triggered cleanup would never have run on the box
    # that needed it.
    #
    # Safe from a reader: the scan only ever touches PAST-DATE files, which
    # have no writer, and it is rate-limited to once per 30 minutes per
    # process so the hot read path pays a directory listing at most twice an
    # hour.
    _maybe_compact_stale_odds_lifecycle_files()
    lookback = max(int(days_back or 0), 1)
    end_token = _parse_date_token(end_date) or central_today()
    odds_root = root or odds_lifecycle_root()
    rows: list[dict[str, Any]] = []
    for offset in range(lookback):
        current_date = end_token - timedelta(days=offset)
        rows.extend(_load_jsonl_rows(odds_root / f"{current_date.isoformat()}.jsonl"))
    return rows


def _event_aliases(event: Mapping[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in (
        event.get("market_id"),
        event.get("event_id"),
        event.get("game_id"),
        event.get("gamePk"),
        event.get("game_pk"),
        event.get("player_id"),
        event.get("athlete_id"),
        event.get("subject_key"),
        event.get("market_key"),
    ):
        text = str(key or "").strip()
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def build_recent_market_history_index(events: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        payload = dict(event)
        market_id = str(payload.get("market_id") or "").strip() or _candidate_market_id(payload, sport=str(payload.get("sport") or payload.get("sport_slug") or "").strip().lower() or None)
        aliases = _event_aliases(payload)
        if market_id and market_id not in aliases:
            aliases.insert(0, market_id)
        for alias in aliases:
            index.setdefault(alias, []).append(payload)
    for rows in index.values():
        rows.sort(key=_event_timestamp)
    return index


# #75: caching this index was tried and reverted. It looked like the twin of
# _JSONL_ROWS_CACHE -- build_recent_market_history_index runs once per game,
# copies every event under up to nine aliases and sorts each bucket -- but
# measured against production artifacts it bought nothing (identical peak) and
# cost ~7MB of retained memory holding the index. _MAX_JSONL_ROWS_PER_FILE caps
# this path at 2000 rows/day, so the whole 7-day set is ~14k events and
# rebuilding it 15 times is noise. The uncapped path was the odds-history
# shards; see the payload_cache threading in simulation_adapter.py.
def _subject_text_for_filtering(row: Mapping[str, Any]) -> str:
    # Mirrors _candidate_market_id's own entity fallback chain, plus the
    # schema aliases confirmed live 2026-07-29 for WNBA/NBA's live-lens rows
    # ("player"/"entity" instead of "player_name", never "home"/"away" team
    # names for a prop). Never falls back to team for a prop candidate
    # (matching attach_market_id's own rule) -- a team-level match would
    # silently readmit the exact cross-player collision this filter exists
    # to prevent.
    is_prop = str(row.get("candidate_type") or "").strip().lower() == "prop"
    entity = row.get("entity") or row.get("player_name") or row.get("player")
    if not entity and not is_prop:
        entity = row.get("team") or row.get("team_tri") or row.get("selection")
    return str(entity or "").strip().lower()


def _stat_text_for_filtering(row: Mapping[str, Any]) -> str:
    return str(row.get("stat") or row.get("market_type") or row.get("market") or "").strip().lower()


def _recent_history_rows(candidate: Mapping[str, Any], *, sport: str | None = None, lookback_days: int = 7, end_date: str | None = None) -> list[dict[str, Any]]:
    recent_events = load_recent_odds_events(days_back=lookback_days, end_date=end_date)
    if not recent_events:
        return []
    index = build_recent_market_history_index(recent_events)
    candidate_row = dict(candidate)
    candidate_market_id = _candidate_market_id(candidate_row, sport=sport)
    market_level_aliases = {candidate_market_id, str(candidate_row.get("market_id") or "").strip(), str(candidate_row.get("player_id") or candidate_row.get("athlete_id") or "").strip()}
    candidate_aliases = [candidate_market_id, str(candidate_row.get("market_id") or "").strip(), str(candidate_row.get("event_id") or "").strip(), str(candidate_row.get("game_id") or "").strip(), str(candidate_row.get("gamePk") or candidate_row.get("game_pk") or "").strip(), str(candidate_row.get("player_id") or candidate_row.get("athlete_id") or "").strip()]
    candidate_subject = _subject_text_for_filtering(candidate_row)
    candidate_stat = _stat_text_for_filtering(candidate_row)
    for alias in candidate_aliases:
        if not alias or alias not in index:
            continue
        rows = index[alias]
        if alias in market_level_aliases:
            # candidate_market_id/market_id/player_id already identify a
            # single specific market -- trust it as-is.
            return [dict(row) for row in rows]
        # event_id/game_id/gamePk are shared by EVERY candidate in the same
        # game -- confirmed live 2026-07-29: without this filter, several
        # different players' (and different stats') history all merged into
        # one shared "recent history" whenever the market-level alias above
        # missed, showing the identical wrong opening/latest line for every
        # prop in that game. Only accept rows that are actually about this
        # candidate's own subject (and stat, when both sides have one) --
        # if that yields nothing, keep trying the remaining, even coarser
        # aliases rather than silently returning the unfiltered game-wide set.
        if not candidate_subject:
            return [dict(row) for row in rows]
        filtered = [
            row
            for row in rows
            if _subject_text_for_filtering(row) == candidate_subject
            and (not candidate_stat or not _stat_text_for_filtering(row) or _stat_text_for_filtering(row) == candidate_stat)
        ]
        if filtered:
            return [dict(row) for row in filtered]
    return []


def _compaction_trigger_bytes() -> int:
    raw = str(os.environ.get("SYNDICATE_ODDS_EVENTS_COMPACT_BYTES") or "").strip()
    try:
        value = int(raw) if raw else _COMPACTION_TRIGGER_BYTES
    except ValueError:
        value = _COMPACTION_TRIGGER_BYTES
    # 0 disables compaction entirely; otherwise never trim below what a reader
    # can consume, so a mis-set env var cannot starve the board.
    if value <= 0:
        return 0
    return max(value, 1024 * 1024)


def _compact_odds_lifecycle_file(path: Path) -> None:
    """Trim an odds-events log to its last _MAX_PERSISTED_ROWS_PER_FILE lines.

    #76. Keeps RAW lines rather than parsed rows: nothing here needs to
    understand the payload, and round-tripping through json would both cost
    more and risk changing bytes the reader already accepts.

    Must never raise -- this runs on the odds-refresh write path, and failing
    to compact is merely the status quo, whereas failing the append is a
    refresh outage.

    ⚠️ Concurrency: this is read-then-replace, so an append landing between the
    two loses those lines. Today there is exactly one writer
    (odds_refresh_tracking.append_odds_lifecycle_events) and compaction runs
    inline right after its own append, which makes the window small but not
    zero. That is an acceptable trade for telemetry whose consumers only ever
    read the last 2000 rows -- it would NOT be acceptable if this file ever
    became a system of record. If a second writer appears, this needs a lock.
    """
    try:
        original_size = path.stat().st_size
    except OSError:
        return
    kept: deque[str] = deque(maxlen=_MAX_PERSISTED_ROWS_PER_FILE)
    total_lines = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    total_lines += 1
                    kept.append(line if line.endswith("\n") else line + "\n")
    except OSError as exc:
        print(f"ODDS_JSONL_COMPACT_READ_FAILED path={path} error={exc}", flush=True)
        return
    if total_lines <= len(kept):
        # Already at or under the retention target: the file is big because its
        # rows are big, not because there are many. Rewriting would buy nothing.
        # Still push the threshold out, or this repeats on every append.
        _COMPACTION_NEXT_THRESHOLD[str(path)] = original_size + _compaction_trigger_bytes()
        print(
            f"ODDS_JSONL_COMPACT_SKIPPED path={path} bytes={original_size} rows={total_lines}",
            flush=True,
        )
        return
    # Unique temp name per #25: two writers of the same file must not collide
    # on one temp path.
    temp_path = path.parent / f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.compact.tmp"
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.writelines(kept)
        os.replace(temp_path, path)
    except OSError as exc:
        print(f"ODDS_JSONL_COMPACT_WRITE_FAILED path={path} error={exc}", flush=True)
        try:
            if temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        return
    try:
        new_size = path.stat().st_size
    except OSError:
        new_size = -1
    if new_size >= 0:
        _COMPACTION_NEXT_THRESHOLD[str(path)] = new_size + _compaction_trigger_bytes()
    print(
        f"ODDS_JSONL_COMPACTED path={path} before_bytes={original_size} after_bytes={new_size} "
        f"rows_before={total_lines} rows_kept={len(kept)}",
        flush=True,
    )
    # The row cache keys on mtime, and compaction changes both the mtime and
    # the content -- but dropping the entry explicitly means a reader between
    # here and its next stat() cannot serve pre-compaction rows.
    _JSONL_ROWS_CACHE.pop(str(path), None)


# How often a process re-scans for oversized past-date logs. The scan is a
# directory listing plus one stat per file, so this is cheap; the interval
# exists only to keep it off every single append.
_STALE_SCAN_INTERVAL_SECONDS = 1800
_last_stale_scan_epoch = 0.0


def compact_stale_odds_lifecycle_files(*, root: Path | None = None, today: date | None = None) -> int:
    """Trim PAST-DATE odds-event logs that are already oversized.

    #76 backlog. Compaction on the append path only ever touches the file
    currently being written, so it bounds today's log and leaves every earlier
    one at whatever size it had reached. Measured on refresh-worker
    2026-07-27, all predating the append-path fix:

        07-21  46.7MB   07-24  315.7MB
        07-22  56.9MB   07-25  512.5MB
        07-23  16.5MB   07-26 1712.5MB

    ~948MB of that is in CLOSED files, and `load_recent_odds_events` still
    reads all of them every cycle through its 7-day lookback, so they keep
    filling the page cache that #79 showed `memory.current` counting.

    Past-date files have no writer -- the odds refresh only ever appends to
    the current slate date -- so trimming them carries none of the
    read-then-replace race the live file does.

    Note this is a no-op in steady state: from now on each day's log is
    compacted repeatedly *during* its own day and rolls over already small.
    It exists to clear the backlog, and to catch a file that went stale while
    large (compaction disabled, a long outage).

    Deliberately trims rather than deletes. Removing whole files beyond the
    lookback window would reclaim marginally more and is the other option
    recorded in #76, but this recovers ~94% of it without destroying anything.
    """
    odds_root = root or odds_lifecycle_root()
    reference = today or central_today()
    trigger = _compaction_trigger_bytes()
    if not trigger:
        return 0
    compacted = 0
    try:
        candidates = sorted(odds_root.glob("*.jsonl"))
    except OSError:
        return 0
    for path in candidates:
        file_date = _parse_date_token(path.stem)
        # Unparseable stem: leave it alone rather than guess. Today's and any
        # future-dated file may have a writer and is the append path's job.
        if file_date is None or file_date >= reference:
            continue
        try:
            if path.stat().st_size <= trigger:
                continue
        except OSError:
            continue
        _compact_odds_lifecycle_file(path)
        compacted += 1
    if compacted:
        print(f"ODDS_JSONL_STALE_SCAN compacted={compacted} root={odds_root}", flush=True)
    return compacted


def _maybe_compact_stale_odds_lifecycle_files() -> None:
    global _last_stale_scan_epoch
    now = datetime.now(timezone.utc).timestamp()
    if now - _last_stale_scan_epoch < _STALE_SCAN_INTERVAL_SECONDS:
        return
    _last_stale_scan_epoch = now
    try:
        compact_stale_odds_lifecycle_files()
    except Exception as exc:  # pragma: no cover - must never break the write path
        print(f"ODDS_JSONL_STALE_SCAN_FAILED error={exc}", flush=True)


def append_odds_lifecycle_events(date_str: str, events: Sequence[Mapping[str, Any]]) -> Path | None:
    records = [json.dumps(dict(event), ensure_ascii=True, separators=(",", ":")) for event in events if isinstance(event, Mapping)]
    if not records:
        return None
    path = odds_lifecycle_path(date_str)
    started = datetime.now(timezone.utc)
    _trace_log("before_append_odds_lifecycle_events", path=str(path), rows=len(records), size_bytes=_trace_file_size(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record)
            handle.write("\n")
    # #76. Checked after the append, on a plain stat(), so the common case
    # costs one syscall. Deliberately not raising out of here: an append that
    # succeeded is the important part, and a failed compaction just leaves the
    # file as it would have been anyway.
    trigger_bytes = _compaction_trigger_bytes()
    if trigger_bytes:
        try:
            threshold = _COMPACTION_NEXT_THRESHOLD.get(str(path), trigger_bytes)
            if path.stat().st_size > threshold:
                _compact_odds_lifecycle_file(path)
        except OSError:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            print(f"ODDS_JSONL_COMPACT_UNEXPECTED path={path} error={exc}", flush=True)
        # Past-date logs have no writer, so nothing else will ever shrink them
        # (#76 backlog). Rate-limited internally; a no-op in steady state.
        _maybe_compact_stale_odds_lifecycle_files()
    elapsed_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 3)
    _trace_log("after_append_odds_lifecycle_events", path=str(path), rows=len(records), size_bytes=_trace_file_size(path), elapsed_ms=elapsed_ms)
    return path


def load_odds_lifecycle_events(date_str: str) -> list[dict[str, Any]]:
    path = odds_lifecycle_path(date_str)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def summarize_odds_lifecycle_events(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {"total_events": 0, "open_events": 0, "update_events": 0, "live_events": 0, "close_events": 0, "final_events": 0}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        summary["total_events"] += 1
        event_type = str(event.get("event_type") or "").strip().lower()
        if event_type == "open":
            summary["open_events"] += 1
        elif event_type == "update":
            summary["update_events"] += 1
        elif event_type == "live":
            summary["live_events"] += 1
        elif event_type == "close":
            summary["close_events"] += 1
        elif event_type == "final":
            summary["final_events"] += 1
    return summary


def _candidate_market_id(candidate: Mapping[str, Any], *, sport: str | None = None) -> str | None:
    event_id = _first_present(candidate.get("event_id"), candidate.get("game_id"), candidate.get("game_pk"), candidate.get("gamePk"), candidate.get("matchup"), candidate.get("subject_key"), candidate.get("name"))
    market_type = _first_present(candidate.get("market_type"), candidate.get("market"), candidate.get("market_label"), candidate.get("market_key"), candidate.get("selection"), candidate.get("period"))
    entity = _first_present(candidate.get("entity"), candidate.get("player_name"), candidate.get("player"), candidate.get("team"), candidate.get("selection"), candidate.get("name"))
    line = _first_present(candidate.get("line"), candidate.get("point"), candidate.get("spread"), candidate.get("total"), candidate.get("projected"))
    attached = attach_market_id(dict(candidate), sport=sport or candidate.get("sport") or candidate.get("sport_slug") or "sport", event_id=event_id, market_type=market_type, entity=entity, line=line)
    return str(attached.get("market_id") or "").strip() or None


def _event_timestamp(event: Mapping[str, Any]) -> tuple[int, str]:
    text = str(event.get("timestamp") or event.get("captured_at") or event.get("last_updated") or "").strip()
    if not text:
        return (0, "")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat()
    except Exception:
        parsed = text
    return (1, parsed)


def _event_line(event: Mapping[str, Any]) -> float | None:
    return _coerce_float(event.get("line") or event.get("current_line") or event.get("latest_line") or event.get("value"))


def _event_price(event: Mapping[str, Any]) -> float | None:
    return _coerce_float(event.get("price") or event.get("odds") or event.get("last_odds") or event.get("current_odds"))


def _history_rows(candidate: Mapping[str, Any] | None, market_state: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if isinstance(market_state, Mapping):
        history = market_state.get("history")
        if isinstance(history, list) and history:
            return [dict(item) for item in history if isinstance(item, Mapping)]
    if isinstance(candidate, Mapping):
        market_history = candidate.get("market_history")
        if isinstance(market_history, list) and market_history:
            return [dict(item) for item in market_history if isinstance(item, Mapping)]
        odds_history = candidate.get("odds_history")
        if isinstance(odds_history, Mapping):
            history = odds_history.get("history")
            if isinstance(history, list) and history:
                return [dict(item) for item in history if isinstance(item, Mapping)]
    return []


def _history_change_count(rows: Sequence[Mapping[str, Any]]) -> int:
    changes = 0
    previous_line = None
    previous_price = None
    for row in rows:
        current_line = _event_line(row)
        current_price = _event_price(row)
        if previous_line is not None and current_line is not None and current_line != previous_line:
            changes += 1
        elif previous_price is not None and current_price is not None and current_price != previous_price:
            changes += 1
        previous_line = current_line if current_line is not None else previous_line
        previous_price = current_price if current_price is not None else previous_price
    return changes


def _selection_direction(candidate: Mapping[str, Any]) -> float | None:
    pick = str(candidate.get("pick") or candidate.get("selection") or candidate.get("name") or "").strip().lower()
    if "under" in pick:
        return -1.0
    if "over" in pick or "yes" in pick:
        return 1.0
    return None


def _implied_probability_from_american_odds(value: Any) -> float | None:
    odds = _coerce_float(value)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    absolute = abs(odds)
    return absolute / (absolute + 100.0)


def build_market_history_view(candidate: Mapping[str, Any] | None = None, *, sport: str | None = None, market_state: Mapping[str, Any] | None = None, lookback_days: int = 7, end_date: str | None = None, shard_key: str | None = None, shard_lookback: int | None = None, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    candidate_row = dict(candidate) if isinstance(candidate, Mapping) else {}
    resolved_sport = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    market_id = _candidate_market_id(candidate_row, sport=resolved_sport)
    if market_state is None and resolved_sport:
        resolved_shard_key = _resolve_shard_key_for_candidate(candidate_row, sport=resolved_sport, shard_key=shard_key, end_date=end_date)
        if resolved_shard_key:
            market_state = _resolve_market_state_across_shards(
                sport=resolved_sport,
                market_id=market_id,
                shard_key=resolved_shard_key,
                shard_lookback=shard_lookback if shard_lookback is not None else _odds_history_shard_lookback(),
                payload_cache=payload_cache,
            )

    if market_state is None:
        recent_rows = _recent_history_rows(candidate_row, sport=resolved_sport, lookback_days=lookback_days, end_date=end_date)
        if recent_rows:
            market_state = {"history": recent_rows}

    history_rows = _history_rows(candidate_row, market_state)
    if not history_rows:
        opening_line = _coerce_float(candidate_row.get("line"))
        opening_price = _coerce_float(candidate_row.get("odds"))
        return {
            "market_id": market_id,
            "event_id": candidate_row.get("event_id") or candidate_row.get("game_id") or candidate_row.get("matchup"),
            "opening_line": opening_line,
            "latest_line": opening_line,
            "closing_line": opening_line,
            "opening_price": opening_price,
            "latest_price": opening_price,
            "closing_price": opening_price,
            "movement_delta": None,
            "movement_direction": "flat",
            "movement_velocity": None,
            "price_delta": None,
            "price_direction": "flat",
            "volatility": 0,
            "clv": None,
            "closing_edge": None,
            "is_steam_move": False,
            "history_points": 0,
            "movement_events": 0,
            "live_events": 0,
            "close_events": 0,
            "final_events": 0,
            "is_live": bool(candidate_row.get("is_live")),
            "selection_direction": _selection_direction(candidate_row),
            "edge_direction": 1.0 if (_coerce_probability(candidate_row.get("fair_probability")) or 0.0) >= (_coerce_probability(candidate_row.get("market_probability")) or 0.0) else -1.0,
            "movement_signal": None,
            "clv_signal": None,
            "raw_history": [],
        }

    ordered_history = sorted(history_rows, key=_event_timestamp)
    opening_entry = ordered_history[0]
    latest_entry = ordered_history[-1]
    closing_entry = next((entry for entry in reversed(ordered_history) if str(entry.get("event_type") or "").strip().lower() in {"close", "final"}), latest_entry)

    opening_line = _event_line(opening_entry)
    latest_line = _event_line(latest_entry)
    closing_line = _event_line(closing_entry)
    opening_price = _event_price(opening_entry)
    latest_price = _event_price(latest_entry)
    closing_price = _event_price(closing_entry)

    movement_delta = None
    if opening_line is not None and latest_line is not None:
        movement_delta = round(latest_line - opening_line, 4)

    movement_direction = "flat"
    if movement_delta is not None:
        if movement_delta > 0:
            movement_direction = "positive"
        elif movement_delta < 0:
            movement_direction = "negative"

    # Line and price/odds are two independent dimensions a market can move
    # on -- a total's number (3.5 -> 4.5) and its juice (-110 -> -120) can
    # each shift on their own. Only the line side had a delta/direction
    # tracked here; price had opening/latest values recorded but no delta
    # ever computed from them, so callers had no way to report "odds moved
    # by X" separately from "the line moved by X". Mirrors movement_delta/
    # movement_direction's pattern exactly.
    price_delta = None
    if opening_price is not None and latest_price is not None:
        price_delta = round(latest_price - opening_price, 4)

    price_direction = "flat"
    if price_delta is not None:
        if price_delta > 0:
            price_direction = "positive"
        elif price_delta < 0:
            price_direction = "negative"

    movement_velocity = None
    if movement_delta is not None:
        try:
            start = datetime.fromisoformat(_event_timestamp(opening_entry)[1].replace("Z", "+00:00")).astimezone(timezone.utc)
            end = datetime.fromisoformat(_event_timestamp(latest_entry)[1].replace("Z", "+00:00")).astimezone(timezone.utc)
            elapsed_hours = max((end - start).total_seconds() / 3600.0, 0.0)
            if elapsed_hours > 0:
                movement_velocity = round(movement_delta / elapsed_hours, 4)
        except Exception:
            movement_velocity = None

    volatility = _history_change_count(ordered_history)
    candidate_line = _coerce_float(candidate_row.get("line") or candidate_row.get("current_line") or candidate_row.get("projected"))
    candidate_price = _coerce_float(candidate_row.get("odds") or candidate_row.get("current_odds") or candidate_row.get("market_probability"))
    candidate_probability = _coerce_probability(candidate_row.get("market_probability")) or _coerce_probability(candidate_row.get("implied_probability")) or _implied_probability_from_american_odds(candidate_price)
    closing_probability = _implied_probability_from_american_odds(closing_price)

    clv = None
    if candidate_line is not None and closing_line is not None:
        clv = round(candidate_line - closing_line, 4)

    closing_edge = None
    if candidate_probability is not None and closing_probability is not None:
        closing_edge = round(candidate_probability - closing_probability, 4)

    selection_direction = _selection_direction(candidate_row)
    edge_direction = 1.0 if (_coerce_probability(candidate_row.get("fair_probability")) or 0.0) >= (_coerce_probability(candidate_row.get("market_probability")) or 0.0) else -1.0
    movement_signal = None
    if movement_delta is not None:
        direction_factor = selection_direction if selection_direction in {1.0, -1.0} else 0.0
        scale = max(1.0, abs(opening_line or latest_line or candidate_line or 1.0))
        if direction_factor != 0.0:
            movement_signal = round((-direction_factor * movement_delta * edge_direction) / scale, 4)
        else:
            movement_signal = round((movement_delta / scale) * edge_direction, 4)

    clv_signal = None
    if clv is not None:
        scale = max(0.5, abs(opening_line or latest_line or candidate_line or 1.0))
        if selection_direction in {1.0, -1.0}:
            clv_signal = round((-selection_direction * clv) / scale, 4)
        else:
            clv_signal = round(-clv / scale, 4)
    elif closing_edge is not None:
        clv_signal = round(-closing_edge * 5.0, 4)

    live_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "live" or bool(entry.get("is_live")))
    close_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "close")
    final_events = sum(1 for entry in ordered_history if str(entry.get("event_type") or "").strip().lower() == "final")
    steam_window = abs(movement_delta or 0.0) >= 0.5 and volatility >= 1 and (movement_velocity is None or abs(movement_velocity) >= 0.05)

    return {
        "market_id": market_id,
        "event_id": candidate_row.get("event_id") or candidate_row.get("game_id") or candidate_row.get("matchup"),
        "opening_line": opening_line,
        "latest_line": latest_line,
        "closing_line": closing_line,
        "opening_price": opening_price,
        "latest_price": latest_price,
        "closing_price": closing_price,
        "movement_delta": movement_delta,
        "movement_direction": movement_direction,
        "movement_velocity": movement_velocity,
        "price_delta": price_delta,
        "price_direction": price_direction,
        "volatility": volatility,
        "clv": clv,
        "closing_edge": closing_edge,
        "is_steam_move": steam_window,
        "history_points": len(ordered_history),
        "movement_events": volatility,
        "live_events": live_events,
        "close_events": close_events,
        "final_events": final_events,
        "is_live": bool(candidate_row.get("is_live")) or live_events > 0,
        "selection_direction": selection_direction,
        "edge_direction": edge_direction,
        "movement_signal": movement_signal,
        "clv_signal": clv_signal,
        "raw_history": ordered_history[-10:],
    }


def build_market_features(candidate: Mapping[str, Any], *, sport: str | None = None, market_state: Mapping[str, Any] | None = None, lookback_days: int = 7, end_date: str | None = None, shard_key: str | None = None, shard_lookback: int | None = None, payload_cache: dict[tuple[str, str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    features = build_market_history_view(candidate, sport=sport, market_state=market_state, lookback_days=lookback_days, end_date=end_date, shard_key=shard_key, shard_lookback=shard_lookback, payload_cache=payload_cache)
    candidate_row = dict(candidate)
    features["candidate_line"] = _coerce_float(candidate_row.get("line") or candidate_row.get("current_line") or candidate_row.get("projected"))
    features["candidate_price"] = _coerce_float(candidate_row.get("odds") or candidate_row.get("current_odds") or candidate_row.get("market_probability"))
    features["candidate_probability"] = _coerce_probability(candidate_row.get("market_probability")) or _coerce_probability(candidate_row.get("implied_probability")) or _implied_probability_from_american_odds(features["candidate_price"])
    features["source_sport"] = str(sport or candidate_row.get("sport") or candidate_row.get("sport_slug") or "").strip().lower() or None
    features["lookback_days"] = max(int(lookback_days or 0), 1)
    features["has_recent_history"] = bool(features.get("history_points") or 0)
    return features


def market_feature_summary(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    market_rows = [dict(item) for item in features if isinstance(item, Mapping)]
    if not market_rows:
        return {
            "market_feature_count": 0,
            "movement_delta_mean": None,
            "movement_velocity_mean": None,
            "volatility_mean": None,
            "clv_mean": None,
            "closing_edge_mean": None,
            "edge_retention_mean": None,
            "closing_line_count": 0,
            "market_history_points": 0,
        }

    movement_deltas = [_coerce_float(row.get("movement_delta")) for row in market_rows if _coerce_float(row.get("movement_delta")) is not None]
    movement_velocity = [_coerce_float(row.get("movement_velocity")) for row in market_rows if _coerce_float(row.get("movement_velocity")) is not None]
    volatility = [_coerce_float(row.get("volatility")) for row in market_rows if _coerce_float(row.get("volatility")) is not None]
    clv_values = [_coerce_float(row.get("clv")) for row in market_rows if _coerce_float(row.get("clv")) is not None]
    closing_edges = [_coerce_float(row.get("closing_edge")) for row in market_rows if _coerce_float(row.get("closing_edge")) is not None]
    edge_retention_values: list[float] = []
    for row in market_rows:
        edge = _coerce_float(row.get("edge")) or _coerce_float(row.get("candidate_edge"))
        closing_edge = _coerce_float(row.get("closing_edge"))
        if edge is None or closing_edge is None or edge == 0:
            continue
        edge_retention_values.append(round(closing_edge / edge, 4))

    return {
        "market_feature_count": len(market_rows),
        "movement_delta_mean": round(sum(movement_deltas) / len(movement_deltas), 4) if movement_deltas else None,
        "movement_velocity_mean": round(sum(movement_velocity) / len(movement_velocity), 4) if movement_velocity else None,
        "volatility_mean": round(sum(volatility) / len(volatility), 4) if volatility else None,
        "clv_mean": round(sum(clv_values) / len(clv_values), 4) if clv_values else None,
        "closing_edge_mean": round(sum(closing_edges) / len(closing_edges), 4) if closing_edges else None,
        "edge_retention_mean": round(sum(edge_retention_values) / len(edge_retention_values), 4) if edge_retention_values else None,
        "closing_line_count": len([row for row in market_rows if row.get("closing_line") is not None]),
        "market_history_points": sum(int(row.get("history_points") or 0) for row in market_rows),
    }