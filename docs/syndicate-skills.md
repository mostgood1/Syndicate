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

## Current runtime alignment
The VS Code skills are still developer-side playbooks, but Syndicate runtime intelligence now mirrors part of that structure in code:
- `syndicate/features/intelligence.py`: main query engine, candidate collection, market-fit scoring, and unified response contract.
- `syndicate/features/intelligence_router.py`: internal analysis-focus routing for richer sport-specific asks.
- `syndicate/features/intelligence_analysis_views.py`: stable analysis-view entrypoint that delegates to sport-owned builders.
- `syndicate/features/intelligence_analysis_common.py`: shared row/filter/signal helpers used by the analysis builders.
- `syndicate/features/mlb/intelligence_analysis.py`: MLB prop analysis builders.
- `syndicate/features/nba/intelligence_analysis.py`: NBA analysis builders.
- `syndicate/features/wnba/intelligence_analysis.py`: WNBA analysis builders with league-specific environment and pressure fields.
- `syndicate/features/ncaab/intelligence_analysis.py`: NCAAB analysis builders with college-specific tempo and volatility fields.
- `syndicate/features/nfl/intelligence_analysis.py`: football-family analysis builders for NFL and NCAAF asks.
- `syndicate/features/nhl/intelligence_analysis.py`: hockey prop analysis builders.
- `syndicate/features/intelligence_parlay_correlation.py`: same-game pair penalties and medium-correlation preference enforcement.
- `syndicate/features/intelligence_parlay_runtime.py`: parlay payload assembly, round-robin generation, and parlay ranking.

The current runtime path supports:
- candidate-driven market inference instead of relying only on hardcoded query aliases
- market-shape-aware recommendation scoring
- medium-correlation and pair-penalty-aware parlay filtering and ranking
- structured analysis views for MLB HR plus strikeout/total-bases explainer asks, NBA matchup asks with pace/usage/shot-profile context, WNBA matchup asks with team-environment and matchup-pressure context, NCAAB matchup asks with tempo/volatility context, football market asks with EPA/target-share/pass-rate context, and hockey prop asks

The main remaining expansion area is deeper sport-native reasoning and artifact-backed explainers inside each sport module now that the router, parlay runtime, and analysis-builder boundaries are in place.

## Current recovery worktrees
The hidden git work that had been stashed is now surfaced in isolated review worktrees so it can be compared safely:
- `../Syndicate-recover-migration`
- `../Syndicate-recover-intelligence`
- `../Syndicate-recover-manifests`

The highest-value remaining intelligence recovery work is still in `../Syndicate-recover-intelligence`, especially deeper sport-specific reasoning and any additional parlay-correlation slices that are worth porting into tested runtime code.
