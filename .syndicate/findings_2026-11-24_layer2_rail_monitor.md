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
- **Not checked:** WNCAAB Alcorn St @ Tenn-Martin read `not_in_resim` at R4 only (snapshot 11:04 AM). The cause is either a kickoff after the snapshot or a name miss.
