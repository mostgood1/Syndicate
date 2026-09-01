# FINDINGS — the game-market entry-cost → ROI curve, and what item 05 is actually worth

**Session** `02ec72a5-aed0-41b6-bc3b-6a6c1abeca72`, lane `game-market-entry-roi-curve`.
**Date** 2026-09-01. Every number is read off production
(`https://syndicate-an21.onrender.com`) — the served portfolio payloads and the
`book_quotes` shards — not off the local checkout, and each carries its n and
its window.

This discharges the CORRECTION block added to
`findings_2026-08-31_mlb_accuracy_assessment.md` section 7h on 2026-09-01
(`17088500`), which retracted *"+1.57pp is worth about +1.2% ROI"* and asked for
a game-market sensitivity before any substitute was published.

Reproduce: `py -3 scripts/measure_game_market_option_value.py --start 2026-08-22
--end 2026-08-31 --superset`. Tests: `tests/test_game_market_option_value.py`
(30, and each of six deliberate mutations of the script is caught).

---

## 0. The answer, in one paragraph

Exchange price-shopping on MLB game markets is worth **+0.74 ROI points** to the
book that actually stakes money — not the retracted +1.2%, and not the +3.8 you
would get by fixing only the slope. The reason is not the slope: it is that
**62% of the improvement was already banked before the item was written.** The
game board already routes to exchanges, enters at **0.88pp per side** into
quotes holding **1.96% two-way**, and the residual it leaves is mostly held at
books the platform has no execution path to. The retracted number had a third defect nobody had named: the +1.57pp
is **one date**, and pooled over ten the same measurement gives **+1.10pp**.

**The tell, and it needed none of this machinery:** +1.57pp of "improvement" is
larger than the **0.88pp** of entry cost this book pays in total. A gain bigger
than the entire cost it is supposed to be removing cannot be about that book.

---

## 1. The book

MLB game-market paper orders — `h2h`, `spreads`, `totals`, and their `_alt`
siblings, every segment — from `/api/portfolio/paper?date=` over
**2026-08-22..08-31**, the full retained window (nothing before 08-22 returns
orders).

| | n |
|---|---|
| filled orders in game families | 956 |
| settled (`won`/`lost`/`push`) | 929 |
| **priced** (time-aligned two-sided quote from the order's own book) | **621** |

`h2h_3_way` is excluded — a three-way market does not de-vig against one
opposite side — and it is 23 of 999 staked rows.

**This is the order-level view, not the position-level one.** Section 6 of the
08-31 assessment counts positions (`settlement.by_market_family`: game_line 178,
game_total 188) and is a smaller number over a longer window. An entry
improvement applies per ORDER — per venue book that actually took a price — so
that is the unit here. Neither count is wrong; they answer different questions.

Composition of the 621: `totals` 266, `spreads` 176, `h2h` 101, `totals_alt` 47,
`spreads_alt` 31. Books: prophetx 193, kalshi 160, polymarket 89, novig 88,
pinnacle 35, williamhill_us 15, fanduel 10, fanatics 8. Venue books: `paper`
(best-price, unconstrained) 334, `paper:prophetx` 105, `paper:kalshi` 84,
`paper:novig` 53, `paper:polymarket` 45. Outcomes 299 won / 317 lost / 5 push.

---

## 2. THE PRICE IS OLDER THAN THE ORDER — the defect that had to be fixed first

The obvious anchor is `submitted_at`. It is wrong, and it is wrong in a way that
does not error.

On 139 of 584 rows the book's quote **at submission** differed from `fill_price`
by more than 1pp — mean **−2.46pp**, worst −77pp. The board carries a price with
a real age (section 5 of the assessment: `book_age_seconds` median 202s, p90
1,308s), so an order written at 20:00 can be taking a price the book showed at
19:00 and has since moved off.

Taken at face value, that made the book's mean per-side entry cost come out at
**−1.43pp** — paying *less* than fair, on average, which is not a thing — and the
sensitivity table then read **−1.05%** at "today's" cost against a ledger that
read **+5.31%**. A table whose own operating point misses the ledger by six
points is not a table.

**The anchor used here is the last snapshot at or before submission at which
that book showed exactly `fill_price`.** It is self-verifying: the price has to
match to the cent. Median age of that quote at submission: **16.5 minutes**, p90
152 minutes.

After the fix every row's entry cost is positive (min +0.06pp) and the three
anchors bracket:

| | |
|---|---|
| ledger stake-weighted return on these rows | **+6.14%** |
| flat-1u reconstruction at the quoted price | **+6.03%** |
| the curve at the measured cost (0.88pp) | **+6.03%** (identical by construction) |

The payout model was verified against the ledger before use, not assumed: on 929
settled rows `stake × (1/implied(fill_price) − 1)` reproduces the ledger's own
`pnl_dollars` to within 0.02 of a stake on **every** row and to 1e-6 on 833.
This is the ledger's arithmetic with one input changed.

---

## 3. WHAT THE BOOK ACTUALLY PAYS — and it is not 4.05pp

| | per side | two-way hold on the same quotes |
|---|---|---|
| mean | **0.883pp** | **1.957%** |
| median | 0.467pp | 1.029% |
| exchange-booked rows (n=530) | 0.598pp | |
| sportsbook-booked rows (n=91) | 2.546pp | |

**Those two columns are not `hold = 2 × per side`, and the difference is real,
not rounding.** Proportional de-vig charges each side in proportion to its
price, so `c = q(S−1)/S` and `2c = hold` only at even money. This book's mean
implied price paid is **0.4516**, and `2 × 0.883 / 1.957 = 0.902 = 2 × 0.4516`
exactly. Item 07's prop book sat near even money, so its 4.05pp ↔ 8.1% was a
clean doubling; ours is not, and quoting `1.76%` as "the hold" would understate
it by two tenths of a point.

Item 07's prop book pays **4.05pp per side**. This book pays **0.883pp** — a
4.6× difference in where the two books sit on their own curves. That, not the
slope, is why the prop table could not price this.

---

## 4. THE GAME-MARKET SENSITIVITY — the table item 05 needed

n=621, flat 1u, every row re-priced exactly. Each row's own entry cost is scaled
in proportion so the curve passes through the price actually paid.

| 2 × per side | per side | book ROI |
|---|---|---|
| **0.00%** | 0.00pp | **+8.21%** |
| 0.50% | 0.25pp | +7.57% |
| 1.00% | 0.50pp | +6.95% |
| 1.50% | 0.75pp | +6.34% |
| **1.76% — what it paid** | **0.88pp** | **+6.04%** |
| 2.00% | 1.00pp | +5.76% |
| 3.00% | 1.50pp | +4.62% |
| 5.00% | 2.50pp | +2.50% |
| 7.50% | 3.75pp | +0.09% |
| 8.10% — *where item 07's prop book sits* | 4.05pp | −0.46% |

The first column is twice the second, which is the same convention item 07's
table uses. It is **not** this book's measured two-way hold (1.957%) — see the
note in section 3.

**Slope, ROI points per 1pp of cheaper entry:** **+1.91** across 2.50→4.05pp
(the span item 07's table covers), **+2.45** across 0.00→1.00pp (the range this
book actually operates in; the script prints +2.46 because it slopes the
unrounded curve rather than the 2-dp table published here). Item 07's prop table gives **+1.77** over the same
2.50→4.05 span. The published constant was **0.75**.

### Why a slope is not a property of the market type

With flat 1u, a per-side cost `c` and a no-vig probability `p`,
`ROI(c) = mean(w / (p + c)) − 1`, so `dROI/dc = −mean(w / (p + c)²) ≈ −(1 + ROI)/q`
where `q = p + c` is the implied probability paid. **The slope is set by the
book's own realized return and its price level.** Props and games are not
different worlds; they are different W and different q. The two curves land at
1.91 and 1.77 across the same span — close enough that the slope error alone was
the *smaller* of section 7h's two defects, and far enough that neither licenses
the other.

### Two methods, and when they diverge

Item 07 could set one uniform cost on every row because its prop vig was uniform
(3.07–4.63pp across ten market/line cells). This book's is not: 0.60pp on
exchange-booked rows against 2.55pp on sportsbook-booked, a 4× spread. Both are
printed (`--uniform-cost`); they agree to within 0.5 points everywhere on this
book and to 1e-6 on a synthetic uniform book. Proportional scaling is used
because only it keeps the curve on the ledger.

---

## 5. THE ENTRY IMPROVEMENT, RE-MEASURED ON THIS BOOK'S OWN POPULATION

551 of 621 rows carry both a sportsbook and a best-any quote at their anchor
instant. In implied-probability points:

| | mean | median |
|---|---|---|
| exchanges **make available** | **+1.579pp** | +1.310 |
| the board **already took** | **+0.977pp** | +1.066 |
| **still on the table** | **+0.602pp** | +0.000 |

An exchange beats every sportsbook on **73.0%** of these rows — well above the
superset's 52.5%, exactly as it should be: these keys were selected partly
*because* the price looked good.

**The residual is concentrated and mostly unreachable.** It sits on 124 of 551
rows, and **63.7% of it is held at books with no execution path** — betopenly 23,
onexbet 8, williamhill_us 6, gtbets 6, nordicbet 4. Item 05 proposes making the
board read the *venue* feeds; it cannot make the board bet at 1xBet.

### Priced per row — the counterfactual, not the table

Over the same 551 rows:

| entry | book ROI |
|---|---|
| best **sportsbook** price, no exchanges at all | +4.49% |
| the price it **actually took** | **+6.69%** |
| best price at an **execution venue**, or the fill | **+7.43%** |
| best price **any** book showed (unreachable ones included) | +8.45% |
| the **fair** price, zero hold — the ceiling no venue beats | +8.98% |

- **exchange access → +2.20 ROI points. ALREADY BANKED.** Not available to spend
  again. *And this is an upper bound on its value:* without exchanges the board
  would have selected different rows, so removing them while holding the picks
  fixed removes the reason some of those picks exist.
- **routing to the best execution venue → +0.74 ROI points.** This is what item
  05's board change could actually claim.
- perfect shopping anywhere → +1.76 points, an upper bound and not a plan.
- total remaining headroom to a zero-hold venue → +2.29 points.

**Stability.** +0.74 holds at **+0.73 / +0.74 / +0.73 / +0.72** for quote windows
of 15 / 30 / 60 / 120 minutes, and **+0.77** when `betfair`/`matchbook`/`smarkets`
are counted as exchanges. Per venue book it ranges +0.08 (prophetx, n=105) to
+1.64 (polymarket, n=45), with the largest book (`paper`, n=334) at +0.93.

---

## 6. A THIRD DEFECT: +1.57pp IS ONE DATE

Section 7h's superset was reproduced exactly. A "snapshot" is `captured_at` —
the refresh-cycle stamp shared by every book written in one pass — **not**
`snapshot_ts`, which is each book's own last-update time and differs book to
book by a second or two. Grouping on the latter does not error; it silently
returns a near-empty population that still looks like a measurement.

| date | n | exchange improves | mean | median |
|---|---|---|---|---|
| 2026-08-22 | 5,999 | 48.3% | +0.982 | +0.000 |
| 2026-08-23 | 6,924 | 48.3% | +0.979 | +0.000 |
| 2026-08-24 | 224 | 52.7% | +0.594 | +0.211 |
| 2026-08-25 | 19,558 | 47.7% | +0.999 | +0.000 |
| 2026-08-26 | 18,731 | 53.3% | +1.171 | +0.268 |
| 2026-08-27 | 7,211 | 54.2% | +1.260 | +0.365 |
| 2026-08-28 | 10,833 | 55.1% | +1.228 | +0.408 |
| 2026-08-29 | 3,080 | 50.4% | +0.967 | +0.143 |
| 2026-08-30 | 5,414 | 52.2% | +1.059 | +0.221 |
| **2026-08-31** | **13,344** | **52.4%** | **+1.140** | **+0.232** |
| **POOLED** | **91,318** | **51.4%** | **+1.101** | **+0.203** |
| *section 7h published* | *13,093* | *52.5%* | *+1.570* | *+0.240* |

**2026-08-31 alone matches the published population on n (within 1.9%), on the
win rate (52.4 vs 52.5) and on the median (+0.232 vs +0.240)** — the same
measurement on the same day, which is the day the assessment was written. **The
mean does not reproduce**: +1.140 here against +1.570 published, and the gap is
entirely in the tail (p99 +7.49 here against +17.16 published). This run applies
the dead-price filter section 1 of that same document mandates (`|american| >
1000` refused; settled/dead prices contaminate 6.7% of priced games and a naive
backtest over them returned +101% to +331%). Dropping the filter moves the mean
only to +1.244, so contamination is a *plausible* and *insufficient* explanation
— **stated as an unreproduced figure, not a diagnosed one.** The original was a
scratchpad analysis (section 9) and no longer exists to read.

Either way, the mean is the wrong statistic to spend on a distribution whose
median is +0.20pp.

---

## 6b. THE `book_quotes` PUBLISH CLOBBER DOES NOT REACH THIS WINDOW — checked, not assumed

Lane `book-quotes-publish-clobber` (session 3492626c) confirmed on 2026-09-01
that the daily `book_quotes` shard **loses rows**: two services each keep their
own local copy, append only their own rows, and `publish_hot_artifact` pushes
the WHOLE FILE, so web keeps whichever published last. On 2026-09-01 only
**46.1%** of that date is matchable, and they attribute 76% of `#624` step 6's
"no time-aligned quote" exclusions to it.

**Every number above reads those same shards, so this had to be checked rather
than hoped.** Three readings, all mine:

1. **Their own overlap metric, applied to my ten dates: 100.0% matchable on
   every one**, and the sportsbook and exchange spans are *identical to the
   minute* on all ten (e.g. 2026-08-27 both `06:16..04:19`). A clobbered shard
   shows one cohort's tail truncated; none of these does.
2. **Refetch is byte-identical.** 2026-08-27 (87,809 game rows) and 2026-08-31
   (156,220) re-exported ~2.5 hours after the run: **0 lost, 0 gained**. Their
   falsification test was "a clean append target could only ever be a superset";
   these are equal, which is stronger.
3. **The mechanism needs two writers, and in this window there is one.** Every
   one of the 87,809 game rows on 2026-08-27 carries `source: null` — the
   `source=venue_direct` stamp does not exist before the Kalshi capture landed
   at 2026-09-01 16:11Z. Before that date the exchange rows arrive through the
   same OddsAPI writer as the sportsbook rows, which is exactly why their spans
   coincide.

**This bounds their finding rather than contradicting it:** the race begins when
the second writer appears, so it is a 2026-09-01-onward defect. Anyone extending
this measurement past 08-31 must run the overlap check first.

**It does refine one thing I wrote.** The 206
`fill_price_never_quoted_before_submit` refusals are *not* clobbered rows. They
are exchange fills whose price came through a path the OddsAPI feed did not
carry — which is the gap the venue-direct capture was built to close. The
coverage bound stands; its mechanism is named correctly now rather than by
resemblance.

---

## 7. WHAT THIS CHANGES

- **The retracted +1.2% is replaced by +0.74 ROI points**, on the staked
  game-market book, over 2026-08-22..08-31.
- **The published table for reuse is section 4's**, embedded in
  `scripts/measure_game_market_option_value.py` as `GAME_SENSITIVITY` and
  interpolated by `roi_from_table()`. Do not carry a slope constant out of it;
  `tests/test_game_market_option_value.py` pins the 0.75 out and asserts the two
  tables give materially different answers at the cost each book actually pays.
- **Item 05's board change is worth about three quarters of a point on game
  markets, not five and not one and a quarter.** That does not kill it — +0.74
  points on a book returning +6.7% is a 11% relative improvement for a
  routing change — but it is a *small* item, and it should be ranked as one.
- **The order of work in section 7h stands unchanged.** Capture first, then
  measure props, then the board change. Nothing here touches the prop side.
- **`#624` step 6 (MLB prop staking) is unaffected.** It was recorded NOT MET on
  2026-09-01 for its own reasons; this is a separate thread.

---

## 8. WHAT THIS DOES NOT CLAIM

- **Settlement is `settled_by = inferred`** — our own grading, no venue
  confirmation. Section 6 measured real money at **−5.5%** over adjacent days
  against paper's +9.4%. The **level** of the curve is optimistic. The **slope**
  goes as `(1+ROI)/q` and is far less sensitive; the +0.74 is a *difference*
  between two re-pricings of the same rows, so it inherits the level error only
  to first order in the ratio.
- **Ten dates is not a rate.** The per-date superset spread (+0.59 to +1.26pp)
  is wide enough that a different ten days would move the third figure.
- **The priced book is not a random sample of the staked book.** 308 of 929
  settled orders are refused, dominated by exchange fills priced through a path
  the OddsAPI feed did not carry (polymarket 124, kalshi 117 {DASH} and see 6b: they
  are not clobbered rows), and those rows returned **+15.85%** against the
  priced rows' **+6.14%**. The curve's level is therefore
  conservative. The residual is plausibly *overstated* by the same exclusion —
  a venue-direct fill is already at the venue's price, so it has less left to
  claim — which cuts against +0.74 rather than for it.
- **It prices the ENTRY only.** Picks and outcomes are held fixed. It does not
  say the board's selections are good; section 4 of the 08-31 assessment says
  the opposite about `model_edge`, and this book stakes on `ev_basis =
  market_fair` instead.
