# Syndicate

[![CI](https://github.com/mostgood1/Syndicate/actions/workflows/ci.yml/badge.svg)](https://github.com/mostgood1/Syndicate/actions/workflows/ci.yml)
[![Render Blueprint](https://img.shields.io/badge/Render-Blueprint-46E3B7?logo=render&logoColor=white)](https://github.com/mostgood1/Syndicate/blob/main/render.yaml)

Syndicate is the new unified multi-sport app that will eventually replace the separate sport-specific frontends.

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

## Current state

- Flask scaffold is in place.
- The shared shell follows the MLB-first migration plan.
- Module status currently breaks down as follows:
  - MLB: phase-1 complete reference module with cards, game detail, live-lens, a daily archive, season betting-card surfaces, and shared rank-board API parity across the main ranked MLB views.
  - NBA: active source-backed migration with cards, game detail, picks, live-lens, season betting-card surfaces, and a stored-date archive under MLB-shaped routes.
  - NHL: active source-backed migration with cards, a game drill-in, ranked picks, a live-lens board, and a stored-date archive lane projected from daily snapshots.
  - WNBA: active shared-board migration with cards, game detail, picks, props, live lens, and a stored-date archive lane.
  - NFL: near-complete module-family candidate with cards, a game drill-in, grouped weekly picks, a season betting-card companion, and source-style picks API aliases built from stored weekly recommendation snapshots.
  - NCAAF: active artifact-backed migration with weekly cards, a game drill-in, picks, and a season betting-card companion.
  - NCAAB: active source-backed migration with cards, a game drill-in, a live-lens board, a season review page, a historical betting-card companion, and a results archive.
- The home screen should be treated as the migration tracker for module maturity, not just a launcher.

## Local run

```powershell
py -3 -m pip install -r requirements.txt
py -3 app.py
```

## Render deploy

This repo is ready to deploy to Render as a Blueprint-backed Flask app using [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml).

Current hosted boundary:

- The web app itself is deployable on Render now.
- The hosted ops control plane and refresh-status backend are now Render-safe: the blueprint defines a web service, a background worker, and a shared Render Key Value instance for refresh manifests and logs.
- Public module data is still mirror-first with respect to sibling source repos. Hosted refreshes can safely own status and worker execution now, but sports that still depend on sibling repo generation or source-app export are not yet fully self-refreshing on Render.

Render setup:

1. In Render, choose New + and create a Blueprint instance from the GitHub repo `mostgood1/Syndicate`.
2. Let Render read [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml), which now defines three resources:
  - `syndicate`: the public Flask web service.
  - `syndicate-refresh-worker`: the background worker that polls for queued refresh jobs.
  - `syndicate-refresh-state`: the shared Render Key Value instance used for refresh state and logs.
3. Set `ADMIN_TOKEN` in Render if you want the protected ops/status endpoints enabled for the deployed instance.
4. Deploy the Blueprint and verify that all three resources become healthy.
5. Verify the root page plus any needed public module routes from the web service.

Hosted state overrides:

- `SYNDICATE_REPORTS_ROOT`: optional absolute path for refresh status, latest manifests, logs, and daily-update state. Defaults to `reports/` under the repo.
- `SYNDICATE_DATA_ROOT`: optional absolute path for mirrored data roots such as `mlb_source/` and `nba_source/`. Defaults to `data/` under the repo.
- `SYNDICATE_ARTIFACT_ROOT_MLB`: optional published MLB artifact bundle root used by [scripts/refresh_mlb_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_mlb_source_mirror.ps1) during ingest mode. When set, Syndicate can import MLB daily/live/eval artifacts from that neutral bundle path instead of a sibling `MLB-BettingV2` checkout.
- `SYNDICATE_ARTIFACT_ROOT_NBA`: optional published NBA artifact bundle root used by [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1) during ingest mode. When set, Syndicate can import NBA processed, raw, web, live-lens, and live-snapshot artifacts from that neutral bundle path instead of a sibling `NBA-Betting` checkout.
- `SYNDICATE_ARTIFACT_ROOT_NHL`: optional published NHL artifact bundle root used by [scripts/refresh_nhl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nhl_source_mirror.ps1) during ingest mode. When set, Syndicate can import NHL processed, live-lens, team-odds, and props artifacts from that neutral bundle path instead of a sibling `NHL-Betting` checkout.
- `SYNDICATE_ARTIFACT_ROOT_WNBA`: optional published WNBA artifact bundle root used by [scripts/refresh_wnba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_wnba_source_mirror.ps1) during ingest mode. When set, Syndicate can import WNBA processed, raw, and live-lens artifacts from that neutral bundle path instead of a sibling `WNBA-Betting` checkout.
- `SYNDICATE_STATE_ROOT`: optional fallback root for reports-style state when `SYNDICATE_REPORTS_ROOT` is not set. This is mainly useful when the hosted runtime mounts one persistent state directory and you want Syndicate to treat it as the reports root.
- `SYNDICATE_REFRESH_STATE_BACKEND`: controls how refresh manifests, recent run history, stdout/stderr payloads, and the latest daily-update manifest are stored. Defaults to `filesystem`. Set it to `keyvalue` for a shared Redis or Render Key Value-backed state store that both the web service and worker can read.
- `SYNDICATE_REFRESH_STATE_URL`: connection URL used when `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`. `REDIS_URL` is also accepted as a fallback.
- `SYNDICATE_REFRESH_STATE_NAMESPACE`: optional key prefix for the shared refresh-state backend. Defaults to `syndicate`.
- `SYNDICATE_REFRESH_LAUNCH_MODE`: controls how the ops refresh endpoint launches work. Defaults to `detached_subprocess`, which preserves the current local behavior. Set it to `manifest_only` or `external_runner` when a hosted deployment should only record queued refresh manifests and let an external runner or worker pick them up. In those queued modes the persisted run manifests now include an explicit `externalRunner` contract describing the command plus status file paths the worker should own.

Blueprint defaults:

- The checked-in [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) sets `SYNDICATE_REFRESH_LAUNCH_MODE=external_runner` on the web service.
- The checked-in [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) sets `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` for both the web service and the worker.
- The checked-in [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) wires `SYNDICATE_REFRESH_STATE_URL` from the Render Key Value service connection string.
- The checked-in [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) leaves `SYNDICATE_DATA_ROOT` unset, so public mirrored artifacts still come from the repo-backed `data/` tree unless you deliberately introduce a separate hosted artifact strategy.

When the site is running in one of those queued hosted modes, a worker can pick up the latest queued refresh contract with:

```powershell
python .\scripts\run_queued_refresh_job.py
python .\scripts\run_queued_refresh_job.py --run-stamp 20260522_120000
python .\scripts\run_queued_refresh_job.py --dry-run
python .\scripts\run_refresh_worker.py
python .\scripts\run_refresh_worker.py --poll-seconds 30
python .\scripts\run_refresh_worker.py --run-once
```

That runner script claims the queued manifest, marks it `running`, and executes the persisted `externalRunner` contract through [scripts/run_refresh_odds_job.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_refresh_odds_job.py). This is the first worker-side pickup path for the hosted refresh contract.

[scripts/run_refresh_worker.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_refresh_worker.py) is the long-running worker entrypoint for hosted environments. It polls the latest queued manifest and invokes [scripts/run_queued_refresh_job.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_queued_refresh_job.py) whenever the ops control plane records a new `pending_external` refresh run. Use `SYNDICATE_REFRESH_WORKER_POLL_SECONDS` to control the polling interval when the default 15-second loop is not appropriate.

Important Render constraint:

- Render persistent disks are attached to only one service instance and cannot be shared between the web service and a background worker.
- Because of that single-service disk limit, a self-refreshing Render deployment should use the shared state backend in [syndicate/features/shared/refresh_state_store.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/refresh_state_store.py) with `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` instead of trying to share a local `reports/` disk between web and worker.
- The current refresh-state abstraction now supports both the default filesystem mode and a shared Key Value mode for refresh manifests, recent run history, stdout/stderr log payloads, and the latest daily-update manifest.
- `SYNDICATE_DATA_ROOT` is still separate from the shared refresh-state backend. Public mirrored artifacts and per-sport source data are still file-backed, so the remaining self-hosting work is now about deployment wiring and broader artifact ownership rather than only report-state sharing.

These overrides are part of the self-hosting path. They are not required for the current read-only repo-backed Render deployment, but they are now supported by the ops/status layer so hosted refresh state can move onto durable storage without changing the public ops endpoints.

Hosted smoke checklist:

1. Open the web root and confirm the main Syndicate routes still render from the deployed web service.
2. Open `/ops/odds-refresh` with the admin token and confirm the page loads without filesystem-state errors.
3. Trigger one dry-run refresh from the ops surface and confirm the web status moves to `pending_external`, then `running`, then `finished` or `failed` as the worker picks it up.
4. Restart or redeploy the web service and confirm the latest refresh status still appears, proving that refresh state is coming from Key Value instead of the web filesystem.
5. Treat any sport-level refresh failure as an artifact-generation ownership issue, not a refresh-state or worker-wiring failure, unless the status itself fails to update.

If the goal is a self-refreshing hosted instance rather than a repo-backed read-only deployment, start with [RENDER_SELF_HOST_BACKLOG.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_BACKLOG.md) for the execution order and use [RENDER_SELF_HOST_REFACTOR_PLAN.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_REFACTOR_PLAN.md) for the architectural rationale behind that backlog.

## GitHub automation

The repo now includes a GitHub Actions workflow at [.github/workflows/ci.yml](c:/Users/mostg/OneDrive/Coding/Syndicate/.github/workflows/ci.yml). It runs on pushes and pull requests to `main`, installs the app dependencies, and executes the archive regression suite so the repo badge reflects real app health instead of a placeholder status image.

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

This wrapper refreshes MLB, NBA, NHL, and WNBA mirrors for the selected date and then runs [scripts/migration_gate.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/migration_gate.py). Use `-BaseUrl` to reuse an already-running local server for the browser smoke phase, and use `-SkipMLB`, `-SkipNBA`, `-SkipNHL`, or `-SkipWNBA` when a sport does not need a mirror refresh for the current slice.

When `-RefreshOdds` is enabled, the wrapper first calls the new shared odds refresh orchestrator at [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py). That tool runs the real per-sport source refresh commands first, then the existing Syndicate mirror scripts keep the local mirrors in sync. `-OddsPhase` accepts `pregame`, `live`, or `all`, `-OddsSports` accepts a comma-separated sport list such as `mlb,nba,nhl`, and `-OddsRegions` forwards a region string like `us` to the source commands that support it.

The same per-sport source-root overrides are honored end to end by the direct mirror scripts and by [scripts/refresh_and_gate.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_and_gate.ps1), because those wrappers simply invoke the shared orchestrator and mirror scripts in the current environment.

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

- MLB: `tools.oddsapi.fetch_daily_oddsapi_markets`
- NBA: `nba_betting.refresh_oddsapi_props_job`
- NHL: `nhl_betting.cli team-odds-collect` plus `props-collect`
- NFL: `nfl_compare/src/odds_api_client.py` plus `scripts/fetch_oddsapi_props.py`
- WNBA: `wnba_betting.refresh_oddsapi_props_job`
- NCAAB: `ncaab_model.cli fetch-odds-history --mode current`
- NCAAF: `fetch_2025_lines.py`

That keeps Syndicate aligned with the existing source models for pregame and live odds, while the mirror scripts now also copy the refreshed odds artifacts that those source refreshes produce.

For NCAAB specifically, `--mirror-only` now takes the hosted-friendly path through [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1) with `-UseExistingRawOutputs`, so the shared planner can rebuild the local API bundle from already mirrored raw outputs without requiring a sibling `NCAAB` checkout for that step.

Use `--dry-run` when you want the tool to resolve source roots, working directories, and commands without executing any refreshes. This is the safest way to validate a new schedule, a narrowed sport list, or a deployment environment before turning the job loose.

If a source repo is not checked out as a sibling of Syndicate, set a per-sport absolute path override before running the tool:

```powershell
$env:SYNDICATE_SOURCE_ROOT_MLB = 'D:\repos\MLB-BettingV2'
$env:SYNDICATE_SOURCE_ROOT_NBA = 'D:\repos\NBA-Betting'
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase live --sports mlb,nba --skip-mirror --dry-run --json
```

Supported override variables follow the same pattern: `SYNDICATE_SOURCE_ROOT_MLB`, `SYNDICATE_SOURCE_ROOT_NBA`, `SYNDICATE_SOURCE_ROOT_NHL`, `SYNDICATE_SOURCE_ROOT_NFL`, `SYNDICATE_SOURCE_ROOT_WNBA`, `SYNDICATE_SOURCE_ROOT_NCAAB`, and `SYNDICATE_SOURCE_ROOT_NCAAF`.

Those variables are also respected when you run the per-sport mirror scripts directly, for example [scripts/refresh_mlb_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_mlb_source_mirror.ps1) or [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1), so path overrides stay consistent across the whole refresh pipeline.

If the goal is a self-refreshing Render deployment instead of a read-only site backed by prebuilt mirrors, see [RENDER_SELF_HOST_REFACTOR_PLAN.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_REFACTOR_PLAN.md). That plan documents the remaining multi-repo refresh dependencies and the exact refactors needed before Syndicate can refresh itself without sibling checkouts.

Each unattended run now writes a timestamped artifact bundle under [reports](c:/Users/mostg/OneDrive/Coding/Syndicate/reports) by default. That bundle includes the per-sport mirror refresh outputs, the gate console output, and persisted `migration_gate_report.json` plus `migration_gate_report.txt` files. Use `-ArtifactsDir` on [scripts/refresh_and_gate.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_and_gate.ps1) or `--write-dir` on [scripts/migration_gate.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/migration_gate.py) if you want those reports written somewhere else.

The refresh wrapper now also publishes a stable latest-status manifest at [reports/refresh_status/latest/refresh_status_latest.json](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/refresh_status/latest/refresh_status_latest.json). That file points at the last `refresh_and_gate` artifact bundle and is the durable read target for admin/status tooling.

## Ops Status API

Syndicate now exposes two protected read-only ops endpoints for the shared odds refresh workflow:

```text
GET /api/ops/odds-refresh/status
GET /api/ops/odds-refresh/plan?date=2026-05-18&sports=mlb,nba&phase=live&skip_mirror=1
```

Set `ADMIN_TOKEN` (or `SYNDICATE_ADMIN_TOKEN`) in the environment, then pass it as either `Authorization: Bearer <token>`, `X-Admin-Token: <token>`, or `?admin_token=<token>`. The `status` endpoint reads the stable latest manifests under [reports/refresh_status](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/refresh_status) and [reports/daily_update/latest](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/daily_update/latest); the `plan` endpoint resolves the dry-run command plan without executing any source refreshes.

## Daily Update

To run a scheduled-ready global daily update that refreshes mirrors, runs the migration gate, and snapshots module status against the MLB reference contract:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1 -Date 2026-05-18
powershell -ExecutionPolicy Bypass -File .\scripts\daily_update.ps1 -Date 2026-05-18 -BaseUrl http://127.0.0.1:5000 -Json
```

This daily update writes a timestamped run under [reports/daily_update](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/daily_update), keeps a rolling latest manifest under [reports/daily_update/latest](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/daily_update/latest), emits `module_tracker_snapshot.json`, and now publishes `module_tracker_gap_report.txt` so each run shows the highest-leverage MLB parity gaps and a ranked module backlog alongside migration health.

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

To refresh Syndicate's local MLB validation mirror from the sibling MLB repo for a specific date:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_mlb_source_mirror.ps1 -Date 2026-05-15
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_mlb_source_mirror.ps1 -Date 2026-05-15 -UseExistingMirrorArtifacts
```

The script copies the main live-lens report and JSONL, live prop registry files, daily snapshot and sim folders, archived market refresh history, and archived StatsAPI live feed files into [data/mlb_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/mlb_source).

MLB now supports the same two mirror modes as the in-season board modules. The default run still copies fresh artifacts from the sibling MLB repo when that checkout is available. The `-UseExistingMirrorArtifacts` switch skips the sibling repo requirement and rewrites the MLB mirror manifest from the already mirrored files under [data/mlb_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/mlb_source). That gives the shared ingest path a hosted-safe local mirror mode for the reference module without changing the default source-backed refresh flow.

Each run also writes [data/mlb_source/manifests/mirror_refresh_latest.json](c:/Users/mostg/OneDrive/Coding/Syndicate/data/mlb_source/manifests/mirror_refresh_latest.json), and the migration gate now validates that manifest for the core mirrored MLB artifact families: daily summary, ladders, top props, ops, snapshots, sims, and season eval payloads.

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
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_ncaab_source_mirror.ps1 -Date 2026-04-06 -UseExistingRawOutputs
```

These scripts populate [data/nba_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/nba_source), [data/nhl_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/nhl_source), and [data/wnba_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/wnba_source) with the date-scoped processed artifacts that Syndicate already reads for cards, archive, picks, props, and sim-backed detail lanes.

NBA now supports the same two mirror modes. The default run still copies fresh artifacts from the sibling NBA repo when that checkout is available. The `-UseExistingMirrorArtifacts` switch skips the sibling repo requirement and rewrites the NBA mirror manifest from the already mirrored files under [data/nba_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/nba_source). That gives the shared ingest path a hosted-safe local mirror mode without changing the default source-backed refresh flow.

NHL now supports two mirror modes as well. The default run still copies fresh artifacts from the sibling NHL repo when that checkout is available. The `-UseExistingMirrorArtifacts` switch skips the sibling repo requirement and rewrites the NHL mirror manifest from the already mirrored files under [data/nhl_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/nhl_source). That gives the shared ingest path a hosted-safe local mirror mode without changing the default source-backed refresh flow.

WNBA now supports the same two mirror modes. The default run still copies fresh artifacts from the sibling WNBA repo when that checkout is available. The `-UseExistingMirrorArtifacts` switch skips the sibling repo requirement and rewrites the WNBA mirror manifest from the already mirrored files under [data/wnba_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/wnba_source). That gives the shared ingest path a hosted-safe local mirror mode without changing the default source-backed refresh flow.

NCAAB now supports two mirror modes. The default source-backed run still copies fresh artifacts from the sibling NCAAB repo when that checkout is available. The `-UseExistingRawOutputs` switch skips the sibling repo requirement and rebuilds `data/ncaab_source/api` directly from the already mirrored bundle under [data/ncaab_source/raw_outputs](c:/Users/mostg/OneDrive/Coding/Syndicate/data/ncaab_source/raw_outputs). That raw-only mode is the new hosted-friendly boundary for local API regeneration and Render-style rebuilds.

The source-backed NCAAB raw mirror contract is now intentionally narrow. Syndicate only mirrors the files currently needed to regenerate the local API bundle: `live_lens_tuning.json` plus `predictions_<date>.csv`, `predictions_unified_enriched_<date>.csv`, and `live_features_<date>.csv`.

`predictions_<date>.csv` is intentionally still part of that contract. The local settled-results export uses its `pred_total` and `pred_margin` values, while `predictions_unified_enriched_<date>.csv` supplies display and market metadata. Those two files are not interchangeable in the current raw-output lane.

## Next implementation steps

1. Keep NFL stable as the next module-family completion candidate, and only reopen its weekly snapshot family if a focused payload or view audit exposes a real artifact-backed gap.
2. Keep tightening NBA, NHL, and WNBA around the MLB public contract while preserving source parity where those sports have denser source-specific pages.
3. Keep tightening NCAAB's historical lane now that season review, a historical betting-card board, and the results archive are in place, and keep hardening shared helpers only where real consumers already exist.
4. Keep MLB stable as the reference feature module, and only extract helpers after multiple real consumers prove the contract.
5. Leave NCAAF stable as an artifact-backed weekly module until the live source workflow is populated again.

## How We Call A Module Done

For the current migration phase, a module is only considered complete when:

1. Its hub launches the real source-backed workflow rather than a placeholder route.
2. Season, week, or date identity stays intact across launchers, cards, drill-ins, ranked boards, and archive lanes.
3. The active surfaces are covered by the focused regression suite.
4. The home tracker and docs describe the same visible surfaces the module actually ships.

MLB now meets the current phase-1 complete standard. NFL is now the nearest near-complete module-family candidate, and the current weekly snapshot family is coherent through cards, drill-ins, grouped picks, betting-card navigation, explicit missing-week empty states, and source-style picks payload aliases.