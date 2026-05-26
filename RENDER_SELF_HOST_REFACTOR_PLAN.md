# Render Self-Host Refactor Plan

This document answers the stricter question behind Render readiness: what still has to change before Syndicate can refresh itself on Render without external source repos.

For the execution-ordered version of this plan, use [RENDER_SELF_HOST_BACKLOG.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_BACKLOG.md). This file remains the architectural overview; the backlog file is the implementation tracker.

## Current state

Syndicate is already close to deployable as a read-only web app that serves mirrored artifacts already present inside this repo.

Syndicate is not yet a self-refreshing hosted system. The remaining gap is not the request path. The remaining gap is the refresh and export path.

Today that path still depends on three assumptions:

1. [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) now resolves local bundle roots for the MLB, NHL, NFL, and NCAAF lanes and runs source-owned commands only where a sport still needs them.
2. The generation layer is still partially source-owned even though the per-sport mirror scripts under [scripts](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts) can now import from neutral artifact bundles instead of relying on repo layouts.
3. [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) launches background refresh jobs with `subprocess.Popen` and persists run state under repo-local `reports/`, which implies writable durable storage and a process model friendlier than a standard Render web dyno.

Render can host the web app now. Render cannot yet replace the whole local refresh workflow.

## Dependency map by sport

### MLB

Current source refresh owner:
- `tools.oddsapi.fetch_daily_oddsapi_markets`
- `tools.web.flask_frontend._persist_live_lens_tick`

Current Syndicate mirror behavior:
- [scripts/refresh_mlb_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_mlb_source_mirror.ps1) copies processed daily artifacts, live-lens files, market refresh history, raw feed snapshots, and season eval outputs out of the repo-owned MLB bundle.

Required Render-safe refactor:
- Move the canonical MLB OddsAPI refresh and live-lens rebuild into a Syndicate-owned package, or publish the canonical MLB artifacts to a neutral storage location that Syndicate can ingest.

### NBA

Current source refresh owner:
- `nba_betting.refresh_oddsapi_props_job`

Current Syndicate mirror behavior:
- [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1) copies processed and raw artifacts out of the owned NBA bundle root.

Required Render-safe refactor:
- The source-app bootstrap fallback used to emit live-state snapshots has already been removed from the mirror layer.
- The remaining NBA gap is generation ownership: move the props refresh job into Syndicate-owned code or a shared installable package.

### WNBA

Current source refresh owner:
- `wnba_betting.refresh_oddsapi_props_job`

Current Syndicate mirror behavior:
- [scripts/refresh_wnba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_wnba_source_mirror.ps1) copies processed, raw, and live-lens artifacts out of the owned WNBA bundle root.

Required Render-safe refactor:
- Same pattern as NBA, but the mirror layer is simpler because it is currently copy-only.
- The main missing piece is a Syndicate-owned WNBA props refresh job or a shared artifact publisher.

### NHL

Current source refresh owner:
- Syndicate-owned [scripts/refresh_nhl_oddsapi.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nhl_oddsapi.py) for scoreboard, team odds, and player-props lines

Current Syndicate mirror behavior:
- [scripts/refresh_nhl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nhl_source_mirror.ps1) ingests the local or published artifact bundle and can still backfill extra processed/live-lens files when a source repo is available.

Required Render-safe refactor:
- Keep the owned odds-snapshot lane stable.
- Replace the remaining processed board and live-lens generation dependencies so the local bundle no longer needs optional source-root backfill.

### NFL

Current source refresh owner:
- Syndicate-owned [scripts/refresh_nfl_oddsapi.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nfl_oddsapi.py) plus local helper modules for team odds and player props

Current Syndicate mirror behavior:
- [scripts/refresh_nfl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nfl_source_mirror.ps1) ingests weekly recommendations, real betting lines, props snapshots, calibration files, and manifests from the local or published artifact bundle.

Required Render-safe refactor:
- Keep the owned weekly artifact contract stable and verify any remaining deeper NFL generation/runtime seams separately from this odds-refresh boundary.

### NCAAF

Current source refresh owner:
- Syndicate-owned [scripts/refresh_ncaaf_oddsapi.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaaf_oddsapi.py)

Current Syndicate mirror behavior:
- [scripts/refresh_ncaaf_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaaf_source_mirror.ps1) ingests weekly recommendation summaries and the small recommendation bundle from the local or published artifact bundle.

Required Render-safe refactor:
- Keep the owned line-refresh bundle stable and maintain the local predicted-schedule/recommendation contract.

### NCAAB

Current source refresh owner:
- `ncaab_model.cli fetch-odds-history --mode current`

Current Syndicate mirror behavior:
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1) is not just a copy script.
- By default it rebuilds the local API bundle from mirrored raw outputs already stored under `data/ncaab_source/raw_outputs`.
- A manual compatibility switch can still resync those raw outputs from the sibling source repo before exporting the API bundle.

Required Render-safe refactor:
- The source-app API export path has been replaced with a Syndicate-owned exporter that reads mirrored NCAAB artifacts directly.
- The remaining NCAAB self-host gap is fresh raw-output generation: replace the dependence on the source CLI for odds-history refresh with Syndicate-owned code or a shared package.

## Cross-cutting refactors

These are the implementation changes required regardless of sport.

### 1. Split refresh generation from mirror ingestion

Right now [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) performs both orchestration and source-repo command resolution.

Render-safe shape:
- A Syndicate-owned refresh layer generates canonical artifacts directly, or
- Syndicate consumes canonical artifacts from object storage or another external publisher.

What must change:
- Stop defaulting to external source repo roots as the primary runtime model.
- Replace per-sport `source_repo_name` plus `cwd=source_root` execution with either local Syndicate jobs or remote artifact pull steps.

### 2. Replace repo-local status storage with durable hosted storage

Current behavior in [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py):
- writes status to `reports/refresh_status`
- writes job outputs to `reports/migration_runs`
- launches background refreshes with `subprocess.Popen`

Render-safe shape:
- status manifests live on a persistent disk or external store
- long-running refreshes run in a worker, cron job, or one-shot job process, not as detached children of the web process

What must change:
- separate web-process ops endpoints from job execution
- persist latest status outside ephemeral app storage
- treat the web service as a reader of job state, not the parent process of the job

Current implementation progress:
- [syndicate/features/shared/refresh_state_store.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/refresh_state_store.py) now provides the shared state seam for refresh manifests, recent run history, stdout/stderr payloads, and the latest daily-update manifest.
- That seam supports both the existing filesystem mode and a Key Value-backed mode suitable for Render-style shared status storage.
- [scripts/run_refresh_worker.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_refresh_worker.py) now provides the long-running worker loop that can consume queued refresh manifests outside the web process.

### 3. Convert mirror scripts from source-repo copy jobs into neutral import jobs

Right now the mirror scripts assume a checked-out sibling source repo and mostly perform `Copy-Item` against that tree.

Render-safe shape:
- mirror scripts import from a neutral artifact location such as object storage, a mounted disk, or a published release bundle
- or the scripts disappear because Syndicate writes directly into its own canonical data roots

What must change:
- replace `SourceRepo` defaults like the legacy compatibility roots used by the remaining source-bound lanes
- define a stable ingest contract per sport that no longer assumes source repo layout details

Current implementation progress:
- MLB, NBA, NHL, NFL, WNBA, and NCAAF now support neutral `artifact_bundle_or_existing_mirror` ingestion via `SYNDICATE_ARTIFACT_ROOT_*` overrides or local existing-mirror mode.
- NCAAB already supports a hosted-safe `existing_raw_outputs` bundle path for rebuilding the local API bundle.
- The remaining work in this refactor is no longer the ingest contract itself. It is the generation/export side: publishing those bundles from source-owned jobs or replacing those jobs with Syndicate-owned generation.

### 4. Remove source Flask app bootstrapping from normal refresh

Current offenders:
- No normal mirror path should still boot a source Flask app.

Render-safe shape:
- export artifacts directly from data contracts, not from source web routes

What must change:
- create direct exporters for live-state, live-lines, recommendations, and results where Syndicate still relies on source-app API execution

## Recommended execution order

1. Decide whether Render should be read-only or self-refreshing.
2. If read-only, deploy now and keep refresh outside Render.
3. If self-refreshing, replace the remaining source-owned generation jobs now that the normal mirror bootstrap paths are gone.
4. Next replace [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) with a Syndicate-owned refresh runner or a remote artifact puller.
5. Then move [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) off detached subprocess execution and onto durable hosted job state.
6. Only after that expand [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) into a full self-refreshing deployment blueprint.

## What counts as done

Syndicate is self-host ready when all of the following are true:

1. No normal refresh path requires an external checkout.
2. No normal refresh path boots a source Flask app to export artifacts.
3. The web service can restart without losing the latest refresh status and manifests.
4. Refresh jobs can run outside the web process and publish status that the web app can read.
5. The artifact contracts consumed by Syndicate pages are generated by Syndicate-owned code or pulled from a neutral published source.