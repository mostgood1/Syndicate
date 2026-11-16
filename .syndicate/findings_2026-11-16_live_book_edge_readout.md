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

## Method artefact

The analysis script is session scratch for now (`pf_edge.py`). Its formulas are above. Promoting it to
`scripts/live_book_edge_readout.py` with a test that pins these numbers is this lane's next build step.
