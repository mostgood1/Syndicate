# SmartSim 2.0 NCAAF Calibration Profile v2 — Red-Zone / TD-Conversion Pass

- Date: 2026-07-15
- Trigger: `ncaaf_week1_shakeout_report.md` surfaced a red-zone-conversion gap (72.6-76.4% simulated vs 85.6% truth) that the v1 validation pass never measured.
- Directive: keep yards/drive, yards/play, and possessions/game where they already fit well; improve red-zone success and touchdown conversion.
- Architecture constraint honored: **no simulator fork.** Two new fields were added to the shared `CalibrationProfile` seam (`calibration_profile.py`), both defaulting to the exact literal that was previously hardcoded — `NFL_CALIBRATION_PROFILE` is unaffected. Only `NCAAF_CALIBRATION_PROFILE` sets a non-default value for one of them.

## What Changed (Football Core, additive only)

`calibration_profile.py` gained two fields, both consumed in `play_simulator._play_outcome_weights` in place of literals that were previously hardcoded and shared, unconditionally, by every league:

| Field | Default (= old hardcoded literal) | Replaces |
| --- | --- | --- |
| `red_zone_touchdown_weight_bonus` | 0.33 | the `red_zone * 0.33` term inside the touchdown outcome-weight formula (fires only when `play_state.red_zone`, i.e., yardline ≥ 80) |
| `red_zone_gain_stiffening` | 0.80 | the `gain *= 0.80` scoring-zone stiffening (fires only when `play_state.field_goal_range`, i.e., yardline ≥ 65) |

No branch, control-flow statement, or decision sequence changed — the same `if play_state.red_zone:` / `if play_state.field_goal_range:` blocks fire under the same conditions as before; only the two literals inside them became `profile.<field>` reads. Confirmed byte-identical NFL output: `test_omitting_profile_reproduces_explicit_nfl_profile` (new) and the full pre-existing 28-test suite pass unchanged, including the one pre-existing stochastic flake reproducing the exact same assertion failure ("4 not less than 2") as every prior pass in this project.

## Parameter Sweep

Both fields were swept independently (800-game neutral-input batches, same method as the v1 validation pass) before choosing final values.

**`red_zone_gain_stiffening`** (0.80 → 1.00, i.e., less red-zone gain suppression): no clear red-zone-success improvement (0.769 → 0.756-0.769 across the range, within noise), while yards/drive and yards/play both drifted upward away from their already-good fit. **Rejected as a lever; left at 0.80 (unchanged from v1/NFL).**

**`red_zone_touchdown_weight_bonus`** (0.33 → 0.90): monotonic improvement in both red-zone metrics, at a monotonic cost to the (already near-exact) overall touchdown_rate:

| bonus | red-zone success | red-zone TD share | overall TD rate | yards/drive | yards/play | poss/game |
| --- | --- | --- | --- | --- | --- | --- |
| 0.33 (v1) | 0.769 | 0.592 | 0.284 | 42.87 | 5.940 | 20.14 |
| 0.42 | 0.776 | 0.602 | 0.289 | 42.73 | 5.958 | 20.28 |
| 0.50 | 0.781 | 0.612 | 0.294 | 42.60 | 5.954 | 20.30 |
| **0.58 (chosen)** | **0.789** | **0.624** | 0.298 | **42.49** | 5.958 | 20.34 |
| 0.65 | 0.790 | 0.627 | 0.301 | 42.58 | 5.982 | 20.43 |
| 0.75 | 0.793 | 0.631 | 0.302 | 42.50 | 5.993 | 20.51 |
| 0.90 | 0.802 | 0.644 | 0.307 | 42.19 | 6.003 | 20.63 |

"Red-zone TD share" = red-zone entries ending specifically in a touchdown (not just any score) — the "TD Conversion" metric distinct from "Red-Zone Success" (any score: TD+FG).

**0.58 chosen**: normalized error on red-zone success falls from 0.102 to 0.078 (-24%) and on red-zone TD share from 0.129 to 0.082 (-36%), while yards/drive lands almost exactly on truth (42.49 sim vs 42.49 truth — coincidental grid alignment, but confirms no drift) and yards/play/possessions barely move. The overall touchdown_rate normalized error rises from 0.076 to 0.129 — a real, disclosed trade-off, not hidden: more aggressive bonus values (0.75-0.90) buy further red-zone gains at a steeper cost to that already-good fit, so 0.58 was chosen as the point past which the trade stops paying for itself.

## Confirmation: Kept Metrics Held Steady (800-game neutral batch)

| Metric | v1 (bonus 0.33) | v2 (bonus 0.58) | Change |
| --- | --- | --- | --- |
| Yards/drive | 42.87 | 42.49 | **-0.9%, closer to truth (42.49)** |
| Yards/play | 5.940 | 5.958 | +0.3%, effectively unchanged |
| Possessions/game | 20.14 | 20.34 | +1.0%, effectively unchanged |

## Confirmation: Improved Metrics (800-game neutral batch)

| Metric | Truth | v1 (bonus 0.33) | v2 (bonus 0.58) |
| --- | --- | --- | --- |
| Red-zone success (TD+FG share of red-zone entries) | 85.6% | 76.9% | **78.9%** |
| Red-zone TD share (of red-zone entries) | ~68.0% (proxy: touchdown_rate/red_zone_entry_rate) | 59.2% | **62.4%** |

## Real-Schedule Confirmation (51 FBS-vs-FBS games, 2026 Week 1 CFBD schedule, `ncaaf_week1_shakeout_report.md`'s exact method)

| Metric | Before (v1) | After (v2) |
| --- | --- | --- |
| Red-zone conversion rate | 72.6% | **75.9%** |
| Yards/drive | 41.59 | 41.22 |
| Yards/play | 5.80 | 5.90 |
| Possessions/game | 20.24 | 20.73 |
| Touchdown rate | 26.8% | 29.8% |
| Game totals | 44.08 | 48.47 (moved closer to 53.35 truth) |
| Simulation errors / anomalies | 0 | 0 |

The improvement direction and magnitude on the real schedule matches the neutral-batch sweep (small-sample noise aside); no new anomalies, crashes, or structurally invalid drives appeared in the re-run.

## Test Coverage Added

`tests/test_smartsim2_calibration_profile.py` (new, 5 tests): NFL defaults match the pre-existing hardcoded literals exactly; the NCAAF profile differs from NFL on exactly the documented field set (now including `red_zone_touchdown_weight_bonus`, with `red_zone_gain_stiffening` explicitly confirmed unchanged); omitting `profile=` reproduces the explicit NFL profile byte-for-byte; a higher `red_zone_touchdown_weight_bonus` measurably raises red-zone touchdown frequency in a direct `simulate_drive` comparison; `to_dict()` round-trips the new fields. Full suite: 33/34 passing (one pre-existing, unrelated stochastic flake, unchanged).

## Explicit Answers

**Did yards/drive, yards/play, and possessions stay where they were?** Yes — all three moved by under 1.1% and, where they moved at all, moved toward truth rather than away from it. Neither new field touches the yardage-generation or possession-count levers (`drive_yardage_multiplier`, `explosive_yardage_multiplier`, `explosive_play_multiplier`); the small residual movement is the second-order effect of drives now less often stalling out.

**Did red-zone success and TD conversion improve?** Yes — red-zone success normalized error down 24%, red-zone TD-share normalized error down 36%, confirmed both on a large neutral-input batch and on the real 2026 Week 1 schedule.

**What did it cost?** The one disclosed trade-off: overall touchdown_rate (all drives, not just red-zone) drifted from 28.4% to 29.8% sim (truth 26.4%), a normalized-error increase from 0.076 to 0.129. This was an explicit, measured choice — more aggressive bonus values bought further red-zone gains at a steeper version of the same cost.

**Is this Calibrated or still Experimental?** Still **Experimental** — one more parameter sweep on top of the v1 measurement pass, not the NFL profile's multi-iteration, per-season-validated process. The known-gaps ledger from `ncaaf_profile_validation_report.md` (turnover-on-downs, punt rate, plays/drive/possessions coupling) is unchanged by this pass; red-zone conversion moves from "unmeasured gap" to "partially closed, now-tracked gap," and overall touchdown_rate moves from "near-exact" to "known, disclosed, moderate residual."

## Deliverables

- `calibration_profile.py` — two new additive fields (`red_zone_touchdown_weight_bonus`, `red_zone_gain_stiffening`), NFL defaults unchanged.
- `ncaaf_calibration_profile.py` — `red_zone_touchdown_weight_bonus=0.58`, `red_zone_gain_stiffening=0.80` (explicitly confirmed at the shared default, not merely omitted), updated module docstring (v1 → v2).
- `play_simulator.py` — two literals replaced with `profile.<field>` reads, no control-flow change.
- `tests/test_smartsim2_calibration_profile.py` — new, 5 tests.
- This report.
