---
name: syndicate-parlay-design-assistant
description: "Design and scope parlay-related intelligence work inside The Syndicate. Use when expanding leg-count parsing, same-game or cross-sport rules, bankroll or exposure controls, market-correlation logic, or the tests and UI that support ticket construction."
---

# Syndicate Parlay Design Assistant

Use this skill when the request is about how Syndicate should build, filter, rank, or explain parlays.

## Workflow
1. Identify the requested parlay type, sport mix, correlation tolerance, bankroll rules, and leg-count constraints.
2. Map the ask to parser fields, candidate filtering, pair or shape penalties, ranking, and payload output.
3. Prefer explicit pair-family or market-shape rules over vague heuristics.
4. Keep same-game correlation logic explainable in payload fields and tests.
5. Validate with targeted intelligence tests before touching broader flows.

## Deliverables
- Concrete logic changes.
- Test cases covering the new preference or penalty rule.
- Payload fields needed for downstream rendering.
