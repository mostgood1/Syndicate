# SmartSim 2.0 NFL Truth Recalibration Report

- Date: 2026-07-15
- Benchmark: **HistoricalTruthSnapshot** — 17,677 real drives, 816 regular-season games, nflverse PBP 2023-2025, adapted through `to_calibration_snapshot()`
- Simulation workload: 532 games (2025 wk17/wk18/wk20 game summaries), unchanged for comparability with Iterations 1-6
- Evaluation path: new additive `calibration/truth_audit.py` (`load_truth_audit_result`) — Football Core architecture, Historical Truth Layer, and calibration framework contracts untouched
- Tests: 19/19 passing

## Success Criterion Met

Simulator evaluation now runs entirely against historical NFL truth data. The proxy benchmark is no longer part of the evaluation path (its builder remains only to supply the replayable simulation inputs).

## Truth vs Simulator Comparison (final state)

| Metric | NFL Truth | Simulator (before) | Simulator (recalibrated) | Norm Err (before -> after) |
| --- | --- | --- | --- | --- |
| possessions_per_game | 21.66 | 20.55 | **21.69** | 0.051 -> 0.001 |
| drive_length_seconds | 166.2 | 178.8 | **169.6** | 0.075 -> 0.020 |
| game_totals | 45.13 | 43.48 | **44.15** | 0.036 -> 0.022 |
| red_zone_conversion_rate | 87.8% | 87.3% | **85.4%** | 0.007 -> 0.028 |
| drive_length_yards | 30.66 | 34.51* | **32.26** | 0.126 -> 0.052 |
| punt_rate | 35.1% | 42.4% | **37.2%** | 0.208 -> 0.059 |
| quarter_1_scoring | 8.82 | 9.04 | 9.38 | 0.025 -> 0.063 |
| touchdown_rate | 22.0% | 25.6% | **23.5%** | 0.165 -> 0.068 |
| quarter_4_scoring | 12.86 | 12.17 | 11.89 | 0.053 -> 0.075 |
| quarter_2_scoring | 13.91 | 11.76 | **12.44** | 0.155 -> 0.106 |
| quarter_3_scoring | 9.26 | 10.32 | 10.32 | 0.115 -> 0.115 |
| drive_length_plays | 5.93 | 6.90 | **6.62** | 0.164 -> 0.117 |
| turnover_rate (incl. downs) | 17.1% | 9.0% | **13.8%** | 0.476 -> 0.191 |
| field_goal_rate | 18.4%** | 10.7% | **13.0%** | 0.419 -> 0.293 |

\* before-value includes the punt-yardage crediting defect, fixed this iteration.
\** benchmark row counts FG attempts (made 15.7% + missed 2.7%); simulated made-FG share is 13.0% with attempts at 16.2%.

### Drive-Ending Frequency Audit vs Truth

| Outcome | Truth | Simulator | Gap |
| --- | --- | --- | --- |
| touchdown | 0.220 | 0.235 | +0.015 |
| field_goal | 0.157 | 0.130 | -0.027 |
| missed_field_goal | 0.027 | 0.032 | +0.005 |
| punt | 0.351 | 0.372 | +0.021 |
| turnover | 0.113 | 0.100 | -0.013 |
| turnover_on_downs | 0.058 | 0.039 | -0.019 |
| end_of_quarter_stop | 0.000 | 0.010 | +0.010 |
| end_of_half_stop | 0.074 | 0.083 | +0.009 |

Every drive-ending share is now within 2.7 points of measured NFL reality — a seven-way outcome distribution matched, not the proxy's four-way fiction.

## Changes Made

- **Evaluation path**: `calibration/truth_audit.py` (additive) — builds the truth snapshot from the cached nflverse mirror, adapts it into the existing benchmark contract, and evaluates the standard 532-game workload against it.
- **Bookkeeping fix**: drive yardage no longer credits punt net distance (special-teams yardage), making `drive_length_yards` genuinely measurable (34.51 -> 32.26 vs truth 30.66).
- **Turnovers restored** (proxy had forced ~4x suppression): per-play giveaway weight raised in stages to `0.07 + long_yardage*0.04` — drives ending in giveaways rose 6.1% -> 10.0% (truth 11.3%).
- **Fourth-down aggression** (truth TOD 5.8% vs sim 2.8%): neutral 4th-and-short go-for-it (punt only ~38% on 4th-and-<=3 past the 42; ~68% on 4th-and-<=6 past the 55), real conversion attempts on declined kicks (52% max, distance-scaled) instead of automatic failure.
- **FG volume up** (truth attempts 18.4%): long-range fringe attempts (53-55 yd kicks at 55%), in-range attempt probability 0.85-0.97, deeper scoring-zone stiffening (gain x0.82), red-zone TD boost trimmed 0.55 -> 0.36 so red-zone stalls settle for three.
- **Two-minute drill sharpened** (truth Q2 13.91): explosive passing x1.45 and small TD lift in hurry-up, urgency-kick window widened to 90 seconds.

## Metrics Now Validated (near truth, <= 0.08 normalized error)

possessions_per_game (0.001), drive_length_seconds (0.020), game_totals (0.022), red_zone_conversion_rate (0.028), drive_length_yards (0.052), punt_rate (0.059), quarter_1_scoring (0.063), touchdown_rate (0.068), quarter_4_scoring (0.075) — nine of fourteen metrics.

## Metrics Previously Misdiagnosed by the Proxy

- **punt_rate**: proxy demanded 59%; the simulator was pushed to 53.9% in Iteration 4 and scored as 17 points short in Iterations 5-6. Truth is 35.1% — the "shortfall" was overshoot.
- **turnover_rate**: proxy demanded 0.4%; three iterations suppressed giveaways toward fiction. Truth is 17.1% including downs — the correction ran the opposite direction.
- **turnover_on_downs / missed FG / clock stops**: proxy scored all three as pure error (target 0). All three are real football (5.8% / 2.7% / 7.4%) and the simulator now matches within ~2 points.
- **red_zone_conversion**: proxy target 43.1% made the simulator look catastrophically wrong; truth is 87.8% and the simulator has been realistic since Iteration 5.
- **plays_per_drive**: proxy target 4.05 scored honest drive length as regression; truth is 5.93.

## Largest Remaining True Simulator Errors (priority order)

1. **Field-goal volume** (norm err 0.293): made FGs 13.0% vs 15.7%; attempts 16.2% vs 18.4%. The residual sits in scoring-opportunity shape — drives reach the fringe less often than real offenses. Next lever: field-position-conditional series conversion rather than more gate tuning.
2. **Turnover mix** (0.191): total giveaways 13.8% vs 17.1%; both interception/fumble (10.0 vs 11.3) and downs (3.9 vs 5.8) are slightly clean. Next lever: 4th-down decision model conditioned on score/time (real teams go for it far more when trailing in Q3, not only Q4).
3. **Drive length plays** (0.117): 6.62 vs 5.93 — plays run slightly long even after shortening; partially offset by near-exact drive seconds, implying per-play clock is marginally fast.
4. **Q2/Q3 scoring shape** (0.106/0.115): the halftime push is still ~1.5 points light and Q3 ~1 point heavy; end-of-half urgency needs a stronger midfield hurry-up rather than more red-zone potency.

## Explicit Answers

- **What calibration conclusions changed?** The two headline targets inverted: punts needed to come *down* (not up 17 points) and turnovers needed to come *up* ~2x (not down toward 0.4%). Iterations 4-6's suppression of giveaways and inflation of punt share were partially reversed. Missed FGs, downs failures, and clock stops are now targets to match, not errors to eliminate.
- **Which previous "errors" disappeared?** Red-zone conversion (0.925 -> 0.028 normalized error against the correct target), turnover_rate's headline 20+ normalized error (an artifact of the 0.4% proxy row), plays-per-drive's "overshoot" against 4.05, missed-FG share (+0.024 "pure error" now a 0.005 match), turnover-on-downs and end-of-half stops (previously benchmark-impossible outcomes, now within 2 points), and the drive-yards inflation (evaluator bookkeeping, fixed).
- **What is now the largest genuine simulator error?** Field-goal volume — made FGs 2.7 points below truth (13.0% vs 15.7%), rooted in scoring-opportunity creation on the fringe of kick range. Second: total giveaway rate 3.3 points light.
- **How close is SmartSim to NFL historical truth?** Nine of fourteen metrics within 8% of measured reality; possessions, drive time, totals, and red-zone behavior essentially exact (0.1-2.8%); all seven drive-outcome shares within 2.7 points; every metric within 0.30 normalized error against real data — versus normalized errors of 20+ against the proxy one day ago.

## Final Verdict

**Near Historical Truth.**

The simulator now reproduces the real NFL outcome distribution, pace, possession economy, and scoring ecology to within a few points across the board, evaluated entirely against 17,677 measured drives. It is not yet a Historical Truth Candidate: FG volume, giveaway mix, and the Q2/Q3 scoring shape remain outside the ~5% band, and holdout-split validation (calibrate on 2023-2024, verify on 2025) has not yet been run. These, plus score/time-conditioned 4th-down decisions, define the NFL calibration profile's remaining work inside the shared SmartSim Football Core.
