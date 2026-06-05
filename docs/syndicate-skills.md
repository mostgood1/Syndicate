# Syndicate Skills

This workspace now includes a set of task-specific Copilot skills for planning, debugging, auditing, deployment verification, and richer sport-level question answering inside Syndicate.

## Core workflow skills
- `syndicate-intelligence-planner`: expand the intelligence layer, advanced-data access, ranking logic, and render-ready outputs.
- `syndicate-advanced-data-analyst`: answer rich questions with local advanced artifacts, tables, and charts.
- `syndicate-parlay-design-assistant`: design and validate parlay parsing, filtering, and correlation logic.
- `syndicate-live-lens-debugger`: debug live payload, hydration, and stale-state issues.
- `syndicate-readiness-auditor`: audit migration-gate blockers, advanced inputs, and artifact coverage.
- `syndicate-deployment-verifier`: check local-versus-Render parity and stale deploy concerns.

## Sport-level analyst skills
- `syndicate-mlb-statcast-analyst`: MLB Statcast-backed matchup and prop analysis.
- `syndicate-basketball-matchup-analyst`: NBA, WNBA, and NCAAB matchup and prop analysis.
- `syndicate-college-basketball-analyst`: NCAAB matchup, props, and slate-shape analysis.
- `syndicate-hockey-live-prop-analyst`: NHL live and pregame prop analysis.
- `syndicate-nfl-market-analyst`: NFL weekly card, prop, game-script, and correlation-aware market analysis.
- `syndicate-college-football-analyst`: NCAAF weekly card, line-context, and volatility-aware market analysis.

## When to use them
- Use a workflow skill when the task is about changing code, debugging behavior, validating readiness, or checking deployment state.
- Use a sport-level analyst skill when the ask is primarily a sports question that needs evidence-backed reasoning from local Syndicate artifacts.

## Current recovery worktrees
The hidden git work that had been stashed is now surfaced in isolated review worktrees so it can be compared safely:
- `../Syndicate-recover-migration`
- `../Syndicate-recover-intelligence`
- `../Syndicate-recover-manifests`

See `tmp_hidden_work_inventory_2026-06-05.md` for the stash mapping and duplicate-retry notes.
See `tmp_recovered_intelligence_delta_2026-06-05.md` for the current-versus-recovered intelligence comparison.
