# Findings — lane `portfolio-monitor`, Wed 2026-11-18 (Central)

This continues `findings_2026-11-17_portfolio_monitor.md`, which holds the method, readings 1-24, findings F1-F7
and their fixes. Same probe (`scripts/portfolio_monitor_probe.py`), same page (Portfolio Watch).

## Reading 25 — Wed 11-18 12:11 AM CST (06:11Z), window 32 min

- **The Central date rolled over.** "Today" in the probe is now 11-18: orders today 0, cap use 0%.
  - `plan_commits` now tracks 11-18's plan. Its 6-h series still holds the earlier evening, when 11-18 was the next
    day, so its "max gap 102.6 min" (02:02 -> 03:44Z) is the next-day cadence, not a stall.
  - Read the evening metric from the 11-17 readings.
  - 11-17's last plan write was 05:58:39Z.
- **Plan 0.3 min old (11-18).** 30 suggested -> 24 sized -> 15 positions. Ceiling used 37.1%.
- **Execution, 32 min:** 10 live ticks, 0 placed, 0 failed. Refused: 4 `already_held_other_slate` (11-18 positions
  already held from the 11-17 slate), 1 `outside_price_band`, 1 `game_started`.
- **Settlement:** 7 started and unsettled (from 10), 0 late. These are 11-17's late NBA/NHL games. **11-17's daily
  summary waits for them.**
- **Endpoints:** all 7 read 200, all under 0.25 s. 0 kills. **Gate:** pending BC-041 (count 0).

## Reading 26 — Wed 11-18 12:42 AM CST (06:42Z), window 31 min

- **Clean apart from the gate's clock.**
- **Plan 2.1 min old (11-18).** 38 suggested -> 25 sized -> 19 positions. Ceiling used 44.3%.
- **Execution, 31 min:** 11 live ticks, **1 placed** (kalshi, 11-18's first order: an early-line pregame bet, resting
  0.1 min at the reading). 0 failed. 5 polymarket refusals were `already_held_other_slate`.
  - Cap use: kalshi 3.8% of 11-18's day cap.
- **Settlement:** 7 started and unsettled, all **11-17 NBA games that tipped at 10:10 PM CST**. 0 late. They are due
  around now, and 11-17's daily summary follows them.
- **Expected next, so not to be misread as faults:**
  - The refresh-worker TERM load (lane `ncaaf-grid-build-speed`, 1:10-1:40 AM CST) and the board-process-split
    drained `down`/`up` (lane `layer2-board-process-split`, ~2:00-2:15 AM CST) will each stop plan writes for about
    20 min.
  - The banner may go stale across the `down`/`up`.

## Reading 27 — Wed 11-18 1:13 AM CST (07:13Z), window 31 min

- **11-17 is fully graded** (started and unsettled 0). **Its DAILY SUMMARY is in `findings_2026-11-17_portfolio_monitor.md`.**
- **Overnight pregame betting on 11-18 has begun: 9 placed in 31 min** (kalshi 5, polymarket 4), 0 failed.
  - Orders today 10: 7 filled, 3 submitted and resting (31.1, 25.8, 3.1 min). None is overdue by the probe's
    resting rules: `maker_pilot_held` refusals show maker posts are in play, and those are exempt until kickoff.
  - Unreconciled 1, inside the 10-min grace.
  - Refusals: 39 `outside_price_band`, 10 `already_held_other_slate`, 6 `axis_held_live`, 5 `maker_pilot_held`.
- **Plan 2.8 min old.** 42 suggested -> 25 sized -> 19 positions, ceiling used 49.6%. Cap use: kalshi 9.2%,
  polymarket 2.3%.
- **Refresh-worker not restarted yet.** pid 28948 has been up since 21:53Z 11-17, and the fleet head is `3920a2d4d`
  at 07:14:22Z. The `ncaaf-grid-build-speed` load window opened 07:10Z.
- **Endpoints:** all 7 read 200, all under 0.25 s. 0 kills.
