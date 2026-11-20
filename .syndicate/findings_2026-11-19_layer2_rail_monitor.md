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

## Reading 5 — 1:36 PM CST (19:36Z), NCAAB's first game live

- **Live:** 1 game, Florida @ West Virginia (NCAAB), with 18 rail rows. No WNCAAB game is live.
- **Flags: 3 shown on 1 card, 0 false, 0 missed, 0 dark.**
  - full-game total u144.5 (model 0.547 vs fair 0.509, ours 142.7);
  - first-half total u68.5 (0.588 vs 0.492, ours 65.6);
  - moneyline WVU (0.297 vs 0.213, a long shot in the P4 slice).
- **P1:** 0 contradictions; both totals have ours on the flagged side of the line. **#824 (below points):** 0.
  **P6:** 0. **P8 (score floor):** 0 of 9.
- **Team cards:** 94 chips, 0 defects.
- **P7 (#850), 12:45-1:36 PM:** 0 `MEMORY_GUARD_ABORT`, 0 child exits. The child is at 3.75 GB after 2.6 h up (3.00 GB at
  23 min, 3.47 GB at 62 min, 3.41 GB at 105 min).
  - Board: 12 builds, wall median 164 s, max 228 s, 0 over 300 s; publication gap median 246 s, max 338 s.
- **R-B (#844 baseline, sample 1):** NCAAB 14 grid rows (7 venue), h2h 1, `h2h_row_fresh` 0 vs `h2h_cell_fresh` 1,
  **`mismatch` 3**; NBA 0 rows (not live). This is the predicted shape: mismatch > 0, row-fresh below cell-fresh.
- **R-E:** 2 NHL steps since 12:45 PM, 0 timed out.
- **Live odds:**
  - NCAAB overlay gap max 37 s; 12 sweeps, 0 refused;
  - priced age p50 116 s, p90 285 s (3 of 18 rows over 300 s);
  - all 5-6 web merges list `wncaab` as stale: no WNCAAB game was live, so that overlay has nothing new. Not a defect.
- **Load:** query 3.42 s (a warm read), shortlist 0.98 s, chips 0.20 s.
- **I-28:**
  - Since 12:45 PM: 9 queries, 8 cold (89%), cold total p50 7.07 s, warm 2.56 s.
  - The session (local_a5513c97) attributed it: 69 of the 75 cold reads on the 11-18 evening were a NEW worker's first read
    after a memory recycle. The other kind is a 180 s cache expiry; nothing in the cache reads the board's version.
  - Its fix is todo #853 (`9931a787b`, `SYNDICATE_COMBINED_BOARD_SHARED_COPY`, default off): a shared copy in `/dev/shm`.
    Prediction: cold <= 25%, query p50 <= 5.5 s, p90 <= 13 s.
  - The load (env key + a drained full down/up) is the user's decision, asked in that session.

## Reading 6 — 2:13 PM CST (20:13Z)

- **Live:** 1 game, NCAAB WVU / Florida (ESPN 401920517), H1 3:38, Florida 32-23; 18 rail rows. **0 flags.**
- **P1:** 0. **P6:** 0. **P8:** 0 of 0 calibrated rows; there are none (see I-29). **Team cards:** 94 chips, 0 defects.
- **P7 (#850), 1:36-2:13 PM:** 0 refusals, 0 child exits. The child is at 3.83 GB after 3.2 h.
  - Board: 9 builds, wall median 165 s, max 197 s; publication gap median 246 s, **max 264 s**.
- **R-B (#844 sample 2):** NCAAB 11 rows (4 venue), h2h 1, row-fresh 1 = cell-fresh 1, `mismatch` 1. NBA 0 rows.
- **R-E:** 3 NHL steps, 0 timed out.
- **Live odds:**
  - NCAAB's own live lane ran 37 times in 37 min (`NCAAB_LIVE_AUTORUN_LAUNCHED`, 60 s);
  - overlay gap max 147 s; priced age p50 191 s, p90 324 s.
  - `ODDS_SWEEP_LAUNCHED` showed a 26-min gap (1:41-2:07 PM). That is the 1,800 s pregame cadence (`PREGAME_CADENCE_SKIPPED`), not live. Not a defect.
  - 39 of 39 web merges list `wncaab` as stale; no WNCAAB game is live.
- **Load:** query 3.05 s, shortlist 1.13 s, chips 0.17 s. **I-28:** 7 queries since 1:36 PM, 3 cold (43%).

**I-29 (new, live defect): a mid-game home/away flip blacked out the game's live model for 30+ minutes.**
- **The flip:** ESPN 401920517 / odds event `5246df44...` read **"Florida Gators @ West Virginia Mountaineers"** on the chip
  and the rail rows at 10:37 AM and 1:36 PM (away Florida 4, home WVU 0). At 2:13 PM both read **"West Virginia
  Mountaineers @ Florida Gators"** (away WVU 23, home Florida 32).
- **The join since then** (`LIVE_GAMELINE_BUILD sport=ncaab`, `C:\tmp\railmon\lgb.py`):
  - 1:33-1:43 PM: projected 1-14 a build, full_games 1 (flags at reading 5).
  - 1:44:43 PM: considered 0, the rows re-keyed.
  - **From 1:47:41 PM to 2:16:41 PM (latest read), every build has projected 0 and full_games 0.** All full-game
    lines are withheld `no_live_gameline_projection` (21-27 a build), while
    `index_why: games_in_snapshot 1, indexed 1, sources_seen live_resim 1`.
  - The re-sim keeps running: `NCAAB_LIVE_RESIM_TICK live=1 resimmed=1 written=True` every ~8 min, last at 2:17 PM.
  - So the model exists and is indexed under the other orientation; the rows look it up under the new one.
- **Effect:** the live rail cannot flag this game (0 of 18 rows carry `live_model_probability`). The P8 floor and P1 have
  nothing to read. The probe's `dark_rows` / `missed` (0) cannot see it either, because they need a model on the row.
  That is an instrument gap to close.
  - It fails closed: no model, no flag, no bet.
- **Why #791 does not cover it:** the team-alias join is NCAAF-only (`_TEAM_ALIAS_JOIN_SPORTS`) and keys an ordered
  `(away, home)` pair.
- **Open questions for the owner:**
  - which feed flipped: ESPN, the odds API, or both, and at what time;
  - whether this is a neutral-site game listed differently by the two sources;
  - how many of tonight's NCAAB / WNCAAB games could flip.
- Proposed as its own session (below). The monitor will also count rows without a live model per live game.

## Reading 7 — 2:52 PM CST (20:52Z)

- **Live:** 1 game, NCAAB WVU / Florida, H2 13:14; 20 rail rows. 0 flags. P1 0; P6 0; P8 0 of 0. Team cards: 94 chips,
  0 defects.
- **New `live_games_no_model`: 1 of 1 live game** (`ncaab West Virginia Mountaineers @ Florida Gators`).
- **I-29 PERSISTS:**
  - `lgb.py ncaab` shows every build from 1:47:41 PM to 2:52:11 PM (65 min, ~35 builds) at projected 0, full_games 0,
    withheld `no_live_gameline_projection` 14-22 a build.
  - **Cause located:** the re-sim snapshot (Redis `syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/ncaab_live_resim.json`,
    `generatedAt 2026-11-19T14:52:10-06:00`) still holds **away "Florida Gators", home "West Virginia Mountaineers"**,
    `event_id 401920517`, `nameSource: odds`.
  - The odds rows and the chip now read West Virginia @ Florida. The re-sim took its team names from the odds feed's
    orientation at the start and kept them; the odds feed flipped orientation mid-game. The join looks up
    (away, home) by name and misses.
  - Open for the owner: is the re-sim's home-court side also inverted, and does its score mapping follow the ids or
    the names? (`home_id 277`, `away_id 57`.)
  - Card task_dcdd0d3d proposed; not started.
- **P7 (#850), 2:13-2:52 PM:** 0 refusals, 0 child exits. Child 3.87 GB after 3.9 h.
  - Board: 9 builds, wall median 172 s, max 196 s; publication gap median 248 s, max 354 s.
- **R-B (#844 sample 3):** NCAAB 13 rows (6 venue), h2h 1, row 1 = cell 1, `mismatch` 1.
- **R-E:** 1 NHL step, 0 timed out.
- **Live odds:** NCAAB overlay gap max 70 s; priced age p50 119 s, p90 397 s (8 of 20 rows over 300 s); 8 sweeps,
  1 refused.
- **Load:** query 2.64 s. **I-28:** 7 queries since 2:13 PM, 4 cold (57%), cold total p50 5.63 s vs warm 2.83 s.

## Reading 8 — 3:31 PM CST (21:31Z), full page

- **Live:** 2 games.
  - NCAAB WVU / Florida, H2 1:08: 6 rail rows, still with no model.
  - WNCAAB High Point @ Vermont, Q2 7:27: 0 rail rows. Its join considered 0 lines, because no book quotes it live, and its re-sim tick was `refused=1`. Nothing to price, not a join defect.
- 0 flags; P1 0; P6 0; P8 0 of 0; team cards 94 chips, 0 defects.
- **I-29:**
  - `live_games_no_model` is 1 of 1 game with rows.
  - `lgb.py ncaab` shows projected 0 on every build from 2:52 to 3:31 PM; from 1:47 PM that is the whole rest of the game,
    about 1 h 45 min. A typical build withheld 19-29 lines as `no_live_gameline_projection`.
  - Card task_dcdd0d3d is proposed and not started.
- **P7 (#850), 2:52-3:31 PM:** 0 refusals, 0 child exits. Child 3.94 GB after 4.5 h.
  - Board: 9 builds, wall median 179 s, max 217 s; publication gap median 256 s, max 285 s.
- **R-B (#844 sample 4):** NCAAB 14 rows (6 venue), h2h 1, row 0 / cell 0. NBA 0.
- **R-E:** 2 NHL steps, 0 timed out.
- **Live odds:** NCAAB overlay gap max 72 s; 6 sweeps, 0 refused; priced age p50 97 s, p90 209 s.
- **Load:** `/intelligence` 10.44 s; query **9.19 s**; shortlist 1.11 s; chips 0.41 s.
  - **I-28:** 7 queries since 2:52 PM, 3 cold (43%), cold total p50 6.63 s vs warm 2.70 s.
  - Its fix #853 waits on the user's load decision (local_a5513c97).

## Reading 9 — 4:09 PM CST (22:09Z)

- **Live:** 2 games.
  - NCAAB Auburn / Notre Dame, H1 17:57: 18 rail rows, **no model**.
  - WNCAAB High Point @ Vermont, Q3: 0 rows; no book quotes it live.
- WVU / Florida went final ~3:35 PM.
- 0 flags; P1 0; P6 0; P8 0 of 0; team cards 94 chips, 0 defects.

**I-29 is a neutral-site orientation mismatch, and it will recur tonight.**
- **Second game, dark from the tip:**
  - the rail and chip read "Auburn Tigers @ Notre Dame Fighting Irish";
  - the re-sim snapshot (generated 4:09:35 PM, `resimmed 1`) holds **away "Notre Dame Fighting Irish", home "Auburn Tigers"**,
    event 401920519, `nameSource: odds`;
  - `lgb.py ncaab` at 4:08:35 PM: considered 19, projected 0, withheld `no_live_gameline_projection` 12.
- **The mechanism:**
  - `syndicate/features/ncaab/slate.py:202` `orient_neutral_site_games` (since 11-02, commit `92d9e9193`) swaps a
    neutral-site game's home/away to the odds feed's orientation when the feed has only the reversed pair.
  - The Games rail, chips and the rows' matchup follow the reoriented slate.
  - The live re-sim keys its game on ESPN's raw orientation.
  - So every REORIENTED neutral-site game has rows in one order and the model in the other, and the join misses.
  - WVU / Florida flipped mid-game, presumably at the moment the odds feed's pair set first held only the reversed pair. The slate file (fetched 22:10:33Z) shows `reoriented_neutral_site: 4` of 29 NCAAB games.
- **Exposure tonight**, NCAAB neutral-site games on the 11-19 slate (7, of which 4 reoriented):

  | CST | game | venue |
  |---|---|---|
  | 1:30 PM | WVU @ Florida (dark 1:47 PM-final) | Michelob ULTRA Arena |
  | 4:00 PM | Auburn @ Notre Dame (dark from the tip) | Michelob ULTRA Arena |
  | 5:00 PM | NC State @ Murray State | Baha Mar Convention Center |
  | 7:30 PM | Wisconsin @ Seton Hall | Baha Mar Convention Center |
  | 7:30 PM | UNLV @ Rutgers | Michelob ULTRA Arena |
  | 8:00 PM | Oregon State @ Oregon | Moda Center |
  | 10:00 PM | Houston @ Kansas | Michelob ULTRA Arena |

  - 2 more of these 5 should be reoriented, and so dark.
  - WNCAAB has 3 neutral-site games, 0 reoriented.
- **Effect:** these games fail closed (no model, no flag, no bet), so the cost is missed live opportunities, not losses.
  - The fix (re-key the re-sim to the slate's orientation, or an orientation-free join with side mapping) is the
    proposed session task_dcdd0d3d, not yet started.
  - A fix that changes live joins is a betting change. Loading tonight would need the user's
    `--outside-window` reason; otherwise the 11-24 window.

**The rest:**
- **P7 (#850), 3:31-4:09 PM:** 0 refusals, 0 exits. Child 4.08 GB after 5.1 h.
  - Board: 8 builds, wall median 161 s, max 224 s; publication gap median 237 s, max 288 s.
- **R-B (#844 sample 5):** NCAAB 11 rows (3 venue), h2h 1, row 1 = cell 1. NBA 0.
- **R-E:** 1 NHL step, 0 timed out.
- **Live odds:**
  - NCAAB overlay gap max 1,713 s: the lull between WVU / Florida's final and Auburn / ND's tip, with no rows;
  - priced age p50 85 s, p90 262 s.
- **Load: query 24.55 s, chips 9.19 s** (usually 0.2-0.4 s), shortlist 1.16 s.
  - Host load 3.5, with two soccer artifact builds at nice 0 (132% and 102% CPU) at the read.
  - **I-28:** 3 queries since 3:31 PM, all cold, cold total p50 9.0 s.

## Reading 10 — 4:50 PM CST (22:50Z)

- **Live:** 2 games.
  - NCAAB Auburn / Notre Dame, H1 3:31: 16 rail rows.
  - WNCAAB High Point @ Vermont, Q4 0:32: no live market.
- 0 flags; P1 0; P6 0; P8 0 of 0; team cards 94 chips, 0 defects.
- **I-29:**
  - New instrument `C:\tmp\railmon\p29_orient.py` compares each live game's rail rows with the re-sim snapshot's away/home.
  - **Auburn @ Notre Dame: 18 rows, 0 with a model, re-sim `REVERSED`** (event 401920519; snapshot generated 4:49:20 PM).
  - `lgb.py ncaab` shows projected 0 on every build from 4:09 to 4:49 PM.
  - Next exposed tip: NC State @ Murray State at 5:00 PM.
- **P7 (#850), 4:09-4:50 PM:** 0 refusals, 0 exits. Child 4.00 GB after 5.8 h; parent 870 MB.
  - Board: 10 builds, wall median 172 s, max 229 s; publication gap median 248 s, max 355 s.
- **R-B (#844 sample 6):** NCAAB 13 rows (5 venue), h2h 1, **row-fresh 0 vs cell-fresh 1**, mismatch reported. NBA 0.
- **R-E:** 1 NHL step, 0 timed out.
- **Live odds:** overlay gap max 68 s; priced age p50 207 s, p90 293 s (4 of 16 rows over 300 s).
- **Load:** query 5.52 s, chips 0.38 s, shortlist 0.77 s.
  - **I-28:** 38 queries since 4:09 PM (the page is open), 22 cold (58%); cold total p50 5.08 s, warm 2.66 s; all p50 4.84 s.

## Reading 11 — 5:25 PM CST (23:25Z), the evening opens

- **Live:** 11 games: 2 NCAAB, 9 WNCAAB. 5 have rail rows (60 rows).
- **Flags: 1 shown, 0 false, 0 missed, 0 dark.** NCAAB Murray St / NC State full-game u160.5 (model 0.555 vs fair 0.500,
  ours 157.9).
- **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 31.** Team cards: 94 chips, 0 defects.
- **I-29 (`p29_orient.py`):**
  - Auburn @ Notre Dame: 14 rows, 0 with a model, re-sim **REVERSED**. Dark since the 4:00 PM tip.
  - **Murray St @ NC State** (neutral, Baha Mar; ESPN listed "NC State @ Murray State"): 16 of 16 with a model, re-sim
    **direct**. A neutral-site game whose re-sim matches the rows joins normally.
  - WNCAAB: 3 games with rows, all direct, all with a model (15/15, 10/10, 6/6). The WNCAAB re-sim refused 6 of 9 live games;
    those have no rows to join.
- **The live-odds-worker restarted ~5:11 PM CST** (pid 1011284 -> 1111191). The supervisor log reads `exited code=0 after
  22277s -- restarting in 5s`: its routine ~6 h self-recycle (earlier: 19,874 s, 22,723 s). Not a deploy, not a crash.
- **P7 (#850), 4:50-5:25 PM:** 0 refusals, 0 exits. Child 3.92 GB after 6.4 h.
  - Board: 8 builds, wall median 164 s, max 193 s; publication gap median 250 s, max 275 s.
- **R-B (#844 sample 7):** NCAAB 22 rows (7 venue), **h2h 2, row-fresh 0 vs cell-fresh 2, mismatch 3**. This is the predicted
  baseline shape. NBA 0.
- **R-E:** 2 NHL steps, 0 timed out.
- **Live odds:**
  - overlay gap max 74 s; 78 web merges, 28 list `wncaab` stale;
  - priced age p50 183 s, p90 317 s, max 734 s (16 of 60 over 300 s).
- **Load:** query 3.16 s, chips 0.08 s, shortlist 1.06 s. **I-28:** 20 queries since 4:50 PM, 13 cold (65%), all p50 4.87 s.

## Reading 12 — 5:50 PM CST (23:50Z), full page

- **Live:** 15 games (2 NCAAB, 13 WNCAAB); 6 with rail rows (43 rows).
- **0 flags**, 0 false, 0 missed. P1 0; #824 0; P6 0; **P8 0 of 14**. Team cards 94 chips, 0 defects.
- **`live_games_no_model` 2 of 6:**
  - **Auburn @ Notre Dame:** re-sim REVERSED (I-29), H2 7:51, 13 rows, 0 with a model.
  - **Stetson @ UCF (WNCAAB):** 7 rows, 0 with a model; re-sim **direct**, so not an orientation miss.
    - The WNCAAB re-sim tick refused 10 of 13 live games: `no_margin_anchor` 9, `on_floor_incomplete` 1.
    - Most refused games have no live market (no rows). This one does: books quote it live, but the re-sim has no
      pregame margin anchor for it.
    - Lead, not chased: WNCAAB games with a live market and no anchor.
  - Murray St @ NC State: 8 of 14 rows with a model, direct (H1 2:34; some half rows unpriced).
- **P7 (#850), 5:25-5:50 PM:** 0 refusals, 0 exits. Child 4.10 GB after 6.8 h.
  - Board: 5 builds, wall median 182 s, max 218 s; publication gap median 260 s, max 353 s.
- **R-B (#844 sample 8):** NCAAB 23 rows (9 venue), **h2h 2, row-fresh 0 vs cell-fresh 2, mismatch 6**. NBA 0 (tips 7:10 PM).
- **R-E:** 1 NHL step, 0 timed out (NHL starts 6 PM).
- **Live odds:** overlay gap max 69 s; 23 web merges, 0 stale; priced age p50 214 s, p90 327 s.
- **Load:** `/intelligence` 9.27 s; query 2.89 s; shortlist 1.02 s; chips 0.31 s. **I-28:** 6 queries, 3 cold.

## Reading 13 — 6:15 PM CST (00:15Z)

- **Live:** 40 games: 9 NCAAB, 6 NHL (P1), 25 WNCAAB. 22 have rail rows (203 rows).
- **Flags: 8 shown on 6 cards, 0 false, 0 missed, 0 dark.**
  - By sport: NCAAB 11 flagged rows of 123; NHL 1 of 26; WNCAAB 0 of 54.
  - 2 are college full totals.
- **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 121.** Team cards 94 chips, 0 defects.
- **`live_games_no_model` 3 of 22:**
  - **Auburn @ Notre Dame:** REVERSED (I-29), H2 1:31. Dark from tip to final.
  - **St Louis @ Pittsburgh (NHL, P1 15:40):** 4 rows, 0 with a model.
    - NHL's join: full_games 5 of 6, with `no_live_gameline_projection` 6 (this game's lines).
    - The other 5 NHL games have a model on 1-2 of their full-game rows; the rest are `display_only` or have no
      distribution for that market.
    - Early first period; re-check next reading before calling it.
  - **Stetson @ UCF (WNCAAB):** re-sim refused, no margin anchor (WNCAAB re-sim: 19 of 25 live games refused).
  - All 8 other live NCAAB games join **direct**, with a model on every row. That includes Murray St @ NC State (neutral).
- **P7 (#850), 5:50-6:15 PM:** 0 refusals, 0 exits. Child 3.99 GB after 7.2 h.
  - Board: 6 builds, wall median 172 s, max 246 s; publication gap median 248 s, max 326 s.
- **R-B (#844 sample 9), the full evening shape:**
  - NCAAB grid 129 rows (68 venue), `p1_sportsbook_newest` 4;
  - **h2h 9: row-fresh 0 vs cell-fresh 7; mismatch 29.**
  - NBA 0 (7:10 PM tip).
- **R-E:** 0 NHL generation steps in the window, 0 timed out. NHL child odds age max 42 s.
- **Live odds:**
  - overlay gap max 68 s (NHL); 61 web merges, 0 stale;
  - 8 sweeps, 3 refused (`lane_busy`);
  - priced age p50 171 s, p90 382 s, max 771 s (45 of 203 over 300 s).
- **Load:** query **11.56 s**, chips 1.41 s, shortlist 0.72 s. **I-28:** 26 queries since 5:50 PM, 17 cold (65%), all p50 5.29 s.

## Reading 14 — 6:40 PM CST (00:40Z), the 7 PM peak

- **Live:** 45 games: 9 NCAAB, 1 NCAAF, 7 NHL, 28 WNCAAB. 25 have rail rows (249 rows).
- **Flags: 7 shown, 0 false, 0 missed, 3 dark.** Dark means a qualifying flag whose price is now over 300 s old.
  - **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 123.** Team cards 94 chips, 0 defects.
- **Host load 7.91** (5-min 8.11), against 1.6-3.6 all afternoon. At the read, the busiest processes were:
  - an MLS soccer artifact build (98% CPU);
  - live odds refreshes for WNCAAB (96%), NCAAF (58%) and soccer;
  - an NCAAF game-lines fetch (94%);
  - the board child (68%); the live-odds worker (47%); a web worker (55%);
  - two live re-sim workers (22% each, nice 5).
- **Board under that load (6:15-6:40 PM):**
  - **3 builds**, wall median 262 s, max **548 s** (1 over 300 s);
  - publication gap median 502 s, **max 662 s**; today's board 633 s old at the read;
  - 1 deferred slow tick; pregame run max 741 s.
- **P7 (#850): 0 refusals, 0 exits.** The memory guard is not what slowed the board; CPU contention is.
- **Load:** shortlist **10.19 s** (normally ~1 s); query **15.48 s**; chips 0.59 s.
  - **I-28:** 19 queries since 6:15 PM, 9 cold, all p50 10.5 s; warm p50 10.4 s, so CPU contention slows even warm queries.
- **Live odds:**
  - overlay gap max 142 s (WNCAAB); 7 sweeps, 4 refused (`lane_busy`, 36%);
  - NHL child odds age max 371 s; NHL rows' `book_age_seconds` up to 836 s;
  - priced age p50 169 s, p90 580 s (101 of 249 rows over 300 s).
- **`live_games_no_model` 5 of 25:**
  - **I-29 / other college:**
    - **Charleston @ Drake (NCAAB):** `not_in_resim`, 4 rows. Probably tipped after the 6:37 PM re-sim tick; re-check.
    - Stetson @ UCF (WNCAAB): no-anchor refusal, as before.
    - Auburn / ND went final. All 9 other NCAAB games are direct with a model, including Murray St / NC State (7 of 19 rows; half rows unpriced).
  - **NHL: 3 of 7 live games with no model** (STL @ PIT 0/5, BUF @ WSH 0/3, EDM @ TBL 0/7, just dropped).
    - `LIVE_GAMELINE_BUILD sport=nhl index_why`: 12 games in the snapshot, **6 indexed with a `live_resim` lane, 6 `pregame_only`**; full_games 5.
    - NHL live projections come from `nhl_live_generation` runs (the last at 00:20:11Z). A game that dropped after that run has only a pregame lane until the next one.
    - STL @ PIT dropped ~6:05 PM and still has no model 35 min later. Watch: does the next generation cover it?
- **R-B (#844 sample 10):** NCAAB 138 rows (53 venue), `p1_sportsbook_newest` 5, **h2h 9: row-fresh 0 vs cell-fresh 9, mismatch 26**.
- **R-E:** 1 NHL step, 0 timed out.

## Reading 15 — 7:06 PM CST (01:06Z)

- **Live:** 50 games: 14 NCAAB, 1 NCAAF, 7 NHL, 1 soccer, 27 WNCAAB. 29 have rail rows (317 rows).
- **Flags: 20 shown on 10 cards, 0 false, 0 missed, 0 dark.**
  - By sport: NCAAB 38 flagged rows of 261; NHL 0 of 18; WNCAAB 0 of 30.
  - 6 are college full totals.
- **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 123.** Team cards 94 chips, 0 defects.
- **I-29:** every live NCAAB game joins **direct**, all 14 in the re-sim with 0 refused. The remaining college no-model game
  is Stetson @ UCF (WNCAAB, no-anchor refusal).
  - Session local_a94d8ca3 put the orientation-free join on main (`e5a267c…`). It runs in shadow when its switch is absent
    and is not loaded. Measured: 24 of 24 reversed NCAAB games since 11-02 were dark.
- **I-30 (new): NHL live lanes flicker build to build.**
  - `live_games_no_model` lists 5 of 7 live NHL games at the read (BUF @ WSH, EDM @ TBL, LAK @ TOR, NYI @ WPG, PHI @ OTT).
    NHL flagged rows: 0 of 18.
  - `C:\tmp\railmon\lgbidx.py nhl` reads `index_why` per build. Of 12 snapshot games, the count with a `live_resim` lane
    tonight went 3, 6, 4, 6, 4, 3, 6, 4, 2, **1**, 4 (00:07-01:03Z, 7 games live); full_games moved with it.
  - **11-18 had the same shape:** 3 live games, `live_resim` cycling 0, 1, 2 every few builds. So it is not new tonight.
  - The 6:55 PM `nhl_live_generation` run (189 s, exit 0) did not hold coverage: 4 of 12 at 01:03Z.
  - **Hypothesis, not tested:** two producers write the NHL lens. The ~30-min live generation writes `live_resim` lanes;
    the faster odds sweeps rewrite games as `pregame_only` in between. That is the one-key-two-writers shape that
    `board_enrichment.py`'s path map documents for NFL (R8).
  - Owner: none in the ledger (no `pregame_only` hit in todo.md, lanes or state_board). Proposed as a session.
- **P7 (#850), 6:40-7:06 PM:** 0 refusals, 0 exits. Child 4.19 GB after 8.1 h.
  - Board: 3 builds, wall median 309 s, max 325 s (2 over 300 s); publication gap median 384 s, max 414 s.
  - `today_cadence_step_max_s` 326. Host load 4.18 (8.1 at 6:40 PM).
- **R-B (#844 sample 11):** NCAAB 168 rows (70 venue), `p1_sportsbook_newest` 7, h2h 12: row-fresh 7 = cell-fresh 7,
  mismatch 8. NBA 0 rows: the 7:10 PM tip had not produced live rows.
- **R-E:** 1 NHL step, 0 timed out; NHL child odds age max 44 s.
- **Live odds:**
  - overlay gap max 185 s (soccer); 79 web merges, 0 stale;
  - 10 sweeps, 5 refused (`lane_busy`, 33%);
  - priced age p50 160 s, p90 631 s (104 of 317 over 300 s).
- **Load:** query 3.56 s, shortlist 1.56 s, chips 1.97 s. **I-28:** 26 queries since 6:40 PM, 14 cold, all p50 7.6 s.
  #853 is queued as change F of the 11-24 batch (local_a5513c97).

## Reading 16 — 7:31 PM CST (01:31Z), full page

- **Live:** 50 games; 33 with rail rows (**1,277 rows**; NBA's 4 games add 963).
- **Flags: 18 shown on 10 cards, 0 false, 0 missed, 0 dark.**
  - By sport: NCAAB 17 of 222; NBA 4 of 963; NCAAF 3 of 13; NFL 0 of 25; NHL 0 of 21; WNCAAB 0 of 27.
  - 7 are college full totals.
- **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 169.** Team cards 94 chips, 0 defects.
- **`live_games_no_model` 4 of 33:**
  - **NFL IND @ HOU (TNF, 7:15 PM kick):** 0 model rows. Re-check next reading (the first NFL live re-sim may lag the kick).
  - **NHL EDM @ TBL, PHI @ OTT (I-30).** Coverage has risen: `lgbidx.py nhl` shows `live_resim` 7-8 of 12 and full_games 6-7
    on 01:26-01:31Z builds. Still flickering; card task_59fd9474 proposed.
  - **Fairleigh Dickinson @ LSU (WNCAAB):** a direct refusal (WNCAAB re-sim: 15 of 20 refused).
- **I-29:** all 14 live NCAAB games direct, 0 refused. The 7:30 PM neutral-site tips (Wisconsin @ Seton Hall, UNLV @ Rutgers)
  have no rail rows yet.
- **NBA quote age:**
  - rows are 572 alt totals, 301 alt spreads, 56 totals, 9 spreads, 8 h2h;
  - `book_age` p50 171 s, and `seen_age_at_pricing` is p50 = p90 = 136 s: one sweep's rows, priced together;
  - only 13 of 963 were priced within 120 s. That is NBA's live sweep cadence at tip-off; watch it as the games settle.
- **P7 (#850), 7:06-7:31 PM:** 0 refusals, 0 exits. Child 4.35 GB after 8.5 h.
  - Board: 5 builds, wall median 238 s, max **407 s** (1 over 300 s); publication gap median 330 s, **max 513 s**.
  - Host load 5.5; an NHL OddsAPI refresh at 86% CPU at the read.
- **R-B (#844 sample 12):**
  - NCAAB 206 rows (122 venue), h2h 13: row-fresh 11 vs cell-fresh 12, mismatch 8;
  - **NBA 61 rows, h2h 4: row-fresh 4 = cell-fresh 4, mismatch 0.** This is P3's baseline: the NBA grid is unaffected.
- **R-E:** 0 NHL steps, 0 timed out; NHL child odds age max 183 s.
- **Live odds:** overlay gap max 272 s (soccer); 8 sweeps, 3 refused; priced age p50 172 s, p90 455 s.
- **Load:** `/intelligence` **2.17 s** (35 MB raw, the largest today); query 6.69 s; shortlist 2.41 s.
  **I-28:** 15 queries, 8 cold (53%).

## Reading 17 — 7:56 PM CST (01:56Z)

- **Live:** 48 games; 33 with rail rows (1,239 rows).
- **Flags: 19 shown on 14 cards, 0 false, 0 missed, 2 dark** (prices over 300 s old).
- **P1:** 0. **#824:** 0. **P6:** 0. **P8 (score floor): 0 of 143.** Team cards 94 chips, 0 defects.
- **I-29: 4 of 4 reoriented neutral-site games went dark, as predicted at reading 9.**
  - **Wisconsin @ Seton Hall** (401920888): 14 rows, 0 with a model, re-sim REVERSED.
  - **UNLV @ Rutgers** (401920520): 20 rows, 0 with a model, re-sim REVERSED.
  - With WVU / Florida and Auburn / Notre Dame earlier, that is 4 of 4. The other 3 neutral-site games joined directly:
    Murray St / NC State, plus Oregon St @ Oregon (8 PM) and Houston @ Kansas (10 PM), still to tip.
  - Session local_a94d8ca3 replayed UNLV / Rutgers with the fix switched on: 29 of 29 rows matched their lane, right sides
    (`dbd42a9fb`). Not loaded.
- **TNF IND @ HOU had no live model for its first ~40 min. That was a gate, not a join miss.**
  - `NFL_LIVE_RESIM` every ~5 min showed `live_resimmed 0`, `refusals_by_reason {"game_not_in_progress": 12,
    "uninformative_probability": 1}`: the one live game was refused as uninformative from kickoff (7:15 PM).
  - The first `live_resimmed 1` came at 01:55:10Z. `LIVE_GAMELINE_BUILD sport=nfl date=2026-11-19` went from index 0 /
    full_games 0 to **index 1, projected 21, full_games 1 at 01:56:55Z**, 51 s after this reading's probe.
  - Lead, not chased: is NFL's `uninformative_probability` gate holding the first quarter dark by design? Its threshold
    belongs to the NFL live lane.
- **NHL (I-30):** `live_games_no_model` lists CBJ @ CHI and LAK @ TOR. `lgbidx.py nhl`: `live_resim` 6, 5, then **2** of 12
  by 01:53Z. Still flickering.
- **P7 (#850), 7:31-7:56 PM:** 0 refusals, 0 exits. Child 4.28 GB after 8.9 h.
  - Board: 4 builds, wall median 231 s, max 255 s; publication gap median 312 s, max 325 s. Host load 5.2.
- **R-B (#844 sample 13):**
  - NCAAB 255 rows (171 venue), **h2h 14: row-fresh 0 vs cell-fresh 11, mismatch 44**;
  - NBA 70 rows, h2h 4 = 4, mismatch 0.
- **R-E:** 0 NHL steps, 0 timed out.
- **Live odds:** overlay gap max 180 s (soccer); 9 sweeps, 4 refused; priced age p50 217 s, p90 701 s (295 of 1,239 over 300 s).
- **Load:** query 7.58 s, chips **3.36 s**, shortlist 0.78 s. **I-28:** 28 queries, 14 cold (50%).
