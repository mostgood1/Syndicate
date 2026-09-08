# The spreads edge is not concentrated in a few games. It is concentrated in STALE QUOTES — and a stale quote is not a price you can bet.

**2026-09-08, lane `profitable-buckets`, session 3492626c.**
`scripts/bucket_edge_concentration.py`. 10 days of MLB ledger, 93 games.

## What was asked, and what the answer turned out to be

`spreads q4_late` measured +14.22pp at +2.93σ over 93 games — the only bucket
clearing a family-wise bar. The question was whether a few lucky games carried
it. They did not. Something worse did.

## Not concentrated by game, and it CANNOT be

Each game contributes `won − implied`, bounded in ±0.5, because the outcome is
binary and every bet is one unit. This is not a P&L where one position carries
the book: per-game contributions ran −0.881 to +0.781, and the top 5 of 93 games
gave +3.59 of +13.22 (27%). "Concentrated" here can only ever mean "a few coin
flips", never "one outlier". Worth stating because the naive concentration
question sounds more informative than it is.

## Not concentrated by date either

All seven dates positive (+1.06pp to +29.08pp). Leave-one-date-out: the worst
case is dropping 2026-09-07, which still leaves **+12.22pp at +2.31σ on n=82**.
The edge survives removing any single day.

## It scales with disagreement — and THAT is what exposed it

| tercile | mean \|model − market\| | n | edge | sigma |
|---|---|---|---|---|
| low | 2.65pp | 31 | +4.84pp | +0.54 |
| mid | 9.74pp | 31 | +2.33pp | +0.26 |
| **high** | **28.66pp** | 31 | **+35.47pp** | **+6.68** |

This test was included because a real edge should be larger where the model
differs more — that is what "the model knows something" means mechanically.
The profile is monotone in the right direction, which read as confirmation.

**+35.47pp is not confirmation. Nothing beats a book by 35 points.** A number
that large is a broken join or a leaked outcome, and the band it appears in —
LATE innings — names the mechanism.

## The mechanism: the model has the score, the quote does not

| | n | median quote age |
|---|---|---|
| high disagreement (≥15pp) | 32 | **254s** |
| low disagreement (<15pp) | 61 | **172s** |

**The games where the model "disagrees" most carry quotes 82 seconds older.**
Across the bucket, median quote age is **186s** and the maximum is **593s** —
the publish gate is `max_quote_age_seconds` 600s, which is loose enough to admit
a quote from three half-innings ago in a market that resolves in nine.

Restricting to quotes fresh enough to plausibly hit:

    fresh <= 120s   n=30   edge +9.88pp +/-8.80   (+1.12 sigma)
    all             n=93   edge +14.22pp +/-4.85  (+2.93 sigma)

The edge falls from +2.93σ to **+1.12σ**.

**This is not proof the whole thing is staleness.** n drops 93 → 30, so the
point estimate falls only ~30% while the standard error nearly doubles; the
fresh subsample cannot rule a real edge in OR out. What it can do, it does: it
removes the significance, and the age gradient across disagreement terciles is
independent evidence pointing the same way.

## The practical conclusion does not depend on resolving that

**A 186-second-old quote is not a price you can bet.** Whether or not a real
edge hides underneath, the measured edge is computed against prices that were
gone before anyone could act on them. Reporting `spreads q4_late` as a
profitable bucket would be reporting money that cannot be collected.

## What this changes

1. **`spreads q4_late` is NOT a bettable bucket on this evidence.** The lane's
   one candidate is withdrawn.
2. **Bucket measurement must be quote-age aware from here.** Any bucket table
   that pools across quote ages is measuring the book's latency as much as the
   model's skill, and the ledger already carries `quote_age_seconds`.
3. **The real question for tradeability is narrower and harder**: is there an
   edge against quotes ≤60s old? n=8 today — UNMEASURED, and it needs far more
   days rather than a cleverer statistic.
4. `max_quote_age_seconds = 600` deserves a look for the LIVE path
   specifically — recorded for another lane, not chased here.
