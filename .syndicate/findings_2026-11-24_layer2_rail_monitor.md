# 2026-11-24: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## Fleet-watcher flag: soccer LASK @ Bodø/Glimt "not_in_resim" at R7 and R8 (12:03 and 12:23 PM CST); read-only

- **Verdict: no fleet defect.** Both matches are Champions League (`ucl`), and no UEFA match gets a live model, on purpose.
  - The soccer live lens covers `ucl`, `uel` and `uecl` (`leagues_checked`). A UEFA match in play is served with `projection` null and `momentum.reason` `competition_not_modelled` (`scripts/poll_soccer_live_state.py` `_scoreboard_only_game`, the `league_has_sim` branch).
  - The cause is the #699 GO/NO-GO gate, NO-GO for UCL, UEL and UECL (verified 10-16, re-tested twice 10-19; `state_soccer.md`). Lane `soccer-uefa-competitions` closed 10-21 with UEFA projections left off.
- **The match was not dropped.** The lens at 12:26:59 PM CST held ESPN 401915380, spelled "LASK Linz" @ "Bodo/Glimt", at 40', 0-0. Aston Villa @ Galatasaray (401915300) was there too, at 41'. Read from redis `soccer_live_lens.json` with `C:\tmp\railmon\diag_1124_bodo\lens.sh` (read-only, nice 19).
- **"not_in_resim" was the monitor's own name miss.** `p29_orient.norm` did not fold "ø" to "o". Galatasaray matched, but its reason read "unknown", because the helper only knew the re-simmed case for soccer.
- **Fixed in the monitor (`C:\tmp\railmon\p29_orient.py`, not the repo):**
  - `norm` now folds diacritics (NFKD plus ø, æ, œ, ß, đ, ł, ı, þ).
  - A null projection with `competition_not_modelled` now reads as that reason, with the detail "no in-play projection by design (#699 NO-GO gate)".
  - **Re-run at 12:29 PM CST:** both matches read `direct` with `competition_not_modelled`. The 3 NCAAB games and 1 WNCAAB game still read `direct` / `resimmed`.
  - Ticks from 12:43 PM on carry the fix.
- **Checked in the follow-up below:** WNCAAB Alcorn St @ Tenn-Martin read `not_in_resim` at R4 only (snapshot 11:04 AM).

## Follow-up (user "Yes, check it"): WNCAAB Alcorn St @ Tenn-Martin "not_in_resim" at R4 (11:03 AM CST); read-only

- **Verdict: the monitor's name miss again, and no model was lost.**
  - The game is ESPN 401921217. It tipped off at 11:00 AM CST and is final.
  - The rail had it at R4 only (4 rows, 2 priced, 0 with a model). It had no rail rows from R5 on.
- **Why the names differ:** the re-sim takes the board's spelling from the WNCAAB odds file (`live_resim.odds_team_names`, then `board_name`). That file holds 16 names (8 games) for 11-24, and this game is not among them.
  - The re-sim lane therefore carries ESPN's "Alcorn State Lady Braves @ UT Martin Skyhawks" (`nameSource` `espn_display`), while the rail says "Alcorn St Braves @ Tenn-Martin Skyhawks".
  - Both fold to one pair under `team_aliases.chip_join_key` ("alcorn state", "ut martin"). Checked with the fleet checkout's code, read-only.
- **The re-sim had the game.** The WNCAAB live count went 5 -> 6 -> 7 between 11:02 and 11:06 AM. From 12:07 PM the live-odds-worker logged `PLAYER_OUT event=401921217 team=UTM` (Tyler Jones, a key player, off the floor since 11:11:54 AM), so the re-sim refused the game on purpose.
- **A latent fleet gap, cost 0 so far:** the live join matches WNCAAB rows to lanes on exact names. Its team-alias fallback is on for NCAAF only, with an opt-in switch for NHL (`live_gameline_join._TEAM_ALIAS_JOIN_SPORTS`). A re-simmed WNCAAB game missing from the odds file but with live rows would lose its model on the rail. The margin anchor is not affected, because it keys on `chip_join_key`.
  - **No reading shows it happening.** Over 11-20 to 11-24, every directly matched college game that was re-simmed but showed no priced row with a model lasted one reading (13 cases). A name miss repeats at every tick, so it cannot explain a one-reading gap.
  - **2:25 PM:** all 6 ESPN-named WNCAAB lanes were refused (5 `no_margin_anchor`, 1 `key_player_out`), and none had rail rows.
- **Monitor fix:** `p29_orient.find` now tries `chip_join_key` pairs (unique match only, with any failure leaving the answer None) after its three name rules.
  - **Offline check:** it finds 401921217 from the rail's spelling, refuses the swapped pair and an unrelated pair, and still finds 401915380 from "Bodø".
  - **Full run on the fleet, 2:25 PM:** rc 0 in 0.7 s; 24 games, 22 direct, 2 REVERSED, 0 `not_in_resim`.
- **Change G (#854, the I-29 orientation fix) reads as working:**
  - **11-20 to 11-23:** the monitor's REVERSED college games had a priced model row at 0 of 162 game-readings.
  - **11-24 to 2:25 PM:** 11 of 11.
  - **2:25 PM:** Pittsburgh @ Oklahoma (11 of 11 rows) and Oregon St @ San Francisco (9 of 9) carried the model.
  - The nightly close counts the full evening.

## Fleet-watcher flag: WNCAAB Winthrop @ James Madison "resimmed_no_row_model" at R19 / R20 (4:03 / 4:23 PM CST), and NCAAB Providence @ Arizona at R20; read-only

- **Verdict: no join defect, and not a change G regression.**
  - The rows carry the right keys (`winthrop` / `james madison`) and the re-sim matched them directly.
  - The dashboard reads only the probe's first live-rail read (`liverail_0`). Each time, that read fell in a moment when the model was legitimately absent. My helper's read about a minute later had it: Winthrop 1 of 3 priced rows at R19 and 4 of 7 at R20, Providence 5 of 5 at R20.
- **Winthrop, R19** (read 22:03:10Z, overlay written 22:02:49Z): the WNCAAB re-sim tick at 22:00:44Z listed 2 live games instead of 3, and the next at 22:02:56Z listed 4.
  - The builds at 22:00:47, 22:02:00 and 22:02:37 carried one game with only its pregame lane (`index_why`: `skipped_no_accepted_lane` 1, `sources_seen` `pregame_only` 1). Its rows were withheld as `no_live_gameline_projection` (7-8).
  - Winthrop's rows had no `live_total` in that overlay. The 22:03:44 build indexed 4 of 4.
  - **Likely cause, untested:** halftime. The game tipped at 21:00Z, so 22:00Z is about an hour in.
- **Winthrop, R20** (read 22:23:08Z, overlay 22:22:41Z): the lane had joined, so every totals row carried `live_total` 119.73. The build withheld every row: 32 on the 120 s quote-age ceiling and 11 on the WNCAAB quote-older-than-the-state rule (30 s).
  - The second read 10 s later (22:23:12 build) priced the 120.5 line (0.44 / 0.56; quotes 26 s and 59 s old). It left the 117.5 / 118.5 / 119.5 / 121.5 lines, whose quotes were 101-215 s old.
  - **By design.** The order rule is the user's 11-06 "Yes, do it here". WNCAAB keeps the strict state-fetch basis, and NCAAB moved to score-change on 11-08 (#762; `live_gameline_join.py`).
  - **Volume:** across the 38 WNCAAB builds from 21:55 to 22:25Z, the ceiling withheld 1,479 row-builds and the order rule 119.
- **Providence @ Arizona:** the scheduled tip was 22:05Z (4:05 PM).
  - At R19 (4:03 PM), `no_plays` was right: the game had not started.
  - Every NCAAB build from 22:05:42 to 22:23:11Z carried one game pregame-only (`no_live_gameline_projection` 9-13 rows). The 22:25:11 build indexed 6 of 6, and the helper's read at 22:24:14Z had Providence 5 of 5 modelled.
  - **So it had no live lane for about 19 minutes after its scheduled tip.** That fits a run of `no_plays`. Not checked: when ESPN's first play actually landed.
- **Monitor fix (`C:\tmp\railmon\dash\dash_update.py`, not the repo):** a re-simmed game with priced rows but none modelled now gets one of three labels.
  - `resimmed_model_by_helper_read`: the helper's later read had the model, so the gap is timing between the two reads.
  - `resimmed_lane_joined_rows_withheld`: `live_total` is on the rows but no probability, so the per-line gates withheld them.
  - `resimmed_no_row_model` (the join-defect flag) / `resimmed_few_priced_rows`: neither of the above.
  - **Re-run on R19 / R20 into a throwaway day file:** both games read `resimmed_model_by_helper_read`. With the helper's Winthrop count zeroed, Winthrop R20 read `resimmed_lane_joined_rows_withheld` (live_total on 5). Today's `rows_2026-11-24.jsonl` was not written. Ticks from 4:43 PM carry it.

## DAILY SUMMARY — Tue 11-24 (day 10), closed 1:12 AM CST 11-25

The Windows task took 44 readings, every 20 min from 10:03 AM to 12:43 AM CST. One tick failed: at 6:03 PM `d4metrics` returned rc -1, so that tick wrote no row. Readings ran every 20 min through the last 90 min of the slate. POP_START is 16:00Z. Flags are graded on their first sighting, against the finals by date (`C:\tmp\railmon\grade_2026-11-24_out.json`).

This was the first slate after the 11-24 window batch (16 changes, 2:30 AM). Every reading ran on fleet head `76a006f45`.

At the grade, two NCAAB games were still live: Gonzaga @ Kansas St and Colorado @ Stanford. Neither had a graded flag, because the rail rolled to 11-25 at midnight. 9 flags were skipped (5 no probability, 2 team unmatched, 2 no score).

### The grade

| bucket | flags | games | W-L-P | hit | fair | hit − fair, 90% CI (game-clustered) |
|---|---|---|---|---|---|---|
| **ALL** | 631 | 102 | 347-281-3 | **0.553** | 0.501 | [+0.011, +0.094] |
| P3 first reading: yes | 120 | 56 | 59-61 | 0.492 | 0.475 | [−0.055, +0.091] |
| P4 fair < 0.40 | 23 | 14 | 6-16-1 | 0.273 | 0.210 | [−0.081, +0.209] |
| P5 NCAAB full totals | 203 | 73 | 120-83 | 0.591 | 0.502 | [+0.010, +0.164] |
| sport: NCAAB | 505 | 74 | 285-220 | 0.564 | 0.509 | [+0.006, +0.106] |
| sport: NBA | 50 | 3 | 24-26 | 0.480 | 0.436 | [−0.055, +0.176] |
| sport: WNCAAB | 37 | 13 | 15-22 | 0.405 | 0.480 | [−0.195, +0.061] |
| sport: soccer | 27 | 9 | 17-7-3 | 0.708 | 0.508 | [+0.026, +0.371] |
| sport: NCAAF | 11 | 2 | 6-5 | 0.545 | 0.498 | (2 games) |
| sport: NHL | 1 | 1 | 0-1 | 0.000 | 0.314 | (1 game) |

- **The flags beat their fair price for the 7th day in a row (11-18 to 11-24), and for the 3rd day the CI clears 0.**
  - It was the biggest slate yet: 631 flags, against 382 on 11-23.
  - The model's mean p was 0.600 against a 0.553 hit, so it is ~5 pp over-confident on its own side (#847). On 11-23 that gap was ~4 pp.
- **Full-game markets carried it.**
  - Spreads 0.593 vs 0.494 (191 flags, CI clear of 0); totals 0.571 vs 0.497 (260 flags, CI clear of 0).
  - The segment markets (halves and quarters) were below fair: spreads 0.389 vs 0.483 (36 flags), totals 0.465 vs 0.498 (99).
  - **Segment spreads were below fair on 4 of the last 5 days.** Pooled 11-20..11-24 (point estimate, not clustered): 0.413 vs 0.450 over 225 flags. That is evidence for per-line calibration (#847), never a gate.
- **NCAAB full-game totals:** the unders went 0.620 (150 flags) and the overs 0.509 (53). The flagged lines went over 84 of 203 times.
- **NBA** had only 3 games. Its long shots went 2-7 (0.222 vs 0.190).
- **WNCAAB** was below fair (0.405 vs 0.480, 13 games), within noise.

### Pre-registered verdicts (standing P1-P6, P8)

| # | prediction | result | verdict |
|---|---|---|---|
| P1 | 0 rail-card contradictions | 0 at all 44 readings (0 skew-consistent either) | **MET** |
| P2 | board publication gap median ≤ 600 s, none > 1,800 s, 5:30-10:30 PM | 57 publications, median **314 s**, max 536 s (8:59 PM), 0 over 600 s (`p2_boardpub.py`) | **MET** (11-23: median 384 s, max 901 s, 6 over 600 s) |
| P3 | first-reading flags at or below fair | 0.492 vs 0.475, +1.7 pp, CI [−0.055, +0.091] | **not falsified** (above fair by a hair, within noise) |
| P4 | long shots (fair < 0.40) at most fair + 2 pp | 0.273 vs 0.210, +6.3 pp, 23 flags, 14 games, CI [−0.081, +0.209] | **NOT MET on the point, within noise** |
| P5 | report NCAAB calibrated live full totals | 203 flags / 73 games, 0.591 vs 0.502; under 150 (0.620) / over 53 (0.509); the flagged lines went over 84 of 203 | report |
| P6 | 0 pregame NCAAB / WNCAAB totals flags | 0 at all 44 readings | **MET** |
| P8 | score floor: 0 college calibrated full totals below the score | **4 of 3,883** rows, all at R30 (8:03 PM), all Samford @ Georgia Tech | **timing, not the floor** |

- **P8's 4 rows** were full-game totals lines 164.5 / 165.5 with `live_total` 165.0, while 166 had been scored.
  - The chip read H2 0:51, 90-76. The chip's own newer re-sim (as of 02:02:00Z) had a final total of 167.3, above the score.
  - So the rows were priced from a re-sim older than the last basket, in the last minute of regulation. That is the 11-20 pattern, not a floor fault.
  - The quote ages (234-879 s) are the book quotes'.
  - The game had **0 live bets** (`live_bets_for.py` on the event id and on both team names).

### What the day found

- **Change G (#854, the I-29 orientation join) works over a full evening.**
  - 9 of the 10 college games whose lane was REVERSED against the rows carried a live model, at 44 of 50 game-readings. On 11-23 it was 0 of 12 games (0 of 162 game-readings 11-20..11-23).
  - The 10th was WNCAAB Arkansas @ High Point, refused for `no_margin_anchor`, a different cause.
  - The 6 readings without a model were that game's 3 plus 3 `key_player_out` refusals (Bellarmine @ Georgia Southern, Oregon St @ San Francisco), which are deliberate.
- **The WNCAAB `espn_display` name gap cost 0 all evening** (the latent gap from the 11:03 AM follow-up above).
  - The only WNCAAB `not_in_resim` readings were Alcorn St @ Tenn-Martin at 11:03 AM (a key-player refusal) and DePaul @ Loyola (Chi) at 7:03 PM.
  - DePaul @ Loyola tipped at 7:00 PM; the 7:02:31 PM snapshot did not have it yet. It carried a model from 7:23 PM on.
- **Change O, R-K: P-E3 MET** (below).
- **Sweeps refused rose to 192 of 454 (42%), all `lane_busy`;** 11-23 had 72 of 279 (26%).
  - #851 made the live-odds loop faster (iteration p90 123 s, against 299 s), so it attempts sweeps more often and finds a busy lane more often.
  - Accepted sweeps rose from 207 to 262, and #851's per-sport attempt gap was PREDICTED (R-D, main `c021089b3`).
- **Games with no live model, as unique games** (38; 36 on 11-23):
  - soccer `competition_not_modelled`: 8 Champions League matches, by design (the #699 NO-GO gate);
  - WNCAAB `no_margin_anchor`: 4;
  - `pbp_score_mismatch`: 4;
  - `key_player_out`: 4, deliberate;
  - NCAAB `no_plays`: 3 (Ohio @ New Mexico St, 4 readings);
  - `not_in_resim` at tip-off: 3;
  - `resimmed_no_row_model`: 3, one or two readings each. Winthrop @ James Madison is explained in the block above.
  - NHL `in_intermission`: 1; NCAAF `resimmed_lane_joined_rows_withheld`: 1; NCAAB `regulation_over`: 1.
- **A chip-less WNCAAB card,** "Kansas Jayhawks @ Nebraska Cornhuskers" (2 pregame rows), at 8 readings from 10:03 AM to 1:43 PM.
  - The real game was Kansas City Roos (UMKC) @ Nebraska, 7:00 PM. Some odds source spelled UMKC as Kansas.
  - The card was gone from 2:03 PM. Its live rows read "UMKC Kangaroos". Not chased (a lead).
- **After midnight:** the 12:03 AM reading counted 4 flipped cards on the new 11-25 slate (all pregame). They were gone at 12:23 AM. 11-23 had 12.
- Flags: 1 false (R39, 11:03 PM: VCU @ Colorado St moneyline, 300.4 s old against the 300 s limit, a 0.4 s edge) and 0 missed. Dark rows at most 4 (R14), all `board_cadence`. Overlay gaps 0 over 360 s all day.

### Owned readings

- **R-D (#851), 11:00 PM:** P1-P6 all PREDICTED; lane `polymarket-slate-off-odds-loop` CLOSED (main `c021089b3`).
- **R-G (#853), 11:20 PM:** LOAD CHECK MET, P1-P4 PREDICTED, P5 FALSIFIED, P6 WATCH (confounded by the 9:57 AM GC revert) (main `53cac5dd9`).
- **R-K (change O, P-E3): MET.**
  - `overlay_offdate_inplay` was `{}` in all 8 metrics files whose window starts 02:43Z..05:03Z (`m_auto_1124_33..40.json`), so no `soccer@2026-11-25` key appeared.
  - Overlay gaps were 73-141 s, with 0 over 360 s.
  - HOU @ SJ's rail card had 2-5 live rows in 2-3 markets at its 7 live readings. LAFC on 11-23 had 2 rows in 1 market.
  - Sent to session local_15f2d5e2 (delivered).
- **R-F (#850): qualified, P1/P2/P3 all PREDICTED.**
  - 38 core games were live at 7:03 PM, and refresh-worker did not restart in 5-10 PM.
  - 0 fingerprint-stage refusals, 0 exits, longest build gap 536 s.
  - Parent 8-10 PM p50 1,756 MB (11-23: 1,994).
  - It was change J's first evening, not a repeat evening.
  - Written to lane `board-split-memory-guard` (findings §20), since its session is archived.
- **R-B (#844 / CHANGE D): INTERIM.**
  - P1 PREDICTED on one sample (7 of 9, against 1.8% on 11-19). P4 NEITHER: the NCAAB stale share was flat, and WNCAAB's fell while priceable fell too.
  - P2 and P3 are owed. The lean tick never ran the sampler, so it now runs at every tick on 11-25 and 11-26, and the 11-25 close grades them (findings `2026-11-18_college_quote_age_text_max.md`).
- **R-H (#860, CHANGE M): owed.** St. Louis did not play 11-24. The first game is STL @ NYI, 6:00 PM CT 11-25; a one-shot runs the kit at 7:07 PM CST.

### Loads (11-24 slate)

- **2:30 AM:** the window batch, 16 changes in one drained down/up (`d845fe345..672a18e87`). It is a betting change (13 of the 16).
- **9:43 AM:** web: the `/rail-watch` route serves this page from the data root (`2b191302f`; not a betting change).
- **9:57 AM:** web: the GC tuning reverted to CPython's defaults (`76a006f45`; not a betting change).

### Open user decisions

- **#857** (web's worker recycle limit to 1,500 MB): unblocked by R-G. The user said "Yes, after #853" on 11-20; when its drained restart runs is their call (asked 11:20 PM 11-24).
- **R-H at 7:07 PM 11-25:** on MET, whether to close lane `nhl-live-join-stl-alias` is the user's call.
- The next betting-change window is 12-08.
