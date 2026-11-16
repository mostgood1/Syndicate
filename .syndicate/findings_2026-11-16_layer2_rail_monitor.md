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
