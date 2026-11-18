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

## Reading 28 — Wed 11-18 1:45 AM CST (07:45Z), window 32 min

- **Clean apart from the gate's clock.**
- **Plan 2.2 min old.** 45 suggested -> 25 sized -> 20 positions, ceiling used 44.0%.
- **Execution, 32 min:** 10 live ticks, 3 placed (kalshi 2, polymarket 1), 0 failed.
  - Orders today 13: 11 filled, 2 resting at 63.1 and 57.8 min. Neither is overdue: maker-pilot posts are exempt
    until kickoff, and 5 `maker_pilot_held` refusals confirm posts are working.
  - Unreconciled 0. Cap use: kalshi 10.2%, polymarket 3.3%.
- **Refresh-worker still not restarted** (pid 28948 up 35,341 s at 07:45:09Z, fleet head `3920a2d4d`).
  - A drain was requested at 07:14Z: 2 `DEFERRED_BOARD_BUILD reason=deploy_drain_requested` and `DRAIN_HOLD
    stage=mlb_sim_tick`, then released. Plan writes resumed, newest 07:43:01Z.
  - deploys.md on main has no load entry since 01:46Z.
  - Read as: lane `ncaaf-grid-build-speed`'s 1:10 AM attempt has not loaded yet (its own deadline for an entry is
    08:30Z). Not this lane's to act on. The board-split load is sequenced after it.
- **Endpoints:** all 7 read 200, all under 0.4 s. 0 kills.

## Reading 29 — Wed 11-18 2:16 AM CST (08:16Z), window 31 min

- **The refresh-worker restarted at 08:02:56Z (2:02 AM CST)**, at fleet head `3920a2d4d`. Web, live-odds-worker and
  the supervisor were not restarted.
  - The supervisor says: `[refresh-worker] exited code=0 after 36594s -- restarting in 5s`, then
    `CLAIMED_RESTART code=0 holder=ncaab-total-overprojection`. So this is the I-17 lane's claimed TERM, not the
    `ncaaf-grid-build-speed` attempt; deploys.md 07:55Z says that one "GAVE UP, NOTHING LOADED".
  - It loads what is at the head: I-17 `923869cf3`, the per-build memo, and **BC-041's NFL seeds `ee47c930a`, a
    betting change**.
  - BC-041 still reads `pending:refresh-worker` on main. The gate clock starts only when the loading lane runs
    `betting_change.py resolve`. Owed by that lane, not this one; re-checked next reading.
  - **The board-process split is NOT loaded** (head is still `3920a2d4d`, not >= `09eddabf2`). Its drained
    `down`/`up` is still to come.
- **Plan across the restart:** last commit before it 07:58:13Z, first after it 08:10:05Z, a **12-min gap**. Plan 0.7
  min old at the reading.
  - 44 suggested -> 25 sized -> 21 positions, ceiling used 47.0%.
- **Execution, 31 min:** 12 live ticks, 3 placed, 0 failed.
  - Orders today 16: 14 filled, 2 maker posts resting (94.2 and 88.9 min, exempt until kickoff).
  - Unreconciled 0. Cap use: kalshi 10.7%, polymarket 4.7%.
- **Endpoints:** all 7 read 200, all under 0.3 s. 0 kills.

## Reading 30 — Wed 11-18 2:48 AM CST (08:48Z), window 32 min — THE BOARD-PROCESS SPLIT IS LOADED

- **F7's fix is running.** At 08:48:21Z:
  - the fleet head is `09eddabf2`;
  - every role restarted together around 08:31:05Z (refresh-worker 429499, live-odds-worker 429500, web 429429,
    supervisor 429414, all up about 1,035 s), which is the drained `down`/`up`;
  - `BOARD_PROCESS_MODE mode=process parent=429499` and `BOARD_PROCESS_STARTED pid=429539` at 08:31:33Z, then
    `BOARD_PROCESS_CHILD_READY` at 08:31:34Z;
  - exactly 1 `board_build_process --serve` process alive.
  - The load is lane `layer2-board-process-split`'s. Its deploys.md entry and betting-change row were not on main at
    this reading; they are owed by that lane.
- **First builds in the child (calm hours):** `BOARD_BUILD_TIMING` wall 166.2 / 133.8 / 108.7 / 111.3 s (08:37-08:47Z).
  - This is not the reading. The lane's pre-registered reading is the first live evening, 6-10 PM CST 11-18. This
    lane's `plan_commits` is its metric-4 cross-check, and the 11-17 evening is the "before".
- **Plan through the night's two restarts.** Plan writes resumed after each. The largest gap in the 6-h series is
  29.5 min, which covers both restarts and the drain. Plan 0.8 min old at the reading. 30 suggested -> 25 sized ->
  20 positions, ceiling used 56.4%.
- **BC-041 is resolved on main:** loaded at 08:03:01Z by lane `ncaab-total-overprojection`, with its deploys.md entry
  at 08:02:54Z. This reading's gate line still said PENDING because the worktree's register predated the resolve
  (fast-forwarded right after). The gate clock now runs from 08:03:01Z unless the split adds a newer row.
- **Execution, 32 min:** 10 live ticks, 1 placed, 0 failed.
  - Orders today 17: 15 filled, 2 maker posts resting (126 and 121 min, exempt until kickoff).
  - Cap use: kalshi 11.1%, polymarket 4.7%.
- **Endpoints** after the web restart: all 7 read 200, all under 0.25 s. 0 kills.
