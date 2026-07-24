# SmartSim Signal Attribution Study

- Date: 2026-07-16
- Scope: NCAAF, pure analysis — **no code was modified.** SmartSim 2.0, the Enhanced Totals Engine, the blend formulas, and the trial-access infrastructure are all untouched; this study only reads existing artifacts and computes statistics over them.
- References: `smartsim_public_trial_monitoring_report.md`, `smartsim_ensemble_evaluation_report.md`, `smartsim_integration_assessment.md`.

## Method

The public trial's 13/47 disagreement figure came from one week. To get real statistical power for a disagreement-specific breakdown, this study combines **both** real, completed weeks that already have a generated SmartSim 2.0 artifact on disk — Week 1 (47 games) and Week 8 (59 games) of the 2025 season — joined against real final scores, real market lines (CFBD `/lines`, freshly fetched for Week 1, reused from the cached fetch for Week 8), and the Enhanced Totals Engine's own stored predictions for the same games. **106 real games** total, all with real outcomes (the 2025 season is complete). Consensus Projection values were computed by calling the actual, unmodified `smartsim2_blend.compute_blend()` — not reimplemented or approximated.

## Task 1-2: Disagreement Collection and Categorization

| Category | Definition | Count |
| --- | --- | --- |
| Side disagreement only | sign(Engine margin) ≠ sign(SmartSim margin), total gap < 10 pts | 22 |
| Total disagreement only | \|Engine total − SmartSim total\| ≥ 10 pts, same side | 24 |
| Both | Side disagreement AND total gap ≥ 10 pts | 16 |
| **Any disagreement** | Union of the above | **62 / 106 (58.5%)** |
| Neither (systems agree) | — | 44 / 106 (41.5%) |

The 10-point total-disagreement threshold matches the existing large-mismatch convention already used for margin in `smartsim2_blend.py`, chosen for consistency and interpretability rather than picked to flatter either system.

## Task 3: Accuracy Within Disagreement Subsets

### Side disagreement (n=38: side-only + both)

| System | Side-pick accuracy | Margin MAE |
| --- | --- | --- |
| Enhanced Totals Engine | **39.5%** | 17.91 |
| SmartSim 2.0 | **60.5%** | 14.42 |
| Consensus Projection | 42.1% | 16.84 |

(39.5% + 60.5% = 100% exactly, as expected — in a strict side-disagreement game exactly one system picks the actual winner.)

### Total disagreement (n=40: total-only + both)

| System | Total MAE |
| --- | --- |
| Enhanced Totals Engine | **11.36** |
| SmartSim 2.0 | 15.29 |
| Consensus Projection | 12.05 |

### Both (n=16, the highest-conviction disagreements)

| System | Side-pick accuracy | Total MAE |
| --- | --- | --- |
| Enhanced Totals Engine | 31.2% | **8.36** |
| SmartSim 2.0 | **68.8%** | 13.64 |
| Consensus Projection | 37.5% | 8.45 |

### Context: when the systems agree (n=44)

All three systems tie at 81.8% side-pick accuracy, with total MAE within a point of each other (13.5-14.6) — confirms disagreement games are exactly where the two systems' different information actually matters; agreement games are the "easy" ones both already get right.

## The Key Finding: Consensus Underperforms Raw SmartSim in Side Disagreements, and the Reason Is Diagnosable

Breaking the 38 side-disagreement games down by whether the blend formula's large-mismatch rule actually fired:

| Subset | n | Engine accuracy | SmartSim accuracy | Consensus accuracy |
| --- | --- | --- | --- | --- |
| **Not blended** (\|Engine margin\| ≥ 10, Consensus = Engine's margin unblended) | 17 | **23.5%** | **76.5%** | 23.5% (= Engine, by construction) |
| **Blended** (Consensus = weighted average) | 21 | 52.4% | 47.6% | **57.1%** |

This is the single most important, actionable result in this study. **In exactly the 17 games where the current large-mismatch rule defers to the Engine alone, the Engine is wrong three times more often than it's right (23.5%), while SmartSim is right three times more often than wrong (76.5%).** The rule that exists to protect Consensus from an unreliable blend in high-conviction situations is, for side-selection purposes specifically, doing the opposite of what the data supports. Meanwhile, in the 21 games where blending *does* happen, Consensus modestly beats both individual raw systems (57.1% vs. 52.4%/47.6%) — the blend formula itself works well when it's actually used; the large-mismatch exception is the specific piece worth revisiting.

**Concrete examples** (large mismatch, Engine wrong, SmartSim right — 13 of the 17 non-blended cases): Fresno State @ Kansas (actual margin +24, Engine said Kansas −10.1, SmartSim correctly leaned Fresno State +2.4), Coastal Carolina @ Virginia (actual +41, Engine said Virginia −8.7, SmartSim correctly leaned Coastal +4.2), UNLV @ Sam Houston (actual −17, Engine wrongly favored UNLV +13.4, SmartSim correctly leaned Sam Houston −2.1). Several of these are also cases where the **market** already disagreed with the Engine (e.g., Washington State @ Virginia: Engine −13.6, market +16.5, actual +2 — Engine was the outlier against both the market and SmartSim). Only 4 reverse cases exist (Engine right, SmartSim wrong in a non-blended game), all comparatively low-stakes results (App State @ Charlotte, Mississippi State @ Southern Miss, and two others).

## Task 4: Which Game Characteristics Predict a SmartSim Advantage

Restricted to the 38 side-disagreement games, segmented by market-derived characteristics:

| Characteristic | n | Engine accuracy | SmartSim accuracy | Advantage |
| --- | --- | --- | --- | --- |
| **Talent mismatches** (\|market margin\| ≥ 13.2) | 14 | 21.4% | **78.6%** | **SmartSim, by far the largest margin** |
| High totals (market total ≥ 55.7) | 12 | 33.3% | 66.7% | SmartSim |
| Conference games | 18 | 38.9% | 61.1% | SmartSim |
| Non-conference games | 20 | 40.0% | 60.0% | SmartSim |
| Low totals (market total ≤ 49.5) | 17 | 41.2% | 58.8% | SmartSim |
| **Toss-ups** (\|market margin\| ≤ 4.8) | 14 | 50.0% | 50.0% | **Tie — no edge either way** |

The pattern is broad (SmartSim leads in 5 of 6 segments) but **not uniform** — the single largest and most decisive edge is in talent-mismatch games (the same segment driving the large-mismatch finding above, since a "talent mismatch" by market spread strongly correlates with a large Engine margin), while true toss-ups show no advantage for either system. Conference-game status barely differentiates (61.1% vs. 60.0%) — it is not, on this evidence, a meaningful predictor on its own.

## Task 5: Consensus Projection Performance, Summarized

Consensus is a genuine (if modest) improvement over both raw systems specifically in the 21 side-disagreement games where blending actually occurs (57.1% vs. 52.4% Engine / 47.6% SmartSim). It is **not** an improvement — it is functionally identical to the weaker system — in the 17 games where the large-mismatch rule suppresses blending, because in exactly that subset it inherits the Engine's 23.5% accuracy rather than SmartSim's 76.5%. On total, Consensus sits between the two raw systems in every disagreement subset, closer to whichever raw system is more accurate in each specific bucket (Engine in the total-disagreement subset, roughly midway in "both").

## Task 7: Explicit Answers

### When does SmartSim outperform?

In side-selection (who wins), broadly across every disagreement segment except true toss-ups, and overwhelmingly so in talent-mismatch and "both-disagreement" games — precisely the situations a forecaster most needs to get right.

### When does the Engine outperform?

In total (over/under) prediction specifically, when the two systems substantially disagree on total: Engine's total MAE (11.36) beats SmartSim's (15.29) in that 40-game subset, reversing the roles from the side-selection finding. The Engine also modestly wins side-selection in the toss-up segment (tied, not a real Engine edge) and in the 4 reverse-case non-blended games.

### Does the blend outperform both?

**Only when it actually runs.** In the 21 blended side-disagreement games, yes — Consensus beats both raw systems. In the 17 non-blended games, no — Consensus is identical to the weaker (Engine) system by construction, missing SmartSim's demonstrated 76.5%-accurate signal entirely. On total, Consensus never clearly beats the better raw system within a disagreement subset; it sits between them.

### Which disagreement categories matter most?

Side disagreement, and specifically the large-mismatch subset within it. It's both the largest population effect measured (76.5% vs. 23.5%, a 53-point swing) and the one place the current production rule is demonstrably working against the evidence.

## Task 8: Production Usage Rule Recommendations

Not implemented — recommendations only, per this study's read-only scope:

1. **Side/spread selection: revisit the large-mismatch exception specifically.** The evidence suggests high-conviction disagreements (large Engine margin, opposing SmartSim lean) are exactly where SmartSim's signal is most reliable, not least — the opposite of what the current rule assumes. A future calibration pass should consider either lowering the current 10-point exception threshold, or replacing "defer to Engine when Engine's margin is large" with something conditioned on *disagreement* itself (e.g., blend margin whenever the two systems disagree on side, regardless of Engine's margin size) — this is a hypothesis for the next calibration iteration to test, not a change made here.
2. **Total: keep the current always-blend policy**, but note it is not uniformly optimal — in the specific subset where the two systems substantially disagree on total, the Engine alone is more accurate than the current blend. This is a smaller, second-priority finding worth a future look, not an immediate rule change (the always-blend policy still wins on the broader population per `smartsim_ensemble_evaluation_report.md`).
3. **Toss-ups**: no rule change indicated — neither system has an edge, so the existing blend (which already applies in this range) is a reasonable default.
4. **Do not fully override the Engine with SmartSim** — the reverse cases (4 real games where Engine was right and SmartSim wrong even in the non-blended subset) mean an unconditional SmartSim override would trade one bias for another, just a smaller one.

## Final Verdict

**SmartSim Conditional Signal.**

Not merely "secondary" — the 76.5%-vs-23.5% finding in exactly the situations the current rule treats as high-conviction-Engine is too large and too consistent (13 corroborating example games, one clear mechanism) to file under "occasionally useful supplementary information." But not yet "primary" either — Engine holds a real, opposite-direction edge on total disagreement, and the toss-up segment shows no SmartSim advantage at all. The evidence supports SmartSim's role being **conditional on the type of disagreement**: trust it more for side/spread calls, especially in large-mismatch situations; trust the Engine more for totals when they substantially disagree; treat toss-ups as already well-served by the existing blend.
