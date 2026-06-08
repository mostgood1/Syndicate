---
description: Add persistent run-state and checkpoint handling to the daily update root.
name: add-run-state
agent: agent
---

MISSION:
You are a platform reliability engineer improving Syndicate's daily update control plane.

TASK:
Introduce persistent run-state management so the root can make state-aware execution decisions.

REQUIREMENTS:
1. Add a durable run-state store under a Syndicate-owned reports/state location.
2. Track at least:
   - last successful run per sport/date
   - run mode
   - input fingerprint if available
   - artifact manifest fingerprint if available
   - model version if available
   - policy/version metadata if available
3. Load run-state before planning execution.
4. Persist updated run-state only after successful completion.
5. Keep the first implementation simple and file-based.

OUTPUT FORMAT:
1. Proposed run-state schema
2. File paths / modules
3. Code changes
4. Recovery and replay notes
5. Tests for first run, resume, and no-op behavior
``