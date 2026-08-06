# The OddsJam-class board, and where the sim actually earns its keep

Research pass 2026-08-06, requested directly. Extends
`plan_one_opportunity_pipeline.md` §9, which named the five signals; this one
establishes **what the target product actually is**, **what we measurably have
against it**, and **the specific ways a simulation beats a market-only tool**.

Everything numeric below is measured on the real production MLB shard for
2026-08-06 (122,023 rows, 11 books), not estimated.

---

## 1. What OddsJam actually sells

Eight surfaces, from their own product pages:

| surface | what it does | data it needs |
|---|---|---|
| Arbitrage finder | odds discrepancies across books where both sides lock a profit | every book, both sides, **simultaneous** |
| Positive EV finder | book price beats no-vig fair price | fair probability |
| Middles finder | different lines each side; both win if the result lands between | line ladder per market |
| Low hold finder | markets with near-zero combined margin | both sides, best price each |
| Odds screen | every book's price for every market | full book × line matrix |
| Bonus/promo conversion | convert bonus bets at ~80c on the dollar | promo terms + odds |
| Bet tracker | grades bets, tracks **CLV vs the sharpest book** | bet-time price + close |
| Live odds | all of the above in-game, updating every second | live capture cadence |

**Their fair-value method is the load-bearing part.** OddsJam computes *no-vig
fair odds* from books that take sharp action — Pinnacle, Circa, BetOnline,
Heritage, the Betfair exchange — and calls a retail book +EV when it beats that
fair price. Their own docs are explicit that filters exist to ensure a bet is
"+EV to the no-vig fair odds of a variety of sharp bookmakers," and equally
explicit that the weighting is tuned by machine learning against tracked
results. The fair line is **derived from the market**. That is the whole ceiling
of a market-only tool, and it is the seam we can beat.

---

## 2. Where we stand, measured

| | OddsJam | Syndicate |
|---|---|---|
| books | 150+ | **11** (draftkings, betmgm, betrivers, williamhill_us, fanduel, fanatics, bovada, betonlineag, mybookieag, betus, lowvig) |
| sharp anchor | Pinnacle / Circa / exchange | **none captured** — closest are lowvig, betonlineag, mybookieag |
| both sides captured | yes | **yes** — over 52,031 / under 36,814 / home 15,971 / away 15,948 / draw 1,259 |
| de-vig / fair probability | yes | **no — does not exist anywhere in the codebase** |
| arbitrage / middles / low-hold | yes | not written |
| odds screen | yes | not built (data is present: `quote.alternatives` already carries every book) |
| CLV | vs sharpest book | shipped (#213 bet-time quote, #214 closes) |
| **simulation** | **none** | **yes — the differentiator** |

### 2.1 The single highest-leverage defect: we never de-vig

`quote_enrichment` computes `ev_pct = model_probability − implied(best_price)`
using the **raw** implied probability, vig included. Measured hold across our
own two-sided markets:

```
median hold 6.25%    p10 3.27%    p90 7.36%
```

A two-sided hold of 6.25% means one side's implied probability is inflated by
roughly **3.1 percentage points**. So every EV number the board has ever shown
is biased low by about that much. A row displaying `+1.0%` is really `≈ +4.1%`;
rows sitting just under an edge threshold are being discarded while genuinely
+EV. Fixing this re-ranks the entire board and *expands* it — before a single
new feature is written.

### 2.2 What the signals look like in our data — and the traps

First measurement pass reported 716 arbitrages. Nearly all were artifacts, and
the artifacts are the real engineering finding:

1. **Spreads are signed per side.** home −1.5 pairs with away **+1.5**, never
   away −1.5. Pairing on equal `line` manufactures "arbs" out of bets that are
   not opposite sides of anything.
2. **3-way markets have a draw.** `h2h_3_way` paired as home+away fabricated 7
   of the 10 survivors.
3. **The shard is an append-only log over the whole day, including live play.**
   "Freshest price per book" cheerfully pairs a pregame number with an
   8th-inning one. Requiring both legs within 180s of each other and within
   30 min of the shard's end **dropped 88% of pairs** (2,354 → 282).

After all three corrections:

| signal | count | example |
|---|---|---|
| two-sided, fresh, simultaneous | 282 | — |
| arbitrage | ~3 real | `totals 9.5 — over bovada +130 / under fanatics −125` (−0.97%) |
| low hold <2% | 10 | `spreads 7.5 — fanatics −130 / fanduel +130` (0.00%) |

**Conclusion: pure arbitrage is not our product.** With 11 books and no
exchange, real arbs are rare (~1% of fresh pairs) and mostly small. Chasing
them without simultaneity and 3-way guards produces a board that cries wolf —
which is worse than not shipping the feature. Low-hold and +EV are far more
abundant, and the sim edge is more abundant still.

---

## 3. How the sim earns its keep — the determination

OddsJam has exactly one probability source: the market, de-vigged. We have
**two**, which is a difference in kind, not degree.

```
p_book    the individual book's implied probability (vigged)
p_market  de-vigged consensus across our books   <- what OddsJam has
p_model   the simulation's probability            <- what they cannot have
```

Three distinct, separately actionable signals fall out:

**(a) Market edge — `p_market − p_book`.** Classic +EV / line shopping. Needs
no sim at all. This is table stakes and we should ship it because it is the
signal with the least model risk. #211 already measured price shopping alone at
**+2.79 ROI points**.

**(b) Model edge — `p_model − p_market`.** The claim that *the market itself is
wrong*, not merely that one book lags. This is structurally unavailable to a
market-only tool, and it is the only signal that can find value when **every
book agrees**. OddsJam is blind by construction to a correctly-consensus-priced
market that is simply mispriced against reality.

**(c) Agreement as a false-positive filter — `|p_model − p_market|`.** This is
the subtle one and probably the most valuable in practice. A market-only tool's
dominant false positive is the **stale line**: a book looks +EV only because it
has not moved yet, and it will move before the bet settles. OddsJam cannot
distinguish "this book is soft" from "this book is late," because both look
identical in market data. An independent simulation can: if the sim agrees with
consensus and one book is off, that book is *soft* (real +EV); if the sim agrees
with the offside book, the market is *moving* and the edge may be genuine but
fleeting; if the sim disagrees with both, stand down.

That yields a 2×2 the product can actually speak in:

| | model agrees with market | model disagrees with market |
|---|---|---|
| **one book off consensus** | **soft book — highest-confidence +EV** | market may be mid-move; treat as steam, not value |
| **all books agree** | no edge — pass | **sim-only edge — our exclusive signal, highest variance** |

**(d) Markets books price thinly.** The sim produces *distributions*, not point
estimates, so it can price a full alternate-line ladder (and derive fair odds
for lines no book is currently offering). A market-only tool has nothing to say
where there is no market.

**(e) CLV is the referee, and we already have it.** #213 records the quote
struck at bet time; #214 derives closes from the log. So each bucket above can
be *measured* against the closing line rather than argued about. This is the
thing that converts "our sim is an edge" from a claim into a number, and it
should gate how loudly each signal is ranked.

---

## 4. What the boards become

**Layer 2 (the main board) — an opportunity feed, ranked by signal.** Every
card carries one honest headline number and its provenance:

- signal type: `+EV` · `SIM EDGE` · `ARB` · `MIDDLE` · `LOW HOLD` · `STEAM`
- `fair` (de-vigged) vs `best book + price` vs `p_model`
- EV% **computed against fair, not against a vigged price**
- hold %, books quoting, book age (the two clocks already shipped)
- filters/sorts by signal type, EV threshold, sport, book, time to start

**Layer 1 (betting board) — the odds screen.** Every book × every line for a
market. The data is already on the wire: a served row today carries
`quote.alternatives` with all 7 books and their prices. Add the de-vigged fair
and per-market hold as a column and this is a screen OddsJam users would
recognise, built entirely from artifacts we already have.

---

## 5. Order of work

**Stage 0 — coverage, or none of it matters.** The board currently renders a
price strip on **30 of 144 cards**. Serie A is 0/60 because soccer captures no
`book_quotes` at all (404 while mlb/wnba/nfl exist); WNBA was 2/20 because
refresh-worker froze on a 21:03Z shard (#237, shipped). Signals cannot be
computed for markets whose prices never arrive.

**Stage 1 — `opportunity_signals.py`.** Pure functions, heavily tested:
`devig()`, `fair_probability()`, `hold()`, `expected_value()`, `arbitrage()`,
`middle()`, `low_hold()`, `model_edge()`. Must encode the three corrections
above (signed spreads, 3-way draw leg, simultaneity/staleness) — they are not
edge cases, they were 88%+ of the raw signal.

**Stage 2 — attach to the candidate contract**, so all five hang off one
object, per `plan_one_opportunity_pipeline.md` §9.

**Stage 3 — Layer 2 surfaces and filters.**

**Stage 4 — Layer 1 odds screen.**

**Stage 5 — CLV feedback per signal bucket**, which decides the ranking weights
with evidence instead of taste.

---

## Sources

- https://oddsjam.com/betting-tools
- https://oddsjam.com/betting-education/how-do-positive-ev-sports-betting-filters-work
- https://oddsjam.com/betting-tools/low-hold
- https://oddsjam.com/betting-tools/positive-ev
