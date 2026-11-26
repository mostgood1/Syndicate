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
