# Layer 2 Games Rail — standing monitor AND improvement hunt, 2026-11-18 (lane `layer2-rail-monitor`)

Day 4 of the monitor.
- **User (typed in this session): "Yes, from noon"**, answering "Monitor Wednesday 11-18?".
- Confirmed in the ncaab-total-overprojection session ~9:5x AM CST, relayed by local_1f10ce63 verbatim:
  **"monitor the rail Wednesday Nov 18"**.
- The 11-17 standing instruction still holds: **"ensure not only are we monitoring but we should ALSO be
  looking for any and all optimizations or improvements that we can make"**.

Method as on 11-15..11-17:
- Probe `scripts/layer2_rail_monitor_probe.py`; grader `scripts/layer2_rail_flag_grade.py`.
- Wrapper `C:\tmp\railmon\grade1118.py` (the pre-registered splits below).
- Day-3 helpers in `C:\tmp\railmon`, with their windows moved to 11-18.
- Times are Central (CST) unless marked Z.
- Day 3: `.syndicate/findings_2026-11-17_layer2_rail_monitor.md` (daily summary `99ce9489d`); page
  https://claude.ai/artifact/HBPdAGfJxCjGcAF76iNx2f.

## Starting state, read 11:57 AM CST (17:57Z)

**Fleet:** `59fbefc71`, from an ff at 10:33:54 AM CST (fleet reflog).
- refresh-worker pid 152916; live-odds-worker pid 23141.
- **The board split is ON** (`REFRESH_WORKER__SYNDICATE_BOARD_BUILD_PROCESS=1`, BC-042, since 08:30:50Z). Per the
  split's session, it came back after all four of today's restarts.

**Loaded since the day-3 summary (deploys.md / betting_changes.md on main):**

| time (CST) | what | lane / session |
|---|---|---|
| 2:02 AM (08:02:54Z) | refresh-worker TERM: I-17 calibrated college total (`923869cf3`) + NFL re-sim seeds (BC-041) | ncaab-total-overprojection |
| 2:30 AM (08:30:50Z) | drained down/up + ff `09eddabf2`: **the board build in its own process** (BC-042, todo #832) | layer2-board-process-split (local_9c4bd078) |
| 6:37 AM (12:37:52Z) | drained down + WSL vhdx compaction + up (no code) | vhdx-reclaim |
| 7:47 AM (13:47:14Z) | ff `2ae0c646a`: **I-22 live odds lane fix** (BC-046; per-sport deadline, NHL live generation deferred, 900 s, 30-min cooldown). User "Load it now" | odds-lane-sport-deadline (local_73a5d2dd) |
| 8:05 AM (14:05:18Z) | drained down/up + env: **I-21 NHL in-play props pull ON** (todo #837) | nhl-inplay-props-drop (local_ce6ce550) |
| 8:42 AM (14:42:44Z) | ff `36a9f5501` + refresh-worker TERM: **#816 gate fallback** (BC-048) | ncaab-total-overprojection (local_1f10ce63) |
| 9:39 AM (15:39:55Z) | ff `d1e14be46` + refresh-worker TERM: book grid game-state join builds LEAN chips (#790 lever ii) | nba-grid-lean-chips |
| 9:56 AM (15:56:43Z) | ff `cdab875d5`: **pregame NHL generation split** (BC-049; first child 16:07:01Z). User "Yes, load it" | odds-lane-sport-deadline |
| 10:33 AM (ff) / counted from 10:45 AM | ff `59fbefc71`: **NHL stats-REST report cache** (BC-050, #839) | nhl-stats-rest-cache (local_902a702b, closed) |

**What each load changes, as its owner measured it:**
- **BC-048:** a college totals phase whose fit failed walk-forward serves the MARKET. So **today's NCAAB and
  WNCAAB PREGAME totals carry no edge and no pregame college total flags.** NCAAB live stays calibrated
  (a −0.159, c 0.250).
- **BC-049 first sweep:** 402 s. NHL odds 78 s, then the rebuild after every other sport, 293 s.
- **BC-050:** pregame NHL generation for 11-18 + 11-19 went **293 s -> 85 s**, with **14 stats calls instead of
  180** and lineups byte-identical to a cache-off rebuild.
- **NHL generation timing from here mixes BC-049 + BC-050.**

**Loading now, not yet on the fleet at 11:57 AM:** the soccer look-ahead fix `640c6d4fd`
(`SYNDICATE_SOCCER_LOOKAHEAD_DATE_ANCHOR`, BC `no`; user "Load it now" in local_68526c0a).
- Preflight was on HOLD behind look-ahead run 170717 on the old code. The ff time will be in deploys.md.
- **Correction carried from that session:** soccer NEVER held the live-odds-worker's live lane.
  - It caused 0 of the 430 `lane_busy` refusals 11-14..11-18. 169 were NHL-led pregame runs (fixed by BC-049);
    256 were live blocking live.
  - The ~46-min soccer holds were refresh-worker's hourly LOOK-AHEAD re-simulating 7 days: p50 1,201 s,
    max 3,035 s, 86 runs.
- **A lead it handed on (todo #840):** 3 NBA/college pregame runs around 12:01 AM CST held the LIVE lane for 1,800 s
  each and kept no results. Watch at midnight.

**The first game:** Jackson St @ Baylor (NCAAB) tipped 11:01 AM CST (17:01:43Z), before this was written.
- At 11:57:30 AM: 12 rail rows, all from that game.
- 8 of 8 full-game total rows carry `live_total_basis: "calibrated"`.

## PRE-REGISTERED for 11-18 (written 11:57 AM-12:05 PM CST)

Jackson St @ Baylor tipped at 11:01 AM, before this block was written.

**Population for P3-P5:**
- Flags first sighted on 11-18 CT.
- Games commencing at or after 18:05Z (12:05 PM CST).
- Graded against final chips, game-clustered bootstrap, 90% interval on (hit − book fair), the same method as 11-17.
- Games that tipped before 12:05 PM are reported separately and never pooled into a verdict.

### Predictions

- **P1 (I-17, owed by its load):**
  - College full-game totals rows on `/api/board/live-rail` carry `live_total_basis: "calibrated"`.
  - Each reading shows **0** flags whose "ours" sits on the other side of the line from the flagged side, counting
    only flags whose flagged-side model P > 0.5.
  - Falsified by any reading with >= 1 such contradiction that persists to the next reading.
  - The peer's own `/api/board/live-rail` watcher (local_1f10ce63) is the cross-check.
- **P2 (I-20 board split; the formal prediction belongs to the split's session, verdict at 10:15 PM CST):**
  - Measured over 5:30-10:30 PM CST against the 11-17 evening (median 253 s, max 1,510 s):
    - `BOARD_BUILD_TIMING` wall median **< 253 s** and max **< 1,510 s**;
    - no today-board publication gap over 900 s outside a drain.
  - Falsified if the evening max is >= 1,510 s, or the median is >= 253 s.
- **P3 (exploratory on 11-17, registered now):**
  - Flags sighted on a game's FIRST reading, with no prior main line on the rail, hit BELOW their mean fair.
  - Falsified if they hit >= fair on >= 10 games.
- **P4 (T1 again):**
  - Flags with book fair < 0.40 hit at most their mean fair + 2 pp.
  - Falsified if they beat fair by more than 2 pp on >= 10 games.
  - Evidence for I-1's per-line tail calibration, **never a band gate** (the user's every-line rule).
- **P5 (report, not a gate):**
  - NCAAB calibrated full-game LIVE totals flags: hit vs fair, the over share of the flagged lines, and the night's
    all-totals over share.
  - The #816 owner's 7-day grade (11-17..11-23) is the verdict.
- **P6 (BC-048; a defect check):**
  - **0** PREGAME NCAAB / WNCAAB totals flags on the rail or the board today.
  - Any such flag is a defect, handed to the #816 owner.
- **P7 (I-22, copied from the owner's pre-registration; graded in tonight's live NHL window, 3 games from 6:30 PM CST):**
  - Longest live sweep run <= 1,200 s.
  - `lane_busy` refusals <= 50% of sweep attempts (11-17: 88%).
  - An `NHL_LIVE_GENERATION_COOLDOWN` after any generation timeout.
  - NHL odds age <= ~1,200 s.
  - NHL in-play rows not stuck at 0-5.
  - With a healthy NHL API, the only sign is >= 1 deferred `nhl_live_generation` step.
- **P8 (I-21; its own reading runs at 12:30 AM CST Thu):** NHL in-play player-prop rows stay on the board across
  the NHL window, rather than dropping as on 11-17 ("76 of 76 builds at 300 s"). I report what the cards show;
  the owner grades it.

## Per-reading checklist (day 4)

- **Flags:** false, missed and dark; I-17 contradictions (the P > 0.5 rule); #824 ("ours" below the points
  scored); pregame college totals flags (P6).
- **Overlay:** gaps against web's 360 s, and stale web merges.
- **Board:** build wall and spans (`BOARD_BUILD_TIMING`, `BUILD_SPAN_EXIT`) and the board child.
- **Live odds lane:**
  - sweeps launched and refused (`lane_busy`);
  - the longest run;
  - any NHL odds child older than 600 s;
  - lane holds by sport;
  - NHL generation steps (deferred, cooldown).
- **Load:** query, shortlist, chips and live-rail times.
- **Team cards:** flipped, chip-less, det1-3.
- **Improvements:** each with evidence and an owner.
