# SmartSim 2.0 NCAAF Calibration Profile v1 — Report

- Date: 2026-07-15
- Status: **Experimental** (v1, one measurement pass; see `ncaaf_profile_validation_report.md` for the full verdict)
- Inputs: `ncaaf_historical_truth_report.md` (53,548 real NCAAF drives / 2,264 games, 2023-2025), `nfl_historical_truth_report.md`, `nfl_validation_report.md`, `nfl_production_candidate_report.md`
- Architecture constraint honored: **no simulator forks, no NCAAF-specific engine.** NCAAF behavior is expressed entirely through 9 of 20 parameters on the shared `CalibrationProfile` seam; `play_simulator.py`, `drive_simulator.py`, `game_simulator.py`, `situation_model.py`, and `contracts.py` contain zero league-specific branches.
- NFL calibration profile: **frozen and unmodified.** `NFL_CALIBRATION_PROFILE` reproduces every constant that was previously hardcoded directly in the engine; every existing call site defaults to it. Full SmartSim2 regression suite re-run after every edit in this pass: 28/29 passing throughout (the one failure, `test_stronger_features_raise_scoring_frequency`, reproduces the exact same pre-existing stochastic assertion — "4 not less than 2" — byte-for-byte before and after this work, proving the NFL default path's random-number sequence is untouched).

## What Changed (Football Core, additive only)

`calibration_profile.py` (new file) defines `CalibrationProfile`, a frozen dataclass of 20 numeric fields plus `name`, and `NFL_CALIBRATION_PROFILE`, a constant whose every value is the literal that used to be hardcoded in `play_simulator.py`/`drive_simulator.py`. Every function that used to read a hardcoded constant now reads `profile.<field>` instead, with `profile: CalibrationProfile = NFL_CALIBRATION_PROFILE` as the default parameter — an additive, backward-compatible signature change threaded through:

- `play_simulator.py`: `_field_goal_success_probability`, `_play_outcome_weights`, `simulate_play` (explosive-gain and ordinary-gain yardage formulas, touchdown/field-goal outcome weights).
- `drive_simulator.py`: `_punt_decision`, `_field_goal_decision`, `_field_goal_make_probability`, `_execute_field_goal`, `simulate_drive` (fourth-down conversion-probability formulas).
- `game_simulator.py`: `simulate_game` (passes `profile` through to every `simulate_drive` call, regulation and overtime).

No decision logic, branch, or control-flow statement was added, removed, or reordered — only literal constants were replaced by `profile.<field>` reads. This is why the NFL seeded output is unchanged.

## Task 3-4: NFL Truth vs NCAAF Truth — Audit and Quantified Deltas

| Metric | NFL Truth | NCAAF Truth | Delta | Calibration lever required? |
| --- | --- | --- | --- | --- |
| Possessions/game | 21.66 | 23.65 | +9.2% | No dedicated lever (emerges from drive economy) |
| Plays/drive | 5.93 | 5.77 | -2.7% | No — within Football Core noise band |
| Yards/drive | 30.66 | 42.49 | **+38.6%** | **Yes** — `drive_yardage_multiplier`, `explosive_yardage_multiplier` |
| Yards/play | 5.17 | 7.36 | **+42.4%** | **Yes** — `explosive_play_multiplier`, `explosive_yardage_multiplier`, `drive_yardage_multiplier` |
| Touchdown rate | 22.0% | 26.4% | **+20.0%** | **Yes** — `touchdown_weight_multiplier` |
| Field-goal rate (made) | 15.7% | 10.0% | **-36.3%** | **Yes** — `field_goal_make_base/distance_penalty/floor/ceiling` |
| Punt rate | 35.1% | 35.1% | ~0.0% | No — sport-invariant |
| Turnover rate | 11.1% | 10.9% | -1.8% | No — sport-invariant |
| Turnover-on-downs rate | 5.8% | 7.3% | **+25.9%** | **Yes** — `fourth_down_conversion_multiplier` (primary lever) |
| Red-zone conversion | 85.5% | 85.6% | +0.1% | No — sport-invariant |
| Game totals | 45.13 | 53.35 | **+18.2%** | Downstream of yards/play + TD/FG mix (no dedicated lever; a composite outcome) |

## Task 2: Profile-Level Parameters Defined

`ncaaf_calibration_profile.py` sets 9 of the 20 shared `CalibrationProfile` fields away from the NFL default (11 fields — 55% — are left identical; see the shared-parameters answer below):

| Parameter | NFL | NCAAF | Targets |
| --- | --- | --- | --- |
| `explosive_play_multiplier` | 1.00 | 1.45 | yards/play, yards/drive |
| `explosive_yardage_multiplier` | 1.00 | 1.35 | yards/play, yards/drive |
| `drive_yardage_multiplier` | 1.00 | 1.15 | yards/play, yards/drive |
| `field_goal_make_base` | 0.98 | 0.90 | field-goal success profile |
| `field_goal_make_distance_penalty` | 0.012 | 0.022 | field-goal success profile |
| `field_goal_make_floor` | 0.30 | 0.25 | field-goal success profile |
| `field_goal_make_ceiling` | 0.97 | 0.82 | field-goal success profile |
| `fourth_down_conversion_multiplier` | 1.00 | 0.55 | fourth-down aggressiveness / turnover-on-downs |
| `touchdown_weight_multiplier` | 1.00 | 0.66 | scoring distribution |

`field_goal_weight_multiplier` is defined on the shared seam but left at 1.0 for NCAAF: measurement showed it is a **no-op in practice**. `drive_simulator.py`'s 4th-down handling always intercepts `down == 4` with its own explicit `_field_goal_decision`/`_punt_decision` branch before `simulate_play` ever runs, so `play_simulator._play_outcome_weights`'s `down >= 4`-gated `FIELD_GOAL_ATTEMPT` weight is structurally unreachable during normal play. The real field-goal levers are `field_goal_make_*` (make probability, used above) and `field_goal_attempt_*` (attempt probability, left at NFL defaults — see below). This is documented directly in the profile file so a future pass doesn't waste time tuning a dead parameter.

`field_goal_attempt_*` and all seven `fourth_down_*_punt_probability`/`*_punt_base`/`*_punt_scale` fields are left at NFL defaults: measurement showed changing field-goal-attempt probability shifted `punt_rate` (a measured sport-invariant metric) without moving made-FG rate, so it was reverted in favor of the make-probability levers, which move the target metric directly without the punt-rate side effect.

## Task 8: Explicit Answers

### Which behaviors remain Football Core?

Everything not listed as a parameter above: the possession/drive/play state machine, the urgency/situation model (two-minute drill, four-minute offense, halftime/end-game preservation, red-zone/goal-to-go classification), the 4th-down decision *sequence* (urgency field goal -> late-game go-for-it -> field-goal decision -> punt decision -> neutral go-for-it), the outcome taxonomy (`PossessionOutcome`), and the clock-consumption model. Additionally, three **numeric** behaviors measured as sport-invariant and left untouched: punt-decision thresholds, turnover-rate priors (via the untouched `DrivePriorProfile`/`build_drive_priors` feature-scoring logic), and red-zone conversion dynamics.

### Which behaviors require profile calibration?

The five named in the task, each mapped to specific parameters above: explosive-play frequency and magnitude, ordinary drive-yardage magnitude, field-goal make-probability curve, fourth-down conversion success, and touchdown-vs-field-goal outcome-weight balance.

### Which assumptions differ from NFL?

Three structural assumptions embedded in the NCAAF profile's values (not yet expressed as their own dedicated parameters, since they were reachable through the existing 20-field seam): (1) college kickers are trusted over a shorter effective range (steeper `field_goal_make_distance_penalty`, lower `field_goal_make_ceiling`); (2) fourth-down conversion success is lower, not higher, when teams do go for it — consistent with going for it out of kicker distrust/aggression rather than superior short-yardage execution; (3) touchdown frequency is elevated primarily through the shared yardage-generation levers (bigger/more-frequent explosive plays reach and hold the red zone more often, which itself raises touchdown weight in the untouched `_play_outcome_weights` logic) — `touchdown_weight_multiplier` is a *correction*, not the primary driver, and needed to be set **below** 1.0 to avoid overshoot once the yardage levers were in place.

### How much of NCAAF can reuse NFL calibration?

The full Football Core (100% of engine code) plus 11 of 20 profile parameters (55%) — everything governing punt decisions and field-goal attempt-probability curves. Practically: NCAAF needed zero new code and about half of one existing profile's parameter values.

### What percent of parameters are shared?

**55% (11 of 20).** Computed directly by diffing every `CalibrationProfile` field between `NFL_CALIBRATION_PROFILE` and `NCAAF_CALIBRATION_PROFILE`: 9 differ (the ones in the table above), 11 are byte-identical.

## Task 5-6: Preservation and Contract Checks

- Football Core behavior preserved: confirmed via full regression suite (see header) and via direct inspection — no new branches, no removed branches, no reordered logic in any touched function.
- NCAAF truth still runs through the unmodified `HistoricalTruthSnapshot` / `historical_snapshot_builder.py` contract: re-verified by re-running `tmp_ncaaf_truth_build.py` against the same CFBD cache used in the prior phase; 53,548 drives / 2,264 games reproduced identically, `to_calibration_snapshot()` adapter unchanged.

## Deliverables

- `syndicate/features/football/sim_engine/smartsim2/calibration_profile.py` — shared `CalibrationProfile` dataclass + `NFL_CALIBRATION_PROFILE`.
- `syndicate/features/football/sim_engine/smartsim2/ncaaf_calibration_profile.py` — `NCAAF_CALIBRATION_PROFILE`.
- Additive `profile` parameter threading in `play_simulator.py`, `drive_simulator.py`, `game_simulator.py`.
- This report.
- `ncaaf_profile_validation_report.md` — measured simulated-vs-truth comparison (tasks 9-12).
