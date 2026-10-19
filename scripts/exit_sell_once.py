"""Sell N contracts of ONE live Kalshi entry, once, through `execution_exits.place_exit`.

For verifying the sell body against the venue, and for nothing that runs on a
schedule. Every gate `place_exit` applies still applies: the operator must set
`SYNDICATE_EXIT_MODE=live` and `SYNDICATE_EXIT_LIVE_ARMED=1` FOR THIS PROCESS ONLY
(the entry path's `SYNDICATE_EXECUTION_LIVE_ARMED` must already be set), the kill
switch must be clear, and the venue must confirm the contracts are held.

    python scripts/exit_sell_once.py --entry-key <24hex>                 # dry run: prints the body
    python scripts/exit_sell_once.py --entry-key <24hex> --confirm       # sends

The write-ahead row lands in `execution_exits.json`, which the worker's paper
tick also rewrites. Run it right AFTER a worker `EXIT_TICK`; the row is checked
afterwards and put back if a concurrent tick dropped it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entry-key", required=True)
    parser.add_argument("--contracts", type=int, default=1)
    parser.add_argument("--slack", type=float, default=0.01, help="limit = bid - slack, on our leg")
    parser.add_argument("--confirm", action="store_true", help="actually send")
    args = parser.parse_args(argv)

    from syndicate.features.shared import execution_exits as ex
    from syndicate.features.shared.execution_ledger import _load
    from syndicate.features.shared.timezone import central_today_iso

    orders = list(_load().get("orders") or [])
    positions, _ = ex.open_positions(orders, today=central_today_iso())
    state = ex.load_state()
    positions, _ = ex.net_of_live_sales(positions, state)
    match = [p for p in positions if p.entry_key == args.entry_key]
    if not match:
        print(json.dumps({"refused": "entry_not_an_open_position"}))
        return 2
    position = match[0]
    venue = ex.fetch_venue_positions()
    reconciled = ex.reconcile_positions([position], venue)
    sellable = (reconciled.get("sellable") or {}).get(position.entry_key)
    quote = (ex.fetch_quotes([position.ticker]).get("markets") or {}).get(position.ticker)
    from datetime import datetime, timezone

    decision = ex.evaluate_exit(position, quote, margin=-1.0, fair_buffer=0.0, now=datetime.now(timezone.utc))
    if decision.get("bid") is None:
        print(json.dumps({"refused": f"no_bid:{decision.get('reason')}"}))
        return 3
    limit = round(float(decision["bid"]) - args.slack, 4)
    preview = ex.exit_order_body(position, bid=limit, count=args.contracts)
    print(json.dumps({
        "position": {"entry_key": position.entry_key, "ticker": position.ticker, "leg": position.leg,
                     "contracts": position.contracts, "entry_price": position.entry_price},
        "venue": reconciled.get("status"), "sellable": sellable,
        "bid": decision.get("bid"), "bid_size": decision.get("bid_size"), "limit": limit,
        "body": preview, "exit_mode": ex.exit_mode(), "armed": ex.exit_live_armed(),
    }, default=str))
    if not args.confirm:
        print("DRY RUN -- nothing sent (pass --confirm)")
        return 0

    out = ex.place_exit(state, position, decision, sellable=sellable, max_contracts=args.contracts,
                        limit_price=limit, purpose="sell_body_verification")
    print(json.dumps(out, default=str))
    row = out.get("row")
    if row is not None and "refused" not in out:
        # A concurrent worker tick may have rewritten the document between our
        # load and our write. Put the row back if it is gone.
        latest = ex.load_state()
        if latest["exits"].get(row["exit_key"]) != row:
            latest["exits"][row["exit_key"]] = row
            ex._persist(latest)
            print("ROW_REINSERTED after a concurrent write")
        after = ex.fetch_venue_positions()
        print(json.dumps({"venue_after": (after.get("positions") or {}).get(position.ticker),
                          "venue_status": after.get("status")}))
    return 0 if out.get("placed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
