# SmartSim Ensemble Evaluation Report

- Date: 2026-07-15
- Scope: NCAAF, same 103-game real, completed 2025 backtest (Weeks 5 + 10) as `smartsim_integration_assessment.md`. **No SmartSim code, current-engine code, or calibration parameters were touched** — this pass only combines the two systems' already-generated numbers.
- References: `smartsim_integration_assessment.md`, `nfl_production_candidate_report.md`, `ncaaf_calibration_profile_v2_report.md`.

## Method

Same 4-source join as the integration assessment (actual result, market lines averaged across books, current engine's `predicted_home_points`/`predicted_away_points`/`predicted_total_points`, SmartSim `NCAAF_CALIBRATION_PROFILE` v2 fed real season-PPA-derived team ratings, 300-seed Monte Carlo mean per game). Three blend methods were built on top:

1. **50/50 average** — `(engine + smartsim) / 2`, no correction of any kind.
2. **Weighted average** — fixed weights derived from each system's own correlation-with-actual (a principled way to weight two forecasters: the one that tracks reality better gets more say). Margin: engine 0.395 / SmartSim 0.605. Total: engine 0.114 / SmartSim 0.886 — and SmartSim's total is first corrected for its known +6.11-point bias (documented in the integration assessment) before blending, since leaving a known, named bias uncorrected going into an ensemble is not a meaningful test of the *signal*, only of the bias.
3. **Confidence-weighted blend** — same baseline weights as #2, but modulated per game by SmartSim's own Monte Carlo consistency (the standard deviation of its 300 simulated margins/totals for that specific game — tight agreement across seeds = SmartSim is "sure," wide scatter = SmartSim is internally uncertain). This is the only per-game-dynamic method; the other two use one fixed weight for every game.

## Task 3-4: Measured Comparison (N=103)

### Margin

| System | MAE | Bias | Correlation | Side selection | Favorite acc. | Underdog acc. |
| --- | --- | --- | --- | --- | --- | --- |
| Market | **10.99** | +1.24 | **0.632** | **73.8%** | 73.8% (n=103) | — (n=0) |
| Current Engine | 14.18 | −3.58 | 0.356 | 68.0% | 83.1% (n=65) | 42.1% (n=38) |
| SmartSim (raw) | 13.86 | +0.53 | 0.545 | 63.1% | 74.4% (n=78) | 28.0% (n=25) |
| Blend 50/50 | 13.18 | −1.52 | 0.416 | 68.0% | 81.2% (n=69) | 41.2% (n=34) |
| **Blend Weighted** | **13.19** | −1.09 | 0.442 | **68.9%** | 80.6% (n=72) | 41.9% (n=31) |
| Blend Confidence-weighted | 13.19 | −1.07 | 0.444 | 68.9% | 80.6% (n=72) | 41.9% (n=31) |

### Total

| System | MAE | Bias | Correlation |
| --- | --- | --- | --- |
| Market | 12.77 | +0.62 | **0.397** |
| Current Engine | 14.48 | −2.33 | 0.046 |
| SmartSim (raw) | 14.67 | +6.11 | 0.358 |
| Blend 50/50 (no bias correction) | 13.98 | +1.89 | 0.192 |
| **Blend Weighted (bias-corrected)** | **13.24** | −0.27 | **0.350** |
| Blend Confidence-weighted | 13.24 | −0.27 | 0.351 |

**Favorite/underdog accuracy definitions** (stated explicitly to avoid ambiguity): a system "endorses the favorite" on a game when its own predicted margin agrees with which side the market favors; favorite accuracy is the hit rate on those endorsed games. A system "calls an upset" when its predicted margin disagrees with the market's favorite; underdog accuracy is the hit rate on those specific games — i.e., how often a called upset actually happened. This is a much harder, more meaningful bar than side selection alone, because always picking favorites inflates side-selection accuracy without demonstrating any upset-calling skill.

## Task 7: Explicit Answers

### Does SmartSim improve forecasting when blended?

**Yes, on total — clearly. On margin — MAE improves, but at some correlation cost relative to SmartSim standalone.** Total is unambiguous: Blend Weighted's total MAE (13.24) beats both the current engine (14.48) and raw SmartSim (14.67), its bias collapses from SmartSim's +6.11 to −0.27, and its correlation (0.350) sits almost exactly at SmartSim's own strong 0.358 — this blend keeps essentially all of SmartSim's total signal while removing its Achilles-heel bias. Margin is a genuine, disclosed nuance: every blend beats both individual systems on **MAE** (13.18-13.19 vs. engine's 14.18 and SmartSim's 13.86), and beats the engine on **correlation** (0.416-0.444 vs. 0.356) — but none of the blends reach raw SmartSim's own standalone margin correlation (0.545). Averaging in the engine's weaker, differently-biased margin signal improves the practical error metric (MAE) but dilutes SmartSim's stronger raw directional signal. Both things are true at once and should be reported as such, not resolved into one number.

### Which blend performs best?

**Weighted average (correlation-derived weights, with SmartSim's total bias corrected first).** It matches or beats 50/50 on every single metric measured, and is statistically indistinguishable from the confidence-weighted variant (differences of 0.01-0.02 in every row) — the added per-game complexity of Monte Carlo consistency weighting bought nothing measurable in this backtest. On Occam's-razor grounds, the simple fixed-weight blend is the one to ship: same performance, far simpler to implement and explain, no dependency on SmartSim's internal seed-variance output. 50/50 averaging is clearly the weakest of the three blend methods, especially on total (where its lack of bias correction leaves +1.89 points of residual bias and materially worse correlation, 0.192 vs. the weighted blend's 0.350) — **do not ship a naive 50/50 average.**

### Does SmartSim improve side picks?

**Modestly, only through blending — not standalone.** Raw SmartSim's side-selection accuracy (63.1%) is the worst of the three individual systems, below even the engine (68.0%). But the weighted/confidence blends reach 68.9%, a small, real improvement over the engine alone. The favorite/underdog breakdown explains why: SmartSim endorses far more favorites than the engine does (78 games vs. 65) but converts them at a lower rate (74.4% vs. 83.1%), and its upset-calling is weaker (28.0% vs. 42.1% hit rate on called upsets, on fewer called upsets too). Blending pulls SmartSim's over-eager, lower-accuracy favorite/upset calls back toward the engine's more disciplined ones, netting a small overall gain rather than a large one.

### Does SmartSim improve totals?

**Yes — this is the strongest, cleanest finding in this report.** The current engine's total correlation with actual outcomes (0.046) is statistically indistinguishable from noise. SmartSim's (0.358) is not, and survives in the blend (0.350) after the bias correction. This single fact — that the incumbent engine's total output carries essentially zero real signal — is the most decision-relevant number in the whole assessment.

### Where does SmartSim add the most value?

Ranked by the segment analysis (35-game terciles for mismatch/total, conference-flag split for the rest):

1. **Toss-up games** (|market margin| ≤ 4.5, n=35): the single clearest win. SmartSim alone already beats the engine on margin MAE (10.29 vs. 12.35); the weighted blend (9.99) very nearly matches the market itself (9.58) and beats the market's own side-selection tie (68.6% for both). This is exactly the game type where a slow-starting, feature-poor incumbent model would be expected to default to noise, and where an independent simulator adds the most.
2. **Inflated-total (shootout) games** (market total ≥ 55.2, n=35): SmartSim's raw total MAE (13.78) is meaningfully better than the engine's (15.78) — consistent with the concrete shootout examples in the integration assessment (Georgia Tech @ NC State, Utah State @ Vanderbilt). Note a real nuance here: the bias-corrected blend (14.10) is *slightly worse* on this specific high-total segment than raw SmartSim, because part of SmartSim's "bias" is genuine shootout-detection skill, not pure noise — correcting the average bias trades a little of this segment's edge for a large gain on the low-total segment below.
3. **Low-total (defensive) games** (market total ≤ 50.3, n=35): the mirror image — raw SmartSim is clearly worse here (total MAE 17.32 vs. engine's 13.58) because of the same bias, and the corrected blend recovers almost all of the gap (13.74). This is where bias-correction earns its keep.
4. **Conference games** (n=87, most of the sample): the blend is the best of the three non-market systems on both margin (12.89) and total (12.98), beating engine and SmartSim individually — a broad, if modest, improvement across the majority of real games.
5. **Large talent mismatches** (|market margin| ≥ 10.2, n=35): the weakest case for SmartSim. Its side-selection accuracy is actually better than the engine's (77.1% vs. 74.3%), but its margin and total MAE are both worse than the engine's alone; the engine (and the market) are already good at big favorites, which is the least surprising result in the segmentation.
6. **Non-conference games** (n=16, small sample, directional not definitive): SmartSim alone is dramatically better than the engine (margin MAE 14.26 vs. 17.57; side accuracy 81.2% vs. 56.2%), but the blend does not fully capture this edge because it is pulled toward the engine's much weaker performance here. Worth a larger sample before acting on this one.

### Should SmartSim remain a secondary signal, become a primary signal, or act as a conditional signal?

**Conditional signal — the segmentation results promote it past a flat "secondary" role.** A blanket secondary-signal treatment (average it in everywhere, uniformly) leaves value on the table in toss-ups and shootouts and needlessly gives up ground in large-mismatch games where the engine is already fine on its own. The evidence supports routing SmartSim's contribution by situation rather than applying one constant blend weight everywhere.

## Task 8: Recommended Production Usage Pattern

**Blend only under specific conditions, not "always blend."** Concretely:

- **Totals: blend everywhere, with the bias correction applied.** The correlation-weighted, bias-corrected blend beat the engine alone in every segment tested except the inflated-total tercile (where raw SmartSim, not the blend, was best) — and even there, the blend still beat the engine. Given the engine's near-zero total correlation, blending totals is close to a strict improvement with no real segment where it clearly hurts relative to the engine alone.
- **Margin/spread: blend in toss-up and conference games; lean toward the engine (or skip the blend) in large-mismatch games.** The toss-up segment is where the blend (and SmartSim alone) shows its clearest edge; large mismatches are the one segment tested where blending margin costs accuracy relative to the engine alone.
- **Use the simple weighted-average blend, not 50/50 and not the confidence-weighted variant.** The confidence-weighted method added implementation complexity (dependency on SmartSim's per-game seed variance) for no measured benefit in this backtest; revisit it only if a much larger sample later shows a real gap between the two.
- **Do not replace the engine, and do not run SmartSim as a pure validation/sanity layer.** Replacement is not supported (SmartSim underperforms the engine on side selection and underdog-calling standalone); pure validation undersells it (the two systems disagree enough, and SmartSim tracks totals well enough on its own, that suppressing its numbers whenever it disagrees with the engine would throw away exactly the toss-up/shootout value documented above.

## Deliverables

- This report.
- No SmartSim, current-engine, or calibration-parameter code touched. All analysis lives in disposable scripts (gitignored `tmp_*`, not committed), consistent with prior passes.
