# Layer 2 Games Rail — always-on monitor AND improvement hunt, 2026-11-19 (lane `layer2-rail-monitor`)

Day 5 of the monitor, and the first day it runs ALWAYS ON.
- **User, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward".** The monitor opens itself
  each day at ~10:30 AM CST, reads through the slate and closes itself after the last game.
- The 11-17 standing instruction still holds: **"ensure not only are we monitoring but we should ALSO be looking for any
  and all optimizations or improvements that we can make"**.
- Runbook: `C:\tmp\railmon\MONITOR_RUNBOOK.md` (repo backup `scripts/rail_monitor/`, last `853a26cca`).
- Live dashboard: https://claude.ai/artifact/HoJ2n52ewHZnVDbN2LpxaJ.
- Day 4 (11-18): `.syndicate/findings_2026-11-18_layer2_rail_monitor.md` (daily summary `a98871d7b`); page
  https://claude.ai/artifact/ESGaWMYhR7JH6EWfeqiViY.
- Times are Central (CST) unless marked Z.

## Starting state, read 10:37 AM CST (16:37Z)

**Fleet:** `d78a448c4`, from the 10:58 PM 11-18 ff (fleet reflog).
- refresh-worker pid 152916, NOT restarted since 11-18. The board child respawns, about every 30-40 min overnight on
  memory-guard recycles.
- live-odds-worker pid 974825.

**Loads since the 11-18 close:** none. The last two were 11-18's:
- 10:46 PM: suggested recorder `199d6c529`, board-child TERM.
- 10:58 PM: I-17 card fix + calibrated-total score floor `d78a448c4`, ff only. The card fix is on web; the floor is
  live in the board child, but NOT in the refresh-worker parent until its next restart.

**Loading today:** the memory-guard fix (todo #850, lane `board-split-memory-guard`, session local_d0f83044).
- The user typed "11-19 midday" to "When should the four fix switches load on the fleet?".
- Plan from ~10:55-11:00 AM CST: a drained full down/up to `38c3a6905`, 4 `REFRESH_WORKER__` keys, and
  `--outside-window "broken money path"`.
- Ride-along per that lane: #847 and #848, both default-off with their keys absent.
- **The down/up also restarts the refresh-worker parent, which picks up the score floor.**

**Owned readings since 11-19 (`853a26cca`; user "Yes, consolidate", relayed by local_1f10ce63):**
- the I-17 score floor (R-A);
- #844 newest-stamp-by-time (R-B).

**The slate (chips by date, read 10:37 AM):**

| sport | games | first (CST) | last |
|---|---|---|---|
| NCAAB | 29 | 1:30 PM | 10:00 PM |
| WNCAAB | 45 | 10:00 AM (5 live at 10:37) | 9:00 PM |
| NHL | 12 | 6:00 PM | 9:00 PM |
| NCAAF | 1 | 6:30 PM | |
| NBA | 4 | 7:10 PM | 7:10 PM |
| NFL (TNF) | 1 today | 7:15 PM IND @ HOU | |
| soccer | today's subset of 282 by date | 6:30 PM CIN @ ORL | |

## PRE-REGISTERED (written before the first game of the population; POP_START = this block's push time, below)

Population: flags on games commencing after POP_START. The WNCAAB games already live at 10:37 AM go to the
EARLY bucket.

Standing predictions (runbook):
- **P1:** 0 rail-card contradictions ("ours" across the flagged line at model P > 0.5). The card fix has been on web
  since 11-18 10:59 PM.
- **P2 (board cadence):** over 5:30-10:30 PM, the today-board publication gap median <= 600 s and no gap > 1,800 s.
- **P3:** first-reading flags hit at or below their fair.
- **P4:** long-shot flags (book fair < 0.40) hit at most fair + 2 pp. This is evidence for per-line calibration (#847),
  never a gate.
- **P5 (report):** NCAAB calibrated live full totals: hit vs fair, the side mix, and the flagged lines' over share.
- **P6:** 0 pregame NCAAB / WNCAAB totals flags (BC-048).

Day-specific:
- **P7 (#850 memory-guard load; the owner's §5 prediction, copied, not mine):**
  - 5-10 PM refusals: <= 1 an hour and <= 3 in total;
  - child recycles: <= 2, all rc 75 `reason=recycle`, none rc -6;
  - the longest `BOARD_BUILD_TIMING` gap: <= 900 s.
  - Load checks: `BOARD_PROCESS_CHILD_SWITCHES raw_lifeline=1 recycle_after_build=1 ceiling_credit=7168+768`.
  - The owner grades it; the monitor reports the same numbers from its own reading.
  - If the load does not happen today, P7 is VOID, and P2 is expected to FAIL again, as on 11-18 (7 recycles).
  - **Comparability:** today's slate is lighter in the NBA (4 games). The P2 verdict reads live games at 7 PM against
    11-18's.
- **P8 (owned R-A, the I-17 score floor):** after the refresh-worker parent restarts with `d78a448c4`, 0 college
  calibrated full-game total rows on the live rail with `live_total` below the points already scored.
  - Before the restart: violations allowed (11-18 r16: 11 of 262).
  - Falsified if: any violation in a reading taken after the restart, on a row priced after it.
- **P9 (owned R-B, the #844 baseline, CHANGE D not loaded):**
  - while NCAAB is live: `mismatch` > 0 and `h2h_row_fresh` well below `h2h_cell_fresh`;
  - NBA: `mismatch` 0.
  - This is the baseline the 11-24 verdict compares against, not a pass/fail on its own.

POP_START: **2026-11-19T16:40Z** (written before the push; games commencing at or after this time are the population).

## Reading 1 — 10:39 AM CST (16:39Z), day start

- **Live:** 5 WNCAAB games, all in Q2. 13 live rail rows; **0 flags shown**, 0 false, 0 missed, 0 dark.
- **P1 (card contradictions):** 0. **P6 (pregame college totals flags):** 0.
- **P8 (score floor, before the parent restart):** 0 violations of 26 calibrated college full-game total rows.
- **Team cards:** 94 chips today, 0 defects (flipped, detail, chip-less).
- **Load:**
  - `/intelligence` 8.42 s (4.59 MB on the wire);
  - `/api/intelligence/query` 6.19 s (4.24 MB);
  - shortlist 0.89 s; chips 0.22 s.
- **Board (9:30-10:39 AM):**
  - 12 builds, wall median 161 s, max 205 s, 0 over 300 s;
  - publication gap median 274 s, max 628 s;
  - today's board 259 s old at the read.
- **Memory guard (since 9:30 AM):**
  - 11 `MEMORY_GUARD_ABORT` refusals (guard reading 5,288-5,881 MB of 7,168);
  - 2 child recycles, both **rc -6**: 9:42 AM (attempt 26) and 10:21 AM (attempt 27);
  - parent pid 152916 RSS 2.33 GB, not restarted since 11-18. The child is at 2.66 GB, 18 min after its respawn.
  - The #850 load (local_d0f83044) is due ~11 AM.
- **Live odds:**
  - WNCAAB overlay gap max 64 s, 0 over 360 s; 35 web merges, 0 stale;
  - 20 sweeps launched, 2 refused (`lane_busy`, 9.1%);
  - live rows priced age p50 183 s, p90 730 s, max 816 s (4 of 13 rows over 300 s old at the read).
- **#844 sampler (R-B):** ran at 9:19 AM with 0 rows, before any NCAAB game. It starts with the NCAAB tips (1:30 PM).
- **Improvement hunt:** nothing new at this volume (5 games). Watch the WNCAAB quote-age tail as more games go live: 4 of 13
  rows over 300 s, with p90 730 s.

## Reading 2 — 11:23 AM CST (17:23Z), first reading after the #850 load

**The load (BC-053, lane `board-split-memory-guard`, session local_d0f83044):**
- 11:00 AM (17:00:09Z): a drained full down/up, ff `d78a448c4` -> `38c3a6905`, plus 4 `REFRESH_WORKER__SYNDICATE_BOARD_PROCESS_*` keys.
- The user typed "11-19 midday" in that session. It is recorded as a betting change, outside the window, as a broken money path.
- **Load checks, read here from the fleet log: MET.**
  - `BOARD_PROCESS_CHILD_SWITCHES pid=1011359 raw_lifeline=1 recycle_after_build=1 ceiling_credit=7168+768` (17:00:31Z);
  - `BOARD_PROCESS_CEILING_CREDIT from_mb=7168 to_mb=7936`;
  - `ALL_PROCESS_MEMORY container_memory_max_mb: 7936.0`.
- **The new processes:** refresh-worker parent pid 1011283 at 785 MB; board child pid 1011359 at 3.00 GB, 23 min up;
  live-odds-worker pid 1011284. The parent now carries the I-17 score floor, so **P8 is live from here**.
- **Before the load (the old parent, 10:39-11:00 AM):** 3 more refusals (10:47-10:49 AM) and a third rc -6 recycle (10:52 AM,
  attempt 28). That makes 3 rc -6 child exits today before the fix.
- **After the load (11:00-11:23 AM):** 0 `MEMORY_GUARD_ABORT`, 0 child exits.

**The reading:**
- **Live:** 6 WNCAAB games; 17 rail rows; **0 flags shown**, 0 false, 0 missed, 0 dark.
- **P1:** 0. **P6:** 0. **P8 (score floor, first reading on the new parent):** 0 of 21 rows.
- **Team cards:** 94 chips, 0 defects.
- **Load:** `/api/intelligence/query` **2.24 s** (6.19 s at reading 1, before web restarted); shortlist 0.77 s; chips 0.02 s.
  The page was not fetched this reading.
- **Board (10:39-11:23 AM):**
  - 7 builds, wall median 213 s, max 229 s;
  - publication gap median 338 s, **max 722 s**: the down/up gap, from the last old build to the new child's first, published at
    11:07 AM;
  - today's board 144 s old at the read.
- **Live odds:**
  - WNCAAB overlay gap max 103 s, 0 over 360 s; 63 web merges, 0 stale;
  - 10 sweeps, 1 refused (`lane_busy`);
  - priced age p50 133 s, p90 540 s; 6 of 17 rows over 300 s old at the read.
- **#844 (R-B):** 0 NCAAB rows at 11:23 AM. NCAAB tips at 1:30 PM.
- **Improvement hunt:** the WNCAAB quote-age tail persists (6 of 17 rows over 300 s; p90 540 s), with every overlay gap
  <= 103 s. That points at the books' own quote updates, not the pipeline: `seen_age_at_pricing` p50 5 s. Not a lever yet;
  keep measuring when NCAAB adds volume.

## Reading 3 — 12:02 PM CST (18:02Z)

- **Live:** 6 WNCAAB games; 12 rail rows; **0 flags shown**, 0 false, 0 missed, 0 dark.
- **P1:** 0. **P6:** 0. **P8 (score floor):** 0 of 9 rows.
- **Team cards:** 94 chips, 0 defects.
- **P7 (#850), 11:23 AM-12:02 PM:** 0 `MEMORY_GUARD_ABORT`, 0 child exits.
  - The board child (pid 1011359) has been up 62 min and is at 3.47 GB RSS (3.00 GB at 23 min). The parent is at 769 MB.
  - Board: 8 builds, wall median 178 s, max 300 s (1 over 300 s); publication gap median 267 s, max 415 s.
- **R-E (#838 NHL timeout watcher), first run:** 1 NHL generation step since 11:23 AM, 0 timed out, no marker.
- **Instrument fix (self-match).** My first watcher run counted 3 `NHL_LIVE_GENERATION_COOLDOWN` lines. All 3 were
  `ALL_PROCESS_MEMORY` lines quoting my own grep's command line. `d4metrics.py`'s `nhl_generation_markers` /
  `nhl_generation_cooldowns` had the same hole. Both now skip `ALL_PROCESS_MEMORY` lines, and both read 0 on re-run.
  Readings before this one may have over-counted these two fields whenever a grep was running.
- **Live odds:**
  - WNCAAB overlay gap max 65 s, 0 over 360 s; 49 web merges, 0 stale;
  - 15 sweeps, 1 refused;
  - priced age p50 82 s, p90 839 s (4 of 12 rows over 300 s).
- **Load: `/api/intelligence/query` 10.28 s** (2.24 s at reading 2). Three back-to-back fetches at 12:05 PM: 10.3, 14.2,
  5.4 s.

**Improvement I-28 (new): the board query's `board_read` is cold on most requests.**
- **What happens:** the stage costs 3.9-8.8 s on a cold worker, against 1-40 ms warm (`QUERY_STAGE_MS`). It is cold after
  every web worker memory recycle and every newly published board.
  - The recycles: `WEB_WORKER_MEMORY_RECYCLE`, hard, at anon 920-1,045 MB against a ~620-650 MB limit. There were 13 in the
    11 AM hour, and 20-45 an hour on recent evenings.
  - With 2 workers, each one reads every new board version for itself.
- **Measured** (`C:\tmp\railmon\qstage.py`, from the web log):

  | window | queries | cold `board_read` | cold total p50 | warm total p50 | all p50 / p90 |
  |---|---|---|---|---|---|
  | 11-18 5-11 PM | 125 | **75 (60%)**, p50 5.36 s | 9.63 s | 4.32 s | 7.21 / 16.07 s |
  | 11-19 7 AM-1 PM | 53 | 37 (70%), p50 3.90 s | 6.88 s | 4.97 s | 6.35 / 13.89 s |

- **The lever:** take the board read off the request path. For example, each worker could pre-read a newly published board
  in the background (`COMBINED_BOARD_OVERLAY_WARMER` already runs at boot; it is unclear what it warms), or the read could
  be made cheaper. That would move the page's query from ~7 s at the median toward the ~4.3 s warm path.
- **Already known and owned elsewhere:**
  - lane `web-silent-worker-kills` owns the recycle path (the double-recycle fix is loaded);
  - the I-13 response cache was rejected because read-time merges change every response (todo #828).
  - Neither covers the cold board read itself. Owner: none yet; proposed as its own session (below).

## Reading 4 — 12:45 PM CST (18:45Z), full page

- **Live:** 1 WNCAAB game between windows, 0 rail rows. 0 flags; P1 0; P6 0; P8 0 of 0 rows. Team cards: 94 chips, 0 defects.
- **P7 (#850), 12:02-12:45 PM:** 0 `MEMORY_GUARD_ABORT`, 0 child exits.
  - Board child at 3.41 GB, 105 min up.
  - Board: 7 builds, wall median 215 s, max 416 s (3 over 300 s); publication gap median 353 s, max 544 s.
  - These are midday numbers with pregame look-ahead (602 s) and pregame (485 s) runs in the window. P2 is graded on the evening.
- **R-E:** 3 NHL generation steps since 12:02 PM, 0 timed out.
- **Live odds:** 18 sweeps launched, 4 refused (`lane_busy`, 18.2%). Overlay gap max 73 s. The 603 s refresh-tick gap is
  the lull between game windows, the same shape as reading 1's.
- **Load:** `/intelligence` page 11.59 s; **`/api/intelligence/query` 21.09 s**; shortlist 1.42 s; chips 1.30 s.

**I-28 update: a new board version alone makes the read cold.**
- The probe's query logged `board_read` 16,461 ms of 20,823 ms total (18:45:45Z), on worker 1033465. That worker had been
  up 1,533 s and had served 25 requests, so this was not a fresh worker: the board had changed since its last read.
- **So both causes are real:**
  - (a) worker recycles: 18:20:04Z hard recycle, then the new worker's first `board_read` took 10,819 ms;
  - (b) new board versions, each read by each worker for itself.
- **Since 12:02 PM (`qstage.py`):** 12 queries, 6 cold (50%). Cold `board_read` p50 8.77 s, cold total p50 13.56 s, warm
  total p50 4.86 s.
- Cold reads ranged 4.4-16.5 s this window. Session card task_6b228341 is proposed and not yet started.
