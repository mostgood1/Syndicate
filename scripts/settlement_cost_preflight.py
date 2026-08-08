"""What would turning the settlement autorun ON actually cost, and what would it buy?

Context: Syndicate evaluation/feedback loop.
See: docs/ai_context/todo.md (#269), docs/reports/syndicate_end_to_end_assessment_2026_08_02.md (F1)

Role:
- Answer "can refresh-worker survive a settlement run" and "would that run grade
  anything" WITHOUT running settlement and WITHOUT setting
  EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN. Enabling it is the user's
  call; this is the evidence for it.

Constraints:
- READ-ONLY by construction. The default mode (`--project-only`) never opens a
  ledger chunk -- it stats them and applies measured coefficients. That is not
  fastidiousness: reading one production chunk is ITSELF the ~1.4GB allocation
  under investigation (see COEFFICIENTS below), so a prober that read them to
  measure them would be the outage it was written to predict. The `--dry-run`
  mode does read, costs exactly what settlement costs, and says so before it runs.
- Never writes to the ledger. `settle_ledger_for_date(dry_run=True)` short-circuits
  before `settle_result`, so no chunk and no index is rewritten.

WHY THE COST IS NOT OBVIOUS FROM READING THE CODE
The expensive terms are all per-RECORD, not per-run, and two of them are in a
different module from the settlement loop:

  1. `_read_chunk_records` returns a full list of parsed dicts for the date's
     chunk. Streamed since #256, but still fully materialised.
  2. `_replace_ledger_line` rewrites the WHOLE chunk, once per settled record.
     Streamed since #254, so memory-flat -- but O(chunk_bytes) of I/O each time.
  3. `_load_chunk_index` / `_write_chunk_index` round-trip the ENTIRE chunk index
     -- `read_text` + `json.loads` + `json.dumps(indent=2, sort_keys=True)` +
     `write_text` -- once per settled record, uncached and unstreamed. The index
     holds one entry per ledger record EVER written and is never pruned, so
     unlike (1) and (2) it is not bounded by the slate. This is the term nobody
     has measured in production, because the index is not in
     artifact_publisher.HOT_ARTIFACT_PATTERNS and refresh-worker serves no HTTP.

Usage:
    python scripts/settlement_cost_preflight.py                    # projection only
    python scripts/settlement_cost_preflight.py --coverage         # + graded-row ceiling
    python scripts/settlement_cost_preflight.py --dry-run          # + real match rate (EXPENSIVE)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# COEFFICIENTS -- measured 2026-08-08, not estimated.
#
# Method: real ledger chunks from reports/intelligence/evaluation_ledger_chunks/,
# parsed through the production reader, RSS via psutil around a gc.collect().
# Linearity checked across two different chunk files at two scale factors:
#
#     file            json_mb   rss_delta_mb   ratio
#     2026-06-04.jsonl   8.47          34.7     4.10
#     2026-06-04.jsonl  67.76         274.5     4.05
#     2026-07-08.jsonl  65.66         275.3     4.19
#
# EXTRAPOLATION CAVEAT, stated because it is the weak link: those records average
# 10.5-11.8KB, while production's average 20.6KB (2026-08-06 chunk) to 40.6KB
# (2026-08-05 chunk). The ratio holds only if the larger records are larger in
# the same WAY -- more nested dicts rather than one long string, since a dict of
# small values costs far more per byte than a string does. Checked: on the
# largest local record (13,301 bytes) 94% of the bytes are nested dicts
# (`recommendation` 7,896 + `prediction` 2,180 + `artifact_metadata` 1,556).
# So the shape is dict-dominated and the ratio should carry. It is still an
# extrapolation and is labelled as one in the output.
RSS_MB_PER_JSON_MB = 4.1
PARSE_SECONDS_PER_JSON_MB = 0.022
# Per settled record, per MB of the chunk being rewritten (local NVMe; Render's
# mounted disk is network-attached and will be SLOWER, so this is a lower bound).
REWRITE_SECONDS_PER_CHUNK_MB = 0.00456

# Chunk-index round trip, measured on synthetic indexes built from the real
# local index's entry shape (244 bytes/entry on disk at indent=2):
#     entries    disk_mb   load_s   write_s   total_s   rss_mb
#         869       0.20    0.020     0.009     0.030      0.7
#     100,000      22.98    0.289     0.855     1.144     57.5
#     400,000      91.93    1.353     3.974     5.327    237.6
#
# Scaled per MB OF INDEX rather than per entry, deliberately: the file size is
# the only thing the projection can know without READING the index, and reading
# a 92MB index costs ~238MB -- the same class of allocation this tool exists to
# avoid spending. Both measured points agree closely on the per-MB basis
# (2.50 and 2.58 MB RSS per index-MB; 0.0498 and 0.0580 s per index-MB), so the
# upper value is used.
INDEX_BYTES_PER_ENTRY = 244.1  # reporting only -- turns bytes into a legible entry estimate
INDEX_RSS_MB_PER_INDEX_MB = 2.58
INDEX_SECONDS_PER_INDEX_MB = 0.058

# refresh-worker srv-d91dpertqb8s73co8ls0. The RSS basis and the
# reclaimable-cache constant are check_worker_memory_gate.py's, re-derived at the
# three real OOM kills of 2026-08-07 -- do not substitute memory.current here.
WORKER_CONTAINER_LIMIT_MB = 4096.0
CACHE_FLOOR_UNDER_PRESSURE_MB = 500.0
WORKER_RSS_LETHAL_MB = WORKER_CONTAINER_LIMIT_MB - CACHE_FLOOR_UNDER_PRESSURE_MB


def _ledger_root() -> Path:
    from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
    from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path

    return _ledger_chunk_path(DEFAULT_LEDGER_PATH, "0000-00-00").parent


def _target_dates(lookback_days: int, today: str | None) -> list[str]:
    """The autorun's own window: oldest first, `lookback_days` ending today.

    Mirrors run_refresh_worker._evaluation_settlement_lookback_days (default 21)
    rather than assuming a window, so the projection covers what would actually
    be read.
    """
    anchor = date.fromisoformat(today) if today else date.today()
    return [(anchor - timedelta(days=offset)).isoformat() for offset in range(lookback_days - 1, -1, -1)]


def project(dates: list[str]) -> dict[str, Any]:
    from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
    from syndicate.features.shared.intelligence_evaluation import _ledger_chunk_path
    from syndicate.features.shared.intelligence_evaluation import _ledger_index_path

    chunks: list[dict[str, Any]] = []
    for date_token in dates:
        chunk_path = _ledger_chunk_path(DEFAULT_LEDGER_PATH, date_token)
        if not chunk_path.exists():
            chunks.append({"date": date_token, "exists": False})
            continue
        size_mb = chunk_path.stat().st_size / 1_048_576.0
        chunks.append(
            {
                "date": date_token,
                "exists": True,
                "json_mb": round(size_mb, 2),
                # The autorun holds ONE date at a time (#256), so the run's peak
                # is the LARGEST chunk, not the sum. Reported per-chunk so the
                # peak is visible rather than inferred.
                "projected_rss_mb": round(size_mb * RSS_MB_PER_JSON_MB, 1),
                "projected_parse_seconds": round(size_mb * PARSE_SECONDS_PER_JSON_MB, 2),
                "rewrite_seconds_per_settled_record": round(size_mb * REWRITE_SECONDS_PER_CHUNK_MB, 3),
            }
        )

    present = [chunk for chunk in chunks if chunk.get("exists")]
    peak_chunk = max(present, key=lambda chunk: chunk["json_mb"], default=None)

    index_path = _ledger_index_path(DEFAULT_LEDGER_PATH)
    index_bytes = index_path.stat().st_size if index_path.exists() else 0
    index_mb = index_bytes / 1_048_576.0

    return {
        "ledger_chunk_dir": str(_ledger_root()),
        "dates_in_window": len(dates),
        "chunks_present": len(present),
        "chunks_missing": len(dates) - len(present),
        "peak_chunk": peak_chunk,
        "chunk_index": {
            "path": str(index_path),
            "exists": bool(index_bytes),
            "bytes": index_bytes,
            "mb": round(index_mb, 2),
            "estimated_entries": round(index_bytes / INDEX_BYTES_PER_ENTRY),
            "rss_mb_per_settled_record": round(index_mb * INDEX_RSS_MB_PER_INDEX_MB, 1),
            "seconds_per_settled_record": round(index_mb * INDEX_SECONDS_PER_INDEX_MB, 3),
        },
        "projected_peak_rss_mb": round(
            (peak_chunk["projected_rss_mb"] if peak_chunk else 0.0)
            + index_mb * INDEX_RSS_MB_PER_INDEX_MB,
            1,
        ),
        "worker_rss_lethal_mb": WORKER_RSS_LETHAL_MB,
        "basis": "measured coefficients, extrapolated by chunk size -- see module docstring",
        "chunks": chunks,
    }


def coverage(dates: list[str], sports: list[str]) -> dict[str, Any]:
    """The achievable ceiling: how many graded outcomes exist to settle AGAINST.

    This is the half of the question that memory cost cannot answer. A run that
    survives and grades nothing is worse than no run, because a completed status
    file reads as coverage. Cheap -- the grader input build measured ~0.2s per
    (sport, date) on production.
    """
    from syndicate.features.shared.graded_outcomes import graded_rows_for_date

    per_sport: dict[str, int] = {}
    per_sport_date: dict[str, dict[str, int]] = {}
    for sport in sports:
        per_sport_date[sport] = {}
        for date_token in dates:
            try:
                rows = graded_rows_for_date(sport, date_token)
            except Exception as exc:  # noqa: BLE001
                per_sport_date[sport][date_token] = -1
                per_sport_date[sport][f"{date_token}:error"] = f"{type(exc).__name__}: {exc}"  # type: ignore[assignment]
                continue
            count = len(rows or [])
            if count:
                per_sport_date[sport][date_token] = count
            per_sport[sport] = per_sport.get(sport, 0) + count
    total = sum(per_sport.values())
    return {
        "graded_rows_total": total,
        "graded_rows_by_sport": per_sport,
        "graded_rows_by_sport_date": per_sport_date,
        "note": (
            "This is the CEILING on distinct outcomes settlement can match against. "
            "Zero for a sport is not automatically a defect -- nba/nhl are out of "
            "season, and soccer/ncaab/ncaaf graders are documented []-stubs."
        ),
    }


def dry_run(dates: list[str], sports: list[str]) -> dict[str, Any]:
    """The real match rate. EXPENSIVE -- this reads the chunks, which is the
    allocation the projection exists to avoid. Never writes (dry_run=True
    short-circuits before settle_result)."""
    from syndicate.features.shared.evaluation_settlement import settle_ledger_for_dates

    return settle_ledger_for_dates(list(dates), sports=list(sports), dry_run=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lookback-days", type=int, default=21, help="autorun default is 21")
    parser.add_argument("--today", default=None, help="anchor date (ISO); defaults to today")
    parser.add_argument("--coverage", action="store_true", help="also report the graded-row ceiling")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="also run a real no-write settlement pass -- costs what settlement costs",
    )
    parser.add_argument("--sports", default=None, help="comma-separated; defaults to every registered grader")
    args = parser.parse_args(argv)

    from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS

    sports = (
        [item.strip().lower() for item in str(args.sports).split(",") if item.strip()]
        if args.sports
        else sorted(GRADED_OUTCOME_GRADERS.keys())
    )
    dates = _target_dates(max(1, args.lookback_days), args.today)

    report: dict[str, Any] = {"window": {"first": dates[0], "last": dates[-1], "days": len(dates)}, "sports": sports}
    report["projection"] = project(dates)
    if args.coverage:
        report["coverage"] = coverage(dates, sports)
    if args.dry_run:
        peak = report["projection"].get("projected_peak_rss_mb")
        print(
            f"[settlement_cost_preflight] --dry-run READS the chunks: projected peak "
            f"~{peak}MB RSS against a ~{WORKER_RSS_LETHAL_MB:.0f}MB lethal level on refresh-worker.",
            flush=True,
        )
        report["dry_run"] = dry_run(dates, sports)

    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
