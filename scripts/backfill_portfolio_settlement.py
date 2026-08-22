"""Settle historical portfolio positions, one date at a time, preview first.

Context: Syndicate evaluation/feedback loop.
See: docs/ai_context/todo.md (`#502`, `#504`, `#505`)

Role:
- Walk a date range OLDEST-FIRST and settle the portfolio ledger for each date,
  reporting per-date what WOULD change before anything is written.

Constraints:
- **PREVIEW BY DEFAULT.** Writing requires an explicit `--commit`. Settling a
  bet wrongly is worse than leaving it pending, and a backfill applies whatever
  it gets across every historical date at once -- it is the one genuinely
  irreversible action in this area.
- **ONE DATE AT A TIME, never accumulated.** `#256`: holding 21 dates of ledger
  records simultaneously was the single largest allocation on a 4GiB worker.
  Production chunks measured 95-332MB each on 2026-08-22.
- Never writes to the evaluation ledger. Settlement is invoked with
  `dry_run=True` unless `--commit`, and that short-circuits before
  `settle_result`, so no chunk and no index is rewritten.

WHAT THIS CAN AND CANNOT REACH, measured against `HOT_ARTIFACT_PATTERNS`
-----------------------------------------------------------------------
The idea of pulling everything down and backfilling locally is sound, but only
half the inputs can travel. Checked mechanically with `fnmatch`:

    settlement_inputs/closing_lines_*.csv    PULLABLE
    settlement_inputs/finals_*.json          PULLABLE
    reports/intelligence/clv_openings/*      PULLABLE
    evaluation_ledger_chunks/<date>.jsonl    NOT REACHABLE
    evaluation_ledger_chunks/index.json      NOT REACHABLE

The evaluation ledger is worker-local by construction: not allowlisted,
refresh-worker serves no HTTP, and two lanes independently confirmed there is no
path to it from any service with an API. So:

  --mode worker   (default) full pass: reconciliation -> settlement -> bridge.
                  Must run ON refresh-worker. Settles straights AND parlays.
  --mode local    reconciliation only, against pulled `settlement_inputs/`.
                  Settles STRAIGHT bets. **Cannot settle parlays** -- a parlay
                  has no single market to match (`ledger_bridge`'s own
                  docstring), so it needs the bridge, which needs evaluation
                  records, which cannot leave the worker.

That limitation is stated rather than worked around, because the alternative is
inventing a bet<->graded-row join here. `normalize_portfolio_event_identity`
(`#297`) records why that is not a small job: graded rows carry **no event
identifier at all**, so the join runs on normalized team/player VALUES, and
getting it wrong settles the wrong bet rather than none.

BEFORE YOU RUN THIS WITH --commit
---------------------------------
`#505`'s `entity` field mapping has never been measured against real evaluation
records. Read a live `[ledger_bridge]` line first: `matched_by_identity > 0`
means the join works; `index_sizes.by_identity` large with
`matched_by_identity: 0` means the mapping is wrong and a backfill would write
nothing -- or, worse, write matches that are not real.

Usage:
    python scripts/backfill_portfolio_settlement.py --pending
    python scripts/backfill_portfolio_settlement.py --from 2026-08-12 --to 2026-08-21
    python scripts/backfill_portfolio_settlement.py --pending --commit
    python scripts/backfill_portfolio_settlement.py --mode local --result-root ./pulled
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _log(message: str) -> None:
    """Progress to STDERR, so `--json` leaves stdout machine-readable.

    Found by running it: the first `--json` invocation could not be piped into
    `json.load` because these lines were interleaved on stdout. A report you
    have to hand-strip before parsing is a report nobody parses.
    """
    print(message, file=sys.stderr, flush=True)


def _iso(value: str) -> str:
    token = str(value or "").strip()[:10]
    date.fromisoformat(token)  # raises on malformed input rather than skewing a window
    return token


def _date_range(start: str, end: str) -> list[str]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise SystemExit(f"--to {end} precedes --from {start}")
    span = (last - first).days + 1
    # Oldest first: a backfill should settle in chronological order so a partial
    # run leaves a contiguous settled prefix rather than holes.
    return [(first + timedelta(days=offset)).isoformat() for offset in range(span)]


def _pending_dates() -> list[str]:
    from syndicate.features.prediction_reconciliation import pending_prediction_dates

    return pending_prediction_dates()


def _ledger_snapshot(ledger_path: Path | None) -> dict[str, Any]:
    """Counts before/after, so a preview can report a DELTA rather than a claim."""
    from syndicate.features.prediction_ledger import load_all_predictions

    predictions = load_all_predictions(ledger_path=ledger_path)
    settled = 0
    for prediction in predictions:
        result = prediction.get("result")
        if isinstance(result, dict) and str(result.get("outcome") or "").strip().lower() in {"win", "loss", "push", "void"}:
            settled += 1
    return {"total": len(predictions), "settled": settled, "pending": len(predictions) - settled}


def _preview_ledger_copy() -> Path:
    """A throwaway copy of the portfolio ledger.

    `reconcile_prediction_results_for_date` has no `dry_run`; it writes. Rather
    than skip the preview for the half of this that matters most, point it at a
    COPY and diff the counts. That is a real preview, not an assertion that
    nothing happened.
    """
    from syndicate.features.prediction_ledger import _default_ledger_path

    source = _default_ledger_path()
    handle = tempfile.NamedTemporaryFile(prefix="portfolio_preview_", suffix=".json", delete=False)
    handle.close()
    target = Path(handle.name)
    if source.exists():
        shutil.copy2(source, target)
    else:
        target.write_text(json.dumps({"schema_version": 1, "predictions": [], "results": []}), encoding="utf-8")
    return target


def _run_one_date(
    target_date: str,
    *,
    commit: bool,
    mode: str,
    result_roots: list[Path] | None,
    ledger_path: Path | None,
) -> dict[str, Any]:
    from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date

    outcome: dict[str, Any] = {"date": target_date}
    before = _ledger_snapshot(ledger_path)

    try:
        reconciled = reconcile_prediction_results_for_date(
            target_date, ledger_path=ledger_path, result_roots=result_roots
        )
        outcome["reconciliation"] = reconciled.get("summary")
    except Exception as exc:  # noqa: BLE001
        outcome["reconciliation_error"] = f"{type(exc).__name__}: {exc}"

    if mode == "worker":
        try:
            from syndicate.features.shared.evaluation_settlement import _read_ledger_records_for_date
            from syndicate.features.shared.evaluation_settlement import settle_ledger_for_dates
            from syndicate.features.shared.graded_outcomes import GRADED_OUTCOME_GRADERS
            from syndicate.features.shared.intelligence_evaluation import DEFAULT_LEDGER_PATH
            from syndicate.features.shared.ledger_bridge import bridge_settled_results

            settled = settle_ledger_for_dates(
                [target_date],
                sports=sorted(GRADED_OUTCOME_GRADERS.keys()),
                dry_run=not commit,
            )
            outcome["settlement"] = settled.get("totals")

            # The bridge is READ-ONLY against the evaluation ledger; it only
            # writes the portfolio. In preview mode the portfolio it writes is
            # the throwaway copy, so this is safe to run either way -- and
            # running it is the whole point, since its breakdown is what says
            # whether the `#505` identity join actually matched anything.
            records = _read_ledger_records_for_date(DEFAULT_LEDGER_PATH, target_date) or []
            outcome["records_for_date"] = len(records)
            if records:
                outcome["bridge"] = bridge_settled_results(
                    evaluation_records=records, ledger_path=ledger_path
                )
            del records
        except Exception as exc:  # noqa: BLE001
            outcome["settlement_error"] = f"{type(exc).__name__}: {exc}"

    after = _ledger_snapshot(ledger_path)
    outcome["ledger_delta"] = {
        "settled_before": before["settled"],
        "settled_after": after["settled"],
        "newly_settled": after["settled"] - before["settled"],
        "still_pending": after["pending"],
    }
    return outcome


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="start", default="", help="ISO start date (inclusive)")
    parser.add_argument("--to", dest="end", default="", help="ISO end date (inclusive)")
    parser.add_argument(
        "--pending",
        action="store_true",
        help="Derive the date list from the ledger's own unsettled positions (pending_prediction_dates)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write. Without this the run is a PREVIEW against a throwaway ledger copy.",
    )
    parser.add_argument("--mode", choices=("worker", "local"), default="worker",
                        help="worker: full pass incl. settlement+bridge (must run ON refresh-worker). "
                             "local: reconciliation only, against pulled settlement_inputs -- cannot settle parlays.")
    parser.add_argument("--result-root", action="append", default=[],
                        help="Result root to search for graded outputs; repeat to add more")
    parser.add_argument("--max-dates", type=int, default=0,
                        help="Stop after N dates. 0 = no cap. Use it on a first run.")
    parser.add_argument("--json", action="store_true", help="Emit the full per-date report as JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.pending:
        dates = _pending_dates()
    elif args.start and args.end:
        dates = _date_range(_iso(args.start), _iso(args.end))
    else:
        raise SystemExit("give either --pending or both --from and --to")

    if not dates:
        _log("no dates to backfill -- the ledger has no unsettled positions with a resolvable date")
        return 0
    if args.max_dates > 0:
        dates = dates[: args.max_dates]

    ledger_path: Path | None = None
    if not args.commit:
        ledger_path = _preview_ledger_copy()

    result_roots = [Path(value) for value in args.result_root] if args.result_root else None
    if args.mode == "local" and not result_roots:
        # The local mode's whole premise is pulled artifacts; defaulting to the
        # repo's own data/ dir would silently reconcile against a lossy mirror.
        raise SystemExit("--mode local requires at least one --result-root pointing at pulled settlement_inputs")

    banner = "COMMIT (writing)" if args.commit else "PREVIEW (throwaway ledger copy, nothing is written)"
    _log(f"[backfill] {banner} mode={args.mode} dates={len(dates)} first={dates[0]} last={dates[-1]}")
    if args.mode == "local":
        _log("[backfill] local mode settles STRAIGHT bets only -- parlays need the bridge, "
             "which needs evaluation records that cannot leave refresh-worker")

    reports: list[dict[str, Any]] = []
    for target_date in dates:
        report = _run_one_date(
            target_date,
            commit=args.commit,
            mode=args.mode,
            result_roots=result_roots,
            ledger_path=ledger_path,
        )
        reports.append(report)
        delta = report.get("ledger_delta", {})
        bridge = report.get("bridge") or {}
        _log(
            f"[backfill] {target_date} newly_settled={delta.get('newly_settled')} "
            f"still_pending={delta.get('still_pending')} "
            f"records={report.get('records_for_date', 'n/a')} "
            f"index={json.dumps(bridge.get('index_sizes', {}), sort_keys=True)} "
            f"matched_by_id={bridge.get('matched_by_id', 'n/a')} "
            f"matched_by_identity={bridge.get('matched_by_identity', 'n/a')} "
            f"skip_reasons={json.dumps(bridge.get('skip_reasons', {}), sort_keys=True)}"
        )

    total_new = sum(int((r.get("ledger_delta") or {}).get("newly_settled") or 0) for r in reports)
    _log(f"[backfill] DONE dates={len(reports)} newly_settled_total={total_new}")
    if not args.commit:
        _log("[backfill] nothing was written. Re-run with --commit once the numbers above look right.")
        if ledger_path is not None:
            ledger_path.unlink(missing_ok=True)

    if args.json:
        print(json.dumps({"dates": reports, "newly_settled_total": total_new}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
