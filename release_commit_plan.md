# Release Commit Plan - Second Pass

## Current State

The working tree now contains three kinds of changes:

- release source and test files that are safe to stage
- unrelated tracked edits that should stay out of this release
- generated artifacts, cache data, and deleted report files that should not be staged

## Recommended Commit Order

1. Commit 1: NCAAF SmartSim + Runtime Integration
2. Commit 2: NCAAF Card Parity + UI
3. Commit 3: NFL / Football Foundation
4. Commit 4: Documentation, optional

## COMMIT

Stage these files for the release commits.

### Commit 1: NCAAF SmartSim + Runtime Integration

- `syndicate/features/ncaaf/cfbd.py`
- `syndicate/features/ncaaf/sources.py`
- `scripts/build_ncaaf_coach_continuity_snapshot.py`
- `scripts/build_ncaaf_player_identity_snapshot.py`
- `scripts/build_ncaaf_returning_production_snapshot.py`
- `scripts/build_ncaaf_roster_snapshot.py`
- `scripts/build_ncaaf_team_registry_snapshot.py`
- `scripts/build_ncaaf_transfer_portal_snapshot.py`
- `tests/test_ncaaf_cfbd_player_identity.py`
- `tests/test_ncaaf_coach_continuity_builder.py`
- `tests/test_ncaaf_returning_production_builder.py`
- `tests/test_ncaaf_team_registry_builder.py`
- `tests/test_ncaaf_transfer_portal_builder.py`

### Commit 2: NCAAF Card Parity + UI

- `syndicate/features/ncaaf/cards.py`
- `syndicate/templates/shared/_game_card.html`
- `syndicate/templates/shared/_game_card_generic.html`
- `syndicate/templates/shared/_game_card_ncaaf.html`
- `tests/test_ncaaf_cards_local.py`

### Commit 3: NFL / Football Foundation

- `syndicate/features/football/__init__.py`
- `syndicate/features/football/adapters.py`
- `syndicate/features/football/artifacts.py`
- `syndicate/features/football/contracts.py`
- `syndicate/features/football/evaluation.py`
- `syndicate/features/football/feature_lift_analysis.py`
- `syndicate/features/football/player_prop_lift_analysis.py`
- `syndicate/features/football/season_validation.py`
- `syndicate/features/football/features/__init__.py`
- `syndicate/features/football/features/advanced_metrics.py`
- `syndicate/features/football/features/loaders.py`
- `syndicate/features/football/features/market_features.py`
- `syndicate/features/football/features/matchups.py`
- `syndicate/features/football/features/pace_features.py`
- `syndicate/features/football/features/player_usage.py`
- `syndicate/features/football/features/team_identity.py`
- `syndicate/features/football/features/team_metrics.py`
- `syndicate/features/football/ingestion/__init__.py`
- `syndicate/features/football/ingestion/depth_chart_snapshot_builder.py`
- `syndicate/features/football/ingestion/ftn_charting_ingestion.py`
- `syndicate/features/football/ingestion/nflverse_ingestion.py`
- `syndicate/features/football/ingestion/rbsdm_ingestion.py`
- `syndicate/features/football/ingestion/roster_snapshot_builder.py`
- `syndicate/features/football/ingestion/source_fetchers.py`
- `syndicate/features/football/sim_engine/__init__.py`
- `syndicate/features/football/sim_engine/football_core.py`
- `syndicate/features/football/sim_engine/ncaaf_adapter.py`
- `syndicate/features/football/sim_engine/nfl_adapter.py`
- `tests/test_depth_chart_snapshot_builder.py`
- `tests/test_football_sim_engine.py`
- `tests/test_roster_snapshot_builder.py`

### Commit 4: Documentation, optional

- `docs/fix_notes_log.md`

## REVIEW

These files are real code changes, but they are outside the NCAAF/NFL release slice and should not be staged in this pass.

- `syndicate/features/intelligence.py`
- `syndicate/features/intelligence/api/response_builder.py`
- `syndicate/features/intelligence_board.py`
- `syndicate/features/shared/intelligence_evaluation.py`
- `syndicate/features/shared/live_refresh_loop.py`
- `syndicate/features/shared/recommendation_engine.py`
- `syndicate/features/wnba/cards.py`
- `syndicate/templates/shared/_game_card_generic.html` is staged above for the NCAAF UI slice only if the diff is part of that release path; otherwise leave it in review until the card scope is confirmed.
- `reports/manifests/wnba.json`
- `tests/test_live_refresh_loop.py`
- `data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_07_13.jsonl`
- `data/mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_07_13.json`

## EXCLUDE

These are generated artifacts, cache/tracking files, scratch outputs, or deleted report files that should not be staged.

- `data/nfl_source/tracking/odds_history.json`
- `data/nfl_source/tracking/odds_nfl_team_odds_history_2026-06-12.csv`
- `data/nfl_source/tracking/odds_nfl_team_odds_history_2026-07-09.csv`
- `data/nfl_source/tracking/odds_nfl_team_odds_movement_signals_2026-06-12.csv`
- `data/nfl_source/tracking/odds_nfl_team_odds_movement_signals_2026-07-09.csv`
- `data/nfl_source/tracking/odds_nfl_team_odds_opening_2026-06-12.csv`
- `data/nfl_source/tracking/odds_nfl_team_odds_opening_2026-07-09.csv`
- `reports/live_refresh_loop/last_lineup_check.json`
- `reports/live_refresh_loop/latest_live_refresh_tick.json`
- `tmp/**` and the `nfl_season_validation*.json` files that were created there
- All root-level deleted report files currently shown as `D` in git status:
  - `ncaaf_card_experience_design.md`
  - `ncaaf_card_parity_final_report.md`
  - `ncaaf_card_parity_implementation_report.md`
  - `ncaaf_cfbd_integration_report.md`
  - `ncaaf_coach_continuity_generation_report.md`
  - `ncaaf_coaching_continuity_onboarding_report.md`
  - `ncaaf_coaching_source_validation_report.md`
  - `ncaaf_onboarding_validation_report.md`
  - `ncaaf_phase_2_1_smart_sim_integration_design.md`
  - `ncaaf_phase_2_2_runtime_integration_report.md`
  - `ncaaf_phase_2_3_runtime_integration_report.md`
  - `ncaaf_phase_2_4_candidate_generation_report.md`
  - `ncaaf_phase_2_5_feature_aware_evaluation_report.md`
  - `ncaaf_phase_2_6_coverage_aware_ranking_report.md`
  - `ncaaf_phase_3_smartsim_validation_report.md`
  - `ncaaf_phase_4_board_validation_report.md`
  - `ncaaf_player_identity_source_report.md`
  - `ncaaf_returning_production_generation_report.md`
  - `ncaaf_returning_production_onboarding_report.md`
  - `ncaaf_roster_onboarding_report.md`
  - `ncaaf_schedule_onboarding_report.md`
  - `ncaaf_team_metadata_onboarding_report.md`
  - `ncaaf_team_registry_generation_report.md`
  - `ncaaf_transfer_portal_generation_report.md`
  - `ncaaf_transfer_portal_onboarding_report.md`
  - `ncaaf_week0_market_readiness_report.md`
  - `ncaaf_week1_join_gap_report.md`
  - `ncaaf_week1_market_readiness_report.md`
  - `ncaaf_week1_publication_readiness_report.md`
  - `release_blocker_remediation_report.md`
  - `release_readiness_audit.md`
  - `release_commit_plan.md`
- `__pycache__/**` under the football tree or any other tree

## What Should Be Staged Now

Stage only the COMMIT files above. Leave REVIEW and EXCLUDE untouched.

## What Must Not Be Staged

- all generated tracking, cache, and scratch files
- all deleted NCAAF/NFL report files listed under EXCLUDE
- all unrelated intelligence, WNBA, and live-refresh edits listed under REVIEW

## Push and Deploy Answer

- After selective staging, is the repo safe to push? Yes, if you stage only the COMMIT files and leave REVIEW and EXCLUDE out.
- After selective staging, is the repo safe to deploy? Yes, for the release slice covered by the focused validation suite.