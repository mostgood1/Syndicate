# Board / intelligence engine audit — PASS 3: the mechanical remainder

Completes §1's import graph, §3's returns-None sweep, §6's artifact map and §8's boundary census. Read-only. Written 2026-08-14.

Scope: 390 python modules under `syndicate/**` + `pipeline/**`.

## §1 (completed) — import graph

### Hub modules — imported by more than 10 others (24)

A hub is usually a concept that wants splitting.

| importers | module |
|---:|---|
| 56 | `syndicate.features.shared.timezone` |
| 39 | `syndicate.features.shared.refresh_state_store` |
| 31 | `syndicate.features.shared.source_roots` |
| 29 | `syndicate.features.shared.rank_board` |
| 28 | `syndicate.features.shared.game_board_contract` |
| 23 | `syndicate.features.mlb.sources` |
| 22 | `syndicate.features.nfl.sources` |
| 19 | `syndicate.features.wnba.sources` |
| 19 | `syndicate.features.shared.discrete_nav` |
| 18 | `syndicate.features.nba.sources` |
| 17 | `syndicate.features.ncaaf.sources` |
| 16 | `syndicate.features.soccer.sim_engine.soccersim.contracts` |
| 15 | `syndicate.features.soccer.sources` |
| 15 | `syndicate.features.shared.memory_observability` |
| 14 | `syndicate.features.shared.request_path_guard` |
| 14 | `syndicate.features.nhl.sources` |
| 14 | `syndicate.features.football.sim_engine.smartsim2.contracts` |
| 13 | `syndicate.features.shared.live_lens_local` |
| 13 | `syndicate.features.mlb.ladders_common` |
| 12 | `syndicate.features.shared.odds_control_plane` |
| 12 | `syndicate.features.shared.intelligence_evaluation` |
| 11 | `syndicate.features.shared.odds_book_quotes` |
| 11 | `syndicate.features.ncaaf.cards` |
| 11 | `syndicate.features.mlb.cards` |

### Import cycles (24)

- `pipeline.intelligence_entrypoint -> pipeline.intelligence_pipeline -> pipeline.intelligence_state -> pipeline.intelligence_entrypoint`
- `pipeline.intelligence_pipeline -> pipeline.intelligence_state -> pipeline.intelligence_pipeline`
- `pipeline.intelligence_state -> pipeline.layer2_shortlist -> syndicate.features.shared.board_enrichment -> syndicate.features.shared.game_chip_scoreboard -> syndicate.blueprints.home -> syndicate.blueprints.intelligence -> pipeline.intelligence_state`
- `syndicate.blueprints.home -> syndicate.blueprints.intelligence -> syndicate.features.intelligence -> syndicate.blueprints.home`
- `syndicate.features.intelligence -> syndicate.features.intelligence.api.response_builder -> syndicate.features.intelligence`
- `syndicate.blueprints.home -> syndicate.blueprints.intelligence -> syndicate.features.intelligence -> syndicate.features.intelligence.api.response_builder -> syndicate.features.intelligence.scoring.edge -> syndicate.blueprints.home`
- `syndicate.features.mlb.cards -> syndicate.features.mlb.live_lens -> syndicate.features.mlb.cards`
- `syndicate.features.mlb.cards -> syndicate.features.mlb.live_lens -> syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.mlb.cards`
- `syndicate.features.nba.cards -> syndicate.features.nba.live_lens -> syndicate.features.nba.cards`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.nba.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.ncaab.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.ncaaf.cards -> syndicate.features.ncaaf.smartsim2_trial_monitoring -> syndicate.features.ncaaf.sources -> syndicate.features.ncaaf.cards`
- `syndicate.features.soccer.sources -> syndicate.features.shared.team_aliases -> syndicate.features.soccer.sources`
- `syndicate.features.shared.odds_book_quotes -> syndicate.features.shared.artifact_publisher -> syndicate.features.shared.odds_book_quotes`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.ncaaf.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.nfl.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.nhl.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.game_board_contract -> syndicate.features.shared.simulation_adapter -> syndicate.features.wnba.cards -> syndicate.features.shared.game_board_contract`
- `syndicate.features.shared.board_enrichment -> syndicate.features.shared.game_chip_scoreboard -> syndicate.blueprints.home -> syndicate.blueprints.intelligence -> syndicate.features.shared.board_enrichment`
- `syndicate.features.shared.board_enrichment -> syndicate.features.shared.game_chip_scoreboard -> syndicate.blueprints.home -> syndicate.blueprints.intelligence -> syndicate.features.shared.book_grid_artifact -> syndicate.features.shared.board_enrichment`
- `syndicate.features.shared.game_chip_scoreboard -> syndicate.blueprints.home -> syndicate.blueprints.intelligence -> syndicate.features.shared.game_chip_scoreboard`
- `syndicate.features.football.sim_engine.smartsim2.play_state -> syndicate.features.football.sim_engine.smartsim2.situation_model -> syndicate.features.football.sim_engine.smartsim2.play_state`
- `syndicate.features.soccer.sim_engine.soccersim.event_state -> syndicate.features.soccer.sim_engine.soccersim.situation_model -> syndicate.features.soccer.sim_engine.soccersim.event_state`

### Modules reachable from NO route and NO loop entrypoint (164)

Static reachability only. Thread targets, registries and dynamic imports are NOT followed — `learnings.md` records that a trace omitting those is not evidence. Treat as a shortlist.

- `pipeline.__init__`
- `pipeline.formatter`
- `pipeline.performance_aggregator`
- `syndicate.__init__`
- `syndicate.features.football.__init__`
- `syndicate.features.football.adapters`
- `syndicate.features.football.artifacts`
- `syndicate.features.football.contracts`
- `syndicate.features.football.evaluation`
- `syndicate.features.football.feature_lift_analysis`
- `syndicate.features.football.features.__init__`
- `syndicate.features.football.features.advanced_metrics`
- `syndicate.features.football.features.loaders`
- `syndicate.features.football.features.market_features`
- `syndicate.features.football.features.matchups`
- `syndicate.features.football.features.pace_features`
- `syndicate.features.football.features.player_usage`
- `syndicate.features.football.features.team_identity`
- `syndicate.features.football.features.team_metrics`
- `syndicate.features.football.ingestion.__init__`
- `syndicate.features.football.ingestion.depth_chart_snapshot_builder`
- `syndicate.features.football.ingestion.ftn_charting_ingestion`
- `syndicate.features.football.ingestion.nflverse_ingestion`
- `syndicate.features.football.ingestion.rbsdm_ingestion`
- `syndicate.features.football.ingestion.roster_snapshot_builder`
- `syndicate.features.football.ingestion.source_fetchers`
- `syndicate.features.football.player_prop_lift_analysis`
- `syndicate.features.football.season_validation`
- `syndicate.features.football.sim_engine.__init__`
- `syndicate.features.football.sim_engine.football_core`
- `syndicate.features.football.sim_engine.ncaaf_adapter`
- `syndicate.features.football.sim_engine.nfl_adapter`
- `syndicate.features.football.sim_engine.smartsim2.__init__`
- `syndicate.features.football.sim_engine.smartsim2.calibration.__init__`
- `syndicate.features.football.sim_engine.smartsim2.calibration.baseline_audit`
- `syndicate.features.football.sim_engine.smartsim2.calibration.benchmark_contracts`
- `syndicate.features.football.sim_engine.smartsim2.calibration.calibration_report_generator`
- `syndicate.features.football.sim_engine.smartsim2.calibration.evaluation_metrics`
- `syndicate.features.football.sim_engine.smartsim2.calibration.simulator_evaluator`
- `syndicate.features.football.sim_engine.smartsim2.calibration.truth_audit`
- `syndicate.features.football.sim_engine.smartsim2.calibration_profile`
- `syndicate.features.football.sim_engine.smartsim2.contracts`
- `syndicate.features.football.sim_engine.smartsim2.drive_priors`
- `syndicate.features.football.sim_engine.smartsim2.drive_simulator`
- `syndicate.features.football.sim_engine.smartsim2.game_simulator`
- `syndicate.features.football.sim_engine.smartsim2.historical_truth.__init__`
- `syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_builder`
- `syndicate.features.football.sim_engine.smartsim2.historical_truth.historical_snapshot_contract`
- `syndicate.features.football.sim_engine.smartsim2.historical_truth.nfl_historical_loader`
- `syndicate.features.football.sim_engine.smartsim2.ncaaf_calibration_profile`
- `syndicate.features.football.sim_engine.smartsim2.play_outcomes`
- `syndicate.features.football.sim_engine.smartsim2.play_simulator`
- `syndicate.features.football.sim_engine.smartsim2.play_state`
- `syndicate.features.football.sim_engine.smartsim2.possession_outcomes`
- `syndicate.features.football.sim_engine.smartsim2.possession_state`
- `syndicate.features.football.sim_engine.smartsim2.runtime`
- `syndicate.features.football.sim_engine.smartsim2.situation_model`
- `syndicate.features.intelligence_audit`
- `syndicate.features.live_ui_audit`
- `syndicate.features.mlb.box_score_stats`
- `syndicate.features.ncaab.mirror_export`
- `syndicate.features.ncaaf.cfbd`
- `syndicate.features.ncaaf.player_stats`
- `syndicate.features.ncaaf.smartsim2_betting_performance`
- `syndicate.features.ncaaf.smartsim2_performance_tracking`
- `syndicate.features.nfl.smartsim2_betting_performance`
- `syndicate.features.nfl.smartsim2_performance_tracking`
- `syndicate.features.nhl.sim_engine.__init__`
- `syndicate.features.nhl.sim_engine.hockeysim.__init__`
- `syndicate.features.nhl.sim_engine.hockeysim.adapters`
- ...and 94 more

## §3 (completed) — functions whose EVERY return is None/[]/{} (38)

AST-derived: >=2 return statements, all of them empty. A function here either is dead, or exists only for side effects (in which case the return is a lie).

| file:line | function | returns | body stmts |
|---|---|---:|---:|
| `syndicate/features/ncaaf/cards.py:596` | `_attach_smartsim2_shadow_fields` | 2 | 27 |
| `syndicate/features/mlb/cards.py:6227` | `_mlb_hydrate_market_board_prop_movement` | 2 | 25 |
| `syndicate/blueprints/intelligence.py:1125` | `_visit` | 6 | 16 |
| `syndicate/features/shared/live_refresh_loop.py:2310` | `_finalize_orphaned_sim_run` | 4 | 16 |
| `syndicate/features/intelligence.py:6864` | `_mlb_hydrate_live_prop_projection` | 3 | 15 |
| `pipeline/intelligence_state.py:6233` | `_load_persisted_state_locked` | 2 | 14 |
| `syndicate/features/mlb/cards.py:6155` | `_mlb_hydrate_market_board_line_movement` | 2 | 13 |
| `syndicate/features/shared/basketball_market_board.py:509` | `_basketball_hydrate_market_board_line_movement` | 2 | 13 |
| `syndicate/blueprints/ask_the_syndicate.py:388` | `_apply_briefing_to_response` | 2 | 12 |
| `syndicate/features/mlb/cards.py:6058` | `_mlb_hydrate_market_board_live_projection` | 3 | 12 |
| `syndicate/features/shared/intelligence_evaluation.py:559` | `_update_evaluation_ledger_record` | 4 | 12 |
| `syndicate/features/shared/intelligence_evaluation.py:443` | `_append_evaluation_ledger_record` | 2 | 11 |
| `syndicate/features/shared/soccer_projections.py:272` | `_price_against_market` | 4 | 11 |
| `syndicate/blueprints/intelligence.py:1088` | `_refresh_live_columns_from_artifact` | 8 | 10 |
| `syndicate/features/soccer/market_board.py:476` | `_soccer_hydrate_market_board_line_movement` | 2 | 10 |
| `syndicate/features/shared/odds_lifecycle.py:476` | `_compact_odds_lifecycle_file` | 4 | 9 |
| `syndicate/features/nhl/sim_engine/hockeysim/engine.py:832` | `_emit_assists` | 2 | 8 |
| `pipeline/intelligence_state.py:1842` | `_normalize_card_edge_units` | 4 | 7 |
| `syndicate/features/intelligence.py:6678` | `_apply_candidate_state_guard` | 4 | 7 |
| `syndicate/features/shared/basketball_market_board.py:559` | `_basketball_hydrate_market_board_prop_movement` | 2 | 7 |
| `syndicate/features/shared/basketball_props_smart_sim.py:4969` | `_load_pairs` | 4 | 7 |
| `syndicate/features/shared/book_margin_model.py:87` | `observe` | 3 | 7 |
| `pipeline/intelligence_state.py:1767` | `_mark_layer2_decided` | 3 | 6 |
| `syndicate/app.py:321` | `_start_background_loops` | 4 | 6 |
| `syndicate/features/mlb/cards.py:1262` | `_attach_cards_pregame_starter_ladder_badges` | 2 | 6 |
| `syndicate/features/mlb/live_lens.py:168` | `_refresh_current_date_live_statuses` | 3 | 6 |
| `syndicate/app.py:86` | `_run_bootstrap` | 3 | 5 |
| `syndicate/features/shared/live_refresh_loop.py:4050` | `_report_odds_sweep_outcomes` | 3 | 5 |
| `pipeline/intelligence_state.py:1011` | `_collect` | 2 | 4 |
| `syndicate/app.py:65` | `_bootstrap_render_data` | 7 | 4 |
| `syndicate/features/shared/basketball_props_smart_sim.py:4049` | `_add` | 2 | 4 |
| `syndicate/features/shared/refresh_state_store.py:307` | `_record_refresh_status_history` | 2 | 4 |
| `syndicate/features/shared/source_roots.py:25` | `_append_repo_fallback` | 2 | 4 |
| `syndicate/features/shared/quote_enrichment.py:368` | `_emit_enrich_profile` | 2 | 3 |
| `syndicate/features/shared/refresh_state_store.py:241` | `record_known_refresh_lane` | 2 | 3 |
| `syndicate/features/shared/request_path_guard.py:30` | `refuse_if_compute_in_request_path` | 2 | 3 |
| `syndicate/blueprints/wnba.py:168` | `_release_wnba_api_throttle` | 2 | 2 |
| `syndicate/features/shared/live_refresh_loop.py:1054` | `_record_mlb_tip_off_simmed` | 2 | 1 |

## §6 (partial->fuller) — artifact accessor map

| accessor | writers | readers |
|---|---:|---:|
| `_write_json` | 26 | 0 |
| `publish_hot_artifact` | 7 | 0 |
| `read_book_quotes` | 0 | 5 |
| `read_intelligence_board_state` | 0 | 5 |
| `read_json_file` | 0 | 114 |
| `read_latest_intelligence_board_state` | 0 | 3 |
| `read_latest_intelligence_state` | 0 | 12 |
| `read_layer2_shortlist` | 0 | 4 |
| `read_quote_last_seen` | 0 | 6 |
| `write_intelligence_board_state` | 2 | 0 |
| `write_json_file` | 74 | 0 |
| `write_latest_intelligence_state` | 3 | 0 |
| `write_layer2_shortlist` | 3 | 0 |

Site lists for the single-writer/single-reader cases (the ones where a disagreement cannot be averaged away):

- `read_book_quotes` — writers: none · readers: ['pipeline/layer2_shortlist.py:92', 'syndicate/blueprints/intelligence.py:2346', 'syndicate/blueprints/intelligence.py:2878', 'syndicate/features/shared/odds_book_quotes.py:776', 'syndicate/features/shared/odds_book_quotes.py:1283']
- `read_intelligence_board_state` — writers: none · readers: ['pipeline/intelligence_state.py:1974', 'pipeline/intelligence_state.py:2108', 'pipeline/intelligence_state.py:2115', 'syndicate/blueprints/intelligence.py:666', 'syndicate/blueprints/intelligence.py:2681']
- `read_latest_intelligence_board_state` — writers: none · readers: ['pipeline/intelligence_state.py:1909', 'pipeline/intelligence_state.py:2104', 'syndicate/blueprints/intelligence.py:666']
- `read_layer2_shortlist` — writers: none · readers: ['pipeline/intelligence_state.py:1582', 'pipeline/intelligence_state.py:1953', 'syndicate/blueprints/ask_the_syndicate_data.py:3353', 'syndicate/blueprints/intelligence.py:2673']
- `read_quote_last_seen` — writers: none · readers: ['pipeline/layer2_shortlist.py:142', 'syndicate/blueprints/intelligence.py:2358', 'syndicate/blueprints/intelligence.py:2887', 'syndicate/features/shared/book_grid_artifact.py:174', 'syndicate/features/shared/odds_book_quotes.py:303', 'syndicate/features/shared/odds_book_quotes.py:307']
- `write_intelligence_board_state` — writers: ['pipeline/intelligence_state.py:1961', 'pipeline/intelligence_state.py:5956'] · readers: none
- `write_latest_intelligence_state` — writers: ['pipeline/intelligence_state.py:2940', 'pipeline/intelligence_state.py:2943', 'pipeline/intelligence_state.py:5404'] · readers: none
- `write_layer2_shortlist` — writers: ['pipeline/intelligence_state.py:1923', 'pipeline/intelligence_state.py:3533', 'pipeline/intelligence_state.py:4879'] · readers: none

## §8 (census) — pregame/live boundary surface

91 modules contain a pregame/live discriminator (`is_live`, `effective_phase`, `pregame`, `live_lens`, `_live_tier`).

| mentions | module |
|---:|---|
| 141 | `syndicate/features/intelligence.py` |
| 101 | `syndicate/blueprints/home.py` |
| 39 | `syndicate/features/shared/live_refresh_loop.py` |
| 29 | `syndicate/features/shared/odds_refresh_tracking.py` |
| 29 | `syndicate/features/wnba/cards.py` |
| 28 | `syndicate/features/mlb/live_lens.py` |
| 22 | `syndicate/blueprints/intelligence.py` |
| 22 | `syndicate/features/shared/recommendation_engine.py` |
| 19 | `pipeline/intelligence_state.py` |
| 18 | `syndicate/features/shared/artifact_publisher.py` |
| 18 | `syndicate/features/shared/opportunity_gate.py` |
| 15 | `syndicate/features/shared/live_lens_loop.py` |
| 13 | `syndicate/features/mlb/cards.py` |
| 13 | `syndicate/features/shared/layer1_board.py` |
| 12 | `syndicate/features/shared/layer2_board.py` |
| 11 | `syndicate/features/shared/intelligence_contracts.py` |
| 11 | `syndicate/features/shared/live_projection_join.py` |
| 10 | `syndicate/features/intelligence_board.py` |
| 10 | `syndicate/features/shared/game_chip_scoreboard.py` |
| 9 | `syndicate/features/nfl/live_game_state.py` |
| 7 | `syndicate/features/nfl/live_lens.py` |
| 7 | `syndicate/features/shared/odds_lifecycle.py` |
| 7 | `syndicate/features/soccer/features/__init__.py` |
| 6 | `syndicate/blueprints/nba.py` |
| 6 | `syndicate/features/intelligence/api/response_builder.py` |

**Modules whose NAME contains `live` (16)** — candidate forks rather than conditionals:

- `syndicate/features/mlb/live_lens.py`
- `syndicate/features/nba/live_lens.py`
- `syndicate/features/ncaab/live_lens.py`
- `syndicate/features/ncaaf/live_lens.py`
- `syndicate/features/nfl/live_game_state.py`
- `syndicate/features/nfl/live_lens.py`
- `syndicate/features/nhl/live_lens.py`
- `syndicate/features/shared/basketball_live_artifacts.py`
- `syndicate/features/shared/live_edge_policy.py`
- `syndicate/features/shared/live_lens_contract.py`
- `syndicate/features/shared/live_lens_loop.py`
- `syndicate/features/shared/live_projection_join.py`
- `syndicate/features/shared/live_refresh_loop.py`
- `syndicate/features/soccer/ingestion/espn_live_state.py`
- `syndicate/features/soccer/live_lens.py`
- `syndicate/features/wnba/live_lens.py`
