# Production Runtime Notes

> `[2026-11-17]` The filename is historical. Production ran on Render until Render billing-suspended all three services on 2026-09-30; Render is retired. This note describes the fleet.

Production runs this repository's Flask application on the local WSL fleet: `scripts/local_production.py up` supervises web, refresh-worker, live-odds-worker and a local Redis on one shared disk, `~/syndicate-prod/data` (`SYNDICATE_DATA_ROOT`). Web serves `http://127.0.0.1:10000`. The fleet runs the commit its checkout `~/Syndicate` was fast-forwarded to (an exact-SHA `git merge --ff-only <sha>`), not whatever is on `main`; `/versionz` reports the commit web loaded. Each role's env is built at `up` from `scripts/fleet_role_spec.json` -> `~/syndicate-prod/fleet_env/<role>.json` -> `~/syndicate-prod/local_production.env` -> forced keys; `render.yaml` is read by nothing. Runbook: `docs/ai_context/local_production_runbook.md`.

Agent skills do not run at request time.
Skills are only development-time guidance for Copilot.

Therefore:
- all runtime behavior must be implemented in application code
- endpoint correctness must come from the Flask route / pipeline / models
- changing SKILL.md alone does not change runtime behavior
