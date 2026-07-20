# SoccerSim SERIE_A Truth Baseline Report

- Source: football-data.co.uk serie_a [2023, 2024, 2025]
- Split: calibration
- Score: 0.962
- Sample size: 1140
- Notes: serie_a profile baseline audit, 1000 simulated matches, neutral teams

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shot_on_target_share | 32.9% | 34.2% | +0.012 | 0.012 |
| corners_per_match | 9.25 | 9.62 | +0.367 | 0.367 |
| shots_per_match | 24.75 | 24.09 | -0.667 | 0.667 |
| match_totals | 2.53 | 2.48 | -0.051 | 0.051 |
| home_win_rate | 40.2% | 42.1% | +0.019 | 0.019 |
| draw_rate | 28.0% | 26.7% | -0.013 | 0.013 |
| away_win_rate | 31.8% | 31.2% | -0.006 | 0.006 |
| both_teams_scored_rate | 49.7% | 53.2% | +0.035 | 0.035 |
| half_1_scoring | 1.10 | 1.12 | +0.022 | 0.022 |
| half_2_scoring | 1.44 | 1.36 | -0.074 | 0.074 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.