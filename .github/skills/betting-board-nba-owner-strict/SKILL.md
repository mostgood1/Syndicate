---
name: betting-board-nba-owner-strict
description: >-
  Use for strict NBA betting board contract work when you need the visible response shape,
  candidate counts, Render parity, and board hydration behavior enforced aggressively.
---

# NBA Betting Board Owner Strict Skill

Use this skill when NBA board work needs a stricter contract-first approach.

## Contract Rules
- The NBA board should not ship an empty shell when a populated response is possible.
- The NBA query path should prefer a computed NBA response over a queued-only fallback when cache content is missing or zero-candidate.
- The visible response should expose NBA opportunities through the fields the UI consumes.
- The board should remain readable even when worker state is stale or the snapshot is partial.
- Render parity should be verified before calling the board fixed.

## Validation Bar
A change is not complete until at least one of these passes:
- `/nba` renders populated board content locally
- targeted NBA regression tests pass
- Render version and NBA board state agree

## Troubleshooting Priority
1. Deploy parity
2. Empty or stale snapshot
3. Candidate count and visible NBA opportunities
4. Response-shape promotion
5. UI hydration
