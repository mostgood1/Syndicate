# 2026-11-27: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close. The day's daytime sections (the Santander @ Levante flag, the soccer lane-age ceiling #865, SOCCER_RUN_FAILED, the MLS history gap and the MLS ratings rollover #866) are in `.syndicate/findings_2026-11-26_layer2_rail_monitor.md`.

## DAILY SUMMARY -- Fri 11-27 (Black Friday, day 13), closed 1:26 AM CST 11-28

The Windows task took **46 readings**, every 20 min from 10:03 AM to 1:03 AM CST, with **no failed tick**; they covered the last 90 min of the slate. Fleet heads: `fe46fb249` (R1-R2), `c2fb7f49b` (R3-R9), `a99dc4492` (R10-R14), `3231ee493` (R15-R20), `c0950cdaf` (R21-R26), `b02c76e43` (R27), `bcbb5465f` (R28-R42), `4bfaa108a` (R43-R46). POP_START is 16:00Z. Flags are graded on their first sighting against the finals by date (`C:\tmp\railmon\grade_2026-11-27_out.json`): 592 unique, 588 graded, 4 skipped (3 no probability, 1 team unmatched). **The heaviest slate in a week:** every sport but MLB and WNBA, up to 51 live games (R17, 3:23 PM) and 1,302 live rows (R30, 7:43 PM).

### The grade

| bucket | flags | games | W-L | hit | fair | hit - fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 588 | 104 | 287-301 | **0.488** | 0.476 | [-0.025, +0.053] |
| P3 first reading: yes | 80 | 48 | 35-45 | 0.438 | 0.489 | [-0.130, +0.030] |
| P4 fair < 0.40 | 89 | 29 | 17-72 | 0.191 | 0.231 | [-0.123, +0.041] |
| P5 NCAAB full totals | 126 | 48 | 68-58 | 0.540 | 0.502 | [-0.047, +0.127] |
| sport: NCAAB | 259 | 48 | 142-117 | 0.548 | 0.502 | [-0.021, +0.116] |
| sport: WNCAAB | 43 | 19 | 26-17 | 0.605 | 0.514 | [-0.029, +0.216] |
| sport: NCAAF | 77 | 13 | 43-34 | 0.558 | 0.511 | [-0.059, +0.162] |
| sport: NBA | 186 | 11 | 67-119 | **0.360** | 0.411 | **[-0.093, -0.004]** |
| sport: NHL | 9 | 6 | 4-5 | 0.444 | 0.526 | [-0.355, +0.227] |
| sport: soccer | 14 | 7 | 5-9 | 0.357 | 0.499 | [-0.410, +0.081] |

- **The flags beat their fair price on the point for the 10th day in a row (11-18 to 11-27); the CI does not clear 0** (588 flags in 104 games). The model's mean p was 0.578 against a 0.488 hit, ~9 pp over-confident on its own side (#847; 11-26 ~5 pp, 11-25 ~7 pp).
- **NBA was below fair, and the CI cleared 0 below** (186 flags, 11 games). Full-game spreads went 10-31 (0.244 vs 0.318, CI [-0.140, -0.003]); totals 0.373 vs 0.429 (102). **Pooled over the 8 graded NBA days (11-19..11-27):** 1,054 flags, hit 0.396 vs fair 0.414 at a mean model p of 0.534, below fair on the point on 6 of 8 days (a weighted sum of the daily buckets, no pooled CI). The NBA live model is ~14 pp over-confident where it flags. Evidence for per-line calibration (#847), never a gate.
- **NCAAB full-game spreads cleared 0 above:** 42-19 (0.689 vs 0.501, 61 flags / 38 games, CI [+0.086, +0.284]). All full-game spreads 0.530 vs 0.446 (134, CI [+0.018, +0.154]); segment spreads 0.383 vs 0.458 (47); segment totals 0.449 vs 0.494 (107); full-game totals 0.488 vs 0.473 (254); moneyline 0.565 vs 0.553 (46).
- **Totals:** unders 0.522 vs 0.486 (207), overs 0.416 vs 0.470 (154), the reverse of 11-26 (overs 24-9). NCAAB full totals: unders 50-43, overs 18-15; the flagged lines went over 61 of 126.

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 0 at all 46 readings; 1 skew-consistent (R35); 0 `ours_resim_tick` | **MET** |
| P2 | board publication gap median <= 600 s, none > 1,800 s, 5:30-10:30 PM | 24 publications, median **628 s**, max 1,508 s (from 10:15 PM), 13 over 600 s, 0 over 1,800 s (`p2_boardpub.py`) | **NOT MET** on the median (11-26: 285 s; 11-25: 361 s) |
| P3 | first-reading flags at or below fair | 0.438 vs 0.489, CI [-0.130, +0.030] | **MET** (within noise) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.191 vs 0.231, -4.0 pp, 89 flags / 29 games | **MET** |
| P5 | report NCAAB calibrated live full totals | 126 / 48 games, 0.540 vs 0.502; under 93 (0.538) / over 33 (0.545); the flagged lines went over 61 of 126 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 46 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | **14 of 2,901** rows, at R16 (5), R28 (8), R41 (1) | **NOT MET on the count; timing, not the floor** |

- **Why P2 missed: the refresh-worker parent's ratchet, on the week's heaviest slate.** The parent (pid 469) has run since the 11-26 11:10 AM reboot. It was 1.1-1.3 GB on the 11-26 evening and 2.0-2.46 GB on this one (p50 2,305 MB 7:30-10:30 PM CST, 9 readings). 5 PM-10:30 PM CST the board child exited rc 75 **9 times** (5 `post_build_headroom` recycles, 4 `heavy_build_refused` streaks), with 23 `MEMORY_GUARD_ABORT` (22 `pre_source_state_fingerprint`) and `POST_BUILD_CHECK` held `min_uptime` 8 times (`p7count.py`, `C:\tmp\railmon\p7count_1127.txt`). 3 of the 5 gaps over 1,200 s hold a streak exit (7:09, 7:49 and 10:00 PM). This is #850 CHANGE J's note: after any fleet ff the parent cannot self-recycle until a deliberate restart. Changing that rule is lane `board-split-memory-guard`'s question for the user (a betting change), not the monitor's.
- **P8's rows are the last seconds of regulation.** The probe samples up to 3 rows a reading (7 of 14). All 4 sampled games: Le Moyne @ Maine (H2 0:10), Memphis @ Wake Forest (H2 0:09), Bowling Green @ Indiana (H2 0:36; the chip's own re-sim final 146.5 < 150 scored) and Jacksonville St @ Omaha (END H2, quote 399 s old). In 2 of the 4 the chip's re-sim already sat above the score, so the rows were priced from the re-sim before. As on 11-20: timing, not the floor. **0 live bets** on the 4 games (`live_bets_for.py`). The other 7 rows' inputs are gone (the tick drops saved queries after 6 h).

### Owned readings

- **R-M, the after-midnight carry (`8455f25c0`): MET on its first population.** After the 06:00Z roll, refresh-worker's `LAYER2_CARRYOVER date=2026-11-27` reported `chips_live_now` 2 to 06:38Z, 1 to 06:59Z and 0 at 07:06Z (`read_carry.sh`). The probe readings at 12:03, 12:23 and 12:43 AM carried both games still live, Creighton @ Gonzaga and Texas Tech @ San Diego State; the 1:03 AM one carried Texas Tech @ San Diego State alone. **0 carried games without a live card** at all 4 (`read_carry.py`). D's chip artifact published every 5-11 min after the roll. On 11-26 and 11-25 those games' cards were gone at 12:03 AM.
- **The rail card OURS fix (`fe46fb249`): MET on its first population.** `read_ours_fix.py` over 6 evening readings (7:23-10:03 PM): 34 flagged uncalibrated full-game totals with their own live total; OURS equals the row's own total on 33. The 34th (R35 Memphis @ Minnesota o214.5, own 219.25) differs only in rounding: the page shows 219.3, and the reader's Python round gives 219.2. The tooltip showed where the PROJ box differed (5 rows). `ours_resim_tick` was 0 at all 46 readings. Output: `C:\tmp\railmon\ours_fix\read_1127.txt`. Both deploys.md verifies are answered (deploys.md 2026-11-28 07:26:21Z READING).

### What the day found

- **The soccer live lens stalled all evening on live-odds-worker's memory gate.** It logged 123 `low_headroom` skips 6-11 PM CST: role RSS 2,853-3,313 MB against 3,072 MB, so the 300 MB headroom was never met. The lens snapshot was 16-36 min old at R30-R38 (the new `stale_snapshots` field's first evening), with 0-1 MLS match in it. Those lanes priced live soccer rows with no age check; 0 live bets on Vancouver @ Real Salt Lake. The #865 ceiling would refuse such lanes when `on`; 12-08 loads it as `shadow` only (user "yes, add #865 to the batch as shadow"). R-N re-measures it at the 11-28 close. The afternoon's R14-R18 soccer `not_in_resim` (Chelsea @ Nottingham Forest, Santander @ Levante, Nacional @ Maritimo) is the same stall, on the 14:01:59 CST snapshot, read before the `snapshot_stale` label landed at 4:14 PM.
- **Games with no live model, as unique games: 50** (22 on 11-26, 60 on 11-25):
  - `resimmed_model_by_helper_read` 10 (timing between two reads) and `key_player_out` 9;
  - `not_in_resim` 9: the 3 soccer matches above; 3 NBA at R27 (6:43 PM), which tipped after the 6:43 PM snapshot (Nets @ Raptors again at R34); 3 NCAAB, at 1 reading each;
  - `orientation_reversed` 5 (I-29), `no_margin_anchor` 4 (WNCAAB), `sport_absent_from_helper_read` 4 (NHL), at 1-5 readings each;
  - `resimmed_no_row_model` 3, at 1-2 readings each;
  - 1-2 games each: `in_intermission`, `no_plays`, `uninformative_probability`, `resimmed_few_priced_rows`, `snapshot_stale`.
- **Sweeps refused: 320 of 513 (62%)**, the week's highest share (11-26: 11%; 11-25: 28%; 11-24: 41%).
- **Dark rows:** 81 at R33 (8:43 PM; that window's one board build took 435 s), otherwise at most 5. In the samples: `board_cadence` 24, `cadence_edge` 6.
- **Other readings:** NHL odds child age peaked at 1,654 s (R43, 12:03 AM). Overlay gaps over 360 s: 0 (max 296 s). 0 false flags, 0 missed. Web stale merges: 535 (11-26: 1,128).

### Loads (11-27 slate; none a betting change)

| time (CST) | load | how |
|---|---|---|
| 10:29 AM | after midnight the Today rail keeps a still-live game from the evening before (this lane) | ff `8455f25c0` + reload-web |
| 10:42 AM | game-chips makes no ESPN call inside a web request | ff `c2fb7f49b` + reload-web |
| 12:46 PM | NFL makes no ESPN call inside a web request | ff `a99dc4492` + reload-web |
| 2:37 PM | NBA cheat-sheet matchup evidence (#862) | ff `3231ee493` + reload-web |
| 4:32 PM | the NFL props and picks pages lead with the board's picks (#861 1f) | ff `d72d4d536` + reload-web |
| 4:39 PM | cheat-sheet section rules v5 (#862) | ff `c0950cdaf` + reload-web |
| 5:02 PM | fair CLV on closing marks (record fields only) | board child respawn, no restart |
| 6:43 PM | the game cards lead with the board's pick, then the NBA tile colour at 6:58 PM (#861 1g) | ffs `b02c76e43` and `bcbb5465f` + reload-web |
| 12:01 AM | the NCAAF line index reads the week's shards streamed (#867) | ff `4bfaa108a` + reload-web |

### Open user decisions

- **(a2) the carried card's rows and flags:** the after-midnight card shows the scoreboard only (R-M MET). Putting the prior date's live rows on it needs web's combined board read, which other lanes hold (asked 11-27 9:40 AM CST).
- **(b) NCAAB quotes filed by the Central tip day** (a betting change; the 12-08 window at the earliest).
- **Close lane `nhl-live-join-stl-alias` and todo #860** (asked 11-25 7:15 PM CST after R-H MET, unanswered).
- The next betting-change window is 12-08. #865 rides it as `shadow` only; `on` is not approved.
