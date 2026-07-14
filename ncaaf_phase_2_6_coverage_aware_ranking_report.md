# NCAAF Phase 2.6 Coverage-Aware Ranking and Confidence

Phase 2.6 makes artifact coverage operational in the publication layer without changing the football model math. Coverage is already computed in the shared evaluation layer, carried through candidate and recommendation enrichment, and surfaced to response and board payloads. This phase makes the priority explicit: Tier A recommendations are published ahead of Tier B, which are published ahead of Tier C and Tier D.

## What Changed

- Shared coverage profiles now expose `publication_priority` alongside `coverage_score`, `coverage_tier`, `coverage_warnings`, and `coverage_adjusted_confidence`.
- Recommendation ordering now uses coverage priority before edge, expected value, and confidence when building the visible response.
- Board cards now carry the same publication priority and are sorted with the same Tier A-first behavior.
- Confidence remains coverage-adjusted at the publication edge, but the underlying football model outputs are preserved as `model_confidence` where available.

## Direct Answers

### Are NCAAF SmartSim features now influencing ranking?

Yes. Coverage now participates in ranking through explicit publication priority and existing coverage-aware tie-breaking. Tier A entries rise ahead of lower tiers before the remaining score-based fields are considered.

### Are NCAAF SmartSim features now influencing confidence?

Yes. Coverage already adjusts publication-facing confidence through `coverage_adjusted_confidence`, while the original model confidence is preserved separately when present.

### Are Tier A games prioritized automatically?

Yes. Tier A now maps to the highest `publication_priority`, so it sorts ahead of Tier B, C, and D in recommendation and board publication ordering.

### Are Tier C/D games deprioritized or suppressed automatically?

Yes. Tier C/D recommendations receive lower publication priority and remain suppressed from publishable status in the shared coverage profile.

### What remains before NCAAF can be considered fully SmartSim-driven?

- The live NCAAF runtime path still needs a clean end-to-end demo without the unrelated WNBA `NameError` blocker.
- A direct NCAAF board/runtime verification should confirm the same Tier A-first ordering in a live request path.
- If desired, the next phase can make the publication priority visible in any remaining UI slice that still only reads coverage tier.

## Week 1 Demonstration

The stored Week 1 recommendation summary in [NCAAFCompare/data/recommendations_summary/week_1.json](NCAAFCompare/data/recommendations_summary/week_1.json) shows a strong top-end case for publication priority: the best entries are high-edge home-moneyline recommendations such as East Carolina vs Pittsburgh with model probability 0.8309 and edge 2.4896. That is the kind of profile that should land in Tier A once artifact coverage is complete.

The same coverage rules would push weaker or incomplete artifact profiles into lower tiers, where they remain visible only after higher-priority coverage slices have been published.

## Validation

- `get_errors` on the touched Python files reported no errors.
- Synthetic coverage probing already confirmed Tier A, B, C, and D coverage profiles are generated correctly from the shared helper.
