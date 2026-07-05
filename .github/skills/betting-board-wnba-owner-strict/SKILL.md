---
name: betting-board-wnba-owner-strict
description: >-
  Use for strict WNBA betting board contract work when you need the visible response shape,
  candidate counts, Render parity, and board hydration behavior enforced aggressively.
---

# WNBA Betting Board Owner Strict Skill

Use this skill when WNBA board work needs a stricter contract-first approach.

## Contract Rules
- The WNBA board should not ship an empty shell when a populated response is possible.
- The WNBA query path should prefer a computed WNBA response over a queued-only fallback when cache content is missing or zero-candidate.
- The visible response should expose WNBA opportunities through the fields the UI consumes.
- The board should remain readable even when worker state is stale or the snapshot is partial.
- Render parity should be verified before calling the board fixed.
- When runtime behavior is suspect, reproduce the issue in a local Render-emulated environment before leaning on live Render checks.

## Validation Bar
A change is not complete until at least one of these passes:
- local Render-emulated runtime reproduction for the WNBA board path
- `/wnba` renders populated board content locally
- targeted WNBA regression tests pass
- Render version and WNBA board state agree

## Troubleshooting Priority
1. Deploy parity
2. Empty or stale snapshot
3. Candidate count and visible WNBA opportunities
4. Response-shape promotion
5. UI hydration
