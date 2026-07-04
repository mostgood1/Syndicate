---
name: betting-board-nhl-owner-strict
description: >-
  Use for strict NHL betting board contract work when you need the visible response shape,
  candidate counts, Render parity, and board hydration behavior enforced aggressively.
---

# NHL Betting Board Owner Strict Skill

Use this skill when NHL board work needs a stricter contract-first approach.

## Contract Rules
- The NHL board should not ship an empty shell when a populated response is possible.
- The NHL query path should prefer a computed NHL response over a queued-only fallback when cache content is missing or zero-candidate.
- The visible response should expose NHL opportunities through the fields the UI consumes.
- The board should remain readable even when worker state is stale or the snapshot is partial.
- Render parity should be verified before calling the board fixed.

## Validation Bar
A change is not complete until at least one of these passes:
- `/nhl` renders populated board content locally
- targeted NHL regression tests pass
- Render version and NHL board state agree

## Troubleshooting Priority
1. Deploy parity
2. Empty or stale snapshot
3. Candidate count and visible NHL opportunities
4. Response-shape promotion
5. UI hydration
