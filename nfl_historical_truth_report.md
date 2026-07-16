# NFL Historical Truth Report

- Date: 2026-07-15
- Source: nflverse play-by-play, 2023-2025 regular seasons (downloaded via the truth-layer loader; identical assets to `nfl_data_py.import_pbp_data`)
- Sample: 147,928 plays -> **17,677 real drives** across **816 games** (272 per season)
- Cache: `data/nfl_source/historical_truth/play_by_play_<season>.csv.gz` (offline-replayable)
- Simulator behavior: unchanged. The truth layer adapts into the existing `CalibrationBenchmarkSnapshot` contract via `HistoricalTruthSnapshot.to_calibration_snapshot()`.

## NFL Historical Truth Snapshot (2023-2025 regular season)

| Metric | Real NFL (truth) | Old proxy benchmark | Iteration 6 simulator |
| --- | --- | --- | --- |
| Possessions per game | **21.66** | 21.11 | 20.55 |
| Plays per drive | **5.93** | 4.05 | 6.90 |
| Seconds per drive | **166.2** | 166.1 | 178.8 |
| Yards per drive | **30.66** | 31.07 | 51.87 (evaluator credits punt yards) |
| Touchdown rate | **22.0%** | 24.5% | 25.6% |
| Field-goal rate (made) | **15.7%** | 16.2% | 10.7% |
| Missed field-goal rate | **2.7%** | 0.0% | 2.6% |
| Punt rate | **35.1%** | 59.0% | 42.4% |
| Turnover rate | **11.1%** | 0.4% | 6.1% |
| Turnover-on-downs rate | **5.8%** | 0.0% | 2.8% |
| End-of-half/clock rate | **7.4%** | 0.0% | 9.7% |
| Red-zone entry rate | **36.7%** | n/a (synthetic) | ~34.9% |
| Red-zone conversion | **85.5%** | 43.1% | 87.3% |
| Q1 scoring | **8.82** | 9.17 | 9.04 |
| Q2 scoring | **13.91** | 13.81 | 11.76 |
| Q3 scoring | **9.26** | 9.42 | 10.32 |
| Q4 scoring | **12.86** | 13.15 | 12.17 |
| Game totals | **45.13** | 46.24 | 43.48 |

## Explicit Answers

### Which current proxy metrics were inaccurate?

Ranked by distortion magnitude:

1. **turnover_rate: 0.4% proxy vs 11.1% real (~28x understated).** The proxy used a penalty-adjustment factor as a giveaway rate.
2. **punt_rate: 59.0% proxy vs 35.1% real (+24 points overstated).** The proxy's residual bucket absorbed turnovers, downs failures, missed FGs, and clock stops.
3. **red_zone_conversion: 43.1% proxy vs 85.5% real (understated by half).** The proxy's synthetic entry flag was not a real entry definition.
4. **turnover_on_downs: 0.0% proxy vs 5.8% real** — simply absent.
5. **missed_field_goal: 0.0% proxy vs 2.7% real** — simply absent.
6. **end-of-half/clock share: 0.0% proxy vs 7.4% real** — simply absent.
7. **plays_per_drive: 4.05 proxy vs 5.93 real** — the seconds÷pace ratio was ~32% low.

Proxy rows that were accurate: seconds per drive (166.1 vs 166.2 — essentially exact), yards per drive (31.07 vs 30.66), possessions per game (21.11 vs 21.66), quarter scoring and game totals (real game data in both).

### How different is the real NFL benchmark?

The outcome mix is structurally different: real football ends drives punt 35.1% / TD 22.0% / FG 15.7% / turnover 11.1% / end-of-half 7.4% / TOD 5.8% / missed FG 2.7% — a seven-way distribution the proxy compressed into a four-way one (punt 59 / TD 24.5 / FG 16.2 / turnover 0.4). Everything the proxy could not represent was silently reassigned to punts. Game-level rows (totals, quarters, possessions, drive time) barely move.

### Which calibration conclusions remain valid?

- **Iteration 4's FG-flood elimination and true FG range** — real made-FG rate (15.7%) confirms the proxy's 16.2% was trustworthy; the 42.3% attempt flood was genuinely broken.
- **Iteration 5's red-zone honesty work** — simulator 87.3% vs real 85.5% per-entry conversion: the simulator was already realistic, and the "remaining 0.92 normalized error" against the proxy's 43.1% was pure benchmark artifact, exactly as suspected.
- **Iteration 6's urgency/clock work** — real end-of-half share is 7.4%; the simulator's 9.7% stop share (after removing fake Q1/Q3 stops) is near reality, and the structural-floor argument is confirmed.
- **The Q2 scoring gap is genuine** — real Q2 is 13.91; the simulator's 11.76 is a real 2.2-point shortfall (Q4 12.17 vs 12.86 is much closer).
- **Made-FG volume is genuinely low** — real 15.7% vs simulator 10.7%.
- **The Data Limited verdict** — every "largest normalized error" row in Iterations 4-6 turns out to have been a fabricated benchmark value.

### Which calibration conclusions change?

1. **The punt-share "gap" inverts.** Iterations 5-6 treated 59% as the target and reported punts 17 points short. Real target is 35.1% — the simulator (42.4%) actually **overshoots punts by ~7 points**. The Iteration 5 "scoped trade-off" was a move toward reality, not away from it.
2. **The turnover conclusion reverses direction.** Every iteration fought to suppress turnovers toward 0.4% (Iterations 4-5 cut per-play turnover weight ~4x). Real drives end in giveaways 11.1% of the time — the simulator (6.1%) is now **too clean**, and some of those suppression steps should be partially unwound.
3. **Turnover-on-downs is a feature, not an error.** Real rate 5.8%; the Iteration 6 go-for-it behavior (2.8%) moved toward truth while the proxy scored it as pure regression.
4. **Missed field goals are already calibrated** (2.6% vs 2.7% real) — flagged as +0.024 pure error by the proxy since Iteration 2.
5. **Plays per drive is mildly high, not wildly high** (6.90 vs 5.93 real, not vs 4.05), and TD rate is ~3.6 points high (25.6% vs 22.0%) rather than near-perfect (vs proxy 24.5%).

## Truth Layer Components Delivered

- `syndicate/features/football/sim_engine/smartsim2/historical_truth/historical_snapshot_contract.py` — `HistoricalDriveRecord`, `HistoricalGameRecord`, `HistoricalTruthMetrics`, `HistoricalTruthSnapshot`, plus the `to_calibration_snapshot()` adapter into the existing Football Core calibration contract.
- `.../historical_truth/nfl_historical_loader.py` — season-cached acquisition (`nfl_data_py` preferred; direct nflverse release download as fallback because this workstation cannot install `nfl_data_py`'s pinned pandas<3/pyarrow set on Windows ARM64). Both paths read identical nflverse assets.
- `.../historical_truth/historical_snapshot_builder.py` — drive records (canonical seven-outcome mapping from `fixed_drive_result`, plays, time of possession, yards, points from score deltas, red-zone/goal-to-go from `yardline_100`), game records (quarter scores from cumulative score progression), and truth metrics.
- `tests/test_smartsim2_historical_truth.py` — 3 focused tests (result mapping, snapshot build, calibration-contract adaptation); all passing.

## Recommended Iteration 7 Targets (against the truth benchmark)

1. Re-point calibration runs at `HistoricalTruthSnapshot.to_calibration_snapshot()` instead of the proxy builder.
2. Partially restore per-play turnover weight (target 11.1% of drives; currently 6.1%).
3. Raise made-FG volume toward 15.7% (attempt-rate, not make-probability — makes are calibrated).
4. Reduce punt share ~7 points (will follow naturally from restoring turnovers).
5. Close the Q2 two-minute scoring gap (11.76 vs 13.91) — the one urgency behavior still under-producing.
6. Fix the evaluator's punt-yards crediting so drive yards can be measured against the real 30.66.
