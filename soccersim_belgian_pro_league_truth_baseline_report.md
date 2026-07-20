# SoccerSim BELGIAN_PRO_LEAGUE Truth Baseline Report

- Source: football-data.co.uk belgian_pro_league [2023, 2024, 2025]
- Split: calibration
- Score: 0.958
- Sample size: 935
- Notes: belgian_pro_league profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 34.9% | 33.6% | -0.013 | 0.013 |
| corners_per_match | 10.01 | 10.14 | +0.128 | 0.128 |
| shots_per_match | 26.26 | 24.99 | -1.264 | 1.264 |
| match_totals | 2.75 | 2.59 | -0.158 | 0.158 |
| home_win_rate | 43.0% | 42.2% | -0.008 | 0.008 |
| draw_rate | 26.7% | 28.3% | +0.016 | 0.016 |
| away_win_rate | 30.3% | 29.5% | -0.008 | 0.008 |
| both_teams_scored_rate | 54.1% | 56.8% | +0.027 | 0.027 |
| half_1_scoring | 1.26 | 1.17 | -0.085 | 0.085 |
| half_2_scoring | 1.49 | 1.42 | -0.073 | 0.073 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.