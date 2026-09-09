# FINDINGS — S6 venue routing: the lever is real, unreachable today, and the obvious fix is the wrong one

`[2026-09-09, lane segments-joint-v1, one measurement agent + a code read of the module's own guards]`

## The measurement that started this

Production read `/api/board/layer2-shortlist?sport=mlb&date=2026-09-09&limit=5000`
at **2026-09-09T12:41:12Z**, board `written_at` 12:30:40Z, 775 rows, 21,749
opportunities considered.

Population reconstructed to match the audit's figure — MLB `kind=prop`,
`side=under`, excluding `batter_home_runs` and `batter_hits_runs_rbis`:
**279 rows / 15 games / 131 players** (hits 97, rbis 76, total_bases 60,
strikeouts 27, outs 13, earned_runs 6).

**Reachability: 0 of 279.** Using `scripts/read_venue_basis.py`'s own predicate,
which deliberately separates "the attach ran" from "a quote matched this side":

| | count |
|---|---|
| rows carrying the `venue_basis` key | 279 / 279 |
| rows where it is a non-null dict | **0 / 279** |
| Kalshi | 0 |
| Polymarket | 0 |

Board-wide only 26 rows carry any verdict, all `game`/`totals`, and every one
refuses with *"pregame row: this path exists only for live markets"*.

## The cause is a guard, not a join

`venue_basis_edge.py:303-308` refuses whenever `is_live` is false. Every one of
the 775 board rows is `game_state=pregame`. **Prop unders are priced pregame, so
the code exits before the join is ever reached.** Deploy 1's separate 7-of-600
Kalshi join problem does not even bind here.

## Do NOT "add a pregame path" to this module

This is the trap, and the module's own docstring is what disarms it. Its guards
are not incidental — they are load-bearing for a specific claim:

- **Guard 1:** *"THE VENUE MUST BE ONE THAT TRADES IN-PLAY. The whole argument
  above rests on it."*
- **Guard 5:** a live venue price against a PREGAME book consensus *"is not an
  edge, it is two clocks"* — measured ~0.90 against ~0.55 on a team three runs up
  in the 7th, **a 35-point number that is entirely vintage and is shaped exactly
  like the finding this module exists to surface.**

`venue_basis_edge` detects **in-play mispricing**: the exchange and the books
disagreeing during a game. The audit's lever is **entry cost**: paying less vig
to take a position. Those are different computations over the same two prices.
Extending the mispricing detector into pregame would repurpose it, inherit
guards designed for another question, and re-open exactly the failure guard 5
exists to prevent. The module also records that a previous unmeasured live-edge
attempt was **shipped and backed out** after pricing three already-won props at
+36.5%/+32.3%/+15.8% straight to the top of an edge-ranked board.

## What entry-cost routing actually is, and why it is a better bet

Pregame the exchange and the book largely AGREE on the price. The difference is
the hold you pay to enter. That is observable at entry and needs no view about
who is mispriced.

Measured over 212 paired over/under rows from the same read, fees per
`venue_fees.py:480`/`:544`:

| | n | p10 | median | p90 |
|---|---|---|---|---|
| Kalshi gross | 212 | +0.98% | **+1.96%** | +2.97% |
| Kalshi net, FULL rate (what the code assumes today) | 212 | +4.14% | **+5.09%** | +6.28% |
| Kalshi net, TRUE half rate | 212 | +2.61% | **+3.55%** | +4.62% |
| Polymarket net (150bps × 2) | 110 | +4.05% | +5.97% | +11.00% |
| Book two-way hold, same rows | 212 | +6.51% | **+6.89%** | +7.40% |

**The audit's 2% target is not attainable.** Kalshi's *gross* 1.96% is
essentially that case, but the fee is real and roughly doubles it. **~3.5% is
attainable.** Interpolating the audit's own ladder (+6.52% ROI at a 2% hold,
+0.98% at ~8.1%), a 3.55% hold is about **+5.1 ROI points against +0.98 today —
a prize of ~+4.1 points, not the +5.5 implied by reading 8.48 as attainable.**

**The 8.48pp figure must stop being quoted bare.** It is ROI at ZERO hold, which
no venue offers. Quote the ladder or quote ~+4.1.

## S6a, already delegated, is worth 1.64 points of that on its own

`venue_quote_fanin.py:1665` passes `kalshi_fee_multiplier=None` unconditionally,
so `venue_basis_edge.py:435` assumes the FULL rate on every Kalshi row. These MLB
series are documented at x0.5 (`venue_fees.py:37-39`). Median hold 5.09% → 3.55%
is **1.64 points**, ~1.5 ROI points on the ladder. The fix is cheap: `venue_ref`
is populated on 257 of 279 rows and already carries the series ticker
(`KXMLBHIT-…`, `KXMLBTB-…`, `KXMLBKS-…`, `KXMLBOUTS-…`).

Note the stamp's denominator today is zero — **0 matched rows carry
`fee_is_upper_bound`, because 0 rows are matched at all.** The mechanism is live
and unexercised, which is not the same as absent.

## Scope for S6b — pregame venue entry-cost routing (NOT yet delegated)

A NEW computation, beside `venue_basis_edge`, not inside it.

- **Question it answers:** for a row we already want, which venue costs least to
  enter, net of fee, right now.
- **It must NOT emit an edge or a pick.** Output is a routing preference plus the
  two holds and the fee basis. `servable` stays the existing bar's problem.
- **Guards it INHERITS from the live module and must not drop:** the venue quote
  must name THIS fixture (`#603`: 26 of 28 live Polymarket totals quotes were
  shared across games, one quote answering four fixtures at once); a one-book
  consensus is not a consensus; and both sides must be same-instant, since a hold
  computed across two vintages is the same "two clocks" error in a cheaper hat.
- **Guards it does NOT need:** the in-play venue requirement and the live-vintage
  book requirement, which exist for the disagreement claim.
- **The caveat that decides whether any of this is real: FILL.** A 3.55% hold you
  cannot fill is worth nothing, and the audit's own pipeline sketch says *route
  by effective hold AND fill probability*. Depth and fill are UNMEASURED here.
  **No saving may be claimed until fill is measured** — an exchange quote is not
  a fill.
- **Grading is available, which is why this is worth doing at all.**
  `bet_status_mlb.py:88-98` maps every market in this population to a box-score
  stat and MLB is a registered resolver (`paper_settlement.py:888`). So "score it
  before serving it" is possible for MLB today, unlike soccer and NFL props,
  whose resolvers refuse. UNVERIFIED: whether prop orders have historically
  graded — the production read used `all_dates=false` and showed 0 orders on the
  date.

Sequence: land S6a, then measure fill depth, then build S6b, then score it, then
argue about serving it. Not before.
