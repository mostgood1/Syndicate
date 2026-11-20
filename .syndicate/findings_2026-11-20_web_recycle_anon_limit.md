# Web worker recycle limit (650 MB, sized for Render) — growth curve, limit model, cost — 2026-11-20

Lane `web-recycle-anon-limit` (session f182fa28, a side session of the board-read-cold-share session). Todo `#857`.
Started from #853's lead ("a higher limit would make recycles RARE"). READ-ONLY on the fleet: every log read ran
at nice 19 (the extract also at `ionice -c3`), 15:50:53-15:51:33Z, plus one-line greps. Nothing was loaded.

## Question

`gunicorn.conf.py` `anon_limit_mb()` defaults `SYNDICATE_WEB_WORKER_ANON_LIMIT_MB` to 650. That was sized for
Render's 2,048 MB container; on the fleet the web role has no cgroup cap. A worker that has built the Layer 2 board
sits near 1 GB, so it is recycled minutes after its first board query: 13.7-28.5 recycles an hour on the 11-17..11-19
evenings. Should the fleet recycle at a higher limit? If so, which one, at what memory cost, and with what prediction?

## Instrument

`scripts/rail_monitor/web_anon_curve.py` (new, stdlib only, runs under WSL `python3`):
- `extract` streams the logs once;
- `report --from --to` prints everything below.

It reads two sources:
- **`web.log`** (10-31 03:14Z .. 11-20 15:46Z): gunicorn boot and exit lines, the guard's `ARMED` / `RECYCLE` /
  `DEFERRED` lines, and `WARMER_STARTED`;
- **live-odds-worker's `ALL_PROCESS_MEMORY`** (11-16 17:40Z .. 11-20 15:48Z): 36,858 snapshots, one per ~9 s.
  These list every fleet process's pid, ppid and RSS, which makes them the only per-worker memory series.

How the series is read:
- **Which processes are workers.** A web worker is a gunicorn-cmdline process whose parent is also one.
- **RSS to anon.** The guard reads `RssAnon`, and the series is RSS. At 503 recycles, RSS minus the guard's anon
  was p10 14, **p50 60**, p90 82 MB. "Anon-eq" below is RSS minus 60.
- **The origin.** A worker "holds the full board" from its first sample at anon-eq >= 850 MB: 533 workers, 372 of
  them in the 5-11 PM CST evening.
  - `WARMER_STARTED` was NOT used as the origin. It marks the first combined-board call of ANY key, sport-filtered
    calls included. Of the 56 workers that lived 20+ min after it, most never passed ~600 MB.

## 1. Growth past the first board build: a plateau, with an evening drift in the first ~15 min

Per worker, the median anon-eq inside each bin, counted from the first >= 850 sample. "n" is the workers with a
sample in the bin; the 650 limit censors the right-hand rows.

| from (s) | evening n | evening median p10 / p50 / p90 | evening bin peak p90 / max | not-evening n | not-evening median p50 / p90 |
|---|---|---|---|---|---|
| 0 | 372 | 856 / 912 / 1,010 | 1,074 / **1,666** (first-build transient) | 167 | 889 / 961 |
| 60 | 151 | 898 / 1,025 / 1,142 | 1,163 / 1,322 | 103 | 946 / 996 |
| 120 | 66 | 931 / 1,055 / 1,179 | 1,218 / 1,401 | 75 | 955 / 1,021 |
| 300 | 34 | 966 / 1,111 / 1,227 | 1,298 / 1,395 | 47 | 971 / 1,062 |
| 600 | 18 | 983 / 1,168 / 1,240 | 1,300 / 1,381 | 26 | 983 / 1,077 |
| 900 | 5 | 1,070 / 1,161 / 1,252 | 1,388 / 1,479 | 17 | 988 / 1,070 |
| 1,200-2,700 | 2-2 | 1,044-1,037 / 1,105-1,070 | 1,262 / 1,119 | 8-4 | 977-945 |

Growth inside the SAME worker: its median in a later window minus its median 60-180 s after it first held the board.

| later window | evening n | evening p10 / p50 / p90 (max) | not-evening n | not-evening p10 / p50 / p90 (max) |
|---|---|---|---|---|
| 180-300 s | 42 | 1 / **17** / 44 (172) | 59 | -4 / 4 / 23 (81) |
| 300-600 s | 34 | 6 / **39** / 107 (213) | 45 | -3 / 11 / 48 (89) |
| 600-900 s | 18 | 10 / **52** / 180 (219) | 26 | -7 / 20 / 85 (119) |
| 900-1,200 s | 5 | 10 / **131** / 210 (213) | 17 | -9 / 29 / 94 (124) |
| 1,200-3,600 s | 2 | 10 / 10 / 10 | 8 | -14 / 18 / 36 (38) |

**Peer reading (lane `web-silent-worker-kills`, sent 11-20; their script `wsk_holdgrowth.py`, read-only).** Since
`db6a395ed`, a held hard recycle keeps a worker serving until its next request after 30 s. That gives anon at the
DEFERRED line and again at the recycle.
- **Holds at age >= 900 s (n 15):** median change **0.0 MB**, net -56 MB, over 1.80 h held and 52 requests.
  - The longest hold, pid 1348221: 838.6 MB, then 843.8 MB 3,677 s later.
  - My series for that pid agrees: 843 MB at its end, max 844.
- **Holds at age < 900 s (n 26):** median +36 MB. These sit inside the first build.

**Per-evening plateau** (per-worker median 60-600 s after the first >= 850 sample), against the board size (the
`QUERY_STAGE_MS` `rows` p50):

| evening | board rows p50 | plateau p50 / p90 / max | per-worker peak p90 / max |
|---|---|---|---|
| 11-16 | 5,438 | 1,023 / 1,089 / 1,278 | 1,102 / 1,667 |
| 11-17 | 5,601 | 1,009 / 1,092 / 1,200 | 1,095 / 1,325 |
| 11-18 | 6,424 | 1,072 / 1,265 / 1,354 | 1,275 / 1,401 |
| 11-19 | 5,726 | 1,049 / 1,124 / 1,182 | 1,161 / 1,480 |

- Board rows p50 ran 3,199-6,641 over the 10-30..11-19 evenings, and the largest single query was 8,172 rows (11-02).
- The plateau rises roughly **+75 MB per +1,000 rows**. That is a rough fit, n 4 evenings. It puts an 8,000-row
  evening's plateau near p50 ~1,200 and p90 ~1,400.

**Structural check.** The per-process board cache is bounded. `_prune_combined_intelligence_response_cache`
(`pipeline/intelligence_state.py`) keeps at most 32 entries and 4,000 rows, but always at least one entry. A full
board (4,600-6,600 rows) therefore sits alone. Nothing evicts an entry by time: a worker keeps its last board until a
newer insert replaces it, or until it is recycled.

**Verdict on H-plateau: NOT falsified on what can be observed, and the long evening tail is unobserved.**
- Away from the evening, growth is flat to 60 min: median +4 to +29 MB.
- Old held workers changed 0.0 MB over 1.8 h.
- The evening drifts upward for the first ~15 min (median +17 / +39 / +52 MB, then +131 at n 5).
- Past ~20 min, today's limit leaves only 2-5 evening workers to look at. Whether the evening drift stops near
  ~1,150-1,250 MB or keeps going cannot be read from today's fleet; the 650 limit censors it.
- The prediction below tests it, and the memory cost is bounded by the limit either way.

## 2. Recycles per hour at candidate limits

**Model.** Anon-eq first crosses L while a worker holds the board. The hazard is crossings per worker-hour at risk,
and recycles/h ~= 2 workers x hazard. Evening exposure is ~10.9 worker-h (11-16..11-19), most of it in the first
10 min after a build.

| limit L | evening crossings / worker-h | recycles/h (pooled) [95%] | late window (>= 600 s after) | not evening |
|---|---|---|---|---|
| 650 (today) | — | **13.7-28.5 measured** | — | 4.0 measured (11-19 morning) |
| 1,100 | 65 / 7.15 | ~18 | 0 / 0.45 | 10 / 11.71 |
| 1,200 | 21 / 8.91 | ~4.7 | 2 / 0.60 | 0 / 12.96 |
| 1,300 | 7 / 10.57 | ~1.3 [0.5, 2.7] | 3 / 1.38 (=> ~4.4/h) | 0 / 12.96 |
| 1,400 | 3 / 10.84 | ~0.6 [0.1, 1.6] | 1 / 1.46 | 0 / 12.96 |
| **1,500** | **1 / 10.89** | **~0.2 [0.0, 1.0]** | 0 / 1.47 | 0 / 12.96 |

- **Ratchet bound.** Suppose instead the evening drift were linear at the 15-20 min rate (+131 MB in ~17 min, about
  +450 MB/h). A worker at 1,050 MB would then reach 1,500 in about 1 h, so L = 1,500 still means about 2 recycles an
  hour, against 14-29 today.
- **Big slates.** 1,300 sits inside the 11-18 plateau's range (p90 1,265, max 1,354), and an 8,000-row evening would
  put most workers over it. 1,500 clears the p90 such an evening is estimated to reach.
- **Failure mode.** A limit that a slate outgrows makes the fleet recycle as it does today. It is not a memory risk.

## 3. Memory cost

The cost is set by the PLATEAU, not by L. Any L above the plateau means both workers hold the board (~1,060 MB anon
each, +60 RSS): about 2,240 MB for the two workers, at every hour. That includes the night, because nothing evicts the
board by time. The table replaces the observed web workers with max(observed, 2,240) per snapshot (11-16 17:40Z ..
11-20 15:48Z, 32,476 snapshots):

| | evening (5-11 PM) | night (11 PM-7 AM) | day (7 AM-5 PM) |
|---|---|---|---|
| web workers RSS, observed p50 | 1,169 | 1,060 | 1,057 |
| fleet roles (web + board child + refresh + live-odds + redis) p50 | 7,435 -> **8,430** | 6,941 -> **8,141** | 6,793 -> **8,030** |
| fleet roles p99 | 9,596 -> 9,983 | 9,088 -> 9,675 | 8,635 -> 9,441 |
| fleet roles max | 10,146 -> 10,146 | 9,419 -> 10,518 | 9,789 -> 10,626 |
| everything incl. co-tenant jobs, p50 / max | 8,327 / 14,031 -> 9,337 / 15,030 | 7,356 / 14,279 -> 8,594 / 16,031 | 7,357 / 12,310 -> 8,599 / 14,190 |

All figures are MB. `accounted_rss_mb` counts shared pages more than once.

- **The VM.** `MemTotal` 16,124,372 kB (15.4 GiB); swap 4 GiB, 1.1 GiB used at 15:5xZ; `pswpout` 2.29 M pages
  since the VM booted (11-18 06:40 CST).
- **The two all-process peaks are co-tenant jobs, not the fleet.**
  - 11-17 8:27 PM CST: `/mnt/c/tmp/elp/kprior2/make_opinions.py`, 5,345 MB.
  - 11-20 ~2:48 AM CST: a `pytest` run in the fleet venv, 7,928 MB RSS. **The kernel's global OOM killer fired**
    (`dmesg`: `Out of memory: Killed process ... anon-rss:8806248kB`, `/proc/vmstat oom_kill 1`). It picked the
    pytest, the largest process. In the same snapshots refresh-worker fell 1,412 -> 452-619 MB, redis 284 -> 82 MB
    and a web worker to 9 MB, which is to say they were swapped out.
- **Per-worker worst case at L = 1,500** (the guard's jitter is 0.95-1.0 x L):
  - a soft recycle at >= 1,425-1,500, checked every 5th request after age 120 s;
  - hard at >= +150, re-checked every request, with a hard stagger of <= 30 s;
  - emergency at >= +750, which goes at once.
  - So web is about 2 x 1,650 + 120 = **~3.4 GB worst case**, against an observed max of 2.85 GB today. Today's
    single-worker max is 1,667 MB (a first-build transient).

**No other role's guard sees web's memory.**
- refresh-worker, live-odds-worker and the board child gate on their OWN role tree's RSS against a declared ceiling.
  `memory_observability` `_local_memory_limit_active` -> `_read_container_memory_current_bytes` =
  `_local_process_tree_rss_bytes`, and `_read_container_memory_stat` returns `{}`, so the VM-wide `memory.stat` is
  ignored.
- The only cross-role channel is the kernel, through swap and global OOM. OOM picks by badness (~RSS). Web workers at
  1.1-1.5 GB rank below the board child (3.4-4.6 GB), refresh-worker (1.4-4.1 GB) and any large co-tenant.
- The real exposure: ~1.1-1.2 GB less free memory in the median hour. A co-tenant spike tips into swap or OOM about
  1.2 GB sooner, and the victim is the largest process: the co-tenant, as on 11-20, or the board child if the
  co-tenant is smaller than it.

## 4. What else reads the limit

- **`gunicorn.conf.py` only.** The key appears in no other file of the repo outside its tests
  (`tests/test_gunicorn_conf.py`).
  - `post_fork`: the limit is jittered x U(0.95, 1.0), and `WEB_MEMORY_GUARD_ARMED` prints the result.
  - `decide_recycle`:
    - soft recycle at >= limit, after `min_age_seconds` 120, checked every 5th request; soft stagger 90 s;
    - **hard = limit + `HARD_MARGIN` 150**, with lane `web-silent-worker-kills`' 30 s hard stagger (re-checked every
      request);
    - **emergency = hard + `EMERGENCY_MARGIN` 600**.
  - All three scale with the limit. Nothing else needs to change.
- **On the fleet the key is set nowhere** (`fleet_env/web.json`, `local_production.env`, `fleet_role_spec.json`).
  The last 400 `ARMED` lines read 617.5-650.0.
- **The web role's `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` = 2,048** (`local_production.py` `PLAN_MEMORY_MB`).
  - A worker's headroom is 2,048 minus its own tree RSS: the root is the worker, because the master never calls
    `memory_observability`.
  - Web-side gates on that headroom: the in-request overview (floors 1,500 / 3,000 MB), overview isolation (needs
    headroom - 400 >= 900), the game-chip publisher, and ops `_overview_skip_reason`.
  - **None of them ran in web in 20 days** of web.log: `OVERVIEW_STOPPED_FOR_MEMORY`, `OVERVIEW_ISOLAT`,
    `cap_below_viable`, `GAME_CHIP` and `MEMORY_GUARD_ABORT` all read 0.
  - They would already refuse at today's ~1,000 MB board-holding workers, so raising the limit changes nothing there.
- **Lane `web-silent-worker-kills`** (owns `gunicorn.conf.py`) was told by message and in its lane block. Its
  `ed5ed7581` (not loaded) changes how a hold is timed and logged, not the decision. An env key edits none of its
  regions.
- **`--max-requests` is set, and becomes the second recycle path.**
  - The command line in `local_production.py:574-583` has no `--max-requests`. But the running master and both
    workers carry `GUNICORN_CMD_ARGS=--max-requests 1000 --max-requests-jitter 100 --access-logfile -`, from the
    Render-era `fleet_env/web.json` snapshot (read from `/proc/<pid>/environ`, 11-20 ~16:00Z).
  - It has never fired: 0 `Autorestarting worker` lines in 20 days, because today no worker gets near 1,000 requests.
  - At 1,500 it will fire. Evenings ran 215-453 requests/h across both workers (11-15..11-19 access log; every line
    captured, 483 = 483 in a spot-checked hour). That is one max-requests recycle per worker every ~4.5-10 h, about
    **0.2-0.45 recycles/h** in an evening.
  - It also bounds any slow leak, independently of the memory guard. It is not staggered with the guard's stamp; its
    jitter of 100 spreads the two workers apart.

## 5. What a recycle costs today (the benefit side)

- **The boot itself is cheap.** Boot to app loaded (`WEB_LOOP_STALL_DUMP_ARMED`) is 0.7-1.0 s p50 and 1.6-1.9 s p90 on
  11-17..11-19 evenings (n 82-110). A recycle's cost is the cold caches.
- **The board query (#853).**
  - On the 11-19 evening, new-worker first reads were 96 of 195 queries (49%) and 84% of cold reads; cold board_read
    p50 was 3.3 s, and 4.2-5.3 s on earlier evenings.
  - About 100 first builds an evening run in web (3-5 s CPU each), competing with the board child (#849's per-core
    clock cost).
  - **#853 already removes most of this**: it adopts another worker's copy in ~0.5 s (projection 58.5% -> 8.7% cold).
    Once #853 is loaded, this change adds only a few points on the board query.
- **Other routes.** This evidence is weak: with 2 workers, a request in a post-boot window may hit the old worker.
  Requests starting within 120 s of any boot were compared with the rest, over the 11-16..11-19 evenings:

  | route | post-boot p50 | other p50 | > 2 s | n |
  |---|---|---|---|---|
  | `/api/board/game-chips` | 2.50 s | 1.91 s | 60% vs 48% | 616 / 871 |
  | `/api/board/layer2-shortlist` | 1.12 s | 0.82 s | | 35 / 77 |
  | `/api/portfolio/live` | 0.40 s | 0.28 s | | 37 / 48 |

  - Post-boot windows cover ~40% of evening requests.
  - The board query itself reads FASTER post-boot (5.9 vs 8.2 s p50), so the split is confounded: recycles follow
    board builds. Read it as direction only.
  - The portfolio monitor tied 2 of 3 slow `live_today` reads on 11-19 to a recycle (relayed from #853).

## RECOMMENDATION

1. **Limit: 1,500 MB.** Set `WEB__SYNDICATE_WEB_WORKER_ANON_LIMIT_MB=1500` in `~/syndicate-prod/local_production.env`.
   It is env only; absent = today. It is the lowest limit with margin above the observed evening plateau (p90 up to
   1,265, max 1,354), the evening drift and the largest observed slate.
   - 1,300 would recycle ~0.5-2.7/h already (late window ~4/h), and more on a big slate.
   - 1,400 is ~0.1-1.6/h with less big-slate margin.
2. **Price: +1.0-1.2 GB at p50, at every hour, night included.** Fleet roles' p99 and max barely move (+0.0-1.1 GB);
   the worst case for web is ~3.4 GB. The VM's real exposure is co-tenant research jobs: one was OOM-killed today
   with web at 0.5 GB.
3. **Not with #853 on 11-24.** #853's P1/P2/P6 assume today's recycle rate; P6 reads recycles/h and anon at recycle.
   Loading both in one down/up voids #853's attribution. Load this change at the **first drained full down/up after
   #853's first-evening reading** (11-24 5-11 PM CST).
4. **Not a betting change.**
   - No code path that places, sizes, holds or exits a bet reads web's memory or its recycle limit. The money path
     runs in the workers, whose guards measure their own trees.
   - The cross-role channel is host memory only, and the safety readings below cover it.
   - Preflight: `--betting-change no`. It needs no window.
5. **Rollback** = remove the line at the next drained full down/up. A role restart reuses the old env, so there is no
   fast rollback. Until that down/up, the guard's hard and emergency margins still cap each worker.

## PRE-REGISTERED PREDICTION — first live evening (5-11 PM CST) after the load (L = 1,500)

**Reader:**
- `web_anon_curve.py extract` + `report --from <D>T23:00:00 --to <D+1>T05:00:00` for P1-P4;
- `coldread_attrib.py` (#853's reader) for P6;
- `/proc/vmstat` (`oom_kill`, `pswpin`, `pswpout`) read at 5 PM and 11 PM CST.

**Baseline:** the same window on the last evening before the load, same readers.

**Load checks (VOID if any is missing):**
- every `WEB_MEMORY_GUARD_ARMED` after the up reads `anon_limit_mb` 1,425-1,500, with `hard_margin_mb` 150 and
  `emergency_margin_mb` 600;
- `fleet_role_env_reading.py compare` shows the key added on web only.

| # | metric | baseline (11-17..11-19 evenings) | predicted | falsified if |
|---|---|---|---|---|
| P1 | recycles/h: `WEB_WORKER_MEMORY_RECYCLE` + `Autorestarting worker` (max-requests), reported apart | 13.7-28.5 (+ 0) | **<= 2 in total** (memory ~0.2 [0, 1.0] + max-requests ~0.2-0.45) | > 4 |
| P2 | H-plateau: evening workers holding the full board >= 60 min, per-worker change from 60-180 s to their last 10 min | not observable today | median <= +150 MB | median > +300 MB, or any slow-growth hard recycle (>= L+150 more than 10 min after the build) |
| P3 | web workers RSS sum (live-odds `ALL_PROCESS_MEMORY`) | p50 1.17 GB, max 2.85 GB | p50 2.0-2.5 GB, max <= 3.5 GB | max > 3.6 GB |
| P4 | fleet roles RSS (web + board + refresh + live-odds + redis) | p50 7.4 GB, max 10.1 GB | p50 <= baseline + 1.3 GB; max <= 11.5 GB | max > 12.5 GB |
| P5 | SAFETY: global OOM kills (`oom_kill` delta, `dmesg`) | 0 in evenings; 1 at 11-20 2:48 AM (co-tenant) | 0 | ANY OOM victim that is a fleet process -> ROLL BACK at the next drained down/up |
| P6 | board query new-worker first reads (share of queries) | 49% (11-19, pre-#853); #853's own post-load reading | <= 3% | > 8% |
| P7 | `WORKER TIMEOUT` kills and loop-stall dumps | 0 a day 11-18..11-20 | 0 | any -> hand the dump to lane `web-silent-worker-kills` |
| P8 | (secondary, not gating) `/api/board/game-chips` p50 | the baseline evening | <= 0.9x | — |

- **CONFOUNDED if** the window has < 30 board queries, a restart / `reload-web` / deploy, or a non-fleet process
  above 2 GB RSS (a co-tenant). Report `pswpin` / `pswpout` deltas beside P5; there is no threshold, because
  co-tenants dominate them.
- **The night cost is predicted too, not as a falsifier:** web workers' RSS night p50 ~2.2 GB, against 1.06 GB today.
- **If P2 is falsified** (a ratchet), the limit still bounds the memory. Read P1: if it is <= 4, keep it. If it is
  > 4, the benefit is smaller than modelled, and keeping it is a decision for the user.

## Leads (not followed)

- **An idle eviction of the board cache** would remove the night cost: drop an entry nobody has requested for N
  minutes, then `malloc_trim`. That is code in `pipeline/intelligence_state.py`; a separate lane.
- **Co-tenant research and test jobs in WSL have no memory cap.** The 8.8 GB pytest was OOM-killed on 11-20 at
  ~2:48 AM CST. The learnings rule covers their CPU priority, not their memory. A `prlimit --as` or
  `systemd-run --user --scope -p MemoryMax=` wrapper would cap them.
- **`#853`'s P6 reads recycles/h within 1.3x.** If this change ever loads in the same down/up, restate P6 first.
