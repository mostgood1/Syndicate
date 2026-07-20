# SoccerSim LIGUE_1 Truth Baseline Report

- Source: football-data.co.uk ligue_1 [2023, 2024, 2025]
- Split: calibration
- Score: 0.948
- Sample size: 918
- Notes: ligue_1 profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 36.1% | 33.4% | -0.027 | 0.027 |
| corners_per_match | 9.45 | 9.56 | +0.116 | 0.116 |
| shots_per_match | 25.02 | 24.09 | -0.937 | 0.937 |
| match_totals | 2.83 | 2.78 | -0.054 | 0.054 |
| home_win_rate | 44.0% | 40.2% | -0.038 | 0.038 |
| draw_rate | 23.7% | 26.9% | +0.032 | 0.032 |
| away_win_rate | 32.2% | 32.9% | +0.007 | 0.007 |
| both_teams_scored_rate | 53.8% | 59.5% | +0.057 | 0.057 |
| half_1_scoring | 1.25 | 1.24 | -0.009 | 0.009 |
| half_2_scoring | 1.59 | 1.54 | -0.045 | 0.045 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.