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

import json
import time
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


def load_recent_ranking_records(
    *,
    days: int = 14,
    ledger_path: "Path | str | None" = None,
    max_chunks: int = DEFAULT_MAX_CHUNKS,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    stats: "dict[str, Any] | None" = None,
) -> list[dict[str, Any]]:
    """Settled, projected records from the last ``days`` of ledger chunks.

    Chunks are SELECTED newest-first under the backstop
    (`_select_ledger_chunks_within_budget`) and yielded in ASCENDING date order,
    file order within a chunk -- the same order `load_recent_evaluation_records`
    produced, so last-wins dedup downstream behaves the same. Returns a list,
    not a generator: `rank_recommendations` iterates it several times.
    """
    started = time.monotonic()
    target_path = Path(ledger_path) if ledger_path is not None else _ie.DEFAULT_LEDGER_PATH
    counters: dict[str, Any] = {
        "days": int(days),
        "chunks_read": 0,
        "bytes_read": 0,
        "lines_seen": 0,
        "kept": 0,
        "skipped_unsettled": 0,
        "kept_superseding_pending": 0,
        "unparseable": 0,
        "excluded_by_backstop": 0,
        "bytes_excluded_by_backstop": 0,
        "chunks_partial": 0,
        "dates_read": [],
    }
    records: list[dict[str, Any]] = []
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
        # Flat single-file ledger (tests / legacy). Streamed, same filter.
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
        for chunk_path, byte_limit in plan:
            consumed = 0
            try:
                with chunk_path.open("r", encoding="utf-8") as handle:
                    counters["chunks_read"] += 1
                    counters["dates_read"].append(chunk_path.stem)
                    for line in handle:
                        # Checked BEFORE consuming, so the byte limit is exact
                        # (same rule as `_stream_chunked_ledger_records`).
                        line_bytes = len(line.encode("utf-8"))
                        if consumed + line_bytes > byte_limit:
                            break
                        consumed += line_bytes
                        stripped = line.strip()
                        if not stripped:
                            continue
                        counters["lines_seen"] += 1
                        try:
                            payload = json.loads(stripped)
                        except Exception:
                            counters["unparseable"] += 1
                            continue
                        _consider(payload)
            except OSError:
                pass
            counters["bytes_read"] += consumed

    elapsed = time.monotonic() - started
    counters["elapsed_s"] = round(elapsed, 3)
    print(
        "[ranking_records] RANKING_RECORDS_LOADED "
        f"days={counters['days']} chunks={counters['chunks_read']} bytes={counters['bytes_read']} "
        f"lines={counters['lines_seen']} kept={counters['kept']} "
        f"skipped_unsettled={counters['skipped_unsettled']} "
        f"kept_superseding_pending={counters['kept_superseding_pending']} "
        f"excluded_by_backstop={counters['excluded_by_backstop']} "
        f"excluded_bytes={counters['bytes_excluded_by_backstop']} partial={counters['chunks_partial']} "
        f"unparseable={counters['unparseable']} elapsed_s={elapsed:.3f}",
        flush=True,
    )
    if stats is not None:
        stats.update(counters)
    return records
