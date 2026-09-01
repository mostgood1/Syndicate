# Polymarket vs Kalshi — captured PROP prices compared (2026-09-01, MLB)

First cross-venue price comparison on PLAYER PROPS that has ever been possible
on this platform: exchange prop prices existed in `book_quotes` **nowhere**
before today (0 rows against 26,710 exchange GAME quotes). Kalshi's capture
(`08ecb418`) and Polymarket's (`9a436fab`, lane `polymarket-prop-quote-capture`)
are what make it measurable. This is `#624` step 2 — *THEN measure* — for PRICE
QUALITY only. **It says which venue to buy at. It says nothing about whether our
model beats either of them.**

## Data and method

* Source: `mlb_source/tracking/book_quotes/2026-09-01.jsonl` read from
  PRODUCTION via `/api/ops/artifacts/stream` on web. **The local mirror could
  not answer this** — its newest MLB shard is 2026-08-05/08-09.
* 48,013 rows in the shard (36,381 prop / 11,632 game). Exchange rows:
  `kalshi|prop 1,527`, `polymarket|prop 1,343`, plus game rows from OddsAPI
  which are DELIBERATELY EXCLUDED (an aggregator's copy of a venue price is not
  the venue's price).
* The log is a CHANGE log, so "the price" is the LAST observation per key;
  identity is `_KEY_FIELDS` minus bookmaker.
* American odds → implied probability for comparison. Round-tripping quantizes
  at ~0.25pp near even money — below the venues' 1¢ tick, so it cannot drive a
  median, but sub-0.5pp differences are noise.

## Gate that had to pass first: ASK or MID?

"Which venue is cheaper" is meaningless if one number is a two-sided MID and the
other is the ASK you would pay — the mid venue looks cheaper by half a spread
and the entire result is an artifact. Settled from the data, no external
reference needed, by summing both sides of one bet at one venue:

| venue | two-sided bets | median sum | p90 | sums < 100% |
|---|---|---|---|---|
| kalshi | 253 | **101.04%** | 102.07% | 1% |
| polymarket | 165 | **101.93%** | 104.93% | 0% |

Both are **ASK-side prices**. The comparison is apples-to-apples, and the excess
over 100% IS each venue's round-trip spread.

## The result

**Coverage.** 809 distinct Kalshi prop bets, 632 Polymarket, **390 quoted by
both** (61.7% of Polymarket's book, 48.2% of Kalshi's).

**The two venues agree, to about one tick.** Polymarket implied − Kalshi
implied, n=390: median **+0.00pp**, mean +0.13, p10 −1.09, p90 +1.13,
median |diff| **0.95pp** ≈ one 1¢ tick.

**Staleness is NOT driving it — control passed.** Median gap between the two
venues' last observations is 111.8 min (p90 197.7). Restricted to pairs captured
within 10 minutes (n=93): median +0.00pp, |diff| 0.90pp — statistically the same
answer, so the agreement is real and not an artifact of comparing across time.

**Kalshi is the tighter book, and that is where the "who is cheaper" tilt comes
from.** Better price: kalshi 37%, polymarket 26%, within 0.5pp 37%. Kalshi's
median spread 1.04pp vs Polymarket's 1.93pp (~1.9x) with a much fatter tail.

**But it is market-specific, and that is the actionable part.** Polymarket is
genuinely the better book on PITCHER volume markets:

| market | n | median (poly − kalshi) | poly cheaper |
|---|---|---|---|
| earned_runs | 11 | **−1.13pp** | **73%** |
| hits_allowed | 26 | **−1.13pp** | **58%** |
| batter_hits | 84 | +0.00 | 33% |
| batter_home_runs | 43 | +0.00 | 30% |
| strikeouts | 28 | +1.01 | 21% |
| batter_hits_runs_rbis | 101 | +0.00 | 18% |
| batter_total_bases | 73 | +0.87 | 15% |
| outs | 24 | +0.96 | 12% |

## Cross-venue arbitrage: effectively none

Buying each side at its cheaper venue, 502 two-sided cross-venue pairs: median
**101.92%**, best 96.84%. Pairs below 100% gross: **6 distinct** (1.2%).

**The 12 I first counted were each counted twice** — the same pair in both leg
orderings. Recorded because a doubled count is exactly how a nothing-burger
reads as an opportunity.

Of the 6, **only 2 survive a 10-minute same-instant bound**, both at ~99%
(Busch `batter_hits 0.5`, Torkelson `batter_hits 0.5` — kalshi over + poly
under). The other 4 have legs 49–119 minutes apart, i.e. a stale leg, not a
mispricing. **~1pp gross on 2 of 502 pairs is not an opportunity**: Polymarket's
fee is an OPEN question here (the "measured zero" was retracted as an instrument
artifact; `kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` is a self-described
placeholder), and any plausible fee erases 1pp several times over.

## Bounds — what this does NOT establish

* **One sport, one slate.** MLB, 2026-09-01. n=390 overlapping bets is a real
  sample of a single day, not a rate across days.
* **Spread numbers rest on the two-sided subset only** — coverage is heavily
  one-sided (kalshi 303 one-sided vs 253 two-sided; polymarket 302 vs 165).
* **Nothing here is a model edge.** These are venue-vs-venue price comparisons.
  Whether our projections beat either book is `#624` step 2's other half and is
  untouched by this.
* Prop POSITIONS remain closed by `market_family_excluded`, so none of this is
  currently actionable in the commit path by design.
