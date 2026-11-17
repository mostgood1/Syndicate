"""Record a live order's venue fill when the venue graded it before reconcile saw the fill (operator act).

[2026-11-17, lane stuck-kalshi-fill-repair] See `execution_ledger.operator_fill_from_venue`.

Reads the order from the venue through the reconciler's own single-order reader and view, prints what it
read and what the row holds, and writes ONLY with --apply and a --note. Run on the fleet with a worker's env
(keyvalue store + venue credentials), at low priority:

  python scripts/operator_fill_from_venue.py --key <idempotency_key>                    # dry run
  python scripts/operator_fill_from_venue.py --key <idempotency_key> --apply --note "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import execution_ledger as el  # noqa: E402

_ROW_FIELDS = ("status", "outcome", "pnl_dollars", "contracts", "fill_price", "fill_stake_dollars", "fees_dollars",
               "venue_status", "venue_order_id", "venue_ticker", "reconciled_at", "settled_by", "selected_date")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--key", required=True)
    ap.add_argument("--venue", default="kalshi")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)

    row = next((o for o in el._load().get("orders") or [] if o.get("idempotency_key") == args.key), None)
    if row is None:
        print(f"order {args.key} not in the live document", file=sys.stderr)
        return 2
    print("ROW", json.dumps({k: row.get(k) for k in _ROW_FIELDS}, default=str))
    reader = el._venue_single_order_reader(args.venue)
    _fetch, view, _coverage = el._venue_reader(args.venue)
    if reader is None or view is None:
        print(f"no single-order reader for {args.venue}", file=sys.stderr)
        return 2
    venue_id = str(row.get("venue_order_id") or "")
    read = reader(venue_id)
    if not isinstance(read, dict) or read.get("status") != "ok" or read.get("order") is None:
        print(f"venue read failed: {read!r}"[:300], file=sys.stderr)
        return 3
    seen = view(read["order"])
    print("VENUE", json.dumps({k: seen.get(k) for k in sorted(seen)}, default=str))
    if not args.apply:
        print("dry run: nothing written (pass --apply --note to write)")
        return 0
    try:
        out = el.operator_fill_from_venue(args.key, seen=seen, note=args.note, venue=args.venue)
    except el.OperatorResolutionError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 4
    print("WRITTEN", json.dumps({k: out.get(k) for k in _ROW_FIELDS}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
