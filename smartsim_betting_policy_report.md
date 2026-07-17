# SmartSim Betting Policy Reassessment

- Date: 2026-07-16
- Scope: NCAAF, pure analysis and recommendation — **no code was modified.** SmartSim 2.0 simulation logic, both calibration profiles, and blend weights are untouched. All candidate policies below are counterfactuals computed from the same real, already-collected 752-game log (`smartsim2_performance_tracking`), calling the existing, unmodified `blend_margin()`/`grade_ats_pick()`/`grade_totals_pick()` as building blocks — nothing in `smartsim2_blend.py` or `smartsim2_betting_performance.py` was changed to produce this report.
- References: `smartsim_betting_performance_report.md`, `smartsim_decision_policy_report.md`, `smartsim_signal_attribution_report.md`.
- Sample: the same 752 real games, all 16 weeks of the 2025 season, graded ATS and totals at standard -110/-110.

## Task 1: Audit of Every Current Betting-Relevant Policy

| Policy | Precise definition | Status |
| --- | --- | --- |
| Margin blend weights | `blend_margin = 0.395 × Engine + 0.605 × SmartSim` | Active, protected (not evaluated for change here) |
| Margin large-mismatch override (Phase 4) | If `\|reference margin\| ≥ 10`, margin = **SmartSim's margin**, unblended | Active — **this report's central subject** |
| Total blend weights | `blend_total = 0.114 × Engine + 0.886 × (SmartSim − 6.11)` | Active, protected (not evaluated for change here) |
| Total override | None — always blended, unconditionally, every game | Active, no exception exists |
| `TOSSUP_MARGIN_THRESHOLD = 5.0` | Declared and exported from `smartsim2_blend.py` | **Audit finding: dead constant.** Grepped the entire module and every NCAAF file that imports from it — this value is never read by any conditional in `compute_blend()` or anywhere else. It has been documented in prose (e.g., "toss-ups: no change, already blended") since the original ensemble evaluation but never actually gates behavior. Worth removing or wiring up in a future cleanup pass; not touched here since code changes are out of scope for this phase. |

## Task 2: ATS ROI vs. Prediction Accuracy — Why This Report Exists

`smartsim_betting_performance_report.md` already established the core problem this reassessment responds to: forecast accuracy (does the source predict the correct straight-up winner) and ATS profitability (does the source's margin beat the closing spread) are different questions that can point in opposite directions. The clearest example, reconfirmed here: in the large-mismatch subset, SmartSim's straight-up accuracy is far better than Engine's (~80% vs. ~72%, per `smartsim_monitoring_phase2_report.md`), but Engine's ATS record in that exact subset (55.05% win, +5.09% ROI) beats SmartSim's (50.81%, -2.99%) by a wide margin. Every comparison in this report uses **ATS/totals ROI as the objective**, not accuracy, per this phase's stated goal.

## Task 3: Large-Mismatch Handling, Specifically

Five ATS margin policies compared on the same 752 real games (all counterfactuals computed from already-stored `engine_margin`/`smartsim_margin`/`market_margin`/`actual_margin` — no new data):

| Policy | Overall (n=752) win% / ROI | Large mismatch (n=310) win% / ROI | Side disagreement (n=326) win% / ROI |
| --- | --- | --- | --- |
| Engine-only | 53.14% / +1.44% | **55.05% / +5.09%** | 50.00% / -4.55% |
| SmartSim-only | 51.54% / -1.61% | 50.81% / -2.99% | 56.44% / +7.75% |
| **Current (Phase 4: SmartSim-only if large mismatch, else blend)** | 50.73% / -3.14% | 50.81% / -2.99% | 51.23% / -2.20% |
| Pre-revision (Engine-only if large mismatch, else blend) | 52.47% / +0.17% | 55.05% / +5.09% (= Engine-only) | 50.61% / -3.37% |
| Always-blend (no exception at all) | 50.73% / -3.14% (= Current, exactly) | 50.81% / -2.99% (= Current, exactly) | 51.23% / -2.20% (= Current, exactly) |

**A striking, verified-not-assumed finding**: the current (post-Phase-4) policy and "always-blend" (removing the large-mismatch exception entirely, using nothing but the ordinary 0.395/0.605 weights everywhere) produce **byte-identical ATS picks on every single one of the 752 games** — confirmed directly (0 games where the two picks differ), not just similar aggregate stats. In this real dataset, the weighted blend's own math never crosses the market line differently than pure SmartSim does inside the large-mismatch subset, so Phase 4's override is currently doing nothing that the ordinary blend formula wouldn't already do on its own. Phase 4's practical effect, measured in real ATS picks, has been **zero** — the "policy" is real and documented, but on this data its behavior is indistinguishable from having no override at all.

The **pre-revision policy is a real, meaningfully different candidate** and is the best-supported reversal: it recovers Engine-only's full advantage in the large-mismatch subset (identical numbers, since it uses Engine there) while keeping the ordinary blend elsewhere, landing at a small-but-real overall improvement (+0.17% vs. -3.14% today) — better than current, though still short of pure Engine-only (+1.44%) because Engine-only also wins outside the large-mismatch subset in ways the pre-revision policy doesn't capture.

## Task 5 (and the real finding of this report): A Better Revised Candidate — Disagreement-Triggered, Not Magnitude-Triggered

Phase 4's mechanism keys the override off **market-margin magnitude** (`|market_margin| ≥ 10`). The betting-performance data points somewhere else: SmartSim's real ATS edge is concentrated in **side-disagreement games** (56.44% win / +7.75% ROI), not in large-magnitude games as such. Testing a candidate policy keyed off disagreement instead of magnitude — **Engine's margin by default; SmartSim's margin specifically when the two sources pick different sides** — on the same 752 games:

| Category | n | Win % | ROI % | Units Net |
| --- | --- | --- | --- | --- |
| **Overall** | 752 | **55.94%** | **+6.80%** | **+50.91** |
| Large mismatch | 310 | 55.70% | +6.34% | +19.45 |
| Conference games | 548 | 55.76% | +6.45% | +35.27 |
| Non-conference games | 204 | 56.44% | +7.74% | +15.64 |
| Side disagreement | 326 | 56.44% | +7.75% | +25.27 |

This candidate beats every other policy tested — current, pre-revision, pure Engine-only, and pure SmartSim-only — in **every category**, including the large-mismatch subset Phase 4 was built for (55.70%/+6.34%, better than both pure Engine-only there, +5.09%, and light-years ahead of current, -2.99%). It is not proposed as an implementation in this phase (blend weights and the decision mechanism are out of scope for this reassessment to change), but it is the clearest, most consistent, most evidence-backed candidate this project has produced for a future "revise" pass: **gate the ATS override on side disagreement, not market-margin magnitude.**

### Totals: no change indicated

Totals has no override mechanism to reassess — `blend_total()` runs unconditionally regardless of margin policy, and it is already the best-performing source in every category tested in `smartsim_betting_performance_report.md` (+9.02% ROI overall, best-or-tied-best everywhere). There is no betting-performance case for touching it.

## Task 4/7: Explicit Answers

### Which source should drive ATS picks?

Neither exclusively, and not the current policy. The strongest evidenced answer is a hybrid: **Engine by default, SmartSim specifically when the two sources disagree on side** — this candidate (Task 5 above) outperforms pure Engine-only, pure SmartSim-only, the current policy, and the pre-revision policy, in every category tested.

### Which source should drive totals?

**Consensus (the existing blend), unchanged.** Demonstrated the best totals performer in every category in `smartsim_betting_performance_report.md`; nothing in this reassessment's data suggests touching it.

### Should ATS and totals use different policies?

**Yes, unambiguously.** Totals should keep its current, always-blended, Consensus-driven approach exactly as is. ATS needs a materially different mechanism — the evidence does not support using the same "blend below a threshold, defer above it" structure that totals never needed and that ATS's current version of has (as shown above) collapsed into being no different from having no override at all.

### Should the Phase 4 revision remain in place?

**Not as currently constructed, for ATS.** The direct 310-game counterfactual shows Phase 4 (SmartSim-only on large mismatch) cost roughly 25 units of ATS value relative to the pre-revision (Engine-only on large mismatch) policy in exactly the subset it targets, and — more precisely — has had **zero net effect on real ATS picks** relative to simply never having built the override at all, since its output is indistinguishable from the ordinary blend formula in this data. Phase 4 remains fully justified on the straight-up-accuracy question it was built to answer; it is not justified on the ATS-profitability question this report is scoped to answer. The evidence favors moving toward the disagreement-triggered candidate (Task 5) over either keeping Phase 4 as-is or reverting to the pre-Phase-4 mechanism, since the disagreement-triggered candidate beats both.

## Final Verdict

**Hybrid Policy.**

Not "Keep Policy" — the large-mismatch override's real-world ATS effect has been either mildly negative (vs. pre-revision) or completely inert (vs. no override at all), which is not a case for leaving it as the ATS mechanism. Not "Revert Policy" outright either — a straight reversion to the pre-Phase-4 mechanism is a real improvement (+0.17% vs. -3.14% overall) but is dominated by the disagreement-triggered candidate this report identifies (+6.80% overall, best in every category), so recommending a plain revert would leave real, demonstrated value on the table. **Hybrid** captures both halves of the actual finding: totals keeps its current policy completely unchanged (no case for touching it), while ATS should move toward a disagreement-triggered mechanism rather than either the current magnitude-triggered one or a simple reversion to its predecessor. This report does not implement that change — consistent with every prior reassessment-only phase in this project, that step (were it approved) belongs in a separate, explicitly-scoped policy-revision phase.
