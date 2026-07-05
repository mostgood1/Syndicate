---
name: betting-board-nhl-owner
description: >-
  Use for the Syndicate NHL betting board when the task involves the board's objective,
  troubleshooting, Render parity, cache hydration, query/status routes, response shape,
  or overall functionality for NHL live and pregame lanes.
---

# NHL Betting Board Owner Skill

Use this skill when the user wants the NHL betting board fixed, debugged, verified, or improved end to end.

## Objective
Own the NHL betting board as a product surface, not just a route.

The board should:
- show the current NHL board contract clearly
- surface live and pregame lanes
- hydrate from the best available cached or computed state
- remain stable on Render and locally
- degrade safely when cache or worker state is stale

## Scope
This skill applies to work on:
- `/nhl`
- NHL cards, games, props, and betting-board responses
- cache, snapshot, and worker parity for NHL board content
- Render deploy verification for the NHL board surface
- troubleshooting empty, stale, or partially hydrated NHL board states

## Operating Principles
- Prefer end-to-end behavior over isolated route success.
- Prefer a populated board response over a shell or queued-only response when the request path can compute safely.
- Prefer cache-backed reads when fresh state exists.
- Preserve compatibility with existing NHL board contracts and UI expectations.
- Keep troubleshooting focused on the smallest path that can explain the board state.

## Troubleshooting Sequence
1. Check deploy parity first.
2. Check the live NHL board and related endpoints.
3. Confirm whether the response is empty, stale, queued, or computed.
4. Determine whether the worker, cache, or request path owns the failure.
5. Verify the visible NHL board shape matches what the template expects.
6. Reproduce the issue in a local Render-emulated environment when the symptom could depend on runtime behavior, startup timing, disk mounts, env vars, or worker/web split behavior.
7. Validate locally with the same request path the UI uses after the runtime-equivalent environment check.

## Validation Expectations
When changing the NHL board, validate at least one of:
- local Render-emulated runtime reproduction when the issue is tied to startup, disk, env, or worker parity
- local Flask test-client flow for `/nhl`
- NHL API or board route checks
- targeted regression tests for the touched slice
- Render version/status parity when deploy behavior is involved

## Guardrails
- Do not widen scope into unrelated sports modules unless the NHL board surface depends on them.
- Do not treat a healthy deploy as success if the board still renders empty.
- Do not stop at queued refresh if the board can be computed immediately.
- Do not change board shape without updating the NHL UI expectations and tests.

## Expected Output
When this skill is used, the result should usually include:
- the root cause of the NHL board issue
- the specific layer responsible
- the minimal code or configuration fix
- focused validation proving the board actually populates
