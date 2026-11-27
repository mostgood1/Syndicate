# 2026-11-26: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## Fleet-watcher flag: soccer FC Copenhagen @ Inter Club d'Escaldes "not_in_resim" at R13 and R14 (to 2:23 PM CST); read-only

- **Verdict: the monitor's own name miss, fixed. No fleet defect, cost 0.** The lens held the match: ESPN 401915738, uecl, spelled "F.C. København" @ "Inter D'Escaldes", `projection` null and `momentum.reason` `competition_not_modelled` (the #699 gate). Read from redis `soccer_live_lens.json` (generated 2:26:38 PM CST) with `C:\tmp\railmon\diag_1126_escaldes.py` (read-only, nice 19).
- **The cause was Copenhagen / København, not the apostrophe or the prefixes** (the watcher's guess). The home side already matched by the word-subset rule ("inter d'escaldes" inside "inter club d'escaldes"). The away side folded to "fc kobenhavn" against the rail's "fc copenhagen", and `team_aliases.chip_join_key` does not join them either.
- **Fixed in the monitor (`C:\tmp\railmon\p29_orient.py`, from 2:27 PM CST; repo copy `scripts/rail_monitor/p29_orient.py`).** `norm` maps native city names to the English ones word by word, on both sides, so it cannot split a pair that already matched: København, München, Köln, Praha, Beograd, București, Warszawa, Kiev, Athina, Wien, Moskva, Lisboa, Genève, Sevilla, Milano, Torino, Napoli, Roma, Firenze, Genova. It also folds curly apostrophes to straight ones.
- **Re-run at 20:27:50Z (2:27 PM CST):** the game reads `direct`, `competition_not_modelled` (uecl), like the other 17 live UEL/UECL games. 18 of 18 live soccer games matched the lens, 0 `not_in_resim`.
- The repo copy of `p29_orient.py` had not been refreshed since 11-22, so it also gains the 11-24 fixes (the ø fold, the UEFA `competition_not_modelled` reason, the `chip_join_key` fallback).

## Rail card OURS fix loaded (10:40 PM CST; user "Yes, fix it here", "Yes, lend it")

- **What:** a flagged full-game total's OURS on the rail card is now the flagged row's own live total, not the chip's PROJ box, which can be one re-sim tick apart (11-25 R20). The tooltip names the box's number when they differ. `fe46fb249`, display only, not a betting change.
- **Load:** ff + reload-web at 04:39:59Z 11-27, after lane `web-silent-worker-kills` loaded `b709934b2` to its exact SHA. Served page carries the branch; web log 0 errors; live page 0 console errors. deploys.md 2026-11-27 04:39:59Z.
- **Owed at the closes:** `ours_resim_tick` reads 0 on every reading after the load. No flagged total was a tick apart from its row at load time, so only the unit test exercised the new answer.

## DAILY SUMMARY -- Thu 11-26 (Thanksgiving, day 12), closed 1:45 AM CST 11-27

The Windows task took **46 readings**, every 20 min from 10:03 AM to 1:03 AM CST, with no failed tick (1 `p29` timeout recovered on its retry). Readings covered the last 90 min of the slate. Fleet heads: `e37a9697f` (R1-R5), `82bfc6bbd` (R6-R36), `30b2be76e` (R37-R38), `fe46fb249` (R39-R46). POP_START is 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-26_out.json`). Every game was final at the grade; 0 flags skipped. A small slate: no NBA and no NHL; 4 NFL, 1 NCAAF.

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit - fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 191 | 29 | 106-84-1 | **0.558** | 0.517 | [-0.032, +0.123] |
| P3 first reading: yes | 41 | 21 | 25-16 | 0.610 | 0.506 | [-0.042, +0.240] |
| P4 fair < 0.40 | 3 | 3 | 2-1 | 0.667 | 0.306 | (3 games) |
| P5 NCAAB full totals | 61 | 20 | 31-30 | 0.508 | 0.500 | [-0.146, +0.181] |
| sport: NCAAB | 167 | 21 | 91-75-1 | 0.548 | 0.518 | [-0.055, +0.123] |
| sport: WNCAAB | 12 | 6 | 9-3 | 0.750 | 0.495 | [+0.060, +0.393] |
| sport: NCAAF | 11 | 1 | 6-5 | 0.545 | 0.498 | (1 game) |
| sport: NFL | 1 | 1 | 0-1 | 0.000 | 0.857 | (1 game) |

- **The flags beat their fair price on the point for the 9th day in a row (11-18 to 11-26); the CI does not clear 0** (191 flags in 29 games). The model's mean p was 0.609 against a 0.558 hit, ~5 pp over-confident on its own side (#847); 11-25 was ~7 pp.
- **By market:** full-game totals 0.562 vs 0.503 (73 flags); full-game spreads 0.475 vs 0.500 (40, below fair again); segment spreads 0.600 vs 0.500 (15); segment totals 0.535 vs 0.499 (44); moneyline 0.737 vs 0.663 (19).
- **Totals leaned under, and the overs won.** 84 of 117 totals flags were unders, at 0.482 vs 0.502; the 33 overs went 24-9 (0.727, CI [+0.101, +0.339]). NCAAB full totals: unders 23-29 (0.442, 52 flags), overs 8-1 (9); the flagged lines went over 37 of 61 (11-25: unders 0.620, over 59 of 136). One day, and the under CI spans 0 ([-0.237, +0.131]).
- **Soccer had 0 flags:** the 13 live matches were Europa / Conference League, `competition_not_modelled`, by design. NFL's Thanksgiving games yielded 1 flag (Bears @ Lions had `uninformative_probability` at 1 reading).

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 0 at all 46 readings; 0 skew-consistent; 0 `ours_resim_tick` | **MET** |
| P2 | board publication gap median <= 600 s, none > 1,800 s, 5:30-10:30 PM | 56 publications, median **285 s**, max 860 s (04:13:32Z), 2 over 600 s (`p2_boardpub.py`) | **MET** (11-25: median 361 s, max 628 s) |
| P3 | first-reading flags at or below fair | 0.610 vs 0.506, +10.4 pp, CI [-0.042, +0.240] | **within noise** (above, not significant, as on 11-19 to 11-22) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.667 vs 0.306, **3 flags in 3 games** | **NOT MET on the point; too few to read** |
| P5 | report NCAAB calibrated live full totals | 61 flags / 20 games, 0.508 vs 0.500; under 52 (0.442) / over 9 (0.889); the flagged lines went over 37 of 61 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 46 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | **0 of 1,100** rows | **MET** |

- **P2's two gaps over 600 s** (802 s from 04:00:10Z, 860 s from 04:13:32Z) bracket the 10:18 PM step-1e board-child TERM (deploys.md 2026-11-27 04:18:28Z), which waited for a drained save: `POST_BUILD_CHECK` held `drain_requested` once (`p7count.py` 23:00-05:00Z). They are the deploy's gaps. Outside them the longest was 444 s.
- `ours_below_points` (#824) was 1, at R19 (4:03 PM).

### Owned readings and carry-overs (runbook R-L)

- **The rail card OURS fix (`fe46fb249`, loaded 10:39:59 PM): nothing to read yet.** `ours_resim_tick` was 0 at all 9 readings after the load (R39-R47), and `read_ours_fix.py` over R39-R42 found **0** flagged uncalibrated full-game totals: every flagged total after the load was calibrated (1-2 a reading), and the rail emptied after midnight. The branch's different answer has still only met the unit test. The owed reading stays open at the next closes.
- **#850 CHANGE J note:** the 11:10 AM reboot gave refresh-worker a FRESH parent (pid 469). It stayed at 1.1-1.3 GB through the evening (`ps` at each reading), not the ~2.2 GB of the note, and logged **0** `BOARD_PROCESS_RECYCLE` and 0 rc 75 exits in 5 PM-11 PM CST. 2 `MEMORY_GUARD_ABORT` (pre_source_state_fingerprint, both 6-7 PM). The board child (pid 535, 4.0-4.5 GB) ran from the boot to the 10:18 PM TERM; its successor is pid 256375. So the evening had no post-build recycles to read.
- **The NCAAB after-midnight cost (R46's lead from 11-25): REAL, on the rail card and on pricing; 0 on money so far.**
  - Two NCAAB games were live across the midnight roll: Baylor @ Gonzaga (tip 04:53Z) and Texas Tech @ Oregon (04:57Z). At 05:43Z each had a rail card with 15 rows (16-17 live rows). **From 06:03Z (12:03 AM CST) the rail rolled to 11-27 and neither game had a card** at R43-R45, though refresh-worker still had both in its live snapshot (`index=2` until 06:50Z). The page's Today filter drops a chip whose Central date is not the rail's date (`intelligence.html` ~4347), and the 11-27 chip list does not carry them.
  - **The same happened on 11-25:** 5 cards were live at 05:43Z 11-26 (Spurs @ Trail Blazers, 125 rows; 4 NCAAB) and 0 from 06:03Z. So it is every night with late West Coast games, and every sport, not only NCAAB.
  - **Pricing thinned on the D+1 shard.** The 11-26 shard built every ~40 s before midnight (15 builds per 10 min, ~80 considered rows per build, 128-281 rows written per 10 min). The 11-27 shard built every ~80 s (6-8 per 10 min, ~30 considered, **0-32 written per 10 min**). Overlay gaps on the 11-27 file were 144-153 s, none over 360 s; the 11-26 file's were 66-89 s before midnight (`overlay_offdate_inplay` `ncaab@2026-11-27` 19-24 rows). Reader: `C:\tmp\railmon\rl2_ncaab_midnight.sh`.
  - **Money:** 0 live bets on either game, before or after midnight (`live_bets_for.py`).
  - **Whose call:** two separate fixes, both the user's. (a) Keep a still-live game of the previous Central day on the Today rail after midnight: a web change plus reload-web, display only, not a betting change. (b) An NCAAB version of change O (quotes filed by the Central tip day): change O was a betting change (BC-070), so (b) is one too and could only load in the 12-08 window, default-off on main until then. No lane owns either (`evening-utc-date-split` closed 11-25).
- R-L (1) done: the 17:28:02Z web load is in `loads.json`, with the day's other 5 loads. R-L (3): the p844 sampler stopped by itself after 11-26.

### What the day found

- **The host was offline for the first hour of the slate.** Its Wi-Fi was down from 12:14 AM to 11:11 AM CST (deploys.md 2026-11-26 17:10:07Z, lane `portfolio-monitor`); Windows was restarted by hand at 11:10 AM. R1-R4 (10:03-11:03 AM) read **0 live games** (the chips could not update), and the day's 3 overlay gaps over 360 s (NCAAB 583 / 775 / 412 s) and tick gaps up to 489 s are all in those windows. After the boot, the longest overlay gap was 172 s.
- **Change G (#854, the I-29 orientation join) held for a 3rd evening.** 11 of the 12 college games whose lane was REVERSED carried a live model, at 61 of 62 game-readings (11-25: 12 of 15). The one miss: Robert Morris @ Clemson (WNCAAB), `no_margin_anchor` at 1 reading.
- **Games with no live model, as unique games: 22** (60 on 11-25, a bigger slate). `competition_not_modelled` 13 (soccer, UEFA), `key_player_out` 3, `not_in_resim` 2 (1 reading each), and 4 single games at 1-2 readings each (`no_margin_anchor`, `uninformative_probability`, `sport_absent_from_helper_read`, the reversed miss above).
- **Sweeps refused fell to 57 of 521 (11%)** (11-25: 28%; 11-24: 41%), on a slate with no NBA or NHL.
- Dark rows 2 at 1 reading, both `board_cadence`. 0 false flags, 0 missed flags. Web stale merges 1,128 of 1,231, in line with 11-23..11-25 (1,147 / 1,340 / 1,215).

### Loads (11-26 slate)

- **11:10 AM:** unplanned restart after the network outage; refresh-worker picked up `e37a9697f` (ride-alongs only). Not a betting change.
- **11:28 AM:** web: the NHL and soccer pages lead with the board's pick (`75624d138`, #861 step 1d; display only).
- **11:40 AM:** live-odds-worker: the exits record archives watch rows unseen for 24 h (`82bfc6bbd`, lane `exit-watch-unseen-prune`; not a betting change).
- **10:18 PM:** web + board child: the board shows the EV it judges, net of fee, and the Kalshi / Polymarket prices (`30b2be76e`, #861 step 1e; display only).
- **10:35 PM:** web: a recycled worker with a request still running leaves at once (`b709934b2`, lane `web-silent-worker-kills`; not a betting change).
- **10:39 PM:** web: the rail card's OURS for a flagged full-game total is the row's own live total (`fe46fb249`, this lane; display only).
- No betting change loaded.

### Open user decisions

- **Late games vanish from the Today rail at midnight** (new, measured above): (a) keep a still-live game of the previous Central day on the rail (display only), and separately (b) file NCAAB quotes by the Central tip day (a betting change, 12-08 window at the earliest).
- **Close lane `nhl-live-join-stl-alias` and todo #860** (asked 11-25 7:15 PM CST after R-H MET, unanswered).
- The next betting-change window is 12-08.
