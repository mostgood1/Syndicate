"""Durable daily rollup for the local Portfolio Watch: the live book's history from its first graded bet.

Rebuilt every run from the fleet ledger (the newest saved `/api/portfolio/live?on=all&show=all`, which carries every
live order since trading began), plus each day's operations from the probe's reading log. Written to
paths.HISTORY / daily_rollup.json, a folder the runner never prunes. If the ledger cannot be read, the previous
rollup is kept, never replaced with an empty one.

Same instrument as the probe (`live_book_edge_readout`): dollar ROI with an event-clustered 95% range, wins against
the breakeven of the prices paid, fee-net same-book CLV. Percentages and counts only, no dollar amounts.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import paths  # noqa: E402
READINGS = paths.READINGS
HISTORY = paths.HISTORY
OUT = HISTORY / "daily_rollup.json"
RB_DIR = paths.REPO_SCRIPTS
CT = dt.timezone(dt.timedelta(hours=-6))


def newest_live_all() -> Path | None:
    for d in sorted((p for p in READINGS.glob("2026*") if p.is_dir()), reverse=True):
        f = d / "live_all.json"
        if f.exists() and f.stat().st_size > 1000:
            return f
    return None


def keep(s: dict | None, prefix: str) -> dict:
    s = s or {}
    return {f"{prefix}bets": s.get("bets"), f"{prefix}events": s.get("events"), f"{prefix}roi_pct": s.get("roi_pct"),
            f"{prefix}roi_lo95": s.get("roi_lo95_pct"), f"{prefix}roi_hi95": s.get("roi_hi95_pct")}


def anomaly_signature(text: str) -> str:
    """One anomaly's identity across readings: its text with every number blanked.

    A persistent issue is re-flagged at every reading with fresh numbers ("resting 134 min", then "resting 164 min";
    "live_today slow: 4.22s", then "3.27s"). Summing those lines per day counted one open grade conflict 18 times on
    11-21 and read as "23 anomalies" (fleet-watcher, 11-21 10 AM). The day's count is the number of distinct issues.
    """
    return re.sub(r"\d+(?:\.\d+)?", "#", str(text)).strip()


def ops_by_day() -> dict[str, dict]:
    """Per CST day: readings, distinct non-GATE anomalies, every anomaly line (per reading), slow live reads."""
    out: dict[str, dict] = collections.defaultdict(lambda: {"readings": 0, "anomalies": 0, "anomaly_lines": 0,
                                                             "live_over_2s": 0, "live_over_3s": 0})
    distinct: dict[str, set[str]] = collections.defaultdict(set)
    try:
        lines = (READINGS / "readings.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        at = r.get("at")
        if not at:
            continue
        day = dt.datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(CT).date().isoformat()
        o = out[day]
        o["readings"] += 1
        lines_ = [str(a) for a in (r.get("anomalies") or []) if not str(a).startswith("GATE")]
        o["anomaly_lines"] += len(lines_)
        distinct[day].update(anomaly_signature(a) for a in lines_)
        o["anomalies"] = len(distinct[day])
        s = ((r.get("endpoints") or {}).get("live_today") or {}).get("seconds")
        if s is not None:
            o["live_over_2s"] += s > 2
            o["live_over_3s"] += s > 3
    return out


def main() -> int:
    src = newest_live_all()
    if src is None:
        print("no saved live_all.json; rollup kept as is")
        return 0
    try:
        orders = json.loads(src.read_text(encoding="utf-8")).get("orders") or []
    except (OSError, ValueError) as e:
        print(f"ledger unreadable ({e}); rollup kept as is")
        return 0
    if not orders:
        print("ledger empty; rollup kept as is")
        return 0
    sys.path.insert(0, str(RB_DIR))
    import live_book_edge_readout as rb

    bets = rb.bets_from_orders(orders)
    if not bets:
        print("no graded bets; rollup kept as is")
        return 0
    days = sorted({b.date for b in bets})
    first, last = dt.date.fromisoformat(days[0]), dt.date.fromisoformat(days[-1])
    order_days: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for o in orders:
        order_days[str(o.get("selected_date") or "")][str(o.get("status") or "")] += 1
    ops = ops_by_day()
    rows = []
    d = first
    while d <= last:
        ds = d.isoformat()
        day = rb.summarize(rb.window_bets(bets, ds, ds))
        w7 = rb.summarize(rb.window_bets(bets, (d - dt.timedelta(days=6)).isoformat(), ds))
        w30_bets = rb.window_bets(bets, (d - dt.timedelta(days=29)).isoformat(), ds)
        w30 = rb.summarize(w30_bets)
        clv_day = rb.clv_summary(rb.window_bets(bets, ds, ds)).get(rb.SCOPE_SAME_BOOK) or {}
        clv30 = rb.clv_summary(w30_bets).get(rb.SCOPE_SAME_BOOK) or {}
        oc = order_days.get(ds, collections.Counter())
        row = {"date": ds, **keep(day, ""),
               "win_pct": (day or {}).get("win_pct"), "breakeven_pct": (day or {}).get("breakeven_win_pct"),
               "fee_pct": (day or {}).get("fee_pct_of_stake"),
               "roi_before_fees_pct": (day or {}).get("roi_before_fees_pct"),
               "clv_net_pp": clv_day.get("clv_net_pp"), "clv_n": clv_day.get("clv_net_bets"),
               **keep(w7, "r7_"), **keep(w30, "r30_"),
               "r30_fee_pct": (w30 or {}).get("fee_pct_of_stake"), "r30_clv_net_pp": clv30.get("clv_net_pp"),
               "orders": sum(oc.values()), "filled": oc.get("filled", 0),
               "not_filled": sum(n for s, n in oc.items() if s in ("rejected", "failed", "canceled", "cancelled", "expired")),
               **ops.get(ds, {"readings": 0, "anomalies": None, "anomaly_lines": None, "live_over_2s": None,
                              "live_over_3s": None})}
        rows.append(row)
        d += dt.timedelta(days=1)
    allb = rb.summarize(bets) or {}
    meta = [{"label": "Source", "value": f"fleet ledger /api/portfolio/live?on=all&show=all saved {src.parent.name}"},
            {"label": "First graded live bet", "value": days[0]},
            {"label": "Graded bets", "value": allb.get("bets")},
            {"label": "Built", "value": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}]
    HISTORY.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"rows": rows, "meta": meta}, indent=0), encoding="utf-8")
    os.replace(tmp, OUT)
    print(f"rollup: {len(rows)} days {days[0]}..{days[-1]}, {allb.get('bets')} graded bets -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
