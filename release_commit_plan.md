# Release Commit Plan

## Status Snapshot

The working tree is mixed. Release-ready source changes are present alongside unrelated tracked edits, generated artifacts, tracking data, and scratch outputs. The plan below separates the deployable release slice from everything that should stay out of the push.

## Classification Legend

- `COMMIT` means stage it in one of the release commits below.
- `REVIEW` means the file is code, but it is outside the release slice and should not be staged until separately approved.
- `EXCLUDE` means generated, temporary, cache, tracking, or scratch output that should not be staged.

## Exact Commit Plan

### Commit 1: NCAAF SmartSim + Runtime Integration

Purpose: restore the NCAAF source-contract and CFBD builder surface so NCAAF builder scripts and regression tests load cleanly.

Exact files:

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

Deployment risk: low to moderate. The change is contract-heavy, but the focused NCAAF/NFL suite already passed.

Rollback risk: moderate. The CFBD builders and source helpers are coupled, so rollback should keep the commit as a single unit.

### Commit 2: NCAAF Card Parity + UI

Purpose: keep the dedicated NCAAF card experience aligned with the shared card dispatcher and dedicated NCAAF renderer.

Exact files:

- `syndicate/features/ncaaf/cards.py`
- `syndicate/templates/shared/_game_card.html`
- `syndicate/templates/shared/_game_card_generic.html`
- `syndicate/templates/shared/_game_card_ncaaf.html`
- `tests/test_ncaaf_cards_local.py`

Deployment risk: low. This is UI/rendering work with dedicated regression coverage.

Rollback risk: low. The surface is isolated to card rendering and local NCAAF card tests.

### Commit 3: NFL / Football Foundation

Purpose: land the new football ingestion, simulation, validation, and support layer that backs NFL and football foundation work.

Exact files:

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

Deployment risk: moderate. This is the largest code slice, but it is covered by the focused football regression suite.

Rollback risk: moderate to high. The commit is broad, so rollback should be atomic and not split across multiple commits.

### Commit 4: Documentation, Audit, and Release Notes, Optional

Purpose: preserve the audit trail and remediation notes without mixing them into the functional commits.

Exact files:

- `docs/fix_notes_log.md`
- `final_git_push_audit.md`
- `release_blocker_remediation_report.md`
- `release_commit_plan.md`
- `release_readiness_audit.md`

Deployment risk: none. Documentation only.

Rollback risk: low. Documentation can be reverted independently of the release code.

## Changed File Classification

### COMMIT

- `syndicate/features/ncaaf/cards.py`
- `syndicate/features/ncaaf/cfbd.py`
- `syndicate/features/ncaaf/sources.py`
- `syndicate/templates/shared/_game_card.html`
- `syndicate/templates/shared/_game_card_generic.html`
- `syndicate/templates/shared/_game_card_ncaaf.html`
- `syndicate/features/football/**`
- `scripts/build_ncaaf_*.py`
- `tests/test_depth_chart_snapshot_builder.py`
- `tests/test_football_sim_engine.py`
- `tests/test_ncaaf_cards_local.py`
- `tests/test_ncaaf_cfbd_player_identity.py`
- `tests/test_ncaaf_coach_continuity_builder.py`
- `tests/test_ncaaf_returning_production_builder.py`
- `tests/test_ncaaf_team_registry_builder.py`
- `tests/test_ncaaf_transfer_portal_builder.py`
- `tests/test_roster_snapshot_builder.py`
- `docs/fix_notes_log.md`
- `final_git_push_audit.md`
- `release_blocker_remediation_report.md`
- `release_commit_plan.md`
- `release_readiness_audit.md`

### REVIEW

- `syndicate/features/intelligence.py`
- `syndicate/features/intelligence/api/response_builder.py`
- `syndicate/features/intelligence_board.py`
- `syndicate/features/shared/intelligence_evaluation.py`
- `syndicate/features/shared/live_refresh_loop.py`
- `syndicate/features/shared/recommendation_engine.py`
- `syndicate/features/wnba/cards.py`
- `tests/test_live_refresh_loop.py`

Rationale: these files are real code, but they are outside the current NCAAF/NFL release slice and should not be bundled into the same push without separate signoff.

### EXCLUDE

- `data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_07_13.jsonl`
- `data/mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_07_13.json`
- `reports/live_refresh_loop/latest_live_refresh_tick.json`
- `data/nfl_source/tracking/**`
- `tmp/**`
- `football_*.md`
- `ncaaf_*.md`
- `football_2026_*.md`
- `nfl_season_validation*.json`
- `run_feature_lift_analysis.py`
- `syndicate/features/football/__pycache__/**`
- `syndicate/features/football/features/__pycache__/**`
- `syndicate/features/football/ingestion/__pycache__/**`
- `syndicate/features/football/sim_engine/__pycache__/**`

Rationale: these are generated artifacts, scratch outputs, cache/tracking files, or rerun products that do not belong in the release history.

## What to Stage Now

Stage the files in Commit 1, Commit 2, Commit 3, and optionally Commit 4 if you want the documentation trail in the same push.

Do not stage anything in `REVIEW` or `EXCLUDE`.

## Recommended Commit Order

1. Commit 1: NCAAF SmartSim + Runtime Integration
2. Commit 2: NCAAF Card Parity + UI
3. Commit 3: NFL / Football Foundation
4. Commit 4: Documentation, Audit, and Release Notes, optional

## Push and Deploy Decision

- After selective staging, is the repo safe to push? Yes, if you stage only the Commit 1 to Commit 3 release files, and optionally Commit 4 docs, while leaving `REVIEW` and `EXCLUDE` untouched.
- After selective staging, is the repo safe to deploy? Yes, based on the passed focused validation suite and the remediation report, assuming the release commits are kept to the plan above.

## Final Recommendation

Use selective staging only. Do not batch the unrelated intelligence/WNBA/live-lens changes into the release. Commit the release slices in order, then push the resulting clean history.