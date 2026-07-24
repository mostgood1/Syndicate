# SmartSim 2.0 NFL Validation Report

- Date: 2026-07-15
- Simulator: frozen at the truth-recalibrated state (no behavior modified for this phase)
- Validation design: the calibrated profile (tuned against pooled 2023-2025 truth) is evaluated against **three per-season truth folds** (2023: 6,058 drives; 2024: 5,875; 2025: 5,744; 272 games each) plus the pooled benchmark, and re-run with **perturbed seeds** to measure stochastic run-to-run noise. Simulation workload: the standard 532-game input set, identical across folds.

## Method

Because the profile was calibrated against the pooled sample, each individual season acts as a test fold: a profile that merely memorized the pooled mixture would show low pooled error but inconsistent, direction-flipping errors per season. A generalizing profile should sit inside the natural season-to-season range of real football, with per-fold errors comparable to the pooled error. The seed-replay run separates genuine calibration bias from Monte Carlo noise.

## Per-Fold Results

| Metric | Truth 2023 | Truth 2024 | Truth 2025 | Simulator | Err 23 | Err 24 | Err 25 | Seed replay |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| possessions_per_game | 22.27 | 21.60 | 21.12 | 21.69 | 0.026 | 0.004 | 0.027 | 21.47 |
| touchdown_rate | 20.3% | 22.7% | 23.1% | 23.5% | 0.157 | 0.037 | 0.016 | 24.1% |
| field_goal_rate (attempts) | 17.5% | 18.9% | 18.9% | 13.0%* | 0.255 | 0.312 | 0.311 | 12.8% |
| turnover_rate (incl. downs) | 17.7% | 16.4% | 17.2% | 13.8% | 0.219 | 0.154 | 0.197 | 13.6% |
| punt_rate | 37.2% | 34.7% | 33.4% | 37.2% | 0.000 | 0.072 | 0.114 | 37.0% |
| quarter_1_scoring | 8.61 | 8.64 | 9.22 | 9.38 | 0.089 | 0.086 | 0.018 | 9.68 |
| quarter_2_scoring | 13.74 | 14.14 | 13.86 | 12.44 | 0.094 | 0.120 | 0.102 | 12.71 |
| quarter_3_scoring | 8.75 | 9.61 | 9.41 | 10.32 | 0.180 | 0.074 | 0.097 | 9.85 |
| quarter_4_scoring | 12.21 | 13.15 | 13.22 | 11.89 | 0.026 | 0.096 | 0.100 | 12.08 |
| game_totals | 43.54 | 45.82 | 46.03 | 44.15 | 0.014 | 0.036 | 0.041 | 44.44 |
| drive_length_plays | 5.84 | 5.95 | 5.99 | 6.62 | 0.133 | 0.113 | 0.104 | 6.64 |
| drive_length_seconds | 161.5 | 166.7 | 170.7 | 169.6 | 0.050 | 0.018 | 0.006 | 170.8 |
| red_zone_conversion_rate | 87.3% | 87.8% | 88.4% | 85.4% | 0.022 | 0.028 | 0.034 | 85.5% |

\* simulated made-FG share; the benchmark row counts attempts (made + missed). Simulated attempts = 16.2%.

### Drive-Outcome Shares by Fold

| Outcome | 2023 | 2024 | 2025 | Simulator |
| --- | --- | --- | --- | --- |
| touchdown | 0.203 | 0.227 | 0.231 | 0.235 |
| field_goal | 0.150 | 0.159 | 0.162 | 0.130 |
| missed_field_goal | 0.024 | 0.030 | 0.027 | 0.032 |
| punt | 0.372 | 0.347 | 0.334 | 0.372 |
| turnover | 0.120 | 0.111 | 0.109 | 0.100 |
| turnover_on_downs | 0.058 | 0.053 | 0.063 | 0.039 |
| end_of_half_stop | 0.073 | 0.074 | 0.074 | 0.083 |

### Stochastic Noise Floor (seed replay)

Re-running the identical workload with perturbed seeds moves quarter scoring by ±0.2-0.5 points, rates by ±0.2-0.6 points, and possessions by ±0.22 — a noise floor of roughly 0.02-0.05 normalized error. Differences inside that band are Monte Carlo noise, not calibration signal.

## Explicit Answers

### Does calibration generalize?

**Yes.** The simulator sits inside or immediately adjacent to the natural season-to-season range of real football on possessions (21.69 vs range 21.12-22.27), game totals (44.15 vs 43.54-46.03), TD rate (23.5% vs 20.3-23.1%), punt rate (37.2% vs 33.4-37.2%), drive seconds (169.6 vs 161.5-170.7), and red-zone conversion (85.4% vs 87.3-88.4%). Per-fold errors are the same magnitude as the pooled error on almost every metric — no fold collapses.

### Is there evidence of overfitting?

**No.** The overfitting signature — low pooled error with erratic, direction-flipping per-fold errors — does not appear. Where the simulator misses, it misses **in the same direction and magnitude in all three seasons** (FG volume low by ~5 points everywhere; giveaways low by ~3 points everywhere; plays/drive high by ~0.65 everywhere). That is stable systematic bias, which is correctable, not memorization of the pooled mixture. One mild blend artifact exists: punt share matches 2023 exactly while TD rate matches 2025 best, reflecting the real secular trend (punts declining 37.2% -> 33.4%, TDs rising 20.3% -> 23.1% across the three seasons). The simulator represents a 2023-2025 average era rather than tracking the drift — expected for a pooled calibration and acceptable within the observed range.

### Which metrics remain unstable?

- **Quarter scoring (Q1-Q4)** is the noisiest family: cross-season truth itself moves ±0.5-1.0 points and seed replay moves the simulator ±0.2-0.5, so most single-quarter comparisons sit near the noise floor. Only Q2 (12.44 vs 13.7-14.1 in every season) is a bias, not noise.
- **Stable and biased (real errors, consistent in every fold):** FG attempt volume (16.2% vs 17.5-18.9%), giveaways (13.8% vs 16.4-17.7%, driven mostly by turnover-on-downs 3.9% vs 5.3-6.3%), and plays per drive (6.62 vs 5.84-5.99).
- **Stable and accurate:** possessions, totals, drive seconds, punt share, red-zone conversion, TD rate.

### Is the NFL profile ready to freeze?

**Structurally yes; numerically almost.** The outcome distribution, possession economy, pace, and scoring ecology generalize across three seasons with no overfitting. Three known biases (FG volume, giveaway mix, plays/drive) are stable across every fold, which means one targeted calibration pass can correct them without re-validation risk. Recommended freeze path: apply that single pass, re-run this exact three-fold validation, and freeze if the per-fold error profile is preserved. Freezing today would ship a usable profile with documented biases.

## Final Verdict

**Validated.**

The NFL calibration profile generalizes across the 2023, 2024, and 2025 seasons with per-fold errors matching pooled errors and no evidence of overfitting; its remaining defects are three well-characterized, direction-stable biases plus a Q2 hurry-up shortfall — all outside the stochastic noise floor and all previously identified in the recalibration report. It is not yet a Production Candidate solely because those biases exceed the ~5% band on four metrics; after one corrective pass and a re-run of this validation, it is the intended first official SmartSim Football Core profile.
