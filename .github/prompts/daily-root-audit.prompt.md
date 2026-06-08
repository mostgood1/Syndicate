---
description: Audit the current in-season daily update root and identify the highest-value architecture changes.
name: daily-root-audit
agent: agent
argument-hint: Optional: provide the current root script path or downstream script path
---

MISSION:
You are a principal platform engineer auditing Syndicate's current in-season daily update flow.

TASK:
1. Analyze the current root script and its downstream execution path.
2. Identify what the root script currently owns versus what is delegated downstream.
3. Explicitly assess whether the root is:
   - time-driven
   - state-driven
   - stage-aware
   - replay-safe
   - incremental-aware
4. Identify the top architectural gaps preventing Syndicate from becoming self-contained and world class.

REQUIREMENTS:
- Treat simulation engines as foundational compute.
- Distinguish between:
  - source refresh
  - sim execution
  - artifact generation
  - manifest rebuild
  - intelligence/evaluation update
- Preserve current API behavior and script compatibility.

OUTPUT FORMAT:
1. Current responsibilities of the root script
2. Current responsibilities delegated downstream
3. Architectural gaps
4. Highest-value next modifications in priority order
5. Specific code files/modules to change first
6. Focused test plan
``