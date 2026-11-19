# Findings -- board-split memory guard (lane `board-split-memory-guard`, todo #850)

Opened 2026-11-19 ~04:10Z (10:10 PM CST 11-18) by session 1f9c9a40, a side session of local_62433e58 (lane
`layer2-rail-monitor`). Every fleet read below is READ-ONLY (`nice -n 19`): `~/syndicate-prod/logs/refresh-worker.log`
and `.log.1`, `/proc` of the live refresh-worker tree, and the role env. Times are CST (UTC-6), with UTC where it
matters. Scripts: `C:\tmp\bmg\` (`bmg_series.py` = the per-minute series, `bmg_sum.py` = the hourly table).

## 1. What happened on 11-18 (the first live evening under the board split, BC-042)

- `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900`, per UTC hour from 15Z 11-18:
  17Z 1, 21Z 2, 22Z 2, **23Z 7, 00Z 5, 01Z 5, 02Z 3, 03Z 6** (to 03:53Z). That is **26 in 5-10 PM CST** (5.2 an hour).
  The 11-17 evening, in-thread, 23Z-05Z: **0**.
- **4 child recycles** (`[worker_recycle] RECYCLE_EXIT reason=heavy_build_refused ... threshold 3`):

  | CST | UTC | pid | child uptime |
  |---|---|---|---|
  | 6:29:18 PM | 00:29:18Z | 152953 | 31,813 s |
  | 7:52:39 PM | 01:52:39Z | 363665 | 4,955 s |
  | 8:42:57 PM | 02:42:57Z | 477538 | 2,977 s |
  | 9:25:30 PM | 03:25:30Z | 549989 | 2,518 s |

  The interval between recycles shrank: 83, 50, 42 min.
- **4 of 4 exited rc -6**, each logging `Fatal Python error: _enter_buffered_busy: could not acquire lock for
  <_io.BufferedReader name='<stdin>'> at interpreter shutdown, possibly due to daemon threads` after `RECYCLE_EXIT`.
  Each was respawned 5 s later (attempt=2..5).
- Gaps between consecutive `BOARD_BUILD_TIMING` lines from 5 PM CST on 11-18: n 28 (29 builds), p50 543 s,
  **max 1,580 s (26.3 min)**, 5 of 28 over 900 s. The respawned children's cold first builds ran 359-526 s.

## 2. Where the memory is (the cause)

The guard (`intelligence_state._abort_if_memory_critical`) reads `memory_headroom_snapshot(1,900 MB)`. On the fleet,
with no cgroup ceiling, that is the declared `SYNDICATE_LOCAL_MEMORY_LIMIT_MB=7168` minus the RSS of the ROLE TREE
(`SYNDICATE_LOCAL_MEMORY_ROOT_PID` = the parent, so parent + board child + any job). `basis=reclaimable_cache` only
means no `memory.stat` is read; nothing is credited back. The guard refuses once the tree passes 7,168 - 1,900 =
**5,268 MB**.

**Is RSS miscounting the child?** No. The 03:52Z reading gave:
- parent 152916: RSS 2,254 MB, anon 2,215, PSS 2,220;
- child 613542: RSS 3,123 MB, anon 3,061, PSS 3,072.

RSS over PSS is 85 MB of 5,377 (1.6%). The memory is real anonymous memory, not shared pages counted twice.

**Per CST hour** (`ALL_PROCESS_MEMORY`, every 60 s, n about 60 an hour; parent / child / tree p50 in MB; refused
= minutes with headroom under 1,900):

| hour | parent | child | tree | tree max | minutes refused |
|---|---|---|---|---|---|
| 11-17 7 PM (in-thread) | 4,266 (whole worker) | - | 4,343 | 5,207 | 0/60 |
| 11-17 9 PM (in-thread) | 4,572 | - | 4,595 | 5,192 | 0/60 |
| 11-18 3 AM | 746 | 2,914 | 3,838 | 4,391 | 0/61 |
| 11-18 noon | 977 | 3,742 | 4,879 | 5,366 | 2/61 |
| 11-18 3 PM | 1,020 | 3,854 | 4,943 | 5,763 | 10/60 |
| 11-18 5 PM | 1,100 | 3,942 | 5,054 | 5,611 | 18/60 |
| 11-18 6 PM | 1,598 | 3,446 | 4,919 | 5,762 | 22/60 |
| 11-18 7 PM | 1,881 | 3,405 | 5,301 | 5,800 | 33/60 |
| 11-18 8 PM | 1,984 | 2,706 | 4,714 | 6,045 | 16/59 |
| 11-18 9 PM | 2,167 | 2,932 | 5,216 | 6,194 | 24/54 |

Three findings, each with its denominator:
1. **The split added a second interpreter.** The parent's calm RSS (3-11 AM CST 11-18, with a child running) was
   p50 **777 MB** (p10 698, p90 1,193; n 476). That is the base a process pays to import this code and warm its
   module caches, and the child pays it again. At matched evening hours the tree is about 0.4-0.9 GB above the
   in-thread worker of 11-17.
2. **The parent grows in the evening.** p50 1,100 MB at 5 PM -> 2,167 MB at 9 PM (+1,067 MB). The parent runs the
   book-grid / in-play overlay tick, the venue odds loop and the chip publisher; the child did not grow over the
   same hours. The in-thread worker of 11-17 grew +1.4 GB over 4-9 PM, so this growth is the tick side, not new.
   - It is never trimmed: all 696 `MALLOC_TRIM` lines since 09Z 11-18 carry one of five board-build guard reasons,
     so they come from the child.
   - In the child, a trim releases p50 250-290 MB (`pre_build_candidate_pool_start_guard` n 198, p50 250 MB;
     `post_layer2_fast_refresh` n 47, p50 290 MB).
   - Whether the parent's +1.1 GB is trimmable, freed heap is NOT measured: that needs a trim in the live parent.
     The parent-trim switch below measures it on its first evening.
3. **A child recycle cannot return the parent's memory.** A child starts small, so the first build after a respawn
   passes the guard (cold, 359-526 s). Its working set then returns to about 2.9 GB, and with the parent still
   growing, refusals resume. That is why the recycle intervals shrank, 83 -> 50 -> 42 min. Each recycle buys one
   publication for one cold build.

**Is the 1,900 MB floor right for the stage?** It was sized for the overview pass's transient, and it still roughly
is. The child's RSS rise from a build's start to its peak, sampled at 60 s, over n 101 builds (9:40 AM-9:53 PM CST):
p50 4 MB, p90 259 MB, **max 1,136 MB** (a cold build after a recycle: +1,026 MB). The 2 s watchdog of 2026-09-12/13
measured up to +1,416 MB, and 60 s sampling under-reads a peak. So the floor carries a 1.3-1.7x margin over the
largest measured stage cost. **It is not lowered.** What changed is not the stage but the accounting: one more
interpreter in the tree that the floor is measured against.

**The VM can afford a credit.** WSL is 15,746 MB total, with 6,811 MB available at 03:52Z (`free -m`) and 4 GB of
swap. The declared role ceilings are web 2,048 + live-odds 3,072 + refresh-worker 7,168 = 12,288 MB. With a 768 MB
credit they are 13,056 MB, plus redis (258 MB RSS).

## 3. The exit (rc -6) -- H2 CONFIRMED

`_start_lifeline`'s daemon thread blocks in `sys.stdin.buffer.read(1)`. At interpreter shutdown, closing `sys.stdin`
needs that BufferedReader's lock, and CPython aborts. Reproduced outside the fleet with the fleet's own interpreter
(Python 3.11.16, a throwaway script with stdin held open, then `sys.exit(75)`):
- buffered read: rc 134 (SIGABRT, = Popen rc -6);
- `os.read(0, 1)`: rc 75.

Windows Python 3.11.9 gives the same split (buffered crashes with 0xC0000005; raw exits 75). The respawn happened
anyway, so the cost was the crash capture and a misleading `reason=exit`, not extra board time.

## 4. The fixes -- on main, each DEFAULT-OFF (absent = the split as loaded at BC-042)

All are in `pipeline/board_build_process.py`, on a loan of three regions from lane `layer2-board-process-split`, plus
a read-only accessor in `worker_recycle.py`. Tests: `tests/test_board_split_memory_guard.py`. They are 33 tests, each
switch reachability-tested off != on through the real code path. They pass with
`tests/test_board_build_process_split.py`: 60 passed under the fleet's Python 3.11.16 and 33 + 47 on Windows.
`test_memory_observability*` and `test_intelligence_overview_memory_guard` pass too (58).

| switch (`REFRESH_WORKER__` prefix in `local_production.env`) | does | proves it loaded |
|---|---|---|
| `SYNDICATE_BOARD_PROCESS_RAW_LIFELINE=1` | the lifeline reads fd 0 with `os.read`; a recycle exits 75 | `BOARD_PROCESS_EXITED ... rc=75 reason=recycle`; 0 `Fatal Python error` |
| `SYNDICATE_BOARD_PROCESS_CEILING_CREDIT_MB=768` | in process mode only, the parent adds 768 MB (the measured p50 second-interpreter base) to the declared ceiling before spawning the child; both processes' gates read 7,936 | `BOARD_PROCESS_CEILING_CREDIT from_mb=7168 to_mb=7936`; `ALL_PROCESS_MEMORY` `container_memory_max_mb: 7936.0` |
| `SYNDICATE_BOARD_PROCESS_PARENT_TRIM_SECONDS=300` | the parent `malloc_trim`s every 300 s, with no gc (11-66 ms per trim in the child's lines) | `MALLOC_TRIM {... "reason": "board_split_parent_periodic"}` |
| `SYNDICATE_BOARD_PROCESS_RECYCLE_AFTER_BUILD=1` | right after a completed build, if the next build would be refused (the guard's own snapshot and floor, re-read under the build guard after a trim), the child takes the build guard and exits 75. The respawn's cold build then starts right after a publication, not after 3 refused cycles. | `BOARD_PROCESS_RECYCLE pid=... reason=post_build_headroom` |

The post-build recycle holds in these cases:
- `transient_jobs`: the parent + child pair alone leaves the floor free, so someone else's odds or sim job made the
  shortfall;
- `min_uptime`: under 1,800 s, the existing minimum;
- `children_running` / `children_unknown`;
- `drain_requested`;
- `disabled`: `SYNDICATE_REFRESH_WORKER_RECYCLE_AFTER_REFUSALS=0` turns this off too.

The refusal-streak recycle stays as the fallback. Simulated on 11-18's own 5-10 PM minutes, the share of minutes
over the guard's line would have been:

| credit | minutes over the line |
|---|---|
| 0 | 113 of 293 |
| 512 MB | 5 of 293 |
| 768 MB | 2 of 293 |
| 1,024 MB | 0 of 293 |

768 is the measured median, not a fit to that table.

## 5. PRE-REGISTERED PREDICTION -- the first live evening after all four keys load (written 2026-11-19 04:17Z = 10:17 PM CST 11-18, before any load)

Window: 5-10 PM CST of the first evening after the load (23:00-04:00Z). The baseline is 11-18's same window (§1).

| # | metric | 11-18 baseline | predicted | falsified if |
|---|---|---|---|---|
| P1 | `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` per UTC hour | 7/5/5/3/6 = 26 | <= 1 in every hour, <= 3 total | > 2 in any hour, or > 6 total |
| P2 | child recycles (`BOARD_PROCESS_EXITED`) and their rc | 4, all rc -6 | <= 2, all rc 75 `reason=recycle` | any rc -6 or any `Fatal Python error` |
| P3 | longest gap between consecutive `BOARD_BUILD_TIMING` lines | 1,580 s; 5 of 28 > 900 s | <= 900 s; <= 1 gap > 900 s | > 1,200 s |

- Load checks, which must hold first or the reading is VOID: `container_memory_max_mb: 7936.0` in
  `ALL_PROCESS_MEMORY`, `BOARD_PROCESS_CEILING_CREDIT` in the log, and
  `BOARD_PROCESS_CHILD_SWITCHES raw_lifeline=1 recycle_after_build=1 ceiling_credit=7168+768`.
- Each metric's verdict is PREDICTED, FALSIFIED or NEITHER.
- **Exploratory, not pass/fail:**
  - parent RSS p50 at 9 PM CST vs 11-18's 2,167 MB;
  - parent-trim `rss_released_mb` p50 (n);
  - post-build recycles vs streak recycles;
  - refresh-worker tree max vs 11-18's 6,194 MB.
- **Comparability:** state live games at 7 PM CST (NCAAB + NBA + NHL + NFL). If it is under 70% of 11-18's count (as
  the 10:15 PM 11-18 board-split reading reports it), the reading is CONFOUNDED.
- Any refresh-worker restart, drain or deploy in the window is named. A restart resets the parent's growth and makes
  P1-P3 easier, so a reading with one in the window is CONFOUNDED.
- **Safety:** refresh-worker tree max <= 7,936 - 1,000 MB (= 6,936); 0 OOM kills in `dmesg`/the role log; WSL
  `MemAvailable` >= 1,500 MB at the evening's minimum.

## 6. The load -- the user's decision

- **It is a betting change by BC-042's own rule.** BC-042 was classified yes because "the portfolio plan's cadence
  follows the board build, and live-odds-worker executes that plan". These switches change that cadence (fewer
  refused builds, shorter gaps), so `--betting-change yes`.
  - The brief from the rail session assumed "not a betting change (board cadence)". Cadence is exactly what BC-042
    was counted for, so this says yes; the user decides.
  - The RAW_LIFELINE switch alone only changes an exit code and is not a betting change.
- **Window:** outside every window (`betting_change.py window`; next 2026-11-24 08:00-13:00Z = Tue 2-7 AM CST).
  - **Option A, recommended:** load 11-19 in a calm midday slot, outside the window, with
    `--outside-window "broken money path: since BC-042 the board refuses builds 5/h in the live evening; 26-min
    plan gaps; this restores BC-042's own cadence"`.
    - The gate clock was at 8 of 800 on BC-052 (portfolio-monitor reading 56), so a restart costs about 8 graded
      events.
    - It is one ff to the exact SHA, the four `REFRESH_WORKER__` keys in `local_production.env`, and a drained full
      down/up. That is an env change, so it needs three claims and a joint preflight CLEAR from a worktree at
      origin/main.
  - **Option B:** queue for the 11-24 window, where the four keys join that night's batch down/up. The cost is five
    more evenings of 16-26-min gaps (11-19..11-23).
- **Rollback:** delete the four keys and do a drained down/up. Each key is independent.
