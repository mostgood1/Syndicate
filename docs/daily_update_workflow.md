# Daily Update GitHub Actions Workflow

This guide documents the current GitHub Actions daily update behavior end to end so it can be used as the operational contract while sport simulation engines are improved.

## What the workflow is responsible for

The workflow is the scheduled and manually-triggered entrypoint for the daily update. It does three things:

1. Resolve the runtime parameters for a specific daily run.
2. Execute the in-season daily-update wrapper and the unified runner.
3. Commit and push only the owned pipeline outputs that the run produced.

The workflow does not compute sports logic itself. It only orchestrates the run, validates the contract, and publishes the resulting artifacts.

## Trigger surface

The workflow currently runs on:

- A daily schedule at 06:00 UTC.
- Manual `workflow_dispatch` runs.

Manual runs accept these inputs:

- `date`: the ISO date to run, or blank to use the current date.
- `base_url`: an optional base URL passed through to the daily-update script.
- `event_sim_force_window_minutes`: the event-simulation force window, defaulting to `30`.

## Runtime environment

The job runs on `windows-latest` and sets up Python 3.11. It then installs `requirements.txt` before any workflow contract checks or daily-update execution.

The workflow also captures the Python executable path into `PYTHON_PATH` so downstream PowerShell scripts can invoke the same interpreter consistently.

## Execution order

The job currently runs in this order:

1. Check out the repository with full history.
2. Set up Python 3.11.
3. Print runtime diagnostics for Git and Python.
4. Install Python dependencies.
5. Capture the resolved Python executable path.
6. Resolve the run date, base URL, and event simulation force window.
7. Run the archive smoke test.
8. Run the active-sport migration gate regression.
9. Run the daily-update and WNBA contract regression suite.
10. Run `scripts/daily_update_in_season.ps1`.
11. Stage, commit, rebase, and push owned pipeline outputs.
12. Upload `daily-update.log` as a workflow artifact.

That order matters. The workflow validates the control-plane contract before it runs the daily pipeline, which keeps a broken orchestration change from silently publishing incorrect artifacts.

## Contract regression slice

The dedicated regression step is the guardrail for the workflow contract itself. It currently covers:

- the root wrapper that delegates to the in-season controller,
- the workflow file structure and staged-output commit rule,
- the odds and event-simulation passthrough surface,
- the unified daily-update run-plan and run-state contract,
- the WNBA source-card payload shape,
- the shared simulation adapter contract, and
- the shared game-board simulation contract.

This step exists so the workflow can keep serving as the stable runtime entrypoint while sport engines evolve underneath it.

## In-season wrapper contract

The workflow calls `scripts/daily_update_in_season.ps1`, which is the workflow-facing wrapper around the unified runner.

The workflow always passes:

- `-RefreshOdds`
- `-OddsPhase all`
- `-OddsSports all`
- `-OddsRegions us`
- `-SkipGitPush`
- `-EventSimForceWindowMinutes <resolved value>`

If `base_url` is provided, it is forwarded too.

The wrapper then passes the selected switches into `scripts/daily_update.ps1` and mirrors source artifacts for active sports after the run.

## Skip and selection behavior

The wrapper and unified runner honor the following key controls:

- `-SkipTests` and `-RunGateTests` are mutually exclusive.
- `-SkipSmoke` and `-RunGateSmoke` are mutually exclusive.
- `-SkipSourceUpdates` skips source refresh work.
- `-SkipRefreshGate` skips the refresh or migration gate slice.
- `-SkipGitPush` prevents the runner from publishing directly, which is how the workflow retains control of the final commit and push.
- `-DryRun` prints the command plan without executing the run.

The in-season wrapper also decides which sports to skip based on date, season activity, no-slate checks, and `-Force*` overrides.

## Unified runner behavior

`scripts/unified_daily_update.ps1` is the orchestration controller.

It is responsible for:

- planning the run,
- writing the run directory and `latest` directory,
- recording run-state, checkpoints, and traces,
- evaluating stage decisions,
- deciding whether artifact generation should occur,
- deciding whether publish should occur, and
- persisting the final daily-update outputs.

The important point for engine work is that the runner is now state-aware. The workflow is not just launching a script; it is driving a run plan that produces canonical latest artifacts.

## Stage contract

The unified runner currently tracks these stages:

- `source_update`
- `sim_execution`
- `event_sim_execution`
- `refresh_gate`
- `artifact_generation`
- `manifest_generation`
- `git_publish`

The manifest and latest run-state artifacts expose the current stage, completed stages, failed stage, replay context, and stage decisions.

## Artifact contract

The workflow-owned run produces both run-scoped and latest-scoped artifacts under `reports/daily_update`.

The canonical cross-sport simulation reference now lives in the daily-update simulation contract artifact. That contract is the preferred source of truth for MLB, NBA, WNBA, NHL, NFL, NCAAF, and NCAAB when you need to compare which source mode, freshness state, source paths, and advanced per-sport inputs the daily run actually used.

Run-scoped artifacts live under `reports/daily_update/<date>/<stamp>/` and include:

- `unified_daily_update_run.json`
- `unified_daily_update_checkpoint.json`
- `unified_daily_update_run_state.json`
- `unified_daily_update_run_trace.json`

Latest-scoped artifacts live under `reports/daily_update/latest/` and include:

- `unified_daily_update_latest.json`
- `unified_daily_update_latest_checkpoint.json`
- `unified_daily_update_latest_run_state.json`
- `unified_daily_update_latest_run_trace.json`
- `unified_daily_update_latest_simulation_contract.json`

The simulation contract now also exposes `advanced_by_sport`, which preserves the structured page and game inputs for each sport inside the canonical latest artifact. The run-state and run-trace artifacts carry the matching contract path, sport count, and advanced-by-sport reference so the control plane can be audited without reopening the board route.

The workflow also uploads `daily-update.log` as a GitHub Actions artifact so a run can be inspected after completion.

## Publish contract

The workflow owns the final Git publish step.

It stages only the owned pipeline output roots that the run produced, then verifies that staged files include artifact trees before committing.

The current publish roots include:

- `data/*_source/source_artifacts`
- `data/*_source/manifests`
- `reports/intelligence`
- `reports/daily_update/latest`
- `reports/refresh_status/latest`
- `reports/odds_control_plane`

The publish step intentionally fails if no staged artifact tree is present. That prevents an empty or malformed run from being treated as a successful update.

## What this means for sport-engine work

Treat this workflow as the contract layer above the sport engines.

When improving a sport simulation engine, the key questions are:

1. Does the daily-update run plan decide the right stage work for that sport?
2. Does the sport produce richer artifacts before runtime needs them?
3. Do the latest run-state and trace files show the expected stage decisions and outputs?
4. Does the workflow still stage and publish the correct source_artifacts and manifest roots?

For current engine work, WNBA is the clearest example: the default source cards path now preserves richer sim payload fields, so the workflow documentation should be read alongside the WNBA artifact contract.

## Practical validation checklist

Use this checklist when you change daily-update logic or a sport engine:

1. Run the workflow contract tests.
2. Check the daily-update latest run-state and trace artifacts.
3. Verify the sport-specific source-artifact roots were produced.
4. Confirm the commit step stages owned outputs, not just the script output.
5. Confirm the workflow still passes the right refresh and odds switches into the in-season wrapper.

## Related docs

- [Daily update control plane](daily_update_control_plane.md)
- [Daily pipeline notes](ai_context/daily_pipeline.md)
- [Simulation system index](ai_context/simulation_system.md)