# Runtime Execution Model (Web vs Workers)

> `[2026-11-17]` This doc used to say "Render" for the web service. Production has been the
> local WSL fleet since 2026-09-30 (Render is retired; runbook
> `docs/ai_context/local_production_runbook.md`): `scripts/local_production.py up` runs web,
> refresh-worker, live-odds-worker and a local Redis on one shared disk, `~/syndicate-prod/data`.
> The rule itself is unchanged.

## Core Rule

The web service should perform **no heavy computation**.

All simulation, aggregation, and data processing should be handled by:
- scheduled jobs (the fleet supervisor's `SCHEDULED_JOBS` in `scripts/local_production.py`)
- background workers (refresh-worker, live-odds-worker)
- offline pipelines

The web service is only responsible for:
- reading precomputed artifacts
- hydrating UI responses
- minimal transformation for display

---

## Execution Split

### Background Layer (Workers / Daily Pipeline)

Runs:
- simulation engine (Monte Carlo)
- artifact generation (daily summaries, sim outputs)
- data enrichment and normalization
- evaluation and calibration updates

Produces:
- normalized simulation_contract artifacts
- per-sport advanced data blocks
- fully enriched game contexts

---

### Runtime Layer (Web)

Runs:
- route handlers
- lightweight adapters
- UI rendering

Consumes:
- precomputed artifacts, read from the shared data root the workers write
- live-lens snapshots (if available)

Must NOT:
- run expensive simulations
- rebuild full game contexts from scratch
- recompute probabilities heavily

Deployment shape:
- the web service is stateless
- the workers own disk-backed writes, refresh jobs, and mutable hosted state (shared state goes
  through the keyvalue store, the fleet's local Redis)

---

## Design Principle

All expensive computation should be done **ahead of time**, not per request.

Runtime logic should be:
- deterministic
- fast
- traceable to a stored artifact

---

## Simulation Rule

SimulationEngine should:
- run in background jobs
- produce outputs stored in artifacts

The web service should:
- display simulation outputs
- optionally trigger lightweight, scoped enrichments only when necessary

---

## Fallback Behavior

If data is missing at runtime:
- prefer degraded display (empty state)
- DO NOT recompute heavy logic
- DO NOT backfill via simulation on request

---

## Risk (if violated)

If the web service is used for compute:
- performance degrades
- results become inconsistent
- debugging becomes non-deterministic
- runtime vs pipeline outputs diverge

---

## Goal State

Daily pipeline produces:
→ full simulation_contract
→ fully enriched inputs + outputs

The web service consumes:
→ simulation_contract and the artifacts the workers wrote
→ no recomputation required on the web service
