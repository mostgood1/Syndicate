# Board query cold `board_read` (rail monitor I-28) — 2026-11-19

Lane `board-read-cold-share` (session eb973f38, a side session of the rail monitor 62433e58).
Todo `#853`. READ-ONLY on the fleet (web log greps at nice 19). The fix is on main and DEFAULT-OFF.

## Question

The Layer 2 page's board query (`POST /api/intelligence/query`, served by web) paid a cold `board_read`
on 60-70% of requests: 3.9-8.8 s, against 1-40 ms warm. The brief named two suspects, (a) web worker
memory recycles and (b) a new board version every ~4.5 min that each worker reads for itself. It asked
for the split to be measured, not assumed.

## Pipeline trace (file:line on main at this lane's commit)

1. `syndicate/blueprints/intelligence.py:2865` `intelligence_query_api`. Under the combined-board default it
   calls, at `:2927`, `read_combined_intelligence_response(dates=None|[date], sport, limit)`, then times
   `_stage("board_read")` at `:2928`. The `QUERY_STAGE_MS` line is printed at `:3012`, AFTER all six stages,
   and it carries no pid.
2. `pipeline/intelligence_state.py:10492` `read_combined_intelligence_response`.
   - The cache key is `(sorted dates, sport, limit)`. The page sends no date, so the key is the default
     3-date window.
   - `:10533` reads `_COMBINED_INTELLIGENCE_RESPONSE_CACHE` (`:10045`), a PER-PROCESS dict.
   - A hit needs age < `SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS` (fleet web: **180**) and no
     newer in-play overlay past `SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS` (fleet web: **22**). The
     overlay rule is `_combined_board_overlay_state` (`:10131`), one `stat` per sport and date.
   - **Nothing in the key or the expiry reads the published board's version.** A newly published board
     reaches a worker only through TTL or overlay expiry. So suspect (b), as framed, is TTL expiry.
   - On a miss, `:10557` takes the in-process single flight: one thread rebuilds, the others serve the
     previous value up to TTL x 10 old or wait.
3. The rebuild (all of it is `board_read`):
   - `:10598` reads each window date's state payload (`_read_single_date_response_for_combining`, `:10427`;
     the on-disk read and expand at `:10480`);
   - `:10740` restates live rows against the scoreboard (`_refresh_layer2_live_state`);
   - builds the board contract;
   - `:10802` merges the Layer 2 card shards (`_layer2_fallback_recommendations`);
   - rebuilds the contract, then slices.
   - It writes the cache at `:11046`. In the log, one cold read is `COMBINED_BOARD_STATE_DATE_MISS` ->
     `COMBINED_STATE_LIVE_RESTATED` -> `LAYER2_CARD_SHARD_MERGE` -> `LAYER2_SHARD_MERGE` ->
     `LAYER2_LIVE_RESTATED` -> `INTEL_TRACE board_input`. At 18:23:45-49Z it took 1.9 s for the state reads,
     1.4 s for the shard merge and 0.9 s for the rest.
4. The warmer (`:10191` `_warm_combined_board_overlays_once`, started lazily at a process's FIRST
   combined-board call by `:10247`, logged at `:10261` as `COMBINED_BOARD_OVERLAY_WARMER_STARTED pid=...
   interval_s=5 window_s=600`).
   - **What it warms:** every key a request in THIS process asked for in the last 600 s, and only when a
     NEWER OVERLAY landed.
   - **What it does not warm:** it never refreshes on TTL expiry. It never runs in a process before that
     process's first board call. It cannot see the other worker's cache.
   - It does keep a watched key fresh through a live evening: 366 rebuilds in 6 h on 11-18, p50 11 s,
     p90 21 s. The two workers each rebuild the same overlay change.
5. `gunicorn.conf.py:294` `decide_recycle` (lane `web-silent-worker-kills` owns this file).
   - The anon limit is ~620-650 MB (`anon_limit_mb`, `:98`); the minimum age is 120 s (`min_age_seconds`, `:116`).
   - A worker that has served the board sits far above the limit. At recycle on 11-18 5-11 PM CST
     (n 82): anon p50 980 MB (p10 797, p90 1,225), age p50 274 s, 15 requests; 75 of the 82 were hard.
   - Growth is board-driven. `GROWTH_EPISODE` 17:52Z: 133 -> 989 MB over 7 requests, 2 of them board
     queries.

## Attribution (measured; instrument `scripts/rail_monitor/coldread_attrib.py`)

Each cold query (board_read > 2,000 ms) gets ONE class, from the marker lines printed inside its
board_read window:
- `boot_cold`: `WARMER_STARTED` printed in the window, i.e. this was the process's first combined-board call;
- `overlay`: `COMBINED_BOARD_OVERLAY_EXPIRED` in the window;
- `ttl_sure`: neither, and no build of any kind ended in the 180 s before;
- `ttl_or_peer`: neither, and a build ended < 180 s before, on a worker the log cannot name.

The attribution itself was run before the lane opened. The lane records this.

| window (CST) | queries | cold | boot_cold | TTL | overlay | warm total p50 | all p50 / p90 | recycles/h |
|---|---|---|---|---|---|---|---|---|
| 11-17 5-11 PM | 370 | 198 (53.5%) | **151 (76% of cold)** | 24 (12%) | 23 (12%) | 4.1 s | 6.4 / 16.3 s | 28.5 |
| 11-18 5-11 PM | 125 | 75 (60.0%) | **69 (92% of cold)** | 2 (3%) | 4 (5%) | 4.3 s | 7.2 / 16.1 s | 13.7 |
| 11-19 7 AM-1 PM | 60 | 41 (68.3%) | 24 (59%) | 13 (32%) | 4 (10%) | 3.7 s | 6.4 / 14.0 s | 4.0 |

- Cold board_read p50: boot_cold 5.3 s on 11-18 (4.2 s 11-17, 3.9 s 11-19); TTL 4.8-9.7 s; overlay 3.9-7.0 s.
- The 11-17 evening predates the hard-recycle stagger (loaded 11-18 19:14Z). The 11-18 evening is after it.
- Per-request rows: `C:\tmp\coldread\rows_1117_evening.txt`, `rows_1118_evening.txt` and `rows_1119_day.txt`.
  They give time CST, class, projection, board_read ms and total ms.

**The rail monitor's reading 4 example** (18:45:45Z, board_read 16,461 ms, on a worker 1,533 s old, read there as
"a new board version alone makes the read cold") classifies `ttl_sure` here, as does the 18:37:15Z read (10,893 ms).
No build of any kind ended in the 180 s before either one. It was midday with no overlays landing, so the warmer
never ran, and the worker's own entry simply expired. The new board reached the worker THROUGH that TTL expiry; the
code never reads the board's version. Same observation, named by mechanism.

**Verdict.** Suspect (a) is the cause on a live evening: 76-92% of cold reads were a NEW worker's first
board read. Suspect (b) is TTL expiry, and it only matters on quiet daytime hours: 32% of cold reads on
11-19's morning, with 4-7 queries an hour and no overlays to drive the warmer. Overlay expiry is 5-12%.
H-a was NOT falsified: 92% and 76% are both well above the registered 50%.

## Levers weighed

| lever | cold reads it removes | memory | verdict |
|---|---|---|---|
| Warm at worker boot, before accepting | boot_cold, but only if the overlay warmer also arms at boot; an evening overlay lands every ~1-2 min | **Raises recycles.** A built board puts a worker at ~980 MB against a ~634 MB limit, so every new worker would be recycled at its 120 s minimum age | REJECTED |
| Pre-read each newly published board in every worker | TTL (b) | Same objection, plus the 2-worker duplicate builds that already cost 366 warmer builds in 6 h | REJECTED |
| Make the build cheaper | all classes, partly | Unknown. It means restructuring the state read / shard merge, a separate study | LEAD (not taken) |
| **Share one worker's build with the others** | boot_cold, overlay, TTL-on-one-worker | Neutral to lower. An adopter lands the SAME objects the first request would have built, without the build's transients. The copy is streamed in 64 KB pickle frames, so there is no 40 MB bytes object on either side | **BUILT** |

- Load cost, measured on the rail monitor's recorded 4,622-row board (`C:\tmp\railmon\q.json`, Idle priority):
  - streamed pickle round trip: write 0.38-0.43 s, load 0.51 s, 36.9 MB, `==` equal;
  - marshal loads in 0.51 s but builds the whole 41 MB bytes object first, so it was not used;
  - a cold build costs 3.9-8.8 s.
- PROJECTION (a MODEL, labelled as one; `coldread_attrib.py` `PROJECTION_model`). For each cold read, would
  the newest build anywhere have been adoptable under the same TTL and overlay rules, or served while
  another worker's build was in flight?
  - 11-18 evening: cold 60.0% -> 14.4% (18 of 125 still cold);
  - 11-17 evening: 53.5% -> 4.9%;
  - 11-19 morning: 68.3% -> 40%. Its TTL misses have no recent build anywhere, so sharing cannot help.

## The fix (on main `9931a787b`, DEFAULT-OFF)

- **Switch:** `SYNDICATE_COMBINED_BOARD_SHARED_COPY`. Absent, empty or any other value = off, the old
  behaviour, and nothing touches the filesystem; a test asserts the directory is never created.
- **Directory:** `SYNDICATE_COMBINED_BOARD_SHARED_DIR`; the default is `/dev/shm/syndicate-combined-board-<uid>`
  (fleet: a 7.7 GB tmpfs, so no disk I/O). It is created 0700 and refused (`COMBINED_BOARD_SHARED_OFF`)
  unless this uid owns it and nobody else can write it.
- **Code:** `syndicate/features/shared/combined_board_shared_copy.py` (new), plus three call sites in
  `read_combined_intelligence_response`: the import, the miss path after the in-process single flight,
  and the publish after the cache write and release.
- **What happens on a miss:** the thread that owns the in-process rebuild, in order:
  1. adopts another worker's NEWER copy that is fresh by this cache's own TTL and overlay rules
     (`COMBINED_BOARD_SHARED_ADOPTED ... from_pid age_s load_s rows own=empty|expired warm=0|1`). The copy
     goes in under the BUILDER's stamp and overlay, so the TTL runs from the build, not from the load;
  2. takes the cross-worker build lease (O_EXCL file; a 90 s deadline like the in-process single flight;
     a dead pid or this process's own leftover lease is taken over), builds, publishes
     (`COMBINED_BOARD_SHARED_BUILD`, then `COMBINED_BOARD_SHARED_PUBLISHED ... mb write_s`) and releases;
  3. if another live worker holds the lease, serves the newest copy <= TTL x 10 old, shared or its own
     (`COMBINED_BOARD_SHARED_SERVED_STALE source=shared|own`). This is the in-process single flight's
     existing rule between threads, extended across processes. With nothing that young, it builds, as before.
- **Unchanged:** a publish never replaces a newer copy. A corrupt copy, a key mismatch, a wrong Python
  version or any read error is a miss, never an error. The warmer code itself is unchanged; it reaches the
  shared path through the same function, so one overlay change is built once, not once per worker.
- **Tests:** `tests/test_combined_board_shared_copy.py`, 20 passed and 1 POSIX-only skip on Windows.
  - Reachability, parametrized: absent / `off` -> 2 builds across a simulated recycle; `1` -> 1 build and
    an `ADOPTED` line.
  - TTL and overlay-floor parity, both sides of the floor.
  - Served-stale while another worker holds the lease; build when it has no young copy, or the copy is
    past TTL x 10.
  - Lease takeover when dead, expired or this process's own.
  - The warmer adopts instead of rebuilding.
  - Corrupt copy; key mismatch; an older build never replaces a newer copy; cleanup; unsafe directory.
  - The 18 existing combined-board test files: 217 passed.
- **Betting change: NO.** Every caller of `read_combined_intelligence_response` is a web route (blueprints,
  `intelligence_layer2_view`, `hub_summary`, ask), and no worker or execution path reads this cache. It
  changes how fast web serves the board, never which live bets are placed, sized, held or exited.
- **Load = an env change:** `WEB__SYNDICATE_COMBINED_BOARD_SHARED_COPY=1` in `local_production.env`, which
  needs a drained full down/up (env is built only at `up`), plus an ff of `~/Syndicate` to a SHA that
  carries the code. Any ff that carries the code with the switch absent changes nothing.

## PRE-REGISTERED PREDICTION — first live evening (5-11 PM CST) after the load

Reader: `scripts/rail_monitor/coldread_attrib.py <from_utc> <to_utc>` over the evening window. Baseline:
the same window on the last evening before the load. The 11-18 numbers are below.

Load checks (VOID if any is missing): at least one `COMBINED_BOARD_SHARED_ARMED` per booted worker that
served a board; >= 1 `COMBINED_BOARD_SHARED_PUBLISHED`; 0 `COMBINED_BOARD_SHARED_OFF`.

| # | metric | 11-18 5-11 PM | predicted | falsified if |
|---|---|---|---|---|
| P1 | cold share (board_read > 2 s) | 60.0% (75/125) | <= 25% | > 30% |
| P2 | `boot_cold` share of queries | 55.2% | <= 20% | > 25% |
| P3 | query total p50 / p90 | 7.2 / 16.1 s | <= 5.5 / <= 13 s | p50 > 6.3 s |
| P4 | `COMBINED_BOARD_SHARED_ADOPTED` load_s p50 | n/a (bench 0.51 s on 4,622 rows) | <= 1.5 s | > 2.5 s |
| P5 | board builds per hour (`SHARED_BUILD` vs warmer + cold builds) | 73.5 (441 in 6 h) | <= 0.75x the baseline | > 0.9x |
| P6 | SAFETY: recycles per hour AND anon p50 at recycle | 13.7 / 980 MB | within 1.3x / 1.1x | both above -> roll back (switch off at the next down/up) |

- `COMBINED_BOARD_SHARED_PUBLISH_FAILED` should be <= 1% of publishes. If it is more, read the reason
  before anything else: a non-picklable type would make the fix inert.
- **CONFOUNDED** if a restart, drain or deploy lands in the window, or the page was not open
  (< 30 queries).
- The TTL class on quiet daytime hours is NOT predicted to change: no build exists for a copy to come from.

## LOAD DECISION (2026-11-19 ~6:20 PM CST)

- **The user, in session eb973f38**, to "How should the shared-copy switch be loaded on the fleet?": **"Ride along next restart"**.
- **Queued** as droppable CHANGE F of batch task `nfl-level-refit-load-1120`: Tue 11-24 2:15 AM CST, one claimed ff +
  one drained full down/up. It adds `WEB__SYNDICATE_COMBINED_BOARD_SHARED_COPY=1`. It is not a betting change: the
  batch registers no betting-change row for F, and if the batch does not load F, F rides the next drained down/up.
- **Kit** `/mnt/c/tmp/w1124_853/`, self-tested 6:24 PM CST.
- **The first live evening after the load** is read against P1-P6 above. If the batch loads at ~2:30 AM CST 11-24,
  that is 11-24 5-11 PM CST; the baseline is the same window on 11-23.

## READING 2026-11-20 ~9:40 AM CST: the 11-19 evening, a third pre-load evening; P3 restated BEFORE any load

Read with `/mnt/c/tmp/w1124_853/coldread_attrib.py 2026-11-19T23:00:00 2026-11-20T05:00:00`, read-only at nice 19. The
switch is not loaded, and the shared-copy markers read 0.

| 11-19 5-11 PM CST | value |
|---|---|
| queries | 195 |
| cold (board_read > 2 s) | 114 (58.5%) |
| new worker's first read / overlay / TTL | 96 (84% of cold) / 14 (12%) / 4 (4%) |
| cold board_read p50 | 3.3 s (new worker) |
| query total p50 / p90 | **5.17 / 10.80 s** (warm p50 3.09 s, cold new-worker p50 6.06 s) |
| warmer rebuilds | 465 (p50 9 s, p90 17 s) |
| recycles | 100 = 16.7/h; anon p50 at recycle 990 MB (p10 820, p90 1,117) vs limit p50 633; 97 hard; age p50 211 s |
| PROJECTION (model) | cold 58.5% -> 8.7% |

- **H-a holds on a third evening.** New-worker first reads are 76-92% of cold reads on all three evenings.
- **P3 as written is NON-DIAGNOSTIC.** Its absolute threshold (p50 <= 5.5 s) came from 11-18's 7.2 s, and 11-19
  already met it without the fix (5.17 s). The evening-to-evening spread is wide:
  - p50 7.2 / 6.4 / 5.2 s;
  - recycles 13.7 / 28.5 / 16.7 an hour.
- **P3 RESTATED NOW, before any load or any post-load data.** It is now relative to the baseline evening (the same
  5-11 PM CST window on the last evening before the load, read with the same reader):
  - predicted: query total p50 <= 0.85x the baseline AND p90 <= 0.85x;
  - falsified: p50 > 0.95x the baseline.
  - Basis: the warm p50 (3.1 s) plus a ~0.5-0.7 s adopt on the reads that would have been cold puts the p50 near
    0.70-0.75x.
  - The batch prompt's abbreviated P3 line is superseded by this one.
- P1, P2 and P4-P6 are unchanged. 11-19's numbers sit inside the variance already allowed.

**Fleet memory on the 11-19 evening.** From live-odds-worker's `ALL_PROCESS_MEMORY` lines (accounted RSS across all
fleet processes; RSS double-counts shared pages):

| | p50 | p90 | max |
|---|---|---|---|
| fleet | 8.8 GB | 9.8 GB | 12.0 GB |
| web (gunicorn master + 2 workers) | 1.16 GB | 2.0 GB | 2.87 GB |
| board child | 4.2 GB | | |

The WSL VM has 15.7 GB, and the web role has no cgroup cap (`gunicorn.conf.py`'s own note, read 2026-11-18).

**LEAD (not followed; the recycle RATE, which #853 does not change).** `SYNDICATE_WEB_WORKER_ANON_LIMIT_MB` defaults
to 650, sized for Render's 2,048 MB container (`gunicorn.conf.py` `anon_limit_mb`). Every worker that serves the
board crosses it within ~3.5 min of age (p50 211 s), so recycles run 14-29 an hour.
- #853 makes each recycle cheap for the board query.
- A higher limit would make recycles RARE for every route. The portfolio monitor tied 2 of 3 slow `live_today` reads
  on 11-19 to a recycle.
- Cost: roughly +0.5-0.7 GB per worker against the measured ~2.5-3.7 GB headroom at the evening max.
- It needs its own measurement (worker anon growth vs age past the first build) and pre-registration.
- The memory guard's code is lane `web-silent-worker-kills`' file, although an env key does not edit it.
- It is the user's decision.

## READING OWNERSHIP + P3 RESTATED AGAIN (2026-11-20 ~10:00 AM CST, before any load)

- **The user, in session eb973f38**, answered "Who should take #853's first-evening reading on 11-24?" with **"Rail
  monitor takes it"**. Lane `layer2-rail-monitor` owns the reading, as it owns #851's.
- **Reader:** `scripts/rail_monitor/p853_readout.py`; a copy is in `/mnt/c/tmp/w1124_853/`. It runs
  `coldread_attrib.py` on both windows and prints the load check, the CONFOUNDED test and P1-P6 graded as registered.
- **Command, after 11 PM CST on the first evening F is live:**

      cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/w1124_853/p853_readout.py \
          2026-11-23T23:00:00 2026-11-24T05:00:00 2026-11-24T23:00:00 2026-11-25T05:00:00

  - That is for a load at the 11-24 2:15 AM CST batch: baseline 11-23 5-11 PM CST, after 11-24 5-11 PM CST.
  - If F loads at another down/up, shift both windows to the evening before and the evening after that load.
- **Dry run (pre-load 11-18 as baseline, pre-load 11-19 as "after"):** every row reads `VOID (would read ...)`
  because no shared-copy line exists. The baseline fresh-worker penalty reads 5,307 ms.

**P3 restated a second time, and why.** The dry run graded the 11-20-morning P3 (whole-evening p50 and p90 <= 0.85x
the baseline) PREDICTED between two evenings WITHOUT the fix (x0.72 / x0.67). Whole-evening latency moves that much
with board size and host load, so no threshold on it can separate the fix from the evening.

P3 is now the **fresh-worker penalty inside the AFTER evening**: the query total p50 of queries that ADOPTED a shared
copy, minus the total p50 of warm queries that touched no shared-copy marker, both from the same evening.
- Predicted <= 1,500 ms; falsified > 2,500 ms.
- Without the fix the same-evening penalty (new-worker cold minus warm) was 5.3 s on 11-18, 3.8 s on 11-17 and
  3.0 s on 11-19. All three sit above the falsification line, so the test can fail.
- Whole-evening p50 / p90 stays in the readout as EXPLORATORY, not graded.
- P1, P2 and P4-P6 are unchanged.
- The batch prompt's abbreviated P1-P6 list is superseded by this file and the reader.

## READING 2026-11-24 ~11:25 PM CST: the first live evening after the load (lane `layer2-rail-monitor`, R-G; read-only)

- **Load:** CHANGE F of the 11-24 window batch (deploys.md 2026-11-24 08:30:10Z entry, F MET at load time):
  `COMBINED_BOARD_SHARED_COPY=1` on the web master and both workers.
- **Command**, run at 05:20Z 11-25 (after the AFTER window closed), nice 19, rc 0. The reader is the registered
  `p853_readout.py` (copy `C:\tmp\railmon\p853\`), and the output is `C:\tmp\railmon\p853\readout_1124.txt`:

      cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p853/p853_readout.py \
          2026-11-23T23:00:00 2026-11-24T05:00:00 2026-11-24T23:00:00 2026-11-25T05:00:00

- **LOAD CHECK: MET.** ARMED 157, PUBLISHED 530, OFF 0, PUBLISH_FAILED 0, READ_FAILED 0, SERVED_STALE 482, ADOPTED 275.
- **CONFOUNDED: no**, by the registered rule (>= 30 queries both windows; no gunicorn master start in AFTER).

| # | metric | baseline (11-23 5-11 PM) | after (11-24 5-11 PM) | verdict |
|---|---|---|---|---|
| P1 | cold share | 16.9% (20/118) | 15.8% (59/374) | PREDICTED |
| P2 | new-worker first-read share | 14.4% | 9.6% | PREDICTED |
| P3 | fresh-worker penalty ms (same evening) | 2626 (cold) | 1128 (adopted, n 85) | PREDICTED |
| P4 | adopt load_s p50 | n/a | 0.66 (n 275) | PREDICTED |
| P5 | builds per hour | 77.7 | 89.3 (x1.15) | FALSIFIED |
| P6 | SAFETY recycles/h, anon p50 at recycle | 11.2/h, 933 MB | 26.5/h (x2.37), 1022 MB (x1.10) | WATCH |
| EXPLORATORY | query p50 / p90 ms, whole evening | 3729 / 5743 | 3738 / 5591 (x1.00 / x0.97) | not graded |

- **What the verdicts carry:**
  - **P3 and P4 are the fix's own test, and both are PREDICTED.**
    - A fresh worker that adopted a copy paid 1.1 s over a warm query. Without the fix, a fresh worker's cold read
      paid 2.6 s on 11-23 and 3.0-5.3 s on 11-17..11-19.
    - An adopt loaded in 0.66 s p50 over 275 adopts.
  - **P1 and P2 are PREDICTED, but the baseline already met them.** The 11-23 evening was 16.9% cold and 14.4%
    first-read, against 60.0% / 55.2% on 11-18. So they show no regression; they are not evidence for the fix.
  - **P5 is FALSIFIED as registered: builds rose x1.15, where <= 0.75x was predicted.** The reader's own note says
    AFTER counts every route's `COMBINED_BOARD_SHARED_BUILD` and the baseline does not, so the comparison leans
    against the fix. Even so, the mechanism did not cut builds.
  - **P6 reads WATCH, not ROLL BACK.** Recycles per hour are above 1.3x, and anon at recycle (x1.095) is under 1.1x.
- **P6 is confounded by a web change the registered rule does not see.** Lane `web-silent-worker-kills` reverted web's
  GC tuning at 15:57:59Z 11-24 (deploys.md), between the two windows. The registered rule only looks for a gunicorn
  master start inside AFTER.
  - **Baseline:** every worker booted tuned: 67 boots, 67 `WEB_WORKER_MEMORY_RECYCLE`, 67 `WEB_GC_TUNED` applied true.
  - **After:** every worker booted untuned: 159 boots, 159 recycles, 159 applied false.
  - Neither window had a `WORKER TIMEOUT` or a `was sent SIGKILL`. Every worker exit was the memory recycle
    (`limit_mb` 630, anon ~1,050 MB, age ~4 min at the newest line, 05:18:53Z).
  - Before the GC tuning, #857 measured 14-29 recycles an hour on evenings. The after evening's 26.5/h sits inside
    that range, and the tuned 11-23 baseline (11.2/h) sits below it. So the x2.37 cannot be attributed to F.
  - The `/rail-watch` web route also loaded between the windows (15:43:16Z, lane `rail-watch-fleet-page`).
  - Script: `C:\tmp\railmon\p853\p853_confound_1124.sh`.
- **Action:** none on F. ROLL BACK did not trigger. #857 (the 1,500 MB recycle limit, user 11-20 "Yes, after #853")
  is now unblocked and rides the next drained full down/up. It is predicted to cut recycles to <= 2/h, which also ends
  P6's WATCH.

## Leads (not followed)

- A daytime TTL miss (32% of 11-19 morning's cold reads) could be served stale-while-revalidate: serve the
  <= TTL x 10 copy and rebuild in the background. That is a freshness change, and a separate decision.
- The rebuild itself (state reads 1.9 s, shard merge 1.4 s on a 3-date window) has not been profiled
  further.
- The warmer's `COMBINED_BOARD_OVERLAY_WARMED` line reports `rebuilt=False` when it adopts. The SHARED_
  lines carry the detail, and the reader excludes those passes from builds.
