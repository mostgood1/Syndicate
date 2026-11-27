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

## RESULT — the map does not carry over; no early kill, so the forward test decides (run 2026-11-19 ~04:07Z = 10:07 PM CST, read-only; pre-registration on main `ccd49b2b6` at 04:05:09Z)

Script: `C:\tmp\pfmon\s5_band_map.py`, exactly as registered. Input: the monitor's `live_all.json` saved 03:42Z.
Result: `C:\tmp\pfmon\s5_result.json`.

**FIT map (selected 08-06..10-31), flat fee-net ROI with a 95% event-clustered CI:**

| band | bets / events | ROI | 95% CI | win - breakeven |
|---|---|---|---|---|
| <.30 | 36 / 36 | -31.1% | [-81.3, +32.6] | -4.1 pp |
| .30-.45 | 323 / 258 | -10.3% | [-22.5, +1.4] | -3.9 pp |
| .45-.55 | 421 / 359 | -3.1% | [-12.0, +6.1] | -0.8 pp |
| **.55-.70** | 129 / 94 | **-15.9%** | **[-30.1, -1.0]** | **-10.2 pp** |
| .70-.85 | 51 / 36 | -6.3% | [-20.7, +7.8] | -1.5 pp |
| >=.85 | 15 / 10 | (< 30 bets, not judged) | | |

- **Excluded band (CI upper < 0): .55-.70 only.** The challenger is the champion without .55-.70 bets.

**Historical early read (selected 11-01..11-17; contaminated, see above):**

| band | bets / events | ROI | win - breakeven |
|---|---|---|---|
| .30-.45 | 141 / 97 | -13.6% | -1.1 pp |
| .45-.55 | 375 / 244 | -8.1% | -4.3 pp |
| **.55-.70** | 384 / 215 | **+0.5%** | **+1.7 pp** |
| .70-.85 | 151 / 114 | -4.5% | -2.7 pp |

- All bets: -5.21%. Challenger, with 384 bets dropped: -8.48%. **D = -3.27 pp [-6.91, +0.46].**
- **The band the FIT map excluded was the best band in the historical test.** Dropping it hurt, though not beyond
  noise. D's CI upper bound is +0.46 > 0, so the registered early KILL does not fire.
- **Verdict as registered: no early kill; the forward test (bets selected >= 11-19, read at >= 150 events) decides.**

**Reading.**
- The FIT map's worst band became the test window's best. The price band at which the book loses moves with the
  period, which matches the close-calibration result (favourite-longshot FALSIFIED).
- **A price-band filter is unlikely to be the lever.** The forward test is kept because it was registered, and it is
  cheap: it only re-reads the ledger.
- The book's losses in the test window sit in **.45-.55 (coin-flip prices, -4.3 pp under breakeven on 375 bets)**.
  That is where the adversely-selected trigger fires most, not a structural price effect. The lead goes to S6
  (adverse-selection features), not to a band rule.
- **Forward read:** the monitor re-runs `C:\tmp\pfmon\s5_band_map.py` once bets selected >= 11-19 cover >= 150 events
  (about 11-25/26 at 24 graded games a day). The verdict is reported then. Nothing goes to the 11-24 window from S5.

## FORWARD RESULT — NO-GO (run 2026-11-27 ~2:00 AM CST = 08:00Z by the daily learning review, read-only)

- Input: the 1:34 AM CST 11-27 watch reading's `live_all.json` (ledger saved 07:34:02Z), `s5_band_map.py ... forward`.
- Forward set (bets selected >= 11-19, graded): 271 bets / 150 games. The challenger drops the fitted band (.55-.70):
  129 bets dropped. ROI all -14.05%, challenger -18.75%, **D = -4.70 pp [-13.6, +4.28]**.
- **Verdict as registered: NO-GO** (GO needed D's 95% lower bound > 0). The fitted map on the refit window also
  moved: .55-.70 is now the excluded band (it was profitable on 11-01..11-17, +0.7%), so the band effect does not
  hold its place between windows.
- **S5 ends. Nothing changes live and nothing is queued for a window.**
