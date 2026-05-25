# Render Self-Host Backlog

This backlog translates [RENDER_SELF_HOST_REFACTOR_PLAN.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_REFACTOR_PLAN.md) into an execution sequence. The goal is not to make Syndicate merely deployable on Render. The goal is to make it self-refreshing and operationally complete on Render without sibling source repos.

## Current hosted boundary

Today Syndicate is safe to run on Render as a read-only web app backed by mirrored artifacts already stored in this repo.

Today Syndicate is not yet safe to run on Render as a self-refreshing system because:

- [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) still resolves sibling repo roots and executes source-owned generation commands by default, even though all per-sport ingestion contracts can now target neutral artifact bundles.
- Deployment proof is still incomplete: the Render blueprint and docs need manual `SYNDICATE_ARTIFACT_ROOT_*` wiring per environment before hosted refreshes can actually ingest published bundles.
- The normal mirror bootstrap blockers are closed, but multiple sports still depend on source-owned generation jobs.

## Backlog status table

### Milestone and workstream status

| Area | Scope | Status | What is done | What is left |
| --- | --- | --- | --- | --- |
| Milestone 0 | Keep current hosted mode stable | In progress | Read-only Render mode is stable and the docs distinguish read-only hosting from self-refresh hosting. | Keep the status/planning surfaces accurate while the self-host cuts continue. |
| Workstream 1A | NCAAB exporter replacement | Completed | Normal NCAAB mirror refresh rebuilds the API bundle from mirrored raw outputs, and the fresh odds snapshot is now generated locally through Syndicate without the source CLI. | Keep the local raw-output lane stable and only reopen it if a broader NCAAB prediction-generation cut becomes necessary. |
| Workstream 1B | NBA live-state bootstrap removal | Completed | The normal NBA mirror path no longer boots the source Flask app or uses the old `/api/live_state` fallback. | NBA generation is still source-owned through the props refresh job. |
| Milestone 1 | Remove source-app bootstrapping blockers | Completed | The normal mirror bootstrap blockers are closed for NCAAB and NBA, and NCAAB no longer depends on the source CLI for fresh odds snapshots. | No further normal-path source-app bootstrap blockers remain; keep the completed seams stable. |
| Milestone 2 | Split refresh generation from artifact ingestion | In progress | Every current sport now has a hosted-safe ingest contract, and NCAAB, NCAAF, and NHL now have normal-path Syndicate-owned generation for their current odds artifact lanes. | Replace the remaining source-owned generation jobs and finish real hosted publication/wiring of those bundles. |
| Milestone 3 | Move runtime and state out of the web process | In progress | The worker contract and the shared refresh-state store exist, including Key Value-backed status/log storage. | Prove the hosted worker/state wiring end to end and keep the ops surfaces reading only from durable state. |
| Milestone 4 | Expand the Render deployment model | In progress | The blueprint and docs now describe a web service, worker, and shared state backend. | Finish the self-refresh deployment proof, environment wiring, and hosted smoke checklist. |
| Acceptance checklist | Final self-host exit criteria | In progress | Normal mirror bootstrap removal, worker/state abstraction, and hosted-safe ingest contracts are largely in place. | Remove normal sibling-repo refresh dependencies, keep refreshes out of the web process, and finish the full hosted architecture proof. |

### Sport ownership status

| Sport | Normal ingest status | Generation status | Backlog coverage | Next migration gap |
| --- | --- | --- | --- | --- |
| MLB | Hosted-safe via `artifact_bundle_or_existing_mirror` | Bundle-local generation in Syndicate for OddsAPI fetch, live-lens bootstrap, bundle materialization, snapshot/archive/meta handling, and existing-artifact reuse | Covered by Milestone 2 and the sport backlog after blockers | Keep the owned MLB bundle path stable; only copied daily/live/eval artifacts still come from the mirrored source data root. |
| NBA | Hosted-safe via `artifact_bundle_or_existing_mirror` | Source-owned generation through the source props refresh job, but the Syndicate runner now skips that job when the day's snapshot/predictions/edges/recommendations already exist and reuses those outputs directly | Covered by Workstream 1B, Milestone 2, and the recommended next-slice guidance | Replace the remaining NBA props refresh job path with a Syndicate-owned generator or a neutral publisher. |
| NHL | Hosted-safe via `artifact_bundle_or_existing_mirror` | Bundle-local generation in Syndicate for scoreboard, team odds, and props lines | Covered by Milestone 2 and the sport backlog after blockers | Keep the owned NHL odds bundle path stable; only the optional processed/live-lens backfill still benefits from a sibling source checkout. |
| NFL | Hosted-safe via `artifact_bundle_or_existing_mirror` | Bundle-local generation in Syndicate for team odds and player props lines | Covered by Milestone 2 and the sport backlog after blockers | Keep the owned NFL bundle path stable; only the copied weekly artifacts still come from the mirrored source data root. |
| WNBA | Hosted-safe via `artifact_bundle_or_existing_mirror` | Source-owned generation through the source props refresh job, but the Syndicate runner now skips that job when the day's snapshot/predictions/edges/recommendations already exist and reuses those outputs directly | Covered by Milestone 2 and the sport backlog after blockers | Replace the remaining WNBA props refresh job path with a Syndicate-owned generator or a neutral publisher. |
| NCAAB | Hosted-safe via `existing_raw_outputs` | Local raw-output generation and local mirror/export are now owned in Syndicate | Covered by Workstream 1A and Milestone 2 | Keep the owned raw-output lane stable and only reopen this sport if broader NCAAB generation must move into Syndicate. |
| NCAAF | Hosted-safe via `artifact_bundle_or_existing_mirror` | Bundle-local generation in Syndicate | Covered by Milestone 2 and the sport backlog after blockers | Keep the owned bundle path stable and only reopen it if the live workflow or publication path needs more owned generation. |

## Delivery strategy

Use four milestones in order:

1. Eliminate source-app bootstrapping.
2. Split refresh generation from artifact ingestion.
3. Move refresh runtime and state out of the web process.
4. Expand the Render deployment model after the hosted runtime boundary is clean.

The milestones below are ordered by dependency, not convenience.

## Milestone 0: Keep current hosted mode stable

Purpose:
Keep the current Render deployment usable while the self-host work is in progress.

Tasks:
- Leave [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) in single-web-service mode until the runtime split is ready.
- Keep [README.md](c:/Users/mostg/OneDrive/Coding/Syndicate/README.md) explicit that the current Render model is read-only and mirror-backed.
- Keep [syndicate/blueprints/ops.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/blueprints/ops.py) usable as a status and planning surface, even if full hosted refresh launch remains gated.

Exit criteria:
- The current Render deployment remains stable while the refactor proceeds.
- Docs distinguish clearly between read-only hosting and self-refresh hosting.

## Milestone 1: Remove source-app bootstrapping blockers

Purpose:
Continue stripping source-owned generation assumptions now that the normal mirror bootstrap blockers are closed.

### Workstream 1A: NCAAB exporter replacement

Current status:
- Completed. The normal NCAAB mirror path is now artifact-only by default.
- [scripts/export_ncaab_source_mirror.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/export_ncaab_source_mirror.py) rebuilds the local API bundle from mirrored raw outputs.
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1) keeps source-backed raw-output sync only behind the explicit manual switch `-RefreshRawOutputsFromSource`.
- [scripts/refresh_ncaab_odds_history.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_odds_history.py) now fetches The Odds API data directly inside Syndicate, so the normal source-mode refresh path no longer imports `ncaab_model` from a sibling checkout.

Owning files:
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1)
- [scripts/export_ncaab_source_mirror.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/export_ncaab_source_mirror.py)
- [syndicate/features/ncaab](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/ncaab)
- [data/ncaab_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/ncaab_source)

Outcome:
- Normal NCAAB mirror refresh no longer boots the source app.
- NCAAB API exports are rebuilt from mirrored artifacts only.
- Fresh NCAAB odds snapshots can now be regenerated locally through Syndicate without the source CLI.
- Focused regression coverage exists for the artifact-only export path and the explicit manual source-sync path.

Next NCAAB gap:
- The remaining NCAAB work is no longer about the normal odds-refresh path. Only the explicit compatibility switch `-RefreshRawOutputsFromSource` still reaches into a sibling checkout.

### Workstream 1B: NBA live-state bootstrap removal

Current status:
- Completed. [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1) no longer contains the source-app bootstrap helper or the `/api/live_state` fallback path.
- Focused regression coverage in [tests/test_nba_mirror_script.py](c:/Users/mostg/OneDrive/Coding/Syndicate/tests/test_nba_mirror_script.py) asserts that the bootstrap helper and source-app fallback hooks are absent.

Owning files:
- [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1)
- [data/nba_source](c:/Users/mostg/OneDrive/Coding/Syndicate/data/nba_source)
- [syndicate/features/nba](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/nba)

Outcome:
- Normal NBA mirror refresh no longer boots the source Flask app.
- NBA ingest now either consumes existing or published artifacts, or fails based on artifact availability rather than a hidden source-app fallback.

Next NBA gap:
- NBA still depends on the source-owned props refresh job for generation. The remaining work is generation ownership, not mirror bootstrap removal.

## Milestone 2: Split refresh generation from artifact ingestion

Purpose:
Break the current assumption that Syndicate refresh orchestration must run commands inside sibling source repos.

Owning files:
- [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py)
- [scripts/refresh_mlb_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_mlb_source_mirror.ps1)
- [scripts/refresh_nba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nba_source_mirror.ps1)
- [scripts/refresh_nhl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nhl_source_mirror.ps1)
- [scripts/refresh_nfl_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_nfl_source_mirror.ps1)
- [scripts/refresh_wnba_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_wnba_source_mirror.ps1)
- [scripts/refresh_ncaab_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaab_source_mirror.ps1)
- [scripts/refresh_ncaaf_source_mirror.ps1](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_ncaaf_source_mirror.ps1)

Tasks:
- Split the current planner in [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) into two explicit layers:
  - generation jobs
  - ingestion jobs
- Define one neutral ingest contract per sport. Each ingest contract should assume a stable artifact payload, not a sibling repo layout.
- Change the mirror scripts so `SourceRepo` is no longer the primary runtime assumption.
- Introduce one hosted-safe source of truth per sport:
  - Syndicate-owned job output, or
  - remote published artifacts, or
  - durable mounted data written by a separate worker.
- Keep a local compatibility wrapper only while the hosted-safe path is being phased in.

Current status:
- The planner now exposes a hosted-safe ingest contract for every current sport module.
- MLB, NBA, NHL, NFL, WNBA, and NCAAF mirror scripts all support `artifact_bundle_or_existing_mirror` via `SYNDICATE_ARTIFACT_ROOT_*` or `-UseExistingMirrorArtifacts`.
- NCAAB already supports the hosted-safe raw-output bundle path via `existing_raw_outputs`.
- NHL source mode now generates scoreboard, team-odds, and player-props artifacts locally through Syndicate, while source-root use is optional for compatibility-only processed/live-lens backfill.
- The remaining gap in this milestone is not neutral ingest shape; it is generation ownership for MLB, NBA, NFL, and WNBA plus actual hosted publication/wiring of those artifact bundles.

Exit criteria:
- Refresh planning can target hosted-safe generation or hosted-safe ingestion without assuming sibling repos.
- Mirror/import jobs operate on neutral artifact contracts instead of source repo directories.

## Milestone 3: Move runtime and state out of the web process

Purpose:
Make the ops dashboard a control plane and reader, not the parent process of refresh work.

Owning files:
- [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py)
- [syndicate/blueprints/ops.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/blueprints/ops.py)
- [reports/refresh_status](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/refresh_status)
- [reports/migration_runs](c:/Users/mostg/OneDrive/Coding/Syndicate/reports/migration_runs)

Tasks:
- Replace `subprocess.Popen`-driven detached job launching in [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) with a worker-oriented execution contract.
- Define a durable state location for:
  - latest refresh manifest
  - recent run history
  - stdout/stderr log payloads
  - latest daily-update summary
- Keep the state boundary independent from Render local disks. Render persistent disks are single-service mounts, so the final hosted state backend must be readable by both the web control plane and the worker without assuming a shared filesystem path.
- Make [syndicate/blueprints/ops.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/blueprints/ops.py) read job state through an abstraction layer instead of assuming repo-local reports.
- Preserve the current UI endpoint `/ops/odds-refresh` and JSON ops endpoints while swapping the backend state store.
- Add tests that simulate missing local `reports/` state but valid external or mounted state.

Current status:
- The worker-oriented execution contract is now in place via [scripts/run_queued_refresh_job.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_queued_refresh_job.py) and [scripts/run_refresh_worker.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/run_refresh_worker.py).
- The refresh-state abstraction now exists in [syndicate/features/shared/refresh_state_store.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/refresh_state_store.py) and supports both filesystem and Key Value-backed refresh status/log storage.
- The remaining hosted gap in this milestone is deployment wiring and proving the shared backend in a real hosted configuration, not the absence of a worker/read abstraction.

Exit criteria:
- The web service does not own long-running refresh subprocesses.
- Refresh state survives web restarts.
- Ops UI and JSON endpoints still work against durable hosted state.

## Milestone 4: Expand the Render deployment model

Purpose:
Only after the refresh and state boundaries are hosted-safe should the deployment blueprint grow beyond a single web service.

Owning files:
- [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml)
- [README.md](c:/Users/mostg/OneDrive/Coding/Syndicate/README.md)
- [RENDER_SELF_HOST_REFACTOR_PLAN.md](c:/Users/mostg/OneDrive/Coding/Syndicate/RENDER_SELF_HOST_REFACTOR_PLAN.md)

Tasks:
- Extend [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) to represent the hosted runtime model actually required:
  - web service
  - worker or job service
  - shared durable state dependency such as Render Key Value for refresh status, or another external store if that proves a better fit
- Document exact environment variables, mounted paths, and responsibilities per service in [README.md](c:/Users/mostg/OneDrive/Coding/Syndicate/README.md).
- Add a hosted smoke checklist that verifies:
  - the web app reads current status
  - refresh jobs can run outside the web process
  - latest status remains after restart
  - artifact imports remain visible to the public routes

Exit criteria:
- `render.yaml` represents the true hosted architecture instead of only the current read-only web service.
- The hosted deployment model is documented and reproducible.

## Sport backlog after the blockers

After Milestones 1 through 3 are complete, use this order for per-sport hosted ownership work:

1. MLB
Reason: live-lens and current-day board ownership are central to the reference module.

2. NFL
Reason: weekly artifact boundaries are clear, and the player-props leg is now local to Syndicate; the remaining gap is the team-odds fetcher.

3. WNBA
Reason: similar shape to NBA, but simpler once the shared props-refresh pattern is established.

4. NCAAF
Reason: smallest structurally, but lower product urgency than the active in-season modules.

## Acceptance checklist

Treat Render self-hosting as done only when all of the following are true:

- No normal refresh path requires `..\<source-repo>` lookup.
- No normal refresh path boots a source Flask app.
- [scripts/refresh_odds_sources.py](c:/Users/mostg/OneDrive/Coding/Syndicate/scripts/refresh_odds_sources.py) plans hosted-safe jobs or hosted-safe imports only.
- [syndicate/features/shared/ops_refresh.py](c:/Users/mostg/OneDrive/Coding/Syndicate/syndicate/features/shared/ops_refresh.py) no longer launches detached local subprocesses from the web-facing control path.
- Ops status and logs survive a web restart.
- [render.yaml](c:/Users/mostg/OneDrive/Coding/Syndicate/render.yaml) describes the actual hosted architecture required for self-refresh operation.

## Recommended next implementation slice

Start with the next source-owned generation job you want Syndicate to own directly.

The highest-leverage next code change is replacing one of the remaining source-owned generation commands with a Syndicate-owned job or a published artifact producer, with the NBA props refresh job as the clearest near-term candidate and MLB or NFL close behind.
