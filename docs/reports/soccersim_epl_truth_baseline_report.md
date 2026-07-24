# SoccerSim EPL Truth Baseline Report (v0 profile)

- Source: football-data.co.uk EPL 2023-24..2025-26
- Split: calibration
- Score: 0.970
- Sample size: 1140
- Notes: EPL v0 profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 34.8% | 34.0% | -0.009 | 0.009 |
| corners_per_match | 10.38 | 10.27 | -0.109 | 0.109 |
| shots_per_match | 26.17 | 25.79 | -0.378 | 0.378 |
| match_totals | 2.99 | 3.05 | +0.066 | 0.066 |
| home_win_rate | 43.2% | 43.1% | -0.001 | 0.001 |
| draw_rate | 24.5% | 25.3% | +0.008 | 0.008 |
| away_win_rate | 32.4% | 31.6% | -0.008 | 0.008 |
| both_teams_scored_rate | 58.3% | 63.5% | +0.052 | 0.052 |
| half_1_scoring | 1.30 | 1.40 | +0.091 | 0.091 |
| half_2_scoring | 1.68 | 1.66 | -0.024 | 0.024 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.