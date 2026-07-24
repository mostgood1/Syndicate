# SoccerSim MLS Truth Baseline Report

- Source: American Soccer Analysis MLS 2026 (games + season shot-rate proxy)
- Split: calibration
- Score: 0.964
- Sample size: 223
- Notes: MLS profile audit vs ASA 2026 season-to-date, 1000 simulated matches, neutral teams, shots are team-season-average proxy, not per-game, corners/SOT/half-split not available from this source -- excluded from scoring

## Target Metrics

| Metric | Benchmark | Simulated | Error | Absolute Error |
| --- | --- | --- | --- | --- |
| shots_per_match | 25.74 | 25.33 | -0.413 | 0.413 |
| match_totals | 3.30 | 3.20 | -0.097 | 0.097 |
| home_win_rate | 48.0% | 48.7% | +0.007 | 0.007 |
| draw_rate | 22.0% | 22.8% | +0.008 | 0.008 |
| away_win_rate | 30.0% | 28.5% | -0.015 | 0.015 |
| both_teams_scored_rate | 61.0% | 65.2% | +0.042 | 0.042 |

## Interpretation

- Lower error means the simulator is closer to historical soccer shape.
- Possession length and possessions per match should stabilize before scoring and totals are trusted.
- Result-rate metrics (home/draw/away, both-teams-scored) should be read as aggregate checks after the possession layer is aligned.