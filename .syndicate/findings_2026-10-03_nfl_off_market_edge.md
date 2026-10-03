# NFL off-market (consensus-fair) edges are NOT earned at the close; claims of 10% or more are a trap (2026-10-03)

Lane `nfl-off-market-edge` (session 05b01a84). Measurement only: no production file edited, no deploy.
Script `scripts/measure_nfl_off_market_edge.py`, tests `tests/test_measure_nfl_off_market_edge.py` (6/6).
Outputs: `C:\tmp\nflbt\offmarket\nfl_off_market_edge.{json,md}`.

## What exists, and what was measured

Every Layer 2 row already carries a market-only `ev_pct`: the best bettable price vs the multi-book
de-vigged MEDIAN (`opportunity_signals.consensus_fair_probability`). NFL included, no model involved. This
measured whether that edge is EARNED.

**Method.**
- Data: as-of closing snapshots. Props are OddsAPI historical at kickoff − 10 min (2023-25, 87,504
  scored lines). Game lines are per-book closes at kickoff − 5 min, with per-book `last_update`
  (2022-24).
- For each line and side: take the best price across books, compute claimed EV under three fair
  definitions, bet flat 1u when claimed EV > 0, and settle against the actual result. Pushes are void.
- The three definitions:
  - `board`: the board's own median, INCLUDING the quoting book;
  - `loo`: leave-one-out;
  - `fresh`: game lines only; stale books (> 900 s, the board's own threshold) dropped.
- **Sportsbooks stand in for exchanges.** The history has no Kalshi/Polymarket quotes.
- Anytime TD is one-sided: 115,534 quotes skipped (not de-viggable).

## Results

| book | definition | bets (games) | mean claimed EV | realized ROI [95% CI, game-clustered] | realized-on-claimed slope [CI] |
|---|---|---|---|---|---|
| props 2023-25 | board | 3,226 (583) | +1.88% | **+0.30% [−3.05, +3.95]** | −0.85 [−2.57, +1.29] |
| props 2023-25 | loo | 4,747 (588) | +1.98% | **−0.49% [−3.16, +2.08]** | −0.87 [−2.32, +0.64] |
| game lines 2022-24 | board = fresh | 552 (469) | +2.22% | −6.43% [−17.3, +5.7] | −0.95 [−5.9, +4.8] |
| game lines 2022-24 | loo | 612 (507) | +2.23% | −6.45% [−17.4, +4.3] | −1.05 [−6.1, +3.0] |

By claimed-EV band, props (board / loo):

| claimed EV band | board: bets, ROI [CI] | loo: bets, ROI [CI] |
|---|---|---|
| 0-1% | 1,301, +2.4% [−3.8, +8.4] | 1,802, −0.4% [−4.8, +3.9] |
| 1-2% | 780, −4.6% [−11.7, +2.4] | 1,142, +1.0% [−5.0, +7.0] |
| 2-3% | 544, +6.8% [−2.3, +15.5] | 799, −2.2% [−9.3, +5.1] |
| 3-5% | 423, −4.5% [−16.2, +6.6] | 720, +0.1% [−8.2, +9.0] |
| 5-10% | 153, +2.6% [−16.9, +21.9] | 249, +2.0% [−11.9, +16.9] |
| **≥ 10%** | 25, **−31.2% [−73.8, +20.2]** | 35, **−44.7% [−80.1, −2.6]** |

## Verdict against the pre-registered hypothesis

- **"Consensus-fair edges mostly do not realize": HOLDS.**
  - Realized ROI ≈ 0 against +1.9-2.2% claimed. No band tracks its claim; every slope point estimate
    is negative.
  - **Caveat at this n:** the slope CIs also cover 1. The data cannot RULE OUT a small real edge. They
    show no evidence for one.
  - Falsification (a band with n ≥ 300 whose slope CI covers 1) is formally triggered only in the sense
    that every CI is wide. No band shows ROI rising with claimed EV.
- **"Large-EV bands are stale quotes": NOT TESTABLE for props, and NOT THE CAUSE for game lines.** At
  the close only 12 book-markets were stale, so `fresh` = `board`. The game-line losses sit in longshot
  moneylines (mean fair 0.13-0.30 in the top bands) at Betfair and LowVig.
- **"Leave-one-out raises claimed EV but not realized ROI": HOLDS.** It adds ~1,500 prop bets at ~0 ROI.
  - Mechanism, unit-tested: with ≥ 3 agreeing books the MEDIAN already ignores a single outlier, so
    leave-one-out only differs when the other books disagree.

## For per-line scoring (no market gated)

1. **Treat a market-only claim of 10% or more as an ERROR SIGNAL, not an opportunity:** −31% / −45% realized
   on props. Down-weight or require corroboration per line. (MLB found the same shape: the largest
   claimed edges were stale quotes, `findings_2026-09-08_spreads_edge_is_stale_quotes.md`.)
2. **Discount market-only EV at the close toward 0 for NFL.** It is not earned there.
3. **The value of price shopping is TIMING, not beating the close.** The fleet-measured NFL fee-net CLV
   (+0.98 [+0.62, +1.44], `findings_2026-09-29_layer2_fee_net_out_of_sample.md`) is about taking a price
   before the market moves to it. A closing snapshot cannot show that, by construction.

## The four known gaps, ranked by measured value

| gap | measured value | rank |
|---|---|---|
| fee-net EV off by default (`SYNDICATE_SCORE_FEE_NET`) | the only one with positive out-of-sample evidence (09-29 fee-net CLV, NFL +0.98) | **1** |
| Kalshi/Polymarket NFL game lines fan in AFTER scoring (`venue_quote_fanin`), so the executable price never feeds `ev_pct` | unmeasured (needs forward exchange fills); it is where an executable off-market price would come from | 2 |
| stale books inside the median | no effect at the close (12 stale book-markets in three seasons); matters pre-close, unmeasured | 3 |
| median not leave-one-out | no value: more bets, same ~0 ROI | 4 (do not build) |

## Next measurement (forward, needs no new capture)

Fleet `book_quotes` has carried Kalshi NFL props since 2026-09-30. Measure each executable Kalshi price
against the consensus at entry time and again at the CLOSE (fee-net CLV, per line). Gradable from week 4
(games 2026-10-04/05) onward.
