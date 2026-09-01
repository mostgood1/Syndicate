"""What is exchange price-shopping worth on MLB PROPS, net of fees? (`#624` step 5)

Item 05 answered this for GAME markets (+1.57pp, ~+1.2% ROI, n=13,093) and
could not answer it for props: until 2026-09-01 no exchange prop price was
captured anywhere. The capture landed, and this is the measurement it unblocked.

RESULT, 2026-09-01. Run `--book gate` for the number that decides step 6.

ALL PROPS, n=2,062 time-aligned comparisons:

                          gross      fee-aware
    exchange is cheaper   82.3%      55.8% - 62.9%
    mean gain            +1.939pp    +0.859 / +1.121 pp

**The 82.3% gross win-rate is a FEE ILLUSION.** Net of measured fees the
exchange wins ~56-63% of the time, which sits right next to the game-market
52.5% instead of looking anomalous.

THE GATE BOOK (`--book gate`: unders, minus HR and HRR), n=653 -- and this is
the one step 6 is written about:

    multiplier   mean gain   per-side cost   two-way hold   book ROI
    m=0.5         +0.955pp    4.05 -> 3.10    8.1% -> 6.2%   +2.66%
    m=1.0         +0.703pp    4.05 -> 3.35    8.1% -> 6.7%   +2.22%

STEP 6 IS NOT MET, on BOTH of its conditions: it needs >= +3% ROI at a <= 5%
effective two-way hold, and price-shopping reaches +2.2% to +2.7% at a 6.2-6.7%
hold. The shortfall is real but NARROW -- roughly 0.3 to 0.8 ROI points.

TWO CORRECTIONS TO THE FIRST VERSION OF THIS NUMBER, which offset each other
and are recorded because either alone would have produced a confident wrong
answer:

  * WRONG ANCHOR. It converted entry improvement to ROI with "1pp of entry ~
    +0.75pp of ROI", taken from the 08-31 assessment, which attributes it to
    item 07's sensitivity table. **The table gives ~1.77**, so the conversion
    understated by ~2.4x. It now INTERPOLATES the published table instead of
    carrying a constant, and a test asserts the slope.
  * WRONG BOOK. It measured entry improvement over ALL props and spent it
    against the ROI curve of a book that is unders-minus-HR-and-HRR. On the
    gate's own book the gain is SMALLER (+0.955 vs +1.121), so the broad
    measurement flattered the answer.

Net of both: the honest reading moved from "+1.6-1.8%, well short" to
"+2.2-2.7%, narrowly short". The DECISION is unchanged; the MARGIN is not.

--------------------------------------------------------------------------
THREE THINGS THIS GETS RIGHT THAT AN OBVIOUS VERSION GETS WRONG
--------------------------------------------------------------------------

1. TIME ALIGNMENT. Item 05's first attempt compared fills against the best
   sportsbook price ANYWHERE IN THE DAY, which silently picks the deepest
   in-play quote -- one HR line walked +475 -> +2600 in a day -- and the
   comparison INVERTED once aligned. Here the sportsbook side is the most
   recent quote for the SAME (player, market, line, side) at or before the
   exchange quote, within a stated window.

2. FEE-AWARE SELECTION, not blanket fee subtraction. You pay an exchange fee
   only on the rows where you actually take the exchange; subtracting it
   everywhere understates the value. The rule is: take whichever is cheaper
   AFTER fees, so the gain floors at zero.

3. THE ASK, not a midpoint. Kalshi rows carry that side's ASK -- the price you
   actually pay. `kalshi_board_join`'s docstring is explicit that deriving one
   side from the other "would erase the spread and invent an edge that is not
   there". Comparing a midpoint against a sportsbook's offered price would
   flatter the exchange by half the spread.

FEES ARE MEASURED, NOT ASSUMED (`syndicate/features/shared/venue_fees.py`):
Polymarket is **150 bps of notional, FLAT and price-independent**; Kalshi is
`0.07 x multiplier x P x (1-P)`. **Kalshi's multiplier for BATTER-PROP series is
unresolved** -- `kalshi_fee_params` refuses without a series payload, and the
half-rate finding is documented for "MLB game/total/spread/K" series, which does
not name batter props. Both bounds are reported rather than one guessed.

Usage:
    py -3 scripts/measure_exchange_prop_option_value.py --date 2026-09-01
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://syndicate-an21.onrender.com"
EXCHANGES = {"kalshi", "polymarket", "novig", "prophetx"}
POLYMARKET_FEE_PP = 1.50   # 150 bps of notional, flat -- measured, price-independent
KALSHI_BASE_RATE = 0.07    # fee = rate * multiplier * P * (1-P)


def implied(price) -> float | None:
    """American price -> implied probability. A value strictly inside
    (-100, 100) is not an American price and is refused, never coerced."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if -100.0 < value < 100.0:
        return None
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def parse_ts(value) -> float | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def fee_pp(venue: str, probability: float, multiplier: float) -> float:
    """The cost of taking this venue, in implied-probability points."""
    if venue == "polymarket":
        return POLYMARKET_FEE_PP
    return 100.0 * KALSHI_BASE_RATE * multiplier * probability * (1.0 - probability)


def quote_key(row: dict) -> tuple:
    return (
        str(row.get("event_id") or ""), str(row.get("market") or ""),
        str(row.get("player_name") or ""), str(row.get("line")),
        str(row.get("selection") or ""),
    )


# `#624` step 6's gate is about ONE book, not about props in general: item 07
# priced "unders, minus home runs and HRR" (n=2,569). Measuring entry
# improvement over ALL props and then spending it against that book's ROI
# sensitivity silently assumes the two move together. They need not: HR unders
# are the longest prices on the board, and the fee shapes are price-dependent.
GATE_EXCLUDED_MARKETS = frozenset({"batter_home_runs", "batter_hits_runs_rbis"})
GATE_SELECTION = "under"

# Item 07's published sensitivity for that book, verbatim (per-side pp -> ROI %),
# from `findings_2026-08-31_mlb_accuracy_assessment.md`. Interpolated rather than
# collapsed to one slope constant, because collapsing it is how the wrong anchor
# got into circulation: the 08-31 write-up said "each 1pp of better entry is
# worth roughly +0.75pp of ROI" and attributed it to THIS table, which actually
# gives ~1.77 (2.74 ROI points across 4.05pp -> 2.50pp per side). Step 5 spent
# the 0.75 and understated the exchange's contribution by ~2.4x.
GATE_SENSITIVITY = ((0.00, 8.48), (0.50, 7.49), (1.00, 6.52), (1.50, 5.57),
                    (2.50, 3.72), (3.75, 1.50), (4.05, 0.98))
GATE_PER_SIDE_TODAY = 4.05      # pp per side == today's ~8.1% two-way hold
GATE_ROI_TARGET_PCT = 3.0       # step 6: target >= +3%
GATE_HOLD_TARGET_PCT = 5.0      # step 6: at <= 5% effective two-way hold


def roi_at_side_cost(side_cost_pp: float) -> float:
    """Book ROI at a given per-side entry cost, linearly interpolated on item
    07's table. Clamped at both ends: this prices a venue change, and
    extrapolating past a measured endpoint would invent a number."""
    points = GATE_SENSITIVITY
    if side_cost_pp <= points[0][0]:
        return points[0][1]
    if side_cost_pp >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= side_cost_pp <= x1:
            return y0 + (y1 - y0) * (side_cost_pp - x0) / (x1 - x0)
    raise AssertionError("unreachable: table is sorted and bracketed")


def in_gate_book(row: dict) -> bool:
    """The surviving book the re-enable gate is written about."""
    return (
        str(row.get("selection") or "").strip().lower() == GATE_SELECTION
        and str(row.get("market") or "").strip().lower() not in GATE_EXCLUDED_MARKETS
    )


def load_rows(path: Path) -> list[tuple[float, str, float, dict]]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("kind")) != "prop":
            continue
        stamp = parse_ts(row.get("snapshot_ts") or row.get("captured_at"))
        probability = implied(row.get("price"))
        if stamp is None or probability is None:
            continue
        out.append((stamp, str(row.get("bookmaker") or "").lower(), probability, row))
    return out


def fetch_shard(date: str, token: str, dest: Path) -> Path:
    url = f"{BASE}/api/ops/artifacts/export?" + urllib.parse.urlencode(
        {"pattern": f"*mlb_source/tracking/book_quotes/{date}.jsonl"})
    request = urllib.request.Request(url, headers={"X-Admin-Token": token})
    with urllib.request.urlopen(request, timeout=900) as response:
        payload = json.loads(response.read().decode("utf-8"))
    artifacts = payload.get("artifacts") or {}
    if not artifacts:
        raise SystemExit(f"no book_quotes shard for {date} on production")
    doc = next(iter(artifacts.values()))
    text = doc if isinstance(doc, str) else "\n".join(json.dumps(r) for r in doc)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--window-minutes", type=int, default=30)
    ap.add_argument("--admin-token", default="")
    ap.add_argument("--book", choices=("all", "gate"), default="all",
                    help="'gate' restricts to the book `#624` step 6 is about: "
                         "unders, minus batter_home_runs and batter_hits_runs_rbis")
    ap.add_argument("--cache-dir", default=str(REPO_ROOT / "reports" / "exchange_prop_value"))
    args = ap.parse_args()

    token = args.admin_token
    if not token:
        env = REPO_ROOT / ".env"
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            if line.startswith("ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        raise SystemExit("no ADMIN_TOKEN")

    shard = Path(args.cache_dir) / f"book_quotes_{args.date}.jsonl"
    if not shard.exists():
        print(f"fetching {args.date} from production ...", flush=True)
        fetch_shard(args.date, token, shard)
    rows = load_rows(shard)
    if args.book == "gate":
        before = len(rows)
        rows = [r for r in rows if in_gate_book(r[3])]
        print(f"\nBOOK = gate (unders, minus HR and HRR): {len(rows)} of {before} prop quote rows")

    books: dict[tuple, list] = defaultdict(list)
    exch: dict[tuple, list] = defaultdict(list)
    for stamp, book, probability, row in rows:
        (exch if book in EXCHANGES else books)[quote_key(row)].append((stamp, book, probability))
    for store in (books, exch):
        for series in store.values():
            series.sort()

    exchange_rows = sum(len(v) for v in exch.values())
    print(f"\nprop quote rows: {len(rows)}   exchange {exchange_rows}   sportsbook {len(rows)-exchange_rows}")
    print(f"keys quoted by both: {len(set(books) & set(exch))}")

    window = args.window_minutes * 60
    for multiplier, label in ((0.5, "m=0.5 (MLB half-rate)"), (1.0, "m=1.0 (full rate)")):
        gains: dict[str, list[float]] = defaultdict(list)
        taken: dict[str, int] = defaultdict(int)
        unmatched = 0
        for key in set(books) & set(exch):
            series = books[key]
            for stamp, venue, exchange_prob in exch[key]:
                best = None
                for book_ts, _book, book_prob in series:
                    if book_ts > stamp:
                        break
                    if stamp - book_ts <= window:
                        best = book_prob if best is None else min(best, book_prob)
                if best is None:
                    unmatched += 1
                    continue
                effective = exchange_prob + fee_pp(venue, exchange_prob, multiplier) / 100.0
                gains[venue].append(max(0.0, best - effective) * 100.0)
                if effective < best:
                    taken[venue] += 1
        every = [g for v in gains.values() for g in v]
        if not every:
            print("\nno comparable quotes")
            return 0
        print(f"\nFEE-AWARE SELECTION, {label}  (take whichever is cheaper AFTER fees)")
        print(f"  excluded, no sportsbook quote within {args.window_minutes} min: {unmatched}")
        print(f"  {'venue':<12}{'n':>7}{'exch taken':>12}{'mean':>10}{'median':>9}{'p90':>8}")
        for venue in sorted(gains, key=lambda v: -len(gains[v])):
            data = sorted(gains[venue])
            n = len(data)
            print(f"  {venue:<12}{n:>7}{100*taken[venue]/n:>11.1f}%{statistics.fmean(data):>+10.3f}"
                  f"{data[n//2]:>+9.3f}{data[int(0.9*n)]:>+8.3f}")
        data = sorted(every)
        n = len(data)
        mean = statistics.fmean(data)
        print(f"  {'ALL':<12}{n:>7}{100*sum(taken.values())/n:>11.1f}%{mean:>+10.3f}"
              f"{data[n//2]:>+9.3f}{data[int(0.9*n)]:>+8.3f}")
        side_cost = GATE_PER_SIDE_TODAY - mean
        print(f"  -> per-side entry cost {GATE_PER_SIDE_TODAY:.2f}pp -> {side_cost:.2f}pp"
              f"   (two-way hold {2*GATE_PER_SIDE_TODAY:.1f}% -> {2*side_cost:.1f}%)")
        print(f"  -> book ROI by item 07's table: {roi_at_side_cost(side_cost):+.2f}%"
              f"   [gate needs >= +{GATE_ROI_TARGET_PCT:.0f}% at <= {GATE_HOLD_TARGET_PCT:.0f}% hold]")
    print("\nCAVEATS, which the number does not survive without:")
    print("  * a single date is not a rate -- re-run over a week before sizing anything")
    print("  * excluded quotes above are exchange prices with NO time-aligned sportsbook")
    print("    quote; this measures the OVERLAP, plausibly the more liquid subset")
    print("  * item 05's game-market +1.57pp is GROSS by this same method, so compare")
    print("    props-to-games gross-to-gross, not this net number against that one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
