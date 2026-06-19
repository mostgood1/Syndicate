# Intelligence, Ask, and Projection Architecture

This note captures how the Syndicate intelligence surfaces are built today so future work can reuse the same call paths without re-tracing the codebase.

## /intelligence route

Primary route entry:
- [syndicate/blueprints/intelligence.py](../syndicate/blueprints/intelligence.py)

Page route:
- `GET /intelligence` -> `intelligence_home()`
- `intelligence_home()` builds the page payload with `_intelligence_page_payload()`
- It then tries `_cached_intelligence_response_with_source()`
- That reads `read_latest_intelligence_state_response()` from `pipeline/intelligence_state.py`
- If the cached response is empty, it queues work with `queue_intelligence_state_refresh()`
- Finally it renders `intelligence.html`

Query route:
- `POST /api/intelligence/query` -> `intelligence_query_api()`
- For the default question it prefers cached state and may queue a refresh
- For non-default questions it calls `run_intelligence_query()`
- The returned payload is wrapped with `build_intelligence_board_contract()` before being returned

### What builds the board

The board is assembled from the recommendation pipeline, not from the route itself:
- `run_intelligence_query()` in [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- `collect_all_recommendations()` in [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)
- `collect_candidates()` -> `score_candidate()` -> `_score_candidates()` -> `rank_candidates()`
- `build_response()` returns the base response payload
- `build_intelligence_board_contract()` turns recommendations into board cards and lane counts

### Data sources used

The board path reads from:
- `current_app.config["SYNDICATE_SPORTS"]` via `build_intelligence_overview()`
- sport artifact mirrors through `_build_sport_overview()`
- odds history payloads through `_odds_history_payloads_by_sport()`
- tracked repository files via `_tracked_repo_files()`
- MLB live-state context via `_apply_live_state_context_to_candidates()`
- evaluation and readiness via `build_intelligence_evaluation_bundle()` and `build_intelligence_status()`
- cached intelligence state via `read_latest_intelligence_state_response()` and `get_intelligence_state_response()`

### Where projections and odds are combined

The main merge points are:
- `_candidate_model_probability()` estimates model probability from simulation/score data
- `_candidate_betting_edge_profile()` combines model probability with implied probability from odds, then derives edge and expected value
- `_candidate_rationale()` turns that combined candidate state into human-readable explanation text
- `_build_supporting_evidence()` surfaces projection, line, live projection, confidence, price edge, and implied probability together
- `_build_structured_answer()` assembles the final narrative around the recommendation set

## Ask the Syndicate

Primary route entry:
- [syndicate/blueprints/ask_the_syndicate.py](../syndicate/blueprints/ask_the_syndicate.py)

Entry point:
- `POST /api/syndicate/query` -> `ask_the_syndicate_query_api()`

Call flow:
- `ask_the_syndicate_query_api()` validates input and routes the question with `_QUERY_ROUTER.route()`
- `_smart_route_payload()` adds inferred sport/context hints
- `_build_fast_state_result()` reads `read_latest_intelligence_state()` and builds the Ask response from the latest snapshot
- If no snapshot is available, the route returns a safe fallback Ask response with a clear missing-snapshot message
- The route no longer calls `run_intelligence_query()`, `run_routed_intelligence_pipeline()`, or `run_intelligence_pipeline()`

### Does Ask trigger computation?

No.

Ask is now a pure consumer of persisted intelligence snapshots:
- it reads the latest snapshot state
- it formats the response from that snapshot
- it returns a safe fallback message when the snapshot is missing

So Ask is now a response surface only.

## Projection logic

Primary implementation surface:
- [syndicate/features/intelligence.py](../syndicate/features/intelligence.py)

Where it runs:
- `run_intelligence_query()`
- `collect_all_recommendations()`
- `collect_candidates()`
- `score_candidate()` and `_score_candidates()`
- `pipeline/intelligence_state.py` inside the background state worker

Projection is not a separate route-only feature. It is part of candidate assembly and scoring.

The important call chain is:
- `build_intelligence_overview()`
- `collect_all_recommendations()`
- `collect_candidates()`
- `score_candidate()`
- `_apply_live_state_context_to_candidates()`
- `_apply_advanced_context_to_candidates()`
- `_candidate_model_probability()`
- `_candidate_betting_edge_profile()`
- `rank_candidates()`

That means projection and odds are fused during recommendation scoring, then the resulting recommendations are rendered into the board contract.

## Polling and loops

Client-side polling:
- [syndicate/templates/intelligence.html](../syndicate/templates/intelligence.html)
- `window.setInterval(..., 30000)` polls the intelligence query API every 30 seconds
- Focus and visibility handlers also re-run `loadIntelligence()`

Background worker loop:
- [pipeline/intelligence_state.py](../pipeline/intelligence_state.py)
- `IntelligenceStateService._background_loop()` waits for queued payloads, runs the routed pipeline, and writes the latest snapshot state
- `self._interval_seconds` defaults to 30 seconds and is bounded to at least 10 seconds

Render worker loop:
- [scripts/run_refresh_worker.py](../scripts/run_refresh_worker.py)
- Default poll interval is 30 seconds through `SYNDICATE_REFRESH_WORKER_POLL_SECONDS`
- The worker loops forever unless `--run-once` is used

App startup loop:
- [syndicate/app.py](../syndicate/app.py)
- `start_intelligence_state_background_loop(app)` is only started when `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is enabled

### Can multiple instances run?

Yes, across processes.
- `IntelligenceStateService.start()` prevents multiple threads in the same process
- It does not prevent multiple worker processes from running the same loop
- Browser polling can also run in multiple tabs

## Safe-to-background vs must-stay-sync

Safe to background:
- `queue_intelligence_state_refresh()`
- `IntelligenceStateService._background_loop()`
- the 30-second polling in `intelligence.html`
- `run_refresh_worker.py`
- warm-refresh side effects from Ask

Must stay synchronous:
- `/intelligence` page rendering
- `/api/intelligence/query` response generation
- `/api/syndicate/query` response generation
- `build_intelligence_board_contract()`
- `build_response()`
- `build_syndicate_query_response()`
- direct `run_intelligence_query()` execution when a live answer is expected

## Notes for later work

- The board contract is a presentation wrapper around scored recommendations.
- The recommendation pipeline is the authoritative place where projections, odds, and live-state context get merged.
- The background worker is a cache-population mechanism, not the sole source of truth.
