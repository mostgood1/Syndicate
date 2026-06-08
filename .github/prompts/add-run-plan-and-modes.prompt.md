---
description: Add explicit run modes and a structured run plan to the daily update root.
name: add-run-plan-and-modes
agent: agent
---

MISSION:
You are a senior PowerShell/platform engineer upgrading Syndicate's daily update root.

TASK:
Refactor the root script to introduce:
- explicit run modes
- a structured run plan object
- cleaner separation between planning and execution

REQUIREMENTS:
1. Add a RunMode parameter with values such as:
   - full
   - incremental
   - sim_only
   - manifest_only
   - evaluation_only
   - backfill
2. Build a structured in-memory run plan before launching downstream work.
3. Keep existing script entrypoints working.
4. Do not change public intelligence outputs.
5. Print the run mode and structured plan summary to the console.

OUTPUT FORMAT:
1. Proposed new parameters
2. Run plan schema/object
3. Code changes
4. Compatibility notes
5. Focused tests