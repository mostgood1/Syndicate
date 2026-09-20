r"""Measure dP/dLine per (sport, market, side) from the board we already publish.

WHY THIS EXISTS. Lane `layer2-line-move-magnitude`. The Layer 2 board scores a
LINE move with a magnitude of `|fair_now - fair_open|`, and those two fair
probabilities sit at DIFFERENT HANDICAPS. That number therefore mixes the
handicap change with the market's repricing, and it can contradict its own sign:

    home +1.0 @ -104  (p .5098)  ->  home -1.5 @ +122  (p .4505)

the probability FALLS 5.94 pp while `_line_move_vs_pick` correctly calls that
move **toward** the pick. An implied-from-price variant of the same comparison
was tried and reverted (it reached steam).

THE REPLACEMENT, and what this script supplies the missing term for:

    magnitude_pp = |line_delta| * slope(sport, market, side)
    sign         = _line_move_vs_pick(side, line_delta)     # unchanged

Both halves then derive from the LINE DELTA, so they cannot disagree by
construction. The price at the new handicap stops entering the line term at all.

WHERE THE SLOPE COMES FROM, and why it does not need new plumbing. The served
board already carries the SAME bet at several handicaps at the SAME instant --
alternate lines are published side by side. Differencing adjacent lines within
one (sport, event, market, segment, player, side) gives dP/dLine directly, with
no model and no fitting. Measured 2026-09-20 on one 2,000-row board: **339 of
864 identities carried 2+ distinct lines**, yielding 726 adjacent pairs.

PER MARKET, NOT PER FAMILY, AND THIS IS THE LOAD-BEARING CHOICE. `market_family`
lumps every NFL prop into `other`, where a one-unit move means something
completely different per market. Measured on the same board:

    nfl totals          over   -2.964 pp per point   (typical line 32.5)
    nfl Receiving Yards over   -0.488 pp per yard    (typical line 33.5)
    nfl Rushing Yards   over   -0.305 pp per yard    (typical line 28.5)

A 6x spread inside one "family". A family-level slope would be wrong for most of
its own members.

WHAT IS FILTERED, each counted rather than dropped silently:
  - `fair_probability` exactly 0.5 -- the devig fallback when only one side is
    quoted. Left in, it flattens every slope toward zero.
  - non-adjacent line pairs -- only neighbours are differenced, so curvature
    over a wide gap is not read as a steeper slope.

WRONG-SIGN RATE IS REPORTED, NOT HIDDEN. An `over` slope must be negative and an
`under` slope positive; anything else is a data fault (stale devig, a book
switch between the two rows, a mispriced alternate). Measured 0% on wnba
spreads and 15-26% on NFL props. **A cell whose wrong-sign rate is high should
not be used**, and the caller decides that with the number in front of it rather
than inheriting a median that quietly averaged noise.

Read-only. Reads `/api/board/layer2-shortlist` and writes nothing to production.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import statistics as st
import urllib.request
from typing import Any

BASE = os.environ.get("SYNDICATE_BASE_URL", "https://syndicate-an21.onrender.com")

#: Below this, a cell's median is noise. Reported anyway, flagged `thin`.
MIN_PAIRS_PER_CELL = 10
#: The devig fallback value. A fair of exactly 0.5 is almost never a measurement.
DEVIG_PLACEHOLDER = 0.5


def fetch_board(limit: int = 2000, date: str | None = None) -> dict[str, Any]:
    url = f"{BASE}/api/board/layer2-shortlist?limit={limit}"
    if date:
        url += f"&date={date}"
    with urllib.request.urlopen(url, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def identity(row: Any) -> tuple:
    """The bet, EXCLUDING its line -- which is the axis we are differencing."""
    return (
        row.get("sport"),
        row.get("event_id"),
        row.get("market"),
        row.get("segment"),
        row.get("player_name"),
        str(row.get("side") or "").strip().lower(),
    )


def collect_pairs(rows: list) -> tuple[dict, dict]:
    """`(sport, market, side) -> [slope, ...]` and the exclusion counters."""
    by_identity: dict[tuple, list] = collections.defaultdict(list)
    stats = collections.Counter()
    for row in rows or ():
        stats["rows"] += 1
        quote = row.get("quote") if isinstance(row.get("quote"), dict) else {}
        fair, line = quote.get("fair_probability"), row.get("line")
        if fair is None or line is None:
            stats["no_fair_or_no_line"] += 1
            continue
        if abs(float(fair) - DEVIG_PLACEHOLDER) <= 1e-9:
            stats["devig_placeholder_excluded"] += 1
            continue
        by_identity[identity(row)].append((float(line), float(fair)))

    slopes: dict[tuple, list] = collections.defaultdict(list)
    wrong: collections.Counter = collections.Counter()
    for key, points in by_identity.items():
        points = sorted(set(points))
        if len(points) < 2:
            stats["identity_single_line"] += 1
            continue
        stats["identity_multi_line"] += 1
        side = key[5]
        for lower, upper in zip(points, points[1:]):
            delta_line = upper[0] - lower[0]
            if delta_line <= 0:
                continue
            slope = ((upper[1] - lower[1]) * 100.0) / delta_line
            cell = (key[0], key[2], side)
            slopes[cell].append(slope)
            stats["pairs"] += 1
            # An `over` must fall as its line rises; an `under` must rise.
            if (side == "over" and slope > 0) or (side == "under" and slope < 0):
                wrong[cell] += 1
    return slopes, {"stats": stats, "wrong": wrong}


def summarise(slopes: dict, wrong: collections.Counter) -> list[dict]:
    out = []
    for cell, values in slopes.items():
        values = sorted(values)
        n = len(values)
        out.append(
            {
                "sport": cell[0],
                "market": cell[1],
                "side": cell[2],
                "n_pairs": n,
                "median_pp_per_unit": round(st.median(values), 4),
                "q1": round(values[n // 4], 4),
                "q3": round(values[(3 * n) // 4], 4),
                "wrong_sign_rate": round(wrong[cell] / n, 4) if n else None,
                "thin": n < MIN_PAIRS_PER_CELL,
            }
        )
    return sorted(out, key=lambda r: (-r["n_pairs"], r["sport"], r["market"]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--date", default=None)
    parser.add_argument("--json-out", default=None)
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=MIN_PAIRS_PER_CELL,
        help="cells below this are printed but flagged `thin`; none are hidden.",
    )
    args = parser.parse_args()

    payload = fetch_board(limit=args.limit, date=args.date)
    rows = payload.get("rows") or []
    slopes, extra = collect_pairs(rows)
    stats, wrong = extra["stats"], extra["wrong"]
    summary = summarise(slopes, wrong)

    print(f"board written_at {payload.get('written_at')}  rows {len(rows)}", flush=True)
    print("\n=== POPULATION ===", flush=True)
    for key in (
        "rows",
        "no_fair_or_no_line",
        "devig_placeholder_excluded",
        "identity_single_line",
        "identity_multi_line",
        "pairs",
    ):
        print(f"  {key:30} {stats[key]}", flush=True)

    if not stats["pairs"]:
        print(
            "\nREFUSING TO REPORT A SLOPE: zero adjacent line pairs.\n"
            "  The board published no identity at two handicaps at once, so dP/dLine\n"
            "  is not observable in this frame. A null result needs a live population.",
            flush=True,
        )
        return 4

    print(f"\n=== dP/dLine, probability points per unit of line ===", flush=True)
    print(f"{'sport':8} {'market':26} {'side':6} {'n':>5} {'median':>9} {'IQR':>18} {'wrong':>6}", flush=True)
    for r in summary:
        flag = "  <- THIN" if r["thin"] else ""
        iqr = f"[{r['q1']:.2f},{r['q3']:.2f}]"
        print(
            f"{r['sport']:8} {r['market'][:26]:26} {r['side'][:6]:6} {r['n_pairs']:>5} "
            f"{r['median_pp_per_unit']:>9.3f} {iqr:>18} {r['wrong_sign_rate']:>6.0%}{flag}",
            flush=True,
        )

    usable = [r for r in summary if not r["thin"]]
    print(
        f"\n{len(usable)} cell(s) at n>={args.min_pairs}, {len(summary) - len(usable)} thin. "
        f"A HIGH wrong-sign rate means the cell's median averaged noise -- do not "
        f"use it because it has n.",
        flush=True,
    )

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "written_at": payload.get("written_at"),
                    "population": dict(stats),
                    "cells": summary,
                },
                handle,
                indent=2,
            )
        print(f"wrote {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
