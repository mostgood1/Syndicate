# 2026-11-26: Layer 2 rail monitor findings (lane `layer2-rail-monitor`)

The user said, 11-19 ~1:00 AM CST: "this should just be an always on monitor moving forward". Lean mode since 11-20: the Windows task `SyndicateRailWatch` takes every reading, and Claude runs the nightly close.

## Fleet-watcher flag: soccer FC Copenhagen @ Inter Club d'Escaldes "not_in_resim" at R13 and R14 (to 2:23 PM CST); read-only

- **Verdict: the monitor's own name miss, fixed. No fleet defect, cost 0.** The lens held the match: ESPN 401915738, uecl, spelled "F.C. København" @ "Inter D'Escaldes", `projection` null and `momentum.reason` `competition_not_modelled` (the #699 gate). Read from redis `soccer_live_lens.json` (generated 2:26:38 PM CST) with `C:\tmp\railmon\diag_1126_escaldes.py` (read-only, nice 19).
- **The cause was Copenhagen / København, not the apostrophe or the prefixes** (the watcher's guess). The home side already matched by the word-subset rule ("inter d'escaldes" inside "inter club d'escaldes"). The away side folded to "fc kobenhavn" against the rail's "fc copenhagen", and `team_aliases.chip_join_key` does not join them either.
- **Fixed in the monitor (`C:\tmp\railmon\p29_orient.py`, from 2:27 PM CST; repo copy `scripts/rail_monitor/p29_orient.py`).** `norm` maps native city names to the English ones word by word, on both sides, so it cannot split a pair that already matched: København, München, Köln, Praha, Beograd, București, Warszawa, Kiev, Athina, Wien, Moskva, Lisboa, Genève, Sevilla, Milano, Torino, Napoli, Roma, Firenze, Genova. It also folds curly apostrophes to straight ones.
- **Re-run at 20:27:50Z (2:27 PM CST):** the game reads `direct`, `competition_not_modelled` (uecl), like the other 17 live UEL/UECL games. 18 of 18 live soccer games matched the lens, 0 `not_in_resim`.
- The repo copy of `p29_orient.py` had not been refreshed since 11-22, so it also gains the 11-24 fixes (the ø fold, the UEFA `competition_not_modelled` reason, the `chip_join_key` fallback).
