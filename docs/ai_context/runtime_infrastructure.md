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
- serves user requests
- loads artifacts produced by daily pipeline
- may supplement with live data
- typically does NOT run full simulation for all routes

---

## Data Availability at Runtime

At request time, the system depends on:
- stored artifacts from daily pipeline
- live-lens data (if available)
- cached or fallback data

If data is not produced in the daily pipeline:
→ it will not exist at runtime

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