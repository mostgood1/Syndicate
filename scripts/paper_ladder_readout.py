"""Paper ladder readout: per venue x EV band, flat ROI and same-book CLV, with the
pre-registered floor rule. Read-only. Pre-registration:
`.syndicate/findings_2026-10-20_paper_ladder.md` (lane paper-alongside-live).

    py -3 scripts/paper_ladder_readout.py [LEDGER_JSON] [--since ISO] [--cells]

With no LEDGER_JSON it reads `execution_ledger.full_history_orders()` under this
process's state env (run inside WSL with refresh-worker's SYNDICATE_REFRESH_STATE_*
and SYNDICATE_REPORTS_ROOT, at nice 19). LEDGER_JSON is a list of order rows, or
{"orders": [...]}.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from typing import Any, Iterable, Mapping

VENUES = ("kalshi", "polymarket")
BAND_ORDER = ("venue_book", "ge2", "1to2", "0to1", "m1to0")
BELOW_FLOOR = ("1to2", "0to1", "m1to0")
DEFAULT_SINCE = "2026-10-20T16:18:24Z"  # paper recording resumed beside live (1006cb75)
MIN_EVENTS = 100


def _f(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def classify(order: Mapping[str, Any]) -> tuple[str, str] | None:
    """(venue, band) for a paper venue-book or ladder row, else None."""
    venue = str(order.get("venue") or "")
    for name in VENUES:
        if venue == f"paper:{name}":
            return name, "venue_book"
        if venue == f"paper:{name}:ladder":
            band = str(order.get("ev_band") or "")
            return (name, band) if band in BAND_ORDER else None
    return None


def settled_population(orders: Iterable[Mapping[str, Any]], since: str) -> list[dict[str, Any]]:
    """One row per (venue, position_key, selected_date): the venue book wins over the ladder."""
    chosen: dict[tuple, dict[str, Any]] = {}
    for order in orders:
        if str(order.get("mode") or "") != "paper" or str(order.get("status") or "") != "filled":
            continue
        if order.get("outcome") not in ("won", "lost"):
            continue
        if str(order.get("submitted_at") or "") < since:
            continue
        where = classify(order)
        if where is None:
            continue
        stake = _f(order.get("fill_stake_dollars")) or _f(order.get("requested_stake_dollars"))
        pnl = _f(order.get("pnl_dollars"))
        if not stake or pnl is None:
            continue
        mark = order.get("closing_mark") if isinstance(order.get("closing_mark"), Mapping) else {}
        clv = _f(mark.get("clv_pct")) if str(mark.get("close_book_scope") or "") == "same_book" else None
        row = {
            "venue": where[0], "band": where[1], "event": str(order.get("event_id") or ""),
            "date": str(order.get("selected_date") or ""), "ret": pnl / stake, "clv": clv,
            "sport": str(order.get("sport") or ""), "market": str(order.get("market") or ""),
            "phase": str(order.get("season_phase") or ""),
        }
        key = (where[0], str(order.get("position_key") or ""), row["date"])
        incumbent = chosen.get(key)
        if incumbent is None or (incumbent["band"] != "venue_book" and row["band"] == "venue_book"):
            chosen[key] = row
    return list(chosen.values())


def clustered(rows: list[dict[str, Any]], field: str) -> tuple[float | None, float | None, int, int]:
    """Mean of `field` (x100 for returns), event-clustered SE, n rows, n events."""
    values = [(r["event"], r[field]) for r in rows if r[field] is not None]
    if not values:
        return None, None, 0, 0
    by_event: dict[str, list[float]] = defaultdict(list)
    for event, value in values:
        by_event[event].append(value)
    n = len(values)
    mean = sum(v for _e, v in values) / n
    events = len(by_event)
    if events < 2:
        return mean, None, n, events
    resid = [sum(v - mean for v in vs) for vs in by_event.values()]
    se = math.sqrt(sum(r * r for r in resid) * events / (events - 1)) / n
    return mean, se, n, events


def verdict(band: str, roi: tuple, clv: tuple) -> str:
    """The pre-registered rule (findings_2026-10-20_paper_ladder.md, 'Decision rule')."""
    mean, se, _n, events = roi
    clv_mean = clv[0]
    if events < MIN_EVENTS or mean is None or se is None:
        return f"INSUFFICIENT ({events} events < {MIN_EVENTS})"
    if band in BELOW_FLOOR:
        if mean > 0 and mean >= 2 * se and clv_mean is not None and clv_mean > 0:
            return "CANDIDATE: ROI >= 2 SE above 0 and same-book CLV > 0 -- the user may consider lowering this venue's floor to this band"
        if mean <= -2 * se:
            return "AGAINST: ROI >= 2 SE below 0 -- this band loses; keep the floor"
        return "NO CHANGE: straddles 0; keep collecting"
    if mean <= -2 * se:
        return "AGAINST THE CURRENT FLOOR: ROI >= 2 SE below 0 -- consider raising it (cross-check the forward test)"
    return "NO CHANGE"


def report(orders: list[Mapping[str, Any]], since: str, cells: bool) -> None:
    pop = settled_population(orders, since)
    dates = sorted({r["date"] for r in pop})
    print(f"PAPER LADDER since {since}: {len(pop)} settled bets, dates {dates[0] if dates else None}.."
          f"{dates[-1] if dates else None} ({len(dates)})")
    for venue in VENUES:
        print(f"\n{venue}")
        for band in BAND_ORDER:
            rows = [r for r in pop if r["venue"] == venue and r["band"] == band]
            roi = clustered([{**r, "ret": r["ret"] * 100.0} for r in rows], "ret")
            clv = clustered(rows, "clv")
            mean, se, n, events = roi
            print(f"  {band:10s} n={n:4d} events={events:4d} ROI="
                  f"{'n/a' if mean is None else f'{mean:+.1f}'} ± {'n/a' if se is None else f'{se:.1f}'}"
                  f"  same-book CLV={'n/a' if clv[0] is None else f'{clv[0]:+.2f}'} (n={clv[2]})"
                  f"  -> {verdict(band, roi, clv)}")
            if cells and rows:
                by_cell: dict[tuple, list] = defaultdict(list)
                for r in rows:
                    by_cell[(r["sport"], r["market"], r["phase"])].append({**r, "ret": r["ret"] * 100.0})
                for cell, cell_rows in sorted(by_cell.items()):
                    m, s, cn, ce = clustered(cell_rows, "ret")
                    print(f"      {'/'.join(cell)}: n={cn} events={ce} ROI={m:+.1f}"
                          + (f" ± {s:.1f}" if s is not None else "") + "  (descriptive only)")


def _load(argv: list[str]) -> tuple[list[Mapping[str, Any]], str, bool]:
    since = DEFAULT_SINCE
    cells = "--cells" in argv
    args = [a for a in argv if a != "--cells"]
    if "--since" in args:
        i = args.index("--since")
        since = args[i + 1]
        del args[i : i + 2]
    if args:
        payload = json.load(open(args[0], encoding="utf-8"))
        orders = payload.get("orders") if isinstance(payload, dict) else payload
    else:
        from syndicate.features.shared.execution_ledger import full_history_orders

        orders = full_history_orders()
    return list(orders or []), since, cells


if __name__ == "__main__":
    report(*_load(sys.argv[1:]))
