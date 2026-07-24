# SmartSim 2.0 Calibration Iteration 2 Report

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Iteration 1 calibration score: 0.000
- Iteration 2 calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233

## Before vs After

| Metric | Iteration 1 Norm Err | Iteration 2 Norm Err | Delta |
| --- | --- | --- | --- |
| turnover_rate | 69.785 | 41.506 | +28.279 |
| red_zone_conversion_rate | 1.319 | 1.319 | +0.000 |
| quarter_3_scoring | 1.592 | 1.007 | +0.585 |
| quarter_1_scoring | 1.541 | 0.873 | +0.668 |
| possessions_per_game | 1.015 | 0.780 | +0.235 |
| punt_rate | 0.564 | 0.759 | -0.195 |
| game_totals | 1.066 | 0.565 | +0.501 |
| drive_length_seconds | 0.484 | 0.415 | +0.069 |
| quarter_4_scoring | 0.791 | 0.382 | +0.409 |
| quarter_2_scoring | 0.751 | 0.305 | +0.446 |
| drive_length_yards | 0.414 | 0.236 | +0.178 |
| field_goal_rate | 0.087 | 0.166 | -0.079 |
| drive_length_plays | 0.223 | 0.130 | +0.093 |
| touchdown_rate | 0.051 | 0.112 | -0.061 |

## Drive-Ending Frequency Audit

| Outcome | Benchmark Freq | Iteration 2 Freq | Delta |
| --- | --- | --- | --- |
| touchdown | 0.245 | 0.217 | -0.028 |
| field_goal | 0.162 | 0.135 | -0.027 |
| missed_field_goal | 0.000 | 0.259 | +0.259 |
| punt | 0.590 | 0.142 | -0.448 |
| turnover | 0.004 | 0.080 | +0.077 |
| turnover_on_downs | 0.000 | 0.079 | +0.079 |

## Biggest Improvements

- turnover_rate: normalized error 69.785 -> 41.506 (+28.279)
- quarter_1_scoring: normalized error 1.541 -> 0.873 (+0.668)
- quarter_3_scoring: normalized error 1.592 -> 1.007 (+0.585)
- game_totals: normalized error 1.066 -> 0.565 (+0.501)
- quarter_2_scoring: normalized error 0.751 -> 0.305 (+0.446)
- quarter_4_scoring: normalized error 0.791 -> 0.382 (+0.409)

## Metrics That Worsened

- punt_rate: normalized error 0.564 -> 0.759 (-0.195)
- field_goal_rate: normalized error 0.087 -> 0.166 (-0.079)
- touchdown_rate: normalized error 0.051 -> 0.112 (-0.061)

## What Improved

turnover_rate, quarter_3_scoring, quarter_1_scoring, red_zone_conversion_rate, game_totals, possessions_per_game, quarter_4_scoring, quarter_2_scoring, drive_length_seconds, drive_length_yards, drive_length_plays

## What Worsened

punt_rate, field_goal_rate, touchdown_rate

## Remaining Unrealistic

- Punt rate improved materially, but it is still well below the benchmark mix, so possession exchanges remain too pass-heavy and turnover-heavy.
- Turnovers improved sharply, but true turnovers are still too frequent compared with the proxy baseline.
- Quarter scoring and game totals improved only partially; the simulator is still producing too many scoring drives and too many total points.
- Missed field goals are now visible as their own branch, but they are still too frequent relative to punts in neutral situations.

## Next Calibration Target

- Keep depressing early scoring branches while preserving drive length.
- Push more 4th-down states to punt rather than field-goal attempt unless the ball is already in true kick range.
- Reduce true turnover weight further only after the punt mix is closer to benchmark, so possession exchange happens through punts instead of giveaways.

## Metric Table

| Metric | Benchmark | Iteration 2 | Iteration 1 Norm Err | Iteration 2 Norm Err | Delta |
| --- | --- | --- | --- | --- | --- |
| turnover_rate | 0.4% | 15.9% | 69.785 | 41.506 | +28.279 |
| red_zone_conversion_rate | 43.1% | 100.0% | 1.319 | 1.319 | +0.000 |
| quarter_3_scoring | 9.42 | 18.91 | 1.592 | 1.007 | +0.585 |
| quarter_1_scoring | 9.17 | 17.18 | 1.541 | 0.873 | +0.668 |
| possessions_per_game | 21.11 | 37.58 | 1.015 | 0.780 | +0.235 |
| punt_rate | 59.0% | 14.2% | 0.564 | 0.759 | -0.195 |
| game_totals | 46.24 | 72.36 | 1.066 | 0.565 | +0.501 |
| drive_length_seconds | 166.1 | 97.1 | 0.484 | 0.415 | +0.069 |
| quarter_4_scoring | 13.15 | 18.17 | 0.791 | 0.382 | +0.409 |
| quarter_2_scoring | 13.81 | 18.02 | 0.751 | 0.305 | +0.446 |
| drive_length_yards | 31.07 | 23.74 | 0.414 | 0.236 | +0.178 |
| field_goal_rate | 16.2% | 13.5% | 0.087 | 0.166 | -0.079 |
| drive_length_plays | 4.05 | 3.53 | 0.223 | 0.130 | +0.093 |
| touchdown_rate | 24.5% | 21.7% | 0.051 | 0.112 | -0.061 |