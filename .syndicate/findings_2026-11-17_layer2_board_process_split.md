# Findings — lane `layer2-board-process-split` (2026-11-17, session cd252f56)

Asked by the rail monitor (session 62433e58, lane `layer2-rail-monitor`, I-20): in the live evening the Layer 2
board build runs 5-11x its calm wall against a 300 s today cadence. All fleet work here is READ-ONLY, at nice 19
(Windows side Idle). Central time = UTC-6.

## Hypotheses (written to the lane before any reading; commit `d61923c0f`)

- **H1 STARVATION (convoy):** the board thread's own CPU per build stays near calm, its share of the interpreter
  lock falls. Predicted board share <= 0.35 in an evening build (calm ~0.9+), process ~1.0 core.
- **H2 MORE WORK:** the board thread's own CPU per evening build >= 3x calm (>= 250 s).
- **H3 HOST:** the host starves the process (process CPU / wall < 0.8 core in evening builds).
- Falsifiers: H1 false if board share >= 0.6 or its CPU >= 3x calm; H3 false if process >= 0.9 core.

## Instruments

- `C:\tmp\l2split\l2s_sampler.sh`: per-thread `/proc/<pid>/task/*/stat` jiffies + state + `schedstat` (run ns,
  runqueue-wait ns) every ~1.4 s, bounded. **Writes to WSL-native `/tmp/l2split/`** — the first launch appended to
  `/mnt/c` every second and Windows Defender (MsMpEng) read ~2.4 cores while it ran, ~1.0-1.2 within a minute of
  stopping it (reading 2). The convoy lane's 11-16 sampler (`C:\tmp\railload\cost790_sampler.sh`) wrote to `/mnt/c`
  the same way, so its window carries that cost too.
- `C:\tmp\l2split\l2s_analyze.py`: joins samples with `BOARD_BUILD_TIMING` / `BUILD_SPAN_EXIT` (stage start =
  end - elapsed); per build and per stage: board-thread CPU, board / main / process share of a core.
- `C:\tmp\l2split\l2s_bench.py`: a fixed pure-Python loop every 30 s (nice 19): CPU-seconds per FIXED work. If it
  rises, each CPU-second does less work (clock / power limit / hypervisor preemption, which Linux under Hyper-V
  does not report as steal).

## Thread identity (refresh-worker pid 28948, booted 21:53:02Z = 3:53 PM CST on `91d865fd5`)

Python 3.11 sets no OS thread names, so the board thread was identified by START ORDER against the boot log, not
assumed. `/proc` thread start times run ~10 min fast against the log (the known WSL `btime` drift), but the
ORDER and 1-s spacing match exactly:

| tid | log line at boot | CPU since boot (read 01:21Z) |
|---|---|---|
| 28948 (main) | book-grid / in-play overlay tick (`run_refresh_worker.py` main loop) | 2,737 s |
| 29001 | `[intelligence_state] BACKGROUND_LOOP_START` 21:53:04.235Z = **the board loop** | 6,313 s |
| 29002 | `CHIP_PUBLISHER_THREAD_STARTED` 04.311Z (bootstrapped BY the board loop) | 425 s |
| 29004 | `[venue_odds_loop] LOOP_START` 04.644Z (started beside it) | 1,309 s |
| 29016 / 29017 | live evidence loop / memory heartbeat | 8 / 19 s |

The analyzer's own pick (most CPU over build spans, main excluded) agrees: 29001 (11-16: 3101899).

## Reading 1 — the convoy lane's 11-16 evening samples, re-cut per build and per stage

Window 01:00-04:00Z 11-17 (7:00-10:00 PM CST 11-16), pid 3101432, n 24 builds:
median wall 230 s, **board CPU 131 s, board share 0.58**, main 0.31, process 1.01.
The early-evening builds (23:55Z-01:42Z, from the convoy lane's own table): walls 345-942 s at board share 0.38-0.53;
board CPU per build 166-358 s.

Per stage (median over the window; calm reference 22:41Z 11-17: overview 1.4 s, shortlist 51 s, portfolio 12.6 s wall):

| stage | n | wall | board CPU | board share | main share |
|---|---|---|---|---|---|
| build_intelligence_overview | 17 | 20.7 s | 9.6 s | 0.36 | 0.37 |
| layer2_shortlist_build | 24 | 125.0 s | 74.3 s | 0.58 | 0.29 |
| portfolio_commit | 24 | 35.5 s | 23.8 s | 0.69 | 0.28 |

- Across builds, a slow stage's board CPU tracks its wall (r 0.92 overview, 0.93 shortlist, 0.82 portfolio) and
  barely tracks how busy the OTHER threads were (r 0.24 / 0.04 / 0.18).
- So the evening slowdown has TWO factors, not one: the board thread's lock share falls (0.9+ alone -> 0.36-0.69),
  AND its own CPU-seconds per build grow (overview 1.4 -> 9.6 s, shortlist ~51 -> 74 s median, 200 s max).
- **H1 PARTLY CONFIRMED** (share 0.36-0.69, not <= 0.35 as predicted; it is half the story). **H2 not yet
  separable** from CPU-second inflation: see reading 2.

## Reading 2 — tonight, 11-17 7:20-7:40 PM CST (01:20-01:40Z 11-18)

- Board builds since 00:26Z (6:26 PM CST): 185, 191, 173, 256, 208, 242, 226, 346 s, then **1,510 s** (01:05-01:30Z,
  7:05-7:30 PM CST: overview 91 s, shortlist 633 s, portfolio 226 s). The 1,510 s build began before any sampler ran.
- In the 157 s of that build the sampler saw: board 0.46 of a core (72 CPU-s), main 0.22, chip publisher 0.14,
  process 0.87; the board thread was runnable-but-not-on-a-CPU (schedstat wait) 9.8 s of 157 (6%).
- **Inside the WSL VM** over 10 s: 33% idle (~4 of 12 vCPUs free), steal 0, load1 16-18; 39% of CPU is nice-19 work
  (a research job `m3_launch.py save-fit`, 132%).
- **On Windows (the host the VM runs on)**, `Get-Counter`, 3 x 10 s at 7:36 PM CST: host **100% busy on all 12
  cores**, processor performance **56-60% of nominal** (Snapdragon X1E80100, 3,417 MHz nominal; 2,188 MHz read at
  7:2x PM). `vmmemwsl` (the whole fleet VM) 388-447% of one core; MsMpEng 94-117% (244% while the /mnt/c sampler
  ran); System 50-62%; the Windows-side Python jobs (10, all research / recorder) are ALL at Idle priority.
- So H3 as written (process < 0.8 core) is FALSE inside the VM (process 0.87-1.01), but the host IS saturated one
  level down: the VM's busy vCPUs (~7.8) get ~4 physical cores, and an Idle-priority job that does not preempt the
  fleet still costs it clock (all-core frequency at 56-64%).

### Reading 2b — the host, again, with the commands (8:05-8:06 PM CST 11-17)

Windows PowerShell, read-only, no admin:

```powershell
Get-Counter '\Processor Information(_Total)\% Processor Time','\Processor Information(_Total)\% Processor Performance',
  '\Processor Information(_Total)\Processor Frequency','\Process(*)\% Processor Time' -SampleInterval 10 -MaxSamples 1
Get-CimInstance Win32_Processor | Select Name, MaxClockSpeed, NumberOfCores      # X1E80100, 3,417 MHz, 12 cores
Get-CimInstance Win32_Battery | Select BatteryStatus, EstimatedChargeRemaining   # 2 = on AC, 80%
powercfg /getactivescheme   # Balanced; AC overlay (HKLM ...\Power\User\PowerSchemes ActiveOverlayAcPowerScheme) ded574b5-...
```

| 10 s sample (CST) | host busy | perf % of nominal | MHz | vmmemwsl (% of 1 core) | MsMpEng | System |
|---|---|---|---|---|---|---|
| 20:05:35 | 100% | 60 | 2,188 | 393 | 135 | 54 |
| 20:05:45 | 100% | 64 | 2,188 | 501 | 114 | 42 |
| 20:05:55 | 100% | 59 | 1,920 | 626 | 97 | 66 |

Summed by Windows priority class at 20:06:26 (10 s): vmmemwsl 643%, `remoting_network` 95% + `remoting_desktop` 19%
(a remote-desktop session), System 78%, MsMpEng 29%, Normal-class processes 85%, Idle-class 20%. So at this moment
the saturation is mostly the fleet VM itself plus System / remoting / Defender; the Idle-class research jobs were small.
Inside WSL at the same hour the rail monitor read load 8.6-10.1 with 2-3 vCPUs idle (its reading 14, 01:40Z) — the
clock is the cost every role pays, not the VM's vCPU count.

**Peer reading (rail monitor, reading 14, 7:39 PM CST; `findings_2026-11-17_layer2_rail_monitor.md`).** The 1,510 s
build's same window (01:11-01:40Z) had 21 BOOK_GRID_TICKs (60-80 in earlier windows), NBA / NCAAB / NHL grid build
p50 51.5 / 35 / 34 s, and web's in-play overlay merge stale on 19 of 36 lines. Two drains tonight (23:09-23:46Z,
01:08-01:28Z) never reached an idle worker: **a refresh-worker load in the live evening is not feasible**, so any load of
this change goes after the slate, and the first live evening after it is the reading.

## Reading 3 — tonight per stage, WSL-native sampler with `schedstat` (from 7:37 PM CST)

`build_intelligence_overview` for board date 11-18, 7:51:46-7:54:32 PM CST (01:51:46-01:54:32Z), **165.6 s wall**
(calm reference 1.4 s), 164 s of samples (`C:\tmp\l2split\l2s_span.py`):

| tid | thread | share of a core | runqueue wait (share of wall) |
|---|---|---|---|
| 28948 | main: book-grid / overlay tick | 0.41 | 0.03 |
| 29004 | venue odds loop (Kalshi / Polymarket; 85 `[kalshi_odds]` lines in the window) | **0.36** | 0.02 |
| 29001 | **the board loop** | **0.19** (30.8 CPU-s) | 0.03 |
| 29002 | chip publisher | 0.04 | 0.02 |
| process | | 1.02 | |

- **H1 CONFIRMED for this stage:** board share 0.19 <= the predicted 0.35, process at the one-core ceiling, and every
  thread's runqueue wait ~0.03 — the VM's CPUs were not the limit, the interpreter lock was. The two competitors, the
  tick and the venue odds loop (the latter started BY `start_intelligence_state_background_loop` beside the board),
  both stay in the parent under the split.
- The board's own CPU in that stage (30.8 s, vs 1.4 s wall calm) says work also varies by date / cache warmth
  (11-18's overview built 8 sports' contexts cold: ncaab 59 games, soccer 121). H2 stays open as a second factor.

## Baselines for the prediction (refresh-worker.log, `C:\tmp\l2split\l2s_baseline.py`)

| window | board builds | wall p50 / p90 / max | today shortlist publish gap p50 / p90 (gaps > 300 s) | NCAAB grid build p50 / p90 |
|---|---|---|---|---|
| 11-17 8 AM-3 PM CST (14-21Z) | 57 | 111 / 337 / 1,357 s | 188 / 1,132 s (15 of 52) | 4.6 / 15.0 s (n 253) |
| 11-17 5-8 PM CST (23-02Z) | 18 | 226 / 522 / 1,510 s | 334 / 972 s (9 of 16) | 8.5 / 30.8 s (n 163) |

The 23:30-23:33Z window carried a deploy drain (`ran=held reason=deploy_drain_requested`), so 16 cadence holds there are
not cost. The full evening (to 10 PM CST) is re-read after the sampler ends at 06:30Z.

## Design — the board loop in its own process (`pipeline/board_build_process.py`)

**What moves.** Only the board loop: `_INTELLIGENCE_STATE_SERVICE.start()` (the `syndicate-intelligence-state-loop`
thread and everything it runs: today cadence, carry-over, the canonical drain thread, Kalshi fast capture, the
heavy build incl. `portfolio_commit` and its paper-only inline execution). **What stays in the parent:** the book-grid /
overlay tick (main thread), the venue odds loop (`start_intelligence_state_background_loop` started it beside the loop;
the split starts it alone), the game-chip publisher (started by the parent; `SYNDICATE_GAME_CHIP_PUBLISH_ENABLED=0` in
the child makes the loop's `ensure_publisher_thread()` a no-op there), live evidence, memory watchdog/heartbeat, MLB
sim tick, odds jobs.

**Switch.** `SYNDICATE_BOARD_BUILD_PROCESS` (refresh-worker). Absent/off = `start_intelligence_state_background_loop()`
exactly as before. On = `python -m pipeline.board_build_process --serve` under a supervisor thread. POSIX only.
The one edit outside the new module: `scripts/run_refresh_worker.py`'s boot call site calls
`start_board_loop_for_refresh_worker()` instead (a loan from lane nfl-live-possession-map).

**How state and publication cross** (each found by the coupling survey, then checked in code):

| seam | today (one process) | split |
|---|---|---|
| board outputs (state, shortlist, shards, chips, ledger rows) | keyvalue store + data disk | unchanged — web already reads them there; the parent's readers (venue loop, Kalshi arb scan) read the store |
| MLB-sim gate `intelligence_pipeline_busy()` = `_execution_guard.locked()` | in-process lock | child guard holds an `flock` on `<reports>/board_process/board_build_busy.lock` while held; parent guard = probe of that flock. Unreadable = BUSY (the gate's own defer bound stops starvation) |
| `live_refresh_loop._PROCESS_STARTED_AT` (sim pointer staleness) | process boot | the ROLE's boot, passed in env — else a sim the parent started before the child reads `killed_by_restart` and the shared pointer is CLEARED (shown in a test) |
| `deploy_drain._PROCESS_BOOTED_AT` (drain honoured only if requested after boot) | process boot | the ROLE's boot — else a child (re)started mid-drain ignores the drain (shown in a test) |
| sim death certificates | owner = refresh-worker | child `SYNDICATE_MLB_SIM_TICK_OWNER=false` (observes only) |
| role memory (`SYNDICATE_LOCAL_MEMORY_ROOT_PID`) | parent pid | parent pid, set explicitly |
| heavy-build refusals -> recycle | parent counts, parent exits | counted in the child; the child recycles ITSELF (rc 75) on its own uptime; the parent's count stays 0. Behaviour change: a refusal streak restarts the board process, not the worker |
| execution ledger | CAS merge (`_persist`) | unchanged — already multi-writer (live-odds-worker writes it); board execution is `inline=True`, structurally paper-only |
| book-quote capture | `shard_append_lock` flock | unchanged — already cross-process |
| role log + stamps | fd 1 | child inherits fd 1/2 and `PYTHONPATH` (the `sitecustomize` stamp) |
| deploy safety | — | `check_deploy_safety.SERVICE_CHILD_CMDLINE_MARKERS` names the child, so it is not a job forever; an in-flight build still blocks through the log line-order check (same lines, same file) |
| shutdown record | parent's recorder | child installs its own (`refresh-worker-board`); if `SYNDICATE_REFRESH_LANE` is set both write the same record file (last wins; both lines are in the log) |

**What restarts.** A refresh-worker restart restarts both (same process group for the supervisor's killpg; stdin pipe
as lifeline: EOF -> the child SIGTERMs itself so its recorder names a killed build; a `getppid()` poll backs it up). A
child exit restarts only the child (5 s backoff doubling to 300 s, reset after 10 min up), so board code can load with
`kill -TERM <child>` without touching the parent's in-flight work. One builder: the child holds `LOCK_EX` on
`board_builder.lock` for life and waits for it before starting the loop.

**Costs, stated.** Up to ~+0.5 core of VM demand while builds run back to back (the board stops waiting on the lock
and actually runs) on a host already at 100% busy — reading 2. +1 interpreter (~80 MB at import measured on Windows;
the board's working set moves with it, it is not duplicated). Not addressed by this change: the host's own saturation
and clock (56-64% of nominal), which inflate every CPU-second on the fleet.

## Open

- The fixed-work benchmark across the slate and into the calm hours (separates CPU-second inflation from real work).
- Tonight's per-stage reading with `schedstat` (WSL-native sampler from 01:37Z, to 06:30Z).
