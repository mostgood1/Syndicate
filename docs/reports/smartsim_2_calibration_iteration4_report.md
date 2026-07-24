# SmartSim 2.0 Calibration Iteration 4 Report

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Iteration 3 calibration score: 0.000
- Iteration 4 calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233
- Objective: correct field-goal attempt frequency and restore realistic punt dominance

## Field-Goal Eligibility Audit (Task 1-3)

The 42.3% FG-attempt share in Iteration 3 came from four compounding defects:

1. `situation_model.classify_situation` defined `field_goal_range = distance <= 12 or yardline >= 80`, so nearly every play anywhere on the field was flagged as in FG range (a 95-yard kick from a team's own 5 qualified whenever distance <= 12).
2. `play_simulator._play_outcome_weights` sampled `FIELD_GOAL_ATTEMPT` as a per-play outcome on downs 1-3. Because the drive loop intercepts all 4th downs itself, 100% of the unrealistic FG attempts fired on early downs.
3. `red_zone` was defined as `distance <= 7 or yardline <= 20 or yardline >= 80`, so the red-zone FG bonus (+0.18/+0.04) and touchdown bonus (+0.80) triggered from anywhere on the field.
4. `_field_goal_success_probability` floored at 0.12, so the flood of bogus long attempts missed constantly (28.3% missed-FG share).

The audit also exposed the deeper masked defect: the `GAIN` play branch set `repeat_down = yards_gained < distance and down < 4`, meaning non-converting plays repeated the down instead of advancing it. The offense effectively had unlimited downs, so drives could not stall into 4th-down punts through normal play; the bogus early-down FG/TD terminals were what had been ending drives.

## True FG Range Definition (Task 2)

Kick distance = 17 + (100 - yardline). **True FG range = yardline >= 65** (kick <= 52 yards), published as `TRUE_FIELD_GOAL_RANGE_YARDLINE` in `situation_model.py`.

## Changes Implemented (Task 4-6)

- `situation_model.py`: `field_goal_range` now requires yardline >= 65; `red_zone` now means yardline >= 80 only; `goal_to_go` now requires yardline >= 90 with yards-to-goal <= distance.
- `play_simulator.py`: `FIELD_GOAL_ATTEMPT` is only samplable on 4th down inside true FG range (previously every down, everywhere); FG make probability is now distance-based (`0.98 - 0.012 * max(0, kick - 25)`, clamped 0.30-0.97).
- `drive_simulator.py`: 4th-down decision order is now FG-first inside true range (attempt probability 0.55 at the 65 to 0.92 clamp deep), then punt as the default neutral outcome (always punt inside own 40, ~98.5% to midfield, ~90-96% up to the 65), then go-for-it. The old dead zone (yardline 88-93: never punt, never kick) is gone.
- `play_simulator.py` (rebalance under real down mechanics): fixed the `repeat_down` unlimited-downs bug, raised GAIN base yardage (2.5 -> 4.4 + priors), trimmed incomplete-pass and per-play turnover weights, nudged explosive-gain weight. These were required to keep drives viable once downs actually advanced; without them scoring collapsed to 17 points per game.
- `tests/test_smartsim2_situation_model.py`: updated the red-zone test that had encoded the old buggy definition (own 18-yard line labeled "Red Zone"); added a backed-up-territory assertion. Full smartsim2 suite: 16/16 passing.

## Before vs After

| Metric | Benchmark | Iteration 3 | Iteration 4 | Iter 3 Norm Err | Iter 4 Norm Err | Delta |
| --- | --- | --- | --- | --- | --- | --- |
| turnover_rate | 0.4% | 9.0% | 8.6% | 22.958 | 21.986 | +0.972 |
| red_zone_conversion_rate | 43.1% | 100.0% | 100.0% | 1.319 | 1.319 | +0.000 |
| quarter_3_scoring | 9.42 | 17.89 | 6.93 | 0.898 | 0.265 | +0.633 |
| quarter_1_scoring | 9.17 | 16.63 | 6.99 | 0.812 | 0.238 | +0.574 |
| punt_rate | 59.0% | 16.3% | 53.9% | 0.723 | 0.086 | +0.637 |
| possessions_per_game | 21.11 | 34.39 | 22.86 | 0.629 | 0.082 | +0.547 |
| game_totals | 46.24 | 70.05 | 28.25 | 0.515 | 0.389 | +0.126 |
| quarter_4_scoring | 13.15 | 17.97 | 7.10 | 0.367 | 0.460 | -0.093 |
| drive_length_seconds | 166.1 | 106.0 | 160.2 | 0.362 | 0.035 | +0.327 |
| quarter_2_scoring | 13.81 | 17.52 | 7.10 | 0.268 | 0.486 | -0.218 |
| drive_length_yards | 31.07 | 25.06 | 43.50 | 0.194 | 0.400 | -0.206 |
| field_goal_rate | 16.2% | 14.0% | 6.6% | 0.135 | 0.594 | -0.459 |
| touchdown_rate | 24.5% | 23.1% | 14.8% | 0.056 | 0.394 | -0.338 |
| drive_length_plays | 4.05 | 3.84 | 5.48 | 0.052 | 0.352 | -0.300 |

Note on drive_length_yards: punt net yardage is credited to drive yards by the evaluator, so a punt-dominant mix mechanically inflates this metric; it is partially an accounting artifact rather than pure field-position error.

## Drive-Ending Frequency Audit

| Outcome | Benchmark | Iteration 3 | Iteration 4 | Delta |
| --- | --- | --- | --- | --- |
| touchdown | 0.245 | 0.231 | 0.148 | -0.083 |
| field_goal | 0.162 | 0.140 | 0.066 | -0.074 |
| missed_field_goal | 0.000 | 0.283 | 0.015 | -0.268 |
| punt | 0.590 | 0.163 | 0.539 | +0.376 |
| turnover | 0.004 | 0.084 | 0.065 | -0.019 |
| turnover_on_downs | 0.000 | 0.006 | 0.021 | +0.015 |
| end_of_quarter_stop | 0.000 | 0.047 | 0.074 | +0.027 |
| end_of_half_stop | 0.000 | 0.046 | 0.072 | +0.026 |

Punt is now the dominant drive ending (53.9% of drives), and total FG attempts fell from 42.3% to 8.1% with a realistic ~81% make rate.

## Preservation Check (Task 6)

- Turnover improvements: preserved. True-turnover share fell 0.084 -> 0.065 and the turnover_rate metric improved slightly (9.0% -> 8.6%).
- Drive length improvements: mixed. Drive seconds are now nearly exact (160.2 vs 166.1 benchmark, norm err 0.035). Drive plays overshot (5.48 vs 4.05) because drives now survive their bogus early terminals.
- TD rate stability: not preserved (23.1% -> 14.8%). The Iteration 3 TD rate was itself propped up by the misclassified red-zone flag (`distance <= 7` anywhere granted a +0.80 per-play TD boost). Removing the fake boost revealed the true underlying scoring power, which is now too low rather than artificially correct.

## Explicit Answers

- **Did FG attempt rate decline?** Yes, decisively: 42.3% -> 8.1% of drives (6.6% made + 1.5% missed). It now slightly undershoots the 16.2% benchmark instead of overshooting it by 26 points, and the missed-FG distortion (28.3% -> 1.5%) is effectively eliminated.
- **Did punt rate improve?** Yes, decisively: 16.3% -> 53.9% against a 59.0% benchmark (normalized error 0.723 -> 0.086). Punt is now the dominant neutral-drive ending, satisfying the primary success criterion.
- **Did possession count improve?** Yes: 34.39 -> 22.86 possessions per game against a 21.11 benchmark (normalized error 0.629 -> 0.082).
- **Did game totals improve?** Yes on error (70.05 -> 28.25 vs 46.24 benchmark, normalized error 0.515 -> 0.389), but the sign flipped: the simulator moved from +51% scoring inflation to a -39% scoring undershoot.
- **What is the new largest calibration error?** By normalized error, turnover_rate (21.99) is still the largest single metric, inflated by the proxy benchmark's near-zero (0.4%) turnover encoding. Structurally, the largest real gap is now **scoring share**: touchdowns 14.8% vs 24.5% and made field goals 6.6% vs 16.2%, compounded by red-zone conversion still pinned at 100% and ~14.6% of drives dying in quarter/half stops.

## What Should Iteration 5 Target?

1. Scoring share recovery: drives sustain realistically but finish too rarely; raise sustained-drive conversion into the scoring zone (series-conversion rate on early downs) rather than re-inflating per-play TD bonuses.
2. Red-zone outcome model: replace the 100% red-zone conversion with a real distribution (TD / FG settle / failure) — this adds made FGs and TDs simultaneously and is the remaining untouched constant since baseline.
3. Second/fourth-quarter scoring shape: benchmark Q2/Q4 scoring is much higher than Q1/Q3; the simulator lacks end-of-half urgency scoring, which the quarter-stop share (14.6%) currently absorbs.
4. Only then revisit residual true-turnover weight (0.065 vs 0.004 proxy).

## Final Verdict

**Iteration 4 Successful.**

The iteration's stated objective is fully met: field-goal attempt rate collapsed from 42.3% to 8.1% of drives, punt became the dominant neutral-drive ending at 53.9% (benchmark 59.0%), possessions per game landed within 8% of benchmark, and drive seconds are within 4%. The audit also uncovered and fixed two structural defects the FG flood had been masking (unlimited-downs `repeat_down` bug, field-wide red-zone misclassification). The cost is an honest scoring undershoot — touchdown and made-FG shares are now the measured, clearly-scoped target for Iteration 5 instead of being artifacts of misclassified situations.
