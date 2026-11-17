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

### #816 reachability anomaly — CAUSE CONFIRMED by the owner, fix on main, NOT loaded (~6:45 PM CST)

**From local_1f10ce63:**
- **Cause:** a row refused before pricing (quote or lane age, e.g. `quote_older_than_live_pricing_ceiling`)
  takes its Live number from `live_gameline_join.live_display_block`. That path applied the #780 k but
  not #816, so it showed the engine's Agresti-Coull fraction: the exact multiples of 1/102 seen here.
  Priced rows were calibrated, which is why one game mixed both.
- **Fix on main `d7c183d8d`:** the display block now applies the same calibration against the row's own
  `market_fair_prob_over`. With a calibration in force and no two-sided market, it shows no
  probability. Display blocks carry `total_calibration` plus `prob_over_uncalibrated` or
  `prob_withheld`.
- Checked here: `d7c183d8d` is on origin/main and NOT in the fleet's `69bd95177`. Loading it is the
  user's call.

**PREDICTION, registered for after it loads:** served NCAAB full-game total rows stop carrying exact
k/102 or k/204 values. The raw share falls from 61 of 92 to 0 (rows with no two-sided market carry no
probability). It is falsified if any served row after the load still carries a raw fraction.

**Fleet event:**
- Fleet ff `13ec8f348 -> 69bd95177` at 00:20:21Z (6:20 PM CST): "odds sweep: keep the NFL game-line
  shard line (todo 817)".
- No restart: refresh-worker pid 2953295 unchanged.
- For the MNF read: the `NFL_GAMELINE_QUOTE_SHARD` line should now land in a role log.

## Reading 13 — Mon 11-16 6:50 PM CST (00:50Z 11-17), full page — the last PRE-load sample for the #816 display fix

**Fleet:**
- Still `69bd95177`; refresh-worker pid 2953295.
- The user told the owner "Load it" for `d7c183d8d` (the #816 display fix). The owner session
  (local_1f10ce63, lane `ncaab-total-overprojection`) holds the refresh-worker claim and was
  draining from ~00:36Z. I did not load it in parallel (its request).

**Slate: 29 live chips.**
- NBA 5: HOU @ MIA Q1; CHI @ CLE, ORL @ BOS and MEM @ WAS Q2; PHI @ BKN Q1.
- NHL 1: MTL @ NYR P1.
- 23 college games.

**Flags: 15 new shown on 12 cards. 0 false, 0 missed, 6 DARK.** 11-16 total: 56.
- **NCAAB full-game totals (9):**
  - 8 unders, calibrated: Iona @ UMBC u140.5 (73.2%, 23.8 pp), Alcorn St @ Maryland u179.5,
    Prairie View @ Ohio State u142.5, Grambling @ Kentucky u145.5, Jacksonville @ Georgia u165.5,
    WKU @ Tulsa u154.5, Richmond @ VT u143.5, Tarleton State @ Drake u153.5.
  - 1 over, **RAW**: Citadel @ Clemson o140.5, 0.598039 = 61/102. The same pre-load display-path
    gap as reading 12.
- **NCAAB spreads / moneyline (4):** Iona @ UMBC UMBC -8.5; Grambling @ Kentucky UK -18.5;
  St. Thomas @ LIU LIU -4.5; Tarleton moneyline.
- **NBA spreads (2):** CHI @ CLE CHI +6.5 (13.3 pp; ours CHI -3.1); PHI @ BKN BKN +5.5 (3.8 pp).
- **Display inconsistency (by design, mentioned to the owner):** Richmond @ VT is flagged **UNDER
  143.5** (calibrated 57.6%) while the card's "ours" reads **146.0**. The #816 "level" moves the
  probability, but the projected total (`total_mean`) stays raw. A reader sees an under flag next to
  a projection above the line.
- **Fade-vs-follow series:**
  | game | 5:20 PM | 5:41 PM | 6:04 PM | 6:27 PM | 6:50 PM |
  |---|---|---|---|---|---|
  | Iona @ UMBC | 141.5 / 145.4 | 134 / 142.7 | 126.5 / 136.5 | 122.5 / 124.6 | **140.5 / 133.3** |
  - The book has jumped +18 since 6:27, ours +8.7. The flag is now UNDER, again against the move.
- **Totals direction, flag by flag: 28 unders, 13 overs.** Through 6:27 PM 20 U / 12 O; this reading
  adds 8 U and 1 O (Citadel).
- **6 DARK flags.** All were priced 39-109 s before their grid build but were 393-463 s old when
  served:
  - Prairie View @ Ohio State OSU -23.5 (9.2 pp);
  - St. Thomas @ LIU 1H +0.5 (3.3 pp);
  - WKU @ Tulsa 1H -14.5 (11.2 pp);
  - Richmond @ VT 1H +9.5 (6.6 pp);
  - Albany @ Rutgers u129.5 (3.3 pp);
  - MEM @ WAS 1H o122.5 (10.6 pp).
  - **The served board was 354 s old** (shortlist written 353 s ago). Over the same 2 minutes, both
    gunicorn workers were recycled (146 / 118 s old at the read, 78 / 59 s old at the end) and
    **host load hit 19.5 on 12 cores**.
  - One sample. Recorded; the web-recycle lead already in `leads.md` covers the mechanism. Not
    handed off yet: re-read next reading.

**#816 reachability, pre-load:**
| read | raw | calibrated | other |
|---|---|---|---|
| this reading (`rail.json`) | 47 | 49 | — |
| owner's `/api/board/live-rail` baseline, 00:35Z | 41 | 72 | 5 no-prob |

**NBA:**
| family | rows | priced <= 120 s |
|---|---|---|
| main | 79 | 15 |
| `_alt` | 901 | 0 |

- Seen age at pricing p50 172 s (one pull).
- NBA overlay: build p50 30.4 s, p90 55.6 s, **max 80.2 s**; **2 `deferred_slow`**; gap p50 70 s,
  max 278 s.
- 3 NBA flags (rows), 1 dark (MEM @ WAS 1H).

**NHL:** 3 rows, 0 priced <= 120 s (P1 just started); overlay 3 builds.

**NCAAB:**
- 185 rows (1H 95 / 2H 37 / break 53); 60 priced <= 120 s; seen age at pricing p50 133 s.
- Overlay gap p50 76 s, max 141 s; builds p50 17.0 s, max 41.4 s (all up from earlier readings).

**WNCAAB:** 2 rows; 11 of 16 builds zero-card with rows (the floor).

**Tick gap:** p50 52 s (21-37 s earlier), max 125 s. 0 overlay gaps over 360 s.

**Web merges:** nba / ncaab / wncaab fresh 30 / 30; nhl fresh 6; nfl stale (pregame).

**Load (worst of the day):**
- **`/intelligence` 25.6 s / 36.6 MB. Query 37.2 s / 80.5 MB. Chips 9.8 s. Live-rail 3.3 s.**
  Shortlist 2.1 s.
- Host load 12.8 → 19.5 during the probe. No single process: NFL and NHL odds pulls, an MLS
  artifact build, both workers, both web workers, and a nice-19 research job
  (`/mnt/c/tmp/elp/ncaaf_breakdown/breakdown.py`, 116% CPU, 985 MB).
- This probe's own page + query fetch (117 MB) adds to the web's load. From here, the full page
  only every ~4th reading.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 29 live chips
have a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 2953295, both unchanged.

### #816 display fix LOADED by its owner — prediction MET (7:02 PM CST)

- **Load (owner local_1f10ce63, lane `ncaab-total-overprojection`, user "Load it" there):**
  - fleet ff `69bd95177 -> d7c183d8d` at 00:55:46.694Z;
  - refresh-worker TERM 00:55:46.699Z; new pid **3101432** up 00:55:54.769Z;
  - drain from ~00:36Z, cleared right after.
  - I did not load it in parallel. The user also asked here ("load the #816 display fix"); the owner
    already held the claim.
  - The NBA overlay-cost lane got the restart time: its second mid-slate cold-cache boundary tonight.
- **Verification** (`/api/board/live-rail` at 01:02:49Z and 01:02:50Z, after 2 post-restart NCAAB
  overlay builds; `C:\tmp\ncal816\rawcheck.py`, read-only):
  - NCAAB full-game total rows: **0 raw**, 70 calibrated, 9 no-prob.
  - Flags 6 under, 0 over.
  - Pre-load: 35-47 raw (00:35-00:50Z). **The registered prediction (raw → 0) is MET.**
  - 0 refresh-worker tracebacks since the restart.
- **Display note passed to the owner (by design, not a defect):** an UNDER flag can sit beside a
  raw "ours" total above the line (Richmond @ VT u143.5 vs ours 146.0 at 6:50 PM).

### MNF read 1 — LAC @ BAL after kickoff (7:19 PM CST, 01:19Z 11-17) — registered prediction (fix-loaded branch) MET, thinly

**User 11-16 ~6:58 PM CST: "check the MNF lines after kickoff".** A watcher fired on the first in-play
NFL overlay.

- **Shard:** `nfl_source/tracking/book_quotes/2026-11-16.jsonl` holds **69 rows captured at or after
  01:15Z** (spreads 26, h2h 25, totals 18), all for kickoff 2026-11-17T01:18Z (MNF), last 01:17:13Z.
  There is **no `2026-11-17.jsonl`**. The kickoff-date filing holds after 00:00Z.
- **Overlay:** `INPLAY_OVERLAY sport=nfl date=2026-11-16 rows_inplay=9 opportunities=12 cards=1
  published=True ... refused={"rows_below_value_floor":11}` at 01:18:56Z, the first in-play NFL build.
  It carries MNF under 11-16.
- **Live-rail: 1 LAC @ BAL overlay game-line row** (`source=layer2_inplay_overlay`): totals full
  under 39.5 at +100, book age 115 s, **no model probability**. Same on 3 reads 01:19:33-01:19:53Z.
- **Verdict:** the falsifier (0 LAC @ BAL overlay game-line rows) **did not occur, so the prediction
  is MET.** Before the fix, these rows went to the UTC-dated 11-17 shard, which no 11-16 overlay
  reads.
- **Why only 1 row, and no model price:**
  - `LIVE_GAMELINE_BUILD sport=nfl date=2026-11-16` 01:18:56Z: considered 42, **priceable 0**,
    withheld 42:
    - `segment_is_not_full_game` 31: quarter and half lines are never priced, known;
    - `no_live_gameline_projection` 11.
  - The first `NFL_LIVE_RESIM` with a live game (live_games 1) came at **01:19:33Z, 37 s after** that
    build. So the first in-play build had no live projection yet.
  - Without a model price, the rows carry only market-fair EV, and 11 of 12 fall under the -2% floor:
    the WNCAAB mechanism. Read 2 (~7:45 PM) checks that full-game lines are priced once the re-sim
    is attached.

## Reading 14 — Mon 11-16 7:21 PM CST (01:21Z 11-17) — first full reading on `d7c183d8d` (refresh-worker 3101432)

**Slate: 37 live chips.**
- NBA 7: HOU @ MIA Q2; CHI @ CLE Q3; GSW @ NOP Q1; ORL @ BOS HALF; MEM @ WAS HALF; POR @ MIN Q1;
  PHI @ BKN Q2.
- NFL 1: LAC @ BAL, Q1 12:50.
- NHL 1: MTL @ NYR, P1 2:43.
- 28 college games.

**Flags: 32 shown on 21 cards (58 qualifying rows). 0 false, 0 missed, 0 dark.** 11-16 total: 88.
- **The 6 dark flags of 6:50 PM did not recur.** That was one burst (served board 354 s old, host
  load 19.5). Not handed off. Now: board built 129 s ago; host load 8.4.
- **NCAAB full-game totals: 13 flags, all UNDER, all calibrated (`total_cal`):**
  Prairie View @ Ohio State u142.5, St. Thomas @ LIU u145.5, Grambling @ Kentucky u145.5,
  Citadel @ Clemson u141.5, Jacksonville @ Georgia u160.5, Richmond @ VT u150.5,
  EKU @ Kent State u133.5, WKU @ Tulsa u149.5, Tarleton @ Drake u143.5, Montana @ Kansas State u154.5,
  Central Arkansas @ Oklahoma u163.5, Western Illinois @ Mi* u136.5, Columbia @ Northwestern u127.
  Gaps 5.7-12.2 pp.
  - **The display inconsistency is now systematic: 8 of these 13 UNDER flags show "ours" AT OR ABOVE
    the line.** Columbia u127 vs ours 133.7. St. Thomas u145.5 vs ours 148.0. WIU u136.5 vs ours
    138.3. Also Richmond, WKU, Tarleton, Montana, Central Arkansas.
  - The calibrated probability (level -0.358 logits, engine deviation x 0.229) leans under, while
    `total_mean` stays the engine's. The count was sent to the owner as a follow-up to its 7:02 PM
    note.
- **The raw-fraction flags are all outside #816's scope, as designed:**
  - NCAAB moneylines: EKU (69.5/102) and Central Arkansas (28/102).
  - WNCAAB totals, uncalibrated by the walk-forward gate:
    - Troy @ LSU **u174.5, model 85.8% (raw) vs fair 51.1%, 34.7 pp; ours 160.9**;
    - Arkansas @ UALR u146.5;
    - Albany @ Rutgers o122.5.
- **NCAAB spreads (6), moneylines (3, including St. Thomas):** Kentucky -28.5, Clemson -22.5,
  Georgia -29.5, VT -9.5, EKU -6, Tarleton +4.5.
- **NBA (8):**
  - spreads: WAS -6.5, PHI -17.5, POR -3.5;
  - totals: ORL @ BOS 2H o103.5 (11.5 pp), MEM @ WAS o240.5, PHI @ BKN Q2 u57.5, GSW @ NOP o214.5.
- **Totals direction, flag by flag: 44 unders, 17 overs.** This reading's 20 totals flags: 16 U
  (13 NCAAB full, WNCAAB Troy + Arkansas, NBA PHI @ BKN Q2) and 4 O (WNCAAB Albany, NBA ORL @ BOS 2H,
  MEM @ WAS, GSW @ NOP).
- The fade-vs-follow series for Iona @ UMBC ends at 6:50 PM (the game is no longer flagged).

**Live rows:** 1,342.
| sport | rows | priced <= 120 s | split |
|---|---|---|---|
| NBA | 1,011 | 23 | 102 main (23 fresh) / 909 `_alt` (0 fresh); one 137 s pull |
| NCAAB | 275 | 93 | 1H 137 / 2H 131 / break 7 |
| NFL | 25 | 11 | 1H 25 |
| WNCAAB | 29 | 12 | — |
| NHL | 2 | 1 | — |

- 21 of 156 markets carry no price of ours (the NFL ones; see MNF read 2).
- Live-rail: 1,313-1,343 rows.

**Overlay (32 min; the window spans the 00:55 restart):**
| sport | gap p50 | gap max | build p50 / max | notes |
|---|---|---|---|---|
| NBA | 64 s | **515 s** | 36.5 s / **94.5 s** | **4 `deferred_slow`** |
| NCAAB | 73 s | 365 s | 13.6 s / 32.3 s | |
| WNCAAB | 65 s | 383 s | — | |
| NHL | 98 s | 457 s | — | |
| NFL | — | — | 14.2 s / **99.7 s** | 2 builds, **1 `deferred_slow`** |

- **One gap over 360 s in each of NBA, NCAAB, WNCAAB and NHL.** Tick gap max 398 s: consistent with
  the drain (~00:36Z) and the 00:55:46Z restart, which fall inside this window. Re-check next
  reading, which will be clean.
- Zero-card with rows: WNCAAB 6 of 20, NHL 1 of 14.

**Web merges:** ncaab and wncaab fresh 40 / 40; nhl 39 / 40; nba 38 / 40; nfl 6 fresh / 34 stale
(pregame until 7:15).

**Load:**
- **Query 14.4 s** / 83.0 MB. Shortlist 1.3 s; chips 2.1 s; live-rail 0.19 s / 1.25 MB.
- Gunicorn workers were 85 s and 21 s old at the read, both still alive at the end. Host load 8.4.
- **Board:** built 129 s ago; shortlist written 375 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 37 live chips have
a live card.

**Restarts:**
- refresh-worker 2953295 → **3101432** at 00:55:46Z (the #816 display fix, recorded above).
- live-odds-worker 2925378, unchanged.

### MNF read 2 — 7:46 PM CST (01:46Z): the lines reach the rail, but NONE carries a model price (a known guard)

- **Live-rail: 30 LAC @ BAL rows, all `source=layer2_inplay_overlay`, all with
  `live_model_probability` = None.**
  - Full-game: 8 totals.
  - Segments: 1H totals 6, Q1 totals 5, Q3 totals 3, Q4 totals 2, 2H totals 2, Q2 total 1,
    Q1 / Q3 spreads 1 each, 1H moneyline 1.
  - By 7:48 PM, 17 rows (Q1 3:53).
- **Overlay:** 18 `INPLAY_OVERLAY nfl date=2026-11-16` builds since 01:15Z. The last ones show
  `rows_inplay=237 opportunities=307-310 cards=189` and
  `refused={"rows_below_value_floor":81-84,"rows_implausible_book":19,"rows_uninformative_ev":18}`.
- **`LIVE_GAMELINE_BUILD nfl 2026-11-16`, every build 01:37-01:45Z:** considered 70-71, **priceable
  0**. Withheld by reason: `no_live_gameline_projection` 26-27 (full game) and
  `segment_is_not_full_game` 44.
- **Why there is no projection:** `NFL_LIVE_RESIM` sees the game (`live_games 1`, live player stats
  attached) but `live_resimmed 0`, `refusals_by_reason {"game_final":13,"uninformative_probability":1}`.
  - The guard is `syndicate/features/nfl/live_resim.py:581-588`, `UNINFORMATIVE_BAND = (0.35, 0.65)`
    (line 172). A live home-win probability inside the band refuses the WHOLE re-sim: totals and
    spreads lose their projection too, not only the moneyline.
  - The guard is deliberate ("Remove this guard when that gate exists") and already recorded:
    `findings_2026-11-15_nfl_live_width_fit.md:40`, and this monitor's 11-15 findings (SNF, MIN @ GB,
    MIA @ IND).
  - Since 00:00Z 11-16: `live_resimmed` 0 on 142 of 143 NFL_LIVE_RESIM ticks.
- **My read-2 expectation ("full-game lines priced once the re-sim attached") was WRONG.** The
  re-sim attaches but refuses a close game. The registered prediction (overlay game-line rows on the
  rail) stays MET.
- Consequence: no MNF flag can show while the game is inside the band. Not handed off: it is a known,
  deliberate guard. Whether its blast radius should be limited to the moneyline is a product and
  engine question for the NFL live-engine lanes.

## Reading 15 — Mon 11-16 7:48 PM CST (01:48Z 11-17) — the slowest board of the day; NBA rows go dark

**Slate:** 35 live chips.
- NBA 7: HOU @ MIA HALF; CHI @ CLE Q3; GSW @ NOP Q2; ORL @ BOS Q3; MEM @ WAS Q3; POR @ MIN Q2;
  PHI @ BKN Q2.
- NFL LAC @ BAL Q1 3:53; NHL MTL @ NYR P2.
- 26 college games.

**Flags: 51 shown on 23 cards (127 qualifying rows). 0 false, 0 missed. 70 DARK rows / 27 dark
markets.** 11-16 total: 139.
- **Dark = NBA, mostly `spreads_alt`.** They were priced 79-118 s before their grid build but served
  318-357 s old. E.g. ORL @ BOS alt spreads -14.5 / -13.5 / -6.5 / -5.5 at 16.5-17.4 pp; MEM @ WAS
  +6.5.
  - NBA overlay: builds p50 **57.7 s**, p90 90.3 s, max **101.8 s**; **4 `deferred_slow`**; gap p50
    139 s, max 374 s, **2 gaps over 360 s**.
  - This is the slow-sport cadence cost: NFL/NBA decision still owed by the user, owner
    local_208683f1.
  - **NBA alts are priced fresh now:** 466 of 802 `_alt` rows priced <= 120 s, vs 0 at 6:27-7:21 PM.
    Many go dark only because the overlay serves them ~4-5 min after pricing.
  - The NBA flags that are shown sit at 273-291 s of their 300 s limit.
- **NCAAB full-game totals (11), all UNDER and calibrated:** Grambling u149.5, St. Thomas u149.5,
  Jacksonville u170.5, Richmond u154.5, WKU u147.5, EKU u119.5, Tarleton u153.5, Western Illinois
  u154.5, Columbia u121.5, Central Arkansas u162.5, SE Louisiana @ Texas A&M u166.5.
- **WNCAAB totals (3), all UNDER and RAW** (out of #816's scope):
  - Troy @ LSU u177.5, 78.9% vs 49.4%, 29.6 pp;
  - Michigan @ Central Michigan u146.5, 18.7 pp;
  - Arkansas @ UALR u142.5, 20.7 pp.
- **NBA totals (13):**
  - 8 OVER: MEM @ WAS full o250.5 and Q4 o51.5; ORL @ BOS full o209.5 and 2H o113.5; PHI @ BKN Q4
    o50.5; POR @ MIN o222.5; GSW @ NOP 1H o92.5 and Q2 o46.5.
  - 5 UNDER: HOU @ MIA full u221.5 and Q4 u66.5; PHI @ BKN full u239.5 and Q3 u52.5; GSW @ NOP
    u204.5.
- **Others:**
  - NCAAB spreads and moneylines (8; Tarleton moneyline raw);
  - NHL MTL @ NYR moneyline (raw, uncalibrated sport);
  - NBA spreads (11), largest GSW @ NOP NOP -22.5 at 22.6 pp and HOU @ MIA MIA -23.5 at 22.5 pp.
- **Totals direction, flag by flag: 63 unders, 25 overs.** Through 7:21 PM 44 U / 17 O; this reading
  adds 19 U (11 NCAAB, 3 WNCAAB, 5 NBA) and 8 O (all NBA).

**Live rows:** 1,255.
| sport | rows | priced <= 120 s | split |
|---|---|---|---|
| NBA | 928 | 519 | 126 main (53 fresh), 802 `_alt` (466 fresh); 1H 489 / 2H 307 / break 132 |
| NCAAB | 285 | 82 | 1H 54 / 2H 173 / break 58 |
| WNCAAB | 24 | 8 | — |
| NFL | 17 | 6 | no model price |
| NHL | 1 | 1 | — |

- 827 rows older than 300 s now. 21 of 145 markets carry no price of ours (NFL).

**Overlay (27 min):**
| sport | builds | gap p50 / max | build p50 / max | notes |
|---|---|---|---|---|
| NBA | 7 | 139 s / 374 s | 57.7 s / 101.8 s | 2 gaps over 360 s |
| NFL | 18 | 80 s / 211 s | 12.7 s / 76.0 s | |
| NHL | 15 | 84 s / 295 s | — | 9 zero-card with rows |
| NCAAB | 19 | 63 s / 202 s | 16.8 s / 34.1 s | |
| WNCAAB | 16 | 112 s / 193 s | — | |

- Only NBA has gaps over 360 s in this window, so the other sports' >360 s gaps at 7:21 PM were the
  restart.
- Tick gap p50 35 s, max 141 s.

**Web merges:** all fresh 43 / 43 (nba, nhl, nfl, ncaab, wncaab).

**Load:**
- **Query 78.3 s / 80.3 MB, the slowest of two days.** Shortlist 4.6 s; chips 0.44 s; live-rail
  0.14 s.
- Gunicorn workers were 159 s and 109 s old at the read. **Both were replaced during the 2-minute
  probe** (105 s and 19 s old at the end). Host load 6.0 → 4.7: not host contention. The cold-worker
  lead in `leads.md` again.
- **Board: shortlist written 1,287 s (21 min) ago, build 1,186 s old.** That is the
  board build's interpreter-lock convoy with 7 NBA games live, lane `nba-overlay-card-cost`'s
  measurement tonight. The live rows come from the overlay, not the shortlist.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 35 live chips have
a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 3101432, both unchanged.

## Reading 16 — Mon 11-16 8:13 PM CST (02:13Z 11-17), full page

**Slate:** 27 live chips.
- NBA 8: HOU @ MIA Q3; CHI @ CLE Q4; GSW @ NOP end Q2; ORL @ BOS Q4; MEM @ WAS Q4; POR @ MIN HALF;
  PHX @ DEN Q1; PHI @ BKN Q3.
- NFL LAC @ BAL Q2 10:16; NHL MTL @ NYR P2.
- 17 college games.

**Flags: 23 shown on 14 cards (40 qualifying rows). 0 false, 0 missed, 0 DARK.** 11-16 total: 162.
- **The 7:48 PM dark burst (70 rows) cleared.** NBA builds p50 24.4 s, max 64.8 s, 2
  `deferred_slow`; NBA gap max 320 s, 0 over 360 s.
- **NBA `_alt`:** 0 of 899 rows priced <= 120 s again (466 of 802 at 7:48). So an alt pull ran around
  7:4x and none since. #811's 60 s pulls stay main-only.
- **Totals: 12 flags, 10 UNDER / 2 OVER.**
  - NCAAB full-game, all calibrated: WKU @ Tulsa u139.5, Tarleton @ Drake u156.5, Columbia @
    Northwestern u128.5, Western Illinois @ Minnesota u156.5, Central Arkansas @ Oklahoma u167.5,
    SE Louisiana @ Texas A&M u165.5.
  - **Tarleton @ Drake 2H u87.5 is RAW** (66/102). #816 calibrates full-game totals only; segment
    totals are outside its scope.
  - WNCAAB, RAW: Troy @ LSU u181.5 (**36.1 pp**, ours 169.4); Michigan @ Central Michigan u142.5
    (17.3 pp).
  - NBA: MEM @ WAS u244.5; ORL @ BOS o207.5; POR @ MIN o220.5 (12.3 pp).
  - Under flag beside an "ours" above the line, again: Columbia u128.5 vs 130.3; Central Arkansas
    u167.5 vs 168.6; also NBA MEM @ WAS u244.5 vs 245.7.
- **Spreads and moneylines (11):** NBA MEM -10.5 at **26.8 pp**, PHI -18.5, ORL +2.5 (full and Q4),
  CLE -14.5, MIA -13.5; NCAAB Minnesota -39.5, Columbia -2.5, Tulsa -2.5 and moneyline, Tarleton +1.5.
- **Totals direction, flag by flag: 73 unders, 27 overs.** This reading adds 10 U (6 NCAAB full,
  1 NCAAB 2H, 2 WNCAAB, 1 NBA) and 2 O (NBA).

**MNF (LAC @ BAL, Q2 10:16):**
- 15 NFL rows on live-rail, 10 priced <= 120 s by the book; **0 with a model price**.
- `NFL_LIVE_RESIM` resimmed the game ONCE, at 01:55:39Z (`live_resimmed 1`, refusals only
  `game_final` 13). It went back to `uninformative_probability` from 02:01Z.
- `LIVE_GAMELINE_BUILD`: priceable 0, `no_live_gameline_projection` 30. No MNF flag can show while
  P(home) stays inside 0.35-0.65.

**Live rows:** 1,242.
| sport | rows | priced <= 120 s | split |
|---|---|---|---|
| NBA | 1,065 | 35 | main 166 (35 fresh), `_alt` 899 (0 fresh); 1H 356 / 2H 537 / break 172 |
| NCAAB | 143 | 44 | 2H 127 |
| WNCAAB | 18 | 6 | — |
| NFL | 15 | 10 | no model price |
| NHL | 1 | — | — |

- 380 rows older than 300 s now. 23 of 118 markets carry no price of ours.

**Overlay (25 min):**
| sport | gap p50 / max | build p50 / max | notes |
|---|---|---|---|
| NBA | 59 s / 320 s | — | |
| NCAAB | 59 s / 188 s | — | |
| WNCAAB | 85 s / 210 s | — | |
| NFL | 108 s / 264 s | 12.1 s / 76.0 s | 1 `deferred_slow` |
| NHL | 117 s / **375 s** (1 over 360 s) | — | 6 of 12 zero-card with rows |

- Tick gap p50 28 s, max 135 s.

**Web merges:** fresh 58 / 58 everywhere except NHL 57 / 58.

**Load:**
- `/intelligence` 11.5 s / 35.0 MB. **Query 8.2 s** / 76.8 MB. Shortlist 1.1 s; chips 2.2 s;
  live-rail 0.14 s.
- Gunicorn workers were 77 s and 35 s old at the read, both alive at the end (126 / 84 s). Host
  load 4.7.
- **Board:** built 154 s ago; shortlist written 229 s ago (1,287 s at 7:48 PM).

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 27 live chips have
a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 3101432, both unchanged.

## Reading 17 — Mon 11-16 8:36 PM CST (02:36Z 11-17)

**Slate:** 25 live chips.
- NBA 5: HOU @ MIA Q4; GSW @ NOP Q3; POR @ MIN Q3; PHX @ DEN end Q1; PHI @ BKN end Q3.
- NFL LAC @ BAL Q2 1:05.
- NHL 2: MTL @ NYR end P2; VAN @ UTA P1.
- 17 college games.

**Flags: 47 shown on 13 cards (162 qualifying rows). 0 false, 0 missed, 0 dark.** 11-16 total: 209.
- **NBA: 36 flags (148 qualifying rows).**
  - NBA `_alt` priced fresh again: 511 of 761 rows priced <= 120 s.
  - NBA builds p50 20.6 s, max 45.2 s; **0 `deferred_slow`**; gap max 86 s. The cadence keeps up at
    5 games.
- **PRE-REGISTERED here, before any NBA final is read: NBA TAIL flags.** Several NBA flags sit on
  deep alt lines where our live distribution is far wider than the book's:
  | game | flag | model | book | ours |
  |---|---|---|---|---|
  | POR @ MIN | u199.5 | 27.3% | 3.8% | 217.7 |
  | GSW @ NOP | u203.5 | 37.2% | 12.7% | 215.0 |
  | PHX @ DEN | u208.5 | 38.3% | 30.1% | 220.7 |
  - These are not flipped sides: the side is the lean, and the tail is fatter than the market's (#780
    k widening).
  - Tonight's grade splits NBA flags by book fair: TAIL (fair < 0.20 or > 0.80) vs BODY (0.20-0.80).
    Each half's hit rate and Brier against the book, game-clustered.
- **Totals: 25 flags, 16 UNDER / 9 OVER.**
  - NCAAB full-game, calibrated, 2 U: Tarleton @ Drake u158.5 (17.2 pp); East Texas A&M @ Oregon
    u150.5.
  - NCAAB 2H, RAW (outside #816's full-game scope): Western Illinois u75.5, Columbia u78.5 (U);
    Montana o73.5 (O).
  - WNCAAB, RAW, 3 U: Troy @ LSU u180.5 (21.7 pp), Michigan @ Central Michigan u136.5, Arkansas @
    UALR u147.5.
  - NBA 9 U: HOU @ MIA full / 2H / Q4; POR @ MIN full / 2H / Q3; GSW @ NOP full / Q3; PHX @ DEN full.
  - NBA 8 O: PHI @ BKN full / 2H / Q4; POR @ MIN Q4; GSW @ NOP Q4; PHX @ DEN 1H / Q2 / Q4.
- **Spreads and moneylines (22):** NBA 19, e.g. GSW @ NOP NOP -23.5 (22.0 pp), HOU @ MIA Q4 MIA
  -3.5 (21.1 pp), POR @ MIN MIN -12.5 (20.3 pp). NCAAB Minnesota -37.5 and Columbia moneyline;
  WNCAAB UALR moneyline.
- **Totals direction, flag by flag: 89 unders, 36 overs.** This reading adds 16 U (4 NCAAB,
  3 WNCAAB, 9 NBA) and 9 O (1 NCAAB, 8 NBA).

**MNF (LAC @ BAL, Q2 1:05): still 0 priced.**
- 25 NFL rows on live-rail, 6 priced <= 120 s by the book, 0 flags.
- `NFL_LIVE_RESIM` resimmed again at **02:33:52Z** (refusals only `game_final`). The other ticks
  02:18-02:28Z were `uninformative_probability`.
- **Even with a projection, 0 lines price.** `LIVE_GAMELINE_BUILD` projected 19-20, priceable 0,
  withheld by reason:
  - `live_resim_published_no_distribution_for_this_market` 18-19;
  - `quote_older_than_live_pricing_ceiling` 8-9;
  - `prob_interval_swamps_edge` 1;
  - segments 34.
- **Known and deliberate:** `findings_2026-11-15_nfl_live_width_fit.md`. NFL live totals and spreads
  have never priced: `nfl/live_resim.py` withholds `marginDist` / `totalRunsDist` because the
  2026-09-27 grade found NFL live margins ~35-40% too narrow (#780 width fit pending). Only the NFL
  moneyline can price live, and the uninformative band refuses it in a close game. So MNF shows lines
  but cannot flag. Not handed off.

**Live rows:** 1,102.
| sport | rows | priced <= 120 s | split |
|---|---|---|---|
| NBA | 953 | 595 | 2H 518 / break 435 |
| NCAAB | 102 | 22 | 1H 13 / 2H 89 |
| NFL | 25 | 6 | no model price |
| WNCAAB | 19 | 8 | — |
| NHL | 3 | 2 | — |

- 358 rows older than 300 s now. 24 of 98 markets carry no price of ours.

**Overlay (23 min), all 0 over 360 s:**
| sport | gap p50 / max | build p50 / max | notes |
|---|---|---|---|
| NBA | 63 s / 86 s | 20.6 s / 45.2 s | |
| NCAAB | 67 s / 129 s | — | |
| WNCAAB | 77 s / 143 s | — | |
| NHL | 61 s / 189 s | — | 5 of 17 zero-card with rows |
| NFL | 80 s / 140 s | 10.1 s / 39.4 s | |

- 0 `deferred_slow`. Tick gap p50 18 s, max 82 s.

**Web merges:** fresh 66 / 66 for every sport.

**Load:**
- **Query 9.1 s** / 74.3 MB. Shortlist 0.75 s; chips 1.8 s; live-rail 0.08 s.
- Gunicorn workers were 258 s and 34 s old at the read. The 258 s worker was recycled during the probe
  (a new one was 25 s old at the end). Host load 3.0.
- **Board:** built 84 s ago; shortlist written 84 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 25 live chips have
a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 3101432, both unchanged.

## Reading 18 — Mon 11-16 8:59 PM CST (02:59Z 11-17)

**Slate:** 17 live chips.
- NBA 4: GSW @ NOP end Q3; POR @ MIN Q4; PHX @ DEN Q2; PHI @ BKN Q4.
- NFL LAC @ BAL at HALF.
- NHL 2: MTL @ NYR P3; VAN @ UTA P1.
- 10 college games.

**Flags: 12 shown on 7 cards (18 qualifying rows). 0 false, 0 missed, 0 dark.** 11-16 total: 221.
- **Totals: 8 flags, 5 UNDER / 3 OVER.**
  - NCAAB full-game, calibrated, U: SE Louisiana @ Texas A&M u165.5; East Texas A&M @ Oregon u163.5.
  - NCAAB 1H, RAW: East Texas A&M @ Oregon u81.5 (U).
  - WNCAAB, RAW, U: Troy @ LSU u191.5 (**29.1 pp**; Troy @ LSU has been flagged under at every
    reading since 7:21 PM: the line went 174.5 (7:21) → 177.5 (7:48) → 181.5 (8:13) → 180.5 (8:36) →
    191.5 (8:59), and every flag was against that rise, a fade-vs-follow case);
    Arkansas @ UALR u154.5.
  - NBA O: PHI @ BKN o248.5, POR @ MIN o214.5, PHX @ DEN o219.5.
- **Spreads and moneylines (4):** NBA 2 spreads and 1 moneyline; NCAAB 1 spread.
- **Totals direction, flag by flag: 94 unders, 39 overs.** This reading adds 5 U and 3 O.

**MNF (LAC @ BAL, HALF):**
- **`NFL_LIVE_RESIM` now resims on every tick** (02:39, 02:45, 02:50, 02:56Z: `live_resimmed 1`,
  refusals only `game_final`). P(home) has left the 0.35-0.65 band.
- **Still 0 priceable.** `LIVE_GAMELINE_BUILD` projected 8, withheld by reason:
  - `live_resim_published_no_distribution_for_this_market` 7: totals and spreads, the #780 gate;
  - `quote_older_than_live_pricing_ceiling` 4-8: the moneyline at halftime, books standing still past
    the 600 s NFL ceiling;
  - `prob_interval_swamps_edge` 1;
  - segments 37.
- 5 NFL rows on live-rail, 0 priced <= 120 s. Expected: the moneyline can price after halftime,
  once quotes move again.

**Live rows:** 697.
| sport | rows | priced <= 120 s | split |
|---|---|---|---|
| NBA | 613 | 25 | main 132 (25 fresh), `_alt` 481 (0 fresh) |
| NCAAB | 55 | 14 | — |
| WNCAAB | 18 | 8 | — |
| NHL | 6 | 4 | — |
| NFL | 5 | 0 | — |

- 299 rows older than 300 s now. 12 of 64 markets carry no price of ours.

**Overlay (23 min), all 0 over 360 s, 0 zero-card builds:**
| sport | gap p50 / max | build p50 / max |
|---|---|---|
| NBA | 59 s / 96 s | 17.0 s / 40.4 s |
| NCAAB | 55 s / 110 s | — |
| WNCAAB | 58 s / 116 s | — |
| NHL | 68 s / 174 s | — |
| NFL | 85 s / 180 s | — |

- 0 `deferred_slow`. Tick gap p50 19 s, max 66 s.

**Web merges:** fresh 55 / 55 for every sport.

**Load:**
- **Query 7.5 s** / 63.4 MB. Shortlist 0.5 s; chips 1.7 s; live-rail 0.06 s.
- Gunicorn workers were 92 s and 89 s old at the read. One was recycled during the probe (a new one was
  5 s old at the end). Host load 3.3-4.2.
- **Board:** built 99 s ago; shortlist written 98 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 17 live chips have
a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 3101432, both unchanged.

## Reading 19 — Mon 11-16 9:22 PM CST (03:22Z 11-17), full page

**Slate:** 13 live chips.
- NBA 3: GSW @ NOP Q4; POR @ MIN Q4; PHX @ DEN HALF.
- NFL LAC @ BAL Q3 5:49.
- NHL 2: MTL @ NYR P3; VAN @ UTA end P1.
- NCAAB 5: SE Louisiana @ Texas A&M H2; East Texas A&M @ Oregon State; Long Beach State @ UCLA;
  Texas Southern @ UC San Diego; Portland State @ Saint Mary's.
- WNCAAB 2: Arkansas @ Little Rock Q4; Houston Christian @ Utah Q3.
- Troy @ LSU is final. Its series ended at u191.5 (8:59 PM).

**Flags: 17 shown on 8 cards (28 qualifying rows). 0 false, 0 missed, 1 dark** (Texas Southern @ UCSD
spread). 11-16 total: 238.
- **Totals: 12 flags, 9 UNDER / 3 OVER.**
  - NCAAB full-game, calibrated, all U: SE Louisiana @ Texas A&M u171.5 (15.5 pp), East Texas A&M @
    Oregon State u171.5, Texas Southern @ UCSD u168.5, Portland State @ Saint Mary's u164.5 (14.3 pp),
    Long Beach State @ UCLA u139.5 (ours 143.6: the display inconsistency again).
  - NCAAB segments, RAW: Texas Southern 1H u84.5 and 2H u82.5; Portland State 1H u81.5 (21.4 pp)
    (U); Long Beach State 2H o76.5 (O).
  - NBA: GSW @ NOP u210.5 (U); POR @ MIN o207.5 and PHX @ DEN o221.5 (O).
- **Spreads (5):** NBA MIN -14.5, PHX +4; NCAAB Texas A&M -28.5, UCSD -12.5, Long Beach State 1H +17.5.
- **Totals direction, flag by flag: 103 unders, 42 overs.** This reading adds 9 U and 3 O.

**MNF (LAC @ BAL, Q3 5:49): the first NFL line priced, but it did not reach the rail.**
- `NFL_LIVE_RESIM` resims every tick from 03:07Z; it was `uninformative_probability` at 03:01Z.
- `LIVE_GAMELINE_BUILD` 03:1xZ: considered 64, projected 17, **priceable 1**. Withheld:
  `no_distribution` 16 (the #780 gate), quote age 4, segments 43. The 1 priced line is the moneyline
  (only it carries a distribution).
- **Live-rail 03:23:01Z: 4 NFL rows, 0 with a model probability, no moneyline row.** The priced line
  did not reach the rail: the overlay's shortlist dropped it (most likely the value floor, which
  refuses 81-84 NFL rows per build). The rail cannot show MNF flags tonight.

**Live rows:** 529.
| sport | rows | priced <= 120 s | notes |
|---|---|---|---|
| NBA | 385 | 15 | main 75 (15 fresh), `_alt` 310 (0 fresh) |
| NCAAB | 124 | 47 | 1H 110 |
| NFL | 11 | 5 | no model price |
| NHL | 8 | 4 | — |
| WNCAAB | 1 | 0 | — |

**Overlay (23 min), all 0 over 360 s:**
| sport | gap p50 / max | build p50 / max | notes |
|---|---|---|---|
| NBA | 55 s / 87 s | 14.3 s / 36.6 s | |
| NCAAB | 50 s / 112 s | — | |
| WNCAAB | 57 s / 100 s | — | 6 zero-card with rows |
| NHL | 72 s / 132 s | — | |
| NFL | 73 s / 148 s | — | |

- 0 `deferred_slow`. Tick gap p50 20 s, max 65 s.

**Web merges:** fresh 56 / 56 for every sport.

**Load:**
- `/intelligence` 4.1 s / 24.6 MB. **Query 5.6 s** / 61.4 MB. Shortlist 0.83 s; chips 0.03 s;
  live-rail 0.03 s.
- Gunicorn workers were 119 s and 100 s old at the read, both alive at the end. Host load 3.0-3.4.
- **Board:** built 226 s ago; shortlist written 320 s ago.

**Teams:** 0 chip-less, det1 / det2 / det3 0 / 0 / 0, 0 flipped, 0 truncated. All 13 live chips have
a live card.

**Restarts:** live-odds-worker 2925378 and refresh-worker 3101432, both unchanged.
