"""Repair LIVE Kalshi rows whose fractional fill was read as zero (todo #783, lane `kalshi-fractional-fills`).

    python3 scripts/kalshi_fractional_repair.py                       # DRY RUN (default): print the plan
    python3 scripts/kalshi_fractional_repair.py --apply --note "..."  # write it -- the user's explicit yes only

WHY. Until the parser fix, `kalshi_orders.venue_order_view` read `fill_count_fp` through `int(float())`, so a
sliver fill read as 0. Census 2026-11-11 (GET /portfolio/fills since 09-20): 7 live take-profit exits recorded
`dead` / 0 and 10 live entries recorded `rejected` with a real fill. The fix stops new ones; this rebuilds the
old ones from KALSHI'S OWN FILLS, never from our estimates.

WHAT IT REPAIRS, from `/portfolio/fills` (GET only), per venue order whose filled total is fractional:
  * a LIVE entry row recorded `rejected` -> `filled`, contracts = the venue total, the price and stake on OUR leg
    from the fills, the fills' fees; `venue_status` canceled with nothing remaining (every one was an IOC).
  * a LIVE exit row recorded `dead` / 0 -> `filled` with the venue total, our leg's price and the fees -- in the
    live exits document, or as a newer copy appended to `execution_exits_archive/` when it was pruned there
    (readers keep the newest copy per key).
Every repaired row keeps what it said before under `fractional_repair.from`, with the fills and the note.

WHAT IT LEAVES ALONE, and reports: graded rows (an outcome stands; e.g. `f67174cb` filled 1.06, recorded 1),
`submitted` rows (the reconciler books them at their true size once the parser fix is loaded: `91822817`), paper
rows, and fills that are no row of ours (manual / combo orders).

ORDER. Apply only after lane `kalshi-aged-out-grade` is loaded: a repaired entry is `filled` and ungraded until
settlement grades it, and an order Kalshi no longer serves by id would otherwise restart the reconcile 404 loop.
`--apply` refuses unless the imported ledger has that fix (`_venue_terminal_fill`).

Run it where the worker runs, with live-odds-worker's store env and Kalshi credentials. Prints order facts only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SINCE = "2026-09-20"


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def kalshi_get(path: str) -> dict[str, Any]:
    from syndicate.features.shared import kalshi_orders as ko
    from syndicate.features.shared.kalshi_auth import signed_request

    return signed_request("GET", ko._read_base().rstrip("/") + path)


def fetch_fills(since: str = SINCE, get: Callable[[str], Mapping[str, Any]] = kalshi_get) -> list[dict[str, Any]]:
    min_ts = int(datetime.fromisoformat(since).replace(tzinfo=timezone.utc).timestamp())
    fills: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(200):
        payload = get(f"/portfolio/fills?limit=200&min_ts={min_ts}" + (f"&cursor={cursor}" if cursor else ""))
        batch = [f for f in (payload.get("fills") or []) if isinstance(f, Mapping)]
        fills.extend(dict(f) for f in batch)
        cursor = str(payload.get("cursor") or "")
        if not cursor or not batch:
            return fills
    raise RuntimeError("fills_page_limit")


def venue_totals(fills: list[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """order_id -> its fills, for orders whose FILLED TOTAL is not a whole number of contracts."""
    by_order: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for fill in fills:
        by_order[str(fill.get("order_id"))].append(fill)
    out = {}
    for order_id, rows in by_order.items():
        total = sum(_num(f.get("count_fp") if f.get("count_fp") is not None else f.get("count")) or 0.0 for f in rows)
        if abs(total - round(total)) > 1e-9:
            out[order_id] = rows
    return out


def on_leg(fills: list[Mapping[str, Any]], leg: str) -> dict[str, Any] | None:
    """Total contracts, average price on `leg`, money at that price, and fees -- from the venue's fills alone."""
    total = proceeds = fees = 0.0
    for fill in fills:
        count = _num(fill.get("count_fp") if fill.get("count_fp") is not None else fill.get("count"))
        price = _num(fill.get(f"{leg}_price_dollars"))
        if count is None or price is None or leg not in ("yes", "no"):
            return None
        total += count
        proceeds += count * price
        fees += _num(fill.get("fee_cost")) or 0.0
    if total <= 0:
        return None
    return {"contracts": round(total, 6), "price": round(proceeds / total, 4), "dollars": round(proceeds, 6),
            "fees": round(fees, 6)}


def _evidence(fills: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keep = ("order_id", "fill_id", "side", "action", "count_fp", "yes_price_dollars", "no_price_dollars", "fee_cost",
            "created_time")
    return [{k: f.get(k) for k in keep} for f in fills]


def plan(*, get: Callable[[str], Mapping[str, Any]] = kalshi_get, since: str = SINCE,
         orders: list[Mapping[str, Any]] | None = None, exit_rows: dict[str, tuple[str, Mapping[str, Any]]] | None = None
         ) -> dict[str, Any]:
    """Everything a repair would write, and everything it leaves alone with the reason. Writes nothing."""
    from syndicate.features.shared import execution_exits as ee
    from syndicate.features.shared import execution_ledger as el
    from syndicate.features.shared import venue_settlement as vs

    fractional = venue_totals(fetch_fills(since, get=get))
    if orders is None:
        orders = list(el._load().get("orders") or [])
    by_venue_id = {str(o.get("venue_order_id")): o for o in orders if o.get("venue_order_id")}
    if exit_rows is None:
        exit_rows = {}
        for row in ee.archived_exit_rows():
            if row.get("venue_order_id"):
                exit_rows[str(row["venue_order_id"])] = ("archive", row)
        for row in (ee.load_state().get("exits") or {}).values():
            if row.get("venue_order_id"):
                exit_rows[str(row["venue_order_id"])] = ("document", row)

    out: dict[str, Any] = {"fractional_orders": len(fractional), "entries": [], "exits": [], "left": []}
    for order_id, fills in sorted(fractional.items(), key=lambda kv: min(str(f.get("created_time")) for f in kv[1])):
        entry = by_venue_id.get(order_id)
        if entry is not None:
            key = entry.get("idempotency_key")
            leg = vs._order_side_key("kalshi", entry)
            got = on_leg(fills, leg)
            if str(entry.get("mode") or "") != el.LIVE:
                out["left"].append({"key": key, "why": "paper"})
            elif entry.get("outcome"):
                out["left"].append({"key": key, "why": f"graded:{entry.get('outcome')}",
                                    "ours": entry.get("contracts"), "venue": got and got["contracts"]})
            elif str(entry.get("status") or "") != el.STATUS_REJECTED:
                out["left"].append({"key": key, "why": f"status:{entry.get('status')} (the reconciler books it once "
                                                       "the parser fix is loaded)", "venue": got and got["contracts"]})
            elif got is None:
                out["left"].append({"key": key, "why": f"unpriced_on_leg:{leg}"})
            else:
                out["entries"].append({"key": key, "ticker": entry.get("venue_ticker"), "leg": leg,
                                       "venue_order_id": order_id, "set": {
                                           "status": el.STATUS_FILLED, "contracts": got["contracts"],
                                           "fill_price": got["price"], "fill_stake_dollars": got["dollars"],
                                           "fees_dollars": got["fees"], "venue_status": "canceled",
                                           "venue_remaining_count": 0.0, "venue_open": False, "error": None},
                                       "from": {k: entry.get(k) for k in ("status", "contracts", "fill_price",
                                                                          "fill_stake_dollars", "fees_dollars",
                                                                          "error", "venue_status")},
                                       "fills": _evidence(fills)})
            continue
        where, row = exit_rows.get(order_id, (None, None))
        if row is not None:
            leg = str(row.get("leg") or "")
            got = on_leg(fills, leg)
            if str(row.get("mode") or "") != ee.EXIT_LIVE:
                out["left"].append({"exit_key": row.get("exit_key"), "why": "paper"})
            elif got is None:
                out["left"].append({"exit_key": row.get("exit_key"), "why": f"unpriced_on_leg:{leg}"})
            elif abs((_num(row.get("filled_contracts")) or 0.0) - got["contracts"]) < 1e-6:
                continue  # already right
            else:
                out["exits"].append({"exit_key": row.get("exit_key"), "entry_key": row.get("entry_key"),
                                     "where": where, "ticker": row.get("ticker"), "leg": leg,
                                     "venue_order_id": order_id, "set": {
                                         "status": ee.EXIT_FILLED, "filled_contracts": got["contracts"],
                                         "fill_price": got["price"], "exit_fee_dollars": got["fees"]},
                                     "from": {k: row.get(k) for k in ("status", "filled_contracts", "fill_price",
                                                                      "exit_fee_dollars", "venue_status")},
                                     "fills": _evidence(fills)})
            continue
        out.setdefault("not_ours", 0)
        out["not_ours"] += 1
    return out


def _audit(item: Mapping[str, Any], note: str, at: str) -> dict[str, Any]:
    return {"at": at, "note": note, "from": item["from"], "venue_order_id": item["venue_order_id"],
            "fills": item["fills"], "tool": "scripts/kalshi_fractional_repair.py", "todo": "#783"}


def apply(the_plan: Mapping[str, Any], *, note: str, settle_seconds: float = 120.0) -> dict[str, Any]:
    """Write the plan. Entries through the ledger's own compare-and-swap `_persist`; pruned exits as a newer
    archive copy; exits still in the live document through its writer, then RE-READ after `settle_seconds`
    and re-applied once if the worker's next tick wrote over them (its save is not a compare-and-swap)."""
    from syndicate.features.shared import execution_exits as ee
    from syndicate.features.shared import execution_ledger as el

    if not hasattr(el, "_venue_terminal_fill"):
        raise SystemExit("REFUSED: this ledger lacks lane kalshi-aged-out-grade's fix; load it first (see ORDER)")
    at = el._utc_now()
    done = {"entries": 0, "exits_archive": 0, "exits_document": 0, "exits_document_reapplied": 0}

    if the_plan.get("entries"):
        state = el._load()
        wanted = {i["key"]: i for i in the_plan["entries"]}
        for order in state.get("orders") or []:
            item = wanted.get(order.get("idempotency_key"))
            if item is None or order.get("outcome") or order.get("status") != el.STATUS_REJECTED:
                continue
            order.update(item["set"])
            order["fractional_repair"] = _audit(item, note, at)
            done["entries"] += 1
        if done["entries"]:
            el._persist(state)

    archive_items = [i for i in the_plan.get("exits") or [] if i["where"] == "archive"]
    if archive_items:
        latest = {r.get("exit_key"): r for r in ee.archived_exit_rows()}
        rows = []
        for item in archive_items:
            row = dict(latest.get(item["exit_key"]) or {})
            if not row:
                continue
            row.update(item["set"])
            row["fractional_repair"] = _audit(item, note, at)
            rows.append(row)
        ee._archive(rows, prefix="exits")
        done["exits_archive"] = len(rows)

    doc_items = [i for i in the_plan.get("exits") or [] if i["where"] == "document"]

    def _write_doc() -> int:
        with ee.EXIT_STATE_LOCK:
            state = ee.load_state()
            n = 0
            for item in doc_items:
                row = (state.get("exits") or {}).get(item["exit_key"])
                if row is None or row.get("fractional_repair"):
                    continue
                row.update(item["set"])
                row["fractional_repair"] = _audit(item, note, at)
                n += 1
            if n:
                ee._persist(state)
            return n

    if doc_items:
        done["exits_document"] = _write_doc()
        time.sleep(settle_seconds)
        done["exits_document_reapplied"] = _write_doc()
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--since", default=SINCE)
    parser.add_argument("--apply", action="store_true", help="WRITE the repair (the user's explicit yes only)")
    parser.add_argument("--note", default="", help="why; required with --apply and stored on every repaired row")
    args = parser.parse_args(argv)

    the_plan = plan(since=args.since)
    brief = {
        "fractional_orders": the_plan["fractional_orders"],
        "not_ours": the_plan.get("not_ours", 0),
        "entries": [{k: i[k] for k in ("key", "ticker", "leg")} | {"to": i["set"]["contracts"], "price": i["set"]["fill_price"],
                                                                   "from": i["from"]["status"]} for i in the_plan["entries"]],
        "exits": [{k: i[k] for k in ("exit_key", "entry_key", "where", "ticker")} | {"to": i["set"]["filled_contracts"],
                  "price": i["set"]["fill_price"], "from": i["from"]["status"]} for i in the_plan["exits"]],
        "left": the_plan["left"],
    }
    print(json.dumps(brief, indent=1, default=str))
    if not args.apply:
        print(f"DRY RUN: nothing written. {len(the_plan['entries'])} entries + {len(the_plan['exits'])} exits would be repaired.")
        return 0
    if not args.note.strip():
        print("REFUSED: --apply needs --note")
        return 2
    print("APPLIED:", json.dumps(apply(the_plan, note=args.note)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
