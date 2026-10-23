"""Longshot audit: stake share and settled ROI by entry price bucket, per book (lane in-game-trading).

USER ASK 2026-10-23: "Audit our pregame live/paper books by price bucket: stake share and settled
ROI below 15c, to see if we should add a longshot floor."

Input: the execution-ledger ARCHIVE (graded orders moved out of the live ledger), e.g.
~/syndicate-prod/data/reports/intelligence/execution_ledger_archive/orders_2026-10.jsonl, copied
read-only. PREGAME only: submitted_at < commence_time. Price -> implied probability: a value in
(0,1) is a venue price; |value| >= 100 is American odds. Graded rows only (won / lost / push).

ROI = sum(pnl) / sum(stake). The CI is CLUSTERED BY GAME (event_id + selected_date): per-game
pnl and stake sums, ratio-of-means with a delta-method standard error, because one game can carry
several correlated orders.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime

BUCKETS = [(0.0, 0.10), (0.10, 0.15), (0.15, 0.25), (0.25, 0.40), (0.40, 0.60), (0.60, 0.75), (0.75, 0.90),
           (0.90, 1.01)]


def implied(price):
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if 0 < p < 1:
        return p
    if p >= 100:
        return 100.0 / (p + 100.0)
    if p <= -100:
        return -p / (-p + 100.0)
    return None


def ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def clustered_roi(groups):
    """groups: list of (pnl_sum, stake_sum) per game -> (roi, lo, hi)."""
    n = len(groups)
    P = sum(g[0] for g in groups)
    S = sum(g[1] for g in groups)
    if n < 2 or S <= 0:
        return (P / S if S else None), None, None
    r = P / S
    resid = [(p - r * s) for p, s in groups]
    var = n / (n - 1) * sum(e * e for e in resid) / (S * S)
    se = math.sqrt(var)
    return r, r - 1.96 * se, r + 1.96 * se


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", nargs="+")
    ap.add_argument("--min-orders", type=int, default=15)
    a = ap.parse_args()
    rows = []
    for path in a.archive:
        rows += [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    skipped = defaultdict(int)
    cells = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))  # (book, bucket) -> game -> [pnl, stake]
    book_stake = defaultdict(float)
    counts = defaultdict(int)
    for r in rows:
        if r.get("outcome") not in ("won", "lost", "push"):
            skipped["ungraded"] += 1
            continue
        sub, com = ts(r.get("submitted_at")), ts(r.get("commence_time"))
        if sub is None or com is None or sub >= com:
            skipped["not_pregame_or_unknown_time"] += 1
            continue
        p = implied(r.get("fill_price") if r.get("fill_price") not in (None, "") else r.get("requested_price"))
        stake = r.get("fill_stake_dollars") or r.get("requested_stake_dollars")
        pnl = r.get("pnl_dollars")
        if p is None or not stake or pnl is None:
            skipped["no_price_stake_or_pnl"] += 1
            continue
        b = next(bk for bk in BUCKETS if bk[0] <= p < bk[1])
        book = str(r.get("venue") or r.get("mode"))
        game = f"{r.get('event_id')}|{r.get('selected_date')}"
        for bk_name in (book, "ALL BOOKS"):
            c = cells[(bk_name, b)][game]
            c[0] += float(pnl)
            c[1] += float(stake)
            counts[(bk_name, b)] += 1
            book_stake[bk_name] += float(stake)
    dates = sorted({r.get("selected_date") for r in rows if r.get("selected_date")})
    print(f"ARCHIVE rows={len(rows)} dates {dates[0]}..{dates[-1]}  skipped={dict(skipped)}")
    print("PREGAME graded orders; ROI = pnl/stake with a GAME-clustered 95% CI\n")
    books = sorted({k[0] for k in cells}, key=lambda b: (b != "ALL BOOKS", b))
    for book in books:
        print(f"=== {book}  (stake ${book_stake[book]:,.0f})")
        for b in BUCKETS:
            if (book, b) not in cells:
                continue
            g = cells[(book, b)]
            n = counts[(book, b)]
            stake = sum(v[1] for v in g.values())
            roi, lo, hi = clustered_roi(list(g.values()))
            share = stake / book_stake[book]
            ci = "" if lo is None else f"[{lo:+.1%},{hi:+.1%}]"
            flag = "  <-- below 15c" if b[1] <= 0.15 else ""
            thin = " (thin)" if n < a.min_orders else ""
            print(f"  p {b[0]:.2f}-{min(b[1], 1.0):.2f}  orders={n:5d} games={len(g):4d} stake={share:6.1%}"
                  f"  ROI {roi:+.1%} {ci}{thin}{flag}")
        lo_g = defaultdict(lambda: [0.0, 0.0])
        for b in BUCKETS:
            if b[1] <= 0.15 and (book, b) in cells:
                for gm, v in cells[(book, b)].items():
                    lo_g[gm][0] += v[0]
                    lo_g[gm][1] += v[1]
        if lo_g:
            roi, lo, hi = clustered_roi(list(lo_g.values()))
            st = sum(v[1] for v in lo_g.values())
            ci = "" if lo is None else f"[{lo:+.1%},{hi:+.1%}]"
            print(f"  ** BELOW 15c combined: stake share {st / book_stake[book]:.1%}, games={len(lo_g)}, ROI {roi:+.1%} {ci}")
        print()


if __name__ == "__main__":
    main()
