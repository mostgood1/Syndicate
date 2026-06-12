# Syndicate World-Class Execution Backlog

This file is the working execution tracker for [docs/syndicate_world_class_implementation_plan.md](c:/Users/tempadmin/OneDrive/Coding/Syndicate/docs/syndicate_world_class_implementation_plan.md).

The plan is to move in small, validated slices and keep the current product stable while doing it.

## Current covered sports inventory

The current Syndicate product surface covers these seven sports:

1. MLB
2. NBA
3. WNBA
4. NHL
5. NFL
6. NCAAF
7. NCAAB

Coverage meaning in this plan:

- MLB is the dense-board reference module and the most mature baseline.
- NBA and WNBA are the main basketball reference anchors for the unified engine.
- NHL, NFL, NCAAF, and NCAAB are active covered modules with sport-specific contract surfaces already in the repo.
- Any future sports should be added only after they can follow the same artifact, sim, and intelligence contract model.

## Per-sport contract map

| Sport | Current contract surface | Standardization gaps |
| --- | --- | --- |
| MLB | Dense-board reference module with cards, game detail, live-lens, daily archive, season betting-card surfaces, and rank-board API parity. | Use MLB as the canonical dense-board shape for shared board, archive, and live-lens contracts. Keep the MLB daily-date archive model as the reference for other sports. |
| NBA | Artifact-backed migration with cards, game detail, picks, props, live-lens, accuracy and recap lanes, season betting-card surfaces, and a stored-date archive. | Converge NBA props, live-lens, recap, and archive payloads into the shared engine shape so the richer basketball surface becomes a reusable baseline rather than a separate pattern. |
| WNBA | Artifact-backed migration with cards, game detail, picks, props, live-lens, local audit/accuracy payloads, and a stored-date archive lane. | Standardize WNBA against the NBA/MLB contract family for props, live-lens, archive, and evaluation fields; keep WNBA-specific gameplay differences only where required by league structure. |
| NHL | Artifact-backed migration with cards, a game drill-in, ranked picks, native live-lens and accuracy lanes, props reconciliation and props-lines surfaces, and a stored-date archive. | Bring NHL props reconciliation, lines, and live-lens into the shared artifact and freshness model so optional source-root backfill is only a compatibility path. |
| NFL | Near-complete module-family candidate with cards, a game drill-in, grouped weekly picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion. | Normalize the weekly cadence into the shared contract model so weekly archives and grouped picks still expose the same core recommendation/evaluation semantics as the daily sports. |
| NCAAF | Artifact-backed migration with weekly cards, a game drill-in, picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion. | Converge NCAAF onto the shared weekly contract shape used by NFL while keeping college-specific volatility and schedule structure explicit instead of implicit. |
| NCAAB | Mirror-first migration with cards, a game drill-in, a live-lens board, a season review page, a historical betting-card companion, and a results archive. | Standardize NCAAB raw-output and mirror flows into the same unified artifact/sim/intelligence contract while preserving the mirror-first source of truth. |

Shared standardization gaps across all sports:

- artifact-root handling still needs to converge on one consistent contract per sport
- sim execution should expose one unified provenance model, even when sport-specific sim internals differ
- recommendation, evaluation, and freshness fields should be shared wherever possible
- weekly sports need to fit the same decision engine as daily sports without hiding cadence differences
- sport-specific variation should remain visible in the data model, not leaked as ad hoc pipeline behavior

## Phase 0 kickoff

- [ ] Inventory the current contract surfaces for MLB, NBA, WNBA, NHL, NFL, NCAAF, and NCAAB.
- [ ] Confirm the unified standardization rule is explicit in the plan and used as the default decision rule.
- [ ] Keep the current regression guardrails green before any phase-1 artifact changes.
- [ ] Preserve every compatibility shim until the replacement path is proven in tests.

## Phase 1 next slice

- [ ] Normalize the remaining per-sport artifact-root assumptions into the shared source_artifacts contract.
- [ ] Verify the daily refresh wrapper stays consistent across all sports.
- [ ] Keep requested-date semantics and no-silent-fallback behavior stable.

## Phase 2 next slice

- [ ] Map simulation inputs and outputs to a single reproducible run contract.
- [ ] Add/confirm run-state and checkpoint persistence.
- [ ] Keep sim-mode changes additive until provenance is stable.

## Operating rule

Do not mark a phase complete until the current product surface, the new contract surface, and the focused regression tests all agree.