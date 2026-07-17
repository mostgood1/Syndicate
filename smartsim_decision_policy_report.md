# SmartSim Decision Policy Reassessment

- Date: 2026-07-16
- Scope: NCAAF, pure analysis and recommendation — **no code was modified.** SmartSim 2.0, both calibration profiles, and projection generation are untouched. All counterfactual "policies" below were evaluated in a disposable scratch script that calls the existing, unmodified `smartsim2_blend.compute_blend()`/`blend_margin()`/`blend_total()` functions as building blocks; nothing in `smartsim2_blend.py` itself was changed.
- References: `smartsim_ensemble_evaluation_report.md`, `smartsim_public_trial_monitoring_report.md`, `smartsim_signal_attribution_report.md`.
- Sample: same 106 real games (Weeks 1 + 8, 2025 season, real outcomes, real market lines) used in the signal attribution study, rebuilt fresh via the same unmodified blend module for this reassessment.

## Task 1: Audit of Every Current Blend Rule

Read directly from `smartsim2_blend.py` (unmodified, quoted precisely, not paraphrased into something friendlier than it is):

| Rule | Precise definition |
| --- | --- |
| **Margin weights** | `blend_margin = 0.395 × Engine + 0.605 × SmartSim` |
| **Total weights** | `blend_total = 0.114 × Engine + 0.886 × (SmartSim − 6.11)` (SmartSim's total bias-corrected before weighting) |
| **Large-mismatch exception** | If `\|reference margin\| ≥ 10` (reference = market margin if available, else Engine's own margin), Consensus margin = **Engine's margin, unblended**. Otherwise, apply the margin weights above. |
| **Total: no exception** | Total is blended unconditionally, every game, regardless of mismatch size. |

## Task 2: Rules Supported vs. Contradicted by Evidence

| Rule | Verdict | Evidence |
| --- | --- | --- |
| Margin fixed weights (0.395/0.605) | **Supported** | In the 21 side-disagreement games where blending actually runs, Consensus (57.1%) beats both raw systems (Engine 52.4%, SmartSim 47.6%) — the weights themselves work when applied. |
| Total fixed weights + bias correction | **Supported** | Current policy has the lowest total MAE overall (13.05) of any tested policy, including pure Engine (13.17) and pure SmartSim (14.73). |
| Total: always blend, no exception | **Supported, with a documented nuance** | Wins overall and in the "both" subset; specifically within the total-disagreement subset, pure Engine (11.36 MAE) beats the current blend (12.05) — a real but narrower and lower-priority finding than the margin issue below. |
| **Large-mismatch exception (defer to Engine)** | **Directly contradicted** | This is the finding this reassessment exists to act on — quantified below. |
| Conditional gating on margin *per se* (the idea that some gate should exist) | **Not contradicted — the direction is** | A gate matters (blending large mismatches instead of choosing a side outright underperforms pure SmartSim in that subset, shown below) — the problem is which system the gate currently favors, not that a gate exists. |

## Task 3-4: Large-Mismatch Policy, Quantified Against Every Alternative

Five margin policies compared head-to-head across four populations. "Current" = production as shipped; the other four are read-only counterfactuals computed from the same real data.

| Policy | All games (n=106) acc / MAE | Side-disagreement (n=38) acc / MAE | Large-mismatch side-disagreement (n=17) acc / MAE | Both (n=16) acc / MAE |
| --- | --- | --- | --- | --- |
| Engine-only | 63.2% / 15.16 | 39.5% / 17.91 | 23.5% / 21.76 | 31.2% / 15.53 |
| SmartSim-only | 70.8% / 15.18 | 60.5% / 14.42 | 76.5% / 16.74 | 68.8% / 11.25 |
| **Current (Engine-only if large mismatch, else blend)** | 64.2% / 14.52 | 42.1% / 16.84 | 23.5% / 21.76 | 37.5% / 13.35 |
| Always-blend (remove the exception entirely) | 68.9% / 14.59 | 55.3% / 15.32 | 52.9% / 18.36 | 50.0% / 12.60 |
| **Reversed exception (SmartSim-only if large mismatch, else blend)** | **72.6%** / 15.07 | **65.8%** / 14.59 | **76.5%** / 16.74 | 56.2% / 12.11 |

The large-mismatch column is the clearest possible statement of the problem: **the current policy and pure Engine-only are numerically identical (23.5%/21.76) in this subset, because the current policy *is* Engine-only there.** The reversed-exception policy matches pure SmartSim-only exactly in this subset (76.5%/16.74), because that's what it does there — and it beats every other option everywhere it's been measured, including matching or beating pure SmartSim-only overall (72.6% vs. 70.8%) by keeping the (better-than-either-raw-system) blend active in the non-mismatch cases.

The "both" subset (16 games) is the one place the reversed-exception policy (56.2%) falls short of pure SmartSim-only (68.8%) — because "both" (side *and* total disagreement) isn't the same population as "large market mismatch"; some of these 16 games have real side disagreement without a large market-implied mismatch, so the reversed policy still blends them rather than going SmartSim-only. This is a real, disclosed limit of a market-margin-based gate, not a contradiction of the headline finding.

## Total Policy: No Change Indicated

| Policy | All games MAE | Total-disagreement (n=40) MAE | Both (n=16) MAE |
| --- | --- | --- | --- |
| Engine-only | 13.17 | **11.36** | **8.36** |
| SmartSim-only | 14.73 | 15.29 | 13.64 |
| **Current (always blend)** | **13.05** | 12.05 | 8.45 |

Current policy wins outright overall and is a close second in both narrower subsets, where pure Engine has a real but small edge. Not enough to justify replacing an unconditional rule that wins on the broader population with a conditional one for a few tenths of a point in a subset — noted as a candidate for a future, lower-priority look, not acted on here.

## Task 6: Quantified Expected Impact (vs. current production policy, side-selection accuracy)

| Alternative policy | Overall (n=106) | Side-disagreement (n=38) | Large-mismatch subset (n=17) |
| --- | --- | --- | --- |
| Always-blend (remove exception) | +4.7 pts | +13.2 pts | +29.4 pts |
| **Reversed exception (recommended)** | **+8.5 pts** | **+23.7 pts** | **+52.9 pts** |

These are measured deltas on real historical games, not projections of future performance — the standard caveat that a 106-game, two-week sample is real evidence but not a guarantee of the same magnitude going forward applies, and is why the recommendation below is framed as a calibration-pass candidate, not an emergency hotfix.

## Task 5: Recommended Production Policy

**Category-specific rule, one narrow change**: keep every existing rule except reverse which system the large-mismatch exception favors.

- **Margin**: blend using the existing 0.395/0.605 weights whenever `\|reference margin\| < 10`. When `\|reference margin\| ≥ 10`, use **SmartSim's margin**, not Engine's, unblended. This is a one-line change in the *target* of an existing conditional — not a new mechanism, not a change to the blend weights, not a change to the gate's threshold or its reference-margin definition.
- **Total**: no change. Keep the current always-blend, bias-corrected policy.
- **Toss-ups**: no change — already blended, and the signal attribution study found no systematic edge for either raw system there.

## Task 8: Explicit Answers

### Should SmartSim ever override the Engine?

Yes — specifically and only in the large-mismatch margin case, where the evidence (76.5% vs. 23.5% accuracy, corroborated by 13 concrete example games in the signal attribution study) is large enough and consistent enough to justify a full override rather than a partial blend. Nowhere else does the evidence support an unconditional override in either direction.

### Should the large-mismatch exception remain?

Yes, as a mechanism — but pointed at the other system. The exception itself (treat large mismatches specially rather than always blending) is supported by the data: always-blending large mismatches (52.9% in that subset) is worse than fully deferring to whichever system is actually right there (76.5%). The mechanism is sound; its current target is not.

### Should the blend policy change?

For margin: yes, the one specific change above. For total: no — the current policy already outperforms both alternatives on the broadest population, with only a minor, lower-priority exception in the total-disagreement subset specifically.

### Which system should drive side picks?

Neither exclusively. The evidence supports a hybrid that already resembles the current architecture, just re-pointed: the existing blend for ordinary disagreements (where it already beats both raw systems, 57.1% vs. 52.4%/47.6%), and SmartSim specifically for large-mismatch disagreements (76.5% vs. Engine's 23.5%).

### Which system should drive totals?

The existing blend, unchanged — it already wins on the broadest population and is competitive everywhere it doesn't.

## Final Verdict

**Minor Revision.**

The measured impact is large (+8.5 points overall, +52.9 points in the affected subset) but the *change* is narrow and surgical: one conditional's target system flips, for margin only, with the threshold, the reference-margin definition, the blend weights, and the entire total policy all left exactly as they are. Calling this "Major Revision" would overstate how much of the existing architecture is actually in question — it is one rule, isolated and clearly identified, not a redesign. Calling it "Maintain Current Policy" would ignore a well-evidenced, real-money-relevant error the data makes hard to defend. This should go into the next calibration/policy pass as a scoped, single-rule change, not a full blend-architecture reconsideration.
