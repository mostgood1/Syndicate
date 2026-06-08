---
description: Add structured pipeline status and observability to the daily update root.
name: add-pipeline-status
agent: agent
---

MISSION:
You are an operations-focused engineer adding run visibility to Syndicate.

TASK:
Add structured pipeline status emission for the in-season daily update flow.

REQUIREMENTS:
- Record:
  - date
  - run mode
  - active sports
  - skipped sports
  - planned stages per sport
  - execution status per stage if available
  - failure reason if any
- Write a simple serialized status artifact under reports/state or a similar Syndicate-owned location.
- Keep implementation thin and additive.

OUTPUT FORMAT:
1. Status schema
2. Code changes
3. Example serialized artifact
4. Tests
``