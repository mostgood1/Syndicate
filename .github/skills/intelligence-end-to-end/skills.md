---
name: intelligence-end-to-end
description: Use this when modifying the intelligence system that backs the live Render intelligence endpoint. Preserve the external endpoint contract rooted at the live intelligence URL while extending the internal pipeline safely.
---

# Purpose

This skill governs end-to-end changes to the intelligence system behind the live intelligence endpoint:

[Live intelligence endpoint](https://syndicate-an21.onrender.com/intelligence)

The external endpoint behavior is the contract to preserve unless the task explicitly asks to change it.

This skill is also the incident-response workflow for repeated board failures. Use it when the live surface is stale, empty, queued-only, or returning 502 during deploy transitions.

Before relying on live Render for diagnosis, first try to reproduce the issue in a local Render-emulated environment that matches the deployed runtime as closely as possible: same env vars, same worker/web split, same data roots or mounted disk layout, and the same disabled or enabled background loops where applicable. Treat that local setup as the preferred place to reach a Render-runtime-equivalent state before widening the investigation.

## Auto-Troubleshoot Triggers

If any of the following are observed, immediately switch into incident-mode troubleshooting before making code changes:
- `/versionz` does not match the latest pushed commit.
- `/healthz` is 200 but `/api/intelligence/status` still shows `candidate_count: 0` or `state_last_updated: null`.
- `/api/intelligence/query` is 200 but the board renders empty or `board_input` logs show zero cards.
- `/intelligence` or `/api/intelligence/status` returns 502 while the deploy dashboard says the service is live.
- Logs show candidate generation happening upstream, but the visible board contract is empty.
- The board becomes empty again after a deploy that was supposed to be a fix.

When triggered, do all of the following automatically:
1. Capture deploy parity (`/versionz`) and confirm the live commit.
2. Check the live board, query, and status endpoints with cache-busting request URLs.
3. Map the failure to one primary bucket: deploy mismatch, request-path timeout, worker ownership/queue issue, cache/snapshot freshness, response-shape/alias drift, or template hydration.
4. Inspect the smallest owning layer that can explain the symptom and stop after the first falsifiable local hypothesis.
5. Reproduce the issue in the local Render-emulated environment first if the symptom depends on runtime shape, startup behavior, disk state, or worker/web parity.
6. Prefer a self-heal if it is safe: refresh queued state, restore missing aliases, or fall back to the best valid cached snapshot.
7. If the fix would block the web dyno, do not compute inline; hand off to the worker and return quickly.

# System intent

The intelligence system should be evolved behind the endpoint through modular layers such as:
- request normalization
- routing
- pipeline orchestration
- intelligence engine invocation
- evidence extraction
- structured output mapping
- formatting / response assembly

The system should self-heal when possible, but never by blocking the web dyno long enough to trigger Render timeouts.

# Core rules

1. Preserve the public behavior of the live intelligence endpoint unless the task explicitly requests a contract change.
2. Prefer adding or modifying logic in:
   - router
   - pipeline
   - evidence builder
   - structured output / formatter
3. Treat `intelligence.py` as a black box unless a targeted change to it is explicitly necessary.
4. Do not mix formatting with analysis logic.
5. Do not bypass structured output when returning endpoint responses.
6. Do not make unreviewed breaking changes to request or response shapes.
7. Any endpoint change must be grounded in repository code that Render will deploy.
8. Treat a healthy `/healthz` as necessary but not sufficient; `/versionz`, `/api/intelligence/status`, `/api/intelligence/query`, and `/intelligence` must also agree.
9. If the request path can compute safely and quickly, prefer a populated response over an empty shell.
10. If the request path would exceed the Render timeout ceiling, stop computing inline and hand off to the worker or cached path.

# Required workflow

1. Confirm deploy parity first with `/versionz` and the current repo HEAD.
2. Inspect the live `/healthz`, `/api/intelligence/status`, `/api/intelligence/query`, and `/intelligence` endpoints together.
3. Classify the failure into one of these buckets:
   - deploy mismatch
   - request-path timeout
   - worker ownership / queue issue
   - cache or snapshot freshness issue
   - response-shape / alias issue
   - template hydration issue
4. Inspect `intelligence.py` and surrounding pipeline modules.
5. Reproduce the issue locally in the Render-emulated environment when the failure may depend on deploy runtime, disk layout, env vars, worker ownership, or startup timing.
6. Identify whether the requested feature belongs in:
   - router
   - pipeline
   - evidence builder
   - structured output / formatter
7. Implement the smallest modular change possible.
8. Wire the change into the endpoint path without changing unrelated code.
9. Add or update tests for:
   - endpoint contract
   - pipeline logic
   - structured output
10. Validate using the local Render-emulated path first when available, then the same live request path the UI uses.
11. Summarize changed files, the failure bucket, and any contract impact explicitly.

If the same failure has recurred across multiple deploys, perform the auto-troubleshoot sequence above before editing code so the incident is diagnosed as a system problem, not just a one-off bug.

# Endpoint contract policy

- The live endpoint is the public contract.
- Internal architecture may evolve.
- External request/response behavior should remain stable unless a contract change is explicitly requested.

# Failure matrix

- `502` on `/versionz`, `/intelligence`, or `/api/intelligence/status`: treat as deploy or runtime failure first, not a board-shape problem.
- `healthz 200` but `status candidate_count: 0` / `state_last_updated: null`: treat as stale snapshot, worker, or persistence failure.
- `query 200` but board still empty: inspect response assembly, board contract shaping, and `top_opportunities` / `recommendations` aliases.
- `candidate_generation > 0` in logs but zero board cards: inspect response filtering, archived/final visibility rules, or alias hydration.
- `board_input` logs show `0` cards while upstream candidates exist: inspect `build_response()` and `build_intelligence_board_contract()` before chasing the worker again.
- live endpoint shows the wrong commit: deploy parity is broken and no further diagnosis should assume the latest code is running.

# Self-heal rules

1. If deploy parity is wrong, stop and fix the deploy first.
2. If the request path is slow enough to threaten the Render timeout, return a cached or queued response and let the worker own recompute.
3. If the board contract would otherwise collapse to an empty visible list, preserve the best available recommendations and surface the archived/final state instead of hiding everything.
4. If status is stale but the worker can refresh, queue a refresh and return the best safe snapshot.
5. If response aliases drift, restore the canonical aliases (`top_opportunities`, `recommendations`, `board_contract`) before changing UI code.
6. If the worker cannot persist state, surface the failure in logs and status instead of silently returning zeroes.
7. If a fix already deployed but the board regresses again, assume one of the trigger conditions above is still true and restart from deploy parity rather than broadening scope.

# Files to inspect first

- the Flask route / blueprint file that serves `/intelligence`
- `intelligence.py`
- pipeline modules
- router modules
- response models / formatter
- `render.yaml`
- `scripts/run_refresh_worker.py`
- deployment/version endpoints
- tests covering intelligence behavior

# References

- ./references/live-endpoint-contract.md
- ./references/architecture.md
- ./references/render-runtime-notes.md

# Examples

- ./examples/request-example.json
- ./examples/response-example.json