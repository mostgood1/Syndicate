# Syndicate World-Class Implementation Plan

This is the official phased implementation plan for turning Syndicate into a world-class multi-sport sim, prediction, recommendation, and intelligence system.

The rule is simple: improve the system without breaking current behavior. Every phase must be additive, contract-driven, and validated against the existing product surface before moving forward.

The current baseline already includes:

- a shared artifact-manifest layer
- a central odds refresh orchestrator
- per-sport mirror and ingest contracts
- a worker-backed refresh-state abstraction
- sport-specific intelligence routing and analysis views
- parlay and correlation runtime boundaries
- MLB as the dense-board reference surface

That is the foundation. The plan below is how to grow it into the target system without derailing the current product.

## Unified platform standardization

Syndicate should behave like one platform with sport-specific surfaces, not a loose collection of separate sport engines.

The default approach is standardization:

- use mature MLB, NBA, and WNBA deliverables as the canonical reference surfaces for shared logic, artifact shape, sim orchestration, and recommendation plumbing
- keep sport-specific differences only where the sport truly requires them
- prefer a shared engine, shared contracts, and shared ranking/evaluation logic before adding sport-local branches
- treat any sport variation as an exception that must prove it improves the product without fragmenting the platform

This means the long-term target is one unified logic engine with sport modules plugged into it, not parallel engines that happen to share some code.

Standardization rules:

1. Shared contracts come first.
2. Shared data shapes come second.
3. Shared sim and recommendation logic come third.
4. Sport-specific overrides are allowed only when they preserve the shared contract and are justified by real sport structure.
5. If a new sport needs a divergence, the divergence must be small, documented, and tested against the unified baseline.

The practical result is that MLB, NBA, and WNBA should be treated as the maturity anchors for the broader platform. Other sports should converge toward those patterns unless they have a stronger, proven structure that still fits the same platform contract.

## Non-negotiable delivery rules

1. Preserve existing route, payload, and artifact contracts unless a replacement is proven in tests.
2. Prefer additive changes over rewrites.
3. Keep compatibility shims until the new path is validated end to end.
4. Do not remove source-app fallbacks, mirror paths, or legacy readers until the replacement path is fully exercised.
5. Every phase must include a focused regression test slice before it is considered complete.
6. A phase is not done until it passes validation in the same environment where it will run.

## Phase 0: Freeze the current contract surface

Goal: lock down the current behavior so the rest of the work can move safely.

Scope:

- MLB board, archive, and live-lens contract
- NBA/WNBA/NHL/NFL/NCAAF/NCAAB artifact contracts
- daily update and refresh-and-gate orchestration
- intelligence query response shape
- parlay and same-game-parlay payload shape

Deliverables:

- a stable contract inventory for every sport
- regression coverage for the current launch surfaces
- a documented list of allowed compatibility shims

Exit criteria:

- the current user-facing behavior is captured by tests or explicit docs
- any future regression can be traced to a specific phase change

## Phase 1: Make the artifact layer universally reliable

Goal: ensure every sport can be read, refreshed, and mirrored through the same stable artifact contract.

Scope:

- normalize per-sport source_artifacts and mirror roots
- keep local source-repo compatibility only where needed
- preserve requested-date semantics and prevent silent fallback drift
- make daily refresh routing consistent across all sports

Deliverables:

- consistent source-artifact bundle roots for every current sport
- mirrored ingest paths that work in local, hosted, and compatibility modes
- tests that verify the planner and mirror scripts resolve the right roots

Exit criteria:

- no normal refresh path depends on an ambiguous or sport-specific ad hoc root
- the daily update wrapper can be rerun without changing existing behavior

## Phase 2: Make simulation the compute core

Goal: turn simulation into the thing that powers recommendations, not a downstream batch afterthought.

Scope:

- sim planning before execution
- explicit run modes for full, incremental, backfill, sim-only, and evaluation-only work
- run-state and checkpoint handling
- persisted sim inputs, outputs, and provenance

Deliverables:

- a documented sim execution contract
- persistent run-state and checkpoints
- phase-specific tests for first run, incremental run, no-op run, and partial failure recovery

Exit criteria:

- simulation runs are reproducible from stored inputs
- recommendation outputs can be traced back to a specific sim run and artifact set

## Phase 3: Build the intelligence engine into a real decision layer

Goal: answer betting questions with evidence, rankings, and professional-grade reasoning.

Scope:

- sport-aware query routing
- candidate collection with artifact-backed evidence
- market normalization and market-shape reasoning
- richer writeups for pregame, live, and explainer questions
- same-game and cross-sport reasoning that respects correlation and risk context

Deliverables:

- a stable response contract for evidence, recommendations, and rationales
- sport-native analysis views that expose the right advanced inputs
- parlay and SGP payloads that explain fit, correlation, and risk

Exit criteria:

- the query engine can answer the common betting questions without source-app fallbacks
- the response format remains stable enough for the UI and downstream consumers

## Phase 4: Close the evaluation loop

Goal: make the recommendation engine learn from outcomes instead of only producing static outputs.

Scope:

- outcome tracking
- calibration, accuracy, CLV, and ROI-style evaluation
- drift detection and recommendation quality monitoring
- feedback-driven ranking adjustments

Deliverables:

- a durable evaluation history per sport and market family
- regression tests for recommendation persistence and scoring behavior
- surfaced quality signals that can be used by the intelligence layer

Exit criteria:

- recommendations can be measured against outcomes at a repeatable cadence
- the system can identify when confidence should increase or decrease over time

## Phase 5: Harden ops and runtime boundaries

Goal: keep refresh, status, and job execution outside the web request path.

Scope:

- worker-driven refresh execution
- durable refresh-state storage
- hosted-safe read/write separation
- job observability and failure recovery

Deliverables:

- web service reads state; worker owns execution
- refresh status survives restarts
- ops endpoints stay stable while the backend evolves

Exit criteria:

- the web process is not the parent of long-running refresh jobs
- status and logs are recoverable from durable storage

## Phase 6: Expand toward a true world-class product

Goal: once the contracts are stable, extend quality and coverage without destabilizing the core.

Scope:

- deeper sport-native explainers
- richer live decisioning
- policy selection and adaptive recommendation strategy
- broader sport coverage as the platform grows

Deliverables:

- new sport modules can inherit the same contract model
- advanced features can be added without changing the baseline rails

Exit criteria:

- new sports can join the platform by following the same artifact, sim, and intelligence contracts

## Execution sequence

1. Finish Phase 0 and keep it green.
2. Complete Phase 1 with the smallest possible cross-sport contract changes.
3. Move to Phase 2 only after the artifact layer is stable.
4. Start Phase 3 only after simulation provenance is reliable.
5. Add Phase 4 once the recommendation path is traceable and reproducible.
6. Finish Phase 5 before expanding the hosted runtime model further.
7. Use Phase 6 only after the platform contract is stable and observable.

## Change-control rules

- No phase may begin if the previous phase is not validated.
- No refactor may remove a compatibility path until a focused test proves the new path is equivalent or better.
- If a change touches a live route, daily update path, or artifact root, it must carry a regression test.
- If a change affects a sport-specific contract, it must be checked against the shared contract model before merging.

## Definition of done

Syndicate is world-class when it can:

- answer betting questions with evidence-backed reasoning across all supported sports
- generate pregame, live, parlay, and SGP recommendations from the same platform contract
- evaluate and learn from outcomes over time
- refresh and publish artifacts without breaking current behavior
- onboard new sports by following the same simulation, artifact, and intelligence pattern

## Current implementation anchor

The current product already has the right starting points:

- MLB as the dense board reference
- shared artifact-manifest and refresh-state layers
- centralized odds refresh orchestration
- sport-specific intelligence builders and parlay runtime boundaries
- contract tests that protect the current behavior

This plan keeps those assets intact while moving the platform forward in small, testable phases.