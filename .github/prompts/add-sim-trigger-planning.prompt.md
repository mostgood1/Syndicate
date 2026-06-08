---
description: Add simulation-trigger planning to the daily update root.
name: add-sim-trigger-planning
agent: agent
---

MISSION:
You are a simulation-platform architect designing state-driven execution for Syndicate.

TASK:
Design and implement the first version of simulation-trigger planning.

GOAL:
The root should decide whether simulations need to run based on meaningful state changes, not just the date.

REQUIREMENTS:
1. Introduce a sim execution decision function per sport/date.
2. Consider future support for:
   - odds/material input changes
   - model version changes
   - artifact staleness
   - policy/config changes
3. For now, implement the lightest safe scaffold that fits the current codebase.
4. Do not require a full downstream rewrite yet.
5. Preserve current output behavior.

OUTPUT FORMAT:
1. Proposed sim-trigger decision contract
2. Initial implementation scaffold
3. Integration with current root planning flow
4. Tests for should-run vs no-op cases
