# Runtime Infrastructure (the local fleet)

## Hosting `[2026-11-17]`
Production is the local WSL "fleet" on the operator's Windows machine, not Render. Render
billing-suspended all three services on 2026-09-30 and is retired
(`docs/ai_context/render_retirement.md`). Runbook: `docs/ai_context/local_production_runbook.md`.

- `scripts/local_production.py up` supervises web, refresh-worker, live-odds-worker and a local
  Redis on ONE shared disk, `~/syndicate-prod/data` (`SYNDICATE_DATA_ROOT`).
- Production reads: `http://127.0.0.1:10000` (`scripts/_base_url.py` resolves the URL and the
  admin token). Logs: `~/syndicate-prod/logs/<role>.log`, read with `py -3 scripts/fleet_logs.py`.
- Deploys: pushing to `main` ships nothing. A deploy is an exact-SHA `git merge --ff-only <sha>` in
  `~/Syndicate`, then `local_production.py reload-web` (web), a role TERM (a worker) or a drained
  full `down` + `up` (env change), each behind `scripts/deploy_claim.py` and a CLEAR
  `scripts/deploy_preflight.py`.
- Env: `scripts/fleet_role_spec.json` → `~/syndicate-prod/fleet_env/<role>.json` →
  `~/syndicate-prod/local_production.env` → forced keys. `render.yaml` is not read.

---

## Execution Model

### Workers and scheduled jobs (pipeline)
- refresh-worker and live-odds-worker run the loops; the supervisor runs `SCHEDULED_JOBS`
  (the former Render dashboard crons, `data-backup`, and fleet-only jobs). GitHub Actions no
  longer generate artifacts (`daily-update.yml` is manual-only).
- generates artifacts (daily_summary, sim outputs, recommendations)
- writes data to the shared data root used at runtime

### Web (Runtime)
- serves user requests through a stateless web service
- reads the artifacts the workers wrote on the shared data root
- may supplement with live data
- does NOT run full simulation for all routes
- delegates disk-backed writes and refresh jobs to workers

---

## Data Availability at Runtime

At request time, the system depends on:
- stored artifacts the workers wrote (a fresh data root is seeded once from the checked-in mirror)
- live-lens data (if available)
- cached or fallback data

If data is not produced in the daily pipeline:
→ it will not exist at runtime

If hosted refresh or write state is needed:
→ the workers write the shared data root, and the shared refresh-state backend (the fleet's local
  Redis) holds mutable state

---

## Simulation Behavior

- some simulation runs are precomputed (daily pipeline)
- some logic may run at request time (intelligence layer)
- not all routes call the simulation engine directly

---

## Key Constraint

Runtime is primarily a **consumer of data**, not a full compute layer.

---

## Risks

- data mismatch between the local checkout and production (the fleet's data root)
- stale artifacts being used instead of live data
- simulation inputs differing between pipeline and runtime

---

## Debug Implication

When debugging:
- always verify whether the issue is:
  - pipeline-level (data not generated)
  - runtime-level (data not consumed correctly)
  - deployment-level (web/worker split, or a role still running an older commit than the fleet
    checkout: `local_production.py status` flags it)