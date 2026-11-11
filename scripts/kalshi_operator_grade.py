"""Grade ONE live Kalshi fill from Kalshi's own settled result, when the venue grader cannot (lane `kalshi-aged-out-grade`).

    python3 scripts/kalshi_operator_grade.py --key 970ec063e70e43b1ac7e1cbd                  # DRY RUN (default)
    python3 scripts/kalshi_operator_grade.py --key 970ec063e70e43b1ac7e1cbd --apply --note "..."

WHY. `execution_ledger.operator_grade_from_venue` explains the case it was built for: key `970ec063` WON on
2026-10-25 and nothing could ever grade it, because the settlement row carried a 0.01-contract YES leg -- our
own take-profit exit, filled 0.01 of 1 and recorded `dead` -- so the venue grader refused `both_sides_held` on
every pass.

WHAT THIS DOES. Reads the ledger row, then Kalshi with GETs only (`/portfolio/settlements?ticker=`,
`/portfolio/fills?ticker=`) and prints the evidence and what a grade WOULD write. It refuses unless:
  * the row is LIVE, Kalshi, `filled` and ungraded;
  * Kalshi's settlement for the ticker names `market_result` yes|no;
  * the settlement's count on OUR leg covers this order's contracts (Kalshi held our position at settlement);
  * the venue grader itself refuses that row (a row it can grade is its business, not an operator's).
`--apply` (with a `--note`) writes the grade through `operator_grade_from_venue`: outcome from the order's own
leg against `market_result`, P&L from the order's own fill, evidence and note stored on the row, the prior
fields kept under `pre_operator_grade`.

RUN IT WHERE THE WORKER RUNS, with the worker's store env and Kalshi credentials (the fleet: live-odds-worker's
environ). It prints order facts only -- never an env value, header or credential. Writing the live ledger is
the user's call: `--apply` only on their explicit yes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def kalshi_get(path: str) -> dict[str, Any]:
    from syndicate.features.shared import kalshi_orders as ko
    from syndicate.features.shared.kalshi_auth import signed_request

    return signed_request("GET", ko._read_base().rstrip("/") + path)


def settlement_for(ticker: str, get=kalshi_get) -> Mapping[str, Any] | None:
    payload = get(f"/portfolio/settlements?ticker={ticker}&limit=100")
    rows = [r for r in (payload.get("settlements") or []) if isinstance(r, Mapping) and r.get("ticker") == ticker]
    return rows[0] if len(rows) == 1 else None


def fills_for(ticker: str, get=kalshi_get) -> list[dict[str, Any]]:
    payload = get(f"/portfolio/fills?ticker={ticker}&limit=200")
    keep = ("order_id", "side", "action", "count_fp", "yes_price_dollars", "no_price_dollars", "fee_cost",
            "is_taker", "created_time")
    return [{k: f.get(k) for k in keep} for f in (payload.get("fills") or []) if isinstance(f, Mapping)]


def exit_row_for(entry_key: str) -> dict[str, Any] | None:
    """Our exit for this entry, from the live document or the archive (pruned rows move there)."""
    from syndicate.features.shared import execution_exits as ee

    xk = ee.exit_idempotency_key(entry_key)
    try:
        doc = (ee.load_state().get("exits") or {}).get(xk)
    except Exception:  # noqa: BLE001 -- evidence only; an unreadable document is reported as such
        doc = None
    row = doc or next((r for r in ee.archived_exit_rows() if r.get("exit_key") == xk), None)
    if row is None:
        return None
    keep = ("exit_key", "entry_key", "mode", "status", "rule", "leg", "requested_contracts", "filled_contracts",
            "venue_order_id", "venue_status", "submitted_at", "venue_resolved_at", "limit_price")
    return {**{k: row.get(k) for k in keep}, "where": "document" if doc else "archive"}


def plan(key: str, *, get=kalshi_get) -> dict[str, Any]:
    """Everything the grade would rest on, and the refusal if it must not happen. Writes nothing."""
    from syndicate.features.shared import execution_ledger as el
    from syndicate.features.shared import venue_settlement as vs

    order = el.find_order(key)
    if order is None:
        return {"refused": "order_not_found"}
    facts = {k: order.get(k) for k in ("idempotency_key", "mode", "venue", "venue_ticker", "side", "market", "line",
                                       "contracts", "fill_price", "fill_stake_dollars", "fees_dollars", "status",
                                       "venue_status", "outcome", "submitted_at", "venue_order_id")}
    out: dict[str, Any] = {"order": facts}
    if str(order.get("mode") or "") != el.LIVE:
        return {**out, "refused": "not_live"}
    if not str(order.get("venue") or "").lower().startswith("kalshi"):
        return {**out, "refused": "not_kalshi"}
    if order.get("outcome"):
        return {**out, "refused": f"already_settled:{order.get('outcome')}"}
    if str(order.get("status") or "") != el.STATUS_FILLED:
        return {**out, "refused": f"not_filled:{order.get('status')}"}
    ticker = str(order.get("venue_ticker") or "")
    row = settlement_for(ticker, get=get)
    if row is None:
        return {**out, "refused": "no_single_settlement_row"}
    leg = vs._order_side_key("kalshi", order)
    held = _num(row.get(f"{leg}_count_fp")) if leg in ("yes", "no") else None
    contracts = _num(order.get("contracts"))
    verdict = vs.grade_kalshi_settlement(row)
    out["settlement"] = {k: row.get(k) for k in ("ticker", "market_result", "settled_time", "yes_count_fp",
                                                 "no_count_fp", "revenue", "fee_cost", "yes_total_cost_dollars",
                                                 "no_total_cost_dollars")}
    out["venue_grader"] = verdict
    out["leg"] = leg
    out["fills"] = fills_for(ticker, get=get)
    out["exit"] = exit_row_for(key)
    result = str(row.get("market_result") or "").lower()
    if result not in ("yes", "no"):
        return {**out, "refused": f"unsupported_market_result:{result or 'absent'}"}
    if held is None or contracts is None or held + 1e-9 < contracts:
        return {**out, "refused": f"settlement_does_not_hold_our_leg:{leg}={held} contracts={contracts}"}
    if verdict.get("graded"):
        return {**out, "refused": "venue_grader_can_grade_it"}
    outcome = vs._kalshi_outcome_from_leg(result, leg)
    pnl = vs._derived_pnl(order, outcome) if outcome else None
    if outcome is None or pnl is None:
        return {**out, "refused": f"not_derivable:outcome={outcome} pnl={pnl}"}
    out["would_write"] = {"outcome": outcome, "pnl_dollars": pnl, "held_side": leg,
                          "settled_at_venue": row.get("settled_time"), "settled_by": "venue"}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--key", required=True, help="the ledger row's idempotency_key")
    parser.add_argument("--apply", action="store_true", help="WRITE the grade (the user's explicit yes only)")
    parser.add_argument("--note", default="", help="why; required with --apply and stored on the row")
    args = parser.parse_args(argv)

    out = plan(args.key)
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
    if out.get("refused"):
        print(f"REFUSED: {out['refused']}")
        return 2
    if not args.apply:
        print("DRY RUN: nothing written. Re-run with --apply --note \"...\" on the user's explicit yes.")
        return 0
    if not args.note.strip():
        print("REFUSED: --apply needs --note")
        return 2
    from syndicate.features.shared import execution_ledger as el

    evidence = {"settlement": out["settlement"], "venue_grader": out["venue_grader"], "fills": out["fills"],
                "exit": out["exit"], "tool": "scripts/kalshi_operator_grade.py"}
    row = el.operator_grade_from_venue(args.key, market_result=out["settlement"]["market_result"],
                                       settled_at_venue=out["settlement"].get("settled_time"),
                                       evidence=evidence, note=args.note)
    print("WRITTEN:", json.dumps({k: row.get(k) for k in ("idempotency_key", "outcome", "pnl_dollars", "held_side",
                                                           "settled_by", "graded_at")}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
