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

- **Addendum from the rail monitor** (lane `layer2-rail-monitor`, reading 21, read 10:09 PM CST; by message 11-19
  ~04:25Z; not re-read here):
  - a **5th recycle at 9:58:38 PM**, child 613542 at 1,960 s uptime, rc -6 again. The intervals are now
    83 / 50 / 42 / 33 min.
  - Headroom at the 3 refusals before recycles 2-5: 1,545-1,867 MB. The tree was 5.30-5.62 GB at each refusal.
  - Each new child is back at 2.40-2.88 GB 9-15 min after its respawn, while the parent held ~2.0-2.3 GB.
  - Board publication gaps around the 5 recycles: 26.3, 16+, 22, 17 and 15.7 min.
  - This is finding 3 below, measured from the other side. The 5-10 PM refusal total is therefore >= 26: my count
    stops at 03:53Z, and the 5th recycle's streak ended after it.
  - The suggested-picks lane's refresh-worker restart after 10:31 PM resets the parent, so 11-19's evening starts
    from a fresh baseline without the fix.

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

## 7. READING 1 -- the first evening after the load, 11-19 5-10 PM CST (23:00-04:00Z), against §5

Taken by the rail monitor (lane `layer2-rail-monitor`, `findings_2026-11-19_layer2_rail_monitor.md` reading 22, main
`6b9e9e9f0`). The P1-P3 counts and the post-build checks were re-derived here from `refresh-worker.log{,.1}` at
04:06Z 11-20, read-only (`C:\tmp\bmg\load\read1.sh`); they match.

| # | 11-18 | 11-19 evening | predicted | verdict |
|---|---|---|---|---|
| P1 refusals per UTC hour 23/00/01/02/03Z | 7/5/5/3/6 = 26 | 0/0/0/2/2 = **4** | <= 1 every hour, <= 3 total | **NEITHER** (over the prediction, short of > 2 in an hour or > 6 total) |
| P2 child exits | 4, all rc -6 | **0** exits, 0 `RECYCLE_EXIT`, 0 `Fatal Python error` | <= 2, all rc 75 | **PREDICTED** |
| P3 longest gap between `BOARD_BUILD_TIMING` lines | 1,580 s; 5 of 28 > 900 s | **807 s**, then 662 and 585 s; 0 of 53 > 900 s (54 builds) | <= 900 s | **PREDICTED** |

- **P1 detail.** The 4 refusals were at 02:42:11, 02:43:19, 03:05:53 and 03:07:01Z, with headroom 1,898 / 1,885 /
  1,785 / 1,886 MB against the 1,900 floor. Each pair of refusals was 68 s apart, and the next attempt built; no
  refusal streak reached 3.
- **Load checks: MET.** `CHILD_SWITCHES raw_lifeline=1 recycle_after_build=1 ceiling_credit=7168+768`; the ceiling
  reads 7,936.
- **No confound from the fleet:** no restart, drain or deploy in the window. Parent 1011283 has been up since
  17:00:29Z, and the fleet ran `38c3a6905` all day.
- **CONFOUNDED by the slate, under §5's own 70% rule.** Live NCAAB + NBA + NHL + NFL was 21 at 7:06 PM (28 at
  7:31 PM), against 46 at 7:06 PM on 11-18: 46% (61%). So P1-P3 are recorded, but they cannot pass the prediction.
- **Safety: MET.** Tree max 6,295 MB <= 6,936; 0 OOM lines; `MemAvailable` 6.47 GB at 10:03 PM (the evening's
  minimum was not sampled).
- **Exploratory:**
  - **Parent RSS:** 785 MB (11:23 AM), 1.04 GB (6:15 PM), 1.55-1.60 GB (9 PM; 11-18: 2,167 MB), 1.52 GB (10:03 PM).
  - **Parent trims:** 60 in the window, released p50 142 MB, max 258 MB. That is freed heap the parent never
    returned before the switch. The parent's 9 PM figure is ~0.6 GB under 11-18, but the slate was lighter, so
    the trim's share of that is not separable.
  - **Child:** 4.35-4.57 GB. It was never recycled (up ~10.6 h at 03:45Z); on 11-18 the child was recycled from
    6:29 PM on.
  - **Post-build recycles: 0.** All 4 `BOARD_PROCESS_POST_BUILD_CHECK` lines were `held=transient_jobs`, with
    `pair_rss_mb` 5,857-6,009, i.e. 27-180 MB under the 6,036 MB line. The rest of the tree (odds and other
    jobs, ~260-290 MB) took headroom to 1,641-1,793 MB.
  - **Streak recycles: 0.**
  - **Board cadence (rail monitor), 5:30-10:03 PM:** 31 publications, gap median 313 s, max 585 s. On 11-18 the
    median was 572 s and the max 26.3 min.
- **What the shape says.**
  - The design did what it says: no crash exits, no 3-refusal streaks, no gap over 15 min. The 4 refusals each
    cost one 68-s retry.
  - **Lead (not built):** the `transient_jobs` hold uses a 0 MB margin. But the "transient" jobs recur through
    every evening cycle, so the board pair sat a few tens of MB under the line while the tree kept tipping over
    it. A margin equal to the evening's typical other-process RSS (~300 MB) would let the post-build recycle
    reset the child before those near-misses. The child's own 12-hour ratchet (4.4-4.6 GB) is the larger half
    of the pair now.
  - Either change is a betting change, by the same rule as BC-053.
- **Owed:** the same §5 thresholds on the next evening that passes the 70% slate rule (>= 33 live NCAAB + NBA +
  NHL + NFL at 7 PM CST), with no restart in the window. Until then the lane's goal is NOT MET.

## 8. Since the load, to 2026-11-20 9:28 AM CST -- the parent's ratchet (written 15:35Z 11-20, before the 11-20 evening)

Read-only, from `refresh-worker.log{,.1}` (scripts `C:\tmp\bmg\load\since_load.sh`, `fatal_after*.sh`).

- **Exits since the load: 1**, at 05:58:33Z 11-20 (11:58 PM CST 11-19): `RECYCLE_EXIT reason=heavy_build_refused`
  after 3 refusals, then `BOARD_PROCESS_EXITED rc=75 reason=recycle`. That is the RAW_LIFELINE fix working: a
  clean exit where 11-18 had 4 of 4 SIGABRTs.
  - "Fatal Python error" does appear twice in the log after the load, at 04:33:47Z. Both are inside an
    `ALL_PROCESS_MEMORY` line: the cmdline of another session's `grep "Fatal Python error" ...` that was running
    at the time (memory note: the heartbeat quotes greps).
  - **0 real fatal errors since the load.**
- **Refusals** after the 11-19 window:
  - 04Z 2, 05Z 5 (10-11:59 PM CST): the streak that recycled the child at 05:58Z;
  - 13Z 1 (7 AM CST).
- **Post-build checks: 11 of 11 `held=transient_jobs`** (02:50Z-05:52Z), with pair 5,825-6,009 MB against the
  6,036 MB line. **The post-build recycle has never fired.** The only recycle was the 3-refusal streak's.
- **The parent does not come back.**

  | when (CST) | parent RSS |
  |---|---|
  | 11-19 11:23 AM | 785 MB |
  | 11-19 6:15 PM | 1.04 GB |
  | 11-19 9 PM | 1.55-1.60 GB |
  | 11-20 9:28 AM | **1,610 MB** |

  - The 60 trims in the 11-19 evening released p50 142 MB each, but the floor after the evening stayed
    ~1.5-1.6 GB overnight: about +0.8 GB from one evening that is not returned.
  - Under the split the parent cannot recycle itself: its own refusal count is always 0, and the board child
    always counts as a running child (§4, owed item 3).
- **This morning:** tree 5,851 MB = parent 1,610 + child 3,890 (respawned 05:58Z) + jobs.
  - Headroom 2,085 MB, 185 MB over the floor, in QUIET hours.
- **Projection for the 11-20 evening, written before it** (not a new pass/fail, an expectation to check):
  - The parent adds +0.8-1.1 GB to reach 2.4-2.7 GB by 9 PM, and the child is at 4.0-4.5 GB. So the pair alone is
    over 6,036.
  - The post-build check should then read `recycle`, not `transient_jobs`, and the child should recycle after
    builds, at most every 30 min (the min uptime).
  - Expect P2's "<= 2 recycles" to be at risk (still rc 75), and refusals fewer than in 11-18's streaks.
- **If the parent's next-morning floor (11-21 ~9 AM CST) is >= 0.5 GB above today's 1,610 MB,** the parent ratchet
  is a multi-day trend. By the second or third evening, the pair with a FRESH child (~2.9 GB after one build) would
  sit over the line on its own, and the 11-18/19 overnight refuse-and-recycle loop returns. Two answers, neither
  built:
  1. **A refresh-worker restart:** a claimed TERM with no code or env change. It resets the parent, and it is not
     a betting change, because nothing that decides bets changes.
  2. **A parent self-recycle under the split:** in quiet hours, when the parent's own RSS is over a threshold and
     no job other than the board child runs, the whole worker exits and the supervisor restarts it. Behind a
     switch; a betting change by BC-053's rule, so the 11-24 window.

## 3a. Addendum 2026-11-20 16:00Z -- every rc -6 wrote a ~3 GB core dump to C: (lead from session local_313ab61c, confirmed here)

- `C:\Users\tempadmin\AppData\Local\Temp\wsl-crashes\` holds 10 files, 27.1 GB. WSL's crash capture keeps the latest 10.
- Nine of them are `wsl-crash-<epoch>-<pid>-_usr_bin_python3.11-6.dmp` (signal 6), **3.06-3.54 GB each**, written on
  11-19 at 12:11:39, 12:47:20, 13:24:03, 14:03:04, 14:33:42, 15:09:26, 15:42:13, 16:21:07 and 16:52:00Z.
  - Their pids match the board child's `BOARD_PROCESS_EXITED ... rc=-6` lines: 844647 at 12:11:39Z, 853119 at
    12:47:20Z and 860765 at 13:24:03Z. 869307 was the board child that `check_deploy_safety` listed at ~13:48Z.
  - So each crash exit also wrote the child's whole memory (~3 GB) to C:, every 31-39 min, on the shared host.
- The series stops at 16:52Z, 8 min before the #850 load (17:00:09Z). Since then the only child exit is the clean
  rc 75 at 05:58Z 11-20, with no dump.
- **One small dump is unexplained:** 25 MB, pid 1406840, at 08:19:56Z 11-20. It is NOT the board child, which had no
  exit then. Its pid appears in no role log line except other sessions' greps quoted in `ALL_PROCESS_MEMORY`.
- The 9 board-child dumps carry nothing the reproduction (§3) did not already show. Deleting them is the user's
  call; it would free ~27 GB.
- **DELETED 2026-11-20 ~16:05Z on the user's "Yes, delete them"** (answering "Delete the nine board-child crash dumps (27 GB)?").
  - Each of the 9 pids was first matched to a `BOARD_PROCESS_STARTED` / `BOARD_PROCESS_EXITED ... rc=-6` pair in the role log.
  - 9 files, 27.0 GB; C: free went from 147.3 to 178.9 GB.
  - The 25 MB pid-1406840 dump was kept.

## 9. READING 2 -- the second evening after the load, 11-20 5-10 PM CST (23:00-04:00Z), against §5 (written 2026-11-21 07:15Z = 1:15 AM CST)

The rail monitor took it (R-F in its nightly close, main `f9f59594e`, `findings_2026-11-20_layer2_rail_monitor.md` DAILY
SUMMARY). It was re-derived here read-only from `refresh-worker.log{,.1}` at 07:03Z 11-21 (`C:\tmp\bmg\load\read2.sh`,
`read2b.sh`, `read2c.sh`, nice 19).

**Load checks: MET.**
- All 300 refresh_worker heartbeats in the window read `container_memory_max_mb: 7936.0`.
- The 3 children started in the window (23:08, 01:36 and 03:29Z) each logged
  `BOARD_PROCESS_CHILD_SWITCHES raw_lifeline=1 recycle_after_build=1 ceiling_credit=7168+768`.

| # | 11-18 (before) | 11-19 (READING 1) | 11-20 (READING 2) | verdict |
|---|---|---|---|---|
| P1 refusals per UTC hour 23/00/01/02/03Z | 7/5/5/3/6 = 26 | 0/0/0/2/2 = 4 | **3/3/3/1/3 = 13** | **FALSIFIED** (> 6 total, and 3 in four of the hours) |
| P2 child exits and rc | 4, all rc -6 | 0 | **3, all rc 75** `reason=recycle`, 0 `Fatal Python error` | NEITHER (more than 2, none rc -6) |
| P3 longest `BOARD_BUILD_TIMING` gap | 1,580 s; 5 of 28 > 900 s | 807 s; 0 of 53 | **1,062 s**; 1 of 47 > 900 s (p50 330 s, 48 builds) | NEITHER (over 900, under 1,200) |

- **P1's count.** The rail monitor reported 15 because it counts every `MEMORY_GUARD_ABORT` stage. §5 counts
  `stage=pre_source_state_fingerprint` only, which is 13. The other 2 are one `build_candidate_pool_start` and one
  `post_pull_hot_artifacts`. The verdict is the same on either count.
  - Headroom at the 13 refusals was 1,575.8-1,890.9 MB against the 1,900 floor. 7 of the 13 were within 100 MB of it.
- **P2's exits.** All 3 are `RECYCLE_EXIT reason=heavy_build_refused` after 3 refusals, at 23:07:53Z, 01:36:01Z and
  03:29:38Z. Each was followed by `BOARD_PROCESS_EXITED rc=75 reason=recycle` and a 5 s respawn.
  - There are 0 real fatal errors since the load. All 26 untimestamped `Fatal Python error` lines in the log sit
    before 16:52Z 11-19, one per pre-load crash.
- **P3's 1,062 s gap is one of those recycles.**
  - The last build before it was at 01:26:22Z.
  - Refusals followed at 01:30:43, 01:33:59 and 01:35:17Z, then the recycle at 01:36:01Z and the respawn at 01:36:13Z.
  - The fresh child's first build landed at 01:44:04Z, a cold build of ~8 min.

**Comparability.**
- **The slate, by the letter, is CONFOUNDED.** Core live games (NCAAB + NBA + NHL + NFL, the rail monitor's p7count)
  were 26 at 7:03 PM CST (NCAAB 22, NBA 4). That is 57% of 11-18's 46, under the 70% rule (33).
  - After that they read 37 (80%) at 7:23 PM, 36 at 7:43 PM and 29 at 8:03 PM.
  - **The confound runs against the failure.** A lighter slate makes refusals rarer, so it cannot explain 13 of them.
    P1's falsification stands. A light slate would only have discounted a pass.
- **No refresh-worker restart, drain or deploy in the window.** Parent 1011283 has been up since 17:00:29Z 11-19, with
  0 `BOOTED` lines since 13Z 11-20. The day's 3 loads were web-only reload-webs before 5 PM (betting change no).
- **Not a confound, but the difference from READING 1:** this was the parent's second evening. It entered the window at
  1,697 MB; READING 1's parent was ~1.04 GB at 6:15 PM.

**Safety.**
- **Tree max: 6,939 MB at 01:24:33Z,** 3 MB over §5's 6,936 line. That is 1 of 300 samples; the next highest is
  6,569 MB. A marginal breach, with no OOM.
- **OOM:** 0 in the role log in the window.
  - `dmesg` holds one OOM kill on this boot, at ~08:46Z 11-20 (2:46 AM CST): a host-wide (`global_oom`) kill of an
    8.8 GB anon-RSS python.
  - It happened while the nightly ci-suite pytest was running; the watchdog logged `ci-suite ... exited rc=1` at
    08:50:55Z. Every fleet role pid was unchanged across it.
  - It is not a fleet role and falls outside both evening windows. Listed as a lead, not chased.
- **WSL `MemAvailable` at the evening's minimum: NOT MEASURED.** No heartbeat field carries it. It read 6.1 GB at
  07:05Z 11-21.

**Exploratory.**
- **Parent RSS, half-hour p50:**

  | 11-20 CST | 5:00 PM | 6:30 PM | 7:00 PM | 8:00 PM | **9:00 PM** | 11:00 PM | 1:00 AM (11-21) |
  |---|---|---|---|---|---|---|---|
  | parent | 1,697 | 1,998 | 2,090 | 2,188 | **2,224** | 2,293 (peak) | 2,094 |

  - At 9 PM that is +0.62-0.67 GB over READING 1's 1.55-1.60 GB, one day later. The rail monitor's 9 PM p50 was 2,255 MB
    and its peak sample 2,396 MB at 10:03 PM.
- **Parent trims:** 60, releasing p50 234 MB (max 260). READING 1: 60 trims, p50 142 MB. They release more, and the
  floor still rises.
- **Child RSS:** p50 3.1-4.1 GB.
- **Post-build checks in the window: 3 of 3 `held=transient_jobs`.** Pair 5,859-5,955 MB against the 6,036 line;
  headroom 1,668-1,856 MB.
  - **Each hold was followed by refusals and a streak recycle:** 23:01 hold -> recycle 23:07; 00:51 -> 01:36;
    02:26 -> 03:29.
  - So the hold turned what could have been a clean post-build recycle into 3 refused builds and the same recycle.
- **Over the slate day (13Z 11-20 to 07Z 11-21):**
  - 1 post-build recycle fired: `reason=post_build_headroom` at 04:14:05Z, pair 6,064 MB, headroom 1,872 MB. It was
    the first ever.
  - There were 6 streak recycles (18:32, 23:07, 01:36, 03:29, 05:47 and 06:46Z), all rc 75.
- **The overnight refuse-and-recycle loop is back, at a lower rate.**
  - Refusals after the window: 04Z 1, 05Z 4, 06Z 5, with streak recycles at 05:47 and 06:46Z. 11-19's overnight ran
    3-8 every hour.

**Against §8's projection (written 15:35Z 11-20, before this evening).**
- **"The parent reaches 2.4-2.7 GB by 9 PM": LOW.** It read 2,224 MB at 9 PM and peaked at 2,293 MB (half-hour p50).
  The rise within the window was +0.53 GB.
- **"The post-build check reads `recycle`": WRONG.** 3 of 3 checks in the window held. The streak recycles keep
  resetting the child (3.1-3.6 GB after a respawn), so the pair stays 80-180 MB under the line and the hold repeats.
  It fired once, at 04:14Z.
- **"P2's <= 2 recycles at risk, still rc 75": RIGHT.** 3 exits, all rc 75.
- **"Fewer refusals than 11-18": RIGHT, but well over §5:** 13 vs 26.

**What it says.**
- **Each of the four switches does what it was built to do.**
  - 3 of 3 exits in the window and 7 of 7 over the slate day were rc 75, not rc -6, and wrote no core dump.
  - The ceiling credit is counted.
  - The evening published 48 builds vs 11-18's 28, and its longest gap was 1,062 s vs 1,580 s.
- **They do not hold the line past the first evening.**
  - The parent keeps ~+0.6 GB a day that trims do not return. The parent cannot recycle itself under the split (§8).
  - So by the second evening the tree runs 1,575-1,890 MB of headroom against the 1,900 floor, and the refusals come
    back.
- **The `held=transient_jobs` rule now costs refused builds.** The jobs it treats as transient recur every cycle.
  That is the recurring-jobs margin lead (the user, 11-20: "Wait for a busy night"). From 7:23 PM this evening was busy
  by the slate rule.

**Owed.**
- **The 11-21 9 AM CST floor reading** (task `board-memory-parent-reset-1121`, rule: restart if the parent p50 is
  >= 2,110 MB).
  - The parent read 2,094 MB at 07:00Z, falling ~40-70 MB per half hour since its 05Z peak. The 9 AM reading may land
    under 2,110, though this evening shows the multi-day rise the rule was set to detect.
- **The lasting fix** (§8 answer 2: a parent self-recycle in quiet hours, plus the recurring-jobs margin). Both are
  betting changes, so the 11-24 window. That is the user's decision after the floor reading.

## 10. 11-21 morning floor and the conditional reset (task `board-memory-parent-reset-1121`, written 2026-11-21 15:05Z = 9:05 AM CST)

(The task named this section 9; section 9 is already READING 2, so it is 10.)

**Floor reading** (`floor.sh`, read 15:01:02Z = 9:01 AM CST):
- parent pid 1011283 (still the 11-19 load's process, etimes 165,637 s); parent RSS p50 **2,166 MB** (n 40 heartbeats, ~40 min);
  child p50 3,425 MB; tree p50 5,620 MB; ceiling 7,936 MB.
- **The condition is MET: 2,166 >= 2,110 MB** (`DECISION_RESTART=yes`). Up +556 MB on 11-20's 1,610 MB floor.
- fleet_head `0d20a69191b7b952cdf00d3dd767a1005abd4fc8`; **runtime_files_changed_since_38c3a6905 = 71**.

**Outcome: NOT restarted.** The task's rule: a non-zero runtime-file count means a TERM would load code other
lanes put on disk, and the user decides. The fleet checkout was fast-forwarded three times since the 11-19 load
(reflog: 3c8ba5b14 at 11:03 AM CST 11-20, eeeb62a63 at 11:38 AM, 0d20a6919 at 2:13 PM; 268 commits on
38c3a6905). refresh-worker has not loaded any of them. Among the 71 files (10,881+/48-):
- money-path / betting code: `syndicate/features/shared/execution_exits.py`, `execution_ledger.py`,
  `exit_hold_value.py` (new, 663 lines), `pipeline/execute_portfolio.py`, `pipeline/intelligence_state.py`,
  `syndicate/features/shared/board_enrichment.py`, `live_gameline_orientation.py`, `live_player_status.py`,
  `combined_board_shared_copy.py`;
- sim: `syndicate/features/ncaaf/live_resim.py`, `live_total_dispersion.py`, `live_blowout_damping.py`,
  `.../sim_engine/smartsim2/game_simulator.py`, `calibration_profile.py`;
- entrypoints: `scripts/run_refresh_worker.py` (+10), `scripts/run_live_odds_refresh_worker.py` (+119),
  `gunicorn.conf.py` (+137);
- the rest are offline/monitor scripts (`scripts/rail_monitor/*`, `scripts/portfolio_watch/*`, `scripts/s6/s7/s8_*`, ...).
Whether each of these is default-off was NOT checked. A TERM now would be a load of 268 commits, possibly a
betting change outside a window -- not the no-code restart the user approved.

No claim, no drain, no preflight, no TERM. Nothing on the fleet was changed.

**For the user.** The parent ratchet is a multi-day trend: 785 MB (11-19 11 AM) -> 1,610 MB (11-20 9:30 AM) ->
2,166 MB (11-21 9 AM). Options: (a) approve the TERM with the 268-commit load (needs each runtime change classified,
and a betting-change window or an `--outside-window` reason if any is a betting change); (b) leave it and accept
a third evening of refusals; (c) the lasting fix, a quiet-hours parent self-recycle -- a betting change for the
11-24 window, not built. The college slate starts at 11 AM CST, so (a) today is only before then.

## 11. The restart that loaded code -- 2026-11-21 16:35:42Z (10:35 AM CST), user "Yes, restart now" (written 16:50Z)

The full entry is deploys.md `## 2026-11-21 16:35:42Z`. Here are the classification and the readings.

**Why it was a decision.** §10's task met its condition but would have loaded 268 commits. So the user was asked "Restart
refresh-worker before 10:45 AM CST, loading those 268 commits?" and answered "Yes, restart now".

**Classification of what refresh-worker loaded** (`git diff 38c3a6905 0d20a6919`; 24 runtime files once offline
monitor/study scripts are left out, 17 of them reachable from refresh-worker):

| commit | what | absent = |
|---|---|---|
| `f29c53e91`, `56e132d40` | #835 NCAAF live total calibration (`SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION*`) | off |
| `44184da1e` | #852 NCAAF live blowout damping (`SYNDICATE_NCAAF_LIVE_BLOWOUT_DAMPING`) | off |
| `42af6a923` | #855 smartsim2 college overtime (a `CalibrationProfile` field) | off |
| `c37bdeab3` | #814 basketball off-floor exit (`SYNDICATE_LIVE_EXIT_OFF_FLOOR`) | off |
| `ace2020d3` | #856 hold-value exits (`SYNDICATE_EXIT_HOLD_VALUE`) | off gate + shadow log |
| `9931a787b` | #853 shared combined-board copy (`SYNDICATE_COMBINED_BOARD_SHARED_COPY`) | off |
| `e5a267c1d`, `6c1a3ecee` | college live join orientation (`SYNDICATE_COLLEGE_LIVE_JOIN_ORIENTATION`) | shadow: serves what the board served, counts only |
| `eeeb62a63` | the combined read leaves the Layer 2 shortlist encoded (`SYNDICATE_COMBINED_READ_SKIP_LAYER2_SHORTLIST`) | skip; nothing on that path reads it |
| `3d636d88e` | fill-quote logging, ledger fields only | on; its lane: NOT a betting change |
| `3c8ba5b14`, `0d20a6919`, `ed5ed7581` | `gunicorn.conf.py` | web only |
| `8f0d73a2e` | #851 slate sweep thread | live-odds-worker only, off |

- All 12 env keys named above were absent from refresh-worker's environ before and after the TERM (checked by name
  only). The TERM reuses the env built at the 11-19 17:00Z up, so nothing could switch on.
- Verdict: **betting change no.**

**Readings.**
- **TERM 16:35:42Z, new pid 2313049, BOOTED 16:35:49Z.** Every load check was MET: ceiling credit, parent trim,
  child switches, healthz 200, 0 Traceback.
- **New parent 1,113-1,174 MB at 16:43-16:47Z.** The expectation was <900, so it is **NOT MET**; 11-19's fresh parent
  was 785 MB.
  - It is still 1.08-1.14 GB under the 2,249 MB baseline.
  - Headroom is 3,795-3,949 MB vs ~1,860.
- **First build 16:47:16Z.** The board went unbuilt from 16:07:28Z, 2,388 s, because the drain stopped builds from
  16:04Z.
  - The drain never read CLEAR: its last-named jobs were all live-odds-worker's (Saturday live soccer). For a
    refresh-worker-only TERM it gated nothing and only stopped the board.
  - A lesson for the next such restart: preflight, then TERM, without the 30 min drain wait, when refresh-worker's own
    jobs are idle.
- **Tonight is the parent's first evening again**, so the same §5 thresholds apply and READING 1's slate rule.

## 12. The lasting fix -- built default-off; PRE-REGISTERED PREDICTION for its 11-24 load (written 2026-11-21 ~17:45Z = 11:45 AM CST, before any load)

**User:** "Yes, build it" (2026-11-21 ~11:00 AM CST, typed in session 1f9c9a40). It answered "Build the lasting fix,
switched off, to load in the 11-24 window?" The code is in `pipeline/board_build_process.py` ("THE PARENT'S RATCHET")
and `syndicate/features/shared/worker_recycle.py` (`register_recycle_check`). Tests:
`tests/test_board_split_memory_guard.py` section (d), 42 new tests, 75 in the file. They pass on Windows and on the
fleet's Python 3.11.16, with 124 across the split's suites there.

**Two switches, each absent = today**, both REFRESH_WORKER__-scoped:

| key | value to load | what it does |
|---|---|---|
| `SYNDICATE_BOARD_PROCESS_PARENT_RECYCLE_MB` | 1500 | the split's parent exits at the worker main loop's own recycle point when its RSS >= 1,500 MB inside 09-12Z (3:00-5:59 AM CST), up >= 6 h, with no job child, the board child idle, no drain, and the checkout HEAD unchanged since its boot |
| `SYNDICATE_BOARD_PROCESS_RECURRING_JOBS_MARGIN_MB` | 400 | the post-build check recycles the child when parent + child + 400 MB of recurring jobs would leave less than the 1,900 MB floor |

**Why these values.**
- **1,500 MB:**
  - A fresh parent reads 0.8-1.2 GB (785 MB 11-19, 1,113-1,174 MB 11-21).
  - After one live evening it is 1.55-2.3 GB, and the morning floors were 1,610 and 2,166 MB.
  - So 1,500 resets it every morning after a live evening, and never after a quiet one.
- **400 MB:** the role's other processes read p90 288-427 MB (11-20 day, evening and night); they run about half
  the time.
- **The 09-12Z window and the 6 h minimum:** at most one recycle a morning, never in an evening. The 11-24 load
  itself (~08:30Z) cannot self-recycle that morning, because it will not have been up 6 h.

**It is a betting change** (the board's build cadence, BC-053's rule), so it loads only in the window. It is queued as
droppable CHANGE J of batch task `nfl-level-refit-load-1120`.

**Load checks** (the reading is VOID without them):
- after the up, one `BOARD_PROCESS_PARENT_RECYCLE_ARMED ... threshold_mb=1500 window_utc=09-12 min_uptime_s=21600
  boot_head=<TARGET's first 12>`;
- `BOARD_PROCESS_CHILD_SWITCHES ... jobs_margin_mb=400`;
- `kit_role_env.py` showing refresh-worker carrying both keys.

| # | what | window | predicted | falsified if |
|---|---|---|---|---|
| P1 | parent self-recycle fires | 11-25 and 11-26, 09:00-11:59Z | on each morning whose 09Z parent RSS is >= 1,500 MB: exactly 1 `BOARD_PROCESS_PARENT_RECYCLE`, then `RECYCLE_EXIT reason=board_parent_rss` and a new supervised pid | 0 recycles on a qualifying morning for a reason other than a legitimate hold (`children_running` / `board_building` / `drain_requested` / `code_on_disk_changed` throughout); or >1 in a morning; or any outside 09-12Z |
| P2 | it costs nothing it should not | each self-recycle | the new parent reads < 1,300 MB 30 min later; the board gap across it (the last `BOARD_BUILD_TIMING` before to the first after) <= 900 s; the RECYCLE line reads `children: 0` | gap > 1,200 s; or any job child killed; or any rc -6 / `Fatal Python error` |
| P3 | refusals per evening | 11-24 and 11-25, 5-10 PM CST | `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` <= 3 an evening (11-19: 4, 11-20: 13) | > 6 on any comparable evening |
| P4 | streak recycles per evening | same | `RECYCLE_EXIT reason=heavy_build_refused` <= 1 an evening (11-20: 3) | >= 3 on any comparable evening |
| P5 | board cadence | same | longest `BOARD_BUILD_TIMING` gap <= 900 s; gap p50 <= 360 s (11-20: 1,062 / 330 s) | longest > 1,200 s, or p50 > 420 s (the margin's extra cold builds costing more than the refusals they save) |

- **Exploratory, not pass/fail:**
  - the parent RSS at 9 PM CST each evening (expected <= 2.0 GB: never more than a day old);
  - post-build `held=transient_jobs` lines per evening (11-20: 3 in the window);
  - post-build recycles vs streak recycles;
  - every `BOARD_PROCESS_PARENT_RECYCLE_CHECK held=` reason seen.
- **Comparability:** the §5 rule per evening (core live NCAAB + NBA + NHL + NFL at ~7 PM CST >= 70% of 11-18's 46 = 33).
  An evening under it is CONFOUNDED for P3-P5. Thanksgiving (11-26 Wed NBA/NCAAB; 11-27 NFL) changes the slate.
- **Confounds named now:**
  - The same down/up loads CHANGES A-I. C (look-ahead lane wait), D (book-grid stamp), G (college orientation join)
    and I (off-floor exits) also run in refresh-worker or its board child, and may move its memory or build time.
  - So P3-P5 rest on the batch, not on J alone. P1-P2 are J's own.
  - A manual refresh-worker restart or deploy in a window resets the parent and is named; an evening with one is
    CONFOUNDED.
- **Safety:** tree max <= 6,936 MB; 0 OOM; 0 rc -6; no job child killed by a self-recycle.
- **Revert:** remove the two env lines, then a drained full down/up. A revert is allowed outside a window.
- **Reading:** owed in this lane, after the 11-26 morning. Scheduled task `board-parent-recycle-reading-1126`.
- **Amended 2026-11-21 ~18:00Z, before any load:** P3-P5 read the 11-24 and 11-25 evenings (the task fires 11-26 7:30 AM CST,
  so the 11-26 evening is outside it). The reader is `C:\tmp\bmg\w1124\read_850j.py`. Dry-run on the 11-20 logs, it
  reproduced READING 2 exactly (13 refusals 3/3/3/1/3, 3 streak recycles, 3 holds, 48 builds, gaps p50 330 s / max 1,062 s, tree max 6,939 MB).

## 13. A busy Saturday on a fresh parent -- the slate, not the ratchet (written 2026-11-22 ~00:30Z = 6:30 PM CST 11-21)

The hypothesis went into the lane first (H1 code, H2 slate). The readers were all read-only, at nice 19: `C:\tmp\bmg\w1124\tonight.sh`, `parents.sh`, `same_clock.sh`, `build_wall.sh` and `stage_cmp.sh`, over `refresh-worker.log` and `.1`/`.2` (11-18 18:11Z on).

**Every split parent's RSS by age** (MB; median of the refresh_worker heartbeats within 15 min of each age):

| pid | first heartbeat (CST) | checkout then | +10 min | +1 h | +3 h | +6 h | +12 h | +24 h | last |
|---|---|---|---|---|---|---|---|---|---|
| 152916 | Wed 11-18 6:12 PM, live evening | a3104a5b6 | 1,569 | 1,797 | 2,136 | 2,345 | 2,292 | - | 2,273 at 16.8 h |
| 1011283 | Thu 11-19 11:01 AM, quiet morning | 38c3a6905 + the 4 switches | 731 | 761 | 764 | 845 | 1,490 | 1,677 | 2,286 at 47.6 h |
| 2313049 | Sat 11-21 10:37 AM, NCAAF day | 0d20a6919 | 1,175 | 1,335 | - | - | - | - | 1,554 at 1.6 h |
| 2397127 | Sat 11-21 12:16 PM, NCAAF day | b07e80882 | 1,328 | 1,538 | 1,528 | 1,665 | - | - | 1,671 at 6.0 h |

**The same clock window, 12:30-6:00 PM CST (18:30-24:00Z), on three days:**

| day | live games the builds saw (median, all sports) | builds | build wall p50 / p90 s | gap p50 / max s | gaps > 900 s | pre_source refusals | post_build_overview refusals |
|---|---|---|---|---|---|---|---|
| Thu 11-19 | 2 | 77 | 168 / 210 | 249 / 355 | 0 | 0 | 0 |
| Fri 11-20 | 4 | 60 | 207 / 250 | 290 / 828 | 0 | 11 | 0 |
| Sat 11-21 | 28 (NCAAF 14, NCAAB 10) | 32 | 371 / 479 | 575 / 1,098 | 4 | 14 | 5 |

- **Saturday's builds are CPU-bound:** cpu p50 337 s, off-CPU 6.4% on the latest.
- **Where the time went, Fri -> Sat** (stage medians, same window):
  - `board_publication` 209 -> 371 s;
  - `layer2_shortlist_build` 96 -> 153 s;
  - `portfolio_commit` 20 -> 61 s;
  - `build_intelligence_overview` 2 -> 37 s (its NCAAF overview 17 -> 35 s);
  - `kalshi_odds_refresh` 42 -> 43 s.

**Verdict.**
- **H2 (slate) SUPPORTED.** A parent's RSS follows what is live while it runs:
  - Booted into a quiet morning, it stays at 730-850 MB until the evening slate: 1011283 read 845 MB at 5 PM CST and 1,490 by 11 PM.
  - Booted into a live slate, it reaches 1,500-1,800 MB within an hour: 152916 on Wednesday evening on older code, and 2397127 on Saturday.
  - It then keeps its high-water mark. That is the ratchet: 1011283 read 2,286 MB at 47.6 h.
- **H1 (code) NOT ESTABLISHED, NOT EXCLUDED.** Both 11-21 parents booted into a Saturday slate.
  - **The decisive reading is Sunday's 4 AM reset**, whose new parent runs b07e80882 on a quiet board.
  - PREDICTION, written now: H2 holds if it reads 700-900 MB at +10 min and +1 h. H1 holds if it reads >= 1,100 MB at either. The task's `wait_first_build2.sh` records it.
- **Tonight's long gaps are mostly build COST, not memory.**
  - 32 builds against 60-77 in the same hours, with each build 1.8-2.2x longer. The 14 refusals come on top of that.
  - Neither CHANGE J nor the morning resets touch build cost. It is not this lane's mechanism; the stage deltas above name where the cost is.
- **Section 12 is unchanged.**
  - Its P3-P5 read the 11-24/11-25 weekday evenings under the comparability rule.
  - Its line "a fresh parent reads 0.8-1.2 GB" holds only for a boot at a quiet hour, as here. J fires only 09-12Z, which is a quiet hour.
- **The morning task:** the parent read 1,657 MB at 00:12Z, so Sunday's 4 AM reset will very likely run (threshold 1,500).
