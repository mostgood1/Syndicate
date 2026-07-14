# Release Readiness Audit

## Git Inventory

Current working tree is not clean. The audit surfaced three distinct buckets:

1. NCAAF and NFL code additions in `syndicate/features/football/**`, `syndicate/features/ncaaf/cfbd.py`, `syndicate/templates/shared/_game_card_ncaaf.html`, `syndicate/templates/shared/_game_card.html`, and the related `tests/test_ncaaf_*` plus `tests/test_football_sim_engine.py` coverage.
2. Unrelated modified files already dirty in the workspace, including `syndicate/features/intelligence.py`, `syndicate/features/intelligence_board.py`, `syndicate/features/shared/intelligence_evaluation.py`, `syndicate/features/shared/recommendation_engine.py`, `syndicate/features/wnba/cards.py`, `syndicate/templates/shared/_game_card_generic.html`, `data/mlb_source/source_artifacts/data/live_lens/*`, and `reports/live_refresh_loop/latest_live_refresh_tick.json`.
3. Large generated or local-only artifacts, especially `tmp/**`, `data/nfl_source/tracking/**`, and the many generated `football_*`, `ncaaf_*`, and `tmp/*` report files in the repo root.

### Changed File Inventory

Tracked modifications currently visible in `git status`:

- NCAAF: `syndicate/features/ncaaf/cards.py`, `syndicate/features/ncaaf/cfbd.py`, `syndicate/templates/shared/_game_card.html`, `syndicate/templates/shared/_game_card_generic.html`
- Shared / Intelligence: `syndicate/features/intelligence.py`, `syndicate/features/intelligence_board.py`, `syndicate/features/shared/intelligence_evaluation.py`, `syndicate/features/shared/recommendation_engine.py`
- WNBA: `syndicate/features/wnba/cards.py`
- Docs / Runtime Artifacts: `docs/fix_notes_log.md`, `data/mlb_source/source_artifacts/data/live_lens/live_lens_2026_07_13.jsonl`, `data/mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_07_13.json`, `reports/live_refresh_loop/latest_live_refresh_tick.json`

Untracked additions currently visible in `git status`:

- Football platform: `syndicate/features/football/**`
- NCAAF builders and onboarding scripts: `scripts/build_ncaaf_*.py`
- NCAAF card artifacts and reports: `ncaaf_card_experience_design.md`, `ncaaf_card_parity_final_report.md`, `ncaaf_week1_board_quality_review.md`, `ncaaf_week1_production_board.md`, and the other `ncaaf_*` markdown reports
- NFL football reports and validation artifacts: `football_*` markdown and `tmp/football_*` files
- Local caches and source tracking: `data/nfl_source/tracking/ftn_charting/`, `data/nfl_source/tracking/nflverse/`
- Tests: `tests/test_depth_chart_snapshot_builder.py`, `tests/test_football_sim_engine.py`, `tests/test_ncaaf_*`, `tests/test_roster_snapshot_builder.py`

### Untracked File Inventory

Do not commit the obvious local/generated buckets:

- `tmp/**`
- `data/nfl_source/tracking/**`
- `data/mlb_source/source_artifacts/data/live_lens/**`
- `reports/live_refresh_loop/latest_live_refresh_tick.json`
- One-off generated analysis or rerun files such as the `football_*` report set and the `nfl_season_validation*.json` files under `tmp/`

## NCAAF Readiness

The NCAAF board/card work is locally coherent, and the dedicated card regression in `tests/test_ncaaf_cards_local.py` passed. The specialized renderer path is present, and `syndicate/features/ncaaf/cards.py` no longer depends on the generic fallback for the publishable path.

Blocker: the CFBD module does not import cleanly. `syndicate/features/ncaaf/cfbd.py` imports `ncaaf_source_artifacts_data_path` from `syndicate.features.ncaaf.sources`, but that symbol does not exist in `syndicate/features/ncaaf/sources.py`. This prevents all NCAAF builder tests from loading.

Status: not ready for commit as a release slice until that import is corrected and the NCAAF builder tests execute.

## NFL Readiness

The new football platform under `syndicate/features/football/**` compiles, and the football sim-engine tests largely pass. The code successfully covers roster snapshot building, depth snapshot building, team identity, player usage, NFLverse ingestion, RBSDM ingestion, and season-validation scaffolding.

However, the targeted regression run exposed contract mismatches:

- `tests.test_football_sim_engine.test_2026_betting_line_schedule_source_flows_into_game_metadata` fails because `simulation_input.adapter_metadata` does not expose `schedule_source`.
- `tests.test_football_sim_engine.test_loader_canonicalizes_home_away_and_player_teams` fails because `simulation_input.adapter_metadata` does not expose `home_team_metadata` / `away_team_metadata`.
- `tests.test_football_sim_engine.test_nfl_loader_falls_back_to_latest_available_season` fails because the season fallback behavior returns `2026` instead of the expected `2025`.

Status: the NFL layer is not release-ready yet. The code is syntactically valid, but the contract surfaced by the tests is inconsistent with the expected shape.

## Shared Infrastructure Risks

No syntax errors were reported in the modified shared template and intelligence files I checked. The following slices were clean on syntax validation:

- `syndicate/features/intelligence.py`
- `syndicate/features/intelligence_board.py`
- `syndicate/features/shared/intelligence_evaluation.py`
- `syndicate/features/shared/recommendation_engine.py`
- `syndicate/features/wnba/cards.py`
- `syndicate/features/ncaaf/cards.py`
- `syndicate/templates/shared/*`

The main shared-risk issue is scope drift: the workspace still contains unrelated intelligence/WNBA/live-lens modifications that are not part of the NCAAF + NFL release slice. Those changes should not be bundled into the same push unless they are intentionally part of a separate release.

One small note: `syndicate/features/football/season_validation.py` contains a direct `print(text)` branch for CLI output. That is not a blocker by itself, but it is a signal that the module doubles as a command-line tool and should be kept out of request-path code.

## Deployment Risks

The workspace is not safe to deploy yet.

Reasons:

1. NCAAF import failure blocks the builder test suite and indicates the NCAAF CFBD module is not loadable in the current shape.
2. NFL football contract mismatches mean the new football layer is not aligned with the asserted simulation metadata contract.
3. The working tree includes many generated artifacts and unrelated dirty files, which increases push/deploy risk and makes a rollback harder to reason about.
4. The previously observed WNBA and unrelated football changes are still present in the same workspace, so a push would mix feature work with residual state from older investigations.

## Recommended Commit Structure

### Commit Group 1: NCAAF onboarding and card work

Include:

- `syndicate/features/ncaaf/cards.py`
- `syndicate/templates/shared/_game_card.html`
- `syndicate/templates/shared/_game_card_ncaaf.html`
- `tests/test_ncaaf_cards_local.py`
- `docs/fix_notes_log.md` only if the note is specific to the NCAAF card change and you want it in the same release trail

Exclude:

- `tmp/**`
- `data/nfl_source/tracking/**`
- unrelated intelligence/WNBA/live-lens changes

### Commit Group 2: NFL football foundation

Include:

- `syndicate/features/football/**`
- `tests/test_football_sim_engine.py`
- `tests/test_depth_chart_snapshot_builder.py`
- `tests/test_roster_snapshot_builder.py`
- `scripts/build_ncaaf_*.py` only if they are intentionally part of the same onboarding release; otherwise split them further

Exclude:

- `tmp/**`
- `data/nfl_source/tracking/**`
- generated validation reports under `football_*` unless you explicitly want documentation artifacts checked in

### Commit Group 3: Documentation and audit artifacts

Include only the durable docs you actually want to keep:

- `release_readiness_audit.md`
- `ncaaf_card_experience_design.md`
- `ncaaf_card_parity_final_report.md`
- `ncaaf_week1_board_quality_review.md`

Exclude:

- transient reruns and scratch files in `tmp/`
- generated validation JSON files
- raw local caches under `data/nfl_source/tracking/`

## Final Decision

- Is the workspace safe to commit? No.
- Is the workspace safe to push? No.
- Is the workspace safe to deploy? No.

### Files That Should Not Be Committed

- `tmp/**`
- `data/nfl_source/tracking/**`
- `data/mlb_source/source_artifacts/data/live_lens/**`
- `reports/live_refresh_loop/latest_live_refresh_tick.json`
- The scratch `football_*` and `nfl_season_validation*.json` artifacts unless you are intentionally preserving them as durable analysis output
- The unrelated intelligence/WNBA changes unless they are part of a separate, explicitly coordinated release

### Blockers Remaining

- Missing import in `syndicate/features/ncaaf/cfbd.py`
- Football sim-engine metadata contract mismatches
- Season fallback mismatch in the NFL loader test
- Large dirty workspace with unrelated changes and generated artifacts

### Recommendation

Do not push this workspace as-is. Fix the NCAAF import blocker and the NFL contract mismatches first, then re-run the focused test slice before preparing release commits.