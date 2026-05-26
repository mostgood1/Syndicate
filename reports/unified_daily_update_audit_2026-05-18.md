# Unified Daily Update Audit

Date: 2026-05-18

## What this audit answers

This audit maps the real source-of-truth pipeline for each repo, the current Syndicate ingestion method for that sport, and the gaps that block a single all-sports daily update workflow.

The key finding is that Syndicate is not using one consistent source-ingestion model today.

- MLB, NBA, WNBA, and NHL are partly mirror-backed.
- NFL and NCAAF now have local mirror refresh scripts and local-mirror-first loader support, but they are newer and narrower than the older four mirror contracts.
- NCAAB is still subprocess-API-backed from the source app.
- Syndicate's legacy `scripts/daily_update.ps1` still does not run source daily updates for any sport. It remains a refresh-and-gate wrapper.
- Syndicate now also has `scripts/unified_daily_update.ps1`, which is the first real source-update-first orchestrator for all sports.

## Current Syndicate orchestrator

Current entrypoints inside Syndicate:

- `scripts/daily_update.ps1`
- `scripts/unified_daily_update.ps1`
- `scripts/refresh_and_gate.ps1`
- `scripts/refresh_mlb_source_mirror.ps1`
- `scripts/refresh_nba_source_mirror.ps1`
- `scripts/refresh_nhl_source_mirror.ps1`
- `scripts/refresh_wnba_source_mirror.ps1`
- `scripts/refresh_nfl_source_mirror.ps1`
- `scripts/refresh_ncaaf_source_mirror.ps1`

What it does now:

- The legacy refresh wrapper refreshes mirrored artifacts for MLB, NBA, NHL, WNBA, NFL, and NCAAF.
- The new unified updater runs source repo update commands first, then calls Syndicate refresh/gate.
- The gate stage runs `scripts/migration_gate.py` and writes migration artifacts.

What it does not do now:

- It does not yet refresh NCAAB into a Syndicate-local mirror.
- It does not yet define one fully artifact-backed output contract across all sports.

## Per-sport pipeline map

| Sport | Source repo daily-update entrypoint | Primary source artifacts generated | Current Syndicate ingestion model | Audit status |
| --- | --- | --- | --- | --- |
| MLB | `Syndicate/tools/daily_update.py` | `data/daily/daily_summary_<date>.json`, `_profile_bundle`, `_locked_policy`, `_hr_targets`, daily snapshots, daily sims, live lens report, raw StatsAPI feed, `data/eval/seasons/.../season_betting_day_*` | Local mirror first under `data/mlb_source`, fallback to sibling repo per-file | Partial mirror, strong source contract |
| NBA | `Syndicate/scripts/daily_update.ps1` | `data/processed/game_cards_<date>.csv`, `recommendations_slate_<date>.json`, `cards_sim_detail_<date>.json`, `cards_props_snapshot_<date>.json`, `props_recommendations_top_by_game_<date>.json` | Local mirror first under `data/nba_source`, some source-app subprocess/API usage for parity lanes | Mirror-backed but not source-update-backed |
| WNBA | `Syndicate/scripts/daily_update.ps1` | `data/processed/game_cards_<date>.csv`, `recommendations_slate_<date>.json`, `cards_sim_detail_<date>.json`, `cards_props_snapshot_<date>.json`, `props_recommendations_top_by_game_<date>.json` | Local mirror first under `data/wnba_source` | Mirror-backed but not source-update-backed |
| NHL | `Syndicate/scripts/daily_update.ps1` | `data/processed/predictions_<date>.csv`, `predictions_sim_<date>.csv`, `recommendations_<date>.csv`, `recommendations_sim_<date>.csv`, `props_boxscores_sim_<date>.csv`, `props_recommendations_<date>.csv`, scoreboard snapshot | Local mirror first under `data/nhl_source` | Mirror-backed but not source-update-backed |
| NFL | `NFL-Betting/daily_update.ps1` | `nfl_compare/data/current_week.json`, `upcoming_recs_<season>_wk<week>.csv`, `upcoming_recs_<season>_wk<week>_publish.csv`, props/scenario/backtest/manifests | Local mirror first under `data/nfl_source`, fallback to sibling repo data root | Mirror-backed for core weekly files |
| NCAAF | `NCAAFCompare/Run-DailyUpdate.ps1` | `data/recommendations_summary/index.json`, `week_<n>.json`, refreshed schedule/prediction/recommendation outputs via weekly pipeline | Local mirror first under `data/ncaaf_source`, fallback to sibling repo | Mirror-backed for recommendation summaries |
| NCAAB | `NCAAB/scripts/daily_update.ps1` and `scripts/auto_daily_update.ps1` | Source app outputs and uploaded Render artifacts; route-backed date/results payloads | Source app subprocess/API calls from Syndicate, not file mirroring | No stable local artifact contract in Syndicate |

## What the source repos really produce

### MLB

Source entrypoint:

- `Syndicate/tools/daily_update.py`

Confirmed source artifact families:

- `data/daily/daily_summary_<date>.json`
- `data/daily/daily_summary_<date>_profile_bundle.json`
- `data/daily/daily_summary_<date>_locked_policy.json`
- `data/daily/daily_summary_<date>_hr_targets.json`
- `data/daily/snapshots/<date>/...`
- `data/daily/sims/<date>/...`
- `data/live_lens/live_lens_report_<date>.json`
- `data/live_lens/prop_registry/...`
- `data/raw/statsapi/feed_live/<season>/<date>/...`
- `data/eval/seasons/<season>/.../season_betting_day_<season>_<date>_<profile>.json`

Important current mismatch:

- Syndicate's MLB mirror now copies the current-date `daily_summary_*` family, ladders, top props, ops, snapshots, sims, raw feed files, and current-date season betting payloads into `Syndicate/data/mlb_source`.
- That is enough to materially reduce sibling-repo fallback for cards and season-family surfaces.
- The remaining gap is breadth, not the basic contract: the mirror is still current-date focused rather than a broader historical season mirror.

### NBA

Source entrypoint:

- `Syndicate/scripts/daily_update.ps1`

Confirmed artifacts Syndicate mirrors:

- `game_cards_<date>.csv`
- `recommendations_slate_<date>.json`
- `cards_sim_detail_<date>.json`
- `cards_props_snapshot_<date>.json`
- `props_recommendations_top_by_game_<date>.json`

Current state:

- Syndicate mirrors the exact processed artifacts its current routes use.
- Syndicate does not run the NBA source daily update itself; it assumes the source repo already generated those files.

### WNBA

Source entrypoint:

- `Syndicate/scripts/daily_update.ps1`

Confirmed artifacts Syndicate mirrors:

- `game_cards_<date>.csv`
- `recommendations_slate_<date>.json`
- `cards_sim_detail_<date>.json`
- `cards_props_snapshot_<date>.json`
- `props_recommendations_top_by_game_<date>.json`

Current state:

- Same model as NBA.
- Mirror contract is clear, but generation is still upstream-only.

### NHL

Source entrypoint:

- `Syndicate/scripts/daily_update.ps1`

Confirmed artifacts Syndicate mirrors:

- `predictions_<date>.csv`
- `predictions_sim_<date>.csv`
- `recommendations_<date>.csv`
- `recommendations_sim_<date>.csv`
- `props_boxscores_sim_<date>.csv`
- `props_boxscores_sim_hist_<date>.csv`
- `props_recommendations_<date>.csv`
- `data/odds/games/date=<date>/scoreboard.csv`

Current state:

- Mirror contract exists and is usable.
- Like NBA and WNBA, Syndicate does not run the source NHL daily update itself.

### NFL

Source entrypoint:

- `NFL-Betting/daily_update.ps1`

Confirmed source outputs used by Syndicate or likely needed for parity:

- `nfl_compare/data/current_week.json`
- `upcoming_recs_<season>_wk<week>.csv`
- `upcoming_recs_<season>_wk<week>_publish.csv`
- player props artifacts
- scenario artifacts
- manifests and calibration bundles

Current state:

- Syndicate now has `scripts/refresh_nfl_source_mirror.ps1` and a local-mirror-first `data/nfl_source` loader path.
- The current mirror scope is intentionally narrow: `current_week.json`, weekly `upcoming_recs_*.csv`, and `manifests/` plus core calibration files.
- NFL is no longer a direct-read-only special case, but its mirror contract is still smaller than the full source repo data surface.

### NCAAF

Source entrypoint:

- `NCAAFCompare/Run-DailyUpdate.ps1`

Confirmed source outputs used by Syndicate:

- `data/recommendations_summary/index.json`
- `data/recommendations_summary/week_<n>.json`
- supporting recommendation data emitted by the weekly pipeline

Current state:

- Syndicate now has `scripts/refresh_ncaaf_source_mirror.ps1` and a local-mirror-first `data/ncaaf_source` loader path.
- The current mirror scope is centered on `data/recommendations_summary` and a small number of supporting summary files.

### NCAAB

Source entrypoints:

- `NCAAB/scripts/daily_update.ps1`
- `NCAAB/scripts/auto_daily_update.ps1`

Current state:

- Syndicate does not read stable mirrored files for NCAAB.
- `syndicate/features/ncaab/sources.py` shells into the source app via its `.venv` and calls Flask test-client routes like `/api/display_prediction_dates`, `/api/dates`, `/api/results_dates`, and `/api/results_by_date`.
- This is the least migration-safe ingestion model because it requires a working source app environment, source app imports, and route stability rather than a committed artifact contract.

## Current ingestion models inside Syndicate

Syndicate currently has three distinct source models.

### Model 1: local-mirror-first file contract

Used by:

- MLB
- NBA
- WNBA
- NHL

Behavior:

- Prefer `Syndicate/data/<sport>_source/...`
- Fall back to sibling source repo when the file is missing

This is the best current migration model because it allows local validation and eventual deployment independence from sibling repos.

### Model 2: direct sibling-repo file reads

Used by:

- no longer the preferred path for NFL or NCAAF after the new mirror work

Behavior:

- No mirror stage
- No explicit local Syndicate copy
- Routes read the sibling repo directly

This still exists as fallback behavior when a mirrored file is missing.

### Model 3: subprocess source-app API calls

Used by:

- NCAAB

Behavior:

- Spawn the source repo Python environment
- Import the source app
- Hit source Flask routes via test client

This is the least stable migration model because it depends on source code execution instead of committed artifacts.

## Gaps blocking a true single daily update

### Gap 1: Syndicate is an auditor, not yet an upstream orchestrator

Current `scripts/daily_update.ps1` in Syndicate refreshes mirrors and runs the migration gate, but it does not drive source generation.

Required change:

- A unified orchestrator must invoke each source repo's native daily-update entrypoint before any mirror refresh step.

### Gap 2: Mirror coverage still does not exist for every sport

Current mirror scripts exist only for:

- MLB
- NBA
- NHL
- WNBA
- NFL
- NCAAF

Required change:

- Replace or supplement the NCAAB subprocess route model with an artifact mirror or export bundle.

### Gap 3: MLB mirror is improved but still incomplete

Current MLB mirror coverage now includes the key current-date summary and betting-card artifacts Syndicate routes rely on.

Required change:

- Expand beyond the current-date slice when future Syndicate pages need broader historical season payload coverage or additional profile families.

### Gap 4: NCAAB has no stable mirror contract

Current NCAAB access depends on importing and executing the source Flask app.

Required change:

- Define a committed export surface for the NCAAB routes Syndicate needs, or
- add a `refresh_ncaab_source_mirror.ps1` that copies the source app outputs and any uploaded artifacts into `Syndicate/data/ncaab_source`.

### Gap 5: unified success criteria do not exist yet

The current Syndicate automation proves UI migration and some mirror freshness, but not end-to-end all-sports source generation.

Required change:

- The unified daily update needs a per-sport success contract with emitted artifacts, freshness checks, and route/API smoke checks.

## Recommended target architecture

### Stage 1: source generation

Run the native source updater for each sport.

- MLB: `python tools/daily_update.py ...`
- NBA: `powershell -File scripts/daily_update.ps1 ...`
- WNBA: `powershell -File scripts/daily_update.ps1 ...`
- NHL: `powershell -File scripts/daily_update.ps1 ...`
- NFL: `powershell -File daily_update.ps1 ...`
- NCAAF: `powershell -File Run-DailyUpdate.ps1 ...`
- NCAAB: `powershell -File scripts/daily_update.ps1 ...`

### Stage 2: source-to-Syndicate mirroring

Refresh the local Syndicate mirror for every sport that should be artifact-backed.

Minimum target set:

- MLB
- NBA
- WNBA
- NHL
- NFL
- NCAAF
- NCAAB

### Stage 3: Syndicate contract validation

Run sport-level validations against the mirrored or directly-mounted data contract.

- date discovery
- non-empty primary board/card payload
- required source files present
- no forced sample fallback for artifact-backed routes

### Stage 4: migration gate and browser smoke

Keep existing:

- `scripts/migration_gate.py`
- `scripts/browser_parity_smoke.py`

But run them after upstream generation and mirror refresh, not as a substitute for those steps.

## Concrete next implementation steps

1. Replace NCAAB subprocess-only ingestion with a mirror-backed `data/ncaab_source` contract, or at minimum add a refresh script that exports the source route payloads into JSON artifacts Syndicate can read without importing the source app.
2. Expand `refresh_mlb_source_mirror.ps1` so the MLB mirror is complete for cards, live lens, and season-family pages.
3. Broaden the new NFL mirror beyond weekly recommendation snapshots if future Syndicate pages need deeper props/scenario coverage from local mirrors.
4. Broaden the new NCAAF mirror if future pages need more than the recommendation summary family.
5. Broaden the new all-sports orchestrator in Syndicate so it can become the default daily entrypoint once NCAAB has a stable mirror/export contract.

## Recommended unified script shape

Suggested new Syndicate entrypoint:

- `scripts/unified_daily_update.ps1`

Recommended stages:

- `Invoke-MLBSourceUpdate`
- `Invoke-NBASourceUpdate`
- `Invoke-WNBASourceUpdate`
- `Invoke-NHLSourceUpdate`
- `Invoke-NFLSourceUpdate`
- `Invoke-NCAAFSourceUpdate`
- `Invoke-NCAABSourceUpdate`
- `Refresh-AllMirrors`
- `Validate-AllContracts`
- `Run-MigrationGate`
- `Run-BrowserSmoke`

Recommended failure policy:

- Hard fail if a source update fails for a requested sport.
- Hard fail if the required mirrored artifact family is missing after refresh.
- Soft fail browser smoke only when the source and artifact contract are present but parity is still incomplete.

## Bottom line

We now understand the real piping.

- The source repos already have sport-specific daily-update entrypoints.
- Syndicate now mirrors MLB, NBA, NHL, WNBA, NFL, and NCAAF locally.
- Syndicate now has a first-pass all-sports source-update orchestrator in `scripts/unified_daily_update.ps1`.
- NFL and NCAAF now have first-pass mirror support in Syndicate.
- NCAAB still bypasses the artifact model entirely.
- MLB's mirror is materially stronger now, but still not a broad historical mirror.

The correct next move is to finish formalizing one source-update-plus-mirror contract per sport, then promote `scripts/unified_daily_update.ps1` from a first-pass orchestrator into the default daily workflow.