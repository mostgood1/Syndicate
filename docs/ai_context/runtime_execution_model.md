# Runtime Execution Model (Render vs Workers)

## Core Rule

Render should perform **no heavy computation**.

All simulation, aggregation, and data processing should be handled by:
- GitHub Actions (scheduled jobs)
- background workers
- offline pipelines

Render is only responsible for:
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

### Runtime Layer (Render)

Runs:
- route handlers
- lightweight adapters
- UI rendering

Consumes:
- precomputed artifacts
- live-lens snapshots (if available)

Must NOT:
- run expensive simulations
- rebuild full game contexts from scratch
- recompute probabilities heavily

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

Render should:
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

If Render is used for compute:
- performance degrades
- results become inconsistent
- debugging becomes non-deterministic
- runtime vs pipeline outputs diverge

---

## Goal State

Daily pipeline produces:
→ full simulation_contract
→ fully enriched inputs + outputs

Render consumes:
→ simulation_contract only
→ no recomputation required
