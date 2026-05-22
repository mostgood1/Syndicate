# Render Self-Host Refactor Plan

This document answers the stricter question behind Render readiness: what still has to change before Syndicate can refresh itself on Render without sibling source repos.

## Current state

Syndicate is already close to deployable as a read-only web app that serves mirrored artifacts already present inside this repo.

Syndicate is not yet a self-refreshing hosted system. The remaining gap is not the request path. The remaining gap is the refresh and export path.

Today that path still depends on three assumptions:

1. [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) resolves sibling repo roots by default and runs source-owned commands inside those repos.
2. The per-sport mirror scripts under [scripts](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts) mostly copy files out of those source repos after the source refresh completes.
3. [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) launches background refresh jobs with `subprocess.Popen` and persists run state under repo-local `reports/`, which implies writable durable storage and a process model friendlier than a standard Render web dyno.

Render can host the web app now. Render cannot yet replace the whole local multi-repo refresh workflow.

## Dependency map by sport

### MLB

Current source refresh owner:
- `tools.oddsapi.fetch_daily_oddsapi_markets`
- `tools.web.flask_frontend._persist_live_lens_tick`

Current Syndicate mirror behavior:
- [scripts/refresh_mlb_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_mlb_source_mirror.ps1) copies processed daily artifacts, live-lens files, market refresh history, raw feed snapshots, and season eval outputs out of `MLB-BettingV2`.

Required Render-safe refactor:
- Move the canonical MLB OddsAPI refresh and live-lens rebuild into a Syndicate-owned package, or publish the canonical MLB artifacts to a neutral storage location that Syndicate can ingest.

### NBA

Current source refresh owner:
- `nba_betting.refresh_oddsapi_props_job`

Current Syndicate mirror behavior:
- [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1) copies processed and raw artifacts out of `NBA-Betting`.
- If a live-state snapshot is missing, the mirror script can boot the source Flask app with a temporary script and hit `/api/live_state` to force snapshot generation.

Required Render-safe refactor:
- Move the props refresh job into Syndicate-owned code or a shared installable package.
- Remove the source-app bootstrap fallback used to emit live-state snapshots and replace it with a direct exporter owned by Syndicate.

### WNBA

Current source refresh owner:
- `wnba_betting.refresh_oddsapi_props_job`

Current Syndicate mirror behavior:
- [scripts/refresh_wnba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_wnba_source_mirror.ps1) copies processed, raw, and live-lens artifacts out of `WNBA-Betting`.

Required Render-safe refactor:
- Same pattern as NBA, but the mirror layer is simpler because it is currently copy-only.
- The main missing piece is a Syndicate-owned WNBA props refresh job or a shared artifact publisher.

### NHL

Current source refresh owner:
- `nhl_betting.cli team-odds-collect`
- `nhl_betting.cli props-collect --source oddsapi`

Current Syndicate mirror behavior:
- [scripts/refresh_nhl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nhl_source_mirror.ps1) copies processed board files, live-lens files, game odds, team odds, and props files out of `NHL-Betting`.

Required Render-safe refactor:
- Move the source CLI collection commands into Syndicate-owned code or into a separately deployable shared package.
- Keep the mirror contract, but make its source something Render can reach without a sibling repo checkout.

### NFL

Current source refresh owner:
- `nfl_compare/src/odds_api_client.py`
- `scripts/fetch_oddsapi_props.py`

Current Syndicate mirror behavior:
- [scripts/refresh_nfl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nfl_source_mirror.ps1) copies weekly recommendations, real betting lines, props snapshots, calibration files, and manifests out of `NFL-Betting`.

Required Render-safe refactor:
- Extract the team-odds and player-props refreshers into Syndicate-owned code or a shared package.
- Preserve the weekly artifact contract now used by the mirror layer.

### NCAAF

Current source refresh owner:
- `fetch_2025_lines.py`

Current Syndicate mirror behavior:
- [scripts/refresh_ncaaf_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaaf_source_mirror.ps1) copies weekly recommendation summaries and a small recommendation bundle out of `NCAAFCompare`.

Required Render-safe refactor:
- Replace the direct dependency on the standalone source fetch script with a Syndicate-owned line refresh job.
- This is structurally the smallest sports-specific migration.

### NCAAB

Current source refresh owner:
- `ncaab_model.cli fetch-odds-history --mode current`
- the source Flask app itself for API export

Current Syndicate mirror behavior:
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1) is not just a copy script.
- It boots the source app under a temporary Python script, calls source APIs with `app.test_client()`, exports recommendations, results, live state, live lines, date metadata, and also copies raw outputs from the source `outputs` tree.

Required Render-safe refactor:
- This is the highest-priority self-host blocker.
- Replace the source-app API export path with a Syndicate-owned exporter that reads mirrored or persisted NCAAB artifacts directly.
- Replace the dependence on the source CLI for odds-history refresh with Syndicate-owned code or a shared package.

## Cross-cutting refactors

These are the implementation changes required regardless of sport.

### 1. Split refresh generation from mirror ingestion

Right now [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) performs both orchestration and source-repo command resolution.

Render-safe shape:
- A Syndicate-owned refresh layer generates canonical artifacts directly, or
- Syndicate consumes canonical artifacts from object storage or another external publisher.

What must change:
- Stop defaulting to sibling repo roots as the primary runtime model.
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

### 3. Convert mirror scripts from source-repo copy jobs into neutral import jobs

Right now the mirror scripts assume a checked-out sibling source repo and mostly perform `Copy-Item` against that tree.

Render-safe shape:
- mirror scripts import from a neutral artifact location such as object storage, a mounted disk, or a published release bundle
- or the scripts disappear because Syndicate writes directly into its own canonical data roots

What must change:
- replace `SourceRepo` defaults like `..\NBA-Betting` and `..\NHL-Betting`
- define a stable ingest contract per sport that no longer assumes source repo layout details

### 4. Remove source Flask app bootstrapping from normal refresh

Current offenders:
- [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1) can boot the NBA source app to force a live-state snapshot
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1) boots the NCAAB source app and exports APIs via `app.test_client()`

Render-safe shape:
- export artifacts directly from data contracts, not from source web routes

What must change:
- create direct exporters for live-state, live-lines, recommendations, and results where Syndicate still relies on source-app API execution

## Recommended execution order

1. Decide whether Render should be read-only or self-refreshing.
2. If read-only, deploy now and keep refresh outside Render.
3. If self-refreshing, first eliminate NCAAB and NBA source-app bootstrapping.
4. Next replace [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) with a Syndicate-owned refresh runner or a remote artifact puller.
5. Then move [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) off detached subprocess execution and onto durable hosted job state.
6. Only after that expand [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) into a full self-refreshing deployment blueprint.

## What counts as done

Syndicate is self-host ready when all of the following are true:

1. No normal refresh path requires a sibling checkout such as `..\NBA-Betting` or `..\NCAAB`.
2. No normal refresh path boots a source Flask app to export artifacts.
3. The web service can restart without losing the latest refresh status and manifests.
4. Refresh jobs can run outside the web process and publish status that the web app can read.
5. The artifact contracts consumed by Syndicate pages are generated by Syndicate-owned code or pulled from a neutral published source.