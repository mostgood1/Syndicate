# Runtime Infrastructure (Render)

## Hosting
Syndicate is deployed on Render (render.com)

---

## Execution Model

### GitHub Actions (Daily Pipeline)
- runs scheduled jobs
- generates artifacts (daily_summary, sim outputs, recommendations)
- writes data to storage used at runtime

### Render (Runtime)
- serves user requests through a stateless web service
- reads repo-local artifacts for read-only responses
- may supplement with live data
- does NOT run full simulation for all routes
- delegates disk-backed writes and refresh jobs to workers

---

## Data Availability at Runtime

At request time, the system depends on:
- stored artifacts from daily pipeline or repo-local checked-in mirrors
- live-lens data (if available)
- cached or fallback data

If data is not produced in the daily pipeline:
→ it will not exist at runtime

If hosted refresh or write state is needed:
→ the worker-owned mounted disk and shared refresh-state backend handle it

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

- data mismatch between local and Render environments
- stale artifacts being used instead of live data
- simulation inputs differing between pipeline and runtime

---

## Debug Implication

When debugging:
- always verify whether the issue is:
  - pipeline-level (data not generated)
  - runtime-level (data not consumed correctly)
  - deployment-level (web/worker split or stale Render rollout)