# Portfolio monitor — Sun 11-22 (Central)

Lane `portfolio-monitor`. Counts and percentages only (the repo is public). Times are CST.

## DAILY SUMMARY — Sun 11-22 (Central), written Mon 11-23 2:10 AM CST by the daily learning review

Sources: `daily_rollup.json` and `performance.json` built from the 1:34 AM CST 11-23 watch reading (ledger saved
07:34:01Z), and the 48 watch readings dated 11-22 CST. Every 11-22 game is graded: 0 started and unsettled, 0 late.

**Performance.**
- **11-22: 44 graded bets / 24 games, ROI -21.86% [-54.8, +11.1].** Won 50.0% against a 62.1% breakeven (excess
  -5.3 wins, z -1.68). Before fees -18.84%; one small day, noise.
- **7 d: 377 bets / 199 games, -2.10% [-11.4, +7.2]** (11-21: +1.12% as now revised).
- **30 d: 1,711 bets / 770 games, -4.78% [-10.2, +0.67]** (11-21: -4.95%). Range includes 0 for the second day.
  All-time: 2,325 bets / 1,260 games, -10.51% [-17.4, -3.6].
- **Fee-net CLV:** 30 d -0.45 pp (643 bets / 440 games with a priced close, gross +1.26, beat close 61.7%); 7 d
  -0.99 pp (188 / 136, gross +0.88, se 0.34); 11-22 alone -1.73 pp on 20.
- **Fees: 3.02% of stake on 11-22, 4.01% over 30 d** (7 d 3.41%). 30 d before fees: -0.77%, so fees are ~84% of the
  30 d loss.
- **Gate: 108 of 800 events**, clock BC-053 since 11-19 17:00Z (11:00 AM CST): ROI -3.11% (lower -16.9), excess wins
  -14.0; condition 3 passes (fee-net CLV -1.61 pp vs ROI -3.11%, close calibration -6.31 pp, z -1.17), condition 4
  passes. 2 deploys.md loads still unclassified.
- **Revision:** the 11-21 row now reads 65 bets / 50 games, +3.29% (yesterday's summary: 62 / 47, +5.33%).

**30-day slices beyond noise (95% range excludes 0):** only one.
- price 0.30-0.45 -12.16% [-23.8, -0.49] (281 bets / 189 games), point estimate unchanged for a week.
- **Left beyond-noise today:** EV band 2-5 -6.83% [-14.5, +0.84] against a predicted +4.13% (1,053 / 579). The
  dashboard still flags it as "EV overstated", but its range now includes 0.
- Noise, worth tracking: totals -10.73% [-22.0, +0.57] (408 / 327); Polymarket -10.75% [-23.3, +1.8]; Kalshi -3.04%
  [-8.9, +2.8]; h2h +5.57% and spreads +0.69%, both noise.
- **Stake quartiles have reversed** since 11-20: Q1 (5.9% of $) -7.84%, Q2 (8.7%) -8.54%, Q3 (21.7%) -5.84%, Q4
  (63.7%) -3.61% [-11.4, +4.1]. On 11-20 Q4 was the worst (-8.64%, beyond noise).

**Operations (48 readings).** Anomaly kinds, by readings flagged: GATE 47 (2 unclassified loads); LEDGER
grade_conflicts 47 (the F26 false alarm, unchanged); CAP Polymarket dollars at 93-112% of the day cap 21 (12:34 PM -
11:34 PM); ENDPOINT 9 (2 slow, 7 failed in one reading); PLAN stale 1 (12:04 AM, 76.7 min, the overnight tail of
11-21). **The 6:04 PM reading failed on all 7 endpoints** with `ValueError: Invalid header value` whose bytes are
UTF-16 text beginning "A conne...": the token lookup returned an error message (it reads like a WSL connection
message) and it went into the auth header. One reading only; the next was clean. Not investigated further. Endpoint
reads over 2 s: 6, of which 3 over 3 s (3:34 AM: live_today 5.8 s, page 5.8 s, plan 3.8 s). Plan age: median
2.9 min, max 76.7 min (1 reading > 15 min). Orders 11-22: 64, 59 filled, 5 not filled, 0 failed.

**Studies.**
- **S6 forward test READ: NO-GO** (D = kept - all +4.26 pp [-3.81, +12.33] on the first 150 events submitted from
  11-20T00:00Z, 1,062 orders; GO needed the lower bound > 0). Fresh fleet dump + join this run (64,682 ledger rows,
  25,011 joined orders). Recorded in `findings_2026-11-19_s6_adverse_selection.md`. Note: yesterday's "73 events"
  count used `live_all.json` (live bets only); the registered population includes the ladder and the paper twin, and
  that is what the tool counts, so the read was probably already due on 11-22.
- S8 heartbeat 07:58:00Z (cycle 3,839, 0 errors), fresh; LOOK 1 due on the first run after 11-23 9:00 AM CST (not
  yet: this run is 2:10 AM).
- S5 forward: 120 events with selected_date >= 11-19 settled (need 150), counted from the newest `live_all.json`;
  not run.
- 11-24 window check and F27 readings not yet due (lane `kalshi-join-sport-scope` carries no `LOADED` line).

### What the data teaches (11-22)
- The 30 d book has sat at about -5% with a range touching 0 for two days (-4.95% → -4.78%, 770 games), after a
  month at -7 to -9%. The move is the window dropping early-November losses, not new skill: the last 7 days are
  -2.10% and fee-net CLV over them is -0.99 pp (136 games), worse than the 30 d -0.45 pp.
- Before fees the 30 d book is -0.77% on 1,711 bets; fees (4.01% of stake) are ~84% of the loss. The gross close-beat
  (+1.26 pp, 61.7% of 643 priced bets beat the close) is real but smaller than the fee.
- Price 0.30-0.45 is the one slice that has stayed beyond noise every day since 11-17 (-12.2% to -12.7%, 189-201
  games). The EV 2-5 overstatement persists in point estimate (realised -6.8% vs predicted +4.1%, 579 games) but its
  range now reaches +0.84.
- The stake-quartile picture reversed in two days (Q4 -8.64% on 11-20 → -3.61% today, while Q1/Q2 are -7.8/-8.5%).
  Recomputed from the ledger rows (my own selected_date window, so absolute fee levels differ from the dashboard's):
  fee share falls with stake, Q1 4.06% → Q4 2.84% of stake, and ROI before fees also improves with stake (Q1 -3.8%,
  Q2 -4.8%, Q3 -2.4%, Q4 -0.9%). Bigger stakes are both cheaper per dollar and better picked. The 11-20 stake-cap
  lead is now contradicted by its own data; drop it.
- S6's frozen filter (in effect a price cut) helped by +4.3 pp forward but not beyond noise at 150 events, the
  outcome its power statement predicted.

**One optimization lead (pre-registrable, offline, changes nothing live).**
- *Hypothesis:* the smallest bets lose more per dollar because the fee share of a small stake is higher and the
  sizer's small stakes mark its weakest picks, so raising the per-bet minimum stake to the 30 d Q2 upper edge (the
  same lines, dropping the bottom half of bets by size, ~15% of dollars) raises fee-net ROI.
- *Data:* the 30 d graded book in `live_all.json` (1,711 bets / 770 games) split at the Q2/Q3 stake boundary, fixed
  now from that set; then a forward copy on bets with selected_date >= 11-24 once that set reaches 150 games, using
  the SAME fixed boundary.
- *Decision rule:* GO (name a min-stake raise as a sizing challenger for the 12-08 window) iff ROI(kept) - ROI(all),
  event-clustered, has a 95% lower bound > 0 on BOTH the 30 d set and the forward set, AND the kept set's fee-net CLV
  is not below the dropped set's. Otherwise KILL. Report the bets and dollar share removed, so "betting less" is
  visible as such.
