---
name: betting-board-mlb-owner
description: >-
  Use for the Syndicate MLB betting board when the task involves the board's objective,
  troubleshooting, Render parity, cache hydration, query/status routes, response shape,
  or overall functionality for MLB live and pregame lanes.
---

# MLB Betting Board Owner Skill

Use this skill when the user wants the MLB betting board fixed, debugged, verified, or improved end to end.

## Objective
Own the MLB betting board as a product surface, not just a route.

The board should:
- show the current MLB board contract clearly
- surface live and pregame lanes
- hydrate from the best available cached or computed state
- remain stable on Render and locally
- degrade safely when cache or worker state is stale

## Scope
This skill applies to work on:
- `/mlb`
- `/mlb/api/cards`
- `/mlb/api/game/*`
- MLB board hydration and response-shape promotion
- cache, snapshot, and worker parity for MLB board content
- Render deploy verification for the MLB board surface
- troubleshooting empty, stale, or partially hydrated MLB board states

## Operating Principles
- Prefer end-to-end behavior over isolated route success.
- Prefer a populated board response over a shell or queued-only response when the request path can compute safely.
- Prefer cache-backed reads when fresh state exists.
- Preserve compatibility with existing MLB board contracts and UI expectations.
- Keep troubleshooting focused on the smallest path that can explain the board state.

## Troubleshooting Sequence
1. Check deploy parity first.
2. Check the live MLB board and status endpoints.
3. Confirm whether the response is empty, stale, queued, or computed.
4. Determine whether the worker, cache, or request path owns the failure.
5. Verify the visible MLB board shape matches what the template expects.
6. Reproduce the issue in a local Render-emulated environment when the symptom could depend on runtime behavior, startup timing, disk mounts, env vars, or worker/web split behavior.
7. Validate locally with the same request path the UI uses after the runtime-equivalent environment check.

## Validation Expectations
When changing the MLB board, validate at least one of:
- local Render-emulated runtime reproduction when the issue is tied to startup, disk, env, or worker parity
- local Flask test-client flow for `/mlb`
- local GET to `/mlb/api/cards`
- local GET to `/mlb/api/game/<gamePk>/card-detail`
- targeted regression tests for the touched slice
- Render version/status parity when deploy behavior is involved

## Guardrails
- Do not widen scope into unrelated sports modules unless the MLB board surface depends on them.
- Do not treat a healthy deploy as success if the board still renders empty.
- Do not stop at queued refresh if the board can be computed immediately.
- Do not change board shape without updating the MLB UI expectations and tests.

## Expected Output
When this skill is used, the result should usually include:
- the root cause of the MLB board issue
- the specific layer responsible
- the minimal code or configuration fix
- focused validation proving the board actually populates
