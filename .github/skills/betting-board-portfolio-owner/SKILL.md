---
name: betting-board-portfolio-owner
description: >-
  Use for the Syndicate betting board across MLB, NBA, WNBA, and NHL when the task involves
  the board's objective, troubleshooting, Render parity, cache hydration, query/status routes,
  response shape, or overall functionality across mature sports.
---

# Betting Board Portfolio Owner Skill

Use this skill when the user wants the cross-sport betting board fixed, debugged, verified, or improved end to end.

## Objective
Own the betting board as a cross-sport product surface, not just a collection of routes.

The board should:
- show the current board contract clearly for MLB, NBA, WNBA, and NHL
- surface live and pregame lanes consistently across mature sports
- hydrate from the best available cached or computed state
- remain stable on Render and locally
- degrade safely when cache or worker state is stale

## Scope
This skill applies to work on:
- `/intelligence`
- `/api/intelligence/query`
- `/api/intelligence/status`
- mature-sport board routes and shared board contracts
- board hydration and response-shape promotion
- cache, snapshot, and worker parity
- Render deploy verification for the board surface
- troubleshooting empty, stale, or partially hydrated board states

## Operating Principles
- Prefer end-to-end behavior over isolated route success.
- Prefer a populated board response over a shell or queued-only response when the request path can compute safely.
- Prefer cache-backed reads when fresh state exists.
- Preserve compatibility with existing board contracts and UI expectations.
- Keep troubleshooting focused on the smallest path that can explain the board state.

## Troubleshooting Sequence
1. Check deploy parity first.
2. Check the live board and status endpoints for the relevant sport.
3. Confirm whether the response is empty, stale, queued, or computed.
4. Determine whether the worker, cache, or request path owns the failure.
5. Verify the visible board shape matches what the template expects.
6. Validate locally with the same request path the UI uses.

## Validation Expectations
When changing the board, validate at least one of:
- local Flask test-client flow for the relevant sport board route
- local POST to `/api/intelligence/query`
- local GET to `/api/intelligence/status`
- targeted regression tests for the touched slice
- Render version/status parity when deploy behavior is involved

## Guardrails
- Do not widen scope into unrelated sports modules unless the board surface depends on them.
- Do not treat a healthy deploy as success if the board still renders empty.
- Do not stop at queued refresh if the board can be computed immediately.
- Do not change board shape without updating the UI expectations and tests.

## Expected Output
When this skill is used, the result should usually include:
- the root cause of the board issue
- the specific layer responsible
- the minimal code or configuration fix
- focused validation proving the board actually populates
