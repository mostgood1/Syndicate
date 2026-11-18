# Worker Architecture (Background Compute Layer)

> `[2026-11-17]` This doc used to say "Render" for the web service. Production has been the
> local WSL fleet since 2026-09-30 (Render is retired; runbook
> `docs/ai_context/local_production_runbook.md`), so it now says **web**: the fleet's `web` role,
> served at `http://127.0.0.1:10000`. The rule itself is unchanged.

## Core Principle

All heavy computation MUST run in background workers, not in the web service.

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

### 1. Scheduled Workers (the fleet supervisor's `SCHEDULED_JOBS`)
- run on a schedule (daily, hourly, etc.) from `scripts/local_production.py`; GitHub Actions no
  longer generate artifacts (`daily-update.yml` is manual-only)
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

Web reads:

→ the artifacts the workers wrote, on the shared data root (`~/syndicate-prod/data` on the fleet)
→ shared state from the keyvalue store (the fleet's local Redis)

---

## Key Rule

Workers write → web reads

There must be NO path where:
web recomputes heavy logic synchronously

---

## Simulation Rule

SimulationEngine:
- runs in workers
- outputs are persisted
- results reused by runtime

Web:
- never runs full simulation
- only consumes outputs
- the web service stays stateless, while the worker owns disk-backed writes and refresh jobs

---

## Data Flow

Raw Data
→ Worker
→ Simulation + enrichment
→ artifact (stored)
→ web
→ UI / intelligence

---

## Freshness Model

Workers ensure:
- artifacts are up-to-date
- live updates are captured

Web:
- selects correct artifact version
- does not regenerate it

---

## Failure Handling

If data is missing:

Web:
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

If computation leaks into web:
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