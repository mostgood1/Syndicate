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

## Phase mapping

This backlog tracks the official implementation plan in execution order.

| Plan phase | Backlog meaning | Current status | Primary validation |
| --- | --- | --- | --- |
| Phase 0: Freeze the current contract surface | Lock the current sports inventory, shared contract shapes, and compatibility shims before deeper changes. | Completed | Focused contract and regression coverage on current surfaces. |
| Phase 1: Make the artifact layer universally reliable | Normalize source_artifacts and mirror roots so every sport resolves the same published data contract. | Completed | Root-resolution and refresh-wrapper regression coverage. |
| Phase 2: Make simulation the compute core | Introduce run planning, run-state, checkpoints, and reproducible sim provenance. | Completed | First-run, incremental-run, no-op-run, and partial-failure tests. |
| Phase 3: Build a central odds management system | Own odds ingestion, refresh, hydration, replay, line movement, and snapshot precedence across sports. | Completed | Odds-control-plane, freshness, and reconciliation coverage. |
| Phase 4: Build the intelligence engine into a real decision layer | Expand query routing, evidence-backed recommendations, and cross-sport reasoning. | Completed | Response-shape and evidence-contract coverage. |
| Phase 5: Close the evaluation loop | Track accuracy, calibration, CLV, ROI, and drift. | Completed | Outcome persistence and scoring regression coverage. |
| Phase 6: Harden ops and runtime boundaries | Keep long-running work out of the web request path and make refresh state durable. | Completed | Worker/web separation and restart-safe state coverage. |
| Phase 7: Expand toward a true world-class product | Add deeper sport-native experiences without fragmenting the shared platform. | Active | Contract-preserving add-on coverage. |
| Phase 8: Optimize execution and platform efficiency | Reduce time-to-answer, time-to-refresh, and throughput bottlenecks without weakening correctness. | Planned | Profiling-driven latency and throughput coverage. |

## Current next slice

Phase 6 is complete. The next executable slice is now the remaining Phase 7 UI polish, accessibility, deeper learning, and policy-control work.

Phase 7 is active now. The home command center, shared board contract, live and pregame lanes, Ask parity, outcome / ledger tracking, and live-lens consistency slices are complete. The remaining work is UI polish, accessibility, and deeper recommendation learning.

The restored live-board and Ask workstreams remain part of Phase 7:

- the `/intelligence` live board stays the canonical decision surface for the shared contract
- Ask the Syndicate keeps using the same board inputs and evidence bundle for explanations
- game and prop live lenses stay aligned with live interval lines, live odds, and in-game projections

First workstream:

- [x] introduce a worker-owned refresh entrypoint
- [x] keep web refresh handlers read-only over refresh state
- [x] route state writes through the worker path only
- [x] emit a structured refresh-worker status artifact
- [x] emit terminal refresh-worker status updates after the queued job finishes
- [x] emit a structured queued-job status artifact
- [x] surface worker and queued-job status artifacts in the ops refresh status payload

Concrete target:

- move long-running work out of the web request path
- keep refresh-state storage durable and recoverable
- preserve stable ops endpoints while the backend evolves
- keep execution-time visibility and runtime budgets explicit for long-running jobs

Phase 6 sub-slices:

- [x] worker-owned refresh execution and hosted-safe separation
- [x] durable checkpoints, replay context, and restart-safe run-state updates
- [x] stable status and manifest artifacts for refresh observability
- [x] runtime-budget and trace visibility for long-running jobs

Current implementation note:

- comparison prompts now route through the shared intelligence router, carry comparison-mode payload shaping, and preserve the matchup-compatible public response contract
- comparison responses now carry explicit comparison evidence, routing context, and multi-sport awareness for downstream consumers
- multi-sport non-comparison prompts now carry a cross-sport reasoning bundle so evidence-backed reasoning is not limited to compare-style requests
- evaluation responses now surface a durable history summary by sport and market family so quality signals are available through the public contract
- the daily update script now carries run-state, checkpoint, replay-context, and trace scaffolding with regression coverage
- replayed daily-update runs now surface a resumed run-state when a checkpoint is applied, instead of only carrying the replay context as metadata
- the daily-update ops surface now exposes stable checkpoint, run-state, and trace artifacts alongside runtime-budget details for long-running refresh visibility
- the odds control plane now publishes a central snapshot that the intelligence pipeline can surface as evidence
- the current daily-update docs and tests now reflect the manifest, checkpoint, replay, and trace scaffolding rather than only the preexisting run manifest path
- the legacy ops full-refresh route now launches and records refresh work without a web-process monitor thread, so the request path no longer waits on long-running completion
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



Additional world-class odds concerns to include in the plan:

- a single odds contract for pregame, live, and line-movement artifacts
- source-of-truth precedence for mirrored, hosted, and local odds bundles
- freshness and latency expectations for odds hydration and live snapshot capture
- reconciliation rules when refresh output, snapshot history, and UI payloads disagree
- auditability for who produced an odds artifact, when it was refreshed, and what changed

Planned validation for this slice:

- worker/web separation and restart-safe state coverage
- run-state, checkpoint, replay-context, and trace scaffold coverage
- response-shape and evidence-contract coverage that remains green after the new snapshot and routing updates

Validation already added:

- targeted pytest coverage for the odds control plane snapshot and history precedence
- targeted pytest coverage for intelligence routing, comparison handling, and evidence bundles
- targeted pytest coverage for the daily-update run-state, checkpoint, replay, and trace scaffolding
- the daily-update scaffold coverage is pinned by [tests/test_unified_daily_update_run_state_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_run_state_scaffold.py), [tests/test_unified_daily_update_replay_context_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_replay_context_scaffold.py), [tests/test_unified_daily_update_replay_apply_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_replay_apply_scaffold.py), [tests/test_unified_daily_update_sim_trace_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_sim_trace_scaffold.py), [tests/test_unified_daily_update_status_artifact_scaffold.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_status_artifact_scaffold.py), and [tests/test_unified_daily_update_sim_noop_detection.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_unified_daily_update_sim_noop_detection.py)
- refresh-worker observability is now pinned by [tests/test_refresh_worker.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_refresh_worker.py), including the idle, running, and terminal status artifact states
- queued-job observability is now pinned by [tests/test_refresh_odds_job.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_refresh_odds_job.py), including the terminal wrapper status artifact
- ops refresh status coverage is now pinned by [tests/test_ops.py](c:/Users/tempadmin/OneDrive/Coding/Syndicate/tests/test_ops.py), including the surfaced worker and queued-job artifact payloads

## Phase 0 kickoff

- [x] Inventory the current contract surfaces for MLB, NBA, WNBA, NHL, NFL, NCAAF, and NCAAB.
- [x] Confirm the unified standardization rule is explicit in the plan and used as the default decision rule.
- [x] Keep the current regression guardrails green before any phase-1 artifact changes.
- [x] Preserve every compatibility shim until the replacement path is proven in tests.

## Phase 1 next slice

- [x] Normalize the remaining per-sport artifact-root assumptions into the shared source_artifacts contract.
- [x] Verify the daily refresh wrapper stays consistent across all sports.
- [x] Keep requested-date semantics and no-silent-fallback behavior stable.

## Phase 2 next slice

- [x] Map simulation inputs and outputs to a single reproducible run contract.
- [x] Add/confirm run-state and checkpoint persistence.
- [x] Keep sim-mode changes additive until provenance is stable.

## Phase 4 next slice

- [x] Expand query routing and evidence-backed recommendations beyond comparison.
- [x] Build cross-sport reasoning on the unified contract model.
- [x] Keep response and evidence contracts stable for the UI and downstream consumers.

## Validation note

Targeted regressions were added and exercised for the new odds control plane, intelligence routing/evidence path, Ask the Syndicate comparison surface, and daily-update run-state scaffolding.

Known validation detail:

- the focused pytest slice was run for the new docs-backed work items, and no new failures were reported in that run

## Phase 5 next slice

- [x] Track accuracy, calibration, CLV, ROI, and drift.
- [x] Build durable evaluation history per sport and market family.
- [x] Surface quality signals for the intelligence layer.

## Phase 6 next slice

- [x] Separate worker-owned refresh execution from web request handling.
- [x] Keep hosted-safe read/write boundaries explicit for refresh state.
- [x] Move long-running work out of the web request path.
- [x] Keep refresh-state storage durable and recoverable.
- [x] Persist durable run checkpoints.
- [x] Load replay context from the latest checkpoint.
- [x] Restore run-state safely after restart.
- [x] Publish latest checkpoint and run-state artifacts alongside the manifest.
- [x] Preserve stable ops endpoints while the backend evolves.
- [x] Keep execution-time visibility and runtime budgets explicit for long-running jobs.

## Phase 7 next slice

1. Home command center shell.
- [x] Make `/` the daily entry point for all sports.
- [x] Give the page a clear command-center header and a fast route into today’s highest-value surfaces.
- [x] Preserve a simple, premium landing experience before adding deeper controls.

2. Shared daily board contract.
- [x] Build the `/intelligence` live board decision surface from the shared board contract.
- [x] Normalize the same lane and card data for the home hub and the intelligence surface.
- [x] Keep recommendation cards explicit about sport, team, player, market, line, movement, and simulated edge.

3. Live-game surface.
- [x] Surface live games and live props as the in-progress decision lane.
- [x] Link live recommendations to current game state so the board can show live performance context.
- [x] Surface pregame props and daily games as the pregame decision lane.
- [x] Preserve the live-versus-pregame split so the UI never blurs a live edge with a pregame edge.
- [x] Make Ask the Syndicate reuse the same live board decision inputs for explanations.
- [x] Keep the Ask surface visually and semantically coherent with the home hub and intelligence board.
- [x] Add recommendation history that records what was recommended, what was placed, what won or lost, and what the policy should learn.
- [x] Add bet and portfolio tracking for actual wagers, open exposure, and manual add/remove actions.
- [x] Make game and prop live lenses use live interval lines, live odds, and in-game projections consistently instead of falling back to off-board intervals.
- [ ] Make the live board feel like a world-class product with strong hierarchy, readable cards, responsive layouts, and accessible contrast.
- [ ] Make the home page feel like a world-class daily command center with a clear slate, strong hierarchy, and fast access to the day’s highest-value sports surfaces.

4. Recommendation learning.
- [ ] Add deeper sport-native explainers and richer live decisioning as part of Phase 7 deeper learning.
- [ ] Support policy selection and adaptive recommendation strategy.
- [ ] Preserve the baseline contract while extending platform coverage.
- [ ] Preserve time-to-answer and latency budgets while adding richer experiences.

5. Identity and scoped state.
- [ ] Add audit events for portfolio and recommendation changes.
- [ ] Keep the existing operator-managed ledger usable until user-scoped state is ready.

## Phase 8 next slice


Do not mark a phase complete until the current product surface, the new contract surface, and the focused regression tests all agree.