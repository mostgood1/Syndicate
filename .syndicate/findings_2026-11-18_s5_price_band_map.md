# Findings — study S5 of the profit learning program: a calibration map by price band (2026-11-18)

Asked for by the user 2026-11-18 ~10:00 PM CST: "Start S5". Written by the portfolio session (lane
`portfolio-monitor`). Read-only: nothing live, no env, no fleet state changed. Not financial advice.

## What is already known (so S5 asks only what is open)

- **Close calibration** (`findings_2026-11-18_portfolio_monitor.md`, pre-registered 15:33:59Z):
  - on the 40% of live bets with a two-sided close, our picks are calibrated against the de-vigged close
    (+0.03 pp [-6.8, +6.8]);
  - **the favourite-longshot hypothesis was FALSIFIED** on that set;
  - the -6.4 pp gap lives in thin, one-sided books (props, unpaired quotes).
- **Fair-price source** (same file, 18:31:42Z): our picks win 7.8 pp less than the consensus and 5.9 pp less than the
  venue's own fair (388 bets / 272 games). The trigger is adversely selected.
- **The 10-24 price map:** no pregame structural price edge on Kalshi; longshots overpriced in play.
- **Already seen before this registration (stated as a contamination):** the monitor's 30-day slices by price band
  (10-19..11-17), e.g. .30-.45 at -12.6% [-23.8, -1.3] on 315 bets. They overlap the historical TEST window below.
  **So the historical split is an early read only, and the decision is a FORWARD test on bets not yet placed.**

## PRE-REGISTRATION (written before any number below is computed)

**Question.** Does a per-line price-band rule, fitted on earlier live bets, improve the live book's fee-net ROI on
later bets than the champion (no band rule)?

- A band rule acts on each line's own price. It is never a sport or market switch (learnings line 1056).

**Population.**
- Live graded bets from `scripts/live_book_edge_readout.bets_from_orders` (`/api/portfolio/live?on=all&show=all`):
  decided (won/lost/push), stake > 0, fill price in (0, 1).
- **Price band** of `p` = the fill price as a probability: <.30, .30-.45, .45-.55, .55-.70, .70-.85, >=.85.
- **Return** per bet = `pnl / stake` (net of fees, flat per bet, so stake-size changes over time do not weight the
  map).

**Coverage, counted before this was written (bets / events, no outcomes read):**

| side | <.30 | .30-.45 | .45-.55 | .55-.70 | .70-.85 | >=.85 | total |
|---|---|---|---|---|---|---|---|
| FIT, selected 08-06..10-31 | 36 / 36 | 323 / 258 | 421 / 359 | 129 / 94 | 51 / 36 | 15 / 10 | 975 |
| historical TEST, 11-01..11-17 | 0 | 142 / 98 | 393 / 258 | 406 / 225 | 160 / 121 | 0 | about 1,101 (incl. 11-18 so far; 11-18 excluded below) |

**The map (FIT only).**
- For each band with >= 30 FIT bets: flat ROI with a **95% event-clustered bootstrap CI** (2,000 draws, seed
  20261119).
- **Excluded bands** = those whose CI upper bound is < 0.
- If no band is excluded, the verdict is NO CHALLENGER and S5 ends there.

**Challenger.** The champion's bets minus those in the excluded bands. It is a filter on the same trigger.

**Decision metric.**
- **D = flat ROI(challenger's bets) - flat ROI(all bets)** on a test set.
- 95% CI from an event-clustered bootstrap: resample events, recompute both and the difference, 2,000 draws, seed
  20261119.

**1. Historical early read:** test = selected 2026-11-01..2026-11-17 (contaminated, see above).
- If D's 95% CI upper bound is < 0 (dropping the bands hurt beyond noise): **KILL early**, and the forward test is
  cancelled.
- Otherwise it decides nothing.

**2. Forward test (the decision):** test = bets with selected_date >= 2026-11-19, none of them placed yet.
- It is read at the first portfolio reading where the forward set has >= 150 events (about a week at 24 graded games
  a day).
- **GO iff D's 95% CI lower bound > 0.** Otherwise NO-GO.
- A GO names a challenger for a betting-change window (12-08 at the earliest). It changes nothing live by itself.

**Reported beside, deciding nothing:** the calibration table per band on FIT and on each test set. It shows win
rate, mean breakeven (fill price plus fee) and their difference.
