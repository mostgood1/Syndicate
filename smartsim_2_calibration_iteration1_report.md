# SmartSim 2.0 Calibration Iteration 1 Report

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Baseline calibration score: 0.000
- Iteration 1 calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233

## Before vs After

| Metric | Baseline Norm Err | Iteration 1 Norm Err | Delta |
| --- | --- | --- | --- |
| turnover_rate | 123.508 | 69.785 | +53.723 |
| quarter_3_scoring | 4.447 | 1.592 | +2.855 |
| quarter_1_scoring | 4.484 | 1.541 | +2.943 |
| red_zone_conversion_rate | 1.319 | 1.319 | +0.000 |
| game_totals | 3.438 | 1.066 | +2.372 |
| possessions_per_game | 2.377 | 1.015 | +1.362 |
| quarter_4_scoring | 2.866 | 0.791 | +2.075 |
| quarter_2_scoring | 2.812 | 0.751 | +2.061 |
| punt_rate | 0.990 | 0.564 | +0.426 |
| drive_length_seconds | 0.693 | 0.484 | +0.209 |
| drive_length_yards | 0.298 | 0.414 | -0.116 |
| drive_length_plays | 0.398 | 0.223 | +0.175 |
| field_goal_rate | 0.087 | 0.087 | +0.000 |
| touchdown_rate | 0.421 | 0.051 | +0.370 |

## Biggest Improvements

- turnover_rate: normalized error 123.508 -> 69.785 (+53.723)
- quarter_1_scoring: normalized error 4.484 -> 1.541 (+2.943)
- quarter_3_scoring: normalized error 4.447 -> 1.592 (+2.855)
- game_totals: normalized error 3.438 -> 1.066 (+2.372)
- quarter_4_scoring: normalized error 2.866 -> 0.791 (+2.075)
- quarter_2_scoring: normalized error 2.812 -> 0.751 (+2.061)

## Metrics That Worsened

- drive_length_yards: normalized error 0.298 -> 0.414 (-0.116)

## What Improved

turnover_rate, quarter_1_scoring, quarter_3_scoring, game_totals, quarter_4_scoring, quarter_2_scoring, possessions_per_game, red_zone_conversion_rate, punt_rate, drive_length_seconds, touchdown_rate, drive_length_plays, field_goal_rate

## What Worsened

drive_length_yards

## Remaining Unrealistic

- Drive length is better but still short of the proxy benchmark.
- Punt rate is still materially below the target shape, so possession exchanges remain too aggressive.
- Quarter scoring and total points are still far too high because the simulator still creates too many scoring drives.
- Turnover rate remains the largest error and still needs a cleaner separation between punts, missed field goals, and true turnovers.

## Next Calibration Target

- Reduce scoring-drive frequency without suppressing sustained drives further.
- Separate missed-field-goal possession changes from true turnovers more cleanly if the next iteration still inflates turnover rate.
- Tune fourth-down decision thresholds once drive length is closer to the benchmark, because possession count and punt mix still control most downstream error.

## Metric Table

| Metric | Benchmark | Iteration 1 | Baseline Norm Err | Iteration 1 Norm Err | Delta |
| --- | --- | --- | --- | --- | --- |
| turnover_rate | 0.4% | 46.6% | 123.508 | 69.785 | +53.723 |
| quarter_3_scoring | 9.42 | 51.33 | 4.447 | 1.592 | +2.855 |
| quarter_1_scoring | 9.17 | 50.31 | 4.484 | 1.541 | +2.943 |
| red_zone_conversion_rate | 43.1% | 100.0% | 1.319 | 1.319 | +0.000 |
| game_totals | 46.24 | 205.22 | 3.438 | 1.066 | +2.372 |
| possessions_per_game | 21.11 | 71.31 | 2.377 | 1.015 | +1.362 |
| quarter_4_scoring | 13.15 | 50.83 | 2.866 | 0.791 | +2.075 |
| quarter_2_scoring | 13.81 | 52.65 | 2.812 | 0.751 | +2.061 |
| punt_rate | 59.0% | 0.6% | 0.990 | 0.564 | +0.426 |
| drive_length_seconds | 166.1 | 51.0 | 0.693 | 0.484 | +0.209 |
| drive_length_yards | 31.07 | 21.81 | 0.298 | 0.414 | -0.116 |
| drive_length_plays | 4.05 | 2.44 | 0.398 | 0.223 | +0.175 |
| field_goal_rate | 16.2% | 14.7% | 0.087 | 0.087 | +0.000 |
| touchdown_rate | 24.5% | 34.8% | 0.421 | 0.051 | +0.370 |