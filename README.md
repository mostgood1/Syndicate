# Syndicate

[![CI](https://github.com/mostgood1/Syndicate/actions/workflows/ci.yml/badge.svg)](https://github.com/mostgood1/Syndicate/actions/workflows/ci.yml)

Syndicate is the new unified multi-sport app that will eventually replace the separate sport-specific frontends.

The official phased implementation plan for reaching the world-class target state lives in [docs/syndicate_world_class_implementation_plan.md](docs/syndicate_world_class_implementation_plan.md).

Workspace Copilot skills for intelligence planning, advanced-data analysis, live-lens debugging, readiness, deployment parity, and sport-specific question answering are documented in [docs/syndicate-skills.md](docs/syndicate-skills.md).

The current intelligence / betting board assessment lives in [docs/intelligence_betting_board_assessment.md](docs/intelligence_betting_board_assessment.md).

The canonical cross-sport daily-update simulation reference lives in [docs/daily_update_workflow.md](docs/daily_update_workflow.md) and the generated latest simulation contract under [reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json](reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json).

## Core principles

- This is not seven apps inside one UI.
- This is one app with seven feature modules.
- After migrating each sport, immediately extract shared logic into a shared layer before migrating the next sport.
- Migration parity is required at the route and page level before a page is considered "moved" into Syndicate.
- For the lead sport being migrated, the first target is the source app's main page experience, not a reduced generic shell.
- Shared abstractions must follow proven parity. Do not flatten a richer source page into a generic component if that removes visible information density, inline controls, or same-page workflows.
- Once the lead sport proves the right page structure, that structure becomes the shared Syndicate reference surface for the next integrations.

## Migration standard

- Inspect the source Flask route, template, CSS, and client-side rendering logic before rebuilding a page in Syndicate.
- Treat the source page's primary workflow as the contract. If the source page is a single dense game pane, the Syndicate version should also be a single dense game pane.
- Keep major information lanes on the main page when the source page does. Do not force extra clicks just because Syndicate has separate modules for related data.
- Only extract shared templates and helpers after the migrated page still preserves the source experience for the lead sport.
- Validate parity with rendered output, not just route coverage or payload availability.

## Shared integration contract

- MLB is the current reference surface for shared dense game-board presentation.
- New sport integrations should match the MLB board contract across three layers at the same time: data parity, presentation parity, and service parity.
- Data parity: keep the same primary information lanes visible on the board that the source app keeps visible.
- Presentation parity: reuse the MLB-derived dense board structure as the default Syndicate game-board shell unless the source sport has a stronger proven surface.
- Service parity: game-board APIs should serve the same `game_board_v1` shape with a `board_contract` block so modules expose a consistent transport contract.
- Live lens is part of the main integration contract, not a sidecar feature. Live and pregame boards should share the same surface grammar and service contract.

## Daily Update Reference

The daily-update simulation contract is the preferred cross-sport reference when you are reasoning about how MLB, NBA, WNBA, NHL, NFL, NCAAF, and NCAAB consume available data in the sim engine.

Use the generated latest contract at [reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json](reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json) together with [docs/daily_update_workflow.md](docs/daily_update_workflow.md) when you need the authoritative source-mode, freshness, and source-path reference for a run.

## Current state

- Flask scaffold is in place.
- The shared shell follows the MLB-first migration plan.
- Module status currently breaks down as follows:
  - MLB: phase-1 complete reference module with cards, game detail, live-lens, a daily archive, season betting-card surfaces, and shared rank-board API parity across the main ranked MLB views.
  - NBA: active artifact-backed migration with cards, game detail, picks, props, live-lens, accuracy and recap lanes, season betting-card surfaces, and a stored-date archive under MLB-shaped routes.
  - NHL: active artifact-backed migration with cards, a game drill-in, ranked picks, native live-lens and accuracy lanes, props reconciliation and props-lines surfaces, and a stored-date archive built from mirrored daily artifacts.
  - WNBA: active artifact-backed migration with cards, game detail, picks, props, live-lens, native local audit and accuracy payloads, and a stored-date archive lane.
  - NFL: near-complete module-family candidate with cards, a game drill-in, grouped weekly picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion built from stored weekly recommendation snapshots.
  - NCAAF: active artifact-backed migration with weekly cards, a game drill-in, picks, a read-only live-lens monitor, a weekly archive lane, and a season betting-card companion.
  - NCAAB: active mirror-first migration with cards, a game drill-in, a live-lens board, a season review page, a historical betting-card companion, and a results archive backed by mirrored local artifacts.
- The home screen should be treated as the migration tracker for module maturity, not just a launcher.

## Local run

```powershell
py -3 -m pip install -r requirements.txt
py -3 app.py
```

## Production: the local fleet `[2026-11-17]`

Production does not run on Render. Render billing-suspended all three services on 2026-09-30 and is retired (lanes `render-retirement` 2026-11-15 and `render-config-retirement` 2026-11-17; the record is [docs/ai_context/render_retirement.md](docs/ai_context/render_retirement.md)). Production is the local WSL "fleet" on the operator's Windows machine. Runbook, including first-time setup of a fleet host: [docs/ai_context/local_production_runbook.md](docs/ai_context/local_production_runbook.md).

- `scripts/local_production.py up` supervises web, `refresh-worker`, `live-odds-worker` and a local Redis on ONE shared disk, `~/syndicate-prod/data` (`SYNDICATE_DATA_ROOT`). The same script has `status`, `down`, `backup` and `env --role <role>` (the role's derived env, secrets masked).
- Production reads go to `http://127.0.0.1:10000`. [scripts/_base_url.py](scripts/_base_url.py) resolves the URL and the admin token.
- Logs: each role writes `~/syndicate-prod/logs/<role>.log`. Read them with `py -3 scripts/fleet_logs.py` (`scripts/render_logs.py` is kept as a compatibility shim).
- Each role's `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` defaults to its old Render plan: web 2048, refresh-worker 4096, live-odds-worker 2048 (`local_production.env` can override it).
- Scheduled jobs: the supervisor runs `SCHEDULED_JOBS` from `scripts/local_production.py` (the former Render dashboard crons, `data-backup`, and fleet-only jobs added since).
- The web/worker split is unchanged: web reads precomputed artifacts only, and the workers compute.

Deploying:

- Pushing to `main` ships nothing. A fleet deploy is an exact-SHA `git merge --ff-only <sha>` in the fleet checkout `~/Syndicate` (its GitHub remote is `github`), then `local_production.py reload-web` for web, a role TERM for a worker (the supervisor restarts it), or a drained full `down` + `up` for an env change.
- Each step is gated: an unexpired `scripts/deploy_claim.py acquire` held by your lane, plus a `scripts/deploy_preflight.py` CLEAR within 15 minutes for the exact SHA. `.claude/hooks/deploy-guard.py` enforces both. Record the measurement in `.syndicate/deploys.md`. The full protocol is in `CLAUDE.md` ("Before any deploy").

Env:

- Each role's env is built at `up` from layers, a later one winning: `scripts/fleet_role_spec.json` -> `~/syndicate-prod/fleet_env/<role>.json` -> `~/syndicate-prod/local_production.env` (`ROLE__KEY` for one role) -> the launcher's forced keys. To change env, edit `local_production.env` and run a drained full `down`/`up`. A role restart reuses the old env.
- [render.yaml](render.yaml) is not read by anything. Editing it changes nothing on the fleet, and the deploy guard refuses a push that carries it.
- The launcher sets `SYNDICATE_HOSTED=true`, `SYNDICATE_SERVICE_NAME` / `SYNDICATE_SERVICE_ID=local-<role>`, `SYNDICATE_INSTANCE_ID` and `SYNDICATE_GIT_COMMIT` on every role. Code reads them through `syndicate/features/shared/service_identity.service_marker`, and branches on them (web's request-path guard, which role owns a loop), so do not strip them. The Render-era `RENDER*` names are gone since 2026-11-17.

Hosted state overrides:

- `SYNDICATE_REPORTS_ROOT`: optional absolute path for refresh status, latest manifests, logs, and daily-update state. Defaults to `reports/` under the repo.
- `SYNDICATE_DATA_ROOT`: optional absolute path for mirrored data roots such as `mlb_source/` and `nba_source/`. Defaults to `data/` under the repo.
- `SYNDICATE_ARTIFACT_ROOT_MLB`: optional published MLB artifact bundle root used by [scripts/refresh_mlb_source_mirror.ps1](scripts/refresh_mlb_source_mirror.ps1) during ingest mode. When set, Syndicate can import MLB daily/live/eval artifacts from that neutral bundle path instead of requiring any external MLB checkout.
- `SYNDICATE_ARTIFACT_ROOT_NBA`: optional published NBA artifact bundle root used by [scripts/refresh_nba_source_mirror.ps1](scripts/refresh_nba_source_mirror.ps1) during ingest mode. When set, Syndicate can import NBA processed, raw, web, live-lens, and live-snapshot artifacts from that neutral bundle path.
- `SYNDICATE_ARTIFACT_ROOT_NFL`: optional published NFL artifact bundle root used by [scripts/refresh_nfl_source_mirror.ps1](scripts/refresh_nfl_source_mirror.ps1) during ingest mode. When set, Syndicate can import NFL calibration, recommendations, props, and manifest artifacts from that neutral bundle path instead of a sibling `NFL-Betting` checkout.
- `SYNDICATE_ARTIFACT_ROOT_NCAAF`: optional published NCAAF artifact bundle root used by [scripts/refresh_ncaaf_source_mirror.ps1](scripts/refresh_ncaaf_source_mirror.ps1) during ingest mode. When set, Syndicate can import NCAAF recommendations, lines, and predicted-schedule artifacts from that neutral bundle path instead of a sibling `NCAAFCompare` checkout.
- `SYNDICATE_ARTIFACT_ROOT_NHL`: optional published NHL artifact bundle root used by [scripts/refresh_nhl_source_mirror.ps1](scripts/refresh_nhl_source_mirror.ps1) during ingest mode. When set, Syndicate can import NHL processed, live-lens, team-odds, and props artifacts from that neutral bundle path.
- `SYNDICATE_ARTIFACT_ROOT_WNBA`: optional published WNBA artifact bundle root used by [scripts/refresh_wnba_source_mirror.ps1](scripts/refresh_wnba_source_mirror.ps1) during ingest mode. When set, Syndicate can import WNBA processed, raw, and live-lens artifacts from that neutral bundle path.
- `SYNDICATE_STATE_ROOT`: optional fallback root for reports-style state when `SYNDICATE_REPORTS_ROOT` is not set. This is mainly useful when the hosted runtime mounts one persistent state directory and you want Syndicate to treat it as the reports root.
- `SYNDICATE_REQUIRE_HOSTED_STORAGE`: set this to `true` in hosted environments to make Syndicate fail fast if `SYNDICATE_DATA_ROOT` or `SYNDICATE_REPORTS_ROOT` is missing. Every fleet role declares it (`scripts/fleet_role_spec.json`), so no role falls back to repo-local paths.
- `SYNDICATE_REFRESH_STATE_BACKEND`: controls how refresh manifests, recent run history, stdout/stderr payloads, and the latest daily-update manifest are stored. Defaults to `filesystem`. Set it to `keyvalue` for a shared Redis-backed state store that web and the workers can all read. The fleet uses `keyvalue` against its local Redis.
- `SYNDICATE_REFRESH_STATE_URL`: connection URL used when `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`. `REDIS_URL` is also accepted as a fallback.
- `SYNDICATE_REFRESH_STATE_NAMESPACE`: optional key prefix for the shared refresh-state backend. Defaults to `syndicate`.
- `SYNDICATE_REFRESH_LAUNCH_MODE`: controls how the ops refresh endpoint launches work. Defaults to `detached_subprocess`, which preserves the current local behavior. Set it to `manifest_only` or `external_runner` when a hosted deployment should only record queued refresh manifests and let an external runner or worker pick them up. In those queued modes the persisted run manifests now include an explicit `externalRunner` contract describing the command plus status file paths the worker should own.

Fleet defaults (declared in `scripts/fleet_role_spec.json` and shadowed by the later env layers; `local_production.py env --role <role>` prints the env the next `up` builds for a role, and a running role's env is its `/proc/<pid>/environ`):

- Every role declares `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` and `SYNDICATE_REQUIRE_HOSTED_STORAGE=true`, and the launcher points `SYNDICATE_REFRESH_STATE_URL` at the local Redis.
- All three roles read and write the same `SYNDICATE_DATA_ROOT` (`~/syndicate-prod/data`). The launcher removes `SYNDICATE_WEB_PUBLISH_URL`, so worker-to-web publishing is a no-op on one shared disk.
- `SYNDICATE_REFRESH_LAUNCH_MODE` is declared per role in the spec; read the effective value with `env --role`.
- Published bundle locations are deployment-specific: set a `SYNDICATE_ARTIFACT_ROOT_*` override in `local_production.env` when ingest should pull from a neutral artifact bundle instead of the data root.

When the site is running in one of those queued hosted modes, a worker can pick up the latest queued refresh contract with:

```powershell
python .\scripts\run_queued_refresh_job.py
python .\scripts\run_queued_refresh_job.py --run-stamp 20260522_120000
python .\scripts\run_queued_refresh_job.py --dry-run
python .\scripts\run_refresh_worker.py
python .\scripts\run_refresh_worker.py --poll-seconds 30
python .\scripts\run_refresh_worker.py --run-once
```

That runner script claims the queued manifest, marks it `running`, and executes the persisted `externalRunner` contract through [scripts/run_refresh_odds_job.py](scripts/run_refresh_odds_job.py). This is the first worker-side pickup path for the hosted refresh contract.

[scripts/run_refresh_worker.py](scripts/run_refresh_worker.py) is the long-running worker entrypoint for hosted environments. It polls the latest queued manifest and invokes [scripts/run_queued_refresh_job.py](scripts/run_queued_refresh_job.py) whenever the ops control plane records a new `pending_external` refresh run. Use `SYNDICATE_REFRESH_WORKER_POLL_SECONDS` to control the polling interval when the default 15-second loop is not appropriate.

Shared state store:

- On Render (retired 2026-09-30) each service had its own persistent disk, so web and the workers could not share a `reports/` tree. That is why shared state goes through [syndicate/features/shared/refresh_state_store.py](syndicate/features/shared/refresh_state_store.py) with `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`.
- The fleet's roles share one disk, but the code still assumes the keyvalue store: with `SYNDICATE_HOSTED=true` the workers refuse a file backend, so `up` starts (or reuses) a local Redis.
- The current refresh-state abstraction now supports both the default filesystem mode and a shared Key Value mode for refresh manifests, recent run history, stdout/stderr log payloads, and the latest daily-update manifest.
- `SYNDICATE_DATA_ROOT` is still separate from the shared refresh-state backend. Public mirrored artifacts and per-sport source data are still file-backed, so the remaining self-hosting work is now about deployment wiring and broader artifact ownership rather than only report-state sharing.

On the fleet these overrides come from the env layers above. A developer machine running `py -3 app.py` needs none of them and falls back to the repo-local `data/` and `reports/` trees.

Hosted smoke checklist:

1. Open the web root and confirm the main Syndicate routes still render from the deployed web service.
2. Open `/ops/odds-refresh` with the admin token and confirm the page loads without filesystem-state errors.
3. If the deployment should ingest published bundles, set the relevant `SYNDICATE_ARTIFACT_ROOT_*` overrides on both the web service and the worker, then verify a dry-run refresh plan shows `artifact_bundle_or_existing_mirror` and includes `-SourceArtifactRoot` for the configured sports.
4. Trigger one dry-run refresh from the ops surface and confirm the web status moves to `pending_external`, then `running`, then `finished` or `failed` as the worker picks it up.
5. Reload web (`local_production.py reload-web`, behind the deploy claim and preflight) and confirm the latest refresh status still appears, proving that refresh state is coming from the keyvalue store instead of the web filesystem.
6. Treat any sport-level refresh failure as an artifact-generation ownership issue, not a refresh-state or worker-wiring failure, unless the status itself fails to update.

[RENDER_SELF_HOST_BACKLOG.md](RENDER_SELF_HOST_BACKLOG.md) and [RENDER_SELF_HOST_REFACTOR_PLAN.md](RENDER_SELF_HOST_REFACTOR_PLAN.md) are the Render-era plan for making a hosted instance self-refreshing. Read them as a record: Render is retired, and on the fleet the workers generate artifacts onto the shared data root.

## GitHub automation

The repo now includes a GitHub Actions workflow at [.github/workflows/ci.yml](.github/workflows/ci.yml). It runs on pushes and pull requests to `main`, installs the app dependencies, and executes the archive regression suite so the repo badge reflects real app health instead of a placeholder status image.

## Regression checks

```powershell
python -m unittest tests.test_archives
```

The `tests.test_archives` suite now also covers archive navigation plus shared rank/game transport parity regressions across MLB, NBA, NCAAB, NCAAF, NFL, NHL, and WNBA.

## Migration gate

To run the full migration automation gate in one command:

```powershell
python .\scripts\migration_gate.py
python .\scripts\migration_gate.py --base-url http://127.0.0.1:5000
python .\scripts\migration_gate.py --base-url http://127.0.0.1:5000 --json
python .\scripts\migration_gate.py --base-url http://127.0.0.1:5000 --write-dir .\reports\migration_gate\latest
```

The gate runs the migration audit, the module-tracker ownership snapshot, the archive regression suite, and the browser parity smoke in sequence, then returns one final pass/fail result. It now treats the known `source_shell_route` audit findings and the current known runtime-dependency fallback set from `scripts/module_tracker_snapshot.py` as the only allowed residual gate state, so any new audit drift or unexpected source-fallback expansion fails the gate immediately. Use `--write-dir` when you want the gate itself to persist `migration_gate_report.json` and `migration_gate_report.txt` without going through the wider mirror-refresh wrapper.

## Refresh And Gate

To refresh the local in-season artifact mirrors and then run the migration gate in one unattended workflow:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_and_gate.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_and_gate.ps1 -Date 2026-05-18
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_and_gate.ps1 -Date 2026-05-18 -BaseUrl http://127.0.0.1:5000 -Json
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_and_gate.ps1 -Date 2026-05-18 -RefreshOdds -OddsPhase all
```

This wrapper refreshes MLB, NBA, NHL, and WNBA mirrors for the selected date and then runs [scripts/migration_gate.py](scripts/migration_gate.py). Use `-BaseUrl` to reuse an already-running local server for the browser smoke phase, and use `-SkipMLB`, `-SkipNBA`, `-SkipNHL`, or `-SkipWNBA` when a sport does not need a mirror refresh for the current slice.

When `-RefreshOdds` is enabled, the wrapper first calls the new shared odds refresh orchestrator at [scripts/refresh_odds_sources.py](scripts/refresh_odds_sources.py). That tool runs the real per-sport source refresh commands first, then the existing Syndicate mirror scripts keep the local mirrors in sync. `-OddsPhase` accepts `pregame`, `live`, or `all`, `-OddsSports` accepts a comma-separated sport list such as `mlb,nba,nhl`, and `-OddsRegions` forwards a region string like `us` to the source commands that support it.

The same per-sport source-root overrides are honored end to end by the direct mirror scripts and by [scripts/refresh_and_gate.ps1](scripts/refresh_and_gate.ps1), because those wrappers simply invoke the shared orchestrator and mirror scripts in the current environment.

## Central Odds Refresh

To run the shared cross-sport odds refresh tool directly:

```powershell
python .\scripts\refresh_odds_sources.py --list
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase all --sports all --json
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase live --sports mlb,nba --skip-mirror --dry-run --json
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase live --sports mlb,nba,nhl,wnba,ncaab --skip-mirror --json
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase pregame --sports nfl,ncaaf --season 2025 --week 3 --json
```

The central tool is intentionally an orchestrator, not a new fetcher. It reuses the existing source repo entrypoints that already own each sport's odds and live-props logic:

- MLB: local `scripts/fetch_mlb_oddsapi_local.py` plus local live-lens bootstrap handling in `scripts/refresh_mlb_oddsapi.py`
- NBA: Syndicate-local `scripts/refresh_nba_oddsapi_props.py`, which reuses existing source outputs or an existing Syndicate artifact bundle first, regenerates the raw OddsAPI props snapshot locally, runs both the no-SmartSim and SmartSim-enabled prediction paths through Syndicate-owned helpers, uses a fully local SmartSim compatibility bridge, and writes the daily `props_predictions_<date>.csv`, `props_edges_<date>.csv`, `props_recommendations_<date>.csv`, and supporting SmartSim artifacts without importing `nba_betting` runtime modules.
- NHL: `scripts/refresh_nhl_oddsapi.py --artifact-root data/nhl_source/source_artifacts`
- NFL: Syndicate-local `scripts/fetch_nfl_team_odds_local.py` plus `scripts/fetch_nfl_oddsapi_props_local.py`
- WNBA: Syndicate-local `scripts/refresh_wnba_oddsapi_props.py`, which reuses existing source outputs or an existing Syndicate artifact bundle first, regenerates the raw OddsAPI props snapshot locally, runs both the no-SmartSim and SmartSim-enabled prediction paths through Syndicate-owned helpers, uses the same fully local SmartSim compatibility bridge, and writes the daily `props_predictions_<date>.csv`, `props_edges_<date>.csv`, `props_recommendations_<date>.csv`, and supporting SmartSim artifacts without importing source runtime modules.
- NCAAB: `scripts/refresh_ncaab_odds_history.py --mode current --out-dir data/ncaab_source/raw_outputs/by_date/<date>`
- NCAAF: `scripts/refresh_ncaaf_oddsapi.py --artifact-root data/ncaaf_source/source_artifacts [--week <week>]`

That keeps Syndicate aligned with the existing source models for pregame and live odds, while the mirror scripts now also copy the refreshed odds artifacts that those refreshes produce.

For the data-root contract and fallback order, see [docs/render_data_authority.md](docs/render_data_authority.md). It was written for Render's per-service disks; on the fleet every role shares `~/syndicate-prod/data`.

For NHL specifically, source mode now generates `scoreboard.csv`, team odds, and player-props lines directly inside [scripts/refresh_nhl_oddsapi.py](scripts/refresh_nhl_oddsapi.py) and writes them into the local or published artifact bundle root. Passing `--source-root` is now optional and only backfills extra processed or live-lens artifacts when needed for compatibility runs.

For NCAAB specifically, source mode now writes the raw odds snapshot locally through [scripts/refresh_ncaab_odds_history.py](scripts/refresh_ncaab_odds_history.py), and `--mirror-only` still takes the hosted-friendly path through [scripts/refresh_ncaab_source_mirror.ps1](scripts/refresh_ncaab_source_mirror.ps1) with `-UseExistingRawOutputs`. That means both fresh raw-output generation and API export can now run without requiring a sibling `NCAAB` checkout on the normal path.

Use `--dry-run` when you want the tool to resolve source roots, working directories, and commands without executing any refreshes. This is the safest way to validate a new schedule, a narrowed sport list, or a deployment environment before turning the job loose.

If a source repo is not checked out as a sibling of Syndicate, set a per-sport absolute path override before running the tool:

```powershell
$env:SYNDICATE_SOURCE_ROOT_MLB = 'D:\repos\mlb_source_bundle'
$env:SYNDICATE_SOURCE_ROOT_NBA = 'D:\repos\nba_source'
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase live --sports mlb,nba --skip-mirror --dry-run --json
```

Supported override variables follow the same pattern: `SYNDICATE_SOURCE_ROOT_MLB`, `SYNDICATE_SOURCE_ROOT_NBA`, `SYNDICATE_SOURCE_ROOT_NHL`, `SYNDICATE_SOURCE_ROOT_NFL`, `SYNDICATE_SOURCE_ROOT_WNBA`, `SYNDICATE_SOURCE_ROOT_NCAAB`, and `SYNDICATE_SOURCE_ROOT_NCAAF`.

Those variables are also respected when you run the per-sport mirror scripts directly, for example [scripts/refresh_mlb_source_mirror.ps1](scripts/refresh_mlb_source_mirror.ps1) or [scripts/refresh_nba_source_mirror.ps1](scripts/refresh_nba_source_mirror.ps1), so path overrides stay consistent across the whole refresh pipeline.

[RENDER_SELF_HOST_REFACTOR_PLAN.md](RENDER_SELF_HOST_REFACTOR_PLAN.md) records the refresh wiring and refactors that were planned for a self-refreshing Render deployment (Render retired 2026-09-30).

Each unattended run now writes a timestamped artifact bundle under [reports](reports) by default. That bundle includes the per-sport mirror refresh outputs, the gate console output, and persisted `migration_gate_report.json` plus `migration_gate_report.txt` files. Use `-ArtifactsDir` on [scripts/refresh_and_gate.ps1](scripts/refresh_and_gate.ps1) or `--write-dir` on [scripts/migration_gate.py](scripts/migration_gate.py) if you want those reports written somewhere else.

The refresh wrapper now also publishes a stable latest-status manifest at [reports/refresh_status/latest/refresh_status_latest.json](reports/refresh_status/latest/refresh_status_latest.json). That file points at the last `refresh_and_gate` artifact bundle and is the durable read target for admin/status tooling.

## Ops Status API

Syndicate now exposes two protected read-only ops endpoints for the shared odds refresh workflow:

```text
GET /api/ops/odds-refresh/status
GET /api/ops/odds-refresh/plan?date=2026-05-18&sports=mlb,nba&phase=live&skip_mirror=1
```

Set `ADMIN_TOKEN` (or `SYNDICATE_ADMIN_TOKEN`) in the environment, then pass it as either `Authorization: Bearer <token>`, `X-Admin-Token: <token>`, or `?admin_token=<token>`. The `status` endpoint reads the stable latest manifests under [reports/refresh_status](reports/refresh_status) and [reports/daily_update/latest](reports/daily_update/latest); the `plan` endpoint resolves the dry-run command plan without executing any source refreshes.

## Daily Update

For the end-to-end workflow map, artifact contract, and current sport-parity gaps, see [docs/daily_update_control_plane.md](docs/daily_update_control_plane.md).

For the shared browser refresh and hydration contract across sports, see [docs/shared_refresh_hydration_contract.md](docs/shared_refresh_hydration_contract.md).

To run a scheduled-ready global daily update that refreshes mirrors, runs the migration gate, and snapshots module status against the MLB reference contract:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1 -Date 2026-05-18
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1 -Date 2026-05-18 -BaseUrl http://127.0.0.1:5000 -Json
```

The PowerShell daily-update wrappers auto-import repo-root `.env` and `.env.local` values into process scope before they resolve per-sport credentials. Keys such as `ODDS_API_KEY` can therefore live in the same local env files the Python refresh scripts already use, while explicit process env and persisted Windows `User` or `Machine` env vars still win.

This daily update writes a timestamped run under [reports/daily_update](reports/daily_update), keeps a rolling latest manifest under [reports/daily_update/latest](reports/daily_update/latest), emits `module_tracker_snapshot.json`, and now publishes `module_tracker_gap_report.txt` so each run shows the highest-leverage MLB parity gaps and a ranked module backlog alongside migration health.

## Unified Daily Runner

To run the temporary all-sports daily workflow from Syndicate in one command, then mirror, gate, and only push after the gate succeeds:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\unified_daily_update.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\unified_daily_update.ps1 -Date 2026-05-24
powershell -ExecutionPolicy Bypass -File .\scripts\unified_daily_update.ps1 -Date 2026-05-24 -SkipGitPush
powershell -ExecutionPolicy Bypass -File .\scripts\unified_daily_update.ps1 -Date 2026-05-24 -BaseUrl http://127.0.0.1:5000 -SkipSmoke
```

This wrapper is the temporary bridge until Syndicate owns all generation locally. MLB now runs through the Syndicate-owned [scripts/refresh_mlb_oddsapi.py](scripts/refresh_mlb_oddsapi.py) path against the repo-owned [data/mlb_source](data/mlb_source) bundle. NBA and WNBA now route through the Syndicate-owned [scripts/refresh_nba_oddsapi_props.py](scripts/refresh_nba_oddsapi_props.py) and [scripts/refresh_wnba_oddsapi_props.py](scripts/refresh_wnba_oddsapi_props.py) entrypoints against the local Syndicate bundle roots. NCAAB now uses the Syndicate-owned [scripts/refresh_ncaab_odds_history.py](scripts/refresh_ncaab_odds_history.py) path when an NCAAB or TheOddsAPI key is available, otherwise it reuses the already mirrored local raw bundle. NHL, NFL, and NCAAF still run their existing source daily-update entrypoints with source-side git push explicitly disabled. After those generation steps complete, the wrapper runs [scripts/refresh_and_gate.ps1](scripts/refresh_and_gate.ps1), and only after that succeeds stages, commits, and pushes each remaining dirty source repo plus Syndicate itself.

The runner also enforces the current temporary runtime policy for the heaviest simulation steps so refreshes stay consistent and fast enough to use operationally: NBA and WNBA run with `DAILY_SMARTSIM_NSIMS=1000` and at least `DAILY_SMARTSIM_WORKERS=4`, NHL runs `-SimSamples 1000` with `-PropsBoxscoreNSims 1000`, and NFL sets `DAILY_UPDATE_SCENARIO_N_SIMS=1000`. MLB now uses the local Syndicate refresh/materialization path rooted at `data/mlb_source` and publishes the current artifact bundle to `data/mlb_source/source_artifacts`. NCAAB now refreshes its raw odds snapshot locally into `data/ncaab_source/raw_outputs/by_date/<date>` and the normal mirror step rebuilds from the local raw bundle without `-RefreshRawOutputsFromSource`. NCAAF currently still runs its native daily-update default because this wrapper does not yet have a verified low-risk local generation replacement for that path. That policy is emitted into the run manifest so dry runs and completed runs both show the exact values used.

The unified runner writes [reports/daily_update/<date>/<stamp>/unified_daily_update_run.json](reports/daily_update) plus a rolling latest copy at [reports/daily_update/latest/unified_daily_update_latest.json](reports/daily_update/latest). Those manifests record the exact source commands invoked and the final per-repo push results.

Use `-SkipGitPush` when you want the full source-refresh plus mirror-plus-gate validation without committing anything, and use the existing per-sport `-SkipMLB`, `-SkipNBA`, `-SkipNHL`, `-SkipWNBA`, `-SkipNFL`, `-SkipNCAAF`, and `-SkipNCAAB` switches to narrow the run. The script refuses to push if `-SkipRefreshGate` is set, because the intended contract is gate-first, publish-second.

## Browser parity smoke

To run an optional browser-level smoke check against the remaining source-shell routes plus the shared custom hubs:

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python .\scripts\browser_parity_smoke.py
```

The smoke runner starts Syndicate in-process by default, opens the MLB, NBA, and NHL source-shell cards routes plus the MLB, NBA, NHL, NFL, WNBA, NCAAF, and NCAAB hubs in Chromium, and verifies that each page leaves its initial loading state and renders its expected board or shared hub shell. The in-process run also injects a synthetic fallback sport so the generic shared hub template is covered in the browser. To point it at an already-running local server instead:

```powershell
python .\scripts\browser_parity_smoke.py --base-url http://127.0.0.1:5000
```

When `--base-url` is used, the synthetic fallback hub check is skipped because that route is only injected into the temporary in-process smoke server.

## Migration audit

To generate a report of likely migration parity gaps that still need cleanup:

```powershell
python .\scripts\audit_migration.py
python .\scripts\audit_migration.py --format json
python .\scripts\audit_migration.py --write migration_audit.md
```

The auditor currently flags source-shell routes, hub templates that skip the shared intro/content shell, hub intro actions that diverge from each module's declared primary href, hub templates that reuse global launch date or season state inside per-date historical loops, cards builders that still define `source_title` without an explicit `empty_state`, and source-style clients that still carry generic empty or unavailable copy.

## MLB mirror refresh

To refresh Syndicate's local MLB validation mirror for a specific date:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_mlb_source_mirror.ps1 -Date 2026-05-15
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_mlb_source_mirror.ps1 -Date 2026-05-15 -UseExistingMirrorArtifacts
```

The script copies the main live-lens report and JSONL, live prop registry files, daily snapshot and sim folders, archived market refresh history, and archived StatsAPI live feed files into [data/mlb_source](data/mlb_source).

MLB now supports the same two mirror modes as the in-season board modules. The default run prefers the repo-owned bundle under [data/mlb_source](data/mlb_source) and the `-UseExistingMirrorArtifacts` switch rewrites the MLB mirror manifest from the already mirrored files under that same bundle. A sibling MLB checkout is now only an optional override path if you explicitly set it.

Each run also writes [data/mlb_source/manifests/mirror_refresh_latest.json](data/mlb_source/manifests/mirror_refresh_latest.json), and the migration gate now validates that manifest for the core mirrored MLB artifact families: daily summary, ladders, top props, ops, snapshots, sims, and season eval payloads.

## In-Season Mirror Refresh

To refresh the local artifact mirrors for the in-season board modules:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_nba_source_mirror.ps1 -Date 2026-05-17
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_nba_source_mirror.ps1 -Date 2026-05-17 -UseExistingMirrorArtifacts
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_nhl_source_mirror.ps1 -Date 2026-05-17
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_nhl_source_mirror.ps1 -Date 2026-05-17 -UseExistingMirrorArtifacts
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_wnba_source_mirror.ps1 -Date 2026-05-17
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_wnba_source_mirror.ps1 -Date 2026-05-17 -UseExistingMirrorArtifacts
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_ncaab_source_mirror.ps1 -Date 2026-04-06
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_ncaab_source_mirror.ps1 -Date 2026-04-06 -RefreshRawOutputsFromSource
```

These scripts populate [data/nba_source](data/nba_source), [data/nhl_source](data/nhl_source), and [data/wnba_source](data/wnba_source) with the date-scoped processed artifacts that Syndicate already reads for cards, archive, picks, props, and sim-backed detail lanes.

NBA now supports the same two mirror modes. The default run prefers the repo-owned bundle under [data/nba_source](data/nba_source) and the `-UseExistingMirrorArtifacts` switch rewrites the NBA mirror manifest from the already mirrored files under that same bundle. That gives the shared ingest path a hosted-safe local mirror mode.

NHL now supports two mirror modes as well. The default run prefers the repo-owned bundle under [data/nhl_source](data/nhl_source) and the `-UseExistingMirrorArtifacts` switch rewrites the NHL mirror manifest from the already mirrored files under that same bundle. That gives the shared ingest path a hosted-safe local mirror mode.

WNBA now supports the same two mirror modes. The default run prefers the repo-owned bundle under [data/wnba_source](data/wnba_source) and the `-UseExistingMirrorArtifacts` switch rewrites the WNBA mirror manifest from the already mirrored files under that same bundle. That gives the shared ingest path a hosted-safe local mirror mode.

NCAAB now defaults to the artifact-only mirror path. Running [scripts/refresh_ncaab_source_mirror.ps1](scripts/refresh_ncaab_source_mirror.ps1) without extra switches rebuilds `data/ncaab_source/api` directly from the already mirrored bundle under [data/ncaab_source/raw_outputs](data/ncaab_source/raw_outputs). Use `-RefreshRawOutputsFromSource` only when you explicitly want a local compatibility run that re-syncs those raw outputs from a sibling `NCAAB` checkout before exporting the API bundle.

The source-backed NCAAB raw mirror contract is now intentionally narrow. Syndicate only mirrors the files currently needed to regenerate the local API bundle: `live_lens_tuning.json` plus `predictions_<date>.csv`, `predictions_unified_enriched_<date>.csv`, and `live_features_<date>.csv`.

`predictions_<date>.csv` is intentionally still part of that contract. The local settled-results export uses its `pred_total` and `pred_margin` values, while `predictions_unified_enriched_<date>.csv` supplies display and market metadata. Those two files are not interchangeable in the current raw-output lane.

## Next implementation steps

1. Keep NFL stable as the next module-family completion candidate, and only reopen its weekly snapshot family if a focused payload or view audit exposes a real artifact-backed gap.
2. Keep NBA and WNBA moving from protected artifact-backed runtime ownership into deeper fully local generator ownership, now that their active props refresh path is already Syndicate-owned.
3. Keep NHL, NFL, NCAAF, and NCAAB stable on their protected artifact-backed contracts while the hosted worker/state and bundle-publication seams are proven end to end.
4. Keep MLB stable as the reference feature module and the first fully local runtime contract, and only extract helpers after multiple real consumers prove the contract.
5. Use the module tracker and migration gate as the source of truth for sport maturity; update docs whenever the tracker contract changes.

## How We Call A Module Done

For the current migration phase, a module is only considered complete when:

1. Its hub launches the real source-backed workflow rather than a placeholder route.
2. Season, week, or date identity stays intact across launchers, cards, drill-ins, ranked boards, and archive lanes.
3. The active surfaces are covered by the focused regression suite.
4. The home tracker and docs describe the same visible surfaces the module actually ships.

MLB now meets the current phase-1 complete standard and is the first fully local runtime contract in Syndicate. NFL remains the nearest near-complete module-family candidate, and the current weekly snapshot family is coherent through cards, drill-ins, grouped picks, live-lens and archive lanes, betting-card navigation, explicit missing-week empty states, and source-style picks payload aliases.