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
