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
- the `/intelligence` live board remains the canonical shared decision surface for the platform
- Ask the Syndicate keeps reading the same board inputs and evidence bundle that power the live board
- live lens surfaces for games and props that keep interval lines, live odds, and projections aligned with the shared board contract instead of falling back to off-board intervals
- a Syndicate home command center at `/` that acts as the daily hub for all sports, surfacing games for the day, live game updates, pregame props, live props, and other high-value central actions
- shared decision inputs so Ask the Syndicate explains the same board state the live board is using
- a world-class UI system with dense but readable recommendation cards, clear visual hierarchy, responsive layouts, and accessible contrast
- consistent interaction patterns for filters, drill-downs, live-state chips, movement badges, and action affordances
- recommendation cards that clearly identify sport, team, player, prop or game market, line, movement, and simulated edge
- separate pregame and live lanes so users can tell whether a recommendation is for a pregame edge, a live in-game edge, or a market move already in flight
- live-game linkage that shows how a recommendation is performing once the game starts, including the current game state and the recommendation's status
- recommendation history that records what was recommended, what was placed, what won or lost, and how the policy should learn from the result
- portfolio and bet tracking that lets the operator add and remove actual wagers, maintain an open bet ledger, and see current exposure alongside recommendations
- a future-ready ledger model that can later expand to named user accounts without rewriting the core recommendation and tracking contract

Deliverables:

- new sport modules can inherit the same contract model
- advanced features can be added without changing the baseline rails
- visible performance guardrails for new experiences
- the live board stays fresh throughout the day and during games as new projections and line movement arrive
- the intelligence board stays the source of truth for recommendation, lane, and evidence presentation
- the home command center gives users one clear entry point for the day across all sports, with live games, pregame props, live props, and other priority surfaces grouped into a premium daily hub
- Ask the Syndicate reads from the same board contract so explanation and surfacing stay aligned
- the Ask surface stays semantically and visually aligned with the intelligence board and home command center
- the live board exposes explicit pregame and live recommendation lanes with clear game, team, and prop context
- game and prop live lenses stay consistent with live interval lines, odds, and projection updates across sports
- the live lens surfaces never fall back to off-board intervals when live state exists
- recommendation tracking captures outcome state, live-game performance, and policy learning signals
- portfolio tracking supports manual add/remove of actual bets and current exposure state
- the UI reads as a polished decision surface rather than a generic data dashboard, with clear hierarchy and mobile-safe layouts

Exit criteria:

- new sports can join the platform by following the same artifact, sim, and intelligence contracts
- the live board and Ask the Syndicate both reflect the same current decision logic and live movement inputs
- every recommendation card can be traced to its sport, market, edge, and the live or pregame lane it belongs to
- live recommendations stay tied to the active game state while the game is in progress
- the system can record placed bets and update portfolio exposure without breaking the recommendation feed
- recommendation history exists well enough to support later learning, optimization, and eventual per-user ledgers
- the live board and Ask surfaces stay visually coherent, accessible, and fast enough to feel premium on desktop and mobile

Workstreams:

1. Board contract and data model.
2. Live and pregame lane separation.
3. Recommendation history, outcome feedback, and policy learning hooks.
4. Portfolio and bet ledger tracking.
5. UI composition and interaction design.
6. Home command-center orchestration for the daily sports hub.
7. Ask The Syndicate parity with the shared decision surface.

Phase 7 execution slices:

1. Home command center shell: make `/` the daily hub entry point with a clear slate, summary header, and prioritized navigation into sports surfaces.
2. Shared daily board contract: keep the intelligence board as the canonical recommendation payload and make the home hub consume the same normalized lane and card data.
3. Live-game surface: expose live games, live props, and in-progress updates with lane-specific presentation and game-state awareness.
4. Pregame surface: expose pregame props, daily games, and pregame recommendations with explicit market, line, and edge metadata.
5. Live-lens interval and projection consistency: keep NBA and prop live lenses on the same live interval lines, odds, and projection inputs that power the board contract.
6. Ask parity: make Ask the Syndicate read the same board inputs so explanations, summaries, and surfaced recommendations stay aligned.
7. Outcome and ledger tracking: record recommended, placed, settled, and open items so the platform can learn from results and show portfolio exposure.
8. UI polish and accessibility: finish responsive hierarchy, card density, contrast, and action affordances so the home and intelligence pages feel like one premium command center.
9. Deeper learning and policy control: keep adaptive strategy, policy selection, and richer explainers attached to the same board contract.

Phase 7 progress snapshot:

- completed: home command center shell
- completed: shared daily board contract
- completed: live-game and pregame lane separation
- completed: live-lens interval/projection consistency
- completed: Ask parity with the shared board inputs
- completed: outcome and ledger tracking
- in progress: worker-backed betting board snapshot artifact
- remaining: UI polish, accessibility refinement, deeper learning, and policy control

Concrete file targets:

- [syndicate/blueprints/intelligence.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/blueprints/intelligence.py)
- [syndicate/templates/intelligence.html](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/templates/intelligence.html)
- [syndicate/blueprints/home.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/blueprints/home.py)
- [syndicate/templates/home.html](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/templates/home.html)
- [syndicate/blueprints/ask_the_syndicate.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/blueprints/ask_the_syndicate.py)
- [syndicate/templates/syndicate.html](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/templates/syndicate.html)
- [syndicate/features/nba/live_lens.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/nba/live_lens.py)
- [syndicate/features/wnba/live_lens.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/wnba/live_lens.py)
- [syndicate/features/nba/cards.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/nba/cards.py)
- [syndicate/features/intelligence.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/intelligence.py)
- [syndicate/features/intelligence_reasoning.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/intelligence_reasoning.py)
- [syndicate/features/intelligence_evaluation.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/intelligence_evaluation.py)
- [syndicate/features/intelligence_analysis_views.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/intelligence_analysis_views.py)
- [reports/intelligence/evaluation_ledger.jsonl](c:/Users/tempadmin/OneDrive/Coding/Syndicate/reports/intelligence/evaluation_ledger.jsonl)
- [tests/test_intelligence.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_intelligence.py)
- [tests/test_intelligence_state.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_intelligence_state.py)
- [tests/test_ask_the_syndicate.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_ask_the_syndicate.py)

## Phase 9: Add identity, permissions, and user-scoped state

Goal: introduce unique logins and permissions so portfolio tracking, saved views, and recommendation history can become user-specific without rewriting the live-board contract.

Scope:

- authentication and session management for named users
- role-based permissions for admin, operator, analyst, and read-only access
- per-user portfolios, bet ledgers, watchlists, and saved recommendation history
- auditability for user actions such as add bet, remove bet, pin, hide, or archive
- safe multi-user state boundaries for recommendations and portfolio exposure

Deliverables:

- a user identity model that can scope portfolios and recommendation history
- permission checks for protected operations and admin tooling
- a path to migrate the current operator-managed ledger into user-scoped storage later
- audit events for portfolio and recommendation changes

Exit criteria:

- a named user can sign in and see only their own scoped portfolio and saved state
- admin and operator capabilities are explicitly separated from normal user access
- the existing live-board and Ask contracts continue to work while user scoping is added
- the system can grow from a single operator ledger to per-user ledgers without changing the recommendation model

Workstreams:

1. Authentication, session persistence, and account bootstrap.
2. Role-based permissions and access gates.
3. User-scoped portfolios, watchlists, and saved recommendations.
4. Audit trail and admin oversight for user actions.
5. Migration path from operator-managed state to user-owned state.

Concrete file targets:

- [syndicate/blueprints/auth.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/blueprints/auth.py)
- [syndicate/templates/auth_login.html](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/templates/auth_login.html)
- [syndicate/templates/auth_permissions.html](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/templates/auth_permissions.html)
- [syndicate/features/auth/session.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/auth/session.py)
- [syndicate/features/auth/permissions.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/auth/permissions.py)
- [syndicate/features/auth/audit.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/auth/audit.py)
- [syndicate/features/auth/user_state.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/syndicate/features/auth/user_state.py)
- [tests/test_auth.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_auth.py)
- [tests/test_permissions.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_permissions.py)
- [tests/test_user_state.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_user_state.py)

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
10. Add Phase 9 only after the live-board and Ask surfaces are coherent enough to justify user-scoped state.

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