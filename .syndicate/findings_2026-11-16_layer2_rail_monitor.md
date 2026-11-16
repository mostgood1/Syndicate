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
