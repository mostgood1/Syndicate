# Findings 2026-11-18: far-dated soccer builds cost the Layer 2 board ~2-3% per build, and `nice` cannot buy it back (todo #849)

Lane `board-build-priority`, session b2be7822. The lever is L-d from the rail monitor
(`findings_2026-11-18_layer2_rail_monitor.md` readings 3, 4, 8, 9, 12), recorded as #849 by lane
`product-optimization-program`.

**Verdict: do not build the `nice` switch** (§4). The builds cost the evening board about 6 s per build and about
19 s of a 371 s mean publication gap. The cost is a slower CPU-second, not waiting: the board waits for a CPU 0.5-0.7%
of its time with or without them, so a lower priority has nothing to give back.

Substrate: **fleet**. All reads were read-only, at `nice 19`, from 7:16 to ~7:55 PM CST on 11-18:
- refresh-worker role logs `~/syndicate-prod/logs/refresh-worker.log{,.1,.2}` (11-16 6:37 AM to 11-18 7:16 PM CST);
- run manifests `~/syndicate-prod/data/reports/migration_runs/2026-11-18/odds_refresh_<stamp>/refresh_and_gate_run.json`;
- `/proc/<board child>/task/*/schedstat`, `/proc/pressure/cpu`, `/proc/loadavg` (WSL, 12 vCPUs).

Scripts and data: `C:\tmp\bbp_849\` (`overlap.py`, `cycle.py`, `sched_sample.py`, `join_win.py`, `runs.py`, `m3.sh`,
`sched_corun.json`, `win_counters.csv`). The hypothesis was written into the lane before the first fleet read
(lane `board-build-priority`, commit `dcf557947`).

## 1. The launcher (H1: CONFIRMED)

The three nice-0 builds the rail monitor saw are **refresh-worker's soccer weekly autorun**
(`scripts/run_refresh_worker.py` `_launch_autorun_soccer_weekly_refresh`), one league-date unit per launch.
They are not the #840 look-ahead, which since `640c6d4fd` builds only `--date <tomorrow>`.

| rail monitor saw (CST) | `SOCCER_UNIT_LAUNCHED` (UTC) | pid | manifest command |
|---|---|---|---|
| 4:22 PM eredivisie 11-22 | 22:22:02Z `eredivisie\|2026-11-22` | 282290 | `--sports soccer --phase live --soccer-leagues eredivisie --soccer-date 2026-11-22` |
| 4:55 PM championship 11-24 | 22:54:55Z `championship\|2026-11-24` | 290890 | `... --soccer-leagues championship --soccer-date 2026-11-24` |
| 6:14 PM epl 11-23 | 00:14:01Z `epl\|2026-11-23` | 342046 | `... --soccer-leagues epl --soccer-date 2026-11-23` (state `failed`) |

- The autorun has 30 units (`SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`), a 14,400 s per-unit interval and 300 s launch
  spacing. So a unit can start every ~5 min all day, evening included.
- Of 391 confirmed units in the logs (11-16..11-18), **387 were dated today+2 or later**. Only 4 were today or tomorrow.
- Launch-to-write time per far unit: p50 64 s, p90 197 s, max 3,309 s.

## 2. What co-running costs the board (measured)

Method: each `BOARD_BUILD_TIMING` line gives a build's end, wall and CPU, so the window is `[end - wall, end]`. Each
`SOCCER_UNIT_CONFIRMED` line gives a unit's `[launched_at, wrote_at]`. For every build, `f_far` is the share of its wall
time that overlapped a unit dated today+2 or later. The comparison is **within the same Central hour** (each hour is
demeaned), so the day's load curve and slate size are held fixed. Units launch on their own 5-min clock, not the
board's, so overlap is close to random within an hour.

| window | builds | mean wall | mean `f_far` | wall per FULL overlap | off-CPU s per full overlap | mean cost per build |
|---|---|---|---|---|---|---|
| all hours, 11-16 6:36 AM .. 11-18 7:02 PM | 762 | 164 s | 0.232 | **+12.9%** [+5.6, +20.2] (+22.1 s [+5.3, +38.9]) | -1.3 s [-3.7, +1.0] | **3.0% = 4.9 s** |
| evenings 5-11 PM, same span (3 evenings) | 136 | 254 s | 0.120 | +20.2% [-6.7, +47.1] | -2.2 s [-10.2, +5.8] | **2.4% = 6.1 s** |
| post board split only (from 11-18 2:31 AM) | 193 | 184 s | 0.196 | +5.9% [-12.1, +24.0] | +2.5 s [-0.2, +5.3] | 1.2% = 2.1 s |

Brackets are 95% CIs (OLS on hour-demeaned values; residual dof = n - hours - 1).

- **Size of the soccer load (H3: holds):** far units were busy 0.258 of the 60.4 h span (one process at a time), and
  **0.129 of one core** over the three evenings (8,333 s in 18 h). The host has 12 vCPUs at load 6-10 in the evening.
- **The cost is CPU time, not waiting:** a co-running unit adds about as many board CPU-seconds (+23.4 s [+6.0, +40.7])
  as wall seconds (+22.1 s), and the board's off-CPU time does not move. So the board is not queued behind the soccer
  build. Its CPU-second gets slower: clock, cache or memory bandwidth, which the 11-17 learnings already measured on
  this host (Windows 100% busy at 56-64% of nominal clock).
- **The estimate is an upper bound.** A unit's own duration stretches under load, so within an hour its overlap is
  larger exactly when the host is busier. That pushes the coefficient up.
- **Against the target:** the evening's 6.1 s per build is 2% of the 300 s cadence target, and well under 1% of the
  11-17 peak (1,254-1,510 s).

### 2a. The publication gap (the rail monitor's point, ~7:40 PM CST)

The rail monitor pointed out that `BOARD_BUILD_TIMING` wall understates the board's real cycle. Each cycle also runs a
`LAYER2_TODAY_CADENCE` step, so the cadence a viewer sees is the gap between two publications. The same within-hour test
on that gap (`C:\tmp\bbp_849\cycle.py`; gaps over 1,800 s dropped as outages, 6 of 764):

| measure | window | n | mean | per FULL far overlap | mean cost |
|---|---|---|---|---|---|
| publication gap | all hours | 755 | 266 s | +14.0% [+4.5, +23.5] (+41.5 s) | 3.4% = 8.9 s |
| publication gap | evenings 5-11 PM | 134 | 371 s | +36.0% [+4.4, +67.5] (+131.8 s) | **5.2% = 19.4 s** (CI about 2-37 s) |
| `LAYER2_TODAY_CADENCE` elapsed | all hours | 30 | 336 s | +37.7% [-28.8, +104.1] | too few to read |

- **So the cost is larger on the gap than on the build:** about 19 s of an evening's 371 s mean gap.
- **Removing far-dated units from the evening entirely** would bring that mean to about 352 s. That is still above the
  300 s target, and no closer to the 1,254-1,510 s peaks.

## 3. Why `nice 10` cannot recover it (H2: see the scheduler reading)

`nice` changes only how Linux shares ONE runqueue among runnable tasks. With 12 vCPUs and a load of 6-10, a niced
soccer build still gets an idle vCPU, runs at the same speed and draws the same power. `nice` also does not reach the
Windows side, where the clock is set.

**Scheduler reading, 7:20-7:29 PM CST (no soccer unit running), 9 min at 2 s:** board child pid 363665 at 0.93 cores while
building. Its **run-delay share was 0.007** (time runnable but waiting for a CPU, over run + wait). PSI cpu `some` was
0.018 and load 5.7. So the most any priority change on any other process can give the board is about 0.7% of its time.

### 3a. The co-run reading (7:40-7:53 PM CST)

The same sampler ran for 13 min (`sched_corun.json` in `C:\tmp\bbp_849\`). Two far units ran inside it at nice 0:
`--league bundesliga --date 2026-11-22` and `--league la_liga --date 2026-11-22`. A Windows `Get-Counter` sampler
ran beside it at 5 s (`win_counters.csv`, joined by `join_win.py`).

| 2 s intervals while the board was building | n | board cores | board run-delay share | PSI cpu some | load |
|---|---|---|---|---|---|
| a soccer unit running (> 0.5 core) | 60 (120 s) | 0.96 | **0.007** | 0.017 | 5.1 |
| no soccer build | 209 (418 s) | 0.91 | **0.005** | 0.017 | 4.6 |

- **H2(b) holds:** with a nice-0 soccer build beside it, the board waited for a CPU 0.7% of its time, against 0.5%
  without one. A priority change on the soccer build can give back at most that 0.2 pp.
- **Windows side, 5 s samples (descriptive; one window, and other load moves too):**
  - with a soccer unit: n 28, Windows 72.2% busy at **67.5%** of nominal clock;
  - without: n 127, Windows 55.0% busy at **74.8%**.
  - That fits §2: one more busy core lowers the clock every core runs at. `nice` inside WSL does not change that.

## 4. Verdict: do not build the `nice` switch

- **H1 confirmed, H2 holds, H3 holds.**
- **Far-dated soccer units do cost the board something, but it is small:**
  - about 6 s per evening build (2.4%);
  - about 19 s of an evening's 371 s mean publication gap (5.2%, CI about 2-37 s).
- **The cost is a slower CPU-second, not waiting.** On 12 vCPUs at a load of 5-10, the board waits for a CPU 0.5-0.7%
  of its time with or without a soccer build. `nice 10` would leave the build on its own vCPU, at the same speed and
  power, so it buys about nothing. It would still have to be classed a betting change: a niced build can finish later
  under contention, and that delays the inputs the priced sims read for those dates (learnings 11-18). Spending a
  window slot, and restarting the gate's 800-event count, on a change predicted to do nothing is not worth it.
- **The only lever that could recover the cost is less concurrent work in the window:** for example, holding units dated
  today+2 or later out of 5-11 PM CST.
  - It is worth at most about 19 s of evening publication gap (371 -> ~352 s mean). It does not reach the 300 s target
    or touch the 1,254-1,510 s peaks.
  - It delays inputs for those dates by up to ~6 h, so it IS a betting change.
  - Not recommended on its own. It is the user's call if they want it in a window batch.
- **Where the board's load-tracking really comes from:** far units are 0.13 of a core of an evening load of 6-10. The
  rest is today's live work: live odds sweeps, the NHL odds child, re-sim workers, live-odds-worker, web. Add the Windows
  side (11-17 learnings: vmmemwsl, MsMpEng) and the host's own clock. From §2, each co-running busy core costs the
  board about +13% [+5.6, +20.2] per build. So the lever is fewer busy cores in the evening, of any kind. That
  includes research jobs, which nice 19 keeps out of the runqueue but which still slow the clock.

## 5. Pre-registered predictions (2026-11-18 ~7:55 PM CST, before anything is built or loaded)

For anyone who builds either lever later. Readings come from the evening's refresh-worker log, 5-11 PM CST, with the
host load stated beside them.
- **P1, `nice 10` on far-dated units:** the board's run-delay share stays 0.005-0.008. The evening board build wall and
  publication gap move by less than 2% (|delta| < 5 s on the build, < 8 s on the gap) against the same weekday's
  baseline. That is inside the noise.
- **P2, holding far-dated units out of 5-11 PM CST:** the evening mean publication gap falls by about 19 s (5%), with
  80% of outcomes between 0 and 37 s. The build wall falls by about 6 s. The share of evening gaps over 300 s falls by
  under 5 pp.
- **Betting-change classification:** this lane built and loaded NOTHING, so it is not a betting change. P1 or P2, if
  built and switched on, would be `yes` (each delays priced inputs for dates today+2 and later).
