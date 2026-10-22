"""Which write path left LIVE execution-ledger orders without `ev_pct` / a price.

Todo #728, lane `live-order-ev-pct-gap`. READ-ONLY: loads the ledger document
and the disk archive, writes nothing to either.

WHY KEY PRESENCE AND NOT `.get()`. A field added by a later builder is ABSENT
on rows an older builder wrote and NULL on rows the new builder wrote with
nothing to record (learnings 2026-10-22, "KEY ABSENT"). `.get()` folds the two.
So every field is classified three ways -- `absent` / `null` / `value` -- and
the set of attribution keys a row carries is its BUILDER SIGNATURE:

  ev_pct, model_edge_pct        OrderRequest since 04187cdf (2026-09-03)
  sim_view ...                  later
  side_picked_by ...            later
  staked_probability_version    #722 (2026-10-21)
  source=venue_rebuild          venue_ledger_rebuild (2026-10-02), not a placement

"No price" uses the fitters' own lookup: the first of `requested_price`,
`fill_price`, `price` that parses as a number (`fit_staked_probability.derive_row`).

Run on the fleet with the fleet venv -- the system python3 has no `redis` and
reads the live document as EMPTY with no error. The script refuses (exit 4)
unless the keyvalue read succeeded.

    nice -n 19 env PYTHONPATH=~/Syndicate SYNDICATE_REFRESH_STATE_BACKEND=keyvalue \\
      SYNDICATE_REFRESH_STATE_URL=redis://127.0.0.1:6379/0 \\
      SYNDICATE_REPORTS_ROOT=/home/amyn/syndicate-prod/data/reports \\
      /home/amyn/.venvs/syndicate/bin/python scripts/ledger_live_ev_pct_census.py [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping

SETTLED_OUTCOMES = {"win", "loss", "push", "void", "won", "lost"}

# (label, key) in the order the builder grew them.
SIGNATURE_KEYS = (
    ("ev", "ev_pct"),
    ("sim", "sim_view"),
    ("attr", "side_picked_by"),
    ("sizing", "staked_probability_version"),
)


def tri(row: Mapping[str, Any], key: str) -> str:
    if key not in row:
        return "absent"
    value = row[key]
    if value is None or (isinstance(value, str) and not value.strip()):
        return "null"
    return "value"


def as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def has_price(row: Mapping[str, Any]) -> bool:
    return any(as_float(row.get(k)) is not None for k in ("requested_price", "fill_price", "price"))


def signature(row: Mapping[str, Any]) -> str:
    if str(row.get("source") or "") == "venue_rebuild":
        return "venue_rebuild"
    present = [label for label, key in SIGNATURE_KEYS if key in row]
    return "+".join(present) if present else "pre-ev(no attribution keys)"


def is_settled(row: Mapping[str, Any]) -> bool:
    outcome = str(row.get("outcome") or "").strip().lower()
    return bool(outcome) and outcome != "none"


def day_of(row: Mapping[str, Any]) -> str:
    stamp = str(row.get("submitted_at") or "")[:10]
    return stamp or ("sel:" + str(row.get("selected_date") or "?"))


def week_of(row: Mapping[str, Any]) -> str:
    day = str(row.get("submitted_at") or row.get("selected_date") or "")[:10]
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return "undated"
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="write the full census here")
    parser.add_argument("--all-modes", action="store_true", help="also tabulate paper (default: live only)")
    args = parser.parse_args()

    from syndicate.features.shared import execution_ledger as el
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    doc, ok = read_json_file_result(el._ledger_path())
    if ok is not True:
        print(f"REFUSE: ledger keyvalue read failed (ok={ok!r}); a count now would be the archive alone", flush=True)
        return 4
    doc_orders = list((doc or {}).get("orders") or [])
    doc_ids = {el._order_identity(o) for o in doc_orders if isinstance(o, Mapping)}
    orders = el.full_history_orders()
    read_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = [o for o in orders if isinstance(o, Mapping) and (args.all_modes or str(o.get("mode") or "") == el.LIVE)]
    live_all = [o for o in orders if isinstance(o, Mapping) and str(o.get("mode") or "") == el.LIVE]
    settled = [o for o in live_all if is_settled(o)]

    print(f"read_at={read_at} ledger_path={el._ledger_path()} keyvalue_ok={ok}", flush=True)
    print(f"orders total={len(orders)} document={len(doc_orders)} archive_only={len(orders) - len(doc_orders)}")
    print(f"live={len(live_all)} live_settled={len(settled)}")
    print(f"settled live outcomes: {dict(Counter(str(o.get('outcome')) for o in settled))}")

    # The fitter's own drop order: no_price first, then no_ev_pct.
    def fitter_reason(o: Mapping[str, Any]) -> str:
        if not has_price(o):
            return "no_price"
        if as_float(o.get("ev_pct")) is None:
            return "no_ev_pct"
        return "usable"

    reason_counts = Counter(fitter_reason(o) for o in settled)
    print(f"\nsettled live, fitter drop order: {dict(reason_counts)}")
    print(f"settled live, independent: no_ev_pct={sum(1 for o in settled if as_float(o.get('ev_pct')) is None)}"
          f" no_price={sum(1 for o in settled if not has_price(o))}")

    table: dict[tuple, Counter] = defaultdict(Counter)
    detail: list[dict[str, Any]] = []
    for o in settled:
        sig = signature(o)
        ev = tri(o, "ev_pct")
        priced = "priced" if has_price(o) else "NO_PRICE"
        where = "doc" if el._order_identity(o) in doc_ids else "archive"
        table[(sig,)][f"ev_{ev}|{priced}"] += 1
        detail.append({
            "sig": sig, "ev": ev, "priced": priced, "where": where,
            "venue": o.get("venue"), "sport": o.get("sport"), "market": o.get("market"),
            "segment": o.get("segment"), "status": o.get("status"),
            "day": day_of(o), "week": week_of(o), "selected_date": o.get("selected_date"),
            "submitted_at": o.get("submitted_at"),
            "has_position_key": bool(str(o.get("position_key") or "").strip()),
            "model_edge": tri(o, "model_edge_pct"),
            "req_price": tri(o, "requested_price"), "fill_price": tri(o, "fill_price"),
            "source": o.get("source"),
        })

    print("\n== settled live by BUILDER SIGNATURE x (ev_pct state | price) ==")
    for (sig,), counts in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {sig:<34} n={sum(counts.values()):>4}  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    def crosstab(label: str, keyfn) -> None:
        print(f"\n== settled live by {label} (rows: n, ev absent/null/value, no_price, usable) ==")
        groups: dict[str, list[dict]] = defaultdict(list)
        for d in detail:
            groups[keyfn(d)].append(d)
        for key in sorted(groups):
            g = groups[key]
            ev = Counter(d["ev"] for d in g)
            usable = sum(1 for d in g if d["ev"] == "value" and d["priced"] == "priced")
            print(f"  {key:<44} n={len(g):>4}  ev a/n/v={ev['absent']:>3}/{ev['null']:>3}/{ev['value']:>3}"
                  f"  no_price={sum(1 for d in g if d['priced'] == 'NO_PRICE'):>3}  usable={usable:>3}")

    crosstab("week x signature", lambda d: f"{d['week']} {d['sig']}")
    crosstab("venue x signature", lambda d: f"{d['venue']} {d['sig']}")
    crosstab("venue x sport x market (ev null, current builder only)",
             lambda d: f"{d['venue']} {d['sport']} {d['market']}" if d["ev"] == "null" and d["sig"] != "venue_rebuild" else "~other")
    crosstab("day (ev null, non-rebuild)", lambda d: d["day"] if d["ev"] == "null" and d["sig"] != "venue_rebuild" else "~other")
    crosstab("where stored", lambda d: f"{d['where']} {d['sig']}")
    crosstab("position_key present x signature", lambda d: f"pk={d['has_position_key']} {d['sig']}")
    crosstab("model_edge state x ev state (non-rebuild)",
             lambda d: f"edge_{d['model_edge']} ev_{d['ev']}" if d["sig"] != "venue_rebuild" else "~rebuild")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"read_at": read_at, "keyvalue_ok": ok, "orders": len(orders),
                       "document": len(doc_orders), "live": len(live_all), "live_settled": len(settled),
                       "fitter_reasons": dict(reason_counts), "rows": detail}, handle, indent=1, default=str)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
