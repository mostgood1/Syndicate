# Intelligence / Betting Board Assessment

This is the current assessment of the Syndicate intelligence board, also treated in the codebase as the betting board. It explains what the system does now, what it is intended to do, and what still has to be fixed before it behaves like a world-class board.

## Short version

The board is already a real cross-sport decision surface, not just a card list. It has a live board contract, a query engine, sport-specific analysis views, Ask-facing response shaping, a cached-state read path, and a background worker path. The main gaps are freshness ownership, orchestration clarity, cross-sport consistency, and reducing the number of places that can produce slightly different board shapes.

## Recent changes

The most recent hosted-runtime work changed how the board is deployed and populated on Render without changing the visible board contract.

- The default board query now preserves explicit recommendation mode for generic prompts like "top edges today" so the board path does not collapse into explanation mode.
- The intelligence state worker now computes fresh state before persisting it instead of only re-reading cached snapshots.
- The Render web service now reads the checked-in repo `data/` and `reports/` trees, while the `orchestrator-worker` keeps the persistent disk for refresh and write paths.
- The Render contract and regression checks were updated so the repo documents the stateless web service / disk-backed worker split explicitly.

These changes were made to keep the betting board functional while avoiding the Render runtime split-brain that appeared when the web service and worker both tried to share the same disk-backed deployment shape.

## What is wired now

### Public surfaces

- [`/intelligence`](../syndicate/blueprints/intelligence.py) renders the intelligence page and prefers cached state first.
- [`POST /api/intelligence/query`](../syndicate/blueprints/intelligence.py) returns the intelligence response envelope and attaches the board contract.
- [`GET /api/intelligence/status`](../syndicate/blueprints/intelligence.py) reads the cached intelligence state for status checks.
- [`POST /api/syndicate/query`](../syndicate/blueprints/ask_the_syndicate_adapter.py) turns intelligence output into Ask-facing response schemas.

### Query and routing layer

- [`syndicate/features/intelligence.py`](../syndicate/features/intelligence.py) is the main query orchestrator.
- [`syndicate/features/intelligence_router.py`](../syndicate/features/intelligence_router.py) maps the question to a route intent or focus.
- [`syndicate/features/intelligence_analysis_views.py`](../syndicate/features/intelligence_analysis_views.py) selects the sport-specific analysis view.
- [`syndicate/features/intelligence_board.py`](../syndicate/features/intelligence_board.py) builds the canonical board contract.
- [`syndicate/blueprints/ask_the_syndicate_adapter.py`](../syndicate/blueprints/ask_the_syndicate_adapter.py) reshapes intelligence results into Ask schemas such as bet analysis, matchup analysis, and market summary.

### Data and evidence sources

The board is not built from a single hardcoded list. It pulls from:

- sport artifact mirrors and source-overview rails
- odds history and live-refresh context
- tracked repository files
- live-state and advanced-input context for select sports
- evaluation and readiness bundles
- cached intelligence state and worker-persisted snapshots

### Current behavior

The current flow is roughly:

```mermaid
flowchart TD
  A[User question or page load] --> B[blueprints/intelligence.py]
  B --> C[run_intelligence_query()]
  C --> D[intelligence_router.py]
  D --> E[intelligence_analysis_views.py]
  C --> F[intelligence_board.py]
  C --> G[ask_the_syndicate_adapter.py]
  H[Cached state / worker snapshot] --> I[status + page hydration]
```

The important point is that the board already has separation of concerns: routing, scoring, board shaping, and Ask response formatting are distinct layers.

### Sport coverage already wired

The system already has real sport-aware branches for:

- MLB home runs and MLB props
- NBA matchup and prop views
- WNBA matchup and prop views
- NCAAB matchup and prop views
- NFL market views
- NHL prop views
- a generic `market_board` fallback for mixed or uncategorized asks

That means the board is already multi-sport and not tied to a single league model.

## What it is supposed to do

The intended board is a state-aware, evidence-backed, cross-sport decision surface that can:

1. answer a question from cached state first when possible
2. refresh from a worker-owned background path when state is stale or missing
3. show the best candidates for the requested sport, market, or matchup
4. explain why a play is on the board using source-backed evidence
5. keep live and pregame lanes consistent and clearly labeled
6. expose one stable board contract that downstream UI and Ask surfaces can trust
7. preserve replayability and auditability so the board can be inspected after the fact

In other words, the board should behave like a control plane for recommendations, not just a rendering wrapper around whatever the query engine happened to return.

## What is still missing

### 1. Freshness ownership is not fully centralized

The biggest architectural gap is that freshness still comes from several places at once:

- page polling
- request-time cache reads
- background state worker refreshes
- direct query execution for non-default questions

This works, but it is not yet a single authoritative refresh contract.

### 2. The board is still split across multiple response surfaces

The same underlying intelligence result can be shaped by:

- the page route
- the JSON query route
- the Ask adapter
- the worker snapshot

That increases the chance of shape drift if one layer changes and another does not.

### 3. Cross-sport consistency is uneven

Some sports have richer native context than others, and some rely on fallback behavior more heavily. The practical result is that the board is strongest where the sport already has a mature artifact contract, and weaker where the sport still depends on indirect or partial inputs.

### 4. The board contract is good, but not yet enough on its own

[`intelligence_board_v1`](../syndicate/features/intelligence_board.py) gives the board a real schema, lane counts, active lanes, and cards. But a world-class board needs more than a card schema:

- stable provenance
- freshness labels
- replay-safe state
- clear source priority
- explicit coverage of empty, stale, and partial states

### 5. Request handling still has overlap with compute

The board path still has a mix of synchronous request logic and background worker logic. That is acceptable for now, but it is not the final shape if the goal is one clear compute owner and one clear read surface.

### 6. Some fallbacks are still broad

There is still fallback logic for mixed asks and generic market boards. That is useful, but it needs tighter boundaries so a fallback does not quietly become the default path for a sport or market that should have a dedicated contract.

## Issues that should be addressed

### Priority 1: make state ownership explicit

The board should have one clear refresh owner and one clear cached read owner. Today the system is close, but the responsibilities are still split between the page, the route, the worker, and the Ask adapter.

### Priority 2: reduce shape drift

The board contract should be normalized so the same recommendation produces the same visible shape no matter which surface reads it.

### Priority 3: tighten sport parity

Every current sport should converge on the same expectations for:

- lane labeling
- evidence depth
- freshness reporting
- empty-state behavior
- board contract completeness

### Priority 4: improve stale-state handling

If cached state is stale, the board should say so clearly and should prefer the worker-owned refresh path rather than silently presenting old output as if it were current.

### Priority 5: make the fallback policy narrower

Generic market-board fallback is useful, but it should not hide missing sport-specific work. The board should fail visibly enough that missing coverage is obvious during validation.

## What world class looks like

A world-class betting board here should:

- be cached-state first and worker refreshed
- have one canonical contract for all read surfaces
- preserve sport-specific depth without fragmenting the UI contract
- show freshness, provenance, and run-state in a readable way
- make empty, stale, partial, and healthy states obvious
- keep analysis, board shaping, and Ask formatting separated
- be auditable back to the source artifacts and the run that produced it
- support replay and recovery without guessing which surface was authoritative

## Recommended next steps

1. Define one canonical board state contract that all surfaces read from.
2. Narrow the board to a single refresh owner and a single worker-backed freshness path.
3. Add explicit stale-state and partial-state presentation rules.
4. Tighten sport parity checks so every sport is validated against the same board expectations.
5. Keep the generic fallback, but make it visibly secondary to sport-owned analysis views.

## Implementation plan

This is the practical sequence to move the board toward a world-class contract without breaking the current surfaces.

### Phase 1: Canonical state contract

Goal: make every surface read the same board state shape.

What to change:

- standardize the board payload returned by the page route, JSON query route, Ask adapter, and worker snapshot
- make freshness, provenance, and run-state fields first-class in the shared board response
- define one canonical empty-state and one canonical stale-state representation

Validation:

- board contract regression for empty, live, pregame, stale, and mixed states
- response-shape regression for `/intelligence`, `/api/intelligence/query`, and Ask output
- worker snapshot round-trip regression against the latest cached state

### Phase 2: Single refresh owner

Goal: make refresh ownership explicit and reduce overlapping compute paths.

What to change:

- keep cached-state reads synchronous
- route refresh work through the background worker as the default freshness owner
- avoid direct recomputation in request paths unless a live answer is explicitly required
- make the board report when it is using cached state versus worker-refreshed state

Validation:

- worker-backed refresh coverage
- request-path cache-only coverage
- concurrency regression to prevent duplicate recomputation across requests and workers

### Phase 3: Stale-state handling

Goal: make freshness visible instead of implicit.

What to change:

- add explicit stale, partial, and healthy labels to the board presentation contract
- make the UI and Ask surfaces show when the board is behind the latest refresh
- ensure the board does not silently present stale output as current

Validation:

- stale-state label regression
- partial-state label regression
- freshness label and provenance coverage in the rendered response

### Phase 4: Sport parity hardening

Goal: make every sport meet the same minimum board expectations.

What to change:

- align lane naming and card metadata across MLB, NBA, WNBA, NCAAB, NFL, and NHL
- verify each sport has a comparable evidence depth standard
- make generic fallback behavior visibly secondary to sport-owned analysis views
- tighten any sport that still depends on indirect or partial artifact reads

Validation:

- one regression per sport for the primary board lane
- one regression per sport for analysis-view routing
- one regression for fallback precedence when sport-owned data is available

### Phase 5: Operational auditability

Goal: make the board easy to inspect after the fact.

What to change:

- include source artifacts, timestamps, and run identifiers in the board trace path
- keep the board state replay-safe so old snapshots can be audited reliably
- make it obvious which run produced the current board state

Validation:

- trace artifact regression
- replay-safe snapshot regression
- board provenance regression through the latest cached state

## Related docs

- [Intelligence ask / projection architecture](intelligence_ask_projection_architecture.md)
- [Intelligence call graph reference](intelligence_call_graph_reference.md)
- [Intelligence execution paths and polling](intelligence_execution_paths_and_polling.md)
- [Daily update control plane](daily_update_control_plane.md)
