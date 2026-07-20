# SoccerSim CHAMPIONSHIP Truth Baseline Report

- Source: football-data.co.uk championship [2023, 2024, 2025]
- Split: calibration
- Score: 0.982
- Sample size: 1656
- Notes: championship profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 32.9% | 33.6% | +0.007 | 0.007 |
| corners_per_match | 10.40 | 10.53 | +0.137 | 0.137 |
| shots_per_match | 24.66 | 24.28 | -0.376 | 0.376 |
| match_totals | 2.58 | 2.58 | +0.005 | 0.005 |
| home_win_rate | 44.0% | 42.2% | -0.018 | 0.018 |
| draw_rate | 26.0% | 26.6% | +0.006 | 0.006 |
| away_win_rate | 30.0% | 31.2% | +0.012 | 0.012 |
| both_teams_scored_rate | 53.1% | 54.3% | +0.012 | 0.012 |
| half_1_scoring | 1.18 | 1.18 | +0.001 | 0.001 |
| half_2_scoring | 1.40 | 1.40 | +0.004 | 0.004 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.