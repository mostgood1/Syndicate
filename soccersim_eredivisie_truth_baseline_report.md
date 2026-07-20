# SoccerSim EREDIVISIE Truth Baseline Report

- Source: football-data.co.uk eredivisie [2023, 2024, 2025]
- Split: calibration
- Score: 0.955
- Sample size: 918
- Notes: eredivisie profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 36.2% | 33.1% | -0.030 | 0.030 |
| corners_per_match | 10.31 | 10.24 | -0.077 | 0.077 |
| shots_per_match | 27.54 | 27.01 | -0.530 | 0.530 |
| match_totals | 3.14 | 3.20 | +0.061 | 0.061 |
| home_win_rate | 44.3% | 45.3% | +0.010 | 0.010 |
| draw_rate | 25.4% | 23.3% | -0.021 | 0.021 |
| away_win_rate | 30.3% | 31.4% | +0.011 | 0.011 |
| both_teams_scored_rate | 58.3% | 66.2% | +0.079 | 0.079 |
| half_1_scoring | 1.36 | 1.42 | +0.063 | 0.063 |
| half_2_scoring | 1.77 | 1.77 | -0.003 | 0.003 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.