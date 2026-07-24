# SmartSim 2.0 Baseline Calibration Audit

- Source: NFL-Betting 2025 wk17/wk18/wk20 proxy baseline
- Split: calibration
- Calibration score: 0.000
- Games evaluated: 532
- Drives synthesized: 11233
- Benchmark shape: proxy benchmark built from historical game summaries plus team-week summary tables
- Current hypothesis: drive length and drive finishing behavior are the first-zero realism gaps

## Severity Summary

- Critical: 13
- Moderate: 0
- Minor: 1

## Largest Gaps

| Metric | Severity | Benchmark | Simulated | Abs Error | Normalized Error |
| --- | --- | --- | --- | --- | --- |
| turnover_rate | Critical | 0.4% | 46.6% | 0.462 | 123.508 |
| quarter_1_scoring | Critical | 9.17 | 50.31 | 41.135 | 4.484 |
| quarter_3_scoring | Critical | 9.42 | 51.33 | 41.902 | 4.447 |
| game_totals | Critical | 46.24 | 205.22 | 158.974 | 3.438 |
| quarter_4_scoring | Critical | 13.15 | 50.83 | 37.679 | 2.866 |
| quarter_2_scoring | Critical | 13.81 | 52.65 | 38.838 | 2.812 |
| possessions_per_game | Critical | 21.11 | 71.31 | 50.192 | 2.377 |
| red_zone_conversion_rate | Critical | 43.1% | 100.0% | 0.569 | 1.319 |
| punt_rate | Critical | 59.0% | 0.6% | 0.584 | 0.990 |
| drive_length_seconds | Critical | 166.1 | 51.0 | 115.046 | 0.693 |

## Full Metric Table

| Metric | Severity | Benchmark | Simulated | Abs Error | Normalized Error |
| --- | --- | --- | --- | --- | --- |
| turnover_rate | Critical | 0.4% | 46.6% | 0.462 | 123.508 |
| quarter_1_scoring | Critical | 9.17 | 50.31 | 41.135 | 4.484 |
| quarter_3_scoring | Critical | 9.42 | 51.33 | 41.902 | 4.447 |
| game_totals | Critical | 46.24 | 205.22 | 158.974 | 3.438 |
| quarter_4_scoring | Critical | 13.15 | 50.83 | 37.679 | 2.866 |
| quarter_2_scoring | Critical | 13.81 | 52.65 | 38.838 | 2.812 |
| possessions_per_game | Critical | 21.11 | 71.31 | 50.192 | 2.377 |
| red_zone_conversion_rate | Critical | 43.1% | 100.0% | 0.569 | 1.319 |
| punt_rate | Critical | 59.0% | 0.6% | 0.584 | 0.990 |
| drive_length_seconds | Critical | 166.1 | 51.0 | 115.046 | 0.693 |
| touchdown_rate | Critical | 24.5% | 34.8% | 0.103 | 0.421 |
| drive_length_plays | Critical | 4.05 | 2.44 | 1.613 | 0.398 |
| drive_length_yards | Critical | 31.07 | 21.81 | 9.257 | 0.298 |
| field_goal_rate | Minor | 16.2% | 14.7% | 0.014 | 0.087 |

## Interpretation

- Read the drive-length rows first; if they are off, the scoring and totals rows are downstream noise.
- Punt and field-goal mix should be reconciled before treating game totals as trustworthy.
- This audit is intentionally a proxy baseline until true drive-level historical play-by-play is mirrored locally.