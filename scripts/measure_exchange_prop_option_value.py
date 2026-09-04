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

--------------------------------------------------------------------------
FOURTH CORRECTION `[2026-09-04, lane gate-per-side-derived]`: THE `4.05` IN
THAT ROW WAS NEVER MEASURED, AND ITS TWO TERMS DESCRIBED DIFFERENT BOOKS
--------------------------------------------------------------------------

Every "per-side cost" reading above starts from `GATE_PER_SIDE_TODAY = 4.05`,
which was `8.1% / 2` -- the LABEL on the top row of item 07's table, halved.
That halving is an identity that holds ONLY AT EVEN MONEY. Measured on
production shards 2026-09-01..09-04 the gate book's unders sit at fair 0.607,
so they carry ~61% of the hold, and the arithmetic was wrong twice over:

  * WRONG ANCHOR. Re-measured under the reference implementation's own
    definition (`(q - q/overround) x 100`, same book, same snapshot --
    `scripts/measure_game_market_option_value.py:541-558`): the gate book costs
    **4.198pp per side** at a **7.09%** two-way hold, not 4.05pp at 8.1%
    (n=114,545 book-rows). On the same +1.172pp gain that moves the answer
    **+3.05% -> +2.79%**, flipping the ROI leg from MET to NOT MET. An
    unmeasured constant was the difference between a ship and a don't.

  * WRONG POPULATION, and it is worth twice as much. The gain is measured
    against the BEST book on the cells an exchange happens to quote; 4.05 stood
    for a cost over EVERY cell at the AVERAGE book. Matched, that baseline is
    **3.391pp** rather than 4.198 -- a -0.807pp mismatch that decomposes 67%
    into the cell set and 33% into the book. Note the direction, which is not
    the intuitive one: price-shopping across sportsbooks buys almost nothing
    here (-0.27pp); the exchange simply SELECTS the cheaper props (-0.54pp). A
    best-price baseline over the WHOLE book reads 4.260pp, ABOVE the average.

Both are fixed by deriving the cost from the same shards at evaluation time,
per row, on ONE population -- see `derive_entry_cost`. A cell no exchange
quotes contributes a gain of ZERO rather than being dropped, because you cannot
take a price that is not there, and it is not there on 91% of cells.

CURRENT READING, production shards 2026-09-01..09-04, n=85,591 gate cells:

                         per-side       two-way hold    book ROI
    the book (all)    4.233 -> 3.956   7.01% -> 6.52%    +1.14%   BOTH LEGS FAIL
    where it quotes   3.861 -> 0.792    ~6.9% -> 1.44%   +6.92%   both legs pass
                      (7,731 cells, 9.0% coverage -- a DIFFERENT question)

STEP 6 IS STILL NOT MET, and by more than any earlier reading said. The
DECISION has never changed across five restatements; the MARGIN has, every
time, and every time against the exchange.

TWO THINGS THIS READING DOES NOT SUPPORT:
  * The ROI column is CLAMPED at 4.05pp, where item 07's table ends. Today's
    4.233pp is OUTSIDE it, so `+1.14%` is a FLOOR and the honest figure is
    lower. Extending the table means re-pricing item 07's 2,569 rows, which
    this script does not hold and cannot do.
  * The exchange leg may be up to `--window-minutes` stale while the sportsbook
    legs come from ONE refresh cycle. Measured 2026-09-03 at 1/5/15/30 min the
    subset gain reads +2.130/+2.323/+2.661/+3.292pp on 1.1/2.6/7.2/12.0%
    coverage. Both verdicts hold at every window; the margin does not.

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
GATE_ROI_TARGET_PCT = 3.0       # step 6: target >= +3%
GATE_HOLD_TARGET_PCT = 5.0      # step 6: at <= 5% effective two-way hold

# ---------------------------------------------------------------------------
# WHERE `GATE_PER_SIDE_TODAY = 4.05` USED TO SIT, AND WHY IT IS GONE
# ---------------------------------------------------------------------------
# It was never measured. It is `8.1% / 2` -- the label on the top row of item
# 07's sensitivity table, halved. That halving is an IDENTITY THAT HOLDS ONLY AT
# EVEN MONEY, because proportional de-vig charges each side in proportion to its
# own price: `side_cost = fair x hold`, so the two sides split the hold 50/50
# only when `fair = 0.5`. This book's unders are FAVOURITES -- measured mean
# fair 0.607 on 2026-09-01..09-04 -- so they carry ~61% of the hold, not 50%.
#
# The error was not academic. Substituting the MEASURED cost flips step 6's ROI
# leg from MET to NOT MET, which is the whole decision.
#
#   asserted   4.05pp per side  <-  8.1% / 2, from a table LABEL
#   measured   4.233pp per side at a 7.012% two-way hold  (n=85,591 gate cells,
#              production shards 2026-09-01..09-04, definition below)
#
# A new hard-coded 4.233 would fail the same way -- it moved 4.327 -> 3.776
# across four consecutive days, a 13% swing -- so the number is DERIVED from the
# same shards the gate already reads, at gate-evaluation time. The asserted value
# is kept ONLY so the drift stays printable and testable; nothing in the
# arithmetic may read it, and `tests/test_exchange_prop_option_value.py` fails if
# anything does.
GATE_PER_SIDE_ASSERTED_2026_08_31 = 4.05

# The reference definition, `scripts/measure_game_market_option_value.py:541-558`:
#     overround    = q_side + q_opposite      (SAME book, SAME snapshot)
#     fair         = q_side / overround
#     side_cost_pp = (q_side - fair) * 100
#     hold_pct     = (overround - 1) * 100
# Band copied from that module: an overround at or below 1.0 is arbitrage or a
# parse artifact, and one above 1.30 is not a two-way market being quoted.
OVERROUND_MIN = 1.0
OVERROUND_MAX = 1.30

# `side_cost = fair x hold` is an identity, so `hold = side_cost / fair` must
# reproduce the overround measured directly. Asserted rather than assumed,
# because it is the exact thing 4.05 got wrong and a silent divergence would mean
# the de-vig and the cost had stopped describing the same price. Measured slack
# on 2026-09-01..09-04: 0.034pp (6.978 derived against 7.012 direct), which is a
# Jensen gap between a mean of ratios and a ratio of means. `2 x side_cost` would
# have said 8.466 -- off by 1.45 points, in the direction that flatters the gate.
HOLD_IDENTITY_TOLERANCE_PP = 0.25


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
        and in_gate_market(row)
    )


def in_gate_market(row: dict) -> bool:
    """The market half of `in_gate_book`, WITHOUT the side filter.

    De-vigging needs the OPPOSITE side, so the cost derivation cannot run on the
    same under-only rows the gain runs on. Splitting the predicate is what lets
    both use one definition of the book instead of two that can drift apart."""
    return str(row.get("market") or "").strip().lower() not in GATE_EXCLUDED_MARKETS


def cell_key(row: dict) -> tuple:
    """`quote_key` WITHOUT the side -- the two-way cell, not one of its legs."""
    return (
        str(row.get("event_id") or ""), str(row.get("market") or ""),
        str(row.get("player_name") or ""), str(row.get("line")),
    )


def latest_quote_at(series, at: float, window: float):
    """The most recent price in `series` at or before `at`, within `window`.

    NOT the cheapest in the window. A venue shows one price at a time; the
    minimum over a half-hour is a price nobody could have taken, and picking it
    is how a comparison silently starts flattering one side."""
    best = None
    for stamp, probability in series or ():
        if stamp > at:
            break
        if at - stamp <= window:
            best = probability
    return best


def side_cost_of(q_side: float, q_opposite: float):
    """`(side_cost_pp, hold_pct, fair)` under proportional de-vig, or None.

    None means the pair is not a usable two-way quote -- never a zero cost. An
    unusable overround dropped onto a cheap default would read as a free entry,
    which is the permissive-on-unknown failure this repo has been bitten by."""
    overround = q_side + q_opposite
    if not (OVERROUND_MIN < overround < OVERROUND_MAX):
        return None
    fair = q_side / overround
    return (q_side - fair) * 100.0, (overround - 1.0) * 100.0, fair


def two_way_hold_pct(side_cost_pp: float, fair: float) -> float:
    """The two-way hold that produces `side_cost_pp` on a side priced at `fair`.

    NOT `2 x side_cost_pp`. That doubling is the same even-money assumption that
    produced 4.05, and it is wrong by the same factor: on this book it reads
    8.47% against a measured 7.01%."""
    if not (0.0 < fair < 1.0):
        raise ValueError(f"fair must be a probability, got {fair!r}")
    return side_cost_pp / fair


def derive_entry_cost(rows: list, window: int) -> dict:
    """What the gate book costs to enter today, and what the exchange changes.

    ONE population, priced PER ROW. The defect this replaces subtracted a gain
    measured against the BEST book on the cells an exchange happens to quote,
    from a cost defined at the AVERAGE book over every cell -- two different
    books over two different cell sets. Measured on 2026-09-01..09-04 that
    mismatch is worth -0.807pp, twice the constant error it hid behind, and it
    decomposes 67% / 33% into the cell set and the book.

    Population: every `(captured_at, event, market, player, line)` cell in the
    gate book carrying a usable two-way SPORTSBOOK quote. Per cell:

        today = the CHEAPEST sportsbook entry cost offered at that instant
        gain  = today's price minus the best fee-adjusted exchange price for the
                same cell within `window`, floored at zero
        after = today - gain

    An absent exchange quote contributes a gain of ZERO rather than dropping the
    cell. That is the difference between "the exchange is cheaper where it
    quotes" and "the book is cheaper" -- you cannot take a price that is not
    there, and only 9.0% of cells had one. Both readings are returned; neither
    answers the other's question."""
    cells: dict[tuple, dict] = defaultdict(dict)
    exchange_unders: dict[tuple, list] = defaultdict(list)
    for stamp, book, probability, row in rows:
        if not in_gate_market(row):
            continue
        selection = str(row.get("selection") or "").strip().lower()
        if selection not in ("under", "over"):
            continue
        if book in EXCHANGES:
            if selection == GATE_SELECTION:
                exchange_unders[(cell_key(row), book)].append((stamp, probability))
            continue
        cells[(row.get("captured_at"), cell_key(row), book)][selection] = (stamp, probability)
    for series in exchange_unders.values():
        series.sort()

    # Collapse each snapshot's rival books to the cheapest ENTRY COST on offer.
    # The gain is measured against the best book, so the baseline must be too.
    cheapest: dict[tuple, dict] = {}
    refused: dict[str, int] = defaultdict(int)
    for (captured, key, _book), sides in cells.items():
        if GATE_SELECTION not in sides:
            refused["cell_has_no_under"] += 1
            continue
        if "over" not in sides:
            refused["no_opposite_side_at_this_book"] += 1
            continue
        (stamp, q), (_over_stamp, q_opposite) = sides[GATE_SELECTION], sides["over"]
        priced = side_cost_of(q, q_opposite)
        if priced is None:
            refused["overround_out_of_band"] += 1
            continue
        cost, hold, fair = priced
        current = cheapest.get((captured, key))
        if current is None or cost < current["cost"]:
            cheapest[(captured, key)] = {"stamp": stamp, "q": q, "cost": cost,
                                         "hold": hold, "fair": fair}

    today, gains, after, fairs, holds = [], [], [], [], []
    sub_today, sub_gain, sub_after, sub_fair = [], [], [], []
    covered = 0
    for (_captured, key), cell in cheapest.items():
        multiplier, _resolved = kalshi_multiplier_for_market(key[1])
        # The LATEST quote each venue is still showing, then the cheapest of
        # those -- price shopping ACROSS venues at one instant. NOT the cheapest
        # quote anywhere in the window: that picks whichever second of the last
        # half hour the exchange happened to be cheapest, which is not a price
        # anyone can take, and it is this script's own documented defect #1
        # (time alignment) reintroduced on the exchange side. Measured cost of
        # getting it wrong on 2026-09-01..09-04: subset gain +3.069 -> +3.172pp.
        #
        # THE ASYMMETRY THAT REMAINS, stated because it is not removable here:
        # the sportsbook legs come from ONE refresh cycle (`captured_at`, exact)
        # while the exchange leg may be up to `window` old. The exchange feed is
        # captured far less often, so tightening the window buys alignment and
        # spends coverage. Measured on 2026-09-03 at 1 / 5 / 15 / 30 min:
        # subset gain +2.130 / +2.323 / +2.661 / +3.292pp on coverage
        # 1.1% / 2.6% / 7.2% / 12.0%. BOTH VERDICTS HOLD AT EVERY WINDOW -- the
        # book fails and the subset passes throughout -- so the window changes
        # the margin and not the decision. Do not quote a gain without its window.
        best_effective = None
        for venue in EXCHANGES:
            probability = latest_quote_at(
                exchange_unders.get((key, venue)), cell["stamp"], window)
            if probability is None:
                continue
            effective = probability + fee_pp(venue, probability, multiplier) / 100.0
            if best_effective is None or effective < best_effective:
                best_effective = effective
        gain = 0.0
        if best_effective is not None:
            covered += 1
            gain = max(0.0, cell["q"] - best_effective) * 100.0
            sub_today.append(cell["cost"])
            sub_gain.append(gain)
            sub_after.append(cell["cost"] - gain)
            sub_fair.append(cell["fair"])
        today.append(cell["cost"])
        gains.append(gain)
        after.append(cell["cost"] - gain)
        fairs.append(cell["fair"])
        holds.append(cell["hold"])

    if not today:
        return {"n": 0, "refused": dict(refused)}
    mean = statistics.fmean
    report = {
        "n": len(today), "covered": covered, "refused": dict(refused),
        "today_pp": mean(today), "gain_pp": mean(gains), "after_pp": mean(after),
        "fair": mean(fairs), "hold_measured_pct": mean(holds),
        "today_median_pp": sorted(today)[len(today) // 2],
        "subset_n": len(sub_today),
        "subset_today_pp": mean(sub_today) if sub_today else None,
        "subset_gain_pp": mean(sub_gain) if sub_gain else None,
        "subset_after_pp": mean(sub_after) if sub_after else None,
        "subset_fair": mean(sub_fair) if sub_fair else None,
    }
    report["hold_derived_pct"] = two_way_hold_pct(report["today_pp"], report["fair"])
    report["hold_identity_slack_pp"] = abs(
        report["hold_derived_pct"] - report["hold_measured_pct"])
    report["hold_identity_ok"] = (
        report["hold_identity_slack_pp"] <= HOLD_IDENTITY_TOLERANCE_PP)
    # The table's measured span ends at 4.05pp. Today sits OUTSIDE it, which is
    # exactly the hole 4.05 papered over, so say so instead of clamping quietly.
    report["today_off_table"] = report["today_pp"] > GATE_SENSITIVITY[-1][0]
    return report


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


def combine_entry_costs(reports: list) -> dict:
    """Pool per-date `derive_entry_cost` reports, weighted by their own n.

    Weighted rather than averaged: 2026-09-01 carries 37,111 cells and 09-04
    carries 6,362, and a flat mean over dates would give the thin day equal say
    in a number the gate turns on."""
    live = [r for r in reports if r.get("n")]
    if not live:
        return {"n": 0, "refused": {}}
    total = sum(r["n"] for r in live)
    weighted = lambda field: sum(r[field] * r["n"] for r in live) / total
    out = {
        "n": total, "covered": sum(r["covered"] for r in live),
        "today_pp": weighted("today_pp"), "gain_pp": weighted("gain_pp"),
        "after_pp": weighted("after_pp"), "fair": weighted("fair"),
        "hold_measured_pct": weighted("hold_measured_pct"),
        "dates": len(live),
    }
    subset = [r for r in live if r.get("subset_n")]
    sub_total = sum(r["subset_n"] for r in subset)
    out["subset_n"] = sub_total
    for field in ("subset_today_pp", "subset_gain_pp", "subset_after_pp", "subset_fair"):
        out[field] = (sum(r[field] * r["subset_n"] for r in subset) / sub_total
                      if sub_total else None)
    refused: dict[str, int] = defaultdict(int)
    for report in live:
        for reason, count in (report.get("refused") or {}).items():
            refused[reason] += count
    out["refused"] = dict(refused)
    out["hold_derived_pct"] = two_way_hold_pct(out["today_pp"], out["fair"])
    out["hold_identity_slack_pp"] = abs(out["hold_derived_pct"] - out["hold_measured_pct"])
    out["hold_identity_ok"] = out["hold_identity_slack_pp"] <= HOLD_IDENTITY_TOLERANCE_PP
    out["today_off_table"] = out["today_pp"] > GATE_SENSITIVITY[-1][0]
    return out


def gate_verdict(after_pp: float, fair: float) -> dict:
    """The two legs of `#624` step 6, each with the reading that decides it."""
    roi = roi_at_side_cost(after_pp)
    hold = two_way_hold_pct(after_pp, fair)
    return {"roi_pct": roi, "hold_pct": hold,
            "roi_met": roi >= GATE_ROI_TARGET_PCT,
            "hold_met": hold <= GATE_HOLD_TARGET_PCT}


def print_gate_verdict(report: dict, window_minutes: int) -> None:
    """Both populations, both verdicts, and never one collapsed number."""
    print(f"\n`#624` STEP 6 -- ENTRY COST DERIVED FROM THESE SHARDS, NOT ASSERTED")
    if not report.get("n"):
        print("  no two-way sportsbook cell in the gate book -- nothing to derive")
        return
    print(f"  definition: (q - q/overround) x 100, same book, same snapshot"
          f"   [{GATE_SENSITIVITY[-1][0]:.2f}pp was the ASSERTED value: 8.1% / 2]")
    print(f"  gate cells priced: {report['n']:,} over {report.get('dates', 1)} date(s)"
          f"   refusals {report['refused']}")
    print(f"  per-side entry cost TODAY   {report['today_pp']:.3f}pp"
          f"   (asserted {GATE_PER_SIDE_ASSERTED_2026_08_31:.2f}pp,"
          f" drift {report['today_pp'] - GATE_PER_SIDE_ASSERTED_2026_08_31:+.3f}pp)")
    print(f"  two-way hold, measured      {report['hold_measured_pct']:.3f}%"
          f"   [derived cost/fair {report['hold_derived_pct']:.3f}%,"
          f" slack {report['hold_identity_slack_pp']:.3f}pp"
          f" -- {'OK' if report['hold_identity_ok'] else 'IDENTITY BROKEN'}]")
    print(f"  mean fair on the under side {report['fair']:.3f}"
          f"   -- so 2 x per-side would say {2*report['today_pp']:.2f}%,"
          f" which is the 4.05 error restated")
    if report["today_off_table"]:
        print(f"  !! today's cost is OUTSIDE item 07's measured table"
              f" (ends at {GATE_SENSITIVITY[-1][0]:.2f}pp). Every ROI at or above"
              f" that point is CLAMPED and is a floor, not a reading.")

    coverage = 100.0 * report["covered"] / report["n"]
    print(f"\n  THE BOOK  (all {report['n']:,} cells; a cell with no exchange quote"
          f" within {window_minutes} min gains 0, it is not dropped)")
    print(f"    exchange coverage         {report['covered']:,}/{report['n']:,}"
          f" = {coverage:.1f}% of cells")
    book = gate_verdict(report["after_pp"], report["fair"])
    print(f"    {report['today_pp']:.3f}pp -> {report['after_pp']:.3f}pp"
          f"   gain {report['gain_pp']:+.3f}pp"
          f"   hold {report['hold_measured_pct']:.2f}% -> {book['hold_pct']:.2f}%")
    print(f"    ROI  {book['roi_pct']:+.2f}%  [needs >= +{GATE_ROI_TARGET_PCT:.0f}%]"
          f"  -> {'MET' if book['roi_met'] else 'NOT MET'}")
    print(f"    HOLD {book['hold_pct']:.2f}%  [needs <= {GATE_HOLD_TARGET_PCT:.0f}%]"
          f"   -> {'MET' if book['hold_met'] else 'NOT MET'}")
    print(f"    GATE -> {'MET' if (book['roi_met'] and book['hold_met']) else 'NOT MET'}")

    if not report.get("subset_n"):
        return
    subset = gate_verdict(report["subset_after_pp"], report["subset_fair"])
    print(f"\n  THE EXCHANGE-QUOTED SUBSET  ({report['subset_n']:,} cells) -- a DIFFERENT"
          f" question, stated beside the book rather than instead of it")
    print(f"    {report['subset_today_pp']:.3f}pp -> {report['subset_after_pp']:.3f}pp"
          f"   gain {report['subset_gain_pp']:+.3f}pp"
          f"   hold -> {subset['hold_pct']:.2f}%")
    print(f"    ROI  {subset['roi_pct']:+.2f}%  -> "
          f"{'MET' if subset['roi_met'] else 'NOT MET'}"
          f"    HOLD -> {'MET' if subset['hold_met'] else 'NOT MET'}")
    print(f"    This is what the exchange is worth WHERE IT QUOTES. It is not the"
          f" book's number: you cannot take a price that is not there, and it is"
          f" not there on {100.0 - coverage:.1f}% of cells. Reporting this one as"
          f" the gate's answer is the population mismatch that 4.05 was hiding"
          f" behind -- a best-book gain on quoted cells, spent against an"
          f" average-book cost over all of them.")
    print(f"    Both legs of this subset are window-sensitive: the sportsbook legs"
          f" are ONE refresh cycle while the exchange leg may be {window_minutes}"
          f" min old. Measured 2026-09-03 at 1/5/15/30 min the gain reads"
          f" +2.130/+2.323/+2.661/+3.292pp on 1.1/2.6/7.2/12.0% coverage -- the"
          f" margin moves, both verdicts do not.")


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
    entry_reports: list = []

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
        # Both sides are kept for the cost derivation -- de-vigging needs the
        # opposite leg, which the gate's under-only filter would have removed.
        two_way_rows = rows
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
        entry_reports.append(derive_entry_cost(two_way_rows, window))
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
    print_gate_verdict(combine_entry_costs(entry_reports), args.window_minutes)
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
