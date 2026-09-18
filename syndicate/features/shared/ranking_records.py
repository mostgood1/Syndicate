"""Settled, projected evaluation records for the board's ranking pass.

Lane `board-eval-reader-chunk-ceiling`, design A (2026-09-16).

WHY THIS EXISTS. `pipeline/intelligence_state.py` fed `rank_candidates` from
`intelligence_evaluation.load_recent_evaluation_records(days=14)`, which skips
any daily chunk over ``max_chunk_bytes=64_000_000`` and keeps every WHOLE parsed
record. Production chunks are now 117-417 MB, so 12 of 14 days were skipped
(636 `SKIP_OVERSIZED_LEDGER_CHUNK ... ceiling=64000000` lines on 2026-09-16).
Raising the ceiling is not an option: whole records cost ~4.4 resident bytes per
file byte, ~13 GiB for those 12 days on a 4 GB worker.

WHAT THIS DOES INSTEAD. Every chunk in the window is streamed line by line with
NO per-file byte skip. A line is kept only if it is SETTLED, and only as a
projection of the fields the ranking pass reads. The full record is transient.
A chunk-count and cumulative byte backstop still exist, and anything they
exclude is REPORTED on the log line -- a narrowed sample must say so.

THE CONSUMERS (read, not guessed), all reached from
`recommendation_engine.rank_recommendations` / `filter_candidates`:

* `recommendation_engine._record_sport`     record.sport, recommendation.sport/sport_slug,
                                              response.sport, query.sport
* `intelligence_evaluation._record_sport`   + artifact_metadata.sport (compute_metrics' sport filter)
* `recommendation_engine._record_market`    recommendation.market/market_key/market_label,
                                              record.market, response.market, query.market
* `recommendation_engine._record_policy`    record.decision_strategy,
                                              recommendation/response .decision_strategy/.policy
* `recommendation_engine._settled_outcome`  record.result
* `recommendation_engine._policy_record_features` / `_policy_record_clv`
    source = recommendation OR response OR record (truthiness!):
    source.edge/confidence/model_probability/fair_probability/implied_probability/
    market_fit_score/odds/price/closing_price; record.edge/implied_probability/
    market_fit_score/pnl/stake/odds/price/closing_price
* `recommendation_engine.compare_policies`  record.pnl/stake
* `intelligence_evaluation._latest_by_recommendation_id` record_type, recommendation_id, prediction_id
* `intelligence_evaluation._settled_records/_win_rate/_roi` result, stake, pnl
* `intelligence_evaluation._clv`            recommendation.line/projected/selection_direction/pick/name,
                                              record.line, record.closing_line
* `intelligence_evaluation._price_clv`      recommendation.odds/price, record.odds/price/closing_price
* `intelligence_evaluation._calibration`    record.implied_probability, record.result

SETTLED means what `compute_metrics` counts: `_result_label(result)` in
{win, loss, push, void}. That is a superset of `_settled_outcome` ({win, loss}),
which `compare_policies` applies on top, so no record either consumer counts is
dropped.

WHAT DROPPING PENDING RECORDS CHANGES (and why it is accepted):

1. `compute_metrics()["sample_size"]` is `len(record_rows)` INCLUDING pending
   rows. It surfaces only as `historical_profile.{sport,market}.metrics.sample_size`
   on ranked rows -- a display field. Nothing in the score, the gate
   (`build_reliability_profile` uses `settled_count`), or the policy choice reads
   it.
2. `_latest_by_recommendation_id` keeps the LAST record per identity. A pending
   record that follows a kept settled record with the same identity hides that
   settlement from `compute_metrics`. That case is HANDLED, not accepted: such a
   pending record is kept (projected) so dedup behaves exactly as before, and
   counted as `kept_superseding_pending`. It is rare -- settlement rewrites the
   ledger line in place, and the measured dedup ratio is 0.9979.
3. A pending record that PRECEDES a settled one with the same identity only
   fixed the dict insertion position in that dedup; dropping it moves the
   settled record later in iteration order. Every sum over those rows is
   order-independent for exact values and at worst last-ULP for floats.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from array import array as _array
from datetime import date as _date, datetime, timedelta as _timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared import intelligence_evaluation as _ie

# A 14-day window is 15 inclusive dates (`_dates_in_window` includes both ends),
# which is what `load_recent_evaluation_records(days=14)` also walks.
DEFAULT_MAX_CHUNKS = 15
DEFAULT_MAX_BYTES_PER_CHUNK = 256_000_000
DEFAULT_MAX_TOTAL_BYTES = DEFAULT_MAX_CHUNKS * DEFAULT_MAX_BYTES_PER_CHUNK

SETTLED_RESULTS = frozenset({"win", "loss", "push", "void"})

_SOURCE_FIELDS = (
    # `_policy_record_features` / `_policy_record_clv`
    "edge", "confidence", "model_probability", "fair_probability",
    "implied_probability", "market_fit_score", "odds", "price", "closing_price",
)

_TOP_LEVEL_FIELDS = (
    # dedup: `_latest_by_recommendation_id`
    "record_type", "recommendation_id", "prediction_id",
    # outcome + economics
    "result", "stake", "pnl",
    # CLV (line): `_clv`
    "line", "closing_line",
    # scoping: `_record_sport`, `_record_market`, `_record_policy`
    "sport", "market", "decision_strategy",
    *_SOURCE_FIELDS,
)

_RECOMMENDATION_FIELDS = (
    "sport", "sport_slug",
    "market", "market_key", "market_label",
    "decision_strategy", "policy",
    # `_clv`
    "line", "projected", "selection_direction", "pick", "name",
    *_SOURCE_FIELDS,
)

_RESPONSE_FIELDS = ("sport", "market", "decision_strategy", "policy", *_SOURCE_FIELDS)
_QUERY_FIELDS = ("sport", "market")
_ARTIFACT_METADATA_FIELDS = ("sport",)


def _project_nested(value: Any, keys: "tuple[str, ...]") -> "dict[str, Any] | None":
    """Project a nested mapping, preserving its TRUTHINESS.

    `_policy_record_features` picks `recommendation or response or record`, so a
    non-empty source that happens to carry none of the kept keys must still be
    truthy, or the projection would silently switch the source.
    """
    if not isinstance(value, Mapping) or not value:
        return None
    slim = {key: value[key] for key in keys if key in value}
    if not slim:
        slim["_projected"] = True
    return slim


def project_ranking_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce one ledger record to what the ranking pass reads."""
    if not isinstance(record, Mapping):
        return {}
    slim: dict[str, Any] = {key: record[key] for key in _TOP_LEVEL_FIELDS if key in record}
    for name, keys in (
        ("recommendation", _RECOMMENDATION_FIELDS),
        ("response", _RESPONSE_FIELDS),
        ("query", _QUERY_FIELDS),
        ("artifact_metadata", _ARTIFACT_METADATA_FIELDS),
    ):
        nested = _project_nested(record.get(name), keys)
        if nested is not None:
            slim[name] = nested
    return slim


def is_settled_record(record: Mapping[str, Any]) -> bool:
    return _ie._result_label(record.get("result")) in SETTLED_RESULTS


def _dedup_identity(record: Mapping[str, Any]) -> "tuple[str, str] | None":
    """The key `_latest_by_recommendation_id` dedups on, or None if it never
    collides (portfolio events are dropped there; id-less records get a unique
    fallback key). recommendation_id and prediction_id are separate namespaces."""
    if str(record.get("record_type") or "").strip().lower() == "portfolio_event":
        return None
    recommendation_id = str(record.get("recommendation_id") or "").strip()
    if recommendation_id:
        return ("recommendation_id", recommendation_id)
    prediction_id = str(record.get("prediction_id") or "").strip()
    if prediction_id:
        return ("prediction_id", prediction_id)
    return None


class RankingRecords(list):
    """The loader's result: a plain list of projected records, plus
    ``fingerprint`` -- a digest of the KEPT records' content and order, or None
    when the per-chunk cache is off or the ledger is not chunked.

    `recommendation_engine` keys its derived-aggregate memo on the fingerprint,
    so it must change whenever any kept record does, and it must NOT change
    when only pending (dropped) lines are appended -- today's chunk grows all
    day with those. A fingerprinted list is READ-ONLY by contract: its records
    are the cache's own objects and are handed to the next build too.
    """

    fingerprint: "str | None" = None


# ---------------------------------------------------------------------------
# Per-chunk parse cache. Lane `ranking-records-build-cost` (2026-09-18).
#
# WHY. Every board build re-read all 15 chunks -- 3.37-3.55 GB, ~183k lines --
# to keep ~17k settled records (46 s median per load on NO-SIM builds, full-day
# reading `deploys.md` 2026-09-17 21:50Z). Past chunks almost never change.
#
# WHAT IS CACHED, per chunk path, in THIS process only: what the chunk
# contributes, in file order -- each settled line's projected record and dedup
# identity, and for each PENDING line that carries an identity only a 64-bit
# hash of that identity and the line's byte offset (a pending line is kept only
# when it supersedes a settled one, which production has never seen:
# `kept_superseding_pending=0`; the offset lets that rare case re-read the one
# line). Pending lines without an identity are only counted.
#
# The cross-chunk supersede rule is REPLAYED over the cached entries on every
# call, in the same order the stream would see them, so the output is identical
# to a fresh read -- a chunk that changed earlier in the window still decides
# whether a later chunk's pending line is kept.
#
# HOW A CHUNK IS REVALIDATED (the two ways the ledger is written, read from
# `intelligence_evaluation`):
# * append (`_append_jsonl`, same inode): only the new COMPLETE lines past the
#   cached offset are parsed, after checking that the 4 KiB just before that
#   offset are byte-identical to what was parsed;
# * settlement rewrite (`_replace_ledger_line`: temp file + `os.replace`, a NEW
#   inode): the chunk is re-parsed from byte 0.
# An unterminated last line (a write in flight) is parsed for this call only
# and never cached, so the line is read again once it is complete.
#
# NOT DETECTED: an in-place rewrite on the same inode that keeps the size, the
# mtime and the last 4 KiB before the cached offset. Nothing in the repo writes
# a chunk that way. `SYNDICATE_RANKING_RECORDS_CACHE=0` turns the cache (and
# the fingerprint) off.
# ---------------------------------------------------------------------------
_CACHE_ENV = "SYNDICATE_RANKING_RECORDS_CACHE"
_PROBE_BYTES = 4096
_CHUNK_CACHE_LOCK = threading.Lock()
_CHUNK_CACHE: "dict[str, _ChunkState]" = {}


def ranking_records_cache_enabled() -> bool:
    return str(os.environ.get(_CACHE_ENV, "1")).strip().lower() not in {"0", "false", "off", "no"}


def reset_ranking_records_cache() -> None:
    with _CHUNK_CACHE_LOCK:
        _CHUNK_CACHE.clear()


class _ChunkState:
    __slots__ = (
        "ino", "dev", "size", "mtime_ns", "offset", "probe", "lines_seen", "unparseable",
        "pending_plain", "settled", "pending_hashes", "pending_offsets", "digest",
    )

    def __init__(self, ino: int, dev: int) -> None:
        self.ino = ino
        self.dev = dev
        self.size = -1
        self.mtime_ns = -1
        self.offset = 0  # bytes of COMPLETE lines parsed into this state
        self.probe = b""  # up to _PROBE_BYTES ending at `offset`
        self.lines_seen = 0
        self.unparseable = 0
        self.pending_plain = 0  # pending lines with no dedup identity
        # (pending lines before it in this chunk, identity or None, projected)
        self.settled: "list[tuple[int, tuple[str, str] | None, dict[str, Any]]]" = []
        self.pending_hashes = _array("q")
        self.pending_offsets = _array("q")
        self.digest = hashlib.blake2b(digest_size=16)


def _entry_digest_bytes(identity: Any, record: Mapping[str, Any]) -> bytes:
    return (json.dumps([identity, record], sort_keys=True, default=str, separators=(",", ":")) + "\n").encode("utf-8")


def _classify_line(raw: bytes) -> "tuple[str, Any, Any]":
    """('blank'|'bad'|'settled'|'pending', identity, payload) for one raw line."""
    stripped = raw.strip()
    if not stripped:
        return ("blank", None, None)
    try:
        payload = json.loads(stripped.decode("utf-8", errors="replace"))
    except Exception:
        return ("bad", None, None)
    if not isinstance(payload, dict):
        return ("bad", None, None)
    identity = _dedup_identity(payload)
    return ("settled" if is_settled_record(payload) else "pending", identity, payload)


def _parse_into_state(handle: Any, state: _ChunkState, byte_limit: int) -> "tuple[bytes | None, int]":
    """Parse complete lines from ``state.offset`` up to ``byte_limit`` into
    ``state``. Returns (unterminated tail line within the limit or None, bytes
    read from disk)."""
    handle.seek(state.offset)
    parsed = 0
    consumed = state.offset
    while True:
        raw = handle.readline()
        if not raw:
            return None, parsed
        # Checked BEFORE consuming, so the byte limit is exact (same rule as
        # `_stream_chunked_ledger_records`).
        if consumed + len(raw) > byte_limit:
            return None, parsed
        parsed += len(raw)
        if not raw.endswith(b"\n"):
            return raw, parsed
        line_offset = consumed
        consumed += len(raw)
        kind, identity, payload = _classify_line(raw)
        if kind != "blank":
            state.lines_seen += 1
        if kind == "bad":
            state.unparseable += 1
        elif kind == "settled":
            projected = project_ranking_record(payload)
            state.settled.append((len(state.pending_hashes), identity, projected))
            state.digest.update(_entry_digest_bytes(identity, projected))
        elif kind == "pending":
            if identity is None:
                state.pending_plain += 1
            else:
                state.pending_hashes.append(hash(identity))
                state.pending_offsets.append(line_offset)
        state.offset = consumed
        state.probe = (state.probe + raw)[-_PROBE_BYTES:]


def _chunk_state_for(chunk_path: Path, handle: Any, st: os.stat_result, byte_limit: int, use_cache: bool) -> "tuple[_ChunkState, str]":
    key = str(chunk_path)
    state = _CHUNK_CACHE.get(key) if use_cache else None
    if state is not None and (state.ino, state.dev) == (st.st_ino, st.st_dev) and state.offset <= min(st.st_size, byte_limit):
        if (state.size, state.mtime_ns) == (st.st_size, st.st_mtime_ns):
            return state, "reused"
        probe_start = state.offset - len(state.probe)
        handle.seek(probe_start)
        if handle.read(len(state.probe)) == state.probe:
            return state, "extended"
    return _ChunkState(st.st_ino, st.st_dev), "parsed"


def _read_line_at(chunk_path: Path, offset: int) -> Any:
    try:
        with chunk_path.open("rb") as handle:
            handle.seek(offset)
            kind, identity, payload = _classify_line(handle.readline())
    except OSError:
        return None, None
    return (payload, identity) if kind == "pending" else (None, None)


def load_recent_ranking_records(
    *,
    days: int = 14,
    ledger_path: "Path | str | None" = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    stats: "dict[str, Any] | None" = None,
) -> RankingRecords:
    """Settled, projected records from the last ``days`` of ledger chunks.

    Chunks are SELECTED newest-first under the backstop
    (`_select_ledger_chunks_within_budget`) and yielded in ASCENDING date order,
    file order within a chunk -- the same order `load_recent_evaluation_records`
    produced, so last-wins dedup downstream behaves the same. Returns a list,
    not a generator: `rank_recommendations` iterates it several times.
    """
    started = time.monotonic()
    target_path = Path(ledger_path) if ledger_path is not None else _ie.DEFAULT_LEDGER_PATH
    use_cache = ranking_records_cache_enabled()
    counters: dict[str, Any] = {
        "days": int(days),
        "chunks_read": 0,
        "bytes_read": 0,
        "bytes_parsed": 0,
        "lines_seen": 0,
        "kept": 0,
        "skipped_unsettled": 0,
        "kept_superseding_pending": 0,
        "unparseable": 0,
        "excluded_by_backstop": 0,
        "bytes_excluded_by_backstop": 0,
        "chunks_partial": 0,
        "chunks_reused": 0,
        "chunks_extended": 0,
        "chunks_parsed": 0,
        "dates_read": [],
    }
    records = RankingRecords()
    # Identities of kept SETTLED records only -- bounded by `kept`, not by lines.
    settled_identities: set[tuple[str, str]] = set()

    def _consider(payload: Any) -> None:
        if not isinstance(payload, dict):
            counters["unparseable"] += 1
            return
        identity = _dedup_identity(payload)
        if not is_settled_record(payload):
            if identity is not None and identity in settled_identities:
                # Last-wins dedup downstream would let this pending record hide
                # the settled one; keep it so that still happens (docstring, 2).
                records.append(project_ranking_record(payload))
                counters["kept_superseding_pending"] += 1
                return
            counters["skipped_unsettled"] += 1
            return
        if identity is not None:
            settled_identities.add(identity)
        records.append(project_ranking_record(payload))
        counters["kept"] += 1

    if not _ie._is_chunked_ledger_path(target_path):
        # Flat single-file ledger (tests / legacy). Streamed, same filter, no cache.
        for payload in _ie._stream_record_payloads(ledger_path=target_path):
            counters["lines_seen"] += 1
            _consider(payload)
    else:
        until_dt = _date.fromisoformat(datetime.now(timezone.utc).date().isoformat())
        since_dt = until_dt - _timedelta(days=max(0, int(days)))
        chunk_paths = [
            chunk_path
            for chunk_path in (
                _ie._ledger_chunk_path(target_path, token)
                for token in _ie._dates_in_window(since_dt.isoformat(), until_dt.isoformat())
            )
            if chunk_path.is_file()
        ]
        plan, selection = _ie._select_ledger_chunks_within_budget(
            chunk_paths,
            max_total_bytes=int(max_total_bytes or 0),
            max_chunks=int(max_chunks or 0),
        )
        counters["excluded_by_backstop"] = int(selection.get("chunks_skipped_count") or 0) + int(
            selection.get("chunks_skipped_budget") or 0
        )
        counters["bytes_excluded_by_backstop"] = int(selection.get("bytes_skipped") or 0)
        counters["chunks_partial"] = int(selection.get("chunks_partial") or 0)
        fingerprint = hashlib.blake2b(digest_size=16)
        settled_hashes: set[int] = set()
        planned_keys: set[str] = set()
        with _CHUNK_CACHE_LOCK:
            for chunk_path, byte_limit in plan:
                tail: "bytes | None" = None
                try:
                    # Binary: a line's byte count is exact, and one invalid
                    # byte (a torn write can split a multibyte character)
                    # costs one line via errors="replace", never the read.
                    with chunk_path.open("rb") as handle:
                        st = os.fstat(handle.fileno())
                        state, how = _chunk_state_for(chunk_path, handle, st, byte_limit, use_cache)
                        counters["chunks_read"] += 1
                        counters["dates_read"].append(chunk_path.stem)
                        counters["chunks_" + how] += 1
                        try:
                            tail, parsed = _parse_into_state(handle, state, byte_limit)
                            counters["bytes_parsed"] += parsed
                            state.size, state.mtime_ns = st.st_size, st.st_mtime_ns
                            if use_cache:
                                _CHUNK_CACHE[str(chunk_path)] = state
                                planned_keys.add(str(chunk_path))
                        except OSError:
                            _CHUNK_CACHE.pop(str(chunk_path), None)
                except OSError:
                    continue

                # Replay this chunk's entries in file order.
                counters["lines_seen"] += state.lines_seen
                counters["unparseable"] += state.unparseable
                counters["skipped_unsettled"] += state.pending_plain
                counters["bytes_read"] += state.offset
                if state.settled:
                    # Only chunks that contribute records: a chunk holding
                    # nothing but pending lines must not move the fingerprint.
                    fingerprint.update(f"{len(state.settled)}|".encode("utf-8"))
                    fingerprint.update(state.digest.copy().digest())

                def _replay_pending(upto: int, start: int) -> int:
                    for index in range(start, upto):
                        if state.pending_hashes[index] in settled_hashes:
                            payload, identity = _read_line_at(chunk_path, state.pending_offsets[index])
                            if payload is not None and identity in settled_identities:
                                projected = project_ranking_record(payload)
                                records.append(projected)
                                counters["kept_superseding_pending"] += 1
                                fingerprint.update(b"S" + _entry_digest_bytes(identity, projected))
                                continue
                        counters["skipped_unsettled"] += 1
                    return upto

                done = 0
                for pending_before, identity, projected in state.settled:
                    done = _replay_pending(pending_before, done)
                    if identity is not None:
                        settled_identities.add(identity)
                        settled_hashes.add(hash(identity))
                    records.append(projected)
                    counters["kept"] += 1
                _replay_pending(len(state.pending_hashes), done)

                if tail is not None:
                    # An unterminated last line: this call only, never cached.
                    counters["bytes_read"] += len(tail)
                    kind, tail_identity, payload = _classify_line(tail)
                    if kind != "blank":
                        counters["lines_seen"] += 1
                        before = len(records)
                        _consider(payload)
                        if kind == "settled" and tail_identity is not None:
                            settled_hashes.add(hash(tail_identity))
                        if len(records) > before:
                            fingerprint.update(b"T" + _entry_digest_bytes(tail_identity, records[-1]))
            if use_cache:
                # Chunks that left the window are dropped, so the cache never
                # holds more than the window.
                prefix = str(_ie._ledger_chunk_path(target_path, "x").parent)
                for key in [k for k in _CHUNK_CACHE if k not in planned_keys and str(Path(k).parent) == prefix]:
                    del _CHUNK_CACHE[key]
        if use_cache:
            records.fingerprint = fingerprint.hexdigest()

    elapsed = time.monotonic() - started
    counters["elapsed_s"] = round(elapsed, 3)
    cache_label = (
        f"reused:{counters['chunks_reused']},extended:{counters['chunks_extended']},parsed:{counters['chunks_parsed']}"
        if use_cache
        else "off"
    )
    print(
        "[ranking_records] RANKING_RECORDS_LOADED "
        f"days={counters['days']} chunks={counters['chunks_read']} bytes={counters['bytes_read']} "
        f"lines={counters['lines_seen']} kept={counters['kept']} "
        f"skipped_unsettled={counters['skipped_unsettled']} "
        f"kept_superseding_pending={counters['kept_superseding_pending']} "
        f"excluded_by_backstop={counters['excluded_by_backstop']} "
        f"excluded_bytes={counters['bytes_excluded_by_backstop']} partial={counters['chunks_partial']} "
        f"unparseable={counters['unparseable']} cache={cache_label} bytes_parsed={counters['bytes_parsed']} "
        f"elapsed_s={elapsed:.3f}",
        flush=True,
    )
    if stats is not None:
        stats.update(counters)
    return records
