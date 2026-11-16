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

   ~~Scaling makes more bets look like Q4.~~ **CORRECTED same day (§ "BIG STAKES EXPLAINED"):** Q4 is mostly
   the live $5-$10 stake band (on 10-20..11-02). It multiplied every bet's stake about 10x. It did not pick worse
   bets: matched on price, EV, date and path, a bigger stake shows no significant difference in results.
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

## Scale-up gate — ADOPTED 2026-11-16 (user: "Adopt as drafted")

Every condition is measured FORWARD from a frozen policy (no mid-window changes), at the fill price, net of fees, with event-clustered SE:

1. **Enough data:** ≥ 800 independent events, about 5 weeks at today's volume. That is enough to resolve a true +5% ROI at 2σ.
   A +3% edge needs ~2,300 events (~100 days).
2. **Results:** dollar ROI's 95% lower bound is above 0, and settled excess wins are ≥ 0.
3. **Instrument:** same-book CLV and results agree in sign (item 3 above resolved first).
4. **Sizing earns its keep:** the top stake quartile's ROI is not below the flat-stake ROI.
5. **Then step, don't jump:** one cap increase at a time, re-measured. Step back the moment the rolling lower bound falls below zero.

**ADOPTED AS DRAFTED, 2026-11-16** (user, verbatim: "Adopt as drafted"; it answered the question "Adopt the scale-up gate as
drafted?").
- Condition 3 is the amended one from § "CLV RECONCILED": fee-net same-book CLV agrees in sign with results, against a close
  that is calibrated on our sides (|z| < 2).
- `scripts/live_book_edge_readout.py` `gate()` reads conditions 1-4 (`GATE_MIN_EVENTS` 800, `GATE_CLOSE_CALIBRATION_Z` 2.0)
  and now labels them ADOPTED. Condition 5 is a procedure. No code acts on the gate.
- What it binds: no live stake, cap or bankroll increase until 1-4 pass together on one window. Then condition 5.
- Reading at adoption: all four measurable conditions FAIL (§ "Method artefact", since 11-03).

**OPEN at adoption: what resets the clock.** The draft says "measured FORWARD from a frozen policy (no mid-window changes)".
Read strictly, as any fleet change to how live bets are chosen or held, the clock has not started. `.syndicate/deploys.md` records at
least 8 such changes inside 11-03..11-16 alone:
- NCAAB on Kalshi, live 11-03/04.
- In-game exits off, 11-07.
- The live lane-age gate default ON, 11-08.
- In-play entries refuse an ask below 0.55, 11-09.
- NCAAB live mechanism env, three changes 11-09..11-10.
- The live player-exit gate, from 11-16.

So `--since 2026-11-03` is the last SIZING change (stake band off), not a frozen policy. The user decides which changes restart
the 800-event count. Until then, the "about 2026-12-02 at the earliest" date holds only under the sizing-only reading.

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

## FEE-NET CLV BUILT (2026-11-16, same session; user "Yes, add fee-net CLV" — order marks + tuner, shadow only)

**Code, on main, not loaded on the fleet:**

- `order_clv.fee_pp_for_order(order)` gives the fee in CLV's probability points: `100 × p_entry × fees_dollars / stake`.
  - Buying at `p` with stake `S` gets `S/p` contracts, so a fee `F` adds `p·F/S` to each contract's price.
  - `fees_dollars = None` (unknown) gives **None**, never 0.
  - A recorded 0.0 is 0 at any price.
  - ProphetX's settlement-basis orders use `venue_fees`' expected win commission `0.02·p·(1−p)`. The realised fee is never used, because it depends on the result.
- `order_clv.fee_net_clv_pct(order, clv_pct)` returns the gross minus the fee.
- `clv_for_orders` resolved rows carry `fee_pp` and `clv_net_pct` beside `clv_pct`.
  - Every aggregate adds `clv_net_n`, `avg_clv_net_pct` and `beat_close_net`.
  - The ORDER_CLV log line adds `same_book_avg_clv_net_pct` and `same_book_net_n`.
- `paper_settlement.stamp_closing_marks`: a mark stamped from now on carries `fee_pp`, and always carries `clv_net_pct` (None when the fee is unknown). Old marks are not rewritten. A reader nets them with `fee_net_clv_pct(order, clv)`.
- `min_ev_tuner`: `SYNDICATE_MIN_EV_TUNER_CLV_BASIS`.
  - Absent or unrecognised means `net`; `gross` is the old basis.
  - `_clv` nets the RECOMPUTED gross (#719 repair kept).
  - Evidence reports `clv_basis`, plus `avg_clv_gross_pct`, `clv_gross_events` and `clv_gross_t` beside the decision's numbers.
  - The basis is in the state, every move, and the MIN_EV_TUNER log line.
  - Mode is unchanged: shadow.
- Tests: `tests/test_fee_net_clv.py`, 16 tests.
  - Unit, unknown fee, ProphetX, rows, aggregates and marks.
  - **Reachability:** the same 60 rows with gross +1.0..+2.0 pp and a 2.0 pp fee give net **RAISE** and gross **HOLD** (`roi_and_clv_opposite_signs`).
  - `tests/test_min_ev_tuner.py`'s fixture now records `fees_dollars` 0.0. Without a recorded fee its rows give no net reading, which is the rule.
  - 695 passed across every clv / settlement / tuner / portfolio_commit / fee suite.

**Fleet A/B, read-only** (2026-11-16 20:21Z). My worktree's code was imported under refresh-worker pid 2809282's env (values not printed) at nice 19, on `full_history_orders()` = 52,454 orders, persisting nothing:

- **Faithfulness:** the gross arm reproduces tonight's persisted state (95 cells, `{'hold': 95}`). No `SYNDICATE_MIN_EV_TUNER*` key is set on the worker, so the mode is shadow.
- **Fee coverage**, same-book-marked tuned rows: Kalshi live 431/431 have a net reading, Kalshi paper 8,886/9,067, Polymarket live 116/116, Polymarket paper 3,429/3,504. The ~2% without one are paper rows with `fees_dollars = None`. That they are pre-10-06 fills (`execution_ledger` began recording paper fees then) is likely but NOT measured here.
- **Mean fee:** Kalshi live 1.52 pp, Kalshi paper 1.52 pp, Polymarket live 2.00 pp, Polymarket paper 1.49 pp.
- **Per-cell actions:** unchanged, 95 hold on both bases.
- **Reasons:** they change in 3 cells. Kalshi NCAAF spreads, Kalshi NCAAF totals and Polymarket NCAAF totals held as `only_clv_significant` on gross: marginal-band gross CLV +1.5 to +2.2 pp at t 5.0–6.9, while band ROI was −11.0%, −10.7% and +10.3%. Net, that CLV is −0.13 to +0.23 pp at |t| < 0.7. That gross "significance" was the fee.
- **Pooled (shadow)**, 1 flip: Kalshi NCAAB totals hold → raise. Band 24 events, ROI −33.4% (t −2.00), net CLV −3.52 pp (t −3.39). Its gross CLV was −1.98 (t −1.80).
- **No money moves:** the tuner and pooling are shadow, and nothing reads them at commit.

## BIG STAKES EXPLAINED (2026-11-16, same session; user "Dig into big stakes")

The hypotheses H1-H4 and the falsification test were written into the lane BEFORE testing. The data is the same
11-16 fleet payload: last 30 days, 1,526 decided live bets. Quartile cuts are $0.51 / $0.70 / $2.70.

**Answer:** the top stake quartile is, to 85% of its dollars, bets placed while the **live $5-$10 stake band** was on.

- **The band:** user decision 10-20, "Bets should be $5-$10 not under $1", lane `live-stake-band`. It was ON from
  2026-10-20 14:37Z to 11-02 18:23Z, when the user turned it off (lane `stake-band-off`).
- **What it did:** it replaced each pregame bet's Kelly-on-capital stake with $5 + $5 × full Kelly / 5%. Its first
  build turned a $0.54 stake into $5.46. It does NOT choose which bets are placed (`live_stake_band.py` docstring).
- **How it shows in the data:** stake ÷ `stake_fraction_ev_only` implies a capital of $1,500-5,000 per venue through
  11-02 and $200-400 from 11-03. The real capital is ~$285 Kalshi and ~$150 Polymarket.

| period, pregame `model_edge` bets | median stake | bets | staked | ROI (event-clustered) | excess wins z |
|---|---|---|---|---|---|
| band ON 10-20..11-02 | $5.41 | 266 | $1,359.85 | −10.5 ± 5.2% | −2.13 |
| band OFF 11-02.. | $0.58 | 703 | $555.55 | −2.1 ± 3.6% | −0.41 |

- **Top-quartile dollars by origin:**
  - band-on pregame `model_edge`: 68.3%
  - band-on rows with no sizing record: 14.0%
  - band-off in-play: 9.0%
  - band-off pregame: 5.6%
  - band-on in-play: 2.1%
  - other: 1.0%
- **H1 (price) FALSE and H2 (claimed EV) FALSE:** Q4's mean price 0.559 and EV 4.14% match Q2 (0.567 / 4.39%) and
  Q3 (0.576 / 3.50%).
- **H3 (time) TRUE, as one specific period:** the band. **H4 (path) TRUE:** band-on pregame.
- **Falsification of "the sizing itself loses" (registered):** does a bigger stake lose more once the bet is matched?
  - Matched on path, venue, half-month, price band and EV band, top-half vs bottom-half stake: **−2.4 ± 4.2 pp** excess-win rate (z −0.57, 317 events).
  - Inside the band, matched on price band: −7.0 ± 6.8 pp (z −1.03, 162 events).
  - Full-Kelly quintiles (stake rank inside the band) are not monotone: excess-win z −2.16, +0.27, −2.25, +0.30, +0.68.
  - So there is no significant evidence that size picks losers. The direction inside the band is negative, so it stays a watch item, not a finding.
- **What the band cost:** the band period's 601 pregame bets staked $1,875.61 and lost $154.76. At the post-band
  median stake ($0.58) the same bets would have lost about $27.67. **About $127 of the last 30 days' $218.64 loss is
  the band's ~10x multiplier, applied to a book with no measured edge.**
  - Per bet, the band period also did worse (flat −10.3% vs −3.5%). The band does not choose bets, though, and the
    gap is not significant (~z 1.1), so that part is calendar or other changes, not attributed.
- **This was, in effect, the scale-up the user asked about**, run for 13 days. Raising stakes ~10x on a book with no
  measured edge multiplied the loss ~10x. That is direct evidence for the gate above: a scale-up multiplies the per-bet
  result, whatever its sign.
- **In-play (`inplay_order_dollars`)** is now the largest routine stake: a fixed $2.40-2.95 per order, about 4.5x the
  pregame median. Band-off: 180 bets, −7.9 ± 6.4%, wins at breakeven (z +0.20). Not significant either way.
- **Early exits (`exit_applied`, 537 of 1,526 bets, all paths)** are a wash: realised minus hold-to-settle = −$20.06
  ± $58.47 (z −0.34). They gave up $423.07 on bets that went on to win and saved $403.01 on bets that went on to lose.
  So excess wins at the fill price (which ignores exits) and ROI tell the same story.

**No fix owed from this.** The band is already off. Since then, pregame stakes follow Kelly on the real capital, and
size does not significantly pick losers. Nothing here is a market or sport switch (learnings line 1056). Scripts:
session scratch `bigstakes.py`, `bigstakes2.py`, `bigstakes3.py` (formulas above).

## Method artefact — PROMOTED 2026-11-16 (user "Yes, build it"): `scripts/live_book_edge_readout.py`, on main `38646cce2`

```
python scripts/live_book_edge_readout.py                    # the fleet now; windows end at the latest decided slate
python scripts/live_book_edge_readout.py --since 2026-11-03 # one window from the last live-policy change
```

- **What it reports:** the formulas above, plus fee-net CLV per scope (`order_clv.fee_net_clv_pct`) and the close's
  calibration on our sides. Also stake quartiles, sizing paths, per-line breakdowns, and the four measurable gate
  conditions, labelled PROPOSED (ADOPTED since 2026-11-16; § "Scale-up gate"). Nothing reads them.
- **Reproduction:** from the saved 11-16 payload, as of 11-15, it matches the pinned numbers exactly:
  - last 30: 1,526 / 641 / $3,006.48 / −$218.64 / −7.27 ± 2.84% / excess −32.5 (z −1.72)
  - last 7: +0.72 ± 4.95%
  - all: −11.02%, z −2.35
  - Q4: −9.19%, z −2.17
  - same-book CLV: gross +1.32, fee 1.63, net −0.30
- **Tests:** `tests/test_live_book_edge_readout.py`, 19 synthetic + 1 pinned. The pinned test runs when
  `SYNDICATE_EDGE_READOUT_PAYLOAD` names the saved payload; the repo is PUBLIC, so the payload is not committed. 20
  passed with the payload; 19 passed + 1 skipped without it.
- **SE estimator (canonical from here):** event-clustered CR0, the same estimator for ROI, CLV and close calibration.
  The "CLV RECONCILED" section's ad hoc estimator gave net ± 0.19 and calibration z −2.94; the script gives ± 0.23 and
  z −3.05 on the same rows (546 vs 545: a push is kept in CLV, dropped from calibration). Every conclusion holds.

**Fresh fleet read, 2026-11-16 21:15Z** (2,225 orders; no 11-16 bet decided yet, so as of 11-15): identical windows.

**Since the stake band went off** (`--since 2026-11-03`, 11-03..11-15):

- Results: 833 bets / 357 events, $928.92, −$42.64, **ROI −4.59 ± 3.83%**, win 57.3 vs breakeven 58.0, excess −5.8 (z −0.42).
- Same-book CLV: gross +1.37, fee 1.72, **net −0.35 ± 0.32 pp**. Close calibration −5.6 pp (z −2.03).
- Q4 is $1.38-5.68 and 61% of dollars (mostly in-play's fixed $2.40-2.95): −6.04% vs flat −4.59%.
- **Gate (PROPOSED): all four measurable conditions FAIL.** The one with a date attached is condition 1: 357 of 800
  events at ~27 events a day is about 16 more days, so the earliest it can pass is about 2026-12-02. That holds only if
  the live policy stays frozen. The results conditions decide whether it passes at all.
