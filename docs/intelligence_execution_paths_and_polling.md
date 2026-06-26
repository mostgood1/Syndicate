# Intelligence Execution Paths and Polling

This note documents the current execution paths that reach the three intelligence entrypoints and the polling loops that can drive them.

Render deployment note:
- the public web service is stateless and reads the repo-local `data/` and `reports/` trees for read-only response shaping
- the `orchestrator-worker` owns the mounted disk and background refresh/write paths
- the Render Key Value backend remains the shared refresh-state store for both surfaces

## Public entrypoints

- [pipeline/intelligence_pipeline.py](../pipeline/intelligence_pipeline.py): `run_intelligence_pipeline()`
- [pipeline/intelligence_entrypoint.py](../pipeline/intelligence_entrypoint.py): `run_routed_intelligence_pipeline()`
- [syndicate/features/intelligence.py](../syndicate/features/intelligence.py): `run_intelligence_query()`

## Execution paths to `run_intelligence_query()`

### 1. Direct intelligence query API

Trigger surface:
- [syndicate/blueprints/intelligence.py](../syndicate/blueprints/intelligence.py) `POST /api/intelligence/query`

Path:
- `intelligence_query_api()` calls `run_intelligence_query()` directly for non-default questions.
- The same route may also call `queue_intelligence_state_refresh()` when the default cached board is empty or a refresh is requested.

Execution mode:
- Synchronous in the request thread.

How often it can run:
- Every request.
- The browser page can hit the route repeatedly through client polling.

Concurrency:
- Can run concurrently across requests, tabs, and worker processes.

### 2. Ask the Syndicate artifact-backed response

Trigger surface:
- [syndicate/blueprints/ask_the_syndicate.py](../syndicate/blueprints/ask_the_syndicate.py)

Path:
- `ask_the_syndicate_query_api()` -> `_build_fast_state_result()` -> `read_latest_intelligence_state()` -> `build_syndicate_query_response()`.

Execution mode:
- Synchronous in the request thread.

How often it can run:
- Every Ask request.

Concurrency:
- Can run concurrently across requests.

Note:
- Ask no longer calls `run_intelligence_query()`, `run_routed_intelligence_pipeline()`, or `run_intelligence_pipeline()`.
- Missing snapshots now return a safe fallback Ask response instead of triggering compute.

### 3. Intelligence state worker

Trigger surface:
- [pipeline/intelligence_state.py](../pipeline/intelligence_state.py)

Path:
- `IntelligenceStateService._background_loop()` -> `_compute_response()` -> `run_routed_intelligence_pipeline()` -> `run_intelligence_pipeline()` -> `run_intelligence_query()`.

Execution mode:
- Background thread or background process loop.

How often it can run:
- Whenever payloads are queued.
- Also when watched payloads are considered stale on the worker interval.

Concurrency:
- One loop per service instance is serialized by the local lock.
- Multiple processes can still run the same work concurrently.

## Execution paths to `run_routed_intelligence_pipeline()`

### 1. Ask the Syndicate fallback pipeline

Trigger surface:
- [syndicate/blueprints/ask_the_syndicate.py](../syndicate/blueprints/ask_the_syndicate.py)

Path:
- Fallback handlers such as `handle_bet_analysis()`, `handle_matchup_analysis()`, and `handle_market_summary()` now format the latest snapshot through `_build_route_payload()`.
- `_build_route_payload()` reads `read_latest_intelligence_state()` and does not call `run_routed_intelligence_pipeline()`.

Execution mode:
- Synchronous in the request thread.

How often it can run:
- Every Ask request that does not resolve through artifact-backed or cached-state handling.

Concurrency:
- Can run concurrently across requests.

### 2. Intelligence state background worker

Trigger surface:
- [pipeline/intelligence_state.py](../pipeline/intelligence_state.py)

Path:
- `_background_loop()` calls `_compute_response()` which routes through `run_routed_intelligence_pipeline()`.

Execution mode:
- Background thread or background process loop.

How often it can run:
- On queued payloads and stale watched payloads.

Concurrency:
- Serialized inside one service instance, but can still run concurrently across processes.

## Execution paths to `run_intelligence_pipeline()`

### 1. Ask the Syndicate fallback pipeline

Trigger surface:
- [syndicate/blueprints/ask_the_syndicate.py](../syndicate/blueprints/ask_the_syndicate.py)

Path:
- Ask fallback handlers call `_build_route_payload()`.
- `_build_route_payload()` calls `run_routed_intelligence_pipeline()`.
- `run_routed_intelligence_pipeline()` calls `run_intelligence_pipeline()`.

Execution mode:
- Synchronous in the request thread.

How often it can run:
- Every routed Ask fallback request.

Concurrency:
- Can run concurrently across requests.

### 2. Intelligence state worker

Trigger surface:
- [pipeline/intelligence_state.py](../pipeline/intelligence_state.py)

Path:
- `_background_loop()` -> `_compute_response()` -> `run_routed_intelligence_pipeline()` -> `run_intelligence_pipeline()`.

Execution mode:
- Background loop.

How often it can run:
- On queued payloads and stale watched payloads.

Concurrency:
- Serialized inside a service instance, but concurrent across processes is still possible.

### 3. Test-only direct calls

Trigger surface:
- [tests/test_intelligence_pipeline.py](../tests/test_intelligence_pipeline.py)

Path:
- Unit tests import and call `run_intelligence_pipeline()` directly.

Execution mode:
- Synchronous test execution only.

How often it can run:
- Test suite only.

Concurrency:
- Whatever the test runner allows.

## Polling loops

### Odds

- [syndicate/app.py](../syndicate/app.py) can start `start_live_refresh_background_loop()` when `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP` is enabled.
- [scripts/run_refresh_worker.py](../scripts/run_refresh_worker.py) runs a forever polling loop for refresh work and can also hydrate odds-related artifacts through the refresh pipeline.
- The intelligence pipeline also reads odds history snapshots during candidate scoring, but that is request-time data access rather than a separate polling loop.

### PBP and game state

- [syndicate/features/mlb/live_lens.py](../syndicate/features/mlb/live_lens.py) contains the live-state refresh logic used by MLB live-lens paths.
- [syndicate/app.py](../syndicate/app.py) can start the live odds refresh background loop, which is the main long-running app-side refresh mechanism touching live game-state style data.
- Browser pages such as MLB cards and intelligence can also poll their APIs from the client side, but the primary always-on loop in this area is the refresh worker infrastructure.

### Intelligence refresh

- [syndicate/templates/intelligence.html](../syndicate/templates/intelligence.html) polls the intelligence query API on an interval and also refreshes on focus and visibility changes.
- [pipeline/intelligence_state.py](../pipeline/intelligence_state.py) runs `IntelligenceStateService._background_loop()` which now routes work through `run_routed_intelligence_pipeline()` and persists with `write_latest_intelligence_state()`.
- [scripts/run_refresh_worker.py](../scripts/run_refresh_worker.py) runs a separate forever refresh loop.
- [syndicate/app.py](../syndicate/app.py) can optionally start `start_intelligence_state_background_loop(app)`.

## Overlapping or duplicate paths

### Duplicate request surfaces for the same intelligence work

- `run_intelligence_query()` is reached both directly from [syndicate/blueprints/intelligence.py](../syndicate/blueprints/intelligence.py) and indirectly through Ask and the background state worker.
- `run_routed_intelligence_pipeline()` and `run_intelligence_pipeline()` are layered entrypoints for the same logical request pipeline.

### Duplicate refresh owners

- `intelligence.html` client polling.
- `IntelligenceStateService._background_loop()`.
- `scripts/run_refresh_worker.py`.
- Optional app startup background loop in [syndicate/app.py](../syndicate/app.py).

### Duplicate state hydration surfaces

- Ask can read cached state, call `run_intelligence_query()` directly, or fall back to routed pipeline execution.
- The intelligence query API can also choose between cached response, queued refresh, and direct execution based on question and cache state.

## What should be centralized

1. Centralize intelligence refresh ownership in [pipeline/intelligence_state.py](../pipeline/intelligence_state.py).
2. Keep `run_routed_intelligence_pipeline()` as the public routed wrapper and treat `run_intelligence_pipeline()` as the internal pipeline implementation.
3. Prefer one canonical refresh worker for odds and game-state hydration instead of overlapping app-level and external forever loops.
4. Keep Ask routing, cached-state response selection, and board rendering separate from the pipeline execution layer.

## Practical summary

- Synchronous request paths should stay synchronous only when the user needs an immediate answer.
- Background refresh should own cache warming, stale-state reconciliation, and queued recomputation.
- The current design works, but it is still split across too many refresh owners.