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
