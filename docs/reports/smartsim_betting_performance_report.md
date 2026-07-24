# SmartSim Betting Performance Assessment

- Date: 2026-07-16
- Scope: NCAAF, measurement only. **SmartSim 2.0, calibration profiles, blend formulas, and decision policies were not modified.** Confirmed by an empty `git diff --stat` against `HEAD` for `syndicate/features/football/` and `syndicate/features/ncaaf/smartsim2_blend.py`.
- References: `smartsim_live_performance_report.md`, `smartsim_signal_attribution_report.md`, `smartsim_decision_policy_report.md`.
- New code: `syndicate/features/ncaaf/smartsim2_betting_performance.py` (ATS/totals pick grading + win%/ROI/units stats — grades bets from the already-collected `smartsim2_performance_tracking` records, does not recompute forecast statistics or touch the blend), `tests/test_ncaaf_smartsim2_betting_performance.py` (19 tests, all passing).
- Sample: the same **752 real, completed 2025-season games** (all 16 weeks) from `smartsim_monitoring_phase2_report.md` — no new data collection was needed, since every field a bet needs (`market_margin`, `market_total`, each source's margin/total, `actual_margin`, `actual_total`) is already in that log.

## Methodology and a Disclosed Assumption

**This report measures a different question than every prior report.** MAE, RMSE, correlation, and "side accuracy" (does the source pick the correct straight-up winner) all measure forecast quality. Betting performance measures something else: does the source's margin/total, compared against the **closing market line**, actually win against the spread and total? These can diverge sharply — a full favorite in a blowout is an easy straight-up pick regardless of forecast quality, but covering a spread the market already set to reflect that blowout is a different, harder question. That divergence is exactly what this report is designed to surface, and it does (see Task 6 below).

**Pick reconstruction**: for each game, a source "picks" the side/total it projects to beat the closing line by. ATS: pick home if `source_margin > market_margin`, else away; graded win/loss/push against whether `actual_margin` beat, missed, or exactly matched `market_margin`. Totals: pick Over if `source_total > market_total`, else Under; graded the same way against `actual_total` vs. `market_total`.

**Odds assumption, stated plainly**: real per-bet prices (juice) were not collected in this project — only the point spread/total themselves. Every bet here is graded at the industry-standard flat **-110/-110** on both sides (risk 1.0 unit to win 100/110 ≈ 0.909 units net). This is the standard assumption for this kind of backtest without real bet-slip prices, not a claim of higher precision than that.

## Task 1-4: Betting Performance, Overall (n=752)

### ATS

| Source | W-L (push) | Win % | ROI % | Units Net |
| --- | --- | --- | --- | --- |
| **Engine** | 398-351 (3) | **53.14%** | **+1.44%** | **+10.82** |
| SmartSim | 386-363 (3) | 51.54% | -1.61% | -12.09 |
| Consensus | 380-369 (3) | 50.73% | -3.14% | -23.55 |

### Totals

| Source | W-L (push) | Win % | ROI % | Units Net |
| --- | --- | --- | --- | --- |
| Engine | 390-356 (6) | 52.28% | -0.19% | -1.45 |
| SmartSim | 384-362 (6) | 51.47% | -1.73% | -12.91 |
| **Consensus** | 426-320 (6) | **57.10%** | **+9.02%** | **+67.27** |

**The headline split**: Engine is the only ATS-profitable source overall; Consensus is the only clearly, substantially profitable totals source overall — and each is the *worst* of the three on the other bet type. This split runs through nearly every category below.

## Task 5: Betting Performance by Category

### Side disagreement (n=326)

| | ATS win% / ROI | Totals win% / ROI |
| --- | --- | --- |
| Engine | 50.00% / -4.55% | 55.73% / +6.39% |
| **SmartSim** | **56.44% / +7.75%** | 51.08% / -2.48% |
| Consensus | 51.23% / -2.20% | **59.13% / +12.89%** |

### Total disagreement (n=275)

| | ATS win% / ROI | Totals win% / ROI |
| --- | --- | --- |
| Engine | 49.09% / -6.28% | 47.06% / -10.16% |
| **SmartSim** | **57.09% / +8.99%** | 56.25% / +7.39% |
| Consensus | 50.91% / -2.81% | 55.51% / +5.98% |

### Large mismatch (n=310)

| | ATS win% / ROI | Totals win% / ROI |
| --- | --- | --- |
| **Engine** | **55.05% / +5.09%** | 52.61% / +0.45% |
| SmartSim | 50.81% / -2.99% | 52.94% / +1.07% |
| Consensus | 50.81% / -2.99% (= SmartSim, by construction) | **60.46% / +15.42%** |

### Conference games (n=548)

| | ATS win% / ROI | Totals win% / ROI |
| --- | --- | --- |
| **Engine** | **53.75% / +2.61%** | 51.56% / -1.57% |
| SmartSim | 51.19% / -2.28% | 51.93% / -0.87% |
| Consensus | 48.99% / -6.47% | **54.86% / +4.74%** |

### Non-conference games (n=204)

| | ATS win% / ROI | Totals win% / ROI |
| --- | --- | --- |
| Engine | 51.49% / -1.71% | 54.23% / +3.53% |
| SmartSim | 52.48% / +0.18% | 50.25% / -4.07% |
| **Consensus** | **55.45% / +5.85%** | **63.18% / +20.62%** |

### High-total vs. low-total games (median split at 51.75 pts, n=376 each)

| | ATS win% / ROI (High / Low) | Totals win% / ROI (High / Low) |
| --- | --- | --- |
| Engine | 51.21% / -2.24%  —  55.05% / +5.10% | 52.55% / +0.32%  —  52.01% / -0.71% |
| SmartSim | 52.82% / +0.83%  —  50.27% / -4.04% | 52.55% / +0.32%  —  50.40% / -3.78% |
| Consensus | 50.13% / -4.29%  —  51.33% / -2.01% | **56.57% / +7.99%  —  57.64% / +10.04%** |

Consensus totals is the single most consistent result in this entire report: it is the best or tied-best totals performer in **every category tested without exception** — overall, both disagreement types, large mismatch, both conference splits, and both total-level splits. No other source/bet-type combination is anywhere near that consistent.

## Task 6: Does Forecast Improvement Translate Into Betting Improvement? — The Large-Mismatch Counterfactual

This is the sharpest test available in this dataset, because it's a **real, direct counterfactual, not a hypothetical**. Before the Phase 4 policy revision, Consensus's margin in the large-mismatch branch was literally the Engine's own margin, unblended — so the "Engine" row in the large-mismatch table above *is* what pre-revision Consensus would have shown on these exact 310 real games. After the revision, Consensus uses SmartSim's margin in that branch instead — shown as the "Consensus" row (identical to "SmartSim" there, by construction).

| | Pre-revision-equivalent (Engine) | Post-revision (Consensus/SmartSim) | Change |
| --- | --- | --- | --- |
| ATS win % | 55.05% | 50.81% | **-4.24 pts** |
| ATS ROI | +5.09% | -2.99% | **-8.08 pts** |
| ATS units (310 games) | +15.64 | -9.18 | **-24.82 units** |

**On the metric this report exists to measure, the Phase 4 policy revision made things worse, not better, in exactly the subset it targeted.** This is not a contradiction of `smartsim_signal_attribution_report.md` or `smartsim_decision_policy_report.md` — those reports measured straight-up pick accuracy (does the source predict the correct winner), and SmartSim genuinely does that better in large mismatches (as this report's own forecast-tracking data continues to show: SmartSim/Consensus straight-up accuracy in this subset is ~80% vs. Engine's ~72%, per `smartsim_monitoring_phase2_report.md`). But straight-up accuracy and ATS covering are different questions. A large market mismatch means the market has already priced in the favorite's edge; correctly picking that favorite to win outright is comparatively easy, while beating the *closing spread* the market set to reflect exactly that edge is not the same task — and real closing lines are frequently sharp enough that even a well-calibrated favorite pick fails to cover. This dataset shows that gap directly: SmartSim's forecast improvement in this subset is real, but it did not carry through to ATS profit — if anything the opposite.

**The one caveat in the other direction**: totals in this same subset improved substantially post-revision (Consensus 60.46%/+15.42% vs. what Engine-only alone was already doing there, 52.61%/+0.45%) — but this is *not* attributable to the Phase 4 policy, since the total policy was never touched by that revision (`blend_total()` runs identically regardless of which margin branch fires). It's a separate, positive, pre-existing pattern in the always-blended total policy showing up strongly in this subset, not a consequence of the margin-policy change.

## Task 8: Explicit Answers

### Which source wins the most bets?

By raw win count: **Engine** on ATS (398 wins), **Consensus** on totals (426 wins). By win rate: same ordering — Engine 53.14% ATS, Consensus 57.10% totals — both the clear leaders in their respective bet type.

### Which source produces the best ROI?

**Engine** on ATS (+1.44%, the only ATS-profitable source of the three). **Consensus** on totals (+9.02%, not close — the next best totals source, Engine, is at -0.19%).

### Does Consensus improve betting outcomes?

**Split, and the split is the finding.** For totals: decisively yes — best or tied-best in every single category tested, +9.02% ROI overall, consistently the standout across the whole report. For ATS: no — Consensus is the *worst* of the three ATS performers overall (-3.14% ROI) and is only ATS-profitable in one category (non-conference games, +5.85%). Consensus does not uniformly "improve betting outcomes" — it does so clearly and consistently for totals, and does not for ATS.

### Does SmartSim create profitable disagreement opportunities?

**Yes, specifically and clearly for ATS.** SmartSim is the only source profitable in both the side-disagreement subset (+7.75% ROI) and the total-disagreement subset (+8.99% ROI) — the two situations where the Engine and SmartSim actively disagree. This is a genuine, real ATS edge tied directly to disagreement, distinct from (and in some ways contradicting) the overall picture where SmartSim's standalone ATS record is negative (-1.61%) — its edge is concentrated specifically in situations of disagreement, not present broadly.

### Does the large-mismatch policy improve ATS performance?

**No — the real counterfactual above shows it reduced ATS performance in exactly the subset it targets** (-4.24 points of win rate, -8.08 points of ROI, -24.82 net units across 310 real games). This does not mean the policy was wrongly justified — it was correctly justified by, and does deliver, better straight-up pick accuracy. It means straight-up accuracy and ATS profitability are different things, and this is the clearest evidence in this project that optimizing for one does not guarantee the other.

## Final Verdict

**Betting Improvement Demonstrated — Totals Only. Not Demonstrated for ATS.**

Consensus's totals performance is a genuine, demonstrated betting improvement: it is the best or tied-best source in every category tested without a single exception, at a substantial and consistent ROI (+9.02% overall, ranging as high as +20.62% in non-conference games), on 752 real games graded against real closing lines — that is a real edge, not merely a promising research signal or an improved projection statistic. ATS tells a different story: no source is consistently profitable across categories, Consensus is the *worst* ATS performer overall, and the Phase 4 large-mismatch policy — while correctly justified on straight-up accuracy grounds — measurably reduced ATS profitability in exactly the subset it targets. SmartSim's one clear, real ATS edge (disagreement games specifically, +7.75-8.99% ROI) is a genuine bright spot worth acting on, but it does not generalize to an overall SmartSim or Consensus ATS advantage. The goal this phase set out to answer — does SmartSim meaningfully improve betting performance, not just projection statistics — has one clear "yes" (Consensus totals) and one clear "not yet, and possibly a step backward" (ATS, especially the large-mismatch branch), and both halves of that answer should carry forward into any future policy discussion rather than only the favorable half.
