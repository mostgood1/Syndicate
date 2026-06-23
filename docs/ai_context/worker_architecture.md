# Worker Architecture (Background Compute Layer)

## Core Principle

All heavy computation MUST run in background workers, not in Render.

Workers are responsible for generating and updating all artifacts used at runtime.

---

## Worker Responsibilities

Workers handle:

- simulation execution (Monte Carlo engine)
- artifact generation (daily summaries, sim outputs)
- data enrichment (live state merge, projections, odds)
- evaluation and calibration updates
- normalization into simulation_contract

---

## Worker Types

### 1. Scheduled Workers (GitHub Actions)
- run on a schedule (daily, hourly, etc.)
- generate baseline artifacts for each sport
- build initial simulation_contract outputs

### 2. Runtime Workers (Background Jobs)
- run asynchronously during runtime if needed
- triggered by:
  - missing data
  - stale artifacts
  - live updates
- update artifacts in storage, NOT response

---

## Execution Model

Workers write:

→ artifacts
→ simulation_contract
→ enriched game context

Render reads:

→ artifacts only

---

## Key Rule

Workers write → Render reads

There must be NO path where:
Render recomputes heavy logic synchronously

---

## Simulation Rule

SimulationEngine:
- runs in workers
- outputs are persisted
- results reused by runtime

Render:
- never runs full simulation
- only consumes outputs

---

## Data Flow

Raw Data
→ Worker
→ Simulation + enrichment
→ artifact (stored)
→ Render
→ UI / intelligence

---

## Freshness Model

Workers ensure:
- artifacts are up-to-date
- live updates are captured

Render:
- selects correct artifact version
- does not regenerate it

---

## Failure Handling

If data is missing:

Render:
- shows degraded UI

Workers:
- regenerate artifacts asynchronously

---

## Observability

Workers should emit:
- timestamps (last updated)
- source mode (live / artifact / fallback)
- run ID / job ID

---

## Risk if Violated

If computation leaks into Render:
- CPU spikes
- slow requests
- inconsistent results vs pipeline
- debugging becomes unreliable

---

## Goal State

Every request is:
→ fast (read-only)
→ deterministic
→ backed by a known artifact

All compute:
→ happens in workers
→ produces versioned outputs