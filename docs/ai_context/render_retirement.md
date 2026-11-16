# Render retirement — what was removed, where it went, and what replaced it

`[2026-11-15, lane render-retirement, todo #766]`

Render billing-suspended all three Syndicate services on 2026-09-30 06:37:51Z.
Production has run on the local WSL fleet since then (`scripts/local_production.py`,
`http://127.0.0.1:10000`, runbook `docs/ai_context/local_production_runbook.md`) and has
traded live money since 2026-10-19. On 2026-11-15 the user said: "we shouldnt be using
render for anything anymore", then "render shouldnt be needed".

**Nothing in this repo needs Render any more.** This file lists every operator tool that
called the Render API and was deleted, the commit that last held it (to read it:
`git show <sha>:scripts/<name>.py`), and what to use on the fleet instead.

## Deleted scripts (they called `api.render.com` and had no fleet path)

| script | what it did | last commit | on the fleet, use |
|---|---|---|---|
| `render_deploy.py` | triggered a Render deploy | `ab43454d8` | an exact-SHA `git merge --ff-only <sha>` of `~/Syndicate`, then `local_production.py reload-web` / a role TERM / a drained `down`+`up` (CLAUDE.md "Production is the WSL fleet") |
| `render_env_set.py` | set one env var on one Render service | `5357d52a2` | edit `~/syndicate-prod/local_production.env` (`ROLE__KEY` for one role), then a drained full `down`/`up` |
| `render_events.py` | read Render service events (kills, deploys, restarts) | `3e0cb05fb` | `local_production.py status` (restarts, loaded commit) and the supervisor's `exited code=` lines in `~/syndicate-prod/logs/` |
| `snapshot_render_env.py` | dated env snapshots of each Render service | `66b668952` | `~/syndicate-prod/render_env/<role>.json` is the fleet's own copy (taken once, 2026-10-01). `local_production.py import-render-env`, which called this, was removed too |
| `oom_band_report.py` | refresh-worker OOM signature from Render events + logs | `c911d0219` | `scripts/render_logs.py` (fleet logs by default) on `CONTAINER_MEMORY` / `ALL_PROCESS_MEMORY` lines; `memory_observability` |
| `slate_band_anon_report.py` | live-slate anon-memory band from Render events + logs | `e7a915ebf` | same as above |
| `ratchet_sample.py` | sampled refresh-worker memory via Render metrics/logs | `5536c4a8b` | same as above |
| `check_worker_memory_gate.py` | Render memory gate and deploy-window criteria | `48a0eb5dd` | same as above; deploy windows come from `deploy_preflight.py` (fleet by default) |
| `bandwidth_tripwire.py` | caught Render bandwidth spikes while logs existed | `a12161493` | nothing: the fleet has no metered egress |
| `controlled_transfer_probe.py` | sent web known bytes to read Render's bandwidth meter | `f444048ae` | nothing (Render billing study) |
| `controlled_transfer_read.py` | scored that transfer against Render's meter | `ba6383b99` | nothing |
| `controlled_transfer_arm2_watch.py` | armed the second controlled transfer on a live spike | `e080f97ce` | nothing |
| `score_arm_a_gate.py` | scored arm 2's fire gate (imported the watcher above) | `2b72946e3` | nothing |
| `render_bandwidth_report.py` | attributed Render bandwidth to services and paths | `e12b024a5` | nothing |
| `audit_blueprint_drift.py` | what a `render.yaml` push would do to the live Render env | `2d3aadbf7` | nothing: `render.yaml` value edits are inert on the fleet (learnings 2026-11-08) |
| `blueprint_sync_preview.py` | what a Render blueprint sync would write | `70e60b55c` | nothing (same reason) |
| `build_consolidated_graft.py` | built off-main deploy grafts per Render service | `8aedaeafd` | nothing: deploys are exact SHAs on `main` |
| `one_shot_restore_web_access_log.py` | one-off: set web's `GUNICORN_CMD_ARGS` on Render | `00e55f9a5` | nothing |
| `ring_cost_ab.py` | A/B of the diagnostic-ring cut on Render refresh-worker | `41000ce68` | nothing |
| `verify_nfl_autorun_obligations.py` | closed two 2026-08-13 NFL deploy obligations from Render logs | `06f5fa7f2` | nothing (obligations closed) |
| `render_cron_enqueue_refresh.py` | Render cron entrypoint that POSTed a refresh enqueue | `dba5b9951` | the fleet supervisor's `SCHEDULED_JOBS` (`local_production.py`) |

Their tests went with them: `test_bandwidth_tripwire.py`, `test_controlled_transfer_{arm2_watch,probe,read}.py`,
`test_ratchet_sample.py`, `test_render_events.py`, `test_snapshot_render_env.py`,
`test_render_cron_enqueue_refresh.py`.

Before deletion each was checked for importers (code search), for references in OPEN
lanes, skills, slash commands, agents and hooks, in the 49 ENABLED Claude scheduled tasks
and in the Windows Task Scheduler (2026-11-15). None was referenced by anything live.
`score_arm_a_gate.py` imported `controlled_transfer_arm2_watch.py` and went with it.

## Kept, Render path removed or repointed

See the lane's findings, `.syndicate/findings_2026-11-15_render_retirement.md`, for the
file-by-file list (fleet log, commit and env readers replacing the Render API calls, and
every `onrender.com` fallback repointed at `http://127.0.0.1:10000`).

## What still says "Render", and why that is not a dependency

- **`RENDER_*` env markers.** The fleet sets `RENDER=true`, `RENDER_SERVICE_NAME` / `_ID`,
  `RENDER_INSTANCE_ID` and `RENDER_GIT_COMMIT` on purpose, because code branches on them
  (CLAUDE.md). They are names, not calls: nothing reaches Render through them.
- **`render.yaml`.** `local_production.py` still reads it as the lowest env layer and for
  each role's start command. Pushing it may still fire `blueprint_sync` against the
  suspended services, so it is left untouched (todo #766 D3).
- **`.claude/hooks/deploy-guard.py`** keeps its rules that BLOCK a Render deploy (a POST
  to the deploys endpoint). Those protect against using Render; they do not need it.
- **`render_logs.py`** keeps its name (about 50 references): it reads the fleet's own logs.
