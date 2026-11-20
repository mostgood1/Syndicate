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
