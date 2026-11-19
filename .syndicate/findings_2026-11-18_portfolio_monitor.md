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

## Reading 31 — Wed 11-18 3:48 AM CST (09:48Z), window 60 min

- **Clean.** The only anomaly is the register's unclassified-load count.
- **Gate clock now runs from BC-042 at 08:31:33Z** (the board-process split's `yes`, registered by its lane): 0 of 800
  events so far. BC-041 (08:03:01Z) is superseded as the clock's start.
- **Unclassified loads 1 -> 2.** `betting_change.py candidates` lists:
  - the 11-17 16:17Z NFL rebuild, as before, with its lane;
  - **the 08:02:54Z refresh-worker TERM, whose deploys.md entry has no `- betting change:` line.** That load carried
    I-17 `923869cf3` (the calibrated college total) as well as BC-041's NFL seeds.
  - It does not move the clock: BC-042 at 08:31:33Z is later. Whether I-17 is its own `yes` is for lane
    `ncaab-total-overprojection` to say. Left with that lane; the session-start digest shows the count to every
    session.
- **Plan 0.6 min old.** In 6 h: 45 commits, **max gap 21.4 min** (the overnight restarts included). The board also
  wrote 11-19 at 09:39:48Z.
- **Execution, 60 min:** 21 live ticks, 2 placed, 0 failed.
  - Orders today 19: 17 filled, 2 maker posts resting (186 and 181 min, exempt until kickoff).
  - Cap use: kalshi 11.5%, polymarket 5.5%.
- **Endpoints:** all 7 read 200 (`/portfolio` 1.02 s, the slowest). 0 kills.

## Reading 32 — Wed 11-18 4:48 AM CST (10:48Z), window 60 min

- **Quiet and clean.** The only flag is the same 2 unclassified loads.
- **Plan 0.4 min old.** In 6 h: 58 commits, **max gap 11.9 min**. Calm-hours cadence on the split, with both overnight
  restarts now outside the 6-h series. 32 suggested -> 25 sized -> 19 positions.
- **Execution, 60 min:** 20 live ticks, 0 placed, 0 failed. Orders today 19, unchanged: 17 filled, 2 maker posts
  resting 246 and 241 min, exempt until kickoff.
- **Gate:** clock BC-042 from 08:31:33Z, 0 of 800.
- **Endpoints:** all 7 read 200, all under 0.55 s. 0 kills.

## Reading 33 — Wed 11-18 5:48 AM CST (11:48Z), window 60 min

- **Quiet and clean.** The only flag is the same 2 unclassified loads.
- **Plan 5.8 min old.** In 6 h: 64 commits, max gap 11.9 min. The 11-19 board was also written at 11:45:51Z.
  32 suggested -> 25 sized -> 18 positions.
- **Execution, 60 min:** 19 live ticks, 1 placed (kalshi), 0 failed. Orders today 20: 18 filled, 2 maker posts
  resting about 5 h, exempt until their kickoff.
- **Endpoints:** all 7 read 200, all under 0.7 s. 0 kills. **Gate:** BC-042 from 08:31:33Z, 0 of 800.

## Reading 34 — Wed 11-18 6:48 AM CST (12:48Z), window 60 min — after the planned vhdx compaction

- **The fleet was down for the planned WSL disk compaction.** It started 12:37:58Z (6:37 AM CST), according to lane
  `web-silent-worker-kills`, whose watcher it stopped. It ran under the vhdx-shrink plan's own lane.
  - Before reading anything, this lane checked over HTTP only: `/healthz` returned 200 at 12:48:14Z, and no
    compaction process was running. **No `wsl` command was run while the compaction might still have been
    going**, since starting WSL mid-compaction could break it.
- **Every role came back together:** supervisor up from about 12:44:28Z, web 610, refresh-worker 678,
  live-odds-worker 679. **The board-process split came back with them:** `BOARD_PROCESS_MODE mode=process parent=678`
  and `STARTED pid=742` at 12:44:44Z, exactly 1 serve child. The env switch survived the restart, as designed.
  - Downtime was about 6.5 min, 12:37:58 -> about 12:44:28Z.
- **Plan 14.5 min old.** The last write, at 12:34:00Z, came before the compaction. The first one after boot is
  expected about 10-20 min after boot. In 6 h: 68 commits, max gap 11.6 min (the outage gap is still open).
- **Execution, 60 min:** 18 live ticks, 1 placed, 0 failed.
  - Orders today 21: 19 filled, 2 maker posts resting about 6 h, exempt until kickoff.
  - Unreconciled 0.
  - Banner ok and armed, state 161 s: **the live-odds-worker is executing again after the restart.**
- **Endpoints:** all 7 read 200, all under 0.3 s. **Gate:** BC-042 from 08:31:33Z, 0 of 800. The compaction loaded
  no code, so it is no betting change.

## Reading 35 — Wed 11-18 7:20 AM CST (13:20Z), window 32 min

- **The plan resumed after the compaction restart.** The gap across the outage was **14.7 min**, from 12:34:00Z to
  the first write after boot; that is now the 6-h series' max gap. In 6 h: 73 commits, newest 13:19:16Z, plan 1.0 min
  old. The restart is closed out.
- **Execution, 32 min: 8 placed** (kalshi 5, polymarket 3), **0 failed**, in 10 live ticks: a morning pregame burst.
  - Orders today 29: 27 filled, 2 maker posts resting about 6.6 h, exempt until kickoff.
  - Unreconciled 0. Cap use: kalshi 14.0%, polymarket 8.6%.
- **Endpoints:** all 7 read 200, all under 0.55 s. 0 kills. Lane `web-silent-worker-kills` read 0 web kills overnight
  (01:46-12:37Z) and re-armed its watcher at 12:47Z.
- **Gate:** BC-042 from 08:31:33Z, 0 of 800. Same 2 unclassified loads, with their lanes.

## PERFORMANCE — added to every reading from 11-18 7:49 AM CST (user: "we need to be assessing PERFORMANCE and ROI of the portfolio and continue to optimize this as part of the monitoring")

**What each reading now carries** (probe `performance`, built on `scripts/live_book_edge_readout.py`, the adopted gate's
own instrument):
- **Results by window** (yesterday, last 7, last 30, all): bets, games, ROI net of fees with an event-clustered 95%
  range, won against the breakeven of the prices paid, and fees as a share of stake.
- **Same-book CLV** gross and fee-net, plus the close's calibration on our sides.
- **30-day slices** by venue, sport, market, sizing path, predicted-EV band, price band and stake quartile.
- **Signals:** slices with at least 30 bets and 20 games whose 95% range excludes 0, plus EV bands whose realized upper
  bound is below their predicted EV.
- The Portfolio Watch page shows ROI tiles, a "where it makes and loses money" table, and the signals in the findings
  table.
- **Slices are evidence for per-line fixes only, never for switching off a sport or market** (learnings line 1056,
  `by_dimension`'s own contract). Percentages and counts only here; dollars stay in the local reading JSON.

### Baseline — Wed 11-18 7:49 AM CST (13:49Z), `/api/portfolio/live?on=all&show=all`

| window | bets / games | ROI | 95% range | won vs breakeven | fees |
|---|---|---|---|---|---|
| yesterday (11-17) | 46 / 17 | -8.02% | -32.3 .. +16.2 | 63.0% vs 61.9% | 3.03% |
| last 7 (11-10..11-17) | 401 / 168 | -2.71% | -13.3 .. +7.9 | 58.2% vs 59.6% | 2.71% |
| **last 30 (10-18..11-17)** | **1,605 / 673** | **-7.35%** | **-12.8 .. -1.9** | 54.5% vs 56.3% | 2.92% |
| all | 2,025 / 1,093 | -11.02% | -18.3 .. -3.7 | 51.5% vs 53.9% | 2.92% |

- **CLV, same-book, last 30 (580 bets):** gross +1.28 pp, **fee-net -0.36 pp (se 0.21)**. The picks beat their close
  by less than the venue fee. Close calibration on our sides: -6.28 pp (z -2.93).
  - Last 7: fee-net -0.29 pp (se 0.39); calibration -9.67 pp (z -2.46).

**Signals beyond noise (30 d):**
- **The book as a whole:** -7.35% [-12.8, -1.9].
- **Predicted EV 2-5% (953 bets / 502 games, 59% of bets):** predicted +4.09%, realized **-10.75% [-18.5, -3.1]**.
  - Finer bands: [2,3) -20.5% [-40.0, -1.0] (96 / 81); [3,4) -12.1% [-24.5, +0.2] (267 / 193);
    [4,5) -8.2% [-19.0, +2.5] (590 / 366); [5,7) +5.7% [-9.8, +21.3] (189 / 141).
  - **The loss is spread, not concentrated.** Every sport is negative in the 2-5 band (only NCAAB beyond noise on
    its own, 84 / 60). Both venues are negative. The `model_edge` sizing path is -11.25% [-19.4, -3.1].
  - The 5-10 band's +5.7% is NOT supported by its CLV: fee-net -0.74 pp (se 0.31). Treat it as noise, not as
    "higher EV is better".
- **Largest-stake quartile (64.0% of dollars):** -9.2% [-16.9, -1.5]. Q1-Q3 are -6.8 / -5.9 / -2.8%.
- **Other slices beyond noise:**
  - market `totals` -12.2% [-23.9, -0.5] (391 / 297);
  - price band 0.30-0.45 -12.6% [-23.8, -1.3] (315 / 206);
  - venue kalshi -6.25% [-12.1, -0.4] (1,196 / 589).
- **No slice wins beyond noise** at 30 bets / 20 games.

### What it says, and the levers that already exist (each is a betting change, so each is the user's call)

The live book buys at prices that need a 56.3% win rate after fees and wins 54.5%. Before fees it beats the same-book
close by +1.28 pp; the fee (about 2.9% of stake) turns that into -0.36 pp. The model's claimed 2-5% edge is not there
at the price paid after fees, and that band is most of the book.

1. **The EV bar is the threshold lever, judged per line, never a market switch.**
   - Base `SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`; live net-of-fee floor `SYNDICATE_LIVE_NET_FLOOR_KALSHI=1.0`,
     `_POLYMARKET=0.5`.
   - The per-cell `min_ev_tuner` runs nightly in **shadow**, **95 of 95 cells hold**: each cell's marginal band is too
     thin to reach its z. The pooled variant proposes 1 raise (11-17, 11-18).
   - The book-level band evidence above is far stronger than any one cell's, and nothing reads it.
   - **Cheapest next measurement, no money:** the paper ladder already records below-floor rows by net-EV band
     (`LADDER_PLAN_WRITTEN bands={'m1to0','0to1','1to2','ge2'}`). Its graded results by band would show where a
     higher net floor stops losing, before any live change.
2. **Execution cost:** fees at 2.9% of stake are larger than the gross CLV. The Kalshi maker pilot is the fee lever;
   its shadow job runs (`kalshi-maker-shadow`).
3. **Sizing:** the top stake quartile loses more than the rest. Compounding/Kelly stakes are largest where the claimed
   EV is highest, and the claimed EV is overstated.
4. **Timing:** the gate's clock restarted at BC-042 (08:31:33Z) with 0 events. A betting change now costs no gate time.

## Paper ladder by net-EV band — does a higher live floor stop the losses? (user "Yes, measure it", 11-18)

**Hypothesis, written before the run:** if the live book's losses come from taking edges that are too thin, the paper
ladder's higher net-EV bands earn more than its lower ones, and some band above today's floor (Kalshi 1.0, Polymarket
0.5) earns beyond noise. **Falsified if** returns do not rise with net EV, or no band above the floor is positive
beyond noise.

**Read:** `scripts/paper_ladder_readout.py` (lane `paper-alongside-live`'s own instrument, pre-registered 2026-10-20 in
`findings_2026-10-20_paper_ladder.md`). Run read-only on the fleet's paper ledger with refresh-worker's env, nice 19,
on fleet head `2ae0c646a`.
- **Coverage:** paper bets submitted since 2026-10-20T16:18:24Z and settled by 11-18 14:2xZ. **27,347 bets over 29 slate
  dates, 10-20..11-17.** This is the fleet, not the git mirror.
- **Units:** flat ROI per bet (mean return per dollar, x100), event-clustered SE. Same-book CLV in pp (gross; the
  readout's `clv_pct`).

| net-EV band | Kalshi ROI ± SE (games) | CLV | Polymarket ROI ± SE (games) | CLV | readout verdict |
|---|---|---|---|---|---|
| paper venue book (the live selection's paper twin) | -5.7 ± 3.8 (318) | +1.65 | -2.1 ± 5.2 (185) | +1.12 | no change |
| ge2 (>= 2 pp, above both floors) | **-9.4 ± 5.1** (109) | -0.91 (n=23) | -7.5 ± 6.4 (79, too few) | -7.96 (n=10) | no change / insufficient |
| 1to2 | **+1.2 ± 3.1** (499) | +1.07 | -6.8 ± 4.4 (340) | +0.58 | straddles 0 |
| 0to1 | -5.9 ± 1.7 (1,196) | +0.95 | -3.7 ± 2.1 (981) | +0.92 | Kalshi AGAINST: keep the floor |
| m1to0 | -4.0 ± 1.2 (1,341) | +0.85 | -5.1 ± 1.5 (1,190) | +0.45 | AGAINST both: keep the floor |

**Result: the hypothesis is FALSIFIED.**
- **Returns do not rise with net EV.** Kalshi's best band is 1to2 at +1.2 ± 3.1; its ge2 band is the worst
  (-9.4 ± 5.1, 1.8 SE below 0). No band above either floor earns beyond noise.
- **Raising the live floor is not supported.** It would keep the bands that lose most and drop the one band near
  breakeven.
- **The floor itself is confirmed:** below it, 0to1 and m1to0 lose beyond 2 SE (pre-registered AGAINST). Lowering it
  is also not supported.
- **Positive same-book CLV with negative ROI in almost every band**, paper and live alike. On the live book the close
  overprices the sides we pick by 6.28 pp (z -2.93, 30 d). The picks beat the close and still lose, because the close
  on those sides is itself too high. That points upstream of any threshold: at which sides and prices the model's
  edge is real, versus where the venue's close is biased (for example a favourite-longshot pattern; live price band
  0.30-0.45 is -12.6% beyond noise).

**So the EV bar is not the lever.** F9 is updated. The next optimization lead is the close-calibration gap: where, by
side and price band, do our picks win less than the close implies, measured on the live book and the paper ladder
together? That decides whether the fix is in the model's probabilities (calibration shrink) or in which prices we
accept. The cell table (`--cells`, descriptive only) was not read; no cell-level rule is pre-registered.

## Reading 37 — Wed 11-18 8:21 AM CST (14:21Z), window 60 min

**Results first.** No live bet was graded since 7:49 AM, so the windows equal the baseline: last 30 days -7.35%
[-12.8, -1.9] on 673 games, last 7 days -2.71% [-13.3, +7.9], fee-net CLV (30 d) -0.36 pp. The same 8 signals.
Today's (11-18) bets are not graded yet.

**Optimization lead this reading — F12, the gate's clock and the change cadence.**
- The gate's clock is now **BC-047 from 14:05:39Z**, 0 of 800 events. In the last 24 h four live-betting changes
  loaded, each restarting the count:
  - BC-042 08:31Z, the board-process split;
  - BC-045 08:03Z, NFL seeds + I-17 (classified after the fact);
  - BC-046 13:47Z, the odds-lane deadline #838;
  - BC-047 14:05Z, NHL in-play props on.
- The book grades about **24 games a day**: 168 in the last 7 days, 673 in the last 30. **800 games therefore needs
  about 33-36 consecutive days with no betting change.**
- At today's cadence the count never gets past about one day of games. **As adopted ("Any betting change"), the
  scale-up gate cannot pass.** No live stake or cap can rise until it does.
- **This is the user's call, not a fault:** keep the gate and batch betting changes into rare windows, or decide which
  changes restart the clock. Recorded with the numbers.

**The fleet since 7:20 AM:**
- **Fast-forward to `2ae0c646a` at 13:47Z** (BC-046). Then a **drained full `down`/`up` at 14:05Z** for the NHL
  in-play props env key (BC-047).
- All roles rebooted about 14:05:18Z (refresh-worker 23140, live-odds 23141, web 23074).
- **The board-process split came back with them:** `mode=process parent=23140`, child 23192 ready at 14:05:44Z,
  1 serve process.
- BC-043 (the compaction restart) is classified `no`. BC-044 (11-17 NFL rebuild) and BC-045 are classified `yes`.
  **The register's unclassified count is now 0, so this reading has 0 anomalies.**

**Health:**
- Plan 8.3 min old. In 6 h: 74 commits, max gap 15.0 min across the 14:05 restart.
- **Execution, 60 min:** 19 live ticks, 5 placed (polymarket), 0 failed.
- Orders today 35: 33 filled, 2 maker posts resting about 7.6 h, exempt until kickoff. Unreconciled 0.
- Cap use: kalshi 14.0%, polymarket 13.7%.
- All 7 endpoints 200 (`/portfolio` 0.72 s). 0 kills.

## Reading 38 — Wed 11-18 9:22 AM CST (15:22Z), window 60 min

**Results first.** No new grades yet today, so the windows are unchanged: 30 d -7.35% [-12.8, -1.9] on 673 games,
7 d -2.71%, fee-net CLV -0.36 pp. The same 8 signals. 11-18's bets grade from the afternoon slate on.

**A fifth live-betting change in 24 h: BC-048, 14:42:52Z** (lane `ncaab-total-overprojection`, ff `2ae0c646a` ->
`36a9f5501` and a refresh-worker TERM).
- `#816`: a college totals phase whose calibration FAILED its walk-forward now serves the MARKET line, not the
  engine's raw number. **NCAAB and WNCAAB pregame totals stop producing bets**; NCAAB live is unchanged.
- This is a model fallback on lines whose fit failed, not a market switch.
- It meets this lane's evidence:
  - 30-day `totals` -12.2% [-23.9, -0.5];
  - NCAAB in the EV 2-5 band -33.9% [-59.6, -8.1].
- The next readings can watch the `totals` and NCAAB slices for the effect. Today's bets settle under the new rule.
- **F12 updated:** BC-042, BC-045, BC-046, BC-047 and BC-048 in about 24 h. The gate's clock is 0 of 800 again from
  14:42:52Z.

**Plan across the 14:42Z restart: a 33.1-min gap**, the largest in 6 h (70 commits). The refresh-worker TERM drops the
build in flight and needs a full cycle to publish. **The board split survived again:** refresh-worker 139688, child
139716, 1 serve process. Web and live-odds-worker were not restarted (up since 14:05Z). Plan 2.7 min old at the
reading.

**Health:**
- **Execution, 60 min:** 20 live ticks, 4 placed (kalshi 3, polymarket 1), 0 failed.
- Orders today 39: 37 filled, 2 maker posts resting about 8.6 h, exempt until kickoff. Unreconciled 0.
- Cap use: kalshi 15.2%, polymarket 15.0%.
- All 7 endpoints 200 (`/portfolio` 0.55 s). 0 kills. **Anomalies: 0.**

## Close calibration by side and price band — PRE-REGISTRATION (written 2026-11-18 15:33:59Z, before any number below is computed; user "Yes, measure it")

**Question.** The live book's picks beat the same-book close (gross CLV +1.28 pp, 30 d) and still win 6.28 pp less than
the close implies (z -2.93). Why?

**Known confound, stated first.** The same-book close is our side's last pregame **ask** (`book_quotes_last_pregame`;
`kalshi_board_join`: each side is priced from its own ask, and `yes_ask + no_ask > 1` by the spread). So
"wins - close-implied" is biased negative by roughly half the venue's spread before anything real.

**Measurement.**
- For each live bet with a resolved same-book close (30 d, decided), resolve the OPPOSITE selection's last pregame
  quote at the same venue with the same resolver (`order_clv._quote_closes_for_orders`, `read_quote_rows_for_events`).
  The flip: over<->under, home<->away, yes<->no; spreads negate the line.
- From the pair: **fair = ours / (ours + theirs)** (a proportional de-vig) and **overround = ours + theirs - 1**.
- Only pairs whose two quotes were captured within 15 min of each other count. The pair rate is reported.
- **Gaps (event-clustered):** raw = won - ours; **fair gap = won - fair**.
- **Slices:** fair-probability band (<.30, .30-.45, .45-.55, .55-.70, .70-.85, >=.85), market family (totals, spreads,
  h2h, props), side (over/under, home/away, yes/no), venue.

**Hypotheses and what falsifies each.**
- **H0, the spread:** the raw gap is mostly the half-spread. The fair gap is within 1.5 pp of 0, with a 95% range that
  includes 0. *Falsified if* the fair gap's 95% upper bound < -1.5 pp.
- **H1, favourite-longshot:** the fair gap concentrates in longshots (fair < .45), and favourites (fair >= .55) are
  calibrated. *Falsified if* the favourites' fair gap is at least as negative as the longshots', or the longshots'
  95% range includes 0.
- **H2, adverse selection (our picks):** the fair gap is negative across price bands alike. *Falsified if* any band
  with >= 50 bets has a fair gap > 0 beyond noise, or the gap differs across bands beyond noise in H1's direction.

**Decision use.**
- H0 survives: the close-calibration condition of the gate is mis-specified (an ask, not a fair price). That is a
  measurement fix, not a betting change.
- H1 survives: a per-line price-band lever, evidence only.
- H2 survives: the model's side selection or probabilities are the problem (calibration shrink).

### Close calibration — RESULT (runs 2026-11-18 15:34-15:39Z, read-only, refresh-worker env, fleet head `36a9f5501`)

**Instrument:** `C:\tmp\pfmon\close_calib.py` (run through `run_with_worker_env.py`). It applies the pre-registered
method above to `/api/portfolio/live?on=all&show=all` saved at 13:49Z.
- **Population:** live bets on 10-18..11-17, decided, with a resolved same-book close: **580 bets / 370 games.**
- **The opposite side's close paired within 15 min: 231 (39.8%).** Unpaired 349:
  - 265 had the two quotes more than 15 min apart;
  - 81 had the opposite side unchanged since our fill;
  - 3 opened in play.

| | gap, pp [95%] | bets / games |
|---|---|---|
| raw gap, won - ask, all 580 | **-6.36 [-10.56, -2.16]** (reproduces the readout's -6.28) | 580 / 370 |
| raw gap, paired | -1.00 [-7.79, +5.80] | 231 / 187 |
| overround at the close, paired | +1.84 [+1.19, +2.49] | 231 / 187 |
| **fair gap, won - de-vigged close, paired** | **+0.03 [-6.76, +6.81]** | 231 / 187 |

- **Paired, by fair band:**
  - .30-.45: +19.3 [-0.7, +39.3] (23);
  - .45-.55: -0.6 [-9.7, +8.5] (120);
  - .55-.70: -3.6 [-17.3, +10.2] (57);
  - .70-.85: -4.9 [-21.6, +11.8] (29).
- **Paired, by family:** h2h -10.6 [-26.3, +5.1] (36); every other family within +-3 pp. **By venue:** kalshi -2.6
  [-10.0, +4.9] (184), polymarket +10.1 [-2.4, +22.7] (47).

**Verdicts as registered:**
- **H0 (the spread) is NOT falsified** where it could be tested. On the 40% of bets with a contemporaneous two-sided
  close, our picks are calibrated against the fair close: +0.03 pp, while the raw ask-based gap is -1.0 pp with a
  +1.84 pp overround.
- **H1 (favourite-longshot) is FALSIFIED:** favourites are not better calibrated than longshots, and the paired
  longshot band leans positive.
- **H2 (adverse selection across bands) is not supported** on the paired set: the fair gap is about 0.
- **Power:** the paired fair gap's 95% range is +-6.8 pp. It rules out a -6.4 pp effect on liquid two-sided markets
  only at the edge.

**EXPLORATORY, not pre-registered: where the -6.36 pp lives.** The **349 unpaired bets carry -9.91 pp [-15.17, -4.65]**
(247 games), against -1.00 on the paired.
- **Unpaired by family:** props **-9.13 [-15.87, -2.40]** (205 bets / 121 games); totals -12.5 [-25.2, +0.3] (64);
  spreads -7.9 (36); h2h -4.9 (27); btts -21.9 (17).
- **Unpaired by venue:** kalshi **-9.30 [-15.23, -3.36]** (273), polymarket **-12.10 [-22.97, -1.23]** (76).
- **Unpaired by ask band:** .30-.45 **-31.4 [-45.5, -17.4]** (19); .55-.70 **-9.2 [-17.8, -0.6]** (128).
- **Reading:** these are markets where the other side was not quoted near our side's close: thin, one-sided books,
  mostly player props. There the last ask is far from a fair price (the paired props alone ran a +4.25 pp overround),
  so both our ENTRY and the "close" sit on a wide spread.

**What it means for the levers:**
1. **The gate's condition 3 compares wins to an ask, so on thin markets it reads a spread as a calibration failure.**
   Measured against a de-vigged two-sided close, liquid picks are calibrated. That is a **measurement fix** to the
   adopted gate's instrument (de-vig where a pair exists, report the paired share), not a betting change. The
   wording of an adopted gate is the user's.
2. **New lead, F13: the live book's shortfall concentrates in thin, one-sided markets (mostly Kalshi player props),
   where fills pay a wide ask.** Liquid two-sided markets look calibrated before fees.
   - **Next measurement (no money):** ROI against the spread AT ENTRY. That is our fill against the opposite side's
     ask at fill time, by market family.
   - If ROI falls with entry spread, a **per-line maximum-spread rule** judges each line on its own spread: a
     threshold, not a market switch (learnings line 1056).

## Reading 39 — Wed 11-18 10:22 AM CST (16:22Z), window 60 min

**Results first.** No new grades, so the windows are unchanged: 30 d -7.35% [-12.8, -1.9], 7 d -2.71%, fee-net CLV
-0.36 pp. Today's bets settle from the afternoon. Optimization leads: F13 (thin-market spread, next = ROI vs the spread
paid at entry) and F12 (gate cadence), both waiting on the user.

**NEW anomaly: `ENDPOINT live_today slow: 25.58 s > budget 3.0 s`.**
- *Hypothesis, written before reading:* a web-worker main-loop stall like yesterday's kills, so the stall dump fired.
- **Falsified as written.** The dump is armed at **40 s**, not 20 s as the hypothesis said, and no dump fired.
- **Cause, from `web.log`:** worker 23086 served a `POST /api/intelligence/query` (Python-urllib script client)
  16:22:07-16:22:25Z: 25,945 ms, 3.7 MB, rows 4,906, `board_read` 13,216 ms, `hydrate_and_mirror` 3,197 ms. **Our
  `GET /api/portfolio/live` ran in the same worker at the same time (25,163 ms)**: CPU/GIL contention between two
  requests, not a loop stall.
- The worker then grew 954 -> 1,161 MB (`GROWTH_EPISODE`, pymalloc) and was **hard-recycled**
  (`WEB_WORKER_MEMORY_RECYCLE hard=true`, limit 625 MB) at 16:22:38.8Z, drained cleanly. New worker 164574 at 16:22:54Z.
- **Rate:**
  - `/api/portfolio/live` over 3 s: 1 of 27 reads today.
  - Intelligence queries with `board_read` > 8 s: 32 of 416 today.
  - Hard web-worker memory recycles: 156 since 00:00Z.
- **The portfolio endpoint is the victim, not the cause.** Handed to lane `web-silent-worker-kills` (it owns web-worker
  health, F2/F3) at 16:24Z with the evidence. Which client posts the 4,906-row queries is unverified. Finding F14.

**Health otherwise:**
- Plan 3.6 min old; in 6 h 66 commits, max gap 33.1 min (the 14:42Z restart).
- **Execution, 60 min:** 18 live ticks, 1 placed, 0 failed. Orders today 40 (38 filled, 2 maker posts resting).
- Cap use: kalshi 15.5%, polymarket 15.0%.
- `/portfolio` 2.17 s of 3.0 (slow-ish, same minute).
- Gate: BC-048, 0 of 800.

## Reading 40 — Wed 11-18 10:56 AM CST (16:56Z), window 35 min

**Results first.** No new grades: 30 d -7.35% [-12.8, -1.9] on 673 games, fee-net CLV -0.36 pp.

**Betting changes 6 and 7 in about 32 h: BC-049 (16:07:01Z) and BC-050 (16:45:40Z)**, lane `odds-lane-sport-deadline`.
- **BC-049:** NHL pregame generation runs after every other sport's odds, with a 900 s deadline.
- **BC-050:** an NHL stats-REST report cache, ff `cdab875d5..59fbefc71`, no restart.
- The gate's clock is BC-050, 0 of 800. F12 updated: BC-042, 045, 046, 047, 048, 049, 050.

**The board filled with tonight's NBA slate.** The plan's suggested rows went 30 -> **164** (of 4,647 board rows).
- `beyond_max_positions` refused **138**: NBA 117, NHL 9, NCAAF 6, soccer 3, NFL 2, NCAAB 1. `max_positions` = 25.
- So the cap now binds, and **the rank that picks 25 of 164 decides what is bet.**
- **Optimization lead (to measure, no money):** do the ranked-in positions beat the ranked-out suggestions? The paper
  ladder or the board's own grading of unbet suggestions would show it.

**Health:**
- Plan 4.7 min old; 13 positions, ceiling used 21.0%.
- **Execution, 35 min:** 10 live ticks, 3 placed, 0 failed. Orders today 43 (41 filled, 2 maker posts resting).
- Cap use: kalshi 16.3%, polymarket 15.0%.
- All 7 endpoints 200, all under 0.5 s (the 25 s read was a one-off, F14). **Anomalies: 0.**

## ROI against the spread paid at entry — PRE-REGISTRATION (written 2026-11-18 17:11:50Z, before any number below is computed; user "Yes, measure it")

**Question.** F13 says the live book's shortfall sits in thin, one-sided markets. Does ROI fall as the spread we
**paid at entry** widens?

**Population.** Live bets with `selected_date` 10-18..11-17, decided (`live_book_edge_readout.bets_from_orders`, the
gate's own predicate), **pregame only** (`submitted_at` < `commence_time`). In-play entries are reported apart, as
descriptive only.

**Entry prices.**
- From the fleet's quote log (`clv_join.read_quote_rows_for_events`, same keys as the CLV resolver), at the bet's
  venue: our selection's and the opposite selection's latest quote change at or before `submitted_at`, and before
  kickoff. The flip is over<->under, home<->away, yes<->no, with spreads negating the line.
- **Entry overround = ours + theirs - 1. Entry fair = ours / (ours + theirs).** Each quote's age at entry is reported.
- A bet with no opposite quote before its fill is its own group, **"one-sided at entry"**.

**Groups:** entry overround < 1 pp, 1-2, 2-4, 4-8, >= 8 pp, one-sided.

**Metrics:** dollar ROI net of fees with the event-clustered SE (`summarize`), and won - entry fair (event-clustered).

**Hypotheses.**
- **H-spread:** ROI is lower where the entry spread is wide. The pooled wide group (>= 4 pp plus one-sided) has a
  lower ROI than the pooled narrow group (< 2 pp), and the difference's 95% interval
  (SE = sqrt(se_wide^2 + se_narrow^2)) excludes 0. *Falsified if* that interval includes 0 or the wide group's ROI
  is higher.
- **H-fair:** against the entry fair price, picks are calibrated in every group with >= 50 bets: won - fair within
  95% of 0. *Falsified if* any such group's 95% interval excludes 0.

**Decision use.**
- H-spread survives: a **per-line entry-spread limit** (judge each line on its own spread, never a market switch) is
  the candidate lever, and its threshold comes from this table. It is the user's call, and a betting change.
- H-fair survives as well: the live book's loss is the spread and fees it pays, not its picks.

## Live sizing trace — is live-odds-worker staking raw sim probabilities? (fleet-watcher lead, user's OK relayed 11-18 ~11:20 AM CST)

**Lead as received:** live-odds-worker places the live orders, and its env has no
`SYNDICATE_STAKED_PROBABILITY_UNFITTED`, which means `raw`. Under `raw`, a model-edge row in an unfitted cell would
be staked on the raw sim. Not confirmed: whether live orders go through that path.

**Read, 2026-11-18 17:16Z, read-only:** the sizing fields stamped on each live order record
(`/api/portfolio/live?on=all&show=all`; copy at `C:\tmp\pfmon\sizing_trace_live_all.json`, not committed).
- **All 48 live orders submitted 11-18** (44 with selected_date 11-18):
  - `sizing_basis = model_edge`;
  - `staked_probability_version = market_fair@staked_probability_pooled_v1@2026-10-22T21:45:48Z`;
  - `sim_share_of_stake = 0.0`;
  - `side_picked_by = price_shopping`.
  - Both orders the watcher named carry exactly this: KXNCAAFSPREAD-26NOV20OREMSU-ORE17 (16:54:40Z, model_edge_pct
    -8.31, ev_pct 4.99) and KXNCAAFTOTAL-26NOV21VTMIA-62 (17:06:51Z, model_edge_pct 20.98, ev_pct 4.86). The model
    edge did not reach the stake.
- **Last 30 days (1,634 live orders):**
  - `market_fair@...pooled_v1` 1,053;
  - `inplay:inplay_book_median_novig/1` 214;
  - `market_fair@unfitted` 20;
  - `unfitted` 11 (sizing basis `market_fair`);
  - no stamp 336 (orders before the field existed);
  - **raw or sim-based: 0.**
  - `side_picked_by`: price_shopping 1,188, simulation 1, none 445. Mean `sim_share_of_stake` -0.039 (n=1,185).

**Answer: NOT raw-sim sizing.** Every live order in 30 days was staked on the market-fair probability. The pooled v1
profile gives the sim zero weight, and the 31 unfitted-cell orders also resolved to market fair. The missing
`SYNDICATE_STAKED_PROBABILITY_UNFITTED` on live-odds-worker is not reached in practice. Setting it to `market` would
change nothing observed here; it is a guard against a future unfitted path only. That is the user's call, and it would
be a betting change.

**What this adds to F9.** The live book's "edge" is a **price-shopping edge**: the venue's ask against the de-vigged
sportsbook consensus (`market_fair`), with the model's sim weighted at 0. So the 2-5% predicted EV that realises
-10.75% [-18.5, -3.1] is the gap between the venue price and the consensus fair price, and that gap does not pay
after fees. Read with F13 (thin, one-sided markets), the venue being "cheaper than the consensus" on thin markets
looks like a stale or one-sided venue quote, not value. The candidate levers are unchanged: per-line spread and
liquidity at entry, now under measurement.

### ROI against the spread paid at entry — RESULT (run 2026-11-18 17:13-17:18:33Z, read-only, refresh-worker env)

**Instrument:** `C:\tmp\pfmon\entry_spread.py`, the pre-registered method, run on the 13:49Z copy of
`/api/portfolio/live?on=all&show=all`.
- **Population:** live bets selected 10-18..11-17, decided, pregame, with a flippable side: **1,156** (419 in-play
  excluded).
- **Coverage, stated first:** **for 555 of 1,156 (48%) the quote log has no change for OUR OWN side at or before the
  fill.** Those bets fall into the "no usable pair" group with any whose opposite side was missing. That group is
  therefore mostly a logging gap, not a measured one-sided market.

| entry overround | bets / games | ROI [95%] | won vs breakeven | won - entry fair | opposite quote age p50 |
|---|---|---|---|---|---|
| < 1 pp | 193 / 153 | -8.67% [-24.4, +7.0] | 48.2 vs 54.4 | -5.52 pp (se 3.72) | 82 min |
| 1-2 pp | 118 / 100 | -9.17% [-31.4, +13.0] | 48.3 vs 54.4 | -4.40 pp (se 4.69) | 48 min |
| 2-4 pp | 49 / 47 | -12.72% [-44.0, +18.6] | 46.9 vs 58.3 | -9.34 pp (se 7.23) | 139 min |
| 4-8 pp | 18 / 18 | +22.26% [-28.5, +73.0] | 50.0 vs 53.2 | -2.10 pp (se 11.4) | 191 min |
| >= 8 pp | 10 / 10 | -3.96% [-62.2, +54.3] | 30.0 vs 53.6 | -19.79 pp (se 15.0) | 1,014 min |
| no usable pair | 768 / 371 | -8.39% [-16.6, -0.2] | 62.6 vs 62.3 | n/a | n/a |

**Verdicts as registered:**
- **H-spread is FALSIFIED.** Wide (>= 4 pp plus no pair) **-7.28%** (796 / 394) against narrow (< 2 pp) **-8.86%**
  (311 / 226). The difference is +1.58 pp, 95% [-13.96, +17.12]: the interval includes 0 and the wide group is not
  lower. **The spread paid at entry does not explain the losses.** Tight-spread bets lose as much. **A per-line
  entry-spread limit is NOT supported.**
- **H-fair is not falsified, but leans one way.** In both groups with >= 50 bets, the picks win less than the venue's
  own fair price at entry implies: < 1 pp **-5.52 (se 3.72)**, 1-2 pp **-4.40 (se 4.69)**. Each 95% interval includes
  0, and both point the same way.
- **F13's exploratory thin-market split is partly a coverage artefact.** Its "unpaired" group was also mostly bets
  the quote log never saw. F13 is downgraded.

**Where that leaves the optimization.** Across five instruments the live book loses about 7-9% at every spread,
every EV band above the floor, and both venues. The bets are chosen by **price shopping**: the venue's ask is "cheaper"
than the sportsbook consensus fair, and the sim has 0 weight (trace above). In tight two-sided venue markets, those
picks win about 4-5 pp less than the venue's own fair price says.
- **The open question is the price-shopping premise itself:** when Kalshi or Polymarket disagrees with the sportsbook
  consensus, is the consensus right?
- **The next measurement (no money):** for the same bets, calibration of outcome against the consensus fair (the
  staked probability) versus against the venue's own fair at entry. If the venue's fair is better calibrated than
  the consensus on these selections, price shopping into these venues is adverse selection, and the "edge" is not
  one.
- **Also owed, separately:** the quote log's venue coverage. 48% of live fills have no logged own-side quote before
  the fill. That blinds the CLV and spread instruments on about half the book.

## Reading 41 — Wed 11-18 11:43 AM CST (17:43Z), window 50 min

- **Results first.** No new grades: 30 d -7.35% [-12.8, -1.9] on 673 games, 7 d -2.71%, fee-net CLV -0.36 pp. Today's
  bets grade from the evening slate.
- **Optimization state.** The pre-registered spread test falsified the spread lever (F13 downgraded). The open lead is
  F15, the price-shopping premise; a calibration test of the sportsbook consensus against the venue's own fair is
  offered to the user.
- **Plan 1.3 min old.** 160 suggested -> 25 sized -> 13 positions (`beyond_max_positions` 135). Ceiling used 19.1%.
- **Execution, 50 min:** 16 live ticks, 3 placed (kalshi), 0 failed.
  - Orders today 44: 43 filled, 1 maker post resting 656 min, exempt until kickoff.
  - Cap use: kalshi 16.7%, polymarket 15.0%.
- **Endpoints:** all 7 read 200, all under 0.35 s. 0 kills. **Gate:** BC-050, 0 of 800. **Anomalies: 0.**

## Is the sportsbook consensus or the venue's own price better calibrated on our picks? — PRE-REGISTRATION (written 2026-11-18 18:31:42Z, before any number below is computed; user "Yes, measure it")

**Question (F15).** Every live order is picked by price shopping: the venue's ask is below the sportsbook-consensus
fair price, which is what the stake is sized on. When the venue and the consensus disagree, which one is right?

**Prices.**
- **Consensus fair** q_c = implied(`requested_price`) x (1 + `ev_pct`/100). Under market-fair staking (48 of 48
  orders today, 1,053 of 1,634 in 30 d), `ev_pct` is the consensus fair's EV at the requested price.
- **Venue fair at entry** q_v = ours / (ours + theirs), from the quote log at the fill (the entry-spread method above).

**Population.**
- Live bets selected 10-18..11-17, decided (pushes out), pregame.
- **Primary:** the bets with a usable venue pair at entry (about 388).
- **Secondary:** q_c's calibration alone on every bet that has `ev_pct` and `requested_price`.

**Metrics** (event-clustered): gap_c = won - q_c; gap_v = won - q_v; **Brier difference d = (won - q_c)^2 - (won - q_v)^2**
(d > 0 means the venue is better calibrated).

**Hypothesis H-venue:** on the primary set, the venue's own price is the better forecast. d > 0 with its 95% interval
above 0, **and** gap_c < 0 with its 95% interval below 0 (the consensus overstates our side).
- *Falsified if* d's interval includes 0 or d < 0.
- If gap_c is negative but d's interval includes 0, the verdict is "consensus overstates our side, venue not shown
  better".

**Decision use.**
- H-venue survives: "venue below consensus" is adverse selection on these venues, and price shopping as built has no
  edge. The candidate levers are to judge EV against a blend that includes the venue's own fair, or to require the
  sportsbook consensus to agree with the venue's own move. Each is per line, a betting change, and the user's call.
- H-venue falsified: the consensus is fine, and the loss sits elsewhere (fees, stake sizing).

### Consensus vs venue calibration — RESULT (run 2026-11-18 ~18:00-18:10Z, read-only; `C:\tmp\pfmon\calib_cons_venue.py`)

**Population:** decided pregame live bets, 10-18..11-17: 1,156. The consensus fair is recoverable for 1,155.
**Primary** (consensus plus a venue pair at entry): **388 bets / 272 games.**

| primary, 388 / 272 | pp [95%] |
|---|---|
| won - consensus fair (gap_c) | **-7.76 [-13.12, -2.41]** |
| won - venue fair at entry (gap_v) | **-5.87 [-11.23, -0.51]** |
| Brier d = consensus - venue (x100; > 0 means the venue is better) | +0.21 [-0.14, +0.56] |
| consensus fair minus venue fair (the claimed edge) | +1.89 [+1.59, +2.20] |

- **By consensus-minus-venue gap:**
  - < 2 pp (143 / 121): won-consensus -7.09, won-venue -7.20;
  - **2-4 pp (225 / 177): won-consensus -8.60 (se 3.35), won-venue -5.79 (se 3.35)**;
  - 4-7 pp (17): noise.
- **Secondary** (all 1,155): won - consensus **-2.94 [-6.40, +0.51]**.

**Verdict as registered: "the consensus overstates our side, and the venue is not shown better."**
- H-venue is FALSIFIED on its Brier test: d's interval includes 0.
- **Both prices overstate the sides we pick, beyond noise:** the consensus by 7.8 pp, the venue's own fair by 5.9 pp.

**What it means:**
- The losses are not a bad fair-price source, a spread, or a threshold. **The price-shopping trigger selects sides
  that win less often than either market says.** It buys when the venue's ask sits below the consensus, and those
  are the sides that go on to lose.
- That is **adverse selection in the trigger.** The likely mechanism, not yet tested, is that one source has moved
  on information the other has not absorbed, and we buy the side the information moved against.
- In the strongest group (claimed edge 2-4 pp, 225 bets) the picks win 8.6 pp less than the consensus says, against
  a claimed +3.
- **Implication for the lever list:**
  - Thresholds, spread limits and fair-source swaps are all ruled out by the evidence above.
  - What remains is (1) **the trigger itself**: require the price gap to persist or the consensus to be fresh,
    tested on paper; and (2) **exposure while no edge is shown**: stakes at the measurement minimum. Both are betting
    changes and the user's call.

## Reading 42 — Wed 11-18 12:47 PM CST (18:47Z), window 60 min

- **Results first.** No new grades: 30 d -7.35% [-12.8, -1.9], fee-net CLV -0.36 pp. Today's 45 orders settle from the
  evening.
- **Optimization state:**
  - the betting-change windows are in force (first window Tue 11-24);
  - the program is on main (`plan_2026-11-18_profit_learning_program.md`);
  - S1 (freshness / adverse selection) is next;
  - live stakes at the measurement minimum is waiting on the user.
- **NEW anomalies: `books` 11.70 s (budget 2) and `live_today` 4.39 s (budget 3).**
  - *Hypothesis, written first:* F14-type contention or a recycle drain in the same web worker.
  - **Confirmed, recycle form:** **both web workers were hard-recycled within 2 s**:
    - pid 209505, 971 MB vs a 641 MB limit, after only 5 requests, at 18:48:01.6Z;
    - pid 206403, 994 MB, 10 requests, at 18:48:03.3Z.
  - Each drained with one accepted-but-unread request, and no worker served until 214265 booted at 18:48:09Z.
  - The portfolio endpoint is the victim again. Added to F14 and sent to lane `web-silent-worker-kills`.
- **1 unclassified load:** the soccer odds-lane ff `59fbefc71 -> 640c6d4fd` at 17:58:30Z (#840, lane
  `soccer-pregame-odds-lane`). That is 90 s before the window rule took effect, so it is not a violation. Its lane owes
  the classification.
- **Health otherwise:**
  - plan 8.6 min old;
  - 16 live ticks, 1 placed, 0 failed;
  - orders today 45 (43 filled, 2 resting: a maker post at 721 min and a fresh one at 4.9 min);
  - unreconciled 1, inside the grace;
  - cap use 16.7% / 16.1%.

## Reading 43 — Wed 11-18 1:07 PM CST (19:07Z), window 20 min

- **Results first.** No new grades:
  - 30 d -7.35% [-12.8, -1.9] on 673 events;
  - last 7 d -2.71% [-13.3, +7.9] on 168 events;
  - fee-net CLV -0.36 pp (se 0.21).
  - Today's 45 orders (44 filled, 1 resting) settle from the evening.
- **Stake cut ("Yes, cut stakes"): stood down before any restart, and waiting on the user.**
  - Env keys load only through a drained full down/up. That would also load other lanes' unloaded commits into both
    workers, outside a window: soccer #840, NHL `cdab875d5` / `59fbefc71`, `d1e14be46`, and `36a9f5501` on
    live-odds-worker.
  - Rolled back:
    - env file restored from its backup;
    - drain cleared (`DRAIN_CLEARED owner=live-stake-minimum`);
    - all three claims released.
  - Nothing loaded.
  - **The cut's size, measured from the full ledger** (`C:\tmp\pfmon\stake_floor_effect.py`):
    - over the last 7 graded dates, live staked $49 a day ($40.94 pregame + $7.95 in-play);
    - one contract per order would have been $31 a day ($29.24 + $1.83);
    - 226 of 380 pregame orders were already one contract;
    - at -7.35% that is about $1.30 a day of expected loss.
  - The plan's "about $100 a day" was the 30-day average. Corrected on main (`3c4fc9443`).
- **Anomaly: `page` 6.17 s (budget 3).**
  - *Hypothesis, written first:* a web recycle drain (F14).
  - **Confirmed:** pid 218465 was hard-recycled at 19:07:10.7Z (824 MB vs a 631 MB limit, 15 requests). The page read
    started at 19:07:07Z.
  - **Rate:** web recycles per hour (hard in brackets):
    - quiet 12Z-17Z at 1-4 (0-3);
    - **18Z: 18 (16)**;
    - overnight game hours 23Z-05Z: 17-45 (15-34).
    - Every hard recycle in the last 15 min came after 10-20 requests at 800-990 MB.
  - The evening will likely return to the overnight rate.
  - F14, owned by lane `web-silent-worker-kills`; the rate is added here for that lane.
- **Unchanged:**
  - 1 unclassified load (the soccer ff at 17:58:30Z, before the window rule; its lane owes the classification);
  - the gate's clock is BC-050 from 16:45:40Z, 0 of 800;
  - the maker post is still resting (740 min);
  - unreconciled 0;
  - cap use 16.7% / 16.2%;
  - plan 18.3 min old, 16 positions.

## Reading 44 — Wed 11-18 2:01 PM CST (20:01Z), window 55 min

- **Results first.** No new grades: 30 d -7.35% [-12.8, -1.9] on 673 events; 7 d -2.71% [-13.3, +7.9]. Today's 48
  orders settle from the evening.
- **Program news since reading 43 (all on main):**
  - Stake cut dropped by the user ("Yes, drop the cut"). Lane `live-stake-minimum` is closed; nothing loaded, and
    sizing stays compounding off venue capital.
  - **S1 freshness: FALSIFIED as registered**: +0.21 pp [-2.82, +3.24] on 6,300 TEST orders / 274 games (F16). No
    challenger for the 11-24 window.
  - In-play recorder backfill complete (27 nights, 319 files, 1.4 GB). The daily copy task `SyndicateInplayPreserve`
    is set up (7:15 AM); its first run returned result 0.
- **No new anomalies.** Every endpoint was inside budget: page 0.20 s, books 0.01 s, live 0.22 s.
- **F14 after the double-recycle fix** (web, live since 19:14Z, lane `web-silent-worker-kills`):
  - 3 recycles in 47 min: 19:16 soft, 19:25 hard, 19:49 hard;
  - none simultaneous, against 18 (16 hard) in the 18Z hour;
  - each came after 10-25 requests at 781-859 MB against a ~630 MB limit.
  - The pressure is the same; the overlap is gone. The evening will test it.
- **Flow:**
  - plan 1.5 min old: 198 suggested, 25 sized, 16 positions; 169 refused `beyond_max_positions`;
  - 16 live ticks, 3 placed, 0 failed (3 `axis_held_live`, a known guard);
  - orders today 48 (47 filled, 1 resting at 4.7 min; the 12-h maker post is no longer resting);
  - unreconciled 1, inside the grace;
  - cap use 17.5% / 17.1%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it); gate clock BC-050, 0 of 800.

## Reading 45 — Wed 11-18 3:01 PM CST (21:01Z), window 60 min

- **Results first.** No new grades: 30 d -7.35% [-12.8, -1.9] on 673 events; 7 d -2.71% [-13.3, +7.9]. Today's 49
  orders (all filled) settle from the evening.
- **Program:** S2 (in-play 95-99c favourites) is closed, **KILL under its own 10-25 pre-registration (R3)**:
  - 476 games over 27 nights;
  - +0.26c per game [-1.59, +1.95];
  - loss rate 3.99% against a 3% line (F17, `findings_2026-11-18_s2_inplay_favourites.md`).
  - S1 and S2 are both closed with no challenger.
- **Near miss: `live_all` 4.45 s (budget 5.0).**
  - *Hypothesis:* F14 again.
  - **Confirmed:** pid 252983 was hard-recycled at 21:01:07.1Z, at 1,082 MB against a 632 MB limit. The probe's read
    started at 21:01:06Z.
  - Since the double-recycle fix (19:14Z) there have been 4 web recycles in 20Z-21Z, all hard and none simultaneous.
    The closest pair was 80 s apart (20:41:11, 20:42:31), each after its own replacement booted.
  - **The peaks are climbing: 970 -> 1,001 -> 1,079 -> 1,082 MB** into the evening. Added to F14 for
    `web-silent-worker-kills`.
- **Flow:**
  - plan 0.6 min old: 166 suggested, 25 sized, 12 positions; 135 refused `beyond_max_positions`;
  - 20 live ticks, 1 placed, 0 failed (6 `axis_held_live`, a known guard);
  - orders today 49, all filled; nothing resting; unreconciled 0;
  - cap use 17.5% / 16.3%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it); gate clock BC-050, 0 of 800.

## Reading 46 — Wed 11-18 4:01 PM CST (22:01Z), window 60 min

- **Results first.** The first of today's bets has graded: all-time 2,026 bets / 1,094 events, -11.01%
  [-18.3, -3.7]. The 30-day window (1,605 bets, -7.35% [-12.8, -1.9]) and the 7-day window (-2.71%) are unchanged
  until today's slate settles.
- **No anomalies.** Every endpoint was inside budget: `live_all` 0.42 s (4.45 s last reading), page 0.38 s.
- **Flow:**
  - plan 11.7 min old (newest write 21:50Z; max gap 20.7 min over 6 h): 186 suggested, 25 sized, 15 positions; 158
    refused `beyond_max_positions`;
  - 18 live ticks, 3 placed, 0 failed (1 `game_started`, a known guard);
  - orders today 52, all filled; nothing resting; unreconciled 0;
  - cap use 18.0% / 17.5%;
  - paper book 14,863 settled, -1.30%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it); gate clock BC-050, 0 of 800.

## Reading 47 — Wed 11-18 4:58 PM CST (22:58Z), window 60 min

- **Results first.** No new grades since reading 46: all-time 2,026 bets / 1,094 events, -11.01%; 30 d -7.35%
  [-12.8, -1.9]. Today's 52 orders (all filled) settle from the evening.
- **New since reading 46: the gate's clock moved to BC-052, loaded 21:02:51Z (3:02 PM CST), 0 of 800.**
  - *Hypothesis, written first:* another lane loaded a betting change outside a window, either under a recorded
    exception or in breach of the rule.
  - **Read (betting_changes.md row BC-052):** lane `nba-midnight-bootstrap-hold`. The NBA games-history fetch is
    bounded and de-duplicated, default ON (`a3104a5b6`), so the NBA Elo/rest/form inputs change.
  - It is registered `[OUTSIDE WINDOW: user override 2026-11-18 ~2:50 PM CST ("Load it now"); not a revert / risk
    reduction / money-path fix]`. **Not a breach:** the user decided, and the row says so plainly.
  - Effect: the gate's 800-event count restarted at 3:02 PM, three hours after the window rule took effect.
  - BC-051 (web double-recycle hold, 19:14:22Z) is classified `no`.
- **No anomalies.** Every endpoint was inside budget: `live_all` 0.28 s, page 0.23 s.
- **Flow:**
  - plan 0.5 min old: 196 suggested, 25 sized, 17 positions; 169 refused `beyond_max_positions`;
  - 20 live ticks, 0 placed (16 `outside_price_band`);
  - orders today 52, all filled; nothing resting; unreconciled 0;
  - cap use 18.0% / 17.5%.
- **S3 measurement:** the daily maker-pilot line copy `SyndicateMakerPilotLines` is set up (first run 22:57Z, result
  0, 14 fills, 0 TAKER).
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it).

## Reading 48 — Wed 11-18 5:29 PM CST (23:29Z), window 32 min

- **Results first.** No new grades; 30 d -7.35% [-12.8, -1.9] on 673 events. Today's 54 orders (all filled) settle
  from the evening slate.
- **No anomalies.** Every endpoint was inside budget: `live_all` 0.34 s, page 0.12 s.
- **Flow:**
  - plan 0.2 min old: 229 suggested, 25 sized, 18 positions; 202 refused `beyond_max_positions`. The pre-slate board
    is the widest of the day.
  - 10 live ticks, 2 placed, 0 failed;
  - orders today 54, all filled; nothing resting; unreconciled 0;
  - cap use 18.6% / 18.6%.
- **Unchanged:** gate clock BC-052 from 21:02:51Z, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z, its lane owes
  it).

## Reading 49 — Wed 11-18 5:59 PM CST (23:59Z), window 31 min

- **Results first.** No new grades; 30 d -7.35% [-12.8, -1.9]. The slate has started: 4 games started and unsettled,
  none late.
- **No anomalies.** Every endpoint was inside budget: `live_all` 0.36 s, page 0.31 s.
  - 15 plan reads in the window (p95 237 ms), against 2 in quiet readings: the slate's in-play polling.
- **Flow:**
  - plan 3.8 min old: 235 suggested, 25 sized, 17 positions; 201 refused `beyond_max_positions`; 6
    `in_play_market_fair`;
  - 12 live ticks, 7 placed, 0 failed (1 `already_held_venue_contract`, a known guard);
  - orders today 61: 59 filled and 2 submitted (0.6 and 0.7 min old). Unreconciled 2 = those two, inside the
    grace;
  - cap use 20.6% / 22.3%.
- **Unchanged:** gate clock BC-052 from 21:02:51Z, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z, its lane owes
  it).

## Reading 50 — Wed 11-18 6:31 PM CST (00:31Z), window 32 min

- **Results first.** One more grade (all-time 2,027 bets / 1,095 events, -11.01%). 30 d is unchanged at -7.35%
  [-12.8, -1.9] until tonight settles. 21 games started and unsettled, none late.
- **No anomalies.** Every endpoint was inside budget: `live_all` 0.39 s, page 0.28 s. 18 plan reads (p95 128 ms).
- **Flow:**
  - plan 15.9 min old (newest write 00:15:40Z; max gap 16.3 min over 6 h): 219 suggested, 25 sized, 14 positions;
  - **46 `in_play_market_fair`** refusals (6 at 5:59 PM) as games go in play, so the sim-edge share fell to 0.70 from
    0.89. Expected in a slate;
  - 9 live ticks, 4 placed, 0 failed (3 `game_started`, 3 `already_held_venue_contract`, known guards);
  - orders today 63, all filled; nothing resting; unreconciled 0;
  - cap use 22.7% / 21.7%.
- **Unchanged:** gate clock BC-052 from 21:02:51Z, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z, its lane owes
  it).

## Reading 51 — Wed 11-18 7:03 PM CST (01:03Z), window 32 min

- **Results first.** No new grades; 30 d -7.35% [-12.8, -1.9]. 35 games started and unsettled, none late.
- **Anomalies: `live_today` 5.42 s (budget 3.0) and `page` 3.52 s (budget 3.0).** `live_all` was 2.16 s, inside its
  budget.
  - *Hypothesis, written first:* F14, web memory recycles under the slate.
  - **Confirmed:**
    - `/api/portfolio/live` finished at 01:03:19.4Z after 5,190 ms;
    - at 01:03:21.8Z pid 392526 was hard-recycled (1,202 MB against a 625 MB limit, 15 requests);
    - 0.1 s later pid 394203 also hit its hard limit (1,230 MB) and was **DEFERRED** by the double-recycle hold, so
      the hold worked as designed;
    - `/portfolio` took 3,460 ms across it.
  - **The slate rate:** 6 hard recycles from 00:43 to 01:03Z (about 18 an hour). Each worker lasts 10-20 requests,
    about 2-4 min.
  - **The peaks keep climbing:** 970-1,082 MB at 3 PM, 1,157-1,230 MB now. Both workers can be over the limit at the
    same moment, and the hold only orders their exits.
  - F14 updated, and the numbers were sent to `web-silent-worker-kills`.
- **Flow:**
  - plan 2.1 min old: **358 suggested** (the widest today), 25 sized, 12 positions;
  - **142 `in_play_market_fair`** refusals as the slate goes in play, so the sim-edge share fell to 0.56;
  - 8 live ticks, 3 placed, 0 failed;
  - orders today 66, all filled; unreconciled 0;
  - cap use 24.2% / 22.5%.
- **Unchanged:** gate clock BC-052, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z).

## Reading 52 — Wed 11-18 7:35 PM CST (01:35Z), window 32 min

- **Results first.** No new grades; 30 d -7.35% [-12.8, -1.9]. 44 games started and unsettled, none late.
- **No endpoint anomalies.** `live_today` 1.20 s (5.42 s last reading), `live_all` 1.02 s, page 0.84 s.
- **New: the first `rejected` order today.**
  - *Hypothesis, written first:* a maker-pilot post that expired, since the ledger marks those `rejected`.
  - **Wrong; benign anyway.** It was an **in-play** Kalshi NHL spreads entry, $2.95 requested, submitted 01:11:00Z,
    `error=venue_canceled` 11 s later. In-play entries are immediate-or-cancel, so an unfilled one comes back
    cancelled. Not a failure.
- **Watch: 1 in-play order still `submitted` at 4.1 min.**
  - Kalshi NBA h2h, $2.95, submitted 01:31:05Z, with a `venue_resolved_at` 1.3 s later but no fill or cancel status
    yet.
  - It is inside the 10-min unreconciled grace (unreconciled 1). An immediate-or-cancel order should not rest for
    minutes, so if it is still `submitted` at the next reading it is an anomaly.
- **Flow:**
  - plan 5.4 min old: 377 suggested, 25 sized, 14 positions; 167 `in_play_market_fair`; sim-edge share 0.52;
  - 8 live ticks, 0 placed (14 `outside_price_band`);
  - orders today 68 (66 filled, 1 rejected as above, 1 submitted);
  - cap use 26.9% / 22.5%.
- **F14:** the web-kills session re-checked reading 51's figures against the log and they hold: since the fix, 41
  restarts, 0 back-to-back, 9 holds, 0 kills. Its 9-hour heartbeat run found no worker near the stall lines.
- **Unchanged:** gate clock BC-052, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z).

## Reading 53 — Wed 11-18 8:08 PM CST (02:08Z), window 33 min

- **Results first.** 3 more grades: all-time 2,030 bets / 1,098 events, -11.04% [-18.3, -3.8]. 30 d is unchanged
  until tonight's date settles. 44 games started and unsettled, none late.
- **Watch item from reading 52: resolved.** The in-play Kalshi NBA order submitted at 01:31:05Z is now `filled`.
  Orders today: 68 = 67 filled + 1 rejected (the unfilled in-play IOC); resting 0; unreconciled 0.
- **No anomalies.** Every endpoint was inside budget: `live_today` 0.30 s, page 0.39 s.
- **Flow:**
  - plan 7.0 min old: 306 suggested, 25 sized, 12 positions; 122 `in_play_market_fair`;
  - 10 live ticks, 0 placed (5 `game_started`, 13 `outside_price_band`);
  - cap use 26.6% / 22.5%;
  - paper book 14,881 settled, -1.27%.
- **Unchanged:** gate clock BC-052, 0 of 800; 1 unclassified load (soccer ff 17:58:30Z).

## Reading 54 — Wed 11-18 8:39 PM CST (02:39Z), window 32 min

- **Results first.** Tonight's grades are landing: all-time 2,042 bets / 1,105 events (+12 bets / +7 events since
  reading 53), -10.99% [-18.3, -3.7]. The 30-day and 7-day windows move once 11-18 is a full graded date. 33 games
  started and unsettled (44 last reading), none late.
- **Gate:** 2 of 800 events (4 bets) since the BC-052 clock (21:02:51Z). These are the first graded games on the
  current clock.
- **No anomalies.** Every endpoint was inside budget: `live_today` 0.47 s, page 0.41 s.
- **Flow:**
  - plan 10.7 min old (newest write 02:29:16Z): 226 suggested, 25 sized, 11 positions; 84 `in_play_market_fair`;
  - 9 live ticks, 0 placed (4 `game_started`, 14 `outside_price_band`);
  - orders today 68 (67 filled, 1 unfilled in-play IOC); unreconciled 0;
  - cap use 26.5% / 22.4%;
  - paper book 14,893 settled, -1.25%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it).

## Reading 55 — Wed 11-18 9:11 PM CST (03:11Z), window 32 min

- **Results first.** All-time 2,050 bets / 1,108 events (+8 bets since reading 54), -10.96% [-18.2, -3.7]. 39 games
  started and unsettled (late starts joined; 33 last reading), none late.
- **Gate:** 2 of 800 events (5 bets) on the BC-052 clock.
- **No anomalies.** Every endpoint was inside budget: `live_today` 0.23 s, page 0.31 s.
- **Flow: the night is winding down.**
  - Tonight's plan was last written 02:53:02Z (19 min old). New plan writes (03:03:56Z) are for 11-19.
  - Tonight's plan: 183 suggested, 7 positions, 94 `in_play_market_fair`.
  - 11 live ticks, 1 placed, 0 failed.
  - Orders today 69 (68 filled, 1 unfilled in-play IOC); unreconciled 0.
  - Cap use 27.0% / 21.5%.
  - Paper book 14,964 settled, -1.24%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it).

## Reading 56 — Wed 11-18 9:42 PM CST (03:42Z), window 31 min

- **Results first.** All-time 2,076 bets / 1,117 events (+26 bets since reading 55), **-10.89%** [-18.1, -3.7].
  - 30 d: 1,606 bets, -7.33% [-12.8, -1.9].
  - 7 d: 402 bets, -2.54% [-13.2, +8.1] (one late grade of an earlier date).
  - 14 games started and unsettled (39 last reading), none late.
- **Gate:** 8 of 800 events (13 bets) on the BC-052 clock.
- **No anomalies.** Every endpoint was inside budget: books 1.33 s (budget 2.0, the slowest today outside recycles),
  plan 1.55 s, page 0.48 s.
- **Flow:**
  - tonight's plan 9.8 min old: 154 suggested, 14 positions, 86 `in_play_market_fair`;
  - the 11-19 plan writes are running (03:41Z);
  - 10 live ticks, 1 placed, 0 failed;
  - orders today 70 (69 filled, 1 unfilled in-play IOC); unreconciled 0;
  - cap use 27.1% / 21.0%;
  - paper book 14,986 settled, -1.25%.
- **Unchanged:** 1 unclassified load (soccer ff 17:58:30Z, its lane owes it).

## Reading 57 — Wed 11-18 10:13 PM CST (04:13Z), window 32 min

- **Results first.** No new grades since reading 56: all-time 2,076 bets / 1,117 events, -10.89%; 30 d -7.33%
  [-12.8, -1.9]. 14 games started and unsettled, unchanged, none late.
- **Program since reading 56 (on main):**
  - **S4 KILL**: Kalshi's in-play mid is the prior, and the NBA re-sim earns weight 0.00 on top of it (F19).
  - **S5 pre-registered and early-read**: the band map does not carry over (FIT's excluded .55-.70 band was the
    best in 11-01..11-17). The forward test, on bets >= 11-19 at 150 events, decides (F20).
- **No anomalies.** Every endpoint was inside budget: `live_today` 0.25 s, page 0.27 s.
- **Flow:**
  - plan 0.8 min old: 98 suggested, 8 positions;
  - 10 live ticks, 0 placed (4 `game_started`);
  - orders today 70 (69 filled, 1 unfilled in-play IOC); unreconciled 0;
  - cap use 27.1% / 21.0%;
  - paper book 15,042 settled, -1.17%.
- **Unchanged:** gate 8 of 800 on the BC-052 clock; 1 unclassified load (soccer ff 17:58:30Z).

## Reading 58 — Wed 11-18 10:44 PM CST (04:44Z), window 31 min

- **Results first.** One grade: all-time 2,077 bets / 1,118 events, -10.89%; 30 d -7.33% [-12.8, -1.9].
- **14 games started and unsettled**, the same count since 9:42 PM. None is past the 8 h late line. These are the late
  (West Coast) games in progress. If the count has not moved after midnight CST, it is checked.
- **No anomalies.** Every endpoint was inside budget: `live_today` 0.12 s, page 0.22 s. 17 plan reads in the window
  (p95 177 ms).
- **Flow:**
  - plan 7.5 min old: 89 suggested, 15 positions; 35 `in_play_market_fair`;
  - 10 live ticks, 1 placed, 0 failed (20 `game_started`, 4 `axis_held_live`);
  - orders today 72 (71 filled, 1 unfilled in-play IOC); unreconciled 0;
  - cap use 29.6% / 21.0%.
- **Unchanged:** gate 8 of 800 on the BC-052 clock; 1 unclassified load (soccer ff 17:58:30Z).
