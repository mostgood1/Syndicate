---
name: betting-board-mlb-owner-strict
description: >-
  Use for strict MLB betting board contract work when you need the visible response shape,
  candidate counts, fleet parity, and board hydration behavior enforced aggressively.
---

# MLB Betting Board Owner Strict Skill

Use this skill when MLB board work needs a stricter contract-first approach.

Production is the local WSL fleet at `http://127.0.0.1:10000` `[since 2026-09-30; Render is retired]`. "Fleet parity" below means the local result matches what the fleet serves.

## Contract Rules
- The MLB board should not ship an empty shell when a populated response is possible.
- The MLB query path should prefer a computed MLB response over a queued-only fallback when cache content is missing or zero-candidate.
- The visible response should expose MLB opportunities through the fields the UI consumes.
- The board should remain readable even when worker state is stale or the snapshot is partial.
- Fleet parity (the board as `http://127.0.0.1:10000` serves it) should be verified before calling the board fixed.
- When runtime behavior is suspect, reproduce the issue in a local fleet-equivalent run (same worker/web split, same role env, a data root laid out like `~/syndicate-prod/data`, paper money only: `scripts/fleet_local.py`) before leaning on live fleet checks.

## Validation Bar
A change is not complete until at least one of these passes:
- local fleet-equivalent runtime reproduction for the MLB board path
- `/mlb` renders populated board content locally
- `/mlb/api/cards` returns MLB cards locally
- targeted MLB regression tests pass
- the fleet's `/versionz` and MLB board state agree

## Troubleshooting Priority
1. Deploy parity
2. Empty or stale snapshot
3. Candidate count and visible MLB opportunities
4. Response-shape promotion
5. UI hydration
