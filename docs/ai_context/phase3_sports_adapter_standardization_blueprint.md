# Phase 3 Sports Adapter Standardization Blueprint

## Status

Blueprint only. This phase is the adapter-standardization pass that follows the completed refresh-contract work.

## Why This Phase Exists

Phase 1 removed the WNBA refresh failure caused by optional SmartSim-derived artifacts being treated as required.

Phase 2 made the refresh contract explicit across sports by splitting required and optional artifacts in the shared refresh / publish / status path.

Phase 3 is the next step: standardize the sport adapter layer so every sport builds the same simulation-facing contract before it reaches the engine, the board, or intelligence surfaces.

The goal is not to make SmartSim smarter or to patch roster quality. The goal is to make the adapter boundary uniform enough that sport differences are handled as explicit source-selection and normalization rules instead of hidden shape drift.

## Objective

Create one shared sports adapter standard that answers the same questions for every sport:

1. What source won?
2. Why did it win?
3. What inputs are simulation-eligible?
4. What inputs are display-only enrichment?
5. What freshness or fallback rule was applied?
6. What evaluation context should influence confidence?

## Current Baseline

The current shared implementation already exists in [syndicate/features/shared/simulation_adapter.py](../../syndicate/features/shared/simulation_adapter.py).

The current design reference is [docs/ai_context/simulation_adapter_design.md](simulation_adapter_design.md).

The canonical cross-sport run reference is the latest daily-update simulation contract under [reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json](../../reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json).

The shared simulation engine is already sport-agnostic. The inconsistent part is the per-sport adapter input shape and source selection behavior.

## Phase 3 Target State

Each sport adapter should produce a normalized payload with the same top-level sections:

- identity: sport, date, source mode, source provenance
- freshness: requested date, resolved date, current-day status, stale status
- source selection: primary source, fallback chain, winner explanation
- game records: normalized matchup rows with team, player, market, live, and evaluation inputs
- simulation inputs: engine-ready context separate from display decoration
- presentation hints: fields for board and live-lens rendering that do not alter simulation meaning
- diagnostics: reason codes, suppression reasons, and missing-input warnings

## Non-Goals

Phase 3 does not:

- improve SmartSim model accuracy
- improve roster quality
- add new sport-specific patches just to solve one sport in isolation
- rewrite the simulation engine math
- move display-only fields into the engine contract
- collapse richer sport surfaces into a generic lowest-common-denominator board

## Blueprint Principles

1. Standardize the adapter contract before standardizing new sport features.
2. Keep source discovery, source selection, normalization, and presentation assembly as separate steps.
3. Make current-day precedence explicit instead of implied.
4. Prefer shared rules with sport-local configuration over sport-local branching in the control path.
5. Record the selected source and fallback reason in every contract.
6. Treat evaluation history as an adapter input, not only a reporting artifact.
7. Preserve display-only enrichment outside the simulation-meaningful input set.

## Workstreams

### Workstream 1: Canonical adapter schema

Define the shared adapter schema as the authoritative input contract for all sports.

The schema should include:

- source mode
- freshness metadata
- source paths
- normalized games
- simulation context
- display-only context
- evaluation context
- warnings and suppression reasons

This workstream is complete only when every sport can emit the same structural shape even if the underlying source data differs.

### Workstream 2: Source selection standard

Standardize the decision rule that chooses between stored artifacts, live rows, mirrored bundles, and fallback sources.

The selector should:

- always record the winner
- always record why it won
- mark stale or partial sources explicitly
- preserve replay safety by making the choice deterministic for the same inputs

This is where current-day behavior should converge across sports without making the adapter itself sport-specific.

### Workstream 3: Normalization boundary

Move sport-specific row translation into a normalized game record layer.

The normalization layer should map source rows into a common record that exposes:

- game identity
- team identity
- player inputs when available
- market inputs when available
- live state when available
- evaluation context when available

The normalization layer must not decide presentation layout.

### Workstream 4: Engine input builder

Convert normalized game records into engine-ready simulation context.

This layer should decide:

- which team projections are eligible
- which player projections are eligible
- which live signals affect confidence or variance
- which market signals alter edge or probability weight

The engine input builder must be stable enough to replay from stored artifacts.

### Workstream 5: Board and live-lens attachment

Attach adapter outputs to board and live-lens consumers after the simulation contract is finalized.

The board layer may decorate the payload, but it should not re-decide source selection or normalize source rows on its own.

The board and live-lens surfaces should consume the same source-selection truth so they stop diverging on current-day precedence.

### Workstream 6: Evaluation feedback loop

Feed calibration, accuracy, and drift signals back into the adapter scoring rules.

This workstream should make the adapter smarter about source choice and confidence, but only after the contract is stable.

## Sport Ordering

Recommended rollout order:

1. NBA and WNBA first, because the live-state and sim-detail lanes already exist.
2. MLB next, because the artifact stack is richest and can prove the contract against the densest board surface.
3. NHL next, because stored predictions and live-lens signals can validate source precedence.
4. NFL next, because weekly snapshots are a useful test of non-daily adapter behavior.
5. NCAAB and NCAAF last, because the stored-summary and mirrored-recommendation patterns should converge onto the same adapter shape once the contract is stable.

## Exit Criteria

Phase 3 is complete when:

- every supported sport emits the same adapter envelope
- source selection is recorded and replayable
- current-day precedence rules are explicit and consistent
- board and intelligence consumers read the same normalized adapter output
- display-only fields no longer affect simulation meaning
- the shared adapter contract has regression coverage across the current sport set

## Validation Plan

The Phase 3 validation slice should prove four things:

1. The adapter schema is stable across sports.
2. The source-selection winner is explicit for current-day and stored-date cases.
3. The board and intelligence surfaces consume the same normalized input shape.
4. Optional enrichment can be absent without breaking the simulation contract.

Suggested regression categories:

- shared schema smoke tests
- sport-parity contract tests
- current-day precedence tests
- stale-source fallback tests
- board / intelligence payload parity tests

## Deliverable Sequence

1. Lock the canonical adapter schema.
2. Implement adapter wrappers that emit the shared schema.
3. Standardize source-selection logic across sports.
4. Keep board and intelligence consumers on the shared adapter output.
5. Add evaluation feedback only after the contract is stable.

## Relationship To Prior Phases

Phase 1 proved that optional downstream artifacts must not block refresh completion.

Phase 2 proved that required versus optional contract semantics belong in the shared refresh / publish / status layer.

Phase 3 extends that same discipline to the simulation adapter layer.

The pattern is the same: define the shared contract first, then move sport variance to the edges, then validate parity before any deeper sport-specific refinement.