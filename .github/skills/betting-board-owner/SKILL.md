---
name: betting-board-owner
description: >-
  Use for the Syndicate betting board when the task involves the board's objective,
  troubleshooting, render parity, cache hydration, query/status routes, response shape,
  or overall functionality across live and pregame lanes.
---

# Betting Board Owner Skill

Use this skill when the user wants the betting board fixed, debugged, verified, or improved end to end.

## Objective
Own the betting board as a product surface, not just a route.

The board should:
- show the current board contract clearly
- surface live and pregame lanes
- hydrate from the best available cached or computed state
- remain stable on Render and locally
- degrade safely when cache or worker state is stale

When the live intelligence endpoint is involved, use the end-to-end intelligence workflow in [.github/skills/intelligence-end-to-end/skills.md](.github/skills/intelligence-end-to-end/skills.md) to classify the failure bucket before making changes. If the same empty or 502 symptom recurs after a deploy, trigger that workflow automatically.

## Scope
This skill applies to work on:
- `/intelligence`
- `/api/intelligence/query`
- `/api/intelligence/status`
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
2. Check the live board and status endpoints.
3. Confirm whether the response is empty, stale, queued, or computed.
4. Determine whether the worker, cache, or request path owns the failure.
5. Verify the visible board shape matches what the template expects.
6. Reproduce the issue in a local Render-emulated environment when the symptom could depend on Render runtime behavior, startup timing, disk mounts, env vars, or worker/web split behavior.
7. Validate locally with the same request path the UI uses after the runtime-equivalent environment check.
8. If the board is still empty, separate the failure into one of these buckets before editing code:
  - deploy mismatch
  - request-path timeout
  - worker ownership / queue issue
  - cache or snapshot freshness issue
  - response-shape / alias issue
  - template hydration issue
9. If the live deploy is healthy but the board still fails, re-run deploy parity and endpoint checks before widening scope.

## Validation Expectations
When changing the board, validate at least one of:
- local Render-emulated runtime reproduction when the issue is tied to startup, disk, env, or worker parity
- local Flask test-client flow for `/intelligence`
- local POST to `/api/intelligence/query`
- local GET to `/api/intelligence/status`
- targeted regression tests for the touched slice
- Render version/status parity when deploy behavior is involved

If the live board still fails after the code change, re-run the same live parity checks before widening scope.

## Guardrails
- Do not widen scope into unrelated sports modules unless the board surface depends on them.
- Do not treat a healthy deploy as success if the board still renders empty.
- Do not stop at queued refresh if the board can be computed immediately.
- Do not change board shape without updating the UI expectations and tests.
- Do not let the web request path block long enough to trip Render timeouts.
- Do not hide final or archived recommendations if that would collapse the visible board to zero.

## Expected Output
When this skill is used, the result should usually include:
- the root cause of the board issue
- the specific layer responsible
- the minimal code or configuration fix
- focused validation proving the board actually populates