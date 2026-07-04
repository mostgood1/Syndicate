---
name: betting-board-wnba-owner
description: >-
  Use for the Syndicate WNBA betting board when the task involves the board's objective,
  troubleshooting, Render parity, cache hydration, query/status routes, response shape,
  or overall functionality for WNBA live and pregame lanes.
---

# WNBA Betting Board Owner Skill

Use this skill when the user wants the WNBA betting board fixed, debugged, verified, or improved end to end.

## Objective
Own the WNBA betting board as a product surface, not just a route.

The board should:
- show the current WNBA board contract clearly
- surface live and pregame lanes
- hydrate from the best available cached or computed state
- remain stable on Render and locally
- degrade safely when cache or worker state is stale

## Scope
This skill applies to work on:
- `/wnba`
- WNBA cards, games, props, and betting-board responses
- cache, snapshot, and worker parity for WNBA board content
- Render deploy verification for the WNBA board surface
- troubleshooting empty, stale, or partially hydrated WNBA board states

## Operating Principles
- Prefer end-to-end behavior over isolated route success.
- Prefer a populated board response over a shell or queued-only response when the request path can compute safely.
- Prefer cache-backed reads when fresh state exists.
- Preserve compatibility with existing WNBA board contracts and UI expectations.
- Keep troubleshooting focused on the smallest path that can explain the board state.

## Troubleshooting Sequence
1. Check deploy parity first.
2. Check the live WNBA board and related endpoints.
3. Confirm whether the response is empty, stale, queued, or computed.
4. Determine whether the worker, cache, or request path owns the failure.
5. Verify the visible WNBA board shape matches what the template expects.
6. Validate locally with the same request path the UI uses.

## Validation Expectations
When changing the WNBA board, validate at least one of:
- local Flask test-client flow for `/wnba`
- WNBA API or board route checks
- targeted regression tests for the touched slice
- Render version/status parity when deploy behavior is involved

## Guardrails
- Do not widen scope into unrelated sports modules unless the WNBA board surface depends on them.
- Do not treat a healthy deploy as success if the board still renders empty.
- Do not stop at queued refresh if the board can be computed immediately.
- Do not change board shape without updating the WNBA UI expectations and tests.

## Expected Output
When this skill is used, the result should usually include:
- the root cause of the WNBA board issue
- the specific layer responsible
- the minimal code or configuration fix
- focused validation proving the board actually populates
