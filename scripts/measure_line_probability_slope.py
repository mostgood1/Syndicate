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
#: OVER/UNDER SYMMETRY CEILING. Over and under are two sides of ONE
#: distribution, so |slope_over| must match |slope_under|. This is the strongest
#: validity test here because it uses no threshold chosen for THIS data -- and
#: the ceiling sits in a natural GAP. Measured 2026-09-20 over 4 boards, the
#: asymmetries were 0,1,1,3,4,4,9 | 20,24,29,62 (%): any ceiling from 10% to 19%
#: gives the identical verdict, so the result does not hinge on this number.
#:
#: WHY SYMMETRY AND NOT WRONG-SIGN RATE as the gate: `nfl Rushing Yards` reads
#: 26-27% wrong-sign pairs yet 1% asymmetry. Individual pairs are noisy; the
#: MEDIAN is well determined. Wrong-sign rate measures per-pair noise, symmetry
#: measures whether the median is trustworthy -- and the median is what a
#: consumer would use. Gating on wrong-sign would have REJECTED a good cell.
MAX_SIDE_ASYMMETRY = 0.15

#: EXISTENCE GATE -- a one-sided sign test that the correct-sign fraction is
#: above one half. SYMMETRY CANNOT ANSWER THIS, which is why it is separate.
#:
#: Symmetry is a RATIO of the two sides' medians, and a ratio of two near-zero
#: numbers is noise. Measured 2026-09-20: `nfl Passing Yards` read 20%
#: asymmetric on one sweep and 2% on the next, because fresh boards moved its
#: medians by ~0.01 at a magnitude of +/-0.05 -- a tenfold swing that let it
#: PASS the symmetry gate by luck while 39-43% of its pairs had the wrong sign.
#: The sign test says what was actually true: p = 0.20 / 0.33, not
#: distinguishable from zero.
#:
#: And it keeps what a wrong-sign-RATE gate would have wrongly thrown out:
#: `nfl Rushing Yards` has 26% wrong-sign pairs but is 74% correct over n=81,
#: p = 8.5e-6. The slope plainly exists; its pairs are merely noisy.
#:
#: Two gates, two questions: this one asks whether there IS a slope, symmetry
#: asks whether its SIZE is right. Neither can stand in for the other.
SIGN_TEST_ALPHA = 0.05


def sign_test_p(correct: int, n: int) -> float:
    """One-sided P(X >= correct | n, 0.5). Exact; no SciPy in this repo."""
    if n <= 0:
        return 1.0
    from math import comb

    return sum(comb(n, i) for i in range(correct, n + 1)) / (2 ** n)
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


def collect_pairs(rows: list, *, date: str | None = None) -> tuple[dict, dict]:
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
            slopes[cell].append((slope, date))
            stats["pairs"] += 1
            # An `over` must fall as its line rises; an `under` must rise.
            if (side == "over" and slope > 0) or (side == "under" and slope < 0):
                wrong[cell] += 1
    return slopes, {"stats": stats, "wrong": wrong}


def summarise(slopes: dict, wrong: collections.Counter) -> list[dict]:
    out = []
    for cell, tagged in slopes.items():
        values = sorted(v for v, _ in tagged)
        n = len(values)
        # CROSS-DAY STABILITY. Pooling days assumes dP/dLine is a structural
        # property of the market rather than something that drifts. That is a
        # HYPOTHESIS, so it is measured here rather than assumed: `day_spread`
        # is the range of the per-day medians, and a cell whose days disagree
        # by more than its own IQR should not be pooled into one number.
        by_day = collections.defaultdict(list)
        for value, day in tagged:
            by_day[day].append(value)
        day_medians = {d: round(st.median(v), 4) for d, v in by_day.items() if v}
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
                "sign_test_p": (
                    None if cell[2] not in ("over", "under") else
                    round(sign_test_p(n - wrong[cell], n), 6)
                ),
                "thin": n < MIN_PAIRS_PER_CELL,
                "days": len(day_medians),
                "day_medians": day_medians,
                "day_spread": (
                    round(max(day_medians.values()) - min(day_medians.values()), 4)
                    if len(day_medians) >= 2
                    else None
                ),
                # POOLABLE only when the days agree to within the cell's own
                # IQR. Otherwise the pooled median is an average of regimes.
                "poolable": (
                    len(day_medians) < 2
                    or (max(day_medians.values()) - min(day_medians.values()))
                    <= max(1e-9, values[(3 * n) // 4] - values[n // 4])
                ),
            }
        )
    # PAIR EACH OVER WITH ITS UNDER (and home with away) and stamp symmetry.
    index = {(r["sport"], r["market"], r["side"]): r for r in out}
    mirror = {"over": "under", "under": "over", "home": "away", "away": "home"}
    for r in out:
        other = index.get((r["sport"], r["market"], mirror.get(r["side"], "")))
        r["asymmetry"] = None
        r["symmetric"] = None
        if other is None or r["thin"] or other["thin"]:
            continue
        a, b = abs(r["median_pp_per_unit"]), abs(other["median_pp_per_unit"])
        denom = max(a, b, 1e-9)
        r["asymmetry"] = round(abs(a - b) / denom, 4)
        r["symmetric"] = r["asymmetry"] <= MAX_SIDE_ASYMMETRY
    return sorted(out, key=lambda r: (-r["n_pairs"], r["sport"], r["market"]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--date", default=None, help="one date (default: the current board)")
    parser.add_argument("--start", default=None, help="sweep from this date (inclusive)")
    parser.add_argument("--end", default=None, help="sweep to this date (inclusive)")
    parser.add_argument("--json-out", default=None)
    parser.add_argument(
        "--min-pairs",
        type=int,
        default=MIN_PAIRS_PER_CELL,
        help="cells below this are printed but flagged `thin`; none are hidden.",
    )
    args = parser.parse_args()

    # ONE BOARD PER DATE: the endpoint serves each date's FINAL build, so a
    # sweep of N dates is N snapshots, not N x builds. Retention reached back
    # only to 2026-09-17 when measured on 2026-09-20 (09-14..09-16 returned
    # zero rows), so a wide --start contributes nothing for the early dates --
    # which is why every date's row count is printed below.
    if args.start and args.end:
        from datetime import date as _d, timedelta as _td
        a, b = _d.fromisoformat(args.start), _d.fromisoformat(args.end)
        dates = [(a + _td(days=i)).isoformat() for i in range((b - a).days + 1)]
    else:
        dates = [args.date]
    slopes = collections.defaultdict(list)
    stats = collections.Counter()
    wrong = collections.Counter()
    written = {}
    for day in dates:
        try:
            payload = fetch_board(limit=args.limit, date=day)
        except Exception as exc:  # noqa: BLE001
            print(f"  {day}: FETCH FAILED {type(exc).__name__}: {exc}", flush=True)
            continue
        rows = payload.get("rows") or []
        label = day or "current"
        written[label] = payload.get("written_at")
        print(f"  {label}: written_at {payload.get('written_at')}  rows {len(rows)}", flush=True)
        part, extra = collect_pairs(rows, date=label)
        for cell, values in part.items():
            slopes[cell].extend(values)
        stats.update(extra["stats"])
        wrong.update(extra["wrong"])
    summary = summarise(slopes, wrong)
    print(f"dates swept {len(dates)}, boards with rows {sum(1 for v in written.values() if v)}", flush=True)
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
        flags = []
        if r["thin"]:
            flags.append("THIN")
        if not r["poolable"]:
            flags.append("DAYS DISAGREE")
        if r["symmetric"] is False:
            flags.append(f"ASYMMETRIC {r['asymmetry']:.0%}")
        if r.get("sign_test_p") is not None and r["sign_test_p"] >= SIGN_TEST_ALPHA:
            flags.append(f"NO SLOPE p={r['sign_test_p']:.2g}")
        iqr = f"[{r['q1']:.2f},{r['q3']:.2f}]"
        spread = "" if r["day_spread"] is None else f"{r['day_spread']:.2f}"
        print(
            f"{r['sport']:8} {r['market'][:26]:26} {r['side'][:6]:6} {r['n_pairs']:>5} "
            f"{r['median_pp_per_unit']:>9.3f} {iqr:>18} {r['wrong_sign_rate']:>6.0%} "
            f"days={r['days']} spread={spread}"
            + (f"  <- {', '.join(flags)}" if flags else ""),
            flush=True,
        )

    # USABLE = enough pairs, days agree, AND its mirror side agrees. A cell with
    # no measurable mirror is NOT usable: symmetry is the check, and an
    # unverifiable cell must not default to passing it.
    usable = [
        r
        for r in summary
        if not r["thin"]
        and r["poolable"]
        and r["symmetric"] is True
        # home/away carry no over/under sign to test, so they rest on symmetry
        # alone -- stated here so that exemption is a decision, not an accident.
        and (r.get("sign_test_p") is None or r["sign_test_p"] < SIGN_TEST_ALPHA)
    ]
    print(
        f"\n{len(usable)} cell(s) USABLE (n>={args.min_pairs}, days agree, mirror agrees, slope exists), "
        f"{len(summary) - len(usable)} not. "
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
