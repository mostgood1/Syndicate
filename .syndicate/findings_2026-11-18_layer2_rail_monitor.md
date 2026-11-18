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
