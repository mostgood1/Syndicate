# SoccerSim LA_LIGA Truth Baseline Report

- Source: football-data.co.uk la_liga [2023, 2024, 2025]
- Split: calibration
- Score: 0.968
- Sample size: 1140
- Notes: la_liga profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 34.8% | 33.8% | -0.010 | 0.010 |
| corners_per_match | 9.52 | 9.62 | +0.099 | 0.099 |
| shots_per_match | 24.38 | 24.14 | -0.237 | 0.237 |
| match_totals | 2.65 | 2.69 | +0.036 | 0.036 |
| home_win_rate | 45.8% | 46.2% | +0.004 | 0.004 |
| draw_rate | 26.1% | 27.3% | +0.012 | 0.012 |
| away_win_rate | 28.2% | 26.5% | -0.017 | 0.017 |
| both_teams_scored_rate | 53.4% | 58.0% | +0.046 | 0.046 |
| half_1_scoring | 1.17 | 1.22 | +0.052 | 0.052 |
| half_2_scoring | 1.49 | 1.47 | -0.016 | 0.016 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.