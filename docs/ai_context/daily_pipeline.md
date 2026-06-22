# Daily Data Pipeline (GitHub Actions)

## Purpose
Generates daily artifacts, simulation outputs, and summary data for all sports.

For the current GitHub Actions daily-update contract, see [Daily update GitHub Actions workflow](../daily_update_workflow.md).

---

## Flow

Raw data sources
→ data collection
→ processing / enrichment
→ simulation runs (some sports)
→ artifact generation (JSON files)
→ stored outputs (daily summaries, sim rows, recommendations)

---

## Outputs Produced

- daily_summary (MLB, etc.)
- simulation outputs
- recommendation rows
- evaluation outputs
- stored artifacts used by cards

---

## Relationship to Runtime

At runtime:
- cards and UI DO NOT recompute everything
- they read from stored artifacts
- simulation is not always re-run live

---

## Key Constraint

If data is not present in artifacts:
→ it will never reach cards or simulation inputs

---

## Key Risk

- available live data ≠ used simulation data
- artifacts may lag behind available signals
- adapters depend on artifact structure

---

## Core Question

Are we:
- generating rich simulation inputs in the daily job?
OR
- losing data before it even reaches runtime?
