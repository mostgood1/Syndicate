# Findings 2026-09-01 — Orphan stash census: all 22 remaining stashes verified, recovered where needed, dropped

Lane `orphan-stash-census`, session fbf1a34b. `[USER AUTHORIZATION 2026-09-01:
"census the other 22 the same way" — the same verify-then-clear treatment as
stash@{0] (9a384978, dropped earlier today) and the orphan sequencer.]`

**Outcome: every stash's cargo was proven landed, superseded, junk, or — in
four cases — genuinely unlanded and RECOVERED verbatim (two ledger files, two
appendices below) before dropping. Nothing was dropped unverified. The stash
stack is now EMPTY.**

## Method

Per stash: enumerate all three components (worktree = `stash^1..stash`, index =
`stash^1..stash^2`, untracked = `stash^3` tree), then per path compare blob
OIDs against origin/main (SAME-AS-MAIN), against main's history for that path
(`--find-object`; IN-MAIN-HISTORY / OLD-LANDED-VERSION = stale copy), by
directory policy (`data/` lossy mirror, `reports/` regenerated, venvs/caches),
or line-by-line against the full current ledger corpus (`.syndicate/*.md`,
`log/*.md`, `todo*.md`) for ledger files. Off-main BASES additionally checked
for branch reachability and content-equivalent twins on main, so no drop
orphans an unlanded base chain. Drops executed highest-index-first, each behind
a same-instant `rev-parse` identity check. Per the 08-31 FORBIDDEN rule,
`git cherry` was never trusted alone — every disposition below rests on blob
or line identity.

## Dispositions

| stash | sha | date | what it was | verdict / evidence |
|---|---|---|---|---|
| 0 | c56b6e67 | 08-21 | oddsapi quota counter | 1 path, `reports/` counter, self-described "generated output". DROP |
| 1 | df7442b5 | 08-18 | log snapshot pre-nhl-merge | 23/26 log lines existed NOWHERE (never committed, verified `-S`): the `model-sim-track` session-end checkpoint. **RECOVERED — Appendix A.** DROP |
| 2 | 67b44237 | 08-18 | ledger snapshot pre-merge | lanes_history +4452 and learnings_evidence +2106 fully present today; lanes.md 47 missing lines (its `nhl-model-owner` block WAS committed, `8aa90fe2`); state.md 25 missing lines are superseded-by-design state (samples self-marked WRONG/SUPERSEDED in the stash). **Missing sets preserved — Appendix D.** DROP |
| 3 | 2d7e8ffa | 08-18 | learnings snapshot pre-merge | 25+16 missing lines are the GENERATED rule-index header/anchors of that vintage plus since-edited prose. **Appendix D.** DROP |
| 4 | 96af1346 | 08-15 | todo.md snapshot | every added line (21) present in today's todo corpus. DROP |
| 5 | 64f05ef1 | 08-04 | odds-history WIP, base OFF main | cargo = reports/vendor-data classes; base chain (2 commits) blob-landed per path, todo.md delta 112/112 lines present today; base tip has main twin `49442bed`. DROP |
| 6 | 7d25fe58 | 08-01 | pre-surname-fix worktree | all 31 paths SAME-AS-MAIN / IN-MAIN-HISTORY / mirror / reports. DROP |
| 7 | 19d0e26a | 07-24 | NHL player-props draft | props modules + `write_props_recommendations_csv` LANDED on main; deleted test also deleted on main. 3 never-landed morsels recorded — Appendix C. DROP |
| 8 | 5c98c1fb | 07-21 | soccer picks WIP | entire delta = ONE import of `picks_rows`, which landed with 3 uses; main's cards.py is 2,692 lines past it. DROP |
| 9 | e707a96c | 07-20 | soccer/branding WIP + 8,313 untracked | 8,199 untracked = `vendor/mlb_bettingv2/.venv_x64` (a virtualenv). Team-branding + soccer code: 7/11 blobs IDENTICAL on main, 4 evolved. `soccersim_phase1_build_report.md` (tracked once, cleaned 07-14, stash holds fullest copy) **RECOVERED → `.syndicate/recovered_2026-07-20_soccersim_phase1_build_report.md`.** DROP |
| 10 | b1a766b0 | 07-19 | log5 combine A/B draft | `MLB_SIM_LOG5_COMBINE`/`_combined_log5` LANDED (4 hits in main's pitch_model). DROP |
| 11 | 0000a512 | 07-18 | board crash-fix draft + fix_notes | the "%-string confidence crashed board-publish" fix LANDED refined — main carries the stash's comment VERBATIM with `_number()` (strips `%`) instead of `_numeric_hint`. fix_notes entries never landed — **Appendix B.** DROP |
| 12 | 00ce838d | 07-16 | SmartSim2 NCAAF drafts | blend/projection/test/script all on main (evolved); plan doc blob IDENTICAL; assessment doc IDENTICAL; ensemble report absent anywhere → **RECOVERED → `.syndicate/recovered_2026-07-15_smartsim_ensemble_evaluation_report.md`.** fix_notes blob identical to stash 11's. DROP |
| 13 | 5438bd08 | 07-06 | "clean tree" sweep, 57,539 untracked | untracked = data/mlb_source 28,973 + TWO virtualenvs 16,562 + vendor 9,097 + reports + pytest/.tmp caches. Tracked code paths all IN-MAIN-HISTORY. DROP |
| 14 | 28c1cbfa | 07-06 | pre-rebase temp, base OFF main | base twin `aa4354e5` equivalent (drift = `daily-update.log` push-scratch); 3 untracked reports files. DROP |
| 15 | 08e0885b | 07-03 | report edits, base OFF main | base twin `ea14a260` equivalent (same scratch-file drift); 9 report/data paths. DROP |
| 16 | 44e3a04d | 06-29 | two 1-line doc tweaks | June-era web/worker split phrasing, superseded by `docs/ai_context/runtime_execution_model.md` + `worker_architecture.md`. Lines quoted — Appendix C. DROP |
| 17 | 72b7bdaa | 06-28 | pre-rebase temp, base OFF main | base twin `c58549f0` content-IDENTICAL (0 diff lines); 2 untracked data files. DROP |
| 18 | bf7f4202 | 06-22 | autostash (tools/ask.py) | 3-line WORKER CONTEXT addition to the ask prompt loader, never landed, main evolved 10 weeks without it. Quoted — Appendix C. DROP |
| 19 | cb1b7163 | 06-05 | copilot clean-tree (tracked) | base 313 commits off main BUT cargo 100% contained in `recover/stash-intelligence`/`recover/stash-manifests` tip `601f9d3c` (0 differing paths) — the June recovery branches survive the drop and remain the owners of that thread. DROP |
| 20 | 6e3be28a | 06-05 | copilot clean-tree (untracked) | same recovery-branch containment; untracked = tmp_browser/tmp_archives scratch + 1 mirror file. DROP |
| 21 | 7bb3ea4b | 05-30 | manifest temp pre-revert | 4 paths, all reports-manifests class. DROP |

**Cross-cutting notes.** (1) The dominant pattern is the same one the orphan
sequencer and stash@{0} showed: sessions stash, land the same content minutes
later via another path, and never clean up. (2) Six stashes sat on off-main
bases from the deploy-branch era; every base was either twinned on main or held
by the June `recover/*` branches — no drop orphaned unlanded commits. (3) The
two virtualenvs and the 28,973-file data sweep inside stashes 9/13 are why the
stash stack weighed what it did; none of it was ever content.

## Appendix A — recovered: `model-sim-track` session-end checkpoint (stash@{1}, log/2026-08-18.md, never committed)

```

### `model-sim-track` — CHECKPOINT (DELTA 14, SESSION END)

**THREE DEPLOYS, ALL GATES PASSED LEGITIMATELY** (no forced claim; the one
break-glass was on web, user-authorised, and justified by a substitute
measurement rather than a widened threshold):

    web             055dfc67  22:54:51Z  five sim artifacts IN PRODUCTION, read back BY CONTENT
    refresh-worker  3d945f04  01:45:44Z  the engine set
    refresh-worker  6966753e  02:02:56Z  the roster-rebuild gate

**THE STALE-PARENT TRAP, CAUGHT THREE TIMES.** Every worker deploy re-cut from
the LIVE SHA. `a1235755` would have reverted basketball's `#467`; `c588e184`
would have reverted my OWN engine set 17 minutes after landing it. **Cutting
from live is the habit that caught all three.**

**ARMED: NO. USER DECISION — wait for the CT rollover**, since tomorrow's date
has no `roster_objs/` and rebuilds free. Taken on CORRECTED numbers: I had said
arming it needed a `render.yaml` edit + `blueprint_sync` across three services;
it is **one key on one service** via the per-service env endpoint. **The
overstatement made the cheap option look expensive.**

**SHIPPED != WORKING, and the ledger says so.** The gate only makes a rebuild
REQUESTABLE. Nothing about the sim's inputs changes until a rebuild runs.

**BLOCKED AT SESSION END:** one `deploys.md` edit uncommitted — another session
has `.git/MERGE_HEAD` open with a conflict in `learnings.md`. **Not mine to
resolve.** Edit verified on disk; watcher `bj1uvjalm` waits for the merge, and
the commit must stage `deploys.md` ALONE — their resolution must not ride along.
My four learnings entries verified still present under the in-progress merge.

**OPEN:** `conditional_arsenal > 0%` from `sim_input_report_*.json` after the
rollover — the first end-to-end verification of the whole chain, costing nothing
but waiting. Worker still off main (63 vs 420, ten conflicting files); deferring
compounds.
```

## Appendix B — recovered: docs/fix_notes_log.md entries of 2026-07-15 (stashes 11+12, identical blob; the file went dormant 07-14 and these never landed)

```
# 2026-07-15 - SmartSim 2.0 NFL profile frozen as Production Candidate after corrective pass
- Symptom: Four stable validated biases remained (FG attempts -2.2pts, giveaways -3.3pts, plays/drive +0.7, Q2 -1.5) before the profile could freeze.
- Root cause: Residual proxy-era conservatism in kick-attempt and giveaway weights, plus an under-powered two-minute drill.
- Fix: Raised in-range FG attempt probability (0.88-0.97) with a 50% long-range fringe, per-play turnover weight to 0.095 base, more neutral 4th-down go-for-its, red-zone TD boost trimmed to 0.33, explosive-play weight up, and a sharper two-minute drill (explosive x1.60, TD +0.04).
- Validation: 19/19 tests; pooled truth: punt 35.0% vs 35.1%, TD 23.1% vs 22.0%, FG attempts 18.0% vs 18.4%, giveaways 14.8% vs 17.1%, all outcome shares within 1.7pts; three-season fold re-run preserved validation structure with FG/giveaway fold errors down ~30% and no new error beyond the ~0.02-0.05 seed-noise floor.
- Follow-up: Known-bias ledger frozen with the profile: FG attempt mix (long-attempt surplus), TOD 4.0% vs 5.8%, plays/drive convention gap, Q2/Q4 hurry-up shape — revisit only with score/time-conditioned 4th-down modeling or play-count convention alignment.

# 2026-07-15 - SmartSim 2.0 recalibrated against NFL historical truth; proxy-era targets partially reversed
- Symptom: The simulator was tuned to proxy fictions (punt 59%, turnover 0.4%), so its most "calibrated" behaviors overshot punts by 7 points and suppressed giveaways to roughly half of reality.
- Root cause: Iterations 4-6 optimized against fabricated benchmark rows; the truth layer showed punts should fall (35.1% real) and turnovers should roughly double (17.1% incl. downs).
- Fix: Added `calibration/truth_audit.py` (evaluates the standard 532-game workload against the adapted HistoricalTruthSnapshot), stopped crediting punt net yards to drive yardage, restored per-play turnover weight (~0.07 base), added neutral 4th-and-short go-for-it with real conversion attempts on declined kicks, raised FG attempt volume (fringe 53-55yd kicks, 0.85-0.97 in range, red-zone TD boost 0.55 -> 0.36), and sharpened the two-minute drill (explosive x1.45, 90s urgency-kick window).
- Validation: 19/19 smartsim2 tests; final truth evaluation: possessions 21.69 vs 21.66, totals 44.15 vs 45.13, drive seconds 169.6 vs 166.2, punt 37.2% vs 35.1%, TD 23.5% vs 22.0%, all seven outcome shares within 2.7 points; every metric <= 0.293 normalized error vs real data.
- Follow-up: FG volume (13.0% vs 15.7% made) and giveaway mix (13.8% vs 17.1%) are the top genuine gaps; add score/time-conditioned 4th-down decisions and run the 2023-24 calibrate / 2025 holdout split before declaring a Historical Truth Candidate.

# 2026-07-15 - SmartSim 2.0 historical truth layer replaced the fabricated proxy benchmark rows
- Symptom: Calibration had hit the proxy-benchmark ceiling; the largest remaining errors (turnover 0.4%, punt 59%, plays/drive 4.05, red-zone 43.1%) were fabrications of the proxy construction, so further tuning would have optimized toward fiction.
- Root cause: The proxy benchmark synthesized drives from team-week aggregates; no real drive/play-level history was mirrored locally.
- Fix: Added `smartsim2/historical_truth/` (contract, NFL loader, snapshot builder). Loader caches nflverse PBP 2023-2025 to `data/nfl_source/historical_truth/` (nfl_data_py preferred, direct release download fallback since Windows ARM64 cannot build pyarrow/nfl_data_py deps). Builder produced 17,677 real drives / 816 games; `HistoricalTruthSnapshot.to_calibration_snapshot()` adapts into the existing calibration contract without touching the simulator.
- Validation: 3 new truth-layer tests plus full smartsim2 suite = 19/19 passing; truth metrics measured: punt 35.1% (proxy said 59%), turnover 11.1% (proxy 0.4%), TOD 5.8%, missed FG 2.7%, end-of-half 7.4%, plays/drive 5.93, RZ conversion 85.5%, totals 45.13.
- Follow-up: Iteration 7 should recalibrate against the truth snapshot — restore turnovers upward (sim 6.1% vs real 11.1%), raise made-FG attempts (10.7% vs 15.7%), reduce punts (~42% vs 35.1%), close Q2 gap (11.76 vs 13.91), and fix the evaluator punt-yards crediting; NCAAF truth layer specified in smartsim_2_truth_layer_plan.md (CFBD drives/plays).

# 2026-07-14 - SmartSim 2.0 Iteration 6 added urgency states and removed fake quarter-boundary drive stops
- Symptom: 16.3% of simulated drives ended in silent clock stops spread evenly across quarters, flattening Q2/Q4 scoring (10.75/9.29 vs 13.81/13.15 benchmark) and suppressing game totals.
- Root cause: Q1/Q3 stops were drive fragmentation (advance_quarter preserves the possession, so one real drive logged as two with a fake stop); Q2/Q4 offenses had no urgency model — 584 drives died silently in scoring range and 81% of halves ended with no two-minute push.
- Fix: Added explicit urgency states (neutral, two-minute, four-minute, trailing, halftime preservation, end-game preservation) in situation_model.classify_urgency; hurry-up clock consumption (~0.09x, implicit timeouts/spikes) and preservation clock draining (0.30x) in play_simulator; urgency field goals (any down, <= 60s, in range) and Q4 trailing 4th-down go-for-it in drive_simulator; merged Q1->Q2/Q3->Q4 carryover drive fragments in game_simulator drive logs.
- Validation: Full smartsim2 suite 16/16 passing; 532-game calibration: stop share 16.3% -> 9.7% (remainder majority kneel-out preservation), Q4 scoring 9.29 -> 12.17, totals 39.40 -> 43.48, TD 25.6% vs 24.5%, possessions 20.55 vs 21.11, punt share preserved at 42.4%.
- Follow-up: Remaining calibration bounds are proxy-benchmark encoding limits (0.4% turnovers, zero stops, 4.05 plays/drive); mirror true play-by-play drive data before tuning against those rows again.

# 2026-07-14 - SmartSim 2.0 Iteration 5 exposed the 100% red-zone conversion as an evaluator tautology
- Symptom: Red-zone conversion reported 100% across all calibration iterations, and scoring was far below benchmark (TD 14.8% vs 24.5%, totals 28.25 vs 46.24) despite calibrated possessions and punts.
- Root cause: `summarize_simulation_outputs` counted a red-zone entry only when the drive scored, so conversion was definitionally 100%; separately, only 30.5% of drives reached true FG range because series conversion ran at 40.9% (real offenses ~65-70%), so the scoring gap was opportunity creation, not finishing.
- Fix: Measure red-zone entries from actual drive-step field position (fp >= 75), raise series conversion (stronger gains, lower incomplete/sack/turnover leak), reduce the red-zone per-play TD boost so drives stall into the full 4th-down outcome family, stiffen scoring-zone defense for FG settles, and raise in-range FG attempt probability.
- Validation: Full smartsim2 suite 16/16 passing; 532-game calibration: TD 22.5%, totals 39.40, possessions 21.33 vs 21.11, red-zone conversion honestly measured at 83.0% with real failures; scoring-opportunity rate 30.5% -> 42.8%.
- Follow-up: Iteration 6 should release the 16.3% clock-stop drive share via end-of-half urgency behavior, which structurally caps punt share (42.1% vs 59.0%) and FG volume.

# 2026-07-14 - SmartSim 2.0 Iteration 4 fixed field-wide FG range, unlimited downs, and fake red zone
- Symptom: 42.3% of simulated drives ended in field-goal attempts (benchmark 16.2%) with punts at 16.3% (benchmark 59.0%), and scoring was inflated ~50%.
- Root cause: `situation_model.py` flagged `field_goal_range` for any play with distance <= 12 anywhere on the field and `red_zone` for any distance <= 7, `play_simulator.py` sampled FIELD_GOAL_ATTEMPT on downs 1-3, and the GAIN branch repeated the down on non-conversions so the offense had unlimited downs and drives never stalled into punts.
- Fix: Define true FG range (yardline >= 65, kick <= 52 yds), gate play-level FG attempts to 4th down in range, make the drive-level 4th-down decision FG-first-in-range with punt as the neutral default, use distance-based FG make probability, fix red_zone/goal_to_go to real field-position definitions, advance downs normally on non-converting gains, and rebalance GAIN/incomplete/turnover/explosive weights for real down mechanics.
- Validation: Full smartsim2 suite 16/16 passing; 532-game calibration shows punts 53.9% (benchmark 59.0%), FG attempts 8.1%, possessions 22.86 vs 21.11 benchmark, drive seconds 160.2 vs 166.1.
- Follow-up: Iteration 5 must recover scoring share (TD 14.8% vs 24.5%, FG 6.6% vs 16.2%) via series conversion and a real red-zone outcome distribution instead of the 100% conversion constant.

# 2026-07-14 - SmartSim 2.0 Iteration 3 evaluation unblocked by turnover-on-downs zero-progress fix
- Symptom: The Iteration 3 calibration report never generated; the 532-game proxy evaluation hung deterministically on game 14 (`2025_01_SF_SEA`) while a single-game probe completed fine.
- Root cause: The 4th-down fallback branch in `syndicate/features/football/sim_engine/smartsim2/drive_simulator.py` returned `TURNOVER_ON_DOWNS` without consuming clock or flipping possession. For field position in [88, 94) both `_punt_decision` (>= 88 guard) and `_field_goal_decision` (< 94 guard) return False deterministically without consuming RNG, so the game loop re-simulated the identical state forever.
- Fix: Make the turnover-on-downs branch a real possession exchange: consume clock, flip the field, flip possession owner, advance drive/possession indices, and log a proper `PossessionStepResult`.
- Validation: 10 focused smartsim2 tests passed (`test_smartsim2_drive_simulator`, `test_smartsim2_play_simulator`, `test_smartsim2_calibration`, `test_smartsim2_possession_state`), and the full 532-game evaluation completed in ~95 seconds producing `smartsim_2_calibration_iteration3_report.md`.
- Follow-up: Any future decision-gate change must preserve the invariant that every drive-loop branch either consumes clock or changes possession; a zero-progress branch is a deterministic hang.
```

## Appendix C — the never-landed morsels (quoted in full; main evolved past each)

**stash@{7}** `odds_refresh_tracking.py` — one-line key rename, would break today's consumers of `"line"`:
```
-  "line": _json_safe(line_snapshot),
+  "line_fields": _json_safe(line_snapshot),
```
**stash@{7}** `timezone.py` — two timestamp keys never added to `normalize_timestamped_payload`:
```
+  "capturedAt",
+  "captured_at",
```
**stash@{7}** `tests/test_odds_refresh_tracking.py` — `market_key = next(key ... if "selection=" in key)` widened to `next(iter(history_payload["markets"]))` for props rows carrying over/under on one row; coupled to the props draft whose landed form solved it otherwise.

**stash@{16}** two June doc lines (superseded by the ai_context runtime/worker docs):
```
+- The Render web service now reads the checked-in repo `data/` and `reports/` trees, while the background worker services keep the persistent disk for refresh and write paths.
+- the background worker services own the mounted disk and refresh/write paths
```
**stash@{18}** `tools/ask.py` — WORKER CONTEXT block never added to the ask prompt loader:
```
+WORKER CONTEXT:
+{load("worker_architecture.md")}
+
```

## Appendix D — ledger lines from the 08-18 snapshots absent from today's corpus

Preserved verbatim for the record. Assessment: lanes.md lines were committed
once (`8aa90fe2`) then trimmed/evolved; state.md lines are superseded state the
file is DESIGNED to overwrite (the largest block is self-marked SUPERSEDED);
learnings lines are a generated index header of that vintage plus since-edited
prose. Nothing here contradicts today's ledger.

### stash@{2} `.syndicate/lanes.md` (47)
```
### nhl-model-owner — OPEN — opened 2026-08-18 — session: nhl-model-owner
- Goal: NHL sim engine reaches the same deep-dive rigor MLB (`mlb_sim_engine_reference.md`
  + `sim_input_checklist.py`) and soccer (`soccersim_phase1_build_report.md` +
  `soccer_sim_input_checklist.py`) already have — a pipeline-trace/input-provenance
  doc, a CONSUMED-vs-POPULATED gating script, and the live findings those produce
  fixed, not just documented. **Testable outcome:** `python scripts/nhl_sim_input_checklist.py`
  exits 0 (or documents/accepts every remaining gap explicitly); `elo_rating` is
  either populated end-to-end or its read site is removed; NHL's Phase 3b
  calibration report matches what `calibration_profile.py`/its versioned-profile
  artifact actually resolves to in production.
  `scripts/nhl_sim_input_checklist.py` (new), `docs/ai_context/hockeysim_engine_reference.md`
  (new). The shared artifact-publisher allowlist module (its own name
  deliberately not repeated here as a slash-bearing token -- see the file's
  own path-extraction mechanism this triggered) is REMOVED from this claim as
  of 2026-08-18 ~15:5xZ; see this lane's RELEASED note further below for the
  full record, which for the same reason also avoids repeating the literal
- Collision check run 2026-08-18 against all OPEN lanes: no active lane claims
  `syndicate/features/nhl/sim_engine/**`. `convergence-phase5-profile-seam` touched
  `hockeysim/calibration_profile.py` but is SHIPPED (`964c89a4`) and session-closed
  2026-08-17 — its `load_versioned_profile` seam is a no-op until an artifact
  exists, which this lane may be the one to create. Not a live conflict.
- Hypothesis: n/a (mixed diagnostic + build) — sub-findings from the survey pass
  (elo_rating CONSUMED+unpopulated, xG loader wired but unallowlisted and unfed,
  Phase 3b deltas absent from the live constant per todo.md + grep) are logged as
  hypotheses to confirm against Render before fixing, per `model_engine_standard.md`
  §3b (local-checkout absence is not proof of production absence).
- Falsification test: for each of the three findings above, if a Render check
  shows the field/file IS actually populated/allowlisted/applied in production,
  the finding is EXONERATED and the doc says so instead of "fixed".
- Verification: checklist script run against a fresh checkout exits documenting
  zero silent gaps; each fix has a stated production measurement in `deploys.md`
  if it required a deploy.
### basketball-model-owner — OPEN — **#461 FIXED AND PUSHED 2026-08-18 (`9075d3eb`, `9d60656d`): stale-schema cache guard was the real cause, not the producer; fix verified by direct invocation against real cached WNBA boxscores (14/14 columns, games 6-8/team). Mirror/production not yet regenerated — needs a refresh-worker deploy.** inventory pass SHIPPED (#460/#461/#462 filed) — opened 2026-08-18 — session: basketball-model-owner
- Goal: Basketball's counterpart to the Modeling (MLB), Soccer, and Football sessions — bring the NBA/WNBA smart-sim engine (`vendor/wnba_betting_repo/src/wnba_betting/sim/smart_sim.py`, `syndicate/features/shared/basketball_props_*.py`) up to `docs/ai_context/model_engine_standard.md`: a CONSUMED x POPULATED gating input checklist over `dataclasses.fields()` (never a name grep), a documented pipeline-trace reference doc (file:line per hop), and a first reachability audit of the known silent no-sampling fallback (`basketball_props_smart_sim` -> `_simulate_smart_game_local` on bare `except`, per `todo.md` #440). NCAAB has no sim engine at all — document that explicitly as a design gap, not an input-population gap, and do not attempt to backfill it inside this lane. Follow-on: fix `#461` (WNBA `team_advanced_stats.games` never populated) at its root cause, not just the symptom.
- Files: scripts/basketball_sim_input_checklist.py (new), scripts/nba_sim_input_checklist.py / scripts/wnba_sim_input_checklist.py (new, if a per-sport split proves necessary), docs/ai_context/basketball_sim_engine_reference.md (new), docs/ai_context/basketball_model_inventory.md (new). Read-only over syndicate/features/shared/basketball_props_smart_sim.py, basketball_props_edges.py, basketball_props_predictions.py, basketball_props_calibration.py, basketball_market_board.py, basketball_live_artifacts.py, basketball_boxscores_history.py, basketball_props_onnx.py, syndicate/features/nba/**, syndicate/features/wnba/**, syndicate/features/ncaab/**. **Write access added 2026-08-18** (widened for the #461 fix): `vendor/wnba_betting_repo/src/wnba_betting/cli.py`, `vendor/nba_betting_repo/src/nba_betting/cli.py` (`_ensure_team_advanced_stats_asof`'s cache-freshness guard only — same latent bug in both leagues' identical code). **#462 note (path deliberately not repeated as a slash-bearing token below -- see #462's own entry for why: this exact bullet, while it matched the guard's Files-block continuation scan, is what re-claimed the shared artifact-publisher allowlist module for THIS lane and blocked a sibling session):** first attempt was blocked by `nhl-model-owner`'s claim; that lane released it and this lane applied its own fix directly (see #462 below for the actual patterns and outcome). Does NOT touch board_enrichment.py, run_live_odds_refresh_worker.py, or wnba_fixture_identity.py (held by wnba-live-tier / wnba-phase2-migration). **Write access added 2026-08-18** (mirror-desync half of `#461`): the two 0-byte WNBA `team_advanced_stats_2026.csv` mirror copies (`data/wnba_source/source_artifacts/data/processed/` and `data/wnba_source/data/processed/`) — regenerating via direct invocation, same method already used for the asof-file half of this fix. Collision check: no other OPEN lane claims any `data/wnba_source/**` path (grepped `lanes.md`, clean).
- Hypothesis: basketball has the same silent-unfed-field shape MLB (#26 fields) and football (#457, 65 keys) both had, concentrated first in the known `_simulate_smart_game_local` fallback path. **Follow-on hypothesis (#461):** the WNBA `team_advanced_stats_*_asof_*.csv` files missing `games`/`source` are stale-schema leftovers that `_ensure_team_advanced_stats_asof`'s non-zero-size-only cache check treats as fresh forever, blocking regeneration under the current (post-`games`-column) code.
- Falsification test: the checklist runs clean (CONSUMED fields all POPULATED, no fallback triggers observed in a sampled window of real artifact reads) — hypothesis would be wrong and the lane's finding becomes "basketball is clean," not "basketball has an unfed surface." **#461 falsification:** if the stale WNBA CSV's header already contains `games`/`source` (i.e. the columns are present but empty, not structurally absent), the cache-guard theory is wrong and the real cause is elsewhere in the producer function itself.
- Verification: `python scripts/basketball_sim_input_checklist.py` (or per-sport variants) exits 0/non-zero on real production artifacts, with the alarm list and EXPECTED_SPARSE reasons documented in docs/ai_context/basketball_sim_engine_reference.md. **#461:** the checklist's Level 2 WNBA `games` alarm clears (or is measurably explained) after the cache-freshness fix, verified by actually invoking the fixed function, not by code inspection alone.
### repo-coordination — OPEN — **deployment, assignment and documentation. NOT any sport, model or engine.** — opened 2026-08-18 — session: repo-coordination
  - `.claude/hooks/` (deploy-guard, lane-guard, commit-guard, session-start)
  - `scripts/session_worktree.py`
  - `scripts/lane_identity_check.py`
  - `scripts/todo_id_reconcile.py`
  - `scripts/state_key_check.py`
  - `scripts/deploy_claim.py`
  - `docs/ai_context/session_isolation_protocol.md`
  - `.github/workflows/ci.yml`
```

### stash@{2} `.syndicate/state.md` (25)
```
## [web-preflight-dead-sample] CORRECTION — THE DEAD PREFLIGHT IS A DELETED EMITTER, NOT MISSING `psutil` `[2026-08-18]`
> **SUPERSEDED — this section's conclusion is WRONG and its own author retracted
> it in the section below, which carries the SAME subject key deliberately.**
> The emitter was not deleted; it is intact at `memory_observability.py:1952`.
> Retained verbatim because the retraction explains how the mistake was made
> (a `head -4` truncated grep read as exhaustive) and that reasoning is worth
> more than a tidy file. **Do not act on anything in this section.**
> Collapsing the two into one is owed work for whoever owns this subject —
> `state_key_check.py` now reports it, which is the intended behaviour.
## [web-preflight-dead-sample] RETRACTION — "THE EMITTER WAS DELETED" IS ALSO WRONG. CAUSE IS **UNKNOWN**. `[2026-08-18]`
> **THIS IS THE CURRENT TRUTH FOR THIS SUBJECT.** It shares its key with the
> superseded CORRECTION section above, so `state_key_check.py` reports the
> subject as stacked — deliberately, per this file's own rule that a second
> section on one subject is a defect to be seen rather than hidden behind a
> different slug. Collapse is owed by this subject's owner.
> **A FOURTH CAUSE HAS SINCE BEEN CLAIMED AND RETRACTED TOO** `[added 2026-08-18
> by lane `ledger-coherence-sweep`]`: `todo.md` `#465` asserted "no web code
> path emits `ALL_PROCESS_MEMORY`", confirmed by caller trace. Also wrong — web
> has a live path, `syndicate/app.py:37` →
> `start_intelligence_state_background_loop` →
> `intelligence_state.py:_diag_log_all_process_memory` (12 sites) →
> `memory_observability.py:1919 log_and_persist_process_memory` → `:1944` →
> `:1952`. It read as true because `app.py` contains zero occurrences of the
> callee — it *starts a loop* that calls it. **The tally in this section is now
> 4 wrong causes, not 3**, and its "do not add a fifth guess" stands.
```

### stash@{3} `.syndicate/learnings.md` (25) + `learnings_index.md` (16)
```
## Index — 407 rules `[generated]`
  the next session that commits the shared tree to carry your edit, and do not
  report that as a failure.** Verify by CONTENT on `origin/main`. Attribution of
  a ledger edit is not a property worth defending; LOSS is the only thing to
**THE DISTINCTION THAT WAS BEING MISSED, and it has different mitigations.**
Three events in one session were all labelled "absorption". Two were; one was
not, and calling it one implied a fix that does not exist:
    STAGED entry from the shared index. Measured twice: `lanes.md` header
    edits into `661cb3da`, and `scripts/archive_released_lanes.py` into
    `d46be8a0` (a commit a later reset then ORPHANED, leaving the file
    untracked again and the work recoverable only by noticing).
    commits the shared tree, and their commit contains your edit. Measured
    once: `state.md` keying landed inside `04e44610`, another session's
    checkpoint. My own worktree commit then rebased to a NO-OP -- 0 commits
    ahead of `origin/main`, because the content was already there.
    -> A worktree CANNOT prevent this and should not try. The edit has to be
       in the shared file to be live. This is shared state working correctly.
**WHY THE MISLABEL MATTERED.** It framed correct behaviour as a defect, which
points the next session at a mitigation (isolate harder) that cannot work, and
distracts from the one check that does: *did the content land, and is anything
lost*. Both were verified here by slug count on `origin/main` and by line
conservation against a backup — and nothing was lost in any of the three.
**THE COORDINATOR-ROLE VERSION OF THIS.** Reporting these as things that
happened, rather than managing them, is itself the failure mode. The
check — not a narration of the incident in chat, which does not survive the
---
## Index — 407 rules `[generated]`
- [2026-08-18 — FORBIDDEN: never apply a transform to a shared file by patching the transf…](#2026-08-18-forbidden-never-apply-a-transform-to-a-shared-file-by-patching-the-transforms-own-source-with-strreplace-session-football-model-owner)
**Rules and corrections — 339**
- [2026-08-18 — A DUPLICATED TERM PASSES EVERY CHECK THIS REPO HAS. A PLAUSIBILITY READ CA…](#2026-08-18-a-duplicated-term-passes-every-check-this-repo-has-a-plausibility-read-caught-it)
- [2026-08-18 — RULE: a union merge CANNOT carry a deliberate deletion. A collapse pushed…](#2026-08-18-rule-a-union-merge-cannot-carry-a-deliberate-deletion-a-collapse-pushed-through-one-is-undone-and-comes-back-bigger)
- [2026-08-18 — A VARIANCE-REDUCTION TRICK THAT CHANGES THE ANSWER IS NOT A VARIANCE-REDUC…](#2026-08-18-a-variance-reduction-trick-that-changes-the-answer-is-not-a-variance-reduction-trick)
- [2026-08-18 — RULE: a wiring gate must ask whether the payload is READ, not whether a pa…](#2026-08-18-rule-a-wiring-gate-must-ask-whether-the-payload-is-read-not-whether-a-payload-is-passed)
- [2026-08-18 — RULE: a zero from a LOCAL checkout is a statement about the mirror, never…](#2026-08-18-rule-a-zero-from-a-local-checkout-is-a-statement-about-the-mirror-never-about-production-i-filed-one-as-a-defect)
- [2026-08-18 — RULE: a guard that gates on IDENTITY fails to a total block when the ident…](#2026-08-18-rule-a-guard-that-gates-on-identity-fails-to-a-total-block-when-the-identity-holder-disappears-gate-on-state)
- [2026-08-18 — CHECK WHETHER A FIELD EXISTS BEFORE DECLARING IT](#2026-08-18-check-whether-a-field-exists-before-declaring-it)
- [2026-08-18 — OVERTURNED: "the ledger files were fine, just big" — session `football-mod…](#2026-08-18-overturned-the-ledger-files-were-fine-just-big-session-football-model-owner)
- [2026-08-18 — OVERTURNED: "a guard that is present is a guard that is working" — session…](#2026-08-18-overturned-a-guard-that-is-present-is-a-guard-that-is-working-session-football-model-owner)
- [2026-08-18 — RULE: before wiring ANY feature into a model, check whether the feature is…](#2026-08-18-rule-before-wiring-any-feature-into-a-model-check-whether-the-feature-is-computed-from-the-thing-being-predicted-ask-what-window-it-covers-not-what-it-is-named)
- [2026-08-18 — A TRUNCATED READING IS NOT A COMPLETE ONE](#2026-08-18-a-truncated-reading-is-not-a-complete-one)
- [2026-08-18 — A STALE-BUT-"RUNNING" SESSION IS INVISIBLE TO EVERY ORPHAN CHECK](#2026-08-18-a-stale-but-running-session-is-invisible-to-every-orphan-check)
- [2026-08-18 — RULE: a session worktree protects your INDEX, not your EDIT. Shared-file c…](#2026-08-18-rule-a-session-worktree-protects-your-index-not-your-edit-shared-file-carry-is-not-absorption)
```
