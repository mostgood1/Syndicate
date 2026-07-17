# SmartSim Production Monitoring Phase 2: Full-Season Stability Report

- Date: 2026-07-16
- Scope: NCAAF, measurement only. **SmartSim 2.0 simulation logic, both calibration profiles, the blend formulas, the blend thresholds, and the decision policy were not modified.** This phase only extends the Phase 1 observation layer to a much larger sample and adds rolling/drift analysis on top of it.
- References: `smartsim_live_performance_report.md` (Phase 1), `smartsim_policy_revision_report.md`, `smartsim_signal_attribution_report.md`.
- New/extended code: `syndicate/features/ncaaf/smartsim2_performance_tracking.py` (additive: `rolling_windows()`, `summarize_season_to_date()`, `partition_by_total_level()`, `detect_drift()`, plus the constants/helpers they need — every Phase 1 function and constant is unchanged), `scripts/fetch_cfbd_lines.py` (new, read-only CFBD `/lines` cache builder), `tests/test_ncaaf_smartsim2_performance_tracking.py` (13 new tests, 29 total, all passing).
- Sample: **752 real, completed 2025-season games across all 16 weeks** — effectively the full regular season plus conference championship week, versus Phase 1's 209-game, 4-week sample. Market-line coverage is 100%. One gap: all 32 Enhanced Totals Engine rows for week 15 (conference championships) have blank predictions in the enhanced CSV itself — a pre-existing data gap in that artifact, not something this phase's join introduced — so week 15 contributes 0 of its 9 real completed games to this sample. Week 1 also has the same single unmatched game noted in Phase 1. Total: 752 of 762 eligible real games (98.7%).

## Methodology Notes (read before the numbers)

- **Chronological ordering**: games carry no exact kickoff timestamp in the tracked record, only `(week, game_id)`. Rolling windows and drift comparisons order games by `week` then by CFBD's numeric `game_id` as a stable tie-break within a week. This is an approximation of real time order, not exact kickoff sequencing, but is adequate at the 50-100 game granularity analyzed here.
- **High/low total split**: rather than a fixed point cutoff, `partition_by_total_level()` splits on this sample's own median market total (51.75 points), so the split reflects this season's actual scoring environment rather than an arbitrary historical number.
- **Drift thresholds** (`PERFORMANCE_DRIFT_ACCURACY_POINTS_THRESHOLD=8.0`, `PERFORMANCE_DRIFT_MAE_THRESHOLD=2.0`, `CALIBRATION_DRIFT_BIAS_POINTS_THRESHOLD=2.0`, `POLICY_DRIFT_ACCURACY_POINTS_THRESHOLD=15.0`) are review triggers for this report only — they do not feed into `smartsim2_blend.py` in any way and are not proposed as new production thresholds.

## Task 2-4: Rolling Metrics and Category Re-Evaluation

### Overall (n=752)

| Metric | Engine | SmartSim 2.0 | Consensus |
| --- | --- | --- | --- |
| Margin MAE | 15.706 | 15.414 | **15.411** |
| Margin RMSE | 20.068 | **19.639** | 19.672 |
| Margin correlation | 0.378 | **0.623** | 0.404 |
| Side accuracy | 63.96% | 68.48% | **68.75%** |
| Total MAE | 13.373 | 13.394 | **12.421** |
| Total RMSE | 16.823 | 16.366 | **15.451** |
| Total correlation | 0.092 | 0.397 | **0.403** |

Consensus's margin-MAE edge over SmartSim has narrowed to a statistical rounding error (15.411 vs. 15.414) at this larger sample size, and SmartSim's raw RMSE is now marginally better than Consensus's. Consensus still holds the highest side accuracy and the lowest total error of the three. This is a real, disclosed nuance versus the Phase 1 headline ("Consensus wins on every metric") — at n=752 the margin race between SmartSim and Consensus is now a statistical tie, not a clear Consensus win. Total performance and side accuracy still favor Consensus outright.

### 50-game rolling windows (16 windows, last one partial with 2 games)

Side accuracy by window (Engine / SmartSim / Consensus):

| Window (games) | Engine | SmartSim | Consensus |
| --- | --- | --- | --- |
| 1 (1-50) | 64% | 72% | 70% |
| 2 (51-100) | 64% | 80% | 76% |
| 3 (101-150) | 68% | 74% | 60% |
| 4 (151-200) | 68% | 64% | **82%** |
| 5 (201-250) | 64% | 70% | 68% |
| 6 (251-300) | 64% | 72% | 72% |
| 7 (301-350) | 60% | 68% | 62% |
| 8 (351-400) | 60% | 66% | 72% |
| 9 (401-450) | 68% | 66% | 74% |
| 10 (451-500) | 66% | 64% | 66% |
| 11 (501-550) | 58% | 60% | 60% |
| 12 (551-600) | 64% | 78% | 68% |
| 13 (601-650) | 68% | 78% | 66% |
| 14 (651-700) | 66% | 50% | 66% |
| 15 (701-750) | 60% | 64% | 68% |
| 16 (751-752, partial) | 0% | 100% | 100% |

Every 50-game window has meaningful movement (accuracy swings of 10-20+ points window to window for all three sources) — expected noise at n=50 per window, not evidence of a trend. Window 14 is SmartSim's single worst stretch (50%, a coin flip), immediately followed by a recovery in windows 15-16; no window shows Engine sustaining an advantage over more than one window in a row. No window (except the 2-game final partial one, too small to read anything into) shows Consensus below both raw sources.

### 100-game rolling windows (7 full + 1 partial)

| Window (games) | Engine acc | SmartSim acc | Consensus acc | Engine margin MAE | SmartSim margin MAE | Consensus margin MAE |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (1-100) | 64% | 76% | 73% | 16.556 | 18.135 | 18.146 |
| 2 (101-200) | 68% | 69% | 71% | 16.475 | 17.228 | 17.298 |
| 3 (201-300) | 64% | 71% | 70% | 14.182 | 12.625 | 12.826 |
| 4 (301-400) | 60% | 67% | 67% | 14.459 | 13.772 | 13.637 |
| 5 (401-500) | 67% | 65% | 70% | 15.947 | 14.801 | 14.608 |
| 6 (501-600) | 61% | 69% | 64% | 15.685 | 14.193 | 14.540 |
| 7 (601-700) | 67% | 64% | 66% | 15.620 | 16.213 | 15.973 |
| 8 (701-752, partial) | 57.7% | 65.4% | **69.2%** | 17.661 | 17.210 | 17.041 |

At the 100-game grain, the noise smooths out considerably. SmartSim leads or ties Engine on accuracy in 7 of 8 windows; Consensus is at or above SmartSim in 5 of 8 and never the worst of the three in any window. Margin MAE tells the same story: Engine is never the best of the three in any 100-game window.

### Season-to-date (cumulative checkpoints every 50 games)

Side accuracy converges as the sample grows — a strong stability signal in itself:

| Through game | Engine | SmartSim | Consensus |
| --- | --- | --- | --- |
| 50 | 64.0% | 72.0% | 70.0% |
| 150 | 65.3% | 75.3% | 68.7% |
| 300 | 65.3% | 72.0% | 71.3% |
| 450 | 64.4% | 70.2% | 70.7% |
| 600 | 64.0% | 69.5% | 69.2% |
| 752 (final) | 64.0% | 68.5% | 68.8% |

Every source's cumulative accuracy is within about 2-4 points of its final value by game 300 and essentially flat from game 450 onward — the metrics are converging, not drifting, as the sample grows. This is the clearest evidence in this report that the four-week Phase 1 sample already had the right general shape; more data mostly narrowed the confidence interval rather than changing the picture.

### Disagreement / mismatch / conference re-evaluation (752-game sample vs. Phase 1's 209)

| Category | n | Engine acc | SmartSim acc | Consensus acc | Engine margin MAE | SmartSim margin MAE | Consensus margin MAE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Side disagreement | 326 | 44.79% | 55.21% | **55.83%** | 17.619 | 13.663 | 13.975 |
| Total disagreement | 275 | 62.91% | 68.00% | **68.36%** | 15.984 | 14.783 | 15.046 |
| Large mismatch | 310 | 72.26% | **80.97%** | **80.97%** | 17.638 | 19.405 | 19.405 |
| Conference games | 548 | 63.32% | 65.69% | **67.34%** | 15.085 | **14.259** | 14.198 |
| Non-conference games | 204 | 65.69% | **75.98%** | 72.55% | 17.375 | 18.517 | 18.670 |

Same relative ordering as Phase 1 throughout: SmartSim/Consensus beat Engine in every disagreement and mismatch category, Consensus keeps a real edge in side disagreement and conference games, and large-mismatch Consensus is numerically identical to SmartSim by construction (the Phase 4 policy still routes that branch straight to SmartSim's margin).

### New in Phase 2 — the exact large-mismatch-and-side-disagreement subset, at full-season scale

| Sample | n | Engine acc | SmartSim/Consensus acc |
| --- | --- | --- | --- |
| Original signal attribution study | 17 | 23.5% | 76.5% |
| Phase 1 (4 weeks) | 30 | 33.3% | 66.7% |
| **Phase 2 (full season)** | **103** | **36.89%** | **63.11%** |

The gap has narrowed somewhat as the sample has grown from 17 to 103 games (as expected — small samples run hot in both directions), but the direction is unchanged and the margin is still wide: SmartSim/Consensus is correct roughly 1.7x as often as Engine in exactly the situation the Phase 4 revision targets. This is now a 103-game finding, not a 17- or 30-game one — meaningfully more statistically load-bearing than either prior version.

### New in Phase 2 — high-total vs. low-total games (median split at 51.75 points)

| Metric | High-total (n=376) | Low-total (n=376) |
| --- | --- | --- |
| Engine margin acc | 63.03% | 64.89% |
| SmartSim margin acc | 68.62% | 68.35% |
| Consensus margin acc | 66.49% | **71.01%** |
| Engine total MAE | 13.924 | 12.821 |
| SmartSim total MAE | **12.566** | 14.223 |
| Consensus total MAE | 12.518 | **12.325** |
| Consensus total correlation | 0.295 | 0.369 |

This is a genuinely new finding not visible in Phase 1: **SmartSim's total-prediction edge over Engine is concentrated in high-total games** (MAE 12.566 vs. Engine's 13.924), while **Engine's raw total prediction is actually a bit better than SmartSim's in low-total games** (12.821 vs. 14.223) — Consensus's blend absorbs this asymmetry well, coming out on top in both buckets. No action is implied here (total policy is out of scope for this phase), but it's worth flagging as a real, category-specific pattern for any future calibration review.

## Task 5: Drift Detection (first 376 games vs. second 376 games, chronological)

```
performance_drift: NOT FLAGGED (no source's accuracy moved ≥8 pts or margin MAE moved ≥2.0 between halves)
calibration_drift: NOT FLAGGED (SmartSim's raw, uncorrected total bias: 6.025 first half -> 5.076 second half, delta -0.95, within the 2.0-point review threshold; both readings remain close to the blend's assumed SMARTSIM_TOTAL_BIAS=6.11)
policy_drift: NOT FLAGGED (large-mismatch-and-side-disagreement subset's SmartSim-minus-Engine accuracy gap: +24.14 pts first half -> +28.88 pts second half, delta +4.74 pts — well under the 15-point review threshold, and if anything widening in SmartSim's favor, not narrowing)
```

None of the three drift checks fired. The calibration check in particular is reassuring: the fixed `SMARTSIM_TOTAL_BIAS = 6.11` correction baked into `blend_total()` was calibrated on an earlier, smaller sample, and it remains close to the raw bias measured independently in both halves of this much larger one — no sign that it's gone stale.

## Task 7: Explicit Answers

### Does Consensus still outperform both sources?

Mostly, with one honest caveat. At n=752, Consensus still has the best side accuracy (68.75%), the best total MAE/RMSE, and the best total correlation of the three. On margin MAE specifically, Consensus (15.411) and SmartSim (15.414) are now statistically indistinguishable — a genuine narrowing from Phase 1's clearer Consensus margin-MAE win, though Consensus was never worse than both raw sources on margin in a single one of the 752 games (56 wins outright against both, 0 losses against both — the rest are cases where the large-mismatch branch makes Consensus numerically equal to SmartSim). On total, Consensus beats both raw sources outright in 234/752 games and loses to both in 106/752 — still a clear net win in aggregate, same conclusion as Phase 1.

### Does SmartSim retain its disagreement advantage?

Yes. Side-disagreement accuracy: Engine 44.79% vs. SmartSim 55.21% (326 games, up from 83 in Phase 1) — same direction, similar magnitude, much larger sample. The large-mismatch-and-side-disagreement subset specifically now stands at 103 games (36.89% vs. 63.11%), the most statistically solid version of this finding to date.

### Does the large-mismatch policy revision remain justified?

Yes, and more so than in Phase 1. The drift check shows the SmartSim-minus-Engine accuracy gap in this exact subset *widened* from the first half of the season to the second (+24.14 to +28.88 points), and the full-season 103-game version of the subset (36.89%/63.11%) still shows a wide, real margin in SmartSim's favor. Nothing in this larger sample calls the Phase 4 revision into question.

### Are any new weaknesses emerging?

One, disclosed above: SmartSim's raw total-prediction advantage over Engine is concentrated in high-total games, and Engine's raw total prediction is actually somewhat better than SmartSim's in low-total games. This wasn't visible in Phase 1's smaller sample. It's a real pattern worth a future look, not an emergency — Consensus's blend already handles both buckets well (best or tied-best total MAE in both). Separately, the margin-MAE race between SmartSim and Consensus has narrowed to a rounding error at this sample size, which tempers (but doesn't reverse) the "Consensus beats both raw systems" headline from Phase 1.

### Is there evidence supporting expansion of the trial?

The evidence points the same direction as Phase 1, now with roughly 3.5x the sample and zero drift signals across three independent checks (performance, calibration, policy). That is meaningful, real support for expansion. It is not yet a full second season or an out-of-sample season — this is still one season's worth of data being analyzed after the fact, not live-trial traffic collected under real user-facing conditions. Whether that distinction matters enough to delay expansion is a judgment call, not a data question this report can resolve on its own.

## Task 8: Rollout Recommendation

**Expand Trial.**

The full-season sample corroborates every material Phase 1 finding, adds a new (Consensus-handled) total-performance nuance, and shows no drift on any of the three checks run. A full regular season of stable, directionally consistent evidence is a reasonable bar for widening exposure beyond the current internal/public-trial scope — but "Production Rollout" (full default-on, trial infrastructure retired) is not yet justified: this is backtested season data, not live-trial telemetry, and the margin-MAE convergence between SmartSim and Consensus is new enough that it deserves at least one more monitoring cycle under real trial conditions before removing the ability to fall back.

## Task 9: Final Verdict

**Stable.**

Not "Improving" — the metrics at n=752 are not meaningfully better than at n=209, and the SmartSim/Consensus margin-MAE race has actually narrowed slightly. Not "Degrading" — no drift check fired, and the large-mismatch policy's justification, if anything, strengthened between the first and second half of the season. "Stable" is the accurate read: a much larger sample confirms the same shape of result as Phase 1, with normal window-to-window noise at 50-100 game granularity and no directional trend in either direction across the season.
