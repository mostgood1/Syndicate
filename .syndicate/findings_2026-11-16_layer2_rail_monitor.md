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
