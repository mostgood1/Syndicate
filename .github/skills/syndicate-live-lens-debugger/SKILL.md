---
name: syndicate-live-lens-debugger
description: "Debug Syndicate live-lens issues across MLB, NBA, WNBA, NHL, NCAAB, and related surfaces. Use when live data is stale, odds are missing, props do not hydrate, cards show old states, or the fleet (production, http://127.0.0.1:10000) serves a different live payload than local code."
---

# Syndicate Live Lens Debugger

Use this skill when the problem is about live cards, live props, scoreboard state, hydration, or local-versus-deployed live payload mismatches.

## Workflow
1. Identify the sport, event date, route, and artifact path involved.
2. Reproduce the issue in a local fleet-equivalent run (same role env and worker/web split, paper money only) first when the symptom could depend on runtime behavior, startup timing, the shared data root, env vars, or worker/web split behavior.
3. Check the owning local payload, mirror artifact, and home/card rendering surface before comparing with the live fleet at `http://127.0.0.1:10000`.
4. Verify whether the issue is source freshness, payload shape, fallback merge logic, runtime-equivalence mismatch, or UI rendering.
5. Prefer focused archive or route tests for the affected sport before broader smoke runs.
6. Preserve event ids and existing artifact contracts unless the task explicitly changes them.

## Useful targets
- Live lens payload builders.
- Home card fallbacks.
- Processed-path resolution.
- Archive regressions and browser smoke coverage.
