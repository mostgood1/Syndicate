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

Status: completed.

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

## Phase 3: Build a central odds management system

Status: completed.

Goal: own odds ingestion, refresh, hydration, replay, line movement, and snapshot precedence across the platform.

Scope:

- odds control-plane orchestration
- pregame and live odds hydration from shared artifact roots
- line-movement artifact refresh and replay safety
- snapshot tracking, freshness, and reconciliation rules

Deliverables:

- a documented odds control-plane contract
- centralized refresh and replay precedence for odds artifacts
- focused tests for pregame, live, and line-movement coverage

Exit criteria:

- all covered sports resolve odds from the same precedence model
- refresh, snapshot, and UI payloads agree on the active odds source

## Phase 4: Build the intelligence engine into a real decision layer

Status: completed.

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

## Phase 5: Close the evaluation loop

Status: completed.

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

## Phase 6: Harden ops and runtime boundaries

Goal: keep refresh, status, and job execution outside the web request path while preserving clear runtime budgets and observable execution time.

Scope:

- worker-driven refresh execution
- durable refresh-state storage
- hosted-safe read/write separation
- job observability and failure recovery
- execution-time visibility for long-running jobs
- budget-aware placement of work that can be moved off the critical path

Deliverables:

- web service reads state; worker owns execution
- refresh status survives restarts
- ops endpoints stay stable while the backend evolves

Kickoff:

- Phase 6 is active now.
- Start with worker-owned refresh execution and hosted-safe read/write separation.
- Then wire the checkpoint and replay path into restart-safe run-state updates.

First workstream:

- [x] introduce a worker-owned refresh entrypoint
- [x] keep web refresh handlers read-only over refresh state
- [x] route state writes through the worker path only
- [x] emit a structured refresh-worker status artifact
- [x] emit terminal refresh-worker status updates after the queued job finishes
- [x] emit a structured queued-job status artifact
- [x] surface worker and queued-job status artifacts in the ops refresh status payload

Phase 6 sub-slices:

- [x] worker-owned refresh execution
- [x] hosted-safe read/write separation for refresh state
- [x] keep refresh execution outside the web request path
- [x] persist durable run checkpoints
- [x] load replay context from the latest checkpoint
- [x] restore run-state safely after restart
- [x] stable status and manifest artifacts for refresh observability
- [x] publish latest checkpoint and run-state artifacts alongside the manifest
- [x] runtime-budget and trace visibility for long-running jobs

Exit criteria:

- the web process is not the parent of long-running refresh jobs
- status and logs are recoverable from durable storage

Validation notes:

- targeted regressions now cover the daily-update run-state, checkpoint, replay, and trace scaffolding
- the daily-update docs and tests now reflect the manifest, checkpoint, replay, and trace path instead of only the preexisting run manifest artifact
- replayed daily-update runs now surface a resumed run-state when a checkpoint is applied, keeping restart behavior explicit in the public artifacts
- the daily-update ops surface now exposes stable checkpoint, run-state, and trace artifacts alongside runtime-budget details for long-running refresh visibility
- the covered scaffolds include [tests/test_unified_daily_update_run_state_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_run_state_scaffold.py), [tests/test_unified_daily_update_replay_context_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_replay_context_scaffold.py), [tests/test_unified_daily_update_replay_apply_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_replay_apply_scaffold.py), [tests/test_unified_daily_update_sim_trace_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_sim_trace_scaffold.py), [tests/test_unified_daily_update_status_artifact_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_status_artifact_scaffold.py), and [tests/test_unified_daily_update_sim_noop_detection.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_sim_noop_detection.py)
- refresh-worker observability is now pinned by [tests/test_refresh_worker.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_refresh_worker.py), including the idle, running, and terminal status artifact states
- the legacy ops full-refresh route now launches and records refresh work without a web-process monitor thread, keeping the request path short while worker-backed refresh execution remains the durable path
- resumed daily-update runs now skip an already-completed source_update checkpoint branch instead of blindly rerunning that completed stage
- the daily-update root now publishes a durable latest run-state artifact alongside the checkpoint so restart-safe state is visible outside the manifest itself
- the ops refresh status payload now exposes the latest daily-update checkpoint and run-state artifacts alongside the manifest so restart-safe state is visible through the public contract
- the ops refresh page now renders the latest daily-update checkpoint and run-state stages alongside the refresh status summary
- the daily-update root now publishes a durable latest trace artifact alongside the checkpoint and run-state so trace visibility is available through the public contract and ops page
- the refresh status payload and ops page now expose elapsed-time and runtime-budget fields for both the active refresh job and the latest daily-update artifact set
- the ops page now shows elapsed time on recent refresh history cards so long-running-job visibility stays consistent across active and historical runs
- the ops page now shows remaining runtime budget for the active refresh job and the latest daily-update artifact set
- the ops page now shows elapsed, remaining, and total budget on recent refresh history cards so long-running-job visibility stays consistent across active and historical runs
- the queued refresh contract now validates required manifest and run-summary paths before claiming work, keeping the worker-owned handoff strict and durable
- the admin full-refresh route now forces manifest-only handoff so the web request path no longer starts a local subprocess for refresh execution


- queued-job observability is now pinned by [tests/test_refresh_odds_job.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_refresh_odds_job.py), including the terminal wrapper status artifact
- ops refresh status coverage is now pinned by [tests/test_ops.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_ops.py), including the surfaced worker and queued-job artifact payloads

## Phase 7: Expand toward a true world-class product

Goal: once the contracts are stable, extend quality and coverage without destabilizing the core or regressing the time-to-answer experience, including the `/intelligence` live board as the primary decision surface.

Scope:

- deeper sport-native explainers
- richer live decisioning
- policy selection and adaptive recommendation strategy
- broader sport coverage as the platform grows
- product choices that preserve latency budgets and runtime predictability
- a live board surface that continuously surfaces fresh options from pregame projections, live lines, and movement data
- shared decision inputs so Ask the Syndicate explains the same board state the live board is using

Deliverables:

- new sport modules can inherit the same contract model
- advanced features can be added without changing the baseline rails
- visible performance guardrails for new experiences
- the live board stays fresh throughout the day and during games as new projections and line movement arrive
- Ask the Syndicate reads from the same board contract so explanation and surfacing stay aligned

Exit criteria:

- new sports can join the platform by following the same artifact, sim, and intelligence contracts
- the live board and Ask the Syndicate both reflect the same current decision logic and live movement inputs

## Phase 8: Optimize execution and platform efficiency

Goal: make the world-class system fast, predictable, and cost-aware once the contracts are stable.

Scope:

- execution-time profiling and latency reduction
- throughput tuning for refresh, sim, and intelligence paths
- cache and reuse strategies where they do not weaken correctness
- workload shaping so expensive work happens off the critical path when possible

Deliverables:

- measurable latency and throughput targets for major platform paths
- profiling checks for regressions in the critical user and refresh flows
- optimization guardrails that preserve the established contracts

Exit criteria:

- the platform can show reduced time-to-answer and time-to-refresh for the key flows
- optimization changes remain contract-safe and regression tested

## Execution sequence

1. Finish Phase 0 and keep it green.
2. Complete Phase 1 with the smallest possible cross-sport contract changes.
3. Move to Phase 2 only after the artifact layer is stable.
4. Start Phase 3 only after simulation provenance is reliable.
5. Add Phase 4 once the odds control plane is stable and auditable.
6. Add Phase 5 once the recommendation path is traceable and reproducible.
7. Finish Phase 6 before expanding the hosted runtime model further.
8. Use Phase 7 only after the platform contract is stable and observable.
9. Add Phase 8 only after the platform is stable enough for execution-focused optimization.

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