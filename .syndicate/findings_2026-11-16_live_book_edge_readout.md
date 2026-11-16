# Live book edge readout — 2026-11-16 (lane `portfolio-edge-measurement`, session 69d80317)

**Question (user, 2026-11-16):** "Right now I'm seeing a solid win rate for the last week — when can we start
to increase investments to see more passive income?" (pasted: the `/portfolio` by-day pivot, 11-06..11-16).

**Answer in one line:** the live book has NOT shown an edge. The win rate is below the breakeven win rate
implied by the prices paid. The last 30 days are negative at about 95% confidence, so scaling now scales a loss rate.

## Substrate

- Fleet `GET http://127.0.0.1:10000/api/portfolio/live?on=all&show=all` (X-Admin-Token), read 2026-11-16
  ~15:50Z (9:50 AM CST): 2,216 live orders, 4.18 MB. Production, not the git mirror.
- Kept: `is_position` (the same predicate as the by-day pivot), outcome in won/lost/push, stake > 0, `fill_price`
  converted through `execution_ledger._price_as_probability` (`[ledger-price-units]`).
- Breakeven per bet = `p_fill * (1 + fees / stake)`. Excess wins = actual wins − Σ breakeven over decided bets;
  z = excess / sqrt(Σ be(1−be)).
- ROI SE is clustered by `event_id`, so correlated bets on one game are not counted as independent.
  Aug/Sep rows carry no event id (552 `venue_rebuild` rows), so their SE is not meaningful.
- Reproduces the pasted table to the cent on 9 of 10 days. 11-13 differs by one row (66 vs 67 settled; −7.25 vs −9.08),
  which is a row whose fill price is outside (0,1).

## Numbers (dollar ROI net of fees; ± = 1 event-clustered SE)

| window | bets | events | staked | P&L | ROI | win % | breakeven win % | excess wins (z) | fees |
|---|---|---|---|---|---|---|---|---|---|
| pasted 11-06..11-15 | 693 | 296 | $731.16 | −$14.67 | −2.0 ± 4.3% | 57.2 | 58.0 | −5.6 (−0.44) | $22.20 |
| last 7 (11-09..11-15) | 449 | 186 | $388.68 | +$2.80 | +0.7 ± 5.0% | 58.7 | 59.3 | −2.6 (−0.25) | $10.51 |
| last 30 (10-17..11-15) | 1,526 | 641 | $3,006.48 | −$218.64 | **−7.3 ± 2.8%** | 54.0 | 56.2 | −32.5 (−1.72) | $87.90 |
| Nov 1-15 | 971 | 413 | $1,373.46 | −$104.10 | −7.6 ± 3.6% | 55.7 | 57.5 | −18.1 (−1.20) | $41.93 |
| Oct | 555 | 239 | $1,633.02 | −$114.54 | −7.0 ± 4.3% | 51.2 | 53.8 | −14.3 (−1.26) | $45.97 |
| all live settled | 1,946 | — | $5,264.82 | −$580.04 | −11.0% | 51.1 | 53.6 | −50.2 (−2.35) | $153.79 |

- **Win rate is the wrong instrument.** The book buys mostly favourites and alt lines. The average breakeven over the pasted
  window was 58.0%, so a 57% win rate LOSES. 11-15's 75% win rate (39-13) made $0.98 on $51.87.
- **The last 30 days are negative at ~95%.** Upper bound −7.27 + 1.96 × 2.84 = −1.7%.
  The "solid week" is +0.7 ± 5.0%: noise around that mean, and indistinguishable from −9%.
- **Fees are 2.9% of stake.** Before fees, last-30 ROI is still −4.35%, so fees are not the whole loss.

## Three things that bear on scaling

1. **The largest stakes lose the most.** Last-30 stake quartiles:
   - Q1 ($0.00-0.51): −11.2%.
   - Q2: −3.6%.
   - Q3: −2.5%.
   - **Q4 ($2.70-9.84): 63% of all dollars, −9.2%, z −2.17.**

   Scaling makes more bets look like Q4.
   Dollar ROI is also worse than flat ROI in Polymarket (−12.2 vs −2.0) and alt spreads (−5.8 vs +0.3).
2. **Stated EV does not predict results.** EV 2-4%: −13.6% dollar ROI (−4.4% flat), 339 bets. EV 4-7%: −5.0% (−6.8% flat), 727 bets.
   The book's own +4-7% EV claim realises about −5% (same family as `findings_2026-10-19_ev_overstatement_decomp.md`).
3. **Same-book CLV contradicts results.** On 546 last-30 bets with a same-book close:
   - CLV is +1.32% mean, 62.5% positive.
   - Settled excess wins are z −3.35 (flat ROI −10.4%).

   On 404 bets with a different-book close: CLV +1.38%, z +0.92. Either CLV is mis-measured on venue contracts
   (side/`held_side`, the unit, or the fee), or venue closes are not efficient. Either way, **CLV cannot be the
   early-warning instrument for a scale-up gate until this is reconciled.** Next diagnostic for this lane.

## Segments (last 30; evidence for per-LINE fixes, never a market switch — learnings line 1056)

- No sport, market, venue or price band is significantly positive.
- Significantly negative:
  - NCAAB: 105 bets, win 34.3% vs breakeven 51.0%, z −3.45, flat −31.8% (lane `ncaab-live-edge20-prereg` is open).
  - Totals: 379 bets, z −2.11, −12.8%.
- In-play (`inplay_order_dollars`, 211 bets): −7.7 ± 6.0%, with no CLV available.
- Volume: 54.5 bets / 22.9 events / $107 staked per day.

## Capital and caps (read 15:48Z)

- Kalshi: $284.98 cash + $10.87 positions. Polymarket: $150.62 buying power.
- Caps: 5% of capital per order ($14.79 / $7.53) and 50% per day ($147.93 / $75.31). Ceilings: $100/order, $2,000/day.

## Scale-up gate — PROPOSED, NOT APPROVED (the user decides)

Every condition is measured FORWARD from a frozen policy (no mid-window changes), at the fill price, net of fees, with event-clustered SE:

1. **Enough data:** ≥ 800 independent events, about 5 weeks at today's volume. That is enough to resolve a true +5% ROI at 2σ.
   A +3% edge needs ~2,300 events (~100 days).
2. **Results:** dollar ROI's 95% lower bound is above 0, and settled excess wins are ≥ 0.
3. **Instrument:** same-book CLV and results agree in sign (item 3 above resolved first).
4. **Sizing earns its keep:** the top stake quartile's ROI is not below the flat-stake ROI.
5. **Then step, don't jump:** one cap increase at a time, re-measured. Step back the moment the rolling lower bound falls below zero.

## CLV RECONCILED (2026-11-16, same session; user "Yes, reconcile CLV")

The same 2026-11-16 fleet payload was used. Rows: last 30 days, decided (won/lost), with a resolved `closing_mark`:
545 same-book (Kalshi 430, Polymarket 115) and 404 different-book. CLV is
`prediction_ledger._clv_pct_from_prices(fill_price, close_price)` = (close implied − fill implied) × 100, in
probability points. The close is the venue's own last pregame quote-log price (`book_quotes_last_pregame`).

1. **The arithmetic is right.** The control is the 54 same-book bets whose close last changed BEFORE our entry, so the
   quote never moved. Their CLV is median +0.02 pp and mean +0.37 pp. Units (contract vs American), side and `held_side` map correctly.
   The fill equals the requested price (mean slippage +0.01 pp, 949 fills).
2. **CLV is GROSS of the taker fee, and the fee is bigger than the CLV.** The mean fee is 1.63 pp per bet
   (`fees_dollars` × fill / stake).
   - Same-book CLV net of fee: **−0.30 ± 0.19 pp**.
   - Different-book CLV net of fee: −0.26 ± 0.23 pp.

   The "+1.32% CLV" was never an edge. Net of fees, CLV and settled results agree in SIGN: both are negative. The
   contradiction in `#815` is mostly this.
3. **The venue close itself overprices the sides we buy, so venue CLV also overstates the SIZE.** On same-book bets,
   wins were 51.4% against a close implying 58.0%: −6.62 pp per bet, event-clustered z −2.94, 351 events.
   - Excluding NCAAB: −4.87 pp, z −1.97, 279 events.
   - Excluding NCAAB and totals: −4.73 pp, z −1.80.

   NCAAB is the largest single piece (92 bets, 33.7% won vs 48.9% close-implied), but the bias does not go away
   without it. Beating a close that is itself ~5 pp optimistic on our selections is not evidence of edge. The venue
   close is not a calibrated benchmark for the sides this book picks.
4. **CLV still ranks bets, weakly.** Win rate by same-book CLV bin: < −2 pp 46.7%, −2..0 49.6%, 0..2 52.5%, 2..5 52.3%,
   ≥ 5 pp 57.7%. Every bin still wins less than its fill price (z −0.26 to −1.72). The ≥ 5 pp bin wins 57.7%
   against a close implying 70.1% (z −2.08): large venue "CLV" moves mostly do not show up in outcomes.
5. **Timing:** median entry 9.7 h before start (p10 77 min). Median close-quote age at start 42 min (p90 10 h).

**Consequences**

- **Scale-up gate, condition 3 changes.** CLV is measured NET OF FEE, and only against a close benchmark that is
  itself calibrated on our selections: |wins − Σ close-implied| within 2 clustered SE. The venue close fails that today.
- **The `min_ev_tuner` (shadow) reads gross CLV.** `min_ev_tuner._clv` recomputes from fill and close with no fee term,
  and its RAISE rule needs ROI AND CLV both significantly NEGATIVE. A fee-gross CLV sits ~1.6 pp high, so a RAISE is
  structurally hard to reach. That fits its 10-20..10-26 readout (0 moves; the closest cell was a near-RAISE) and the
  module's own note that same-book CLV was "positive in every band" while ROI was negative. Fee-net CLV is the fix.
  The tuner is shadow, so nothing live changes today.
- Any surface or report that shows venue CLV should show it fee-net beside gross.

## Method artefact

The analysis script is session scratch for now (`pf_edge.py`). Its formulas are above. Promoting it to
`scripts/live_book_edge_readout.py` with a test that pins these numbers is this lane's next build step.
