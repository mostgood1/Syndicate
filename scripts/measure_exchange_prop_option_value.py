"""What is exchange price-shopping worth on MLB PROPS, net of fees? (`#624` step 5)

Item 05 answered this for GAME markets (+1.57pp, ~+1.2% ROI, n=13,093) and
could not answer it for props: until 2026-09-01 no exchange prop price was
captured anywhere. The capture landed, and this is the measurement it unblocked.

RESULT, 2026-09-01, RE-MEASURED ON THE HEALED SHARD. Run `--book gate` for the
number that decides step 6.

**The first version of every figure below came off a CLOBBERED copy of this
date** (`#630`: two publishers, one whole-file publish each; 46.1% matchable).
`e78aee52` fixed it, the shard now passes this script's own guard at **100.0%
matchable**, and the numbers moved. Superseded figures are kept in the
corrections section at the bottom, because the DIRECTION they moved is the
lesson.

ALL PROPS, n=3,774 time-aligned comparisons (was 2,062):

                          gross      fee-aware
    exchange is cheaper   70.1%         52.2%
    mean gain            +1.709pp     +0.985pp

**The gross win-rate is a FEE ILLUSION.** Net of measured fees the exchange
wins 52.2% of the time, which now sits almost exactly on the game-market 52.5%
instead of looking anomalous -- an observation the repair made STRONGER.

THE GATE BOOK (`--book gate`: unders, minus HR and HRR), n=1,235 (was 653) --
and this is the one step 6 is written about. Kalshi multipliers are RESOLVED
per series, so this is a point estimate rather than a bound:

    mean gain   per-side cost   two-way hold   book ROI
     +0.824pp    4.05 -> 3.23    8.1% -> 6.5%   +2.43%

STEP 6 IS NOT MET, on BOTH of its conditions: it needs >= +3% ROI at a <= 5%
effective two-way hold. The shortfall is **0.57 ROI points**, and the hold sits
further from its condition than the clobbered copy suggested.

**REPAIRING A FILE THAT HAD LOST ROWS MADE THE EXCHANGE LOOK WORSE.** That is
the opposite of the intuitive direction, and it is measured rather than
inferred: split the healed gate book at the clobbered copy's last sportsbook
quote (20:18:49Z) and the rows at or before it take the exchange **64.5%** of
the time for **+1.021pp**, while the rows the repair restored take it **40.2%**
for **+0.737pp**. The truncation had preserved exactly the window where the
exchange looks best, so **the clobber was biased in the exchange's favour** and
the published +2.65% was flattered by it. (That split is a directional test on
one consistent file, not a reproduction of the original run: the pre-cutoff
cohort is n=380 against the original n=653, because that fetch's exchange tail
differed too.)

**RESOLVING THE MULTIPLIER DID NOT CLOSE THE GATE, and the claim that it was
"worth 0.44 ROI points" was wrong about what that width meant.** It was the
width of an UNCERTAINTY, not a recoverable gain: every batter series turned out
to be half rate, so the range collapsed onto its own optimistic end (+2.66% ->
+2.65%, the tiny move being the 13 full-rate pitcher rows). What was bought is
CERTAINTY, which is worth having and is not ROI.

THREE CORRECTIONS TO THIS NUMBER, recorded because the first two offset each
other and either alone would have produced a confident wrong answer, and
because the third moved the margin after the decision looked settled:

  * WRONG ANCHOR. It converted entry improvement to ROI with "1pp of entry ~
    +0.75pp of ROI", taken from the 08-31 assessment, which attributes it to
    item 07's sensitivity table. **The table gives ~1.77**, so the conversion
    understated by ~2.4x. It now INTERPOLATES the published table instead of
    carrying a constant, and a test asserts the slope.
  * WRONG BOOK. It measured entry improvement over ALL props and spent it
    against the ROI curve of a book that is unders-minus-HR-and-HRR. On the
    gate's own book the gain is SMALLER (+0.955 vs +1.121), so the broad
    measurement flattered the answer.

  * CLOBBERED INPUT `[2026-09-01, applied by lane game-market-entry-roi-curve
    at the user's direction]`. Every figure above was first measured on a copy
    of the shard that had lost its sportsbook tail to the `#630` publish race.
    On the healed file the gate book is n=1,235 not 653, the gain +0.824pp not
    +0.949, and the ROI **+2.43% not +2.65%**. Superseded readings, kept so the
    direction stays visible: all props 82.3% gross / +1.939pp / 55.8-62.9%
    fee-aware / +1.121pp; gate 4.05 -> 3.10pp at a 6.2% hold.

Net of all three: the honest reading moved from "+1.6-1.8%, well short" to
"+2.2-2.7%, narrowly short" to **"+2.43%, short by 0.57 points"**. The DECISION
has never changed; the MARGIN has moved three times, and it is the margin a
reader uses to decide whether to keep pulling the thread.

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
`0.07 x multiplier x P x (1-P)`, and the multiplier is now RESOLVED PER SERIES
-- read live across all 14 registered MLB series, re-runnable with
`scripts/read_kalshi_fee_params.py`. Every batter-prop series is half rate;
earned runs / hits allowed / walks are FULL rate. See the map below.

--------------------------------------------------------------------------
THE WEEK-LONG RE-RUN, AND WHY ONE DATE IS STILL ALL THERE IS
--------------------------------------------------------------------------

`--since/--until` pools dates. As of 2026-09-01 that cannot yet produce a week:

  * EXCHANGE PROP CAPTURE EXISTS ON ONE DATE. Measured across 08-26..09-02:
    2026-09-01 has 5,840-7,158 exchange prop rows (the range is the defect
    below); every prior date has **exactly zero**. A 7-day window closes no
    earlier than **2026-09-08**.
  * THE SHARD LOSES ROWS. See the clobber note above `feed_overlap`. Dates whose
    two feeds barely overlap are REFUSED rather than folded into a total,
    because the surviving rows are all real and the number looks fine.

Usage:
    py -3 scripts/measure_exchange_prop_option_value.py --date 2026-09-01 --book gate
    py -3 scripts/measure_exchange_prop_option_value.py --since 2026-09-02 --until 2026-09-08 --book gate
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
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


# ---------------------------------------------------------------------------
# THE KALSHI MULTIPLIER IS RESOLVED PER MARKET. IT IS NOT A PROPERTY OF "MLB".
# ---------------------------------------------------------------------------
# Read live from `GET /trade-api/v2/series/<ticker>` on 2026-09-01, all 14
# registered MLB series -- reproduce with `scripts/read_kalshi_fee_params.py`.
#
# The first version of this measurement could not resolve the batter-prop
# multiplier and reported a BOUND, m=0.5..1.0, whose 0.44-ROI-point width was
# more than half of `#624` step 6's shortfall. Every BATTER series turned out to
# be half rate, so that bound is retired.
#
# But "MLB is half rate" is the WRONG rule and this map is why: earned runs,
# hits allowed and walks -- PITCHER RATE STATS -- are FULL rate, and all three
# sit inside the gate book, which is "unders minus HR/HRR", not "batter unders".
# A single multiplier would be wrong in both directions at once.
KALSHI_MULTIPLIER_BY_MARKET = {
    "batter_hits": 0.5,             # KXMLBHIT
    "batter_home_runs": 0.5,        # KXMLBHR
    "batter_hits_runs_rbis": 0.5,   # KXMLBHRR
    "batter_rbis": 0.5,             # KXMLBRBI
    "batter_total_bases": 0.5,      # KXMLBTB
    "batter_stolen_bases": 0.5,     # KXMLBSB
    "strikeouts": 0.5,              # KXMLBKS
    "outs": 0.5,                    # KXMLBOUTS
    "earned_runs": 1.0,             # KXMLBERA  -- full rate
    "hits_allowed": 1.0,            # KXMLBHA   -- full rate
    "walks_allowed": 1.0,           # KXMLBWA   -- full rate
}
# An unmapped market rounds AGAINST us, per `venue_fees`'s stated rule that a
# fee model which is too LOW manufactures fake edges and loses money on every
# fill. Unknown must not land on the cheap branch, and the count is reported.
KALSHI_UNKNOWN_MULTIPLIER = 1.0


def kalshi_multiplier_for_market(market: str) -> tuple[float, bool]:
    """`(multiplier, was_resolved)` for a board market name."""
    key = str(market or "").strip().lower()
    if key in KALSHI_MULTIPLIER_BY_MARKET:
        return KALSHI_MULTIPLIER_BY_MARKET[key], True
    return KALSHI_UNKNOWN_MULTIPLIER, False


# ---------------------------------------------------------------------------
# THE SHARD CAN BE CLOBBERED, AND A CLOBBERED SHARD PRODUCES A CONFIDENT NUMBER
# ---------------------------------------------------------------------------
# Measured 2026-09-01: two services each keep their OWN local copy of
# `mlb_source/tracking/book_quotes/<date>.jsonl`, append only their own rows to
# it (`odds_book_quotes.append_book_quotes` opens "a"), and then
# `artifact_publisher.publish_hot_artifact` reads the WHOLE FILE and pushes it
# to web -- a whole-file REPLACE, not a merge. Web therefore holds whichever
# service published last, and the other writer's rows are gone.
#
# Proof it is not append-only: a refetch an hour later LOST 1,318 exchange rows
# and gained 0, as a clean tail truncation (0 losses at or before the cutoff),
# while sportsbook rows gained an entire new hour.
#
# WHY THIS NEEDS A GUARD RATHER THAN A COMMENT. The damage is invisible in the
# output: the surviving rows are all real and correctly time-aligned, so the
# measurement still prints a tidy ROI. On 2026-09-01 the sportsbook feed stops
# at 20:18:49 while exchange rows run to 22:22:27, and **1,365 of 1,795
# "no time-aligned sportsbook price" exclusions -- 76% -- are that gap**, which
# the first version of this script reported as a property of market liquidity
# ("plausibly the more liquid subset"). It was a file-clobbering artifact.
#
# So: a date whose two feeds do not overlap for most of their span is REFUSED
# by default. Gate on the OUTPUT (do the two series actually coexist?) rather
# than on an assumption about how the file gets damaged.
FEED_OVERLAP_FLOOR = 0.65


def feed_overlap(rows: list) -> dict:
    """How much of the exchange feed's span the sportsbook feed actually covers.

    Returns the spans and the fraction of exchange quotes that fall at or before
    the last sportsbook quote -- the ones that COULD match. A low fraction means
    one writer's tail was clobbered, not that the market went quiet.
    """
    book_stamps = [s for s, book, _p, _r in rows if book not in EXCHANGES]
    exch_stamps = [s for s, book, _p, _r in rows if book in EXCHANGES]
    if not book_stamps or not exch_stamps:
        return {"ok": False, "reason": "a feed is entirely absent",
                "book_n": len(book_stamps), "exch_n": len(exch_stamps), "matchable": 0.0}
    last_book = max(book_stamps)
    matchable = sum(1 for s in exch_stamps if s <= last_book) / len(exch_stamps)
    return {
        "ok": matchable >= FEED_OVERLAP_FLOOR,
        "reason": "" if matchable >= FEED_OVERLAP_FLOOR else
                  "sportsbook feed ends long before the exchange feed -- "
                  "the shard was very likely clobbered by a competing publish",
        "book_n": len(book_stamps), "exch_n": len(exch_stamps),
        "book_span": (_hhmmss(min(book_stamps)), _hhmmss(last_book)),
        "exch_span": (_hhmmss(min(exch_stamps)), _hhmmss(max(exch_stamps))),
        "matchable": matchable,
    }


def _hhmmss(stamp: float) -> str:
    return datetime.utcfromtimestamp(stamp).strftime("%H:%M:%S")


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


def measure_date(rows: list, window: int) -> dict:
    """Fee-aware gains for one date's rows. Pure -- no printing, no fetching."""
    books: dict[tuple, list] = defaultdict(list)
    exch: dict[tuple, list] = defaultdict(list)
    for stamp, book, probability, row in rows:
        (exch if book in EXCHANGES else books)[quote_key(row)].append((stamp, book, probability))
    for store in (books, exch):
        for series in store.values():
            series.sort()

    gains: dict[str, list[float]] = defaultdict(list)
    taken: dict[str, int] = defaultdict(int)
    unmatched = 0
    unresolved: dict[str, int] = defaultdict(int)
    used: dict[float, int] = defaultdict(int)
    for key in set(books) & set(exch):
        series = books[key]
        multiplier, resolved = kalshi_multiplier_for_market(key[1])
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
            if venue == "kalshi":
                used[multiplier] += 1
                if not resolved:
                    unresolved[market_of(key)] += 1
            effective = exchange_prob + fee_pp(venue, exchange_prob, multiplier) / 100.0
            gains[venue].append(max(0.0, best - effective) * 100.0)
            if effective < best:
                taken[venue] += 1
    return {"gains": gains, "taken": taken, "unmatched": unmatched,
            "unresolved": unresolved, "used": used,
            "both_keys": len(set(books) & set(exch)),
            "exchange_rows": sum(len(v) for v in exch.values())}


def market_of(key: tuple) -> str:
    return key[1]


def expand_dates(explicit: list, since: str, until: str) -> list:
    """Dates to measure. `--since/--until` is the week-long form."""
    if since or until:
        start = datetime.strptime(since or until, "%Y-%m-%d").date()
        end = datetime.strptime(until or since, "%Y-%m-%d").date()
        if end < start:
            raise SystemExit(f"--until {end} is before --since {start}")
        span = (end - start).days
        return [(start + timedelta(days=i)).isoformat() for i in range(span + 1)]
    out: list = []
    for item in explicit or []:
        out.extend(part.strip() for part in str(item).split(",") if part.strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", action="append", default=[],
                    help="repeatable, or comma-separated; use --since/--until for a span")
    ap.add_argument("--since", default="", help="first date of a span, e.g. 2026-09-02")
    ap.add_argument("--until", default="", help="last date of a span, e.g. 2026-09-08")
    ap.add_argument("--window-minutes", type=int, default=30)
    ap.add_argument("--admin-token", default="")
    ap.add_argument("--book", choices=("all", "gate"), default="all",
                    help="'gate' restricts to the book `#624` step 6 is about: "
                         "unders, minus batter_home_runs and batter_hits_runs_rbis")
    ap.add_argument("--allow-clobbered", action="store_true",
                    help="measure a date whose two feeds barely overlap. The shard was "
                         "probably clobbered by a competing whole-file publish; the number "
                         "will look fine and describe a window chosen by a race.")
    ap.add_argument("--refetch", action="store_true", help="ignore any cached shard")
    ap.add_argument("--cache-dir", default=str(REPO_ROOT / "reports" / "exchange_prop_value"))
    args = ap.parse_args()

    dates = expand_dates(args.date, args.since, args.until)
    if not dates:
        raise SystemExit("give --date (repeatable) or --since/--until")

    token = args.admin_token
    if not token:
        env = REPO_ROOT / ".env"
        for line in (env.read_text(encoding="utf-8").splitlines() if env.exists() else []):
            if line.startswith("ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        raise SystemExit("no ADMIN_TOKEN")

    window = args.window_minutes * 60
    pooled: dict[str, list[float]] = defaultdict(list)
    pooled_taken: dict[str, int] = defaultdict(int)
    pooled_used: dict[float, int] = defaultdict(int)
    pooled_unresolved: dict[str, int] = defaultdict(int)
    unmatched = 0
    measured: list = []
    refused: list = []

    print(f"\n{'date':<12}{'exch':>7}{'book':>8}{'matchable':>11}  feed spans (UTC)")
    print("-" * 78)
    for date in dates:
        shard = Path(args.cache_dir) / f"book_quotes_{date}.jsonl"
        if args.refetch or not shard.exists():
            try:
                fetch_shard(date, token, shard)
            except SystemExit as exc:
                print(f"{date:<12}  no shard on production ({exc})")
                refused.append((date, "no shard"))
                continue
        rows = load_rows(shard)
        if args.book == "gate":
            rows = [r for r in rows if in_gate_book(r[3])]
        overlap = feed_overlap(rows)
        if not overlap.get("book_span"):
            print(f"{date:<12}{overlap['exch_n']:>7}{overlap['book_n']:>8}"
                  f"{'--':>11}  {overlap['reason']}")
            refused.append((date, overlap["reason"]))
            continue
        print(f"{date:<12}{overlap['exch_n']:>7}{overlap['book_n']:>8}"
              f"{100*overlap['matchable']:>10.1f}%  "
              f"exch {overlap['exch_span'][0]}..{overlap['exch_span'][1]}   "
              f"book {overlap['book_span'][0]}..{overlap['book_span'][1]}")
        if not overlap["ok"] and not args.allow_clobbered:
            print(f"{'':<12}  REFUSED -- {overlap['reason']}")
            refused.append((date, overlap["reason"]))
            continue
        result = measure_date(rows, window)
        measured.append(date)
        unmatched += result["unmatched"]
        for venue, values in result["gains"].items():
            pooled[venue].extend(values)
        for venue, count in result["taken"].items():
            pooled_taken[venue] += count
        for multiplier, count in result["used"].items():
            pooled_used[multiplier] += count
        for market, count in result["unresolved"].items():
            pooled_unresolved[market] += count

    if refused:
        print(f"\n{len(refused)} date(s) REFUSED -- not silently folded into the total:")
        for date, why in refused:
            print(f"   {date}: {why}")
        print("   A refused date is a SHARD problem, not a market problem. See the")
        print("   clobber note at the top of this file. --allow-clobbered overrides.")

    gains, taken, used, unresolved = pooled, pooled_taken, pooled_used, pooled_unresolved
    for label in (f"per-series multipliers; {len(measured)} date(s): {', '.join(measured) or 'none'}",):
        every = [g for v in gains.values() for g in v]
        if not every:
            print("\nno comparable quotes on any measured date")
            return 1
        print(f"\nFEE-AWARE SELECTION, {label}  (take whichever is cheaper AFTER fees)")
        if used:
            spread = "  ".join(f"x{m}: {c}" for m, c in sorted(used.items()))
            print(f"  kalshi rows by resolved multiplier: {spread}")
        if unresolved:
            print(f"  UNRESOLVED markets priced at x{KALSHI_UNKNOWN_MULTIPLIER} "
                  f"(against us, never toward cheap): {dict(unresolved)}")
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
    print("  * AN EXCLUSION IS NOT EVIDENCE ABOUT LIQUIDITY until the shard is ruled out.")
    print("    Read the `matchable` column above: it is the share of exchange quotes that")
    print("    fall at or before the LAST sportsbook quote, i.e. the ones that could match")
    print("    at all. Anything below 100% is partly the feeds not covering the same span.")
    print("    HISTORICAL CASE, and the reason this line exists: on the CLOBBERED copy of")
    print("    2026-09-01 (46.1% matchable), 1,365 of 1,795 exclusions -- 76% -- were")
    print("    exchange rows stamped after the sportsbook feed simply stopped. An earlier")
    print("    version of this caveat called the survivors 'plausibly the more liquid")
    print("    subset', attributing to the market what was a whole-file publish race.")
    print("  * item 05's game-market +1.57pp is GROSS by this same method, so compare")
    print("    props-to-games gross-to-gross, not this net number against that one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
