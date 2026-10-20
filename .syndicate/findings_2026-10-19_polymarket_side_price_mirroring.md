# MIRRORING IS FALSIFIED. Polymarket itself publishes BOTH legs at the cap on 212 of 4,967 spread markets (4.3%), and the board renders an uncapped ask as a tradeable price

`[2026-10-19 22:5xZ / 5:5x PM CDT]` lane `polymarket-side-price-mirroring`
`[no outcomes used anywhere in this document]`

## The question, and the answer

I raised this myself earlier today: are the 73 NCAAF spread rows whose two sides
sum to 1.96 a real untradeable market, or is **one Polymarket quote being
MIRRORED onto both board sides**? I leaned toward mirroring, because 70 of 73
carried the price identical to the digit and the sums sat at almost exactly
`2 x implied(price)`.

**Mirroring is FALSIFIED.** The venue's own payload carries **two distinct
outcomes with two independently priced legs**, and on a measurable subset it
prices **both of them at the cap**. Nothing is being duplicated.

From `reports/intelligence/polymarket_us_games.json`, the capture whose shape
`venue_quote_adapters._polymarket_sides` actually consumes (`row["outcomes"]`,
`row["outcomePrices"]`):

```
slug     asc-cfb-wkent-nmxst-2026-10-01-neg-21pt5
outcomes ["-21.50", "+21.50"]          <- two distinct handicap sides
prices   ["0.0900", "0.94"]            <- sum 1.03, a normal market
```

and the population figure that answers the lead:

```
spread-shaped markets in that capture : 4,967
with BOTH legs priced >= 0.975        :   212  (4.3%)
```

**212 markets where the venue publishes both sides at 0.98-0.99.** That is the
signature of my 73 board rows (−4900/−4900 = 0.98/0.98 → 1.96;
−9900/−9900 = 0.99/0.99 → 1.98), and it is present in the venue data before the
board touches it.

## Why I was wrong, and what the evidence should have told me

Three things I had in hand and misread:

1. **"Identical price on both sides" is not a signal at all.** Measured on the
   served board: `fanduel` carries identical prices on **122 of 243**
   complementary pairs (50%) with a median sum of 1.0654 — perfectly healthy. A
   balanced market quotes −110/−110. **The sum is the signal; identity never was.**
2. **Polymarket is mostly fine.** 57 complementary pairs, median sum **1.0295**
   — *tighter* than every sportsbook, as a low-fee exchange should be. Only 17
   pairs exceed 1.30. I generalised from the broken tail to the whole venue.
3. **The adapter rules mirroring out by construction.** `_polymarket_sides`
   derives the side's ROLE from the slug via `parse_slug` + `teams_match`, and
   its docstring states array position is **deliberately not used** ("Measured
   2026-08-24 on real spread rows: the order of `outcomes` does not reliably
   follow the slug — 1 of 5 sampled rows would have been priced on the opposite
   handicap. A team we cannot place is REFUSED rather than assigned
   positionally"). A positional zip is the only way one price reaches both
   sides, and that is exactly what this code refuses to do.

## The control that makes this Polymarket-specific

Served board, cap defeated, single same-instant fetch, **complementary pairs
only** — spreads require opposite signed lines, totals require equal ones:

| book | pairs | identical | med sum | max sum | **sum > 1.30** |
|---|---|---|---|---|---|
| **polymarket** | 57 | 20 | 1.0295 | **1.9600** | **17** |
| draftkings | 230 | 7 | 1.0693 | 1.0833 | **0** |
| fanduel | 243 | 122 | 1.0654 | 1.0713 | **0** |
| betmgm | 211 | 23 | 1.0723 | 1.0983 | **0** |
| pinnacle | 122 | 2 | 1.0696 | 1.0803 | **0** |
| kalshi | 48 | 0 | 1.0104 | 1.0497 | **0** |

**854 complementary pairs across five conventional books, not one above 1.0983.**
Polymarket has 17 above 1.30. The pathology is isolated to the venue.

**That gate mattered, and my first run was wrong without it.** Ungated, the
controls looked just as bad (draftkings max 1.8704, fanduel 1.7628). Every one
of those was **my join**: MLB `spreads_alt` carries the **same signed line on
both sides** (+1.5 / +1.5), so those rows are not opposite sides of one bet and
must never be paired. Exposing the signed lines in the dump is what caught it.

## What the degenerate markets actually are

From the sibling `venue_odds` capture family (`{yes, no, ts}` quote history),
which corroborates the picture without being the board's own path:

- **`yes + no` is an ASK SUM, not a probability pair.** Median **1.06–1.08**,
  and within 0.02 of 1.0 only **251 of 5,400** records. Example: `no: 0.985`
  steady while `yes` moves 0.08 → 0.155 — `no` is not `1 − yes`.
- **`1.98` is the signature of both legs pinned at 0.99.** In the two stale,
  far-dated captures (game dates 10-27/10-28, fetched **10-15**) the *median*
  sum is **1.9800** with 0 of 87 near 1.0 and both legs pinned on most records.
  In the fresh captures (fetched 10-19 18:02) the median is 1.06–1.08 and
  pinning is a minority.

So the reading is: **an illiquid or far-dated market has no two-sided book, and
the venue represents that absence as a cap-level ask on each leg.** The board
then converts an ask into a "price", and both sides of such a market arrive at
~0.98. There is no mapping defect; the quote was never tradeable.

## What this means for the board

- **The de-vig band is correct and is the right guard.**
  `opportunity_signals._MAX_OVERROUND = 1.60` (`:182`) refuses a 1.96 overround,
  which is why these rows carry no fair and no `ev_pct` and are unsizable.
- **Lane `fair-price-v2`'s new reason code is accurate.** `5410d7e9` labels
  these `two_sided_devig_refused`, and that is literally what happened.
- **The open question moves upstream and becomes a product decision**, not a bug:
  should a market whose **both** legs sit at the cap be surfaced at all? It
  cannot be traded profitably on either side, and admitting it costs 73 ranked
  shortlist rows carrying up to ±33 points of `model_edge_pct` that inflate
  every coverage census. Excluding a quote whose two legs sum above the de-vig
  band at the INGEST boundary would remove them before they are ranked, rather
  than refusing them at the fair.
- **The token-id discriminator I handed that lane is answered and should be
  retired:** there are two distinct outcomes, so it is not one id read twice.
  `polymarket_markets.json` shows outcomes as dicts carrying separate
  `token_id`s; `polymarket_us_games.json` shows them as plain handicap strings.
  Either way the pair is genuine.

## What is NOT shown here

- **No outcomes were used.** Nothing here tests whether any of these rows would
  win or lose; the claim is about quote structure.
- I did **not** locate my 73 specific games inside an `outcomePrices` capture:
  `polymarket_markets.json` is `truncated: True` (2,000 of 20 pages, fetched
  **10-01**) and holds only 3 spread markets, while `polymarket_us_games.json`
  holds the spread population but I matched it by team token, not by the board's
  `event_id`. So the **212 of 4,967** is the population fact; the per-row join
  from those 73 board rows back to their exact venue records is not done.
- The 3 rows whose sides DIFFER were still never examined, and they remain the
  natural control for anyone revisiting this.
- Whether 4.3% is stable or slate-specific is untested — it is one capture.

## Addendum 2026-10-19 23:3xZ — a shape I missed, and an independent reproduction

Lane `fair-price-v2` re-derived this before retiring the lead (`6990d9a4`):

- **The 212 reproduces.** They counted **5,124** spread-shaped records where I
  counted **4,967**, with the same 212 two-outcome/two-price markets at both
  legs ≥ 0.975. The gap is a later capture or a slightly different shape filter;
  the population fact is unchanged.
- **A shape my write-up did not cover:** **158 records carry two outcomes but
  only ONE price** (35 of them at ≥ 0.975). That shape *could* have produced
  mirroring — one price for two sides is exactly the mechanism I hypothesised.
  **It does not**, and the reason is mechanical: `_polymarket_sides` refuses a
  length mismatch outright at `venue_quote_adapters.py:1273`
  (`if not outcomes or not prices or len(outcomes) != len(prices)`), so those
  records never reach the board. They sampled 6 and got `None` for all 6;
  the line confirms it for all 158.

So mirroring is falsified on **both** shapes — the two-price case because the
legs are independently priced, and the one-price case because the adapter
refuses it before any side is assigned. I had only tested the first and should
have enumerated the shapes rather than the population.

## Addendum 2026-10-20 — the control I twice named and twice skipped, now measured

I called the markets whose sides DIFFER "the natural control" twice and never
looked at them. Measured over the same capture (`polymarket_us_games.json`,
21,817 records, 4,967 two-leg spread-shaped):

| leg state | n | share | med sum | min | max |
|---|---|---|---|---|---|
| neither leg pinned (< 0.975) | 4,023 | 81.0% | 1.0100 | **0.0000** | 1.9100 |
| **ONE leg pinned** | **732** | **14.7%** | **1.0550** | 1.0000 | 1.9600 |
| BOTH legs pinned | 212 | 4.3% | 1.9800 | 1.9600 | 1.9800 |
| length mismatch (adapter refuses) | 158 | — | — | — | — |

**The control settles the falsification far better than the original argument
did.** 732 markets carry one leg at the cap and the other cheap — e.g.
`asc-nhl-pit-phi-2026-09-30-neg-2pt5` at `["0.9800", "0.04"]`, sum 1.02, which
is an ordinary near-decided market. **Under mirroring those 732 could not
exist**: one quote copied onto both sides can only ever produce the both-pinned
shape. Independent pricing is now shown directly rather than inferred from the
adapter's docstring, and the both-pinned cluster is strikingly tight
(min 1.9600, max 1.9800) where the other states span widely.

It also confirms the 158 length-mismatch records the `fair-price-v2` lane found,
to the record — the adapter refuses those at `venue_quote_adapters.py:1273`.

### But it also shows my 212 is a LOWER BOUND, which I had not said

The cap-based count misses two degenerate shapes:

- **`neither leg pinned` reaches a sum of 1.9100** — e.g. two legs around
  0.95/0.96, neither at the 0.975 cap, yet as untradeable as the ones I counted.
- **and a sum of 0.0000** at the bottom, i.e. both legs priced at zero, a state
  I never considered at all.

So "212 of 4,967 (4.3%)" understates the venue pathology, and anyone quoting it
as the size of the problem would be quoting the subset my threshold happened to
catch. **The board-side refusal is NOT affected and is the better instrument
for exactly this reason:** it keys on the de-vig band
(`opportunity_signals._MAX_OVERROUND = 1.60`) via "no fair AND no `ev_pct`", so
it catches every pair the de-vig rejects — including the 1.91 sums the cap
misses — rather than a hand-picked cap. That is an argument for where the guard
lives, not a defence of the 212.
