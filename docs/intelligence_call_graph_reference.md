# Intelligence Call Graph Reference

This reference is a compact call graph for the core intelligence surfaces.

## /intelligence

```mermaid
flowchart TD
  A[GET /intelligence] --> B[intelligence_home()]
  B --> C[_intelligence_page_payload()]
  B --> D[_cached_intelligence_response_with_source()]
  D --> E[read_latest_intelligence_state_response()]
  B --> F[queue_intelligence_state_refresh()]
  B --> G[render_template(intelligence.html)]

  H[POST /api/intelligence/query] --> I[intelligence_query_api()]
  I --> J[run_intelligence_query()]
  J --> K[build_intelligence_overview()]
  K --> L[collect_all_recommendations()]
  L --> M[collect_candidates()]
  M --> N[_score_candidates()]
  N --> O[rank_candidates()]
  O --> P[build_response()]
  P --> Q[build_intelligence_board_contract()]
  P --> R[build_intelligence_evaluation_bundle()]
```

## Ask the Syndicate

```mermaid
flowchart TD
  A[POST /api/syndicate/query] --> B[ask_the_syndicate_query_api()]
  B --> C[_smart_route_payload()]
  C --> D[_QUERY_ROUTER.route()]
  B --> E[_build_artifact_response()]
  E --> F[run_intelligence_query()]
  B --> G[_build_fast_state_result()]
  G --> H[read_latest_intelligence_state_response()]
  H --> I[build_intelligence_board_contract()]
  B --> J[handle_bet_analysis() / handle_matchup_analysis() / handle_market_summary()]
  J --> K[_build_route_payload()]
  K --> L[run_routed_intelligence_pipeline()]
  L --> M[route_intelligence_request()]
  M --> N[run_intelligence_pipeline()]
```

## Projection and odds merge

```mermaid
flowchart TD
  A[build_intelligence_overview()] --> B[collect_all_recommendations()]
  B --> C[collect_candidates()]
  C --> D[score_candidate()]
  D --> E[_apply_live_state_context_to_candidates()]
  D --> F[_apply_advanced_context_to_candidates()]
  D --> G[_candidate_model_probability()]
  D --> H[_candidate_betting_edge_profile()]
  H --> I[odds -> implied_probability]
  G --> J[model_probability]
  I --> K[edge / expected_value]
  J --> K
  K --> L[rank_candidates()]
  L --> M[build_response()]
  M --> N[build_intelligence_board_contract()]
```

## Background and polling

```mermaid
flowchart TD
  A[intelligence.html] --> B[setInterval(loadIntelligence, 30000)]
  C[syndicate/app.py] --> D[start_intelligence_state_background_loop()]
  E[pipeline/intelligence_state.py] --> F[_background_loop() -> run_routed_intelligence_pipeline() -> write_latest_intelligence_state()]
  G[scripts/run_refresh_worker.py] --> H[while True polling loop]
```
