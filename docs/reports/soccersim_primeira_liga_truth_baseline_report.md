# SoccerSim PRIMEIRA_LIGA Truth Baseline Report

- Source: football-data.co.uk primeira_liga [2023, 2024, 2025]
- Split: calibration
- Score: 0.952
- Sample size: 918
- Notes: primeira_liga profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 35.3% | 33.3% | -0.020 | 0.020 |
| corners_per_match | 9.71 | 9.94 | +0.230 | 0.230 |
| shots_per_match | 23.68 | 24.17 | +0.493 | 0.493 |
| match_totals | 2.71 | 2.71 | +0.000 | 0.000 |
| home_win_rate | 42.6% | 43.4% | +0.008 | 0.008 |
| draw_rate | 25.8% | 27.2% | +0.014 | 0.014 |
| away_win_rate | 31.6% | 29.4% | -0.022 | 0.022 |
| both_teams_scored_rate | 50.1% | 59.2% | +0.091 | 0.091 |
| half_1_scoring | 1.20 | 1.23 | +0.036 | 0.036 |
| half_2_scoring | 1.51 | 1.47 | -0.036 | 0.036 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.