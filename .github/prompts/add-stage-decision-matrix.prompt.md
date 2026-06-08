---
description: Add stage-aware execution decisions to the daily update root.
name: add-stage-decision-matrix
agent: agent
---

MISSION:
You are a systems architect converting Syndicate's daily update root into a stage-aware execution controller.

TASK:
Refactor the root script so it decides, per sport/date, whether each stage should run:
- source refresh
- sim execution
- artifact generation
- manifest rebuild
- intelligence/evaluation update

REQUIREMENTS:
1. Introduce a stage decision matrix per sport/date.
2. Distinguish clearly between:
   - refresh required
   - sim required
   - artifact rebuild required
   - manifest rebuild required
   - evaluation update required
3. Preserve current downstream script compatibility for now.
4. Emit a structured plan/status summary before execution.

OUTPUT FORMAT:
1. Proposed per-sport stage decision object
2. Decision rules
3. Code changes
4. Compatibility notes
5. Tests