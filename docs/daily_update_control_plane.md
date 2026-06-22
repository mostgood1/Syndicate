# Daily Update Control Plane

This document maps the current daily update path end to end and summarizes the remaining parity gaps. For the operational GitHub Actions contract, see [Daily update GitHub Actions workflow](daily_update_workflow.md).

## Entry points

- [`.github/workflows/daily-update.yml`](../.github/workflows/daily-update.yml) is the scheduled and manual GitHub Action.
- [`scripts/daily_update.ps1`](../scripts/daily_update.ps1) is the legacy wrapper that launches the unified runner and then runs prediction reconciliation.
- [`scripts/daily_update_in_season.ps1`](../scripts/daily_update_in_season.ps1) is the workflow-facing in-season wrapper that passes the current refresh and skip flags into the unified runner.
- [`scripts/unified_daily_update.ps1`](../scripts/unified_daily_update.ps1) is the current orchestration controller for planning, run-state, simulation decisions, artifact generation, and publish.

## End-to-end flow

1. GitHub Actions triggers on schedule or workflow dispatch.
2. The workflow checks out the repo, installs Python dependencies, resolves the run date, base URL, and event simulation force window, then runs the smoke, gate, and daily-update/WNBA contract regression checks.
3. The workflow invokes `scripts/daily_update_in_season.ps1` with `-RefreshOdds`, all odds sports, and `-SkipGitPush` so the workflow step owns the final commit and push.
4. `scripts/daily_update_in_season.ps1` forwards the selected switches into `scripts/unified_daily_update.ps1`.
5. `scripts/unified_daily_update.ps1` creates the timestamped run directory under `reports/daily_update/<date>/<stamp>/` and the rolling latest directory under `reports/daily_update/latest/`.
6. The unified runner builds a run plan, writes run-state and checkpoint artifacts, evaluates stage decisions, and executes the stage sequence.
7. The workflow stages any owned outputs, verifies that artifact roots were produced, commits them, rebases onto the latest remote branch, and pushes the result.

## Stage contract

The unified runner exposes stage decisions in the manifest and run-state artifacts. The current stage set is:

| Stage | Purpose | Notes |
| --- | --- | --- |
| `source_update` | Run the per-sport source or mirror refresh work | Planned per sport and recorded in the manifest |
| `sim_execution` | Decide whether the main simulation branch should run | Driven by run plan and freshness inputs |
| `event_sim_execution` | Decide whether event-level incremental simulation should run | Uses input fingerprints and event freshness logic |
| `refresh_gate` | Run the refresh or migration gate slice | Can be skipped explicitly |
| `artifact_generation` | Publish the artifact updates for the run | Skips on no-op paths when appropriate |
| `manifest_generation` | Write the manifest, checkpoint, run-state, and trace artifacts | Always tracked through the latest directory |
| `git_publish` | Stage, commit, rebase, and push owned outputs | Skipped when `-SkipGitPush` is set |

The manifest and latest artifacts expose the current stage, completed stages, failed stage, replay context, and stage decisions so the run can be resumed and audited.

## Artifacts written

The unified runner writes both run-scoped and latest-scoped artifacts:

- `reports/daily_update/<date>/<stamp>/unified_daily_update_run.json`
- `reports/daily_update/<date>/<stamp>/unified_daily_update_checkpoint.json`
- `reports/daily_update/<date>/<stamp>/unified_daily_update_run_state.json`
- `reports/daily_update/<date>/<stamp>/unified_daily_update_run_trace.json`
- `reports/daily_update/latest/unified_daily_update_latest.json`
- `reports/daily_update/latest/unified_daily_update_latest_checkpoint.json`
- `reports/daily_update/latest/unified_daily_update_latest_run_state.json`
- `reports/daily_update/latest/unified_daily_update_latest_run_trace.json`
- `reports/daily_update/latest/unified_daily_update_latest_simulation_contract.json`

The workflow also publishes the daily update log as a GitHub Actions artifact.

The latest simulation contract artifact is the canonical cross-sport reference for daily-update debugging. When you are reasoning about MLB or WNBA sim usage gaps, compare against that file first before trusting route-level fallbacks or older stage snapshots. The latest run-state and run-trace files now carry the same contract path and the structured `advanced_by_sport` payload reference so you can audit the normalized inputs without leaving the control plane.

## Current sport contract shape

The daily update system is not fully uniform yet. The current contract looks like this:

- MLB, NBA, WNBA, and NHL are the strongest local mirror-first contracts.
- WNBA source cards now preserve the merged sim artifact fields that matter for runtime use, including `sim.players`, `sim.quarters`, and `sim.pregame_context`, so the default board no longer depends on the separate sim-detail endpoint for player-level context.
- MLB now preserves the structured advanced simulation payload in the normalized contract, including page-level slate inputs and per-game signals such as lineup health, HR targets, live-lens rows, run projections, and first-inning markers.
- NFL and NCAAF have local mirror support, but their published contract is narrower than the older mirror-first sports.
- NCAAB still depends on source-app subprocess/API behavior and does not yet have the same stable local artifact contract.
- The publish path still relies on sport-aware allowlists for force-published artifact roots, so new files can be missed until the allowlist is updated.

## Gaps that remain

1. One canonical per-sport artifact contract is still missing for the full all-sports workflow.
2. NCAAB still needs a stable local artifact mirror contract so it can behave like the other sports.
3. The force-publish allowlist is still partly hardcoded, which makes parity gaps easy to reintroduce.
4. The daily update root is still more of a bridge than a full state-aware execution controller, even though it already carries run-state, checkpoint, and trace scaffolding.
5. The latest artifact contract has two generations in the tree, so the unified latest files must be treated as canonical when both exist.
6. Cross-sport intelligence and advanced-input paths still depend on exact artifact paths in a few places, so broad parity needs explicit validation before a sport can be treated as complete.
7. WNBA publish parity should be checked against the latest run-state and trace artifacts, because the default board now consumes the richer merged sim payload and stale control-plane snapshots can hide that improvement.

## Operational notes

- Use `-SkipGitPush` for local validation when you want the full run without creating a commit.
- Use `-SkipTests`, `-SkipSmoke`, `-SkipRefreshGate`, and the per-sport `-Skip*` switches to narrow the run.
- Prefer `reports/daily_update/latest/unified_daily_update_latest.json` and its companion latest state files over the older legacy latest manifest when comparing recent runs.

## Related documentation

- [Unified daily-update audit](../reports/unified_daily_update_audit_2026-05-18.md)
- [Execution backlog](syndicate_world_class_execution_backlog.md)
- [Implementation plan](syndicate_world_class_implementation_plan.md)

