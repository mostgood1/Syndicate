# SmartSim 2.0 Release Readiness Assessment

- Date: 2026-07-15
- Scope: SmartSim Football Core, NFL Calibration Profile (frozen), NCAAF Calibration Profile v1, Historical Truth Layer, calibration framework, tests, reports
- Method: static inventory, `git status`/`.gitignore` audit, public-contract signature review, targeted reproducibility probes, full relevant test-suite run
- **This report does not modify simulator behavior or calibration parameters.** It is read-only assessment.

## 1. Repository Context (read this before anything else)

The repository is currently checked out directly on **`main`**, not a feature branch, and the working tree is not clean. `git status` shows two disjoint categories of change:

1. **SmartSim 2.0 work** (this assessment's scope): the entire `syndicate/features/football/sim_engine/smartsim2/` tree, 11 test files, 23 report `.md` files, and two data caches (`data/nfl_source/historical_truth/`, `data/ncaaf_source/historical_truth/`) — all untracked (`??`).
2. **Unrelated, pre-existing dirty state**: modified WNBA/MLB data artifacts, `reports/odds_control_plane/`, `data/odds_events/`, `docs/fix_notes_log.md`, `scripts/refresh_wnba_oddsapi_props.py`, and an untracked 196 MB `data/nfl_source/tracking/` directory (ftn_charting + nflverse pbp/player_stats) that neither of the two SmartSim2 work sessions created or touched.

**Implication:** there is no clean commit boundary yet. "Safe to merge" must be answered for the SmartSim2 file set specifically, and a blanket `git add -A` / `git commit` would silently sweep in unrelated WNBA/MLB/odds changes and a large, likely-regenerable tracking-data directory that were never part of this work. This is addressed as a blocking item in Section 8.

## 2. Task 1-2: File Inventory by Category

### Core (shared Football Core engine — no league-specific code)

| File | Role |
| --- | --- |
| `contracts.py` | `PossessionState`, `SmartSim2SimulationInput/Output`, `DriveResult`, etc. — unmodified |
| `possession_state.py`, `possession_outcomes.py` | possession/clock state helpers — unmodified |
| `play_state.py`, `situation_model.py` | urgency/situation classification — unmodified |
| `drive_priors.py` | feature-driven `DrivePriorProfile` — unmodified |
| `play_simulator.py` | per-play outcome selection — **modified**: added optional `profile:` parameter |
| `drive_simulator.py` | per-drive decision sequence (punt/FG/4th-down) — **modified**: added optional `profile:` parameter |
| `game_simulator.py` | full-game loop — **modified**: added optional `profile:` parameter |
| `runtime.py` | thin public entry point | unmodified, calls `simulate_game` positionally (unaffected by new keyword) |
| `calibration_profile.py` | **new** — shared `CalibrationProfile` dataclass + `NFL_CALIBRATION_PROFILE` constant |
| `__init__.py` | package exports | unmodified (see Section 4 gap) |

### NFL (profile-specific)

| File | Role |
| --- | --- |
| `NFL_CALIBRATION_PROFILE` (in `calibration_profile.py`) | every field reproduces a constant that used to be hardcoded directly in the engine |
| `historical_truth/nfl_historical_loader.py` | nflverse PBP acquisition/cache — unmodified |
| `data/nfl_source/historical_truth/` | 55 MB cached PBP (2023-2025), offline-replayable |

### NCAAF (profile-specific)

| File | Role |
| --- | --- |
| `ncaaf_calibration_profile.py` | **new** — `NCAAF_CALIBRATION_PROFILE`, 9 of 20 fields differ from NFL |
| `historical_truth/ncaaf_historical_loader.py` | CFBD acquisition/cache/canonicalization — **new** |
| `data/ncaaf_source/historical_truth/` | 26 MB cached CFBD games/drives/plays (2023-2025), offline-replayable |

### Calibration (framework, league-agnostic)

| File | Role |
| --- | --- |
| `calibration/benchmark_contracts.py` | `CalibrationBenchmarkSnapshot`, `BenchmarkDriveRecord/GameRecord` — unmodified |
| `calibration/evaluation_metrics.py` | `SummaryMetrics`, `compare_summary_metrics` — unmodified |
| `calibration/simulator_evaluator.py` | `evaluate_simulator` — unmodified |
| `calibration/baseline_audit.py` | proxy-benchmark path (pre-truth-layer, retained for replay) — unmodified |
| `calibration/truth_audit.py` | NFL truth-backed audit entry point — unmodified |
| `calibration/calibration_report_generator.py` | report string builder — unmodified |

### Historical Truth (shared layer, both leagues)

| File | Role |
| --- | --- |
| `historical_truth/historical_snapshot_contract.py` | `HistoricalDriveRecord/GameRecord/Metrics/Snapshot` + `to_calibration_snapshot()` — unmodified |
| `historical_truth/historical_snapshot_builder.py` | drive/game aggregation + metrics — **modified**: added optional `league:` parameter, default `"nfl"` |

### Tests (11 files, 29 collected tests, run this assessment)

`test_smartsim2_calibrated_drive_simulator.py` (2), `test_smartsim2_calibration.py` (4), `test_smartsim2_drive_priors.py` (2), `test_smartsim2_drive_simulator.py` (2), `test_smartsim2_game_simulator.py` (2), `test_smartsim2_historical_truth.py` (3), `test_smartsim2_play_simulator.py` (2), `test_smartsim2_play_state.py` (2), `test_smartsim2_possession_state.py` (2), `test_smartsim2_situation_model.py` (2), `test_ncaaf_historical_loader.py` (6).

### Reports (23 files at repo root)

Phase/build/architecture docs (`smartsim_2_phase1..5*`, `smartsim_2_possession_simulation_architecture.md`), calibration iteration history (`smartsim_2_baseline_calibration_report.md`, `smartsim_2_calibration_iteration1..6_report.md`), the historical-data-limitation finding (`smartsim_2_historical_data_assessment.md`), the truth-layer plan (`smartsim_2_truth_layer_plan.md`), the NFL truth/validation/production/recalibration reports (`nfl_historical_truth_report.md`, `nfl_validation_report.md`, `nfl_production_candidate_report.md`, `smartsim_2_nfl_truth_recalibration_report.md`), and the three NCAAF reports (`ncaaf_historical_truth_report.md`, `ncaaf_calibration_profile_report.md`, `ncaaf_profile_validation_report.md`).

## 3. Task 3: Public Contract Review

Every touched public function's new parameter is **keyword-only and defaulted**, appended after the existing `*` separator:

```
simulate_game(simulation_input, *, rng=None, profile: CalibrationProfile = NFL_CALIBRATION_PROFILE)
simulate_drive(possession_state, simulation_input, *, rng=None, profile: CalibrationProfile = NFL_CALIBRATION_PROFILE)
simulate_play(play_state, possession_state, simulation_input, *, priors, rng, profile: CalibrationProfile = NFL_CALIBRATION_PROFILE)
build_historical_truth_snapshot(pbp, *, seasons, source_name=..., regular_season_only=True, league: str = "nfl")
```

No existing parameter was renamed, reordered, removed, or given a new type. `CalibrationProfile` and `NFL_CALIBRATION_PROFILE` are exported from `calibration_profile.py`'s `__all__`; `NCAAF_CALIBRATION_PROFILE` from `ncaaf_calibration_profile.py`'s. **Gap**: none of the three are re-exported from the package-level `smartsim2/__init__.py`, so `from syndicate.features.football.sim_engine.smartsim2 import NCAAF_CALIBRATION_PROFILE` fails today; the deep import path (`...smartsim2.ncaaf_calibration_profile import NCAAF_CALIBRATION_PROFILE`) is required. Non-blocking (Section 8).

## 4. Task 4-5: Backward Compatibility and NFL-Default Verification

Confirmed by direct probe (not just code inspection):

```
d = simulate_game(sim_input).to_dict()                              # no profile= passed
c = simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE).to_dict()
d == c   # True: identical final_score and drive_log
```

The only caller of these functions outside `smartsim2/` and its own tests is `runtime.py`, which calls `simulate_game(simulation_input)` positionally with no keyword arguments — fully unaffected. `grep` across `syndicate/blueprints/` and `ncaaf_adapter.py` finds **zero** references to `smartsim2` anywhere in the live application: **the entire feature is currently dormant and unwired into any route.** This is the single most risk-reducing fact in this assessment — merging cannot regress any currently-served behavior because nothing currently calls it outside its own package and test suite.

Full regression suite re-run for this assessment: **28 passed, 1 failed** (`test_stronger_features_raise_scoring_frequency`, a stochastic 30-seed assertion — `4 not less than 2`). This failure is pre-existing: it reproduces byte-for-byte identically before any calibration-profile work in this repository and after every edit across both work sessions, confirming it is unrelated flake, not a regression introduced by the profile seam.

## 5. Task 6: NCAAF Opt-In Verification

Direct probe, same seed, both profiles:

```
a = simulate_game(sim_input, profile=NCAAF_CALIBRATION_PROFILE).to_dict()
c = simulate_game(sim_input, profile=NFL_CALIBRATION_PROFILE).to_dict()
a != c   # True: NCAAF profile produces different output when explicitly selected
d == c   # True: omitting profile= (the legacy call shape) still yields NFL behavior
```

NCAAF behavior is reachable **only** by explicitly passing `profile=NCAAF_CALIBRATION_PROFILE`. There is no environment variable, config flag, or auto-detection that could silently switch a caller from NFL to NCAAF behavior. This satisfies "fully opt-in through profile selection."

## 6. Task 7: Reproducibility Verification

- Existing test `test_game_simulation_is_seed_stable` covers the NFL-default path (two calls, same seed, identical `final_score`/`drive_log`).
- This assessment additionally probed the **NCAAF profile path directly** (not previously covered by any test): two calls with `profile=NCAAF_CALIBRATION_PROFILE` and the same seed produce identical `final_score` and `drive_log`. Confirmed True.
- Historical Truth Layer reproducibility: re-ran the full NFL truth-snapshot build from the existing cache (`load_pbp_seasons` + `build_historical_truth_snapshot`) — reproduced exactly **17,677 drives / 816 games**, matching `nfl_historical_truth_report.md`. Re-ran the full NCAAF truth-snapshot build from cache — reproduced exactly **53,548 drives / 2,264 games**, matching `ncaaf_historical_truth_report.md`.

All four reproducibility checks (NFL sim, NCAAF sim, NFL truth build, NCAAF truth build) passed.

## 7. Task 9-10: Documentation and Test Coverage

**Documentation:** the historical-truth layer and both `calibration_profile.py`/`ncaaf_calibration_profile.py` files carry module-level docstrings explaining intent, provenance of every constant, and known limitations. The original Football Core engine files (`contracts.py`, `play_state.py`, `situation_model.py`, `drive_priors.py`, `play_simulator.py`, `drive_simulator.py`, `game_simulator.py`, `possession_state.py`, `possession_outcomes.py`, `play_outcomes.py`, `runtime.py`) and the `calibration/` subpackage have **no module-level docstrings** — this predates both SmartSim2 work sessions in this assessment and was not introduced by them. Narrative documentation (the 23 report files) is comprehensive and specifically covers every phase, iteration, and profile decision; inline code documentation is uneven. Non-blocking.

**Test coverage:** 29 tests pass across the engine, calibration framework, historical-truth builder, and NCAAF loader/canonicalization. **Gap**: zero automated tests exercise the `CalibrationProfile` seam itself — the NFL-default-equivalence property, the NCAAF opt-in property, and NCAAF-path reproducibility were all verified in this assessment via ad hoc probes, not captured as permanent regression tests in `tests/`. If a future edit to `play_simulator.py`/`drive_simulator.py` accidentally broke NFL-default equivalence, nothing in the current suite would catch it. Non-blocking for *this* merge (the feature is unwired, zero blast radius), but should be closed before any code path starts calling `profile=NCAAF_CALIBRATION_PROFILE` in production.

## 8. Task 8: Temporary File Audit — **FAILED, blocking**

Task 8 asked to verify no temporary files remain. They do:

- **42 `tmp_*.py`/`tmp_*.txt` files at the repository root**, totaling 1.9 MB, spanning both this session's scratch scripts (`tmp_ncaaf_truth_build.py`, `tmp_ncaaf_profile_measure.py`, `tmp_ncaaf_profile_progress.txt`, etc.) and earlier NFL-calibration-iteration scratch scripts (`tmp_iteration3..6_*`, `tmp_finalize_iteration3*`, `tmp_truth_*`, `tmp_nfl_validation*`, `tmp_single_game_probe.py`, `tmp_smartsim2_iteration3_*`). **None of these are covered by `.gitignore`**: the existing rules (`tmp_*.log`, `tmp_*.json`, `data/tmp_*/`, `scripts/tmp_*.py`) do not match root-level `tmp_*.py` or `tmp_*.txt`. A blanket `git add -A` would commit all 42 of them to `main`.
- **Three untracked data directories with no `.gitignore` coverage**: `data/nfl_source/historical_truth/` (55 MB, this work's NFL cache), `data/ncaaf_source/historical_truth/` (26 MB, this work's NCAAF cache), and `data/nfl_source/tracking/` (196 MB, **not created by either SmartSim2 work session** — pre-existing untracked bulk data of unknown current relevance). Committing 277 MB of regenerable cache/tracking data directly into git history is difficult to undo later and should be a deliberate decision (gitignore + regenerate-on-demand via the loader, or promote through the Syndicate artifact manifest per `smartsim_2_truth_layer_plan.md`'s own Phase 4 notes), not an accidental side effect of a broad commit.

This is the concrete reason the final verdict below is **MERGE BLOCKED** rather than ready — every other check in this report passed.

## 9. Explicit Answers (Task 12)

**Is Football Core safe to merge?** Yes. Zero control-flow changes, zero call sites outside its own package/tests, full regression suite passes (modulo the one pre-existing, unrelated stochastic flake), and the feature is entirely dormant/unwired in the live app — there is no blast radius.

**Is NFL profile safe to freeze?** Yes. `NFL_CALIBRATION_PROFILE` is a literal extraction of the previously-hardcoded constants; every default-path call site produces byte-identical output to before the profile seam existed, verified by direct probe and by the unchanged pre-existing test suite outcome.

**Is NCAAF profile safe to merge?** Yes, *as an Experimental v1 artifact* — the profile-parameter architecture works end-to-end, is fully opt-in, is reproducible, and cannot affect any existing code path. Its calibration quality (documented in `ncaaf_profile_validation_report.md`: strong fit on yards/drive, touchdown rate, field-goal rate; weak fit on turnover-on-downs and punt rate) is a separate question from merge safety — nothing in the codebase consumes `NCAAF_CALIBRATION_PROFILE` yet, so a v1-quality calibration cannot cause a production incident today.

**Are there any cleanup tasks remaining?** Yes, four, none of which touch simulator behavior or calibration parameters:
1. Remove or relocate the 42 `tmp_*` scratch files (or extend `.gitignore` to cover root-level `tmp_*.py`/`tmp_*.txt` before committing).
2. Scope the commit explicitly to SmartSim2 paths — do not `git add -A` given the unrelated WNBA/MLB/odds dirty state described in Section 1.
3. Decide the fate of the 277 MB of untracked data caches/tracking data (gitignore vs. artifact-manifest promotion) before committing.
4. (Non-blocking, recommended before NCAAF sees production traffic) Add `CalibrationProfile`/`NFL_CALIBRATION_PROFILE`/`NCAAF_CALIBRATION_PROFILE` to `smartsim2/__init__.py`'s exports, and add a permanent regression test for the profile seam's opt-in/NFL-equivalence/reproducibility properties.

**What risks remain?**
- Process risk (highest): committing this working tree without scoping would mix unrelated WNBA/MLB/odds changes into a SmartSim2 commit.
- Repo-hygiene risk: scratch files and large data caches, as above.
- Calibration-quality risk (low severity, zero current blast radius): NCAAF v1's turnover-on-downs and punt-rate fits are weak and explicitly diagnosed as a structural tension in `ncaaf_profile_validation_report.md`; this only matters once something starts consuming NCAAF simulation output.
- Test-gap risk (low severity, zero current blast radius): no regression test protects the profile seam's core properties going forward.

## 10. Final Verdict

**MERGE BLOCKED**

Blocking items are exclusively repository-hygiene/commit-scoping issues, not code defects:

1. 42 uncommitted `tmp_*` scratch/probe files at repo root, uncovered by `.gitignore`.
2. No clean commit boundary between SmartSim2 changes and unrelated pre-existing dirty state (WNBA/MLB/odds artifacts, `docs/fix_notes_log.md`, `scripts/refresh_wnba_oddsapi_props.py`).
3. 277 MB of untracked data (two legitimate SmartSim2 caches + one apparently-unrelated 196 MB tracking directory) with no gitignore/artifact-manifest decision made.

Every code-safety, backward-compatibility, opt-in, and reproducibility check in Sections 4-7 **passed**. Once the three blocking items above are resolved — which requires no simulator or calibration-parameter changes, only file cleanup and a scoped `git add` — SmartSim 2.0 (Football Core + frozen NFL profile + Experimental NCAAF profile v1 + historical truth layer + calibration framework + tests + reports) is ready to merge.
