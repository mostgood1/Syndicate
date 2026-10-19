"""Paper-measure compounding before anyone turns it on. READ-ONLY.

    python scripts/compounding_bankroll_paper.py --date 2026-10-19 [--json-out PATH]

Runs the PRODUCTION code (`pipeline.portfolio_commit._apply_compounding_bankroll`,
`default_bankroll_resolver`, `execution_guard.limits`) over production payloads:
today's live venue plans, the live-odds-worker's balance stamp, and today's live
orders from the execution ledger. Writes nothing to the store -- every plan is
deep-copied before it is re-sized, and the env flags are set in THIS process only.

What it reports, per venue, with denominators:

  * SIZING: each live position's stake at the fixed bankroll and at the
    account's own (Kalshi: bounded by the order's shard), plus how many
    positions compounding would refuse and why.
  * CAPS: `limits()` with balance caps off and on, side by side.
  * REPLAY: today's live orders, in submit order, against the balance caps --
    which would have been refused by the order cap or the day cap.

Kalshi shard lookups are the public market endpoint `execution_guard` already
uses (cached, no credential). Nothing here signs or places anything.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VENUES = ("kalshi", "polymarket")


def _measure_sizing(date: str, book: str = "live") -> dict[str, Any]:
    from pipeline import portfolio_commit as pc
    from syndicate.features.shared.portfolio_settings import resolve_settings
    from syndicate.features.shared.refresh_state_store import read_json_file

    settings = resolve_settings()
    out: dict[str, Any] = {"fixed_bankroll": settings.bankroll_units, "venues": {}}
    for venue in VENUES:
        path = (
            pc.live_portfolio_plan_path_for_venue(date, venue)
            if book == "live"
            else pc.portfolio_plan_path_for_venue(date, venue)
        )
        plan = read_json_file(path)
        if not isinstance(plan, dict):
            out["venues"][venue] = {"plan": "absent"}
            continue
        trial = copy.deepcopy(plan)
        if book != "live":
            # paper2 keeps rows live could never place; measure only the ones it could.
            trial["positions"] = [p for p in trial.get("positions") or [] if pc.placeable_refusal(p) is None]
            plan = {**plan, "positions": copy.deepcopy(trial["positions"])}
            plan["totals"] = {"staked_dollars": round(sum(float(p.get("stake_dollars") or 0) for p in plan["positions"]), 2)}
        # The SAME dict objects the step stamps, kept before refused ones are
        # dropped from `trial["positions"]`, so a refusal's reason stays readable.
        stamped = {p.get("position_key"): p for p in trial.get("positions") or [] if isinstance(p, dict)}
        refusals: dict[str, int] = {}
        by_market: dict[str, dict[str, int]] = {}
        by_sport: dict[str, dict[str, int]] = {}
        os.environ["SYNDICATE_COMPOUNDING_BANKROLL"] = "on"
        try:
            pc._apply_compounding_bankroll(
                trial, venue=venue, settings=settings,
                refusals=refusals, by_market=by_market, by_sport=by_sport,
            )
        finally:
            os.environ.pop("SYNDICATE_COMPOUNDING_BANKROLL", None)
        rows = []
        for position in plan.get("positions") or []:
            key = position.get("position_key")
            match = next((p for p in trial.get("positions") or [] if p.get("position_key") == key), None)
            rows.append(
                {
                    "sport": position.get("sport"),
                    "market": position.get("market"),
                    "ticker": position.get("venue_ticker") if not isinstance(position.get("venue_ticker"), dict) else position["venue_ticker"].get("slug"),
                    "stake_fraction": position.get("stake_fraction"),
                    "stake_fixed": position.get("stake_dollars"),
                    "stake_compounded": (match or {}).get("stake_dollars"),
                    "kept": match is not None,
                    "compounding": (stamped.get(key) or {}).get("compounding"),
                }
            )
        out["venues"][venue] = {
            "plan_generated_at": plan.get("generated_at"),
            "positions_in": len(plan.get("positions") or []),
            "positions_out": len(trial.get("positions") or []),
            "staked_fixed": (plan.get("totals") or {}).get("staked_dollars"),
            "staked_compounded": (trial.get("totals") or {}).get("staked_dollars"),
            "refusals_added": refusals,
            "summary": trial.get("compounding"),
            "positions": rows,
        }
    return out


def _measure_caps() -> dict[str, Any]:
    from syndicate.features.shared import execution_guard as guard

    result: dict[str, Any] = {}
    for label, flag in (("off", None), ("on", "on")):
        if flag:
            os.environ["SYNDICATE_EXECUTION_BALANCE_CAPS"] = flag
        else:
            os.environ.pop("SYNDICATE_EXECUTION_BALANCE_CAPS", None)
        result[label] = {
            venue: {
                key: guard.limits("live", venue=venue).get(key)
                for key in ("max_order_dollars", "max_day_dollars", "max_day_dollars_all_venues")
            }
            for venue in VENUES
        }
        if flag:
            result["on_detail"] = guard.limits("live").get("balance_caps")
    os.environ.pop("SYNDICATE_EXECUTION_BALANCE_CAPS", None)
    return result


def _replay_orders(date: str, caps_on: dict[str, Any]) -> dict[str, Any]:
    from syndicate.features.shared.execution_guard import _SPENT_STATUSES, _is_venue_refusal
    from syndicate.features.shared.execution_ledger import LIVE, _load

    orders = [
        o for o in (_load().get("orders") or [])
        if str(o.get("mode")) == LIVE and str(o.get("selected_date") or "") == date
        and str(o.get("status") or "") in _SPENT_STATUSES and not _is_venue_refusal(o)
    ]
    orders.sort(key=lambda o: str(o.get("submitted_at") or ""))
    spent = {venue: 0.0 for venue in VENUES}
    total = 0.0
    rows = []
    for order in orders:
        venue = str(order.get("venue") or "")
        stake = float(order.get("fill_stake_dollars") or order.get("requested_stake_dollars") or 0.0)
        caps = caps_on.get(venue) or {}
        verdict = "allowed"
        if stake > float(caps.get("max_order_dollars") or 0.0):
            verdict = "over_max_order_dollars"
        elif spent.get(venue, 0.0) + stake > float(caps.get("max_day_dollars") or 0.0):
            verdict = "over_max_day_dollars"
        elif total + stake > float(caps.get("max_day_dollars_all_venues") or 0.0):
            verdict = "over_max_day_dollars_all_venues"
        if verdict == "allowed":
            spent[venue] = spent.get(venue, 0.0) + stake
            total += stake
        rows.append({"venue": venue, "sport": order.get("sport"), "stake": round(stake, 2), "verdict": verdict,
                     "submitted_at": order.get("submitted_at")})
    return {"orders": len(rows), "refused": sum(1 for r in rows if r["verdict"] != "allowed"), "rows": rows}


def _measure_ledger(dates: list[str], caps_on: dict[str, Any], caps_off: dict[str, Any]) -> dict[str, Any]:
    """Re-size the ledger's own orders against today's capital. The plans are
    rewritten every build, so the ORDERS are the population that survives.

    Each order was sized as `fraction x fixed bankroll`, so `fraction =
    requested_stake / fixed` (whole-contract rounding moves this by under a
    contract). The paper venue books (`paper:kalshi`, `paper:polymarket`) are
    the same plans live places from, at the same settings.
    """
    from pipeline import portfolio_commit as pc
    from syndicate.features.shared.execution_guard import _SPENT_STATUSES, _is_venue_refusal
    from syndicate.features.shared.execution_ledger import _load
    from syndicate.features.shared.portfolio_settings import resolve_settings

    settings = resolve_settings()
    fixed = float(settings.bankroll_units)
    resolvers = {venue: pc.default_bankroll_resolver(venue, settings) for venue in VENUES}
    books: dict[str, Any] = {}
    for order in _load().get("orders") or []:
        if str(order.get("selected_date") or "") not in dates:
            continue
        book = str(order.get("venue") or "")
        venue = book.split(":", 1)[1] if book.startswith("paper:") else book
        if venue not in VENUES:
            continue
        if str(order.get("status") or "") not in _SPENT_STATUSES or _is_venue_refusal(order):
            continue
        try:
            stake = float(order.get("requested_stake_dollars") or 0.0)
        except (TypeError, ValueError):
            continue
        verdict = resolvers[venue]({"venue_ticker": order.get("venue_ticker")})
        entry = books.setdefault(book, {
            "orders": 0, "fixed_dollars": 0.0, "compounded_dollars": 0.0,
            "below_min_stake": 0, "unknown": {}, "shards": {}, "bankrolls": {},
            "over_order_cap_off": 0, "over_order_cap_on": 0,
        })
        entry["orders"] += 1
        entry["fixed_dollars"] += stake
        if stake > float((caps_off.get(venue) or {}).get("max_order_dollars") or 0.0):
            entry["over_order_cap_off"] += 1
        if not verdict.get("known"):
            reason = str(verdict.get("reason"))
            entry["unknown"][reason] = entry["unknown"].get(reason, 0) + 1
            continue
        compounded = round(stake / fixed * float(verdict["bankroll"]), 2)
        if verdict.get("shard") is not None:
            key = str(verdict["shard"])
            entry["shards"][key] = entry["shards"].get(key, 0) + 1
        bankroll_key = f"{verdict['bankroll']:.2f}"
        entry["bankrolls"][bankroll_key] = entry["bankrolls"].get(bankroll_key, 0) + 1
        if compounded < float(settings.min_stake_units):
            entry["below_min_stake"] += 1
            continue
        entry["compounded_dollars"] += compounded
        if compounded > float((caps_on.get(venue) or {}).get("max_order_dollars") or 0.0):
            entry["over_order_cap_on"] += 1
    for entry in books.values():
        entry["fixed_dollars"] = round(entry["fixed_dollars"], 2)
        entry["compounded_dollars"] = round(entry["compounded_dollars"], 2)
    return {"dates": dates, "fixed_bankroll": fixed, "books": books}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--book", choices=("live", "paper2"), default="live",
                        help="paper2 = the venue comparison book, placeable positions only")
    parser.add_argument("--ledger-dates", default="",
                        help="comma-separated dates whose ledger orders are re-sized against today's capital")
    args = parser.parse_args(argv)

    from syndicate.features.shared.venue_capital import venue_capital
    from syndicate.features.shared.venue_balances import read_venue_balances

    stamp = read_venue_balances()
    report = {
        "date": args.date,
        "stamp_recorded_at": (stamp or {}).get("recorded_at"),
        "capital": {venue: venue_capital(venue, stamp) for venue in VENUES},
        "book": args.book,
        "sizing": _measure_sizing(args.date, args.book),
    }
    report["caps"] = _measure_caps()
    report["replay"] = _replay_orders(args.date, report["caps"]["on"])
    ledger_dates = [d.strip() for d in args.ledger_dates.split(",") if d.strip()]
    if ledger_dates:
        report["ledger"] = _measure_ledger(ledger_dates, report["caps"]["on"], report["caps"]["off"])
        for book, entry in sorted(report["ledger"]["books"].items()):
            print(
                f"[compounding_paper] ledger book={book} orders={entry['orders']} "
                f"fixed=${entry['fixed_dollars']} compounded=${entry['compounded_dollars']} "
                f"below_min_stake={entry['below_min_stake']} unknown={entry['unknown']} "
                f"shards={entry['shards']} bankrolls={entry['bankrolls']} "
                f"over_order_cap off={entry['over_order_cap_off']} on={entry['over_order_cap_on']}",
                flush=True,
            )

    for venue in VENUES:
        cap = report["capital"][venue]
        sizing = report["sizing"]["venues"].get(venue) or {}
        print(
            f"[compounding_paper] venue={venue} capital_known={cap.get('known')} capital=${cap.get('capital')} "
            f"basis={cap.get('basis')} reason={cap.get('reason')} | positions {sizing.get('positions_out')}/{sizing.get('positions_in')} "
            f"staked fixed=${sizing.get('staked_fixed')} compounded=${sizing.get('staked_compounded')} "
            f"refusals={sizing.get('refusals_added')} | caps off={report['caps']['off'][venue]} on={report['caps']['on'][venue]}",
            flush=True,
        )
    print(
        f"[compounding_paper] replay date={args.date} live_orders={report['replay']['orders']} "
        f"refused_under_balance_caps={report['replay']['refused']}",
        flush=True,
    )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
