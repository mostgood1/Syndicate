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
