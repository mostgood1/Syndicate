# Layer 2 Games Rail — standing monitor, 2026-11-16 (lane `layer2-rail-monitor`)

Day 2 of the monitor. The user approved it on 11-16 ~7:49 AM CST: "Yes, from noon".
Method, probe and grader are as on day 1. See `.syndicate/findings_2026-11-15_layer2_rail_monitor.md`
("How a reading is taken" and the 11-15 DAILY SUMMARY):

- `scripts/layer2_rail_monitor_probe.py` (fleet only) runs the SERVED page's own rail code
  through `scripts/layer2_rail_monitor_run.mjs`. Flags are re-derived independently.
- Splits are per sport, main vs `_alt` markets, and 1H / 2H / break.
- Worker restarts are read from supervisor pids.
- Flags are graded at first sighting by `scripts/layer2_rail_flag_grade.py`, clustered by game.

Times are Central (CST) unless marked Z.

## Carried in from 11-15

- **NFL game-line quotes are still sharded by UTC capture date.** The writer is
  `scripts/fetch_nfl_team_odds_local.py:290` (`date_str=now.date().isoformat()`), unchanged on
  main at noon 11-16. The fix session card (task_082379c4) has not been started.
  - So from 6 PM CST (00:00Z 11-17) MNF's game lines (LAC @ BAL, 7:15 PM CST) are expected in
    the 11-17 shard, not in the 11-16 overlay or live-rail.
  - **Prediction, registered before 6 PM:** from the first in-play pull after 7:15 PM CST,
    `/api/board/live-rail` serves 0 NFL game-line rows for LAC @ BAL. The 11-17 NFL shard holds
    its in-play game rows. The rail card's lines come only from the shortlist, priced at its
    cadence.
  - **Falsified if** live-rail serves LAC @ BAL overlay game-line rows
    (`source=layer2_inplay_overlay`) after kickoff.
- The NFL / NBA slow-sport decision is still with the user.
- #811 NBA 60 s pulls are live (live-odds-worker pid 2066024 then, recycled since).

## Fleet events before the first reading

- Fleet ff `10094eae0 -> 09925a4b1` at 15:30:37Z (9:30 AM CST), no restart: the NBA live
  player-exit gate.
- refresh-worker claimed TERM at 16:29:16Z (10:29 AM CST), fleet `09925a4b1 -> a39058946`: the
  in-play overlay checks each file once per build (todo #790). Both are in `deploys.md`.
- live-odds-worker: two routine recycles since last night ("exited code=0 after 19752s" /
  "19899s"). pid now 2479540.

## Reading 1 — Mon 11-16 11:59 AM CST (17:59Z)

**Slate:**
- 57 cards on today's rail, **0 live**. The two 10 AM WNCAAB games are over.
- Next tips: NCAAB 1 PM; WNCAAB 3 PM and 4 PM; the evening wave from 5 PM — ~40 college games,
  NBA 6:10-8:10 PM, NHL 6:30 / 8:30 PM, MNF 7:15 PM.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark. No live rows.
- **Load:**
  - `/intelligence` 6.8 s / 20.2 MB (3.6 MB gz).
  - Query 7.4 s / 56.9 MB (9.8 MB gz).
  - Shortlist 1.4 s. Chips 0.03 s.
  - Live-rail 0.03 s, 0 rows.
- **Board:** build 76 s old; shortlist 76 s.
- WNCAAB overlay: 30 builds in 30 min (gap p50 41 s, max 66 s). 20 of them carried in-play rows
  but published 0 cards. These are the finished 10 AM games' leftover rows (the 11-15 NFL shape);
  benign.

**Teams:** 0 chip-less. det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 2 — Mon 11-16 1:00 PM CST (19:00Z)

**Slate:** 0 live chips; the 1 PM NCAAB tip is not live on its chip yet. 57 cards.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark.
- **Load:** query 5.3 s / 56.9 MB. Shortlist 1.1 s (104 s old). Live-rail 0 rows.
- **Builds (last 61 min):** NBA p50 5.5 s, NFL 1.2 s, NCAAB 3.8 s; pregame only. 0 `deferred_slow`.

**Fleet events:**
- **live-odds-worker pid 2834332:** a routine recycle (supervisor "exited code=0 after 19767s").
- Fleet ff `a39058946 -> 5963e16f4` at 18:39:51Z (12:39 PM CST), no restart: the NCAAB / WNCAAB
  live player-exit gate (deploys.md). It reaches live-odds-worker at its recycle; the 12:5x
  recycle should have loaded it.

**Teams:** 0 chip-less. det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

## Reading 3 — Mon 11-16 2:00 PM CST (20:00Z)

**Slate:** 1 live chip — **NCAAB Florida A&M @ UTEP, at HALF.**
- This is the 11-15 chip-less card. The odds feed had it Sunday 7 PM CST (`commence_time`
  01:00Z 11-16). ESPN had it Monday 1 PM CST (event 401929419).
- **ESPN was right.** Today it is a normal live card that joins its chip. The 11-15 card was the
  odds feed's wrong kickoff, not a team-name join.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark.
- 5 live rows, all at the break: 0 priced <= 120 s; priced age p50 414 s; seen age at pricing
  p50 24 s. Our look is fresh; the book's halftime prices stand still.
- NCAAB overlay: 77 builds in 60 min, gap p50 40 s, max 86 s. NCAAB builds p50 3.4 s.
  0 `deferred_slow`.
- Web merges: ncaab fresh 14 / 14. nfl and wncaab stale 14 / 14 (no games live; expected).
- **Load:**
  - `/intelligence` 6.1 s / 19.8 MB.
  - Query 7.1 s / 56.3 MB. Shortlist 0.75 s.
  - Live-rail 0.02 s, 2 rows.

**Teams:** 0 chip-less. det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.
**Restarts:** live-odds-worker pid unchanged (2834332).

## Reading 4 — Mon 11-16 3:00 PM CST (21:00Z)

1 live chip: FAMU @ UTEP, "END H2" (end of regulation). The 3 PM WNCAAB tip is not live on its chip
yet.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark.
- 3 live rows, all at the break: 0 priced <= 120 s; seen age at pricing p50 52 s.
- NCAAB overlay: 76 builds in 60 min, gap p50 46 s, max 97 s. 7 zero-card builds with rows, at
  the game's end.
- 0 `deferred_slow`.
- Web merges: ncaab fresh 58 / 58. nfl and wncaab stale (no live games).
- **Load:** query 10.5 s / 57.5 MB. Shortlist 0.9 s (371 s old).

**Teams:** 0 chip-less, all detectors 0.
**Restarts:** live-odds-worker pid unchanged (2834332).

**User 11-16 ~3:0x PM CST: "start the NFL night-game fix session".** The card was started as session
"Shard NFL game-line quotes by Central kickoff date" (local_78b841a1). Loading its fix onto the fleet
still needs the user's yes. The MNF prediction above stands unless that load happens before
kickoff.

## Reading 5 — Mon 11-16 4:00 PM CST (22:00Z)

**Fleet:**
- Still at `db463b5be`. The NFL kickoff-shard fix (`ed63c7611`, load target `dac4d49f8`) is
  **not loaded**. It waits on the user's yes in the fix session.
- ff-only loads this afternoon: NHL exit gate 2:55 PM, soccer exit gate 3:17 PM (deploys.md).
- live-odds-worker pid unchanged (2834332).

**Slate:** 1 live chip — WNCAAB Penn State @ Arizona State, at HALF.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark.
- **Load:**
  - `/intelligence` 5.5 s / 21.2 MB.
  - Query 4.1 s / 59.1 MB. Shortlist 0.6 s.
  - Live-rail 0 rows.

### ANOMALY — the WNCAAB in-play overlay published 0 cards on every build through a live game

`refresh-worker.log`, 21:04-21:58Z (`C:\tmp\railmon\wz2.sh`):
- Every sampled `INPLAY_OVERLAY sport=wncaab` (~18 of 71 builds; 68 of 71 had rows and 0
  cards) shows `rows_inplay` 4-12, `opportunities` 6-22, `cards=0`.
- The preceding `LIVE_GAMELINE_BUILD`s withheld most rows for
  `quote_older_than_live_pricing_ceiling` (plus some `prob_interval_swamps_edge` /
  `quote_older_than_the_score_the_model_saw`), **but not all**. At 21:32:04Z, 14 were
  considered and 10 withheld.
- So the game's live lines never reached `/api/board/live-rail` (0 WNCAAB rows). The rail card
  shows 2 shortlist rows.
- It is not a halftime effect: it covers Q1-Q2.
- 11-15 context: WNCAAB 27 of 60 zero-card builds, NCAAB 9 of 185. NCAAB overlays carry cards
  normally.
- **What drops every WNCAAB opportunity before the card step is unknown.** The overlay logs no
  per-row reason.
- **Handed to local_208683f1** (overlay / live-rail owner) at ~4:05 PM CST, as a question.

**Teams:** 0 chip-less. det1 / det2 / det3 0 / 0 / 0. 0 flipped. 0 truncated.

### WNCAAB zero-card overlay — CAUSE MEASURED (lane `wncaab-overlay-zero-cards`, ~4:25 PM CST)

- **Not the overlay owner's.** local_208683f1 placed the drop in `_build_inplay_overlay`
  (`book_grid_artifact.py:1085-1128`): `select_shortlist(opportunities)` returns no rows, and
  the overlay keeps only `.get("rows")` and discards the refusal counters. No open lane claims it,
  so I opened `wncaab-overlay-zero-cards` with the hypothesis written first (lanes.md `02e56e11f`).
- **Replay**, read-only, nice 19, under refresh-worker's environ (`C:\tmp\railmon\wz_replay.py`;
  `build_layer2_rows` and `select_shortlist` checked side-effect free first):
  - WNCAAB grid 11-16 → `select_inplay_rows` → 8 rows → `build_layer2_rows` gives opportunity 5,
    dead 3 (`live:live_market_stale` 3) → `select_shortlist` **chose 0**.
  - **`rows_below_value_floor: 5` of 5.** Their market EV was -6.0 / -9.3 / -10.0 / -10.3%
    against the WNCAAB floor of -2.0% (`flat_default`, both families).
  - The quote-age limit (50,400 s) refused nothing.
- **Mechanism:** the live join withholds the model price (`quote_older_than_live_pricing_ceiling`),
  so the rows carry only the market-fair EV, which is the hold. WNCAAB in-play holds are wide, so
  every live line falls under the board's value floor, and the overlay publishes 0 cards.
- **Hypothesis CONFIRMED (value-floor half).** The quote-age half is FALSIFIED for this build.
- **Effect on the rail:** a WNCAAB live game with a wide in-play hold shows no live lines at all.
  The rail is information (user 2026-11-14), but the overlay is the BOARD's shortlist chain, so it
  inherits the board's value floor. NCAAB rows pass more often (more books, tighter holds).
- **Open question for the user (product):** should the rail's live lines include lines below the
  board's value floor? The overlay also feeds the board's live rows, so it is not only a rail
  change. **Not changed.**

### Instrumentation landed — `146f956cb` on main, NOT loaded (~4:13 PM CST)

- `book_grid_artifact.py` is held by lane `nba-overlay-card-cost`. It lent 3 logging-only regions
  (LOAN NOTE `4fe82f7b8`; loan taken `270da640a`).
- `_build_inplay_overlay` now keeps `select_shortlist`'s result. The overlay gains
  `shortlist_refused`: positive `rows_*` refusal counts. Budgets, sizes, admissions and per-sport
  dicts are excluded.
- `INPLAY_OVERLAY` gains one token, `refused={...}`, last on the line: for example
  `refused={"rows_below_value_floor":5}`. It reads `refused={}` when nothing was refused, so the
  line also proves the branch ran.
- Selection is unchanged.
- Tests: `tests/test_inplay_overlay_shortlist_counters.py`, 13 tests, including:
  - off != on;
  - a guard that the real `select_shortlist([])` maps to `{}`;
  - the lender's `lookups_*` pair staying adjacent.
  153 passed across the 8 overlay test files.
- **Load: the user's call.** The lender asks that no refresh-worker restart happen before 05:00Z
  11-17 (11 PM CST) without telling it: it confounds tonight's NBA reading and per-thread
  sampler. Until a load, the cause stays known only from the 4:25 PM replay, not from the log.

## Reading 6 — Mon 11-16 4:08 PM CST (22:08Z)

**Slate:** 2 live chips, both WNCAAB:
- Penn State @ Arizona State, Q3 9:15;
- Lamar @ Texas A&M, Q1 6:58.

**Readings:**
- **0 flags.** 0 false, 0 missed, 0 dark.
- **Live rows:** live-rail serves **13-16 WNCAAB rows**, all main markets, phase 1H in the probe's
  token parse. Priced age p50 194 s; 2 of 13 priced <= 120 s; 2 aged > 300 s now. Markets with our
  price: 0 of 2 (the join withheld the model price).
- **WNCAAB overlay (last 15 min):** 21 builds, gap p50 39 s, max 67 s. **15 of 21 zero-card with
  rows; 6 carried cards.** So the zero-card overlay is not total: a line whose market EV clears the
  -2% floor reaches the rail.
- **Web merges:** wncaab fresh 6 / 6.
- **Load:**
  - `/intelligence` 1.5 s / 21.2 MB.
  - **Query 20.4 s** / 59.3 MB (10.5 MB wire), the slowest today; one sample.
  - Shortlist 1.1 s; chips 0.2 s; live-rail 0.03 s.
- **Board:** build 208 s old; shortlist written 249 s ago; query snapshot 1,217 s old.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. No live chip
without a live card.

**Restarts:** none. live-odds-worker pid 2834332.

### User decision — keep the value floor (~4:35 PM CST)

- **User 11-16 ~4:35 PM CST: "Keep the floor"**, answering "Should the Games Rail show live lines
  that fall below the board's value floor?"
- **The gate stays.** A wide-hold in-play game can still show no overlay lines on the rail. That
  is now a decided behaviour, not a defect.
- Lane `wncaab-overlay-zero-cards` is CLOSED, GOAL MET.
- The `refused=` token (`146f956cb`) is logging only. It reaches the fleet with the next ff plus a
  refresh-worker restart. Its first fleet reading will be recorded here.

## Reading 7 — Mon 11-16 4:36 PM CST (22:36Z)

### Fleet event: the NFL kickoff-shard fix is LOADED

Fleet ff `db463b5be -> dac4d49f8` at 22:31:26Z (4:31 PM CST; fleet reflog). This is the fix session's
load target (`ed63c7611`). No restart is needed: the NFL odds fetch runs as a subprocess
(`refresh_odds_sources.py --sports nfl --phase live`), so the next launch carries the new code.

**Measured on the fleet's shards, rows captured at or after 22:31Z:**
- `nfl 2026-11-19.jsonl`: 160 rows, all TNF (kickoff 2026-11-20T01:15Z = 11-19 7:15 PM CST).
- `nfl 2026-11-16.jsonl`: 4 rows, all MNF (kickoff 2026-11-17T01:15Z = 11-16 7:15 PM CST).
- Under the old UTC-capture basis, all 164 would be in 11-16. So `basis=kickoff_central` ran.

**Gaps:**
- The `NFL_GAMELINE_QUOTE_SHARD` line is in no file under `~/syndicate-prod/logs`, so the subprocess's
  stdout is not kept there.
- The 11-19 shard also holds rows captured 02:43Z 11-16, before the ff. Their origin was not checked:
  possibly the fix session's own replay or backfill.
- deploys.md has no entry for this ff on origin/main at 22:34Z. The fix session owns it.

**The registered MNF prediction now takes its "fix loaded" branch.** Expected after 7:15 PM CST:
- MNF game rows after 00:00Z land in `nfl 2026-11-16.jsonl`;
- `INPLAY_OVERLAY nfl date=2026-11-16` carries LAC @ BAL;
- live-rail serves NFL overlay game-line rows.

It is falsified if live-rail serves 0 LAC @ BAL overlay game-line rows after kickoff. Read after
7:20 PM and ~7:45 PM.

### Readings

**Slate:** 2 live chips, both WNCAAB:
- Penn State @ Arizona State, Q4 6:43;
- Lamar @ Texas A&M, Q2 4:55.

**Flags: 1 shown (1 card, 2 qualifying rows, 1 market). 0 false, 0 missed, 0 dark.** The first flag
of 11-16:
- WNCAAB Penn State @ Arizona State, full-game total **u139.5**.
- Model 58.3% vs book no-vig fair 49.1% (gap 9.2 pp); our line 138.5.
- Priced 24 s before; 60 s old at the read; Q4 6:43.
- To be graded on the final with the day's flags.

**Live rows:** 14, all WNCAAB main.
| phase | rows | priced <= 120 s | flags |
|---|---|---|---|
| 1H | 8 | 4 | 0 |
| 2H | 6 | 4 | 2 |
- Priced age p50 64 s; seen age at pricing p50 45 s, p90 152 s.
- 1 row older than 300 s now; 2 of 3 markets carry no price of ours.
- Live-rail: 13 rows on 3 reads.

**WNCAAB overlay (30 min):**
- 39 builds, gap p50 41 s, p90 66 s, max 86.5 s, 0 over 360 s.
- **Zero-card builds with rows: 5 of 39**, down from 15 of 21 at 4:08 PM. The second game's lines
  clear the floor.
- Builds p50 0.8 s, max 15.1 s.

**Other builds:**
- NBA p50 12.1 s (pregame, n=2); NFL 19.5 s (n=1); NCAAB 6.1 s; soccer 4.6 s; NHL 0.4 s.
- 0 `deferred_slow`. Tick gap p50 35 s, max 120 s.

**Web merges:** wncaab fresh 37 / 37; nfl and ncaab stale 37 / 37 (nothing live).

**Load:**
- **Query 19.0 s** / 59.9 MB (10.7 MB wire), the second sample over 19 s in a row (3-10 s before 4 PM).
- **Chips 3.1 s** (0.03-0.2 s before). Shortlist 2.4 s. Live-rail 0.03 s.
- At 16:37 CST the serving gunicorn worker was **59 s old** (a recycle), and host load was 5.27 on
  12 cores. So the cause is most likely a cold web worker, not host contention. Not proven: the
  4:08 PM sample's worker age was not read.
- **Board:** build 511 s old, shortlist written 555 s ago (76-371 s in earlier readings). Query
  snapshot 2,908 s old.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. No live chip without a
live card.

**Restarts:**
- live-odds-worker pid 2834332, unchanged.
- refresh-worker pid 2809282, up since the 16:29Z 11-16 TERM.

## Reading 8 — Mon 11-16 4:58 PM CST (22:58Z), full page

**Slate:**
- 1 live chip: WNCAAB Lamar @ Texas A&M, at HALF.
- Penn State @ Arizona State has ended. It carries flag 1 (u139.5), graded tonight with the rest.
- The 5 PM college wave is not live yet: NCAAB builds 7 in 25 min, pregame.

**Readings:**
- **0 flags shown.** 0 false, 0 missed, 0 dark.
- **Live rows:** 6, all WNCAAB main at the break.
  - 1 priced <= 120 s; priced age p50 164 s; seen age at pricing p50 130 s.
  - 3 older than 300 s now. 2 of 2 markets carry no price of ours.
  - Live-rail: 1 row on 3 reads.
- **WNCAAB overlay (25 min):** 31 builds, gap p50 51 s, max 83 s, 0 over 360 s. Zero-card builds
  with rows: 1 of 31.
- **Builds:**
  - NBA p50 12.1 s (n=3, pregame); NFL 9.0 / 38.6 s (n=2); NCAAB p50 8.2 s, max 22.1 s;
    NHL 0.8 / 11.1 s; soccer 5.7 / 12.7 s.
  - 0 `deferred_slow`. Tick gap p50 37 s, max 94 s.
- **Web merges:** wncaab fresh 23 / 23; nfl and ncaab stale (nothing live).
- **Load:**
  - `/intelligence` 4.6 s / 23.2 MB.
  - **Query 7.8 s** / 64.4 MB (11.6 MB wire), down from 19-20 s at 4:08 and 4:36 PM.
  - Shortlist 0.7 s; chips 0.17 s; live-rail 0.015 s.
- **Board:** build 49 s old; shortlist written 78 s ago; query snapshot 542 s.

**Web worker ages:**
- At 16:58:09 the two gunicorn workers were 322 and 879 s old. During the probe, the 879 s worker
  was recycled (`WEB_WORKER_MEMORY_RECYCLE` 22:58:14Z, anon 951 MB vs limit 642 MB, hard,
  15 requests). A new worker booted at 22:58:16Z.
- Recycles in 22:27-22:58Z: 6 worker boots. Each worker passed its ~640 MB anon limit within 5-15
  requests and 285-938 s.
- Recycles by hour:
  - 22Z 11-16: 14;
  - earlier 11-16 game hours: 3-17 per hour;
  - 11-15 game peak: 30-51 per hour.
- This fits the 19-20 s queries landing on cold workers. **Not proven:** which worker served each
  read is not logged.
- The web memory guard is the known, closed mechanism (lane `web-memory-guard`). The
  5-15-requests-per-worker rate is recorded as a lead in `leads.md`, not followed.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated.

**Restarts:** live-odds-worker pid 2834332 and refresh-worker pid 2809282, both unchanged.

## Reading 9 — Mon 11-16 5:20 PM CST (23:20Z)

**Slate:** 7 live chips.
- NCAAB: Iona @ UMBC H1 11:01; Alcorn State @ Maryland H1 13:17.
- WNCAAB: Lamar @ Texas A&M Q3 1:49, plus four games in Q1 (Arkansas-Pine Bluff @ UL Monroe,
  NC Central @ VCU, Robert Morris @ Duquesne, Bryant @ Holy Cross).

**Flags: 5 shown on 2 cards (10 qualifying rows, all NCAAB 1H). 0 false, 0 missed, 0 dark.**

| game | market | side | model | fair | gap | our line | priced |
|---|---|---|---|---|---|---|---|
| Alcorn St @ Maryland | full total | u151.5 | 60.8% | 49.9% | 10.9 pp | 148.3 | 91 s |
| Alcorn St @ Maryland | 1H total | u70.5 | 67.2% | 49.2% | 18.0 pp | 67.2 | 62 s |
| Iona @ UMBC | full total | o141.5 | 60.3% | 50.0% | 10.3 pp | 145.4 | 42 s |
| Iona @ UMBC | moneyline | UMBC | 38.5% | 29.9% | 8.6 pp | — | 80 s |
| Iona @ UMBC | 1H total | u68 | 61.3% | 50.0% | 11.3 pp | 67.2 | 63 s |

- Iona @ UMBC carries a full-game OVER and a 1H UNDER together. They are not contradictory: our
  lines imply ~78 second-half points.
- All 5 are graded on the finals tonight with flag 1.

**Live rows:** 55 (NCAAB 53, WNCAAB 2), all main markets.
| sport | phase | rows | priced <= 120 s | priced age p50 | seen at pricing p50 / p90 |
|---|---|---|---|---|---|
| NCAAB | 1H | 53 | 24 | 134 s | 87 s / 270 s |
| WNCAAB | 2H (Lamar @ A&M) | 2 | 1 | — | — |

- 9 rows older than 300 s now. 2 of 12 markets carry no price of ours.
- Live-rail: 53 rows on 3 reads.
- **The four Q1 WNCAAB games serve 0 live-rail rows** (WNCAAB `rows_inplay_last` 9; 5 of 29
  overlay builds zero-card with rows). This fits the decided value floor, or no in-play quote yet
  this early. Not followed; re-check at the next reading.

**Overlay (22 min), all 0 over 360 s:**
| sport | builds | gap p50 | gap max | zero-card with rows |
|---|---|---|---|---|
| WNCAAB | 29 | 44 s | 76 s | 5 |
| NCAAB | 24 | 47 s | 75 s | 0 |

**Builds:**
- NCAAB p50 4.0 s, p90 17.2 s, max 24.9 s; WNCAAB p50 0.7 s.
- NFL 5.5 / 7.5 s; NBA 4.4 s (pregame); NHL 0.7 s; soccer 4.6 / 11.7 s.
- 0 `deferred_slow`. Tick gap p50 26 s, max 110 s.

**Web merges:** wncaab fresh 18 / 18; ncaab fresh 16 / 18 (2 stale); nfl stale 18 / 18.

**Load:**
- **Query 9.2 s** / 63.6 MB. Gunicorn workers were 104 s and 1,315 s old at the read, with no
  recycle during the probe.
- Shortlist 0.6 s; chips 0.05 s; live-rail 0.05 s.
- **Board:** build 62 s old; shortlist written 92 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 7 live chips have
a live card.

**Restarts:** live-odds-worker pid 2834332 and refresh-worker pid 2809282, both unchanged.

## Reading 10 — Mon 11-16 5:41 PM CST (23:41Z)

**Slate:** 10 live chips.
- NCAAB 3: Iona @ UMBC H1 0:36; Alcorn State @ Maryland H1 7:31; Prairie View @ Ohio State H1 15:23.
- WNCAAB 7: Lamar @ Texas A&M Q4; four games in Q2; Yale @ Quinnipiac and Cleveland State @
  Xavier in Q1.

**Flags: 10 shown on 3 cards (20 qualifying rows, all NCAAB 1H). 0 false, 0 missed, 0 dark.**

| game | market | side | model | fair | gap | our line | priced |
|---|---|---|---|---|---|---|---|
| Iona @ UMBC | full spread | UMBC +1 | 61.8% | 51.1% | 10.8 pp | UMBC -1.1 | 53 s |
| Iona @ UMBC | full total | o134 | 59.8% | 50.0% | 9.8 pp | 142.7 | 76 s |
| Iona @ UMBC | 2H total | o76.5 | 56.4% | 48.4% | 8.0 pp | 79.8 | 35 s |
| Alcorn St @ Maryland | full spread | MD -38.5 | 61.5% | 51.1% | 10.4 pp | MD -43.0 | 52 s |
| Alcorn St @ Maryland | full total | u161.5 | 81.4% | 48.9% | **32.5 pp** | 156.0 | 23 s |
| Alcorn St @ Maryland | 1H total | u79.5 | 83.8% | 48.8% | **35.0 pp** | 76.7 | 33 s |
| Alcorn St @ Maryland | 2H total | u80.5 | 62.7% | 49.4% | 13.3 pp | 79.3 | 33 s |
| Prairie View @ Ohio St | full total | u151.5 | 58.3% | 50.2% | 8.1 pp | 148.1 | 37 s |
| Prairie View @ Ohio St | 1H total | u71.5 | 57.8% | 51.1% | 6.8 pp | 67.3 | 31 s |
| Prairie View @ Ohio St | 2H total | u80.5 | 53.9% | 49.4% | 4.5 pp | 80.9 | 31 s |

- **The two largest gaps of the two days**: Alcorn @ Maryland 1H u79.5 at 35.0 pp and full u161.5
  at 32.5 pp.
- **Observation, not a finding: our live total moved less than the book's between readings 9 and 10.**
  | game | book total | our total |
  |---|---|---|
  | Alcorn St @ Maryland | 151.5 → 161.5 (+10) | 148.3 → 156.0 (+7.7) |
  | Iona @ UMBC | 141.5 → 134 (-7.5) | 145.4 → 142.7 (-2.7) |
  So these flags FADE the book's in-game move.
- **PRE-REGISTERED for tonight's grade, before any 11-16 final is read:** split the 11-16 totals
  flags by whether the flag opposes the book's line move since that game's previous reading. Report
  each half's hit rate, game-clustered. **Totals direction so far: 9 unders, 3 overs.** This
  changes nothing; it is a reading.

**Live rows:** 79 (NCAAB 77, WNCAAB 2).
| sport | phase | rows | priced <= 120 s | priced age p50 | seen at pricing p50 / p90 |
|---|---|---|---|---|---|
| NCAAB | 1H | 77 | 43 | 109 s | 68 s / 221 s |
| WNCAAB | 2H (Lamar @ A&M) | 2 | 0 | — | — |

- 14 rows older than 300 s now. 1 of 18 markets carries no price of ours.
- Live-rail: 66-73 rows on 3 reads.

**WNCAAB: 6 of 7 live games serve 0 live-rail rows.** A read-only replay at 23:41Z
(`C:\tmp\railmon\wz_replay.py`, refresh-worker environ, nice 19):
- The 23:41:24Z grid holds **10 in-play rows across all 7 live games**.
- `build_layer2_rows` gives 20 opportunities. `select_shortlist` chose 2:
  `rows_below_value_floor` 17, `rows_implausible_book` 1.
- So most of the gap is the decided floor (user "Keep the floor"), on top of thin in-play quote
  coverage. Overlay: 19 of 27 builds zero-card with rows.

**Overlay (21 min), all 0 over 360 s:**
| sport | builds | gap p50 | gap max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 29 | 45 s | 70 s | 0 |
| WNCAAB | 27 | 46 s | 81 s | 19 |

**Builds:**
- NCAAB p50 4.4 s, max 25.7 s; WNCAAB 0.8 s.
- NBA 6.0 / 11.4 s and NFL 9.9 / 13.1 s (pregame); NHL 0.1 s; soccer 2.2 s.
- 0 `deferred_slow`. Tick gap p50 32 s, max 83 s.

**Web merges:** ncaab and wncaab fresh 32 / 32; nfl stale (pregame).

**Load:**
- **Query 6.1 s** / 64.8 MB. Gunicorn workers were 260 s and 140 s old at the read. The 140 s
  worker was recycled during the probe; a new one was 26 s old at 17:41:43.
- Shortlist 0.45 s; chips 0.06 s; live-rail < 0.01 s.
- **Board:** build 72 s old; shortlist written 98 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 10 live chips
have a live card.

**Restarts:** live-odds-worker pid 2834332 and refresh-worker pid 2809282, both unchanged.

## Reading 11 — Mon 11-16 6:04 PM CST (00:04Z 11-17), full page

**Slate: 18 live chips.**
- **NCAAB 9:**
  - Iona @ UMBC H2 16:23; Alcorn St @ Maryland HALF; Prairie View @ Ohio State H1 5:15.
  - Six tipped at 6 PM: EKU @ Kent State, WKU @ Tulsa, Grambling @ Kentucky, Citadel @ Clemson,
    Richmond @ Virginia Tech, Jacksonville @ Georgia.
- **WNCAAB 9:** one at HALF, three in Q3, two in Q2, three in Q1.
- NBA not live yet (6:10 tips).

**Flags: 10 shown on 5 cards (20 qualifying rows). 0 false, 0 missed, 0 dark.** 11-16 total: 26.

| game | market | side | model | fair | gap | our line | priced |
|---|---|---|---|---|---|---|---|
| Alcorn St @ Maryland | full spread | MD -45.5 | 53.3% | 48.9% | 4.4 pp | MD -47.9 | 71 s |
| Iona @ UMBC | full spread | UMBC -1.5 | 61.8% | 50.0% | 11.8 pp | UMBC -5.0 | 107 s |
| Iona @ UMBC | full total | o126.5 | 78.9% | 51.1% | 27.8 pp | 136.5 | 42 s |
| Iona @ UMBC | 2H total | o73.5 | 66.2% | 49.4% | 16.7 pp | 79.6 | 110 s |
| Prairie View @ Ohio St | 1H total | u67.5 | 57.4% | 48.4% | 8.9 pp | 66.6 | 112 s |
| Richmond @ Virginia Tech | full total | o147.5 | 69.1% | 48.8% | 20.4 pp | 156.4 | 40 s |
| Richmond @ Virginia Tech | moneyline | RICH | 24.0% | 10.7% | 13.3 pp | — | 29 s |
| Richmond @ Virginia Tech | 1H total | o69.5 | 64.7% | 50.5% | 14.2 pp | 74.8 | 76 s |
| Citadel @ Clemson | full total | o139.5 | 63.2% | 50.4% | 12.8 pp | 145.3 | 42 s |
| Citadel @ Clemson | 1H total | o65.5 | 63.7% | 53.0% | 10.7 pp | 69.0 | 113 s |

- **The fade-vs-follow series** (book total vs our total at each reading, for the pre-registered split):
  | game | 5:20 PM | 5:41 PM | 6:04 PM |
  |---|---|---|---|
  | Iona @ UMBC | 141.5 / 145.4 | 134 / 142.7 | 126.5 / 136.5 |
  - The book has fallen 15 points since 5:20 and ours 8.9. The flag is still OVER, against the move.
- Totals direction across 11-16 flags so far, recounted flag by flag: **11 unders, 9 overs (20 totals
  flags)**. The 6 PM tips add overs in the first minutes.
  - **Correction:** reading 10's "9 unders, 3 overs" was miscounted. Through 5:41 PM it was 10 unders,
    3 overs.

**Live rows:** 95 (NCAAB 94, WNCAAB 1).
| sport | phase | rows | priced <= 120 s | flags |
|---|---|---|---|---|
| NCAAB | 1H | 62 | 25 | 13 |
| NCAAB | 2H | 18 | 8 | 6 |
| NCAAB | break | 14 | 2 | 1 |
| WNCAAB | 1H | 1 | 1 | 0 |

- NCAAB seen age at pricing p50 64 s, p90 199 s. 34 rows are older than 300 s now. 4 of 25 markets
  carry no price of ours. Live-rail: 128 rows on 3 reads.
- **The 41,657 s maximum priced age is 4 pregame `layer2_shortlist` rows**: Richmond @ VT and Citadel @
  Clemson spreads, book unmoved 2,304-41,657 s, our look 45-5,570 s old. They sat on live cards whose
  games had tipped ~2 min before the read; the overlay had not yet replaced them. None flagged (the
  edge needs a <= 120 s price). Expected at tip; not handed off.
- **WNCAAB:** 9 live games, 1 live-rail row. This is the decided floor plus thin in-play coverage
  (5:41 PM replay). Overlay: 7 of 25 builds zero-card with rows.

**Overlay (23 min), both 0 over 360 s:**
| sport | builds | gap p50 | gap max | rows_inplay last |
|---|---|---|---|---|
| NCAAB | 30 | 38 s | 98 s | 198 |
| WNCAAB | 25 | 43 s | 236 s | 11 |

**Builds:**
- NCAAB p50 8.2 s, p90 16.4 s, max 36.6 s (rising with 9 games live).
- NBA p50 11.1 s, max 17.5 s (pregame); NFL 1.7 / 27.3 s.
- 0 `deferred_slow`. Tick gap p50 25 s, max 106 s.

**Web merges:** ncaab and wncaab fresh 22 / 22; nfl stale (pregame).

**Load:**
- **`/intelligence` 13.2 s** / 24.1 MB, the slowest page today (1.5-6.8 s before). **Query 10.3 s** /
  64.5 MB. Shortlist 1.1 s; chips 0.6 s; live-rail 0.03 s.
- Gunicorn workers were 250 s and 51 s old at the read, no recycle during the probe. Host load rose
  from 2.6 to 5.5 during the probe.
- **Board:** build 128 s old; shortlist written 162 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 18 live chips have
a live card.

**Restarts:**
- **live-odds-worker pid 2834332 → 2925378**, a routine recycle (supervisor: "exited code=0 after
  20383s", after a 200 MB log rotation).
- refresh-worker pid 2809282, unchanged.

### Fleet event — #816 college totals calibration LOADED, refresh-worker restarted (6:04 PM CST)

**Source:** a message from the starting session (local_1f10ce63) and deploys.md 2026-11-17 00:04:20Z.
- Fleet ff `dac4d49f8 -> 13ec8f348` at 00:04:20Z.
- A drained, claimed refresh-worker TERM: new pid **2953295** at 00:04:38Z.

**Reading 11 (00:04:14Z) is entirely PRE-load.**

**By design, after the load (user "Spread + level"):**
- Every live NCAAB full-game total is calibrated toward the market, minus a fitted level.
- Per the lane's ledger, priceable live NCAAB full-game totals with |edge| >= 3 went from
  101 over / 116 under (23:20-00:04Z) to 0 over / 156 under (from 00:06Z).
- WNCAAB is unchanged.

**PRE-REGISTERED, at the lane's request, before any 11-16 final is read:** tonight's flag grade
splits NCAAB flags at **00:04:38Z**: before = uncalibrated engine, after = `total_cal`. The
fade-vs-follow split is reported within each half.

**`146f956cb` is on the fleet, carried by this range (closed lane `wncaab-overlay-zero-cards`).** The
first readings of `INPLAY_OVERLAY ... refused=` (33 overlay lines 00:04:38Z-00:27Z):
| sport | cards | refused |
|---|---|---|
| WNCAAB | 0-1 | `rows_below_value_floor` 15-23 |
| NCAAB, first post-restart build | 390 | 68 below the floor + 31 `rows_implausible_book` |
| NCAAB, later builds | 183-205 | 198-237 below the floor + 22-25 implausible book + 1 `rows_uninformative_ev` |

- The roughly halved NCAAB card count, with the floor refusals tripling, matches the calibration
  pulling over-side value under the -2% floor.
- The NBA overlay-cost lane was told about the restart. Its 23:00-05:00Z reading spans it.

## Reading 12 — Mon 11-16 6:27 PM CST (00:27Z 11-17)

**Slate:** 23 live chips.
- NBA 3, all Q1: CHI @ CLE, ORL @ BOS, MEM @ WAS.
- NCAAB 10 (including St. Thomas @ LIU); WNCAAB 10.
- NHL not live yet.

**Flags: 15 new shown on 13 cards. 0 false, 0 missed, 0 dark.** 11-16 total: 41.
- **NCAAB full-game totals (8):**
  - 7 unders, all calibrated-looking (`total_cal`, below): Iona @ UMBC u122.5 (58.1%),
    Alcorn St @ Maryland u170.5, Jacksonville @ Georgia u158.5, St. Thomas @ LIU u147.5,
    WKU @ Tulsa u159.5, Grambling @ Kentucky u145.5, EKU @ Kent State u150.5. Model 59.9-62.3%,
    gaps 7.0-12.3 pp.
  - 1 over: **Richmond @ Virginia Tech o139.5, model 67.6% (69/102, RAW) vs fair 50.9%, 16.8 pp.**
- **NCAAB spreads (2):** Prairie View @ Ohio State OSU -23.5 (9.2 pp); Richmond @ VT VT -14.5 (3.7 pp).
- **WNCAAB (1):** Albany @ Rutgers u129.5 (3.3 pp).
- **NBA (4):** MEM @ WAS u235.5 (5.9 pp; ours 231.0); CHI @ CLE o237.5 (5.7 pp; ours 244.4);
  CHI moneyline (12.5 pp); ORL @ BOS o198.5 (14.1 pp; ours 213.6).
- Fade-vs-follow series:
  | game | 5:20 PM | 5:41 PM | 6:04 PM | 6:27 PM |
  |---|---|---|---|---|
  | Iona @ UMBC | 141.5 / 145.4 | 134 / 142.7 | 126.5 / 136.5 | 122.5 / 124.6, now UNDER |
- Totals direction across 11-16 totals flags, counted flag by flag: **20 unders, 12 overs.**
  - Through 6:04 PM: 11 U / 9 O.
  - Reading 12 adds 9 U (7 NCAAB full, WNCAAB u129.5, NBA u235.5) and 3 O (Richmond o139.5, NBA
    o237.5, o198.5).

### ANOMALY — the #816 calibration reaches about 1/3 of the served NCAAB full-game total rows (handed to local_1f10ce63)

- Served overlay rows (`source=layer2_inplay_overlay`, grid 00:27:30Z, `live_model_probability`):
  - **31 of 92 calibrated-looking, 61 raw.** Raw = an exact multiple of 1/102 or 1/204, the live
    re-sim's count.
  - Pre-load control, reading 11 at 00:04:14Z: **39 of 39 raw.**
- Both kinds sit inside one game and one build. Richmond @ VT:
  - o139.5 = 0.67647 (69/102), u139.5 = 33/102, o141.5 = 61/102;
  - but o142.5 = 0.4231829 (calibrated).
- Iona @ UMBC: 122.5 calibrated (o 0.41906 / u 0.580943); 118 / 119.5 / 120.5 raw.
- **Effect:** the rail flagged a full-game NCAAB over on a raw row (Richmond o139.5). The lane
  reported 0 over leans in its ledger after the load.
- Guess, not verified: the calibration reaches only the line the join prices from the ledger, and
  other books' lines take the raw distribution by another path.
- **Handed to local_1f10ce63** (which relayed the #816 load, lane `ncaab-total-overprojection`) at
  ~6:35 PM CST, with the data path. Nothing changed here.

### NBA live (#811, slow-sport rule)

- **Rows:** 857 (115 main, 742 `_alt`).
  | family | rows | priced <= 120 s |
  |---|---|---|
  | main | 115 | 25 |
  | `_alt` | 742 | 0 |
  - Seen age at pricing p50 212 s (a single 212 s pull for every alt row).
  - As #811 expects: its 60 s pulls refresh main lines only.
- **NBA overlay (16 builds):** build p50 24.6 s, p90 42.0 s, **max 60.5 s**. **1 `deferred_slow`.**
  Gap p50 49 s, **max 235 s**, 0 over 360 s. rows_inplay 2,551.
- NBA flags: 4 shown (17 qualifying rows), 0 dark.

### Rest of the reading

**Live rows:** 1,045.
| sport | rows | priced <= 120 s | seen at pricing p50 |
|---|---|---|---|
| NBA | 857 | 25 | 212 s |
| NCAAB | 187 | 41 | 147 s |
| WNCAAB | 1 | 1 | — |
- NCAAB by phase: 1H 149 / 2H 28 / break 10. 513 rows older than 300 s now (mostly NBA alt).
- Live-rail: 1,049-1,054 rows.

**Overlay (23 min), all 0 over 360 s:**
| sport | gap p50 | gap max | build time p50 / max | zero-card with rows |
|---|---|---|---|---|
| NCAAB | 55 s | 123 s | 7.9 s / 22.3 s | 0 |
| WNCAAB | 59 s | 125 s | — | 11 of 20 (the floor) |

- NFL builds 2.7 / 68.7 s; NHL p50 2.5 s; soccer 8.5 / 27.7 s.
- Tick gap p50 21 s, max 111 s.

**Web merges:** ncaab and wncaab fresh 34 / 34; nba fresh 27; nfl stale (pregame).

**Load:**
- **Query 16.7 s / 82.2 MB** (NBA live adds ~18 MB). Shortlist 1.0 s; chips 0.97 s; live-rail 0.31 s /
  1.0 MB.
- Gunicorn workers were 432 s and 121 s old at the read. The 432 s worker was recycled during the
  probe (a new one was 16 s old at 18:28:02). Host load 5.5 (7.8 over 5 min).
- **Board: shortlist written 828 s ago, build 788 s old** (78-555 s in earlier readings). The board
  build is slow with NBA live; noted, not handed off (the convoy is lane `nba-overlay-card-cost`'s
  reading tonight).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 23 live chips
have a live card.

**Restarts:**
- refresh-worker **2809282 → 2953295** at 00:04:38Z, the #816 load (recorded above).
- live-odds-worker 2925378, unchanged.
