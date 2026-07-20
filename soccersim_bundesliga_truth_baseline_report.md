# SoccerSim BUNDESLIGA Truth Baseline Report

- Source: football-data.co.uk bundesliga [2023, 2024, 2025]
- Split: calibration
- Score: 0.953
- Sample size: 918
- Notes: bundesliga profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 36.1% | 33.9% | -0.021 | 0.021 |
| corners_per_match | 9.75 | 10.18 | +0.431 | 0.431 |
| shots_per_match | 26.47 | 26.02 | -0.448 | 0.448 |
| match_totals | 3.20 | 3.13 | -0.065 | 0.065 |
| home_win_rate | 42.0% | 44.8% | +0.028 | 0.028 |
| draw_rate | 25.4% | 25.8% | +0.004 | 0.004 |
| away_win_rate | 32.6% | 29.4% | -0.032 | 0.032 |
| both_teams_scored_rate | 60.1% | 66.8% | +0.067 | 0.067 |
| half_1_scoring | 1.47 | 1.41 | -0.063 | 0.063 |
| half_2_scoring | 1.72 | 1.72 | -0.002 | 0.002 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.