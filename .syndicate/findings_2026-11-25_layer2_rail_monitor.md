# 2026-11-25: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## Fleet-watcher flag: R8 (12:23 PM CST) overlay_gaps_over_360=1, WNCAAB 1,009 s; read-only

- **Verdict: idle time between games, not a stall. Cost 0.** The WNCAAB in-play overlay printed no line from 18:04:49Z to 18:21:38Z.
  - Navy @ Iowa and Texas Southern @ Vermont (tips ~16:03Z) went final ~18:05Z, and Stetson @ Robert Morris tipped 18:21Z, so no WNCAAB game was live in between.
  - The overlay prints NO line when a build has no fresh in-play rows and its previous publish had no cards (`book_grid_artifact._write_inplay_overlay_best_effort`). So no `rows_inplay=0` line marked the idle.
  - The grid kept building. WNCAAB was rebuilt 3 times inside the gap, each `LIVE_GAMELINE_BUILD ... considered=0`, and the book-grid tick's largest gap was 68 s. WNCAAB's quote log took 0 new rows from 18:04Z to 18:16Z. The rail had 0 WNCAAB rows at R7 and R8.
- **Fixed in the monitor (`C:\tmp\railmon\dash\d4metrics.py`, from 12:46 PM CST; repo copy `scripts/rail_monitor/d4metrics.py`).** A gap after a `cards=0` line counts as QUIET (`overlay_idle_gap_max_s`, `overlay_quiet_over_360_by_sport`) when at least one `LIVE_GAMELINE_BUILD` for that sport and date ran inside it and every one of them considered 0. If no build ran, or a build had live rows, the gap is still a stall.
  - Tested on 5 synthetic cases (`C:\tmp\railmon\d4test\`) and on 10 past stall windows rebuilt from the rotated logs (11-21..11-25). Every count matched the old metric except R8: old 1 gap over 360 s, new 0, with 1,009 s idle and a 106 s maximum (soccer).
  - The first live tick on the new code (1:03 PM, R10) read `log_window_covered` true, 0 gaps over 360 s, and an overlay gap maximum of 95 s. R8's recorded row is unchanged.

## Fleet-watcher flag: R20 (4:23 PM CST) ours_contradictions=1, NCAAB Liberty @ Princeton o134.5 p=0.59, ours 134.3; read-only

- **Verdict: two ticks of one re-sim on one card, not a model disagreement and not two models.**
  - An uncalibrated total's card OURS is the chip's live re-sim `intervals.final.total`, the PROJ box (`intelligence.html` `liveRailSummary`, the `final.total` fallback). The flag's p is the flagged row's own `live_model_probability`.
  - The flagged row (`layer2_inplay_overlay`, grid `price_grid_generated_at` 22:22:25.96Z, betmgm quote 37.5 s old) carried its own `live_total` 137.74, on the over side. P(over 134.5) = 0.59 is consistent with it.
  - The chip carried the re-sim stamped 22:22:28Z: 200 sims, final 134.3 (1H settled 71, 2H 63.3), at H2 11:13 with the score 46-45. That is 2.5 s after the grid build, so the grid could not have used it.
  - On the same game the row equalled the chip whenever they shared a tick: R17 144.495 / 144.5 and R19 145.98 / 146.0. At R18 they were a tick apart (chip 142.7, row 141.245). The 3.4-point drop between ticks follows an H2 scoring drought, 20 points in 8:47.
  - All three live-rail reads (22:23:12-22:23:32Z) showed the same row, so there was no stale mix between the probe's reads.
- **It is LEAD 2 from 11-20 (R32, Wisconsin @ Murray St), seen again.** Todo `#803` lists the same frame issue ("OURS is the re-sim's raw projection; the flag's probability is the priced one"). Neither was fixed, and LEAD 2 was never put to the user.
- **Fixed in the monitor (`C:\tmp\railmon\dash\dash_update.py`, from 4:32 PM CST; repo copy `scripts/rail_monitor/dash_update.py`).** The classification is now `classify_ours()`, with a third outcome, `ours_resim_tick` / `_list`. It applies when OURS equals the chip's live re-sim final (within 0.05), the flagged row's own `live_total` is on the flagged side, and own differs from OURS. The list names both stamps. Anything else across the line still counts in `ours_contradictions`, including 11-18's real defect (OURS from another row).
  - Tested over all 390 saved readings (`C:\tmp\railmon\d17test\regress.py`).
  - With the split off, it reproduces every recorded row since R28 11-22. The 27 older differences are exactly the pre-R28 skew split (those rows have no skew field).
  - The split moves **11 of 1,483 college full-game total flags (0.7%) in 10 readings, 11-15..11-25**, and nothing else. Over all readings the totals are 20 contradictions (mostly before the 11-18 fix), 74 skew-consistent and 11 re-sim tick. The chip is newer than the grid in 9 of the 11.
  - Re-running R20's row through the script to a scratch day file changes only `ours_contradictions` 1 -> 0 and `ours_resim_tick` -> 1. R20's recorded row is unchanged. Backup `dash\dash_update.py.bak_1125b`.
- **Still owed (the card, not the monitor):** the rail card still pairs p from one re-sim tick with OURS from the next, on about 0.7% of college total flags. A display-only fix would make a flagged total's OURS the flagged row's own `live_total`, at the cost of OURS leading or trailing the PROJ box by one tick. That is the user's call: it is a web change and a reload.

## R-H: #860 St. Louis live join at STL @ NYI (7:12 PM CST); read-only, nice 19 -- MET

- **MET.** The kit (`C:\tmp\w1124_stl\kit_after_up_stl.sh`, read_at 2026-11-26T01:12:00Z) read `St Louis Blues @ New York Islanders h2h/puck rows 2, with a live model 2`, like every other game on the rail (NYR @ BUF 3 of 3, VAN @ DET 1 of 1, WPG @ BOS 1 of 1). On 11-21, before the fix, St. Louis read 0 of 1. The key is `on` in refresh-worker and web.
- **The full grid agrees (01:11:50Z, `grid_1125_rh.py`).** Each of the 10 live NHL games joins its live lane on its full-game rows: the moneyline is priced by the lane and the puck line is display-only. St. Louis is the same: moneyline p 0.490 vs market 0.5256, 200 sims, as of 01:10:42Z.
- **Two reads earlier were not join misses.**
  - 01:07Z: STL @ NYI was in the first intermission (`P1 0:00`), and the rail showed only an STL total, which NHL refuses by design.
  - 01:11:31Z, 1:12 into P2: both STL rows had joined (live display lane `live`), but the moneyline quote was over the 120 s pricing ceiling (`quote_older_than_live_pricing_ceiling`). It was fresh (6.2 s) by 01:11:50Z.
- Recorded in lane `nhl-live-join-stl-alias`, todo `#860` and deploys.md 2026-11-26 01:12Z. Closing the lane is the user's call.

## DAILY SUMMARY -- Wed 11-25 (day 11), closed 11:35 AM CST 11-26

The close ran about 10.5 hours late: the 12:47 AM cron's first attempt did not finish. The Windows task took **48 readings**, every 20 min from 10:03 AM to 1:43 AM CST, with no failed tick (3 `p29` timeouts recovered on their retry). Readings covered the last 90 min of the slate. Every reading ran on fleet head `e37a9697f`. POP_START is 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-25_out.json`). Every game was final at the grade; 10 flags were skipped (8 no chip, 2 team unmatched).

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit - fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 550 | 91 | 281-268-1 | **0.512** | 0.481 | [-0.012, +0.075] |
| P3 first reading: yes | 93 | 52 | 41-52 | 0.441 | 0.477 | [-0.131, +0.046] |
| P4 fair < 0.40 | 59 | 23 | 10-49 | 0.169 | 0.232 | [-0.143, +0.039] |
| P5 NCAAB full totals | 136 | 54 | 80-55-1 | 0.593 | 0.503 | [+0.002, +0.165] |
| sport: NCAAB | 335 | 56 | 182-152-1 | 0.545 | 0.504 | [-0.017, +0.100] |
| sport: NBA | 159 | 9 | 66-93 | 0.415 | 0.424 | [-0.068, +0.051] |
| sport: WNCAAB | 24 | 9 | 16-8 | 0.667 | 0.526 | [-0.040, +0.316] |
| sport: NHL | 23 | 13 | 10-13 | 0.435 | 0.477 | [-0.242, +0.141] |
| sport: soccer | 9 | 4 | 7-2 | 0.778 | 0.515 | (4 games) |

- **The flags beat their fair price on the point for the 8th day in a row (11-18 to 11-25), but the CI does not clear 0** after 3 days that did (11-22 to 11-24). The model's mean p was 0.584 against a 0.512 hit, ~7 pp over-confident on its own side (#847); 11-24 was ~5 pp.
- **By market:** full-game totals 0.547 vs 0.475 (193 flags, CI [+0.003, +0.138], clear of 0); full-game spreads 0.449 vs 0.469 (158, below fair); segment spreads 0.558 vs 0.471 (43, above fair after 4 of 5 days below); segment totals 0.518 vs 0.504 (112); moneyline 0.523 vs 0.504 (44).
- **NCAAB full totals:** unders 0.620 (93 flags), overs 0.535 (43). The flagged lines went over 59 of 136.
- **NBA** was the drag: 159 flags in 9 games at 0.415 vs 0.424. Its calibrated or scaled live totals went 0.395 vs 0.436 (86 flags, CI [-0.121, +0.045]). The NBA live total anchor (#834) loaded 11-24; its Kalshi re-check is registered by lane `engine-learner` (12-01).
- **NHL** had 23 flags in 13 games (1 flag on 11-24, a smaller slate), 0.435 vs 0.477, within noise.

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 1 recorded (R20, Liberty @ Princeton), reclassified as two ticks of one re-sim (`ours_resim_tick`, section above); 1 skew-consistent (R35 Omaha @ UC Davis u159.5, OURS = own 162.4) | **MET** (0 real) |
| P2 | board publication gap median <= 600 s, none > 1,800 s, 5:30-10:30 PM | 44 publications, median **361 s**, max 628 s (7:50 PM), 5 over 600 s (`p2_boardpub.py`) | **MET** (11-24: median 314 s, max 536 s, 0 over 600 s) |
| P3 | first-reading flags at or below fair | 0.441 vs 0.477, -3.6 pp, CI [-0.131, +0.046] | **MET** (below fair, within noise) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.169 vs 0.232, 59 flags, 23 games | **MET** |
| P5 | report NCAAB calibrated live full totals | 136 flags / 54 games, 0.593 vs 0.503; under 93 (0.620) / over 43 (0.535); the flagged lines went over 59 of 136 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 48 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | **1 of 2,793** rows, R12 (1:43 PM), N Colorado @ Detroit Mercy o175.5, `live_total` 175.1 with 176 scored | **timing, not the floor** |

- **P8's row:** the chip read H2 0:00 (end of regulation), and its own newer re-sim (as of 19:41:12Z) had a final total of 176.6, at the score. So the row was priced from a re-sim older than the last basket, the 11-20 pattern. The game had **0 live bets** (`live_bets_for.py "Detroit Mercy"`). `ours_below_points` (#824) was 1 at R28 and 1 at R36.

### Fleet-watcher flags and owned readings

- **R8 (12:23 PM), overlay gap 1,009 s, WNCAAB: reclassified QUIET** (idle between games). `d4metrics.py` now counts such a gap as quiet (section above).
- **R20 (4:23 PM), `ours_contradictions=1`, Liberty @ Princeton o134.5: reclassified `ours_resim_tick`** (the row and the chip were adjacent ticks of one re-sim). `dash_update.py` counts it apart (section above). The card's own mismatch (LEAD 2) is a user decision, below.
- **R-H (#860, CHANGE M), 7:12 PM: MET.** St. Louis read 2 of 2 rows with a live model at STL @ NYI, like every live NHL game (section above; deploys.md 2026-11-26 01:12Z).
- **R-B (#844, CHANGE D): P2 and P3 PREDICTED; #844 is graded** (deploys.md 2026-11-26 17:35Z). NCAAB moneyline rows fresh by row age 274 of 352 (77.8%) over 43 distinct grids, equal to fresh by cell (77.8%), 0 mismatch rows (11-19: 31.2% vs 80.1%, 304 mismatches). NBA mismatch 0 over 48 samples. P1 PREDICTED again (1,053 of 2,696 venue rows). P4 stays NEITHER (11-25 interim).

### What the day found

- **Change G (#854, the I-29 orientation join) held for a 2nd evening.** 12 of the 15 college games whose lane was REVERSED carried a live model, at 62 of 74 game-readings (11-24: 9 of 10). The 3 that never did: 2 WNCAAB `no_margin_anchor` (Grand Canyon @ Winthrop, James Madison @ Arkansas) and Saint Louis @ Stanford `no_plays` (2 readings).
- **Games with no live model, as unique games: 60** (38 on 11-24). Mostly deliberate or by design: `key_player_out` 12, `competition_not_modelled` 9 (soccer), `in_intermission` 5, `no_plays` 4, `resimmed_model_by_helper_read` 9. `not_in_resim` 6, each for one reading (games tipping after the snapshot). `resimmed_no_row_model` 3, each for one reading (Albany @ Syracuse, Cavaliers @ Knicks, Norfolk St @ NC State), so not persistent.
- **R46 (1:03 AM), one 665 s NCAAB overlay gap.** It was on the **11-26** overlay file, which held 7 in-play rows of the late 11-25 games (Incarnate Word @ Hawai'i, Saint Louis @ Stanford, Clemson @ Colorado St) after the midnight roll. This is R-J's evening UTC/Central split, seen in NCAAB. Change O moved only soccer's shard. **Lead, no owner** (lane `evening-utc-date-split` closed 11-25): one gap at 1 AM, cost not measured.
- **Sweeps refused fell to 139 of 499 (28%)**, all `lane_busy`; 11-24 had 193 of 473 (41%) by the same row sum.
- **Dark rows: 18 at 6 readings, all `board_cadence`** (rows aged from the board build, by design).
- NHL odds child age max 219 s (limit 600 s). 0 false flags, 0 missed flags.

### Loads (11-25 slate)

- **7:54 AM:** web: quiet-worker memory watch on by default (`e37a9697f`, lane `web-silent-worker-kills`; not a betting change). The `/ops/dashboards` hub and cheat-sheet rules v4 (display only) rode along. Nothing else loaded.

### Open user decisions

- **Rail card OURS for a flagged total** (asked 11-25 4:40 PM CST, unanswered): show the flagged row's own `live_total` beside its probability (a web change plus reload-web, not a betting change), or leave the card as is. It is about 0.7% of college total flags.
- **Close lane `nhl-live-join-stl-alias` and todo #860** (asked 11-25 7:15 PM CST after R-H MET, unanswered).
- The next betting-change window is 12-08.
