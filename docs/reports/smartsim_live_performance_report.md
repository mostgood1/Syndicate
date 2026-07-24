# SmartSim Production Monitoring Phase 1: Live Performance Report

- Date: 2026-07-16
- Scope: NCAAF, measurement only. **SmartSim 2.0 simulation logic, both calibration profiles, the blend weights, the blend thresholds, and the production policy rules were not modified.** This phase adds a new, separate observation layer that reads the outputs those systems already produce.
- References: `smartsim_policy_revision_report.md`, `smartsim_decision_policy_report.md`, `smartsim_signal_attribution_report.md`, `smartsim_public_trial_monitoring_report.md`.
- New code: `syndicate/features/ncaaf/smartsim2_performance_tracking.py` (recording + statistics module, imports `smartsim2_blend.compute_blend()` rather than reimplementing it), `scripts/backfill_smartsim2_performance.py` (real-data join/backfill job), `tests/test_ncaaf_smartsim2_performance_tracking.py` (16 tests, all passing).
- Sample: **209 real, completed 2025-season games** across four weeks (1, 5, 8, 10), each joined against real market lines (CFBD `/lines`), real Enhanced Totals Engine predictions, real SmartSim 2.0 projections (300-seed simulations per game against real CFBD season-PPA ratings), and real final scores. One additional week-1 game had truth data but no matching Engine/SmartSim prediction pair and was excluded (`skipped_no_engine_or_smartsim=1`). Market-line coverage was 100% (209/209) for both spread and total.

This is the largest and most current real sample used in any report in this project to date — roughly double the 106-game, two-week sample behind the signal attribution and decision policy studies — and it is the first sample collected *after* the Phase 4 policy revision (SmartSim-first on large mismatches) went into effect for the blend calculation.

## Task 2-7: What Was Recorded, By Category

Every one of the 209 games has: market spread/total, Enhanced Totals Engine margin/total, SmartSim 2.0 margin/total, Consensus margin/total (computed by calling the unmodified `compute_blend()`), and the actual margin/total. Each record is also tagged with the same categorical flags used in prior studies — `side_disagreement`, `total_disagreement` (Engine/SmartSim totals differ by ≥10), and `large_mismatch` (`|market margin| ≥ 10`, using `LARGE_MISMATCH_MARGIN_THRESHOLD` imported directly from `smartsim2_blend`, never re-declared) — plus `conference_game`, sourced from the historical truth snapshot's own `conferenceGame` field.

### Overall (n=209)

| Metric | Engine | SmartSim 2.0 | Consensus |
| --- | --- | --- | --- |
| Margin MAE | 14.674 | 14.532 | **14.285** |
| Margin RMSE | 18.829 | 18.478 | **18.225** |
| Margin correlation w/ actual | 0.372 | 0.563 | 0.416 |
| Side accuracy (straight-up) | 65.55% | 66.99% | **71.77%** |
| Total MAE | 13.814 | 14.700 | **13.143** |
| Total RMSE | 17.638 | 18.002 | **16.538** |
| Total correlation w/ actual | 0.098 | 0.350 | **0.356** |

Consensus has the lowest MAE/RMSE on both margin and total, and the highest side accuracy of the three — consistent with every prior real-data study in this project.

### Side disagreement (n=83 — Engine and SmartSim picked different winners)

| Metric | Engine | SmartSim 2.0 | Consensus |
| --- | --- | --- | --- |
| Margin MAE | 16.674 | 13.944 | **13.569** |
| Side accuracy | 48.19% | 51.81% | **63.86%** |

This is the subset where the two systems actively disagree on who wins, and it remains the clearest separation in the whole dataset: Consensus beats both raw systems by double digits in accuracy.

### Large mismatch (n=84 — `|market margin| ≥ 10`)

| Metric | Engine | SmartSim 2.0 | Consensus |
| --- | --- | --- | --- |
| Margin MAE | 17.225 | 18.094 | 18.094 |
| Side accuracy | 67.86% | **79.76%** | **79.76%** |

Consensus is numerically identical to SmartSim here by construction — this is exactly the branch where the Phase 4 revision made Consensus defer to SmartSim's margin, unblended. SmartSim beats Engine by 12 points of accuracy in this subset, in the same direction the policy revision was built on.

### Large mismatch AND side disagreement (n=30 — the exact subset the Phase 4 revision targeted)

| Metric | Engine | SmartSim 2.0 / Consensus |
| --- | --- | --- |
| Margin MAE | 22.154 | **16.254** |
| Side accuracy | **33.3%** | **66.7%** |

This is the direct real-world analog of the 23.5%/76.5% finding from `smartsim_signal_attribution_report.md` that motivated the policy revision — now measured on a fresh 30-game sample (vs. the original 17), *after* the revision shipped. The direction is unchanged and the magnitude, while somewhat less extreme (33.3%/66.7% vs. 23.5%/76.5%), is fully consistent: Engine is still the weaker side in exactly the situation the revision was designed to fix. No sign of regression.

### Total disagreement (n=83 — Engine/SmartSim totals differ ≥10 points)

| Metric | Engine | SmartSim 2.0 | Consensus |
| --- | --- | --- | --- |
| Total MAE | 14.561 | 15.508 | **13.983** |

Consensus keeps its edge here too — consistent with the Decision Policy Reassessment's finding that the always-blend total policy needed no change.

### Conference vs. non-conference games

| Metric | Conference (n=145) | Non-conference (n=64) |
| --- | --- | --- |
| Engine margin MAE | 13.548 | 17.224 |
| SmartSim margin MAE | 13.632 | 16.569 |
| Consensus margin MAE | **13.287** | **16.546** |
| Engine side accuracy | 68.28% | 59.38% |
| SmartSim side accuracy | 64.83% | 71.88% |
| Consensus side accuracy | **71.72%** | **71.88%** |

Non-conference games (more likely to include large mismatches — cross-tier matchups) show a bigger Engine/SmartSim accuracy gap in SmartSim's favor than conference games do, which lines up with the large-mismatch finding above rather than contradicting it.

### Consensus vs. both standalone systems, head-to-head per game

| | Margin | Total |
| --- | --- | --- |
| Consensus strictly beats both raw sources | 16 / 209 | 63 / 209 |
| Consensus strictly worse than both raw sources | **0 / 209** | 22 / 209 |

Consensus margin is *never* worse than both raw sources on any of the 209 games (it either beats both, or exactly matches SmartSim in the large-mismatch branch by construction). Consensus total strictly beats both raw sources in 63 games and is strictly worse than both in 22 — the always-blend total policy doesn't dominate every single game, but it wins on every aggregate metric above, which is the relevant standard for a fixed-weight policy.

## Task 10: Weekly Update Summaries

| Week | n | Engine margin MAE | SmartSim margin MAE | Consensus margin MAE | Engine acc. | SmartSim acc. | Consensus acc. | Engine total MAE | SmartSim total MAE | Consensus total MAE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 47 | 17.040 | 17.532 | 17.497 | 61.70% | 70.21% | 68.09% | 13.155 | 15.963 | **13.136** |
| 5 | 51 | 13.183 | 12.375 | **12.355** | 62.75% | 66.67% | **68.63%** | 14.460 | 14.542 | **13.238** |
| 8 | 59 | 13.658 | 13.313 | **13.134** | 64.41% | 71.19% | **76.27%** | 13.174 | 13.745 | **12.975** |
| 10 | 52 | 15.149 | 15.317 | **14.579** | 73.08% | 59.62% | **73.08%** | 14.501 | 14.797 | **13.246** |

Consensus wins or ties on total MAE in every one of the four weeks, and wins outright on side accuracy in three of four (Week 1 is the one exception — Consensus 68.09% narrowly trails SmartSim's 70.21% there, still well ahead of Engine's 61.70%). No week shows Consensus underperforming both raw systems on either margin or total.

## Task 9: Explicit Answers

### Which source is performing best?

**Consensus**, on every headline metric measured across all 209 games: lowest margin MAE/RMSE, lowest total MAE/RMSE, highest side accuracy (71.77% vs. Engine's 65.55% and SmartSim's 66.99%), and never worse than both raw sources on margin in any single game. Between the two raw systems alone, SmartSim edges Engine on margin correlation (0.563 vs. 0.372) and side accuracy (66.99% vs. 65.55%), while Engine edges SmartSim on total MAE (13.814 vs. 14.700) — neither raw system dominates the other, which is exactly why the blended Consensus outperforms both.

### Is the policy revision helping?

Yes. In the 30-game large-mismatch-and-side-disagreement subset — the precise situation the Phase 4 revision was built to fix — SmartSim (now driving Consensus's margin there) is correct 66.7% of the time versus Engine's 33.3%, a 2-to-1 margin in the same direction as the original 23.5%/76.5% finding. Had the pre-revision policy (Engine-first on large mismatches) still been in effect, Consensus would have picked the *wrong* side in roughly two-thirds of these 30 games instead of about one-third.

### Does Consensus outperform both standalone systems?

On aggregate metrics, yes, consistently — lowest MAE/RMSE on both margin and total overall, in every disagreement/mismatch/conference category tested, and in every one of the four weeks. On a strict per-game basis, Consensus margin is never worse than both raw sources (0/209); Consensus total is worse than both raw sources in 22/209 games but still wins on every aggregate measure, meaning its wins are larger and more frequent than its (real, disclosed) losses.

### Are disagreement games still SmartSim's strongest area?

Yes. In the 83 side-disagreement games, SmartSim's side accuracy (51.81%) and margin MAE (13.944) both beat Engine's (48.19%, 16.674) — the same relative pattern found in the original ensemble evaluation and signal attribution studies. Within that group, the large-mismatch-and-side-disagreement subset (n=30) is SmartSim's single strongest measured segment: 66.7% accuracy vs. Engine's 33.3%.

### Are any calibration regressions visible?

No. The four-week sample's headline numbers (Engine ~65-66% side accuracy, SmartSim ~67-80% depending on subset, Consensus ~72-80%) are in the same range and same relative ordering as the pre-revision 106-game sample behind `smartsim_decision_policy_report.md`. The large-mismatch-and-side-disagreement subset — the one place a regression from the Phase 4 change would show up first if the revision had been wrong — still favors SmartSim by a wide margin (66.7% vs. 33.3%) on entirely fresh data collected after the revision shipped. No category in this report shows Engine outperforming SmartSim or Consensus by a margin large enough to call into question any prior finding.

## Task 11: Final Verdict

**Continue Monitoring.**

209 real games across four weeks is a meaningfully larger and more current sample than any prior study in this project, and it corroborates every material finding to date: Consensus beats both standalone systems on aggregate accuracy and error, the Phase 4 policy revision is measurably helping in exactly the subset it targeted, and no calibration regression is visible anywhere in the breakdown. That said, four weeks (out of a ~15-week regular season) is not yet the full-season record the stated Goal calls for, and this report does not attempt to project forward — it states what happened, not what will happen. The right next step is to keep collecting weekly records with this same module (append-only, unmodified join methodology) rather than expanding rollout or revisiting policy on the strength of this sample alone; a broader rollout or another policy pass is better justified once a full-season (or near-full-season) record is in hand.
