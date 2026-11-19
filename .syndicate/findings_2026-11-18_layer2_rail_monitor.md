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

## Reading 1 — Wed 11-18 11:57 AM CST (17:57Z), full page

**Fleet:** `59fbefc71` (ff 10:33:54 AM CST); refresh-worker 152916; live-odds-worker 23141.
- Host: 12 cores, load 1.8 / 2.3 / 2.9; 7.4 GB available.
- The soccer look-ahead fix `640c6d4fd` is not on the fleet yet. Its lane is loading it.

**Slate:** 139 chips today, 3 live:
- NCAAB Jackson St @ Baylor at the half (tipped 11:01 AM, before the pre-registration, so it is reported separately);
- WNCAAB Bucknell @ UAlbany Q4 0:38;
- WNCAAB East Texas A&M @ Texas A&M at the half.

**Flags:** 0 shown, 0 false, 0 missed, 0 dark.
- **P1 (I-17):** 8 of 8 college full-game total rows on `/api/board/live-rail` carry `live_total_basis: "calibrated"`. No flags yet, so there is no contradiction count.
- **P6 (BC-048):** 1 pregame college totals row on the shortlist (Youngstown St @ Cincinnati u153). Model edge −0.0, basis `market_fair`. **0 pregame college totals flags.**

**Live rows:** 12 (NCAAB 10, WNCAAB 2). 5 priced <= 120 s; priced age p50 312 s; 2 of 3 markets with no price of ours.

**Overlay (since 11:00 AM):**
- 0 gaps over 360 s (max WNCAAB 102 s, NCAAB 85 s).
- Ticks 161, gap max 77 s, 0 `deferred_slow`.
- Web merges 50, **0 stale**.

**Board** (`BOARD_BUILD_TIMING`, since 11:00 AM): 10 builds.
- Wall 164-545 s, median ~199 s. The latest was 187 s; the board was built 105 s before the read.
- **Off-CPU only 5.6-17.6%:** the board child is CPU-bound.
- Spans: shortlist 89-102 s, portfolio 8-22 s, overview 3-19 s. 0 deferred builds, no drain.
- **Comparison:** 11-17 at the same hour (17-18Z) ran p50 164 s / max 534 s. Today 9 AM-noon ran p50 127 s.
  **No regression from the split at midday.** The evening is P2's test.

**Live odds lane (I-22, since 11:00 AM):**
- 18 sweeps launched, 1 refused (`lane_busy`).
- Live runs since 9 AM: 9, p50 69 s, max 134 s, 0 over 600 s.
- No odds child older than 600 s at the read.

**Odds runs since 9 AM CST (manifests by slate date):**
- Today's pregame: 14 runs, p50 4 s, max 384 s. The 3 over 300 s are soccer at 308-328 s.
- **Look-ahead (11-19):** 3 runs of 1,391 / 2,444 / 1,942 s, with soccer at **1,189 / 2,225 / 1,818 s**. This is exactly what
  the soccer fix `640c6d4fd` targets (its prediction: p50 412 s, max 951 s).
- Failing steps:
  - soccer `*_history_current` 2-11 per league (Understat "playersData not available", todo #840 lead);
  - `wncaab_odds_snapshot` 10. This one was already failing before today's loads (the odds-lane session counted 172 of 182 since 12:23 AM).

**Load (full page):**
- `/intelligence` 4.6 s / 4.21 MB wire / 21.5 MB raw.
- Query 4.5 s / 3.90 MB / 20.7 MB.
- Shortlist 1.5 s; chips 0.4 s; live-rail 0.015 s.

**Team cards:** 0 flipped, det1 / det2 / det3 0 / 0 / 0, 0 chip-less, 0 live chips without a live card.

**Improvement leads:**
- **L-a (new, watch):** the board child is CPU-bound, and the shortlist span is about half its wall (89-102 s of ~190 s). If tonight's
  builds stay over 300 s with the split ON, the next lever is the shortlist's own CPU, not more isolation. Owner: the split's lane
  hands its 10:15 PM verdict to whoever takes it. **Not opened yet:** a lead until the evening reading.
- **`wncaab_odds_snapshot` fails most pregame runs** ("No odds rows returned"). Already known to the odds-lane session; no owner named. I will
  measure the share against WNCAAB pregame runs at the next reading.

## Reading 2 — Wed 11-18 12:33 PM CST (18:33Z)

**Fleet:** **`640c6d4fd` since 11:58:30 AM CST.** The soccer look-ahead fix was ff'd by its lane, with no restart.
- Host load 6.2 / 5.0 / 4.2; 6.6 GB available.

**Slate: 2 live.** NCAAB Jackson St @ Baylor H2 9:56 (pre-registration-excluded) and WNCAAB East Texas A&M @ Texas A&M Q4.

**Flags: 1 card (Baylor), 4 flagged rows, 0 false, 0 missed, 0 dark.**
- The card's flag is o151.5 at 27.5 pp (model 0.79 vs fair 0.52), with ours 159.0. Ours is on the flagged side.
- **P1 (I-17):** 0 contradictions. 9 of 9 NCAAB full total rows are `calibrated` (`i17check.py` 18:35:25Z: 0 flags by its |edge| >= 3,
  <= 120 s rule at that instant).
- **P6:** 0 pregame college totals flags.

**Live rows:** 10. 9 priced <= 120 s; priced age p50 38 s; 1 of 3 markets with no price of ours.

**Overlay (since 11:58 AM):** 0 gaps over 360 s (max WNCAAB 96 s); ticks 88, gap max 100 s; web merges 64, 0 stale.

**Board:** 6 builds; wall **178-352 s, median 222 s**; cpu 150-320 s; off-CPU 9-16%.
- 2 of 6 builds went over 300 s (12:24 PM 352 s, 12:30 PM 311 s); the shortlist span hit 192 s at 12:22 PM.
- **The midday trend is up** (9 AM-noon p50 127 s; 11 AM-noon 199 s). P2's evening test starts from a heavier base than the
  11-17 calm.

**Live odds lane (since 11:58 AM):** 14 launched, **3 refused** (`lane_busy`).
- The holder was a today-pregame sweep (nba, nhl, ncaab, wncaab; pid 207671) at 410 s at 12:37 PM, in its NHL odds step
  (`refresh_nhl_oddsapi.py` 7 s old).
- Live runs: 1, at 125 s. No odds child older than 600 s.

**Soccer fix, first look-ahead on it (12:07 PM, 11-19 slate):** the run took **386 s, soccer 276 s**, against this morning's
1,391-2,444 s / 1,189-2,225 s.
- Its owner reads the sims at 45 s against a 62 s bound: MET.
- Today's own pregame soccer run (12:16 PM) took 479 s (soccer 449 s). That path is not touched by the fix.

**Load:** query **16.1 s** / 3.94 MB / 20.8 MB (reading 1: 4.5 s); a re-fetch at 12:36 PM took 8.6-10.3 s x3. Shortlist 7.2 s;
chips 0.8 s; live-rail 0.09 s.
- These are under host load 6.2. Watch whether the query stays over 8 s.

**Team cards:** 0 flipped, det 0 / 0 / 0, 0 chip-less.

**A monitor-instrument correction: no defect.** The probe's `query_snapshot_age_s` read **2,348 s** (served
`snapshot_generated_at` 17:54:46Z, unchanged over 3 re-fetches).
- That stamp is the combined window's OLDEST date (`pipeline/intelligence_state.py:10850-10889`). Here it was **11-19's
  look-ahead** shortlist, rebuilt hourly by design.
- Today's own block in `state_meta.dates` read **2026-11-18 written 18:27:50Z (343 s)**, state 18:30:57Z. The state history
  appends every ~5 min (last at 12:31:29 PM).
- Fixed in this lane's probe: it now also prints `query_today_age_s` from `state_meta.dates[<rail date>]`.

## Reading 3 — Wed 11-18 1:14 PM CST (19:14Z)

**Fleet:** **`db6a395ed` since 1:14:21 PM CST.**
- That load was web's hard-recycle fix (lane `web-silent-worker-kills`, deploys.md 19:14:22Z). It is an ff of 84 commits.
- Runtime ride-alongs: `nba/live_resim.py` total anchor (`88193c0a7`, **default OFF**, `SYNDICATE_NBA_LIVE_TOTAL_ANCHOR`) and
  `live_endgame_freshness.py` / `live_gameline_join.py` #836 (**absent = shadow**, `SYNDICATE_LIVE_ENDGAME_FRESHNESS`).
  Neither changes a price while its switch is unset.
- Host load 7.2 (9.9 at 1:10 PM).

**Slate:** 5 live. Flags 1 shown, 0 false, 0 missed, 0 dark. P1: 0 college totals flags, so 0 contradictions. P6: 0. #824: 0.

**Live rows:** 18. 6 priced <= 120 s.

**Overlay (since 12:33 PM):** **1 gap over 360 s: WNCAAB 691 s**, with **7 stale web merges (all WNCAAB)** of 55. Tick gap max 118 s.

**Board: 3 builds, 497 / 547 / 646 s, all over 300 s**; the shortlist span reached 390 s. Today's board was 437 s old at the read.
- **Board CPU per build, by hour (UTC):** 06-13Z p50 90-105 cpu-s; 14Z 117; 15Z 129; 16Z 219; 17Z 170; 18Z 239; 19Z 602.
  The work per build grew about 5x since morning, while off-CPU stayed 5-17%. So it is the build's own work growing,
  not contention.
- The 1:14 PM ff cannot explain it: the board child is a long-running `--serve` process (up 3.5 h) that does not
  reload code.
- Signs of what grows: VENUE_REPRICE_KEYS unmatched nba 20,262 at 12:21 PM; ncaaf GRID_REPRICE sides 3,529.
- **P2 is at risk before the evening starts.** The 1 PM median (547 s) is already 2x the 253 s evening target.
  Becomes **A-1**; a session card is proposed (unowned; the board split's session is archived).

**Live odds lane:** 8 launched, 3 refused (27%). One live run took **514 s**; one pregame run 574 s. NHL odds child 206 s old (under 600 s).

**Load:** query 15.0 s (r2 16.1 s, r1 4.5 s); shortlist 1.2 s.

**Team cards:** 0 defects.

**Dashboard:** the user asked for a live dashboard like the portfolio monitor's: "Rail Watch",
https://claude.ai/artifact/HoJ2n52ewHZnVDbN2LpxaJ. Each reading re-uploads `readings.json`, `findings.json` and
`loads.json` (rows built by `C:\tmp\railmon\dash\dash_update.py` from the probe plus `dash\d4metrics.py`).

## Reading 4 — Wed 11-18 1:49 PM CST (19:49Z), full page

**Fleet:** `db6a395ed`, no new ff. Host load 1.6-2.7 (it was 7-10 at 12:33-1:14 PM).

**Slate:** 5 live of 139.
- Flags: 1 shown, 0 false, 0 missed, 0 dark.
- P1: 1 college totals flag, 0 contradictions. P6: 0. #824: 0.

**Live rows:** 16. 5 priced <= 120 s.

**Overlay:** 0 gaps over 360 s (max WNCAAB 80 s). Web merges 24, 0 stale. **A-2 cleared.**

**Board: 7 builds, wall 134-308 s, median 179 s.** Per-build CPU fell **602 -> 274 -> 165 -> 152 -> 131 -> 151 -> 120 -> 106 s**
(11:11 AM to 1:48 PM). There was no board-child restart (pid 152953 up 4.2 h) and no code change.

**CORRECTION to reading 3's A-1:** "the build's own work growing, not contention" is **WITHDRAWN.**
- Per-build CPU tracked host load (8-10 then, ~2 now). On this host (SMT; the I-20 session measured 56-64% of nominal
  clock), CPU time per unit of work inflates under contention even while the thread stays on-CPU. So a low off-CPU % does
  not rule contention out.
- The session card "Find why the board build's CPU grows 5x through the day" (task_88c5176a) was **withdrawn** before
  anyone started it.
- **Lead L-c:** at 1:10 PM, nice-0 whole-log `awk`/`grep` scans of `refresh-worker.log` (not this lane's; mine run at
  nice 19) used 55-79% of a core each. Other sessions' replays were active 12:30-1:15 PM. Not attributed per process yet.
- P2's evening reading has to state the host load beside the board times.

**Live odds lane:** 7 launched, 1 refused (12.5%). Live runs 4: p50 118 s, max 137 s. Pregame run max 454 s. No NHL odds child running.

**Load (full page):** `/intelligence` 9.0 s; query 5.0 s; shortlist 0.9 s. Today's board was 171 s old.

**Team cards:** 0 defects.

**From the soccer lane's side sessions** (local_68526c0a, reported 1:4x PM). These went into the dashboard's improvements as I-24..I-26:
- **I-24:** Understat has been down since 11-03. The big-5 soccer leagues are priced on history frozen at 10-31.
- **I-25:** NBA history is duplicated by a game-id format mismatch: 1,563 rows for 196 games, Elo shifted 119 points on average.
  The fix `4178ba866` is off by default.
- **I-26:** the day-2 look-ahead was refused 115 of 127 times.

## Reading 5 — Wed 11-18 2:27 PM CST (20:27Z)

**Fleet:** `db6a395ed`, no new ff. Host load 1.2.

**Slate: 4 live.** NCAAB Rutgers @ Notre Dame H2; WNCAAB UC Riverside @ Oregon St, Cal Baptist @ San José St, South Dakota @ Chicago St.

**Flags:** 0 shown, 0 false, 0 missed, 0 dark. P1, P6 and #824: 0.

**Live rows: 10, but only 1 priced <= 120 s.**
- NCAAB: 9 rows, 0 priced <= 120 s. Priced age p50 230 s, max 419 s. Seen age at pricing p50 149 s, so the quotes were already old when priced.
- WNCAAB: 1 row, 85 s.

**This is not a pipeline stall:**
- `NCAAB_LIVE_AUTORUN_LAUNCHED` 106 times and `WNCAAB_` 106 times since 12:39 PM (every ~60 s, `live_games=1` / `3`).
- My first count said "last launch 12:39 PM". That came from a misaligned awk pairing; it is withdrawn.
- The one NCAAB game's book quotes are simply not moving. **Watch:** if more NCAAB games show the same tonight, count books per game (as I-10 did for WNCAAB).

**Main live odds loop:** 1 sweep launched since 1:49 PM.
- 16 `PREGAME_RELAUNCH_COOLDOWN_SKIPPED` (cooldown 1,800 s): the pregame sweep's 30-min relaunch cooldown, as designed.
- Live-phase manifests today are all soccer (16 since 10:53 AM). College live odds run on their own autorun lane.
- Pregame runs 452 / 454 s; look-ahead 292 s (soccer 140 s).

**Board: 9 builds, 140-216 s, median 163 s, 0 over 300 s**, at host load ~1.2. Shortlist span max 111 s.

**Overlay:** 0 gaps over 360 s (max NCAAB 79 s). Web merges 29, 0 stale.

**Load:** query 2.4 s; shortlist 1.3 s. Today's board was 152 s old.

**Team cards:** 0 defects.

**Dashboard:** row 5 uploaded. The page has still not been opened in a browser, so there is no render check (`data/users/me` is empty).

### CORRECTION to reading 5 (~2:55 PM CST): the "stale college quotes" are a grid bug, not the books

The #816 lane (local_1f10ce63, on the user's ask to count books) found it: `.syndicate/findings_2026-11-18_college_quote_age_text_max.md`, `5edae7ef6`, todo #844.
- **The bug:** `syndicate/features/shared/book_grid.py` (origin/main, ~line 1159) sets `newest = max(stamps)` over `observed_at` STRINGS. College sportsbooks stamp `2026-11-18 20:58:05+00:00`; Kalshi / Polymarket stamp `2026-11-18T20:55:57Z`. `T` sorts above a space, so an older venue stamp becomes the row's age, and the live gate (120 s) reads that age.
  - I re-read the line on main and confirm it.
- **The books are fine:** a median of 9 books per live NCAAB game.
  - Rutgers @ Notre Dame had 5-6 fresh books; its grid row read 143.6 s (Kalshi) while FanDuel was 14.6 s.
  - NCAAB moneyline: fresh 81.2% of live minutes by time, but 25.5% by the row age.
  - NBA and NHL are unaffected: their sportsbook stamps use `T` too.
- **The monitor is blind here.** My "priced <= 120 s" counts and "missed" flags read the same row age, so for college rows that carry a venue quote they share the bug. "0 missed" on college cannot see lines the gate wrongly withheld.
  - Recorded as **I-27** on the dashboard.
  - P1's college counts are a lower bound until the bug is fixed.
- **The fix is not built.** `book_grid.py` is held by OPEN lane `ncaaf-grid-build-speed`. It is a betting change, so it loads in the 11-24 window unless the user grants an exception.

## Reading 6 — Wed 11-18 3:05 PM CST (21:05Z)

**Fleet:** **`a3104a5b6` since 3:02:51 PM CST.** The NBA games-history fetch is bounded and de-duplicated, **default ON**: todo #843,
lane `nba-midnight-bootstrap-hold`, user "Load it now", **BC-052, outside a window by the user's override** (deploys.md
21:02:51Z). This is I-25's fix: duplicate history inflated NBA Elo by 119 points on average.
- Ride-alongs: `live_refresh_loop.py` day-2 look-ahead wait (`2aff90c36`, `SYNDICATE_LOOK_AHEAD_LANE_WAIT` **default OFF**);
  `refresh_nba_oddsapi_props.py` timeout.
- Also recorded: the Understat outage naming half (`5a7cc60d2`, betting change no) reached the fleet with the 1:14 PM ff
  (deploys.md 20:22Z reading).
- Host load 3.2.

**Slate: 1 live** (Rutgers @ Notre Dame, OT 4:11).
- Flags: 1 shown, 0 false, 0 missed, 0 dark. P1, P6 and #824: 0.
- Live rows: 9, 2 priced <= 120 s (row age; college row ages are lower bounds per #844).

**Board: 8 builds, 145-253 s, median 166 s, 0 over 300 s.** Shortlist span max 121 s.

**Overlay:** 0 gaps over 360 s (max WNCAAB 85 s).
- Web merges 53, **12 stale, all WNCAAB**, with no WNCAAB game live.
- The WNCAAB overlay built 0 cards in 14 of 29 builds with rows: games ending, and no WNCAAB cards to merge. **Benign.**

**Live odds lane:** 12 launched, 1 refused (7.7%). Live runs 61-63 s; pregame 243 s.

**Load:** query 10.8 s (2.4 s at r5); shortlist 2.4 s. Today's board was 430 s old at the read (one build in flight).

**Team cards:** 0 defects.

**Dashboard:** row 6, the 1:14 PM and 3:02 PM loads, and I-25 marked loaded.

## Reading 7 — Wed 11-18 3:44 PM CST (21:44Z)

**Fleet:** `a3104a5b6`, no new ff. Host load 3.1.

**Slate: 2 live,** both WNCAAB: Utah St @ BYU Q2 and New Hampshire @ Yale Q1.
- Flags: 1 shown, 0 false, 0 missed, 0 dark. P1: 1 college totals flag, 0 contradictions. P6: 0. #824: 0.
- Live rows: 3, 2 priced <= 120 s.

**Board: 7 builds, median 266 s, max 353 s, 1 over 300 s** (shortlist span max 196 s), at host load ~3.
- This is creeping up before the evening (r5 163 s, r6 166 s).
- P2 measures from 5:30 PM with host load beside each build.

**Overlay:** 0 gaps over 360 s (max WNCAAB 73 s). Web merges 30, 14 stale (WNCAAB 13, NCAAB 1). WNCAAB games tipped mid-window.

**Live odds lane:** 14 launched, 2 refused (12.5%). Live runs 103-158 s; pregame 232 s.
- Look-ahead 445 s (soccer 244 s, against 1,189-2,225 s this morning).
- **An NHL odds child was 359 s old at the read**, under the 600 s watch line. It is a pregame run, before the 6:30 PM games.

**Load:** query 12.2 s; shortlist 1.9 s. Today's board was 331 s old.

**Team cards:** 0 defects.

**Dashboard:** row 7. I-26 is marked as the user's choice: fix day 1, retire day 2, queued for the 11-24 window. I-24 has an
alternative-source session working.

## Reading 8 — Wed 11-18 4:22 PM CST (22:22Z), full page

**Fleet:** `a3104a5b6`, no new ff.
- live-odds-worker is now pid 250752: `exited code=0 after 23442s -- restarting in 5s` (supervisor) around 2:36 PM CST. This is its own clean
  recycle, not a deploy. Its in-process code is now `a3104a5b6`, including the day-2 look-ahead wait (default OFF).
- Host load 4.6-5.7.

**Slate: 7 live** (NCAAB Houston @ Florida H1; WNCAAB 6).
- Flags: 3 shown, 0 false, 0 missed, 0 dark. P1: 2 college totals flags, 0 contradictions. P6: 0. #824: 0.
- Live rows: 28, 9 priced <= 120 s (row age; a lower bound for college per #844).

**Board: only 3 builds in 38 min.** 290 / 409 / 373 s, with CPU 260 / 385 / 346 s and off-CPU 7%. **Today's board was 730 s old at the read.**
- At 4:23 PM the board child (74% CPU) shared the host with nice-0 batch jobs:
  - `build_soccer_artifacts.py --league eredivisie --date 2026-11-22` at 99%;
  - `refresh_odds_sources.py --sports wncaab` at 107%;
  - `refresh_ncaab_odds_history.py` at 48%;
  - `build_college_pregame_sims.py` at 98% (nice 15).
- **Lead L-d:** per-build CPU tracks host load across today's readings: about 106-150 s at load 1-2, 240-385 s at about 5, and 500-600 s at 8-10.
  Running non-urgent background builds at a lower priority (e.g. soccer artifacts for a date 4 days out) would protect
  the 300 s board cadence. The evening's P2 readings add points before a session is proposed.

**Overlay:** 0 gaps over 360 s (max NCAAB 98 s). Web merges 57, 6 stale (NCAAB).

**Live odds lane:** 12 launched, 3 refused (20%). Live runs 3, max 248 s; pregame 472 s.
- Look-ahead **798 s** (soccer 396 s). Still under this morning's 1,391-2,444 s, but up from 292-445 s.

**Load (full page):** **`/intelligence` 22.1 s** (r4 9.0 s, r1 4.6 s); query 6.9 s; shortlist 2.4 s.

**Team cards:** 0 defects.

## Reading 9 — Wed 11-18 4:55 PM CST (22:55Z)

**Fleet:** `a3104a5b6`, no new ff. Host load 2.5-3.1.

**Slate: 7 live.**
- Flags: 0 shown, 0 false, 0 missed, 0 dark. P1, P6 and #824: 0.
- Live rows: 11, 4 priced <= 120 s (college row ages are lower bounds per #844).

**Board: 5 builds, wall 176 / 238 / 247 / 253 / 276 s, median 247 s, 0 over 300 s.** CPU per build 150-246 s, at load ~3.
- **L-d point:** at 4:55 PM `build_soccer_artifacts.py --league championship --date 2026-11-24` (a date 6 days out) ran at nice 0, 96% CPU, beside
  the board child (74%).
- Also on the CPU: `redis-aof-rewrite` at 98% (3 s old).

**Overlay:** 0 gaps over 360 s (max NCAAB 70 s); ticks 100, gap max 52 s; web merges 42, 0 stale.

**Live odds lane:** 16 launched, 4 refused (20%). Live run 56 s. No odds child older than 16 s.

**Load:** query 13.6 s; shortlist 1.5 s. Today's board was 284 s old.

**Team cards:** 0 defects.

## Reading 10 — Wed 11-18 5:26 PM CST (23:26Z): the evening window opens (P2 from 5:30 PM)

**Fleet:** `a3104a5b6`, no new ff. Host load 2.5.

**Slate: 17 live.**
- Flags: 4 shown, 0 false, 0 missed, 0 dark.
- P1: 3 college totals flags, 0 contradictions. P6: 0. #824: 0.
- Live rows: 25, 11 priced <= 120 s (college row ages are lower bounds per #844).

**Board: 6 builds, 160 / 164 / 170 / 180 / 195 / 270 s, median 174 s, 0 over 300 s.** CPU per build 132-243 s.
- No nice-0 batch job was in the top processes at 5:26 PM (L-d: none this time).

**Overlay:** 0 gaps over 360 s (max WNCAAB 66 s); ticks 92, gap max 43 s; web merges 27, 0 stale.

**Live odds lane:** 16 launched, 3 refused (15.8%). Live runs 106-137 s; pregame 296 s.
- Look-ahead 410 s (soccer 187 s).

**Load:** query 3.8 s; shortlist 2.1 s. Today's board was 218 s old.

**Team cards:** 0 defects.

**Dashboard (since reading 9):**
- the user asked (~5:05 PM): "are we tracking recomendations and success of recomendations on the rail? can we
  incorporate layer 2 board performance and suggested opportunities performance? We should have a lot of history to
  look at for this as well".
- Added **rail flag results by day** (11-15..11-17, grade outputs) and **board / shortlist-published / staked results**
  (44 scorecard days, 10-06..11-18, 28-day rolling, by sport; `C:\tmp\railmon\dash\perf_series.py` + `perf_build.py`).
- **Gap:** the shortlist's `suggested` flag is not graded as its own set. A session was offered to the user.

## Reading 11 — Wed 11-18 5:50 PM CST (23:50Z)

**Fleet:** `a3104a5b6`, no new ff. Host load 3.2-3.6.

**Slate: 24 live.**
- Flags: 7 shown, 0 false, 0 missed, 1 dark row.
- P1: 3 college totals flags, 0 contradictions. P6: 0. #824: 0.
- Live rows: 139, 47 priced <= 120 s (college row ages are lower bounds per #844).

**Board (P2): 4 builds, 161 / 171 / 183 / 189 s, median 177 s, 0 over 300 s.** CPU per build 132-165 s.
- No nice-0 batch job in the top processes (L-d: none). The live re-sim workers run at nice 5.

**Overlay:** 0 gaps over 360 s (max NCAAB 66 s); ticks 71, gap max 57 s; web merges 19, 0 stale.

**Live odds lane:** 11 launched, 3 refused (21.4%). Live runs 3, max 117 s; pregame 284 s.

**Load:** query 6.3 s; shortlist 1.0 s. Today's board was 403 s old (a build in flight).

**Team cards:** 0 defects.

**Session started on the user's "Yes, start it":** local_fbe07d8c "Grade the board's suggested picks as their own set".
When it reports the file, the dashboard adds a "Suggested by the board" set.

## Reading 12 — Wed 11-18 6:14 PM CST (00:14Z 11-19), full page

**Fleet:** `a3104a5b6`, no new ff. **Host load 8.0** (5.7 / 4.4 over 5 / 15 min).

**Slate: 61 live.**
- Flags: 45 shown, 0 false, 0 missed, 0 dark.
- P1: 13 college totals flags, 0 contradictions. P6: 0. #824: 0.
- Live rows: 1,513, 214 priced <= 120 s (college row ages are lower bounds per #844).

**Board (P2): 3 builds, 189 / 248 / 289 s, median 248 s, 0 over 300 s.** CPU per build 162-260 s. One more build was in flight at the read; today's board was 641 s old.
- **L-d, third point:** at 6:14 PM `build_soccer_artifacts.py --league epl --date 2026-11-23` ran at nice 0, 80% CPU, beside the board child (73%). Three odds refreshes were running at nice 0 too, which is expected for live odds.
- **Monitor fix:** refresh-worker.log rotated at 6:11:21 PM CST. `d4metrics.py` read only the new file, so it reported 0 builds and 8 ticks.
  - It now prepends the rotated `.1` tail when the window is not covered.
  - This reading was re-run with the fix: 3 builds, 65 ticks, coverage true.

**Overlay:** 0 gaps over 360 s (max WNCAAB 161 s); tick gap max 68 s; web merges 24, 0 stale.

**Live odds lane:** 11 launched, 2 refused (15.4%). Live run 70 s. No NHL odds child running; NHL starts 6:30 PM.

**Load (full page):** **`/intelligence` 26.4 s** (r8 22.1 s, r4 9.0 s); query 10.7 s; shortlist 0.7 s.

**Team cards:** 0 defects.

**Since reading 11 (dashboard):**
- **Cheat sheet section added.** The user: "add the cheat sheet picks performance to the dashboard too". It draws on 35 daily reviews, 10-15..11-18.
- **Optimization session started.** The user: "we need to then take all this data to optimize the overall Syndicate product" (accepted as a new session).
  - Session: "Optimize Syndicate from its performance data" (local_09a95c0b).

## Reading 13 — Wed 11-18 6:40 PM CST (00:40Z 11-19): BOARD OUTAGE (A-3) and P1's first contradictions

**Fleet:** `a3104a5b6`, no new ff. **Host load 8.8** (7.8 / 6.7).

**A-3: the board child's scheduled recycle crashed on exit, and the board went 26.3 min without a build.**
- Timeline from refresh-worker.log `[board_process]`, the WSL crash capture and `BOARD_BUILD_TIMING`:

| time (CST) | event |
|---|---|
| 6:16:21 PM | last build of child 152953 finishes (342 s) |
| 6:29:18 PM | `BOARD_PROCESS_RECYCLE pid=152953`: `maybe_recycle` at 31,853 s (8.8 h) uptime; it returns 75 |
| ~6:29 PM | `Fatal Python error: _enter_buffered_busy: could not acquire lock for <_io.BufferedReader name='<stdin>'> at interpreter shutdown, possibly due to daemon threads`. The WSL CaptureCrash shows signal 6 for pid 152953. |
| 6:29:58 PM | `BOARD_PROCESS_EXITED pid=152953 rc=-6 reason=exit uptime_s=31853 respawn_in_s=5`. The intended clean rc 75 ("recycle") became an abort. |
| 6:30:03-6:30:05 PM | child 363665 STARTED / BOOT / READY |
| 6:33:56 PM | its first build starts (`pull_hot_artifacts`) |
| 6:42:41 PM | its first build finishes: **wall 526 s**, cpu 465 s |

- **Cost:** no fresh board from 6:16:21 to 6:42:41 PM, which is 26.3 min against the 300 s cadence, in the evening peak (75 live games, host load 8.8). The build in flight at the recycle was lost. At the 6:40 PM read, today's board was 1,503 s old.
- **The cause sits in shipped code.** `pipeline/board_build_process.py`:
  - the lifeline thread `_read_stdin` (`:433-446`, daemon) blocks in `sys.stdin.buffer.read(1)`;
  - so the interpreter's shutdown cannot take the buffered-reader lock and aborts;
  - the recycle path is `:519-526`.
- **Two fixes, neither a betting change:**
  1. exit without that abort, e.g. read fd 0 with `os.read`, or `os._exit(75)` after cleanup;
  2. recycle only right after a completed build, or defer it while today's board has live games.
- The board-split lane (`layer2-board-process-split`, I-20) is OPEN, but its session is archived. Its 10:15 PM verdict task will see `rc=-6`. A session is proposed for the fix.

**P1 (I-17): 2 contradictions, the first today.** Both are NCAAB full totals with model P > 0.5 whose "ours" sits across the line:
- Chattanooga @ Winthrop: u154.5, model 0.537 / fair 0.489, ours 156.0;
- Coppin St @ La Salle: u145.5, 0.549 / 0.500, ours 146.0.

Both cards' total rows carry `live_total_basis: None`. `i17check.py` at 6:42:57 PM: NCAAB 277 of 286 rows calibrated (9 not), 9 flags; WNCAAB 0 of 111 calibrated, 15 flags. Sent to the I-17 owner (local_1f10ce63) with the question: expected (no calibration input) or a gap? Possibly tied to the stale board (overlay merges on a 25-min-old board).

**Slate: 75 live.**
- Flags: 56 shown (34 cards), 0 false, 0 missed, 0 dark.
- P6: 0. #824: 0.
- Live rows 1,621, 266 priced <= 120 s.
- **NBA: 885 rows, only 8 priced <= 120 s** (I-3 / I-4: NBA slow cadence and alt lines).
- NCAAB 589 (222). WNCAAB 108 (24). NHL 2 (0).

**P7 (NHL window opened 6:30 PM):**
- longest live run 100 s;
- refused 1 of 6 sweeps (16.7%);
- no NHL odds child running;
- NHL overlay: 1 build, 31 in-play rows, 47 s since the last build.

**Overlay:** 0 gaps over 360 s (max NCAAF 148 s); web merges 44, 0 stale.

**Load:** query **21.9 s / 5.97 MB / 31.2 MB** (bigger evening payload); live-rail 1.3 s; chips 3.0 s.

**Team cards:** 0 defects.

**Monitor note:** the probe first ran from `C:\tmp\railmon\dash` (wrong cwd, rc 2). It was re-run from the worktree at 6:40:35 PM.

### CORRECTION to reading 13's P1 attribution (~6:55 PM CST, from the I-17 owner local_1f10ce63)

The 2 contradictions are **real**, but my "rows with `live_total_basis: None`" attribution was wrong.
- `liverail_0.json` (same folder) shows every FULL-game totals row of both games is `calibrated`. The basis-None rows I printed were the h1/h2 half totals (calibration is full-game only, by design), and the probe's `rail.json` card rows do not carry the field.
- **The cause is the card:** `liveRailSummary` takes `marketRows.find(basis === "calibrated")`, which is the FIRST calibrated row of the market, not the flagged row.
  - Chattanooga @ Winthrop: the flagged u154.5 row's own calibrated total is 153.4 (consistent). The card showed 156.0 from the 157.5 row, which was 152-249 s old.
  - Coppin St @ La Salle: the flagged row's own total is 143.9. The card showed 146.0 from the 147.5 row.
- **The fix belongs to the I-17 owner:** OURS will use the flagged/main row's own calibrated total, with the freshest calibrated row as the fallback.
- The owner's row-level watcher saw 0 because it checks each row against its own line. Its deploys.md 00:50Z "MET" is being corrected to "measured rows, not cards".
- **WNCAAB live: 0 of 111 calibrated is by design.** It has no fitted calibration (thin sample) and serves the sim total. BC-048 is the PREGAME market fallback.
- Lesson: the monitor's P1 counter (card edge vs card "ours") and the owner's watcher (row vs own line) measure different things. The card one is what the user sees.

## Reading 14 — Wed 11-18 7:06 PM CST (01:06Z 11-19)

**Fleet:** `a3104a5b6`, no new ff. **Host load 7.9** (7.9 / 7.2). Board child 363665, up since 6:30 PM; no new `[board_process]` events.

**Slate: 80 live.**
- Flags: 27 shown, 0 false, 0 missed, **7 dark**.
- **P1: 2 card contradictions again** (the I-17 owner's card bug: the card shows the first calibrated row's total, not the flagged row's; fix in progress). `i17check.py` 7:11 PM: NCAAB 274 of 290 rows calibrated, 16 flags; WNCAAB 0 of 84 (by design).
- P6: 0. #824: 0.
- Live rows: 1,530, 122 priced <= 120 s.
  - **NBA: 1,032 rows, 13 priced <= 120 s** (I-3 / I-4).
  - NCAAB 388 (77). WNCAAB 87 (23). NCAAF 18 (5). NHL 5 (4).

**Board (P2): 3 builds since 6:40 PM.**
- 526 s (6:42 PM: the respawned child's first build), then 343 s (6:53 PM), then 284 s (7:02 PM).
- Median 343 s; 2 of 3 over 300 s.
- Host load ~8. The top processes were the board child (85%), the live-odds worker (56%) and short-lived children.
- **The evening median now exceeds P2's 253 s target.**

**P7 (NHL window, 6:40-7:06 PM):**
- longest live run 162 s;
- 2 of 7 sweeps refused (28.6%);
- no NHL odds child running at the read;
- 0 `NHL_LIVE_GENERATION` markers.

**P8 (NHL props, I-21):** 19 NHL overlay builds, **176 in-play rows**, 0 gaps over 360 s. Not stuck at 0-5.

**Overlay:** 0 gaps over 360 s (max NBA 330 s); 1 `deferred_slow` tick; tick gap max 125 s. Web merges 51, 0 stale.

**Load:** **query 31.6 s** (the evening payload). Today's board was 473 s old.

**Team cards:** 0 defects.

**Sessions:**
- The user said "start 847, 848, and 849". The optimization session started its own three at the same time (local_7746cb20, local_4010ce82, local_2e89ebdd). Mine are duplicates and are being stood down:
  - local_3ab5373b was stopped mid-turn and told to stand down;
  - local_e0b3696b and local_63ca956d were still starting, so the stop is retried at each reading.
- The user said "add 844 to the 11-24 window" (relayed to the optimization session).

## Reading 15 — Wed 11-18 7:34 PM CST (01:34Z 11-19)

**Fleet:** `a3104a5b6`, no new ff. Host load 6.1 (5.7 / 6.3). Board child 363665; no new `[board_process]` events.

**Slate: 80 live.**
- Flags: 104 shown, 0 false, 0 missed, 0 dark.
- P1: 24 college totals flags, **0 card contradictions** this read.
- #824: **1** college totals flag with ours below the points already scored (to check next read).
- P6: 0.
- Live rows: 1,937, 844 priced <= 120 s.
  - **NBA 1,092 rows, 583 fresh** (13 of 1,032 at 7:06 PM).
  - NCAAB 734 (218). WNCAAB 77 (31). NCAAF 30 (10). NHL 4 (2).

**Board (P2): builds at 7:21 PM (369 s) and 7:31 PM (315 s), median 342 s, both over 300 s.**

**A-4: the today board publishes every 8-18 min, not every 5.**
- Each cycle runs a separate `LAYER2_TODAY_CADENCE` step before `BOARD_BUILD_TIMING`:
  - `LAYER2_TODAY_CADENCE ... ran=yes age_before_s=330 limit_s=300 elapsed_s=536.8` at 7:14:41 PM;
  - `elapsed_s=164.2` at 7:26:29 PM.
- Publications: 6:42:41, 6:53:35, 7:02:30, **7:21:01 (18.5 min after the previous one)**, 7:31:49 PM.
- **Evening 5:26-7:34 PM:** 13 builds; publication gap median **490 s**, max **1,580 s** (the recycle crash, A-3).
- `BOARD_BUILD_TIMING` wall alone understates the cycle. The monitor's metrics now also record `board_pub_gap_*` and `today_cadence_step_max_s`.
- Recorded for the board-split verdict (10:15 PM) and the build-priority session (#849).

**P7 (NHL window):**
- 7 sweeps launched, 3 refused (30%);
- live run 88 s; pregame 325 s;
- an NHL odds child was 186 s old at the read (`refresh_nhl_oddsapi.py --days-ahead 1`, under 600 s);
- 0 `NHL_LIVE_GENERATION` markers.

**P8:** 31 NHL overlay builds, **177 in-play rows**, 0 gaps over 360 s.

**Overlay:** 0 gaps over 360 s (max NBA 314 s); 1 `deferred_slow` tick; tick gap max 161 s. Web merges 19, 0 stale.

**Load:** query 14.5 s. Today's board was 397 s old.

**Team cards:** 0 defects.

**Sessions:** all three duplicate #847-#849 sessions confirmed "stood down", having created nothing. The optimization program's three sessions own the work.

## Reading 16 — Wed 11-18 8:01 PM CST (02:01Z 11-19), full page: the second recycle, and its cause is memory

**Fleet:** `a3104a5b6`, no new ff. **Host load 10.2** (7.0 / 6.1).
- On the CPU: the new board child 477538 (86%); `build_soccer_schedule.py --league la_liga` at nice 0 (71%); `build_cheat_sheets.py` at nice 19; #848's read-only scorecard replay (`/mnt/c/tmp/g848/scorecard_ro.py`) at nice 19.

**A-3 re-diagnosed: the board child recycles because of memory-guard refusals, not on a schedule.**
- `[board_process] BOARD_PROCESS_RECYCLE pid=363665` at 7:52:39 PM came after only 4,991 s, and it again exited `rc=-6 reason=exit` (WSL CaptureCrash signal 6, pid 363665). The child 477538 is READY since 7:53:21 PM.
- The trigger, both times: `[worker_recycle] RECYCLE_EXIT reason=heavy_build_refused {'consecutive_refusals': 3, 'last_refusal_stage': 'pre_source_state_fingerprint', 'threshold': 3, ...}` at 6:29:18 PM (uptime 31,813 s) and 7:52:39 PM (4,955 s).
- The refusals: `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900` at 7:33:21, 7:46:37, 7:50:23 and 7:51:47 PM, with headroom 1,736 / 1,712 / 1,638 / 1,867 MB against the 1,900 MB floor. The container was at 5.30-5.53 GB of 7,168 MB.
- **22 refusals on 11-18:** 17Z 1, 21Z 2, 22Z 2, 23Z 7, 00Z 5, 01Z 5. **The 11-17 evening (23Z-05Z, before the split) had 0**, with the container at 3.7-5.0 GB (same `refresh-worker.log.1`, which starts 11-17 17:46Z).
- **So the board split's first evening runs refresh-worker into its own memory guard.** The child holds ~3.8 GB RSS beside a ~1.5 GB parent.
- Each refusal skips a build. Every third one recycles the child, which loses the in-flight build and needs a ~526 s cold first build.
- Board publications: 7:31:49 and **7:45:02 PM (373 s)**, then none through the read at 8:01 PM. Today's board was 1,031 s old.
- `today_cadence_step_max_s` 245.
- **Session card replaced:** "Fix the board child's recycle crash and timing" (task_2c78e053, uptime premise wrong) is withdrawn. The new card is **"Fix board child memory-guard recycles"** (task_d36c12ca): memory measurement, a clean rc-75 exit, a guard matched to the stage cost, and recycling only between builds.
- These numbers go to the board-split verdict (10:15 PM) through this file.

**Slate: 66 live.**
- Flags: 97 shown, 0 false, 0 missed, 0 dark.
- P1: 18 college totals flags, **1 card contradiction** (the card bug; fix pending).
- #824: **2** ours-below-points (likely the same card bug picking another row's total; to check).
- P6: 0.
- Live rows: 1,680, 744 priced <= 120 s.

**P7:** 9 sweeps launched, 4 refused (30.8%); live runs 4, max 168 s; an NHL odds child was 96 s old; 0 `NHL_LIVE_GENERATION` markers.

**Overlay:** 0 gaps over 360 s (max NBA 230 s); 1 `deferred_slow` tick; tick gap max 84 s. Web merges 24, 0 stale.

**Load (full page):** `/intelligence` **25.2 s**; query 8.9 s.

**Team cards:** 0 defects.

**Also since r15:**
- #847 (local_7746cb20) built per-cell calibration default-off (`75a787964`). The rail use FAILED its held-out test: +0.0010 nats/flag [−0.0030, +0.0051], with only 182 of 1,120 flags reachable. Not recommended to load yet. The scorecard test passed.
- All three duplicate sessions stood down.

## Reading 17 — Wed 11-18 8:28 PM CST (02:28Z 11-19)

**Fleet:** `a3104a5b6`, no new ff. Host load 4.6 (5.2 / 5.8).
- Board child 477538 RSS 3.65 GB; refresh-worker 1.99 GB; live-odds-worker 1.96 GB.
- #848's read-only scorecard replay is also running (nice 19, 1.69 GB RSS).

**A-3:** **0** `MEMORY_GUARD_ABORT` and **0** `RECYCLE_EXIT` since 8:01 PM.

**Board (P2):**
- builds at 8:04:49 PM (**507 s**: the first after the 7:53 PM respawn), 8:14:01 PM (278 s) and 8:23:19 PM (286 s);
- median 286 s; 1 over 300 s;
- publication gap 555-558 s; today-cadence step max 164 s; today's board 326 s old.

**Slate: 53 live.**
- Flags: 91 shown, 0 false, 0 missed, 0 dark.
- P1: 16 college totals flags, 1 card contradiction (the card bug).
- #824: 0 at this read. P6: 0.
- Live rows: 1,775, 759 priced <= 120 s: NBA 1,061 (505); NCAAB 659 (241); WNCAAB 26 (11); NCAAF 25 (0); NHL 4 (2).

**The r16 "ours below points" pair:**
- **Vermont @ Yale u129.5:** the card bug. It showed 127.5 from the u128.5 row; the flagged row's own total of 128.1 sits above the 128 points scored.
- **Coppin St @ La Salle u149.5:** a candidate. The flagged row's own `live_total` was 147.6, priced 110 s before the read, with 149 points on the chip at the read. Either a #824 miss or end-game staleness (#836).
- Both were sent to the #824 / I-17 owner.

**P7:** 7 sweeps launched, 4 refused (36.4%); live run 163 s; no odds child running; 0 `NHL_LIVE_GENERATION` markers.

**P8:** 33 NHL overlay builds, 171 in-play rows.

**Overlay:** 0 gaps over 360 s (max WNCAAB 173 s); tick gap max 114 s. Web merges 10, 0 stale.

**Load:** query 10.3 s.

**Team cards:** 0 defects.

**Monitor slip:** the first dashboard upload this reading went out without rebuilding `readings.json`, so it carried 16 rows. It was rebuilt and re-uploaded, with 17 rows.

### The r16 pair resolved (~8:40 PM CST, the #824 / I-17 owner local_1f10ce63, from the fleet's NCAAB live ledger)

- **Coppin St @ La Salle u149.5 is NOT a #824 miss. It is BOARD STALENESS (A-3's cost).**
  - #824 refused the 148.5 total at 02:00:29Z with `model_projected_final_below_points_scored` (score 149 vs the sim's final 146.83).
  - The 149.5 row's last ledger record was 01:52:02Z: score 132, `priceable False`.
  - So the flag at 02:01:11Z came from a board built before that refusal. The board was 17 min old because of the 7:52 PM memory-guard recycle. The stale board showed a line the gate had already withdrawn.
  - End-game re-sim lag in that game: the sim's state ran 6-13 points behind the score in the last ~4 minutes. This is #836, already known.
- **Vermont @ Yale u129.5:**
  - (a) The card's wrong-row pick. The fix `523357e7f` loads after the 10:31 PM recorder load.
  - (b) The calibrated level pulls the 50/50 total under the sim's final, and late in a game that can cross the score. Rare: 5 of 980 calibrated row reads across 12 readings, all in this one game.
  - A display floor (never below the points scored) has been put to the user by the owner. It is not built.

## Reading 18 — Wed 11-18 8:52 PM CST (02:52Z 11-19): the third memory-guard recycle

**Fleet:** `a3104a5b6`, no new ff. Host load 4.9 (5.9 / 6.0).
- live-odds-worker: `exited code=0 after 22453s -- restarting in 5s` at ~8:50:44 PM. Its own clean recycle; new pid 561403.

**A-3, the third recycle, and the intervals are shrinking: 8.8 h, then 83 min, then 50 min.**
- `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint floor_mb=1900` at 8:32:14, 8:37:39 and 8:42:12 PM. Headroom was 1,678 / 1,545 / 1,598 MB; the container was at 5.49-5.62 GB.
- `RECYCLE_EXIT reason=heavy_build_refused ... uptime_s 2977` at 8:42:57 PM, then `BOARD_PROCESS_EXITED pid=477538 rc=-6 reason=exit uptime_s=3007`.
- Child 549989 READY at 8:43:33 PM (attempt 4). New child RSS 2.43 GB at 8:52 PM.
- Board publications: last at **8:30:23 PM** (335 s). The new child's first build reached its shortlist exit at 8:50:33 PM and had not finished by the read.
- **Today's board was 1,343 s (22.4 min) old at the read.**

**Slate: 42 live.**
- Flags: 42 shown, 0 false, 0 missed, 0 dark.
- P1: 16 college totals flags, 2 card contradictions (the card bug; fix `523357e7f` after 10:31 PM).
- #824: 0. P6: 0.
- **Live rows: 1,412, only 167 priced <= 120 s** (NBA 846 rows, 43 fresh; NCAAB 536, 119), with the board 22 min old.

**P7:** 7 sweeps launched, 3 refused (30%); live run 51 s; an NHL odds child was 27 s old; 0 `NHL_LIVE_GENERATION` markers.

**P8:** 36 NHL overlay builds, 154 in-play rows.

**Overlay:** 0 gaps over 360 s (max NBA 283 s); 1 `deferred_slow` tick. Web merges 5, 0 stale.

**Load:** query 5.4 s.

**Team cards:** 0 defects.

## Reading 19 — Wed 11-18 9:16 PM CST (03:16Z 11-19)

**Fleet:** `a3104a5b6`, no new ff. Host load 5.9 (4.8 / 5.0). A web worker recycled at ~9:15 PM (gunicorn pid 597534, up 75 s).

**Board (P2):**
- Builds at 8:55:36 PM (485 s, the first after the 8:43 PM respawn) and 9:04:40 PM (301 s). Publication gap 544 s.
- Then `MEMORY_GUARD_ABORT` at 9:08:14 and 9:09:33 PM, headroom 1,895 / 1,815 MB. **That is 2 of the 3 refusals that trigger the next recycle.**
- At the read, the next build had reached its shortlist exit (9:15:23 PM). Today's board was 1,268 s old by the query's own block.

**Slate: 32 live.**
- Flags: 43 shown, 0 false, 0 missed, 0 dark.
- P1: 7 college totals flags, 1 card contradiction (the card bug).
- #824: 0. P6: 0.
- Live rows: 1,277, 744 priced <= 120 s (NBA 949 / 643 fresh; NCAAB 317 / 95).

**P7 (NHL window over):** no NHL live rows at this read (38 NHL overlay builds, 0 in-play rows now). 7 sweeps, 1 refused (12.5%).

The owner's 6-9 PM read passed 4 of 5 checks. The miss was one 27-min NHL odds gap around the 6:30 PM puck drop, not caused by NHL. Its full-window verdict comes at 11 PM.

**Overlay:** 0 gaps over 360 s (max NCAAF 152 s); tick gap max 58 s. Web merges 41, 0 stale.

**Load:** query 12.3 s.

**Team cards:** 0 defects.

**Optimization items** (local_09a95c0b, ~9:00 PM). All default-off on main; nothing loaded.
- **#847:** built. Scorecard test passed; the rail test failed on coverage; forward grade 11-26.
- **#848:** the soccer "mis-grade" was false (players who did not play are already voided; the error is the assumed market EV). The NHL stale-quote goal-scorer rows were real (780 of 782); fix default-off.
- **#849:** closed without building. Far-ahead soccer builds cost ~6 s per board build. **This closes L-d.** The evening board cost is A-3 (memory), not CPU priority.

## Reading 20 — Wed 11-18 9:41 PM CST (03:41Z 11-19), full page: the fourth memory-guard recycle

**Fleet:** `a3104a5b6`, no new ff. Host load 3.8 (4.5 / 4.8).

**A-3, the fourth recycle:**
- `MEMORY_GUARD_ABORT` at 9:19:33, 9:23:17 and 9:24:33 PM (headroom 1,554 / 1,724 / 1,642 MB; container 5.44-5.61 GB).
- `RECYCLE_EXIT reason=heavy_build_refused ... uptime_s 2518` at 9:25:30 PM, then `BOARD_PROCESS_EXITED pid=549989 rc=-6 reason=exit uptime_s=2541`.
- Child 613542 READY at 9:25:59 PM (attempt 5); RSS 2.88 GB at 9:41 PM.
- **The intervals keep shrinking: 8.8 h, 83 min, 50 min, 42 min.** Each new child refills to the guard's floor faster.
- Board publications: 9:18:02 PM (316 s), then **9:35:01 PM (359 s)**, a **17 min (1,019 s)** gap. Today's board was 427 s old at the read.

**Slate: 25 live.**
- Flags: 50 shown, 0 false, 0 missed, 0 dark.
- P1: 9 college totals flags, 1 card contradiction (the card bug).
- #824: 0. P6: 0.
- Live rows: 1,190, 665 priced <= 120 s.

**Live odds lane:** 10 launched, 3 refused (23.1%). Live runs 4, max 171 s; pregame 262 s.

**Overlay:** 0 gaps over 360 s (max NCAAF 171 s); tick gap max 52 s. Web merges 45, 0 stale.

**Load (full page):** `/intelligence` 10.4 s; query **27.5 s**.

**Team cards:** 0 defects.

**Next on the fleet:**
- the board-split verdict task at 10:15 PM CST;
- the suggested recorder fix's refresh-worker restart after 10:31 PM (local_fbe07d8c). That restart also resets the parent's memory, so post-restart readings measure a fresh process.
