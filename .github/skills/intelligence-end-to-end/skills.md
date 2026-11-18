---
name: intelligence-end-to-end
description: Use this when modifying the intelligence system that backs the live intelligence endpoint (production is the local WSL fleet). Preserve the external endpoint contract rooted at the live intelligence URL while extending the internal pipeline safely.
---

# Purpose

This skill governs end-to-end changes to the intelligence system behind the live intelligence endpoint:

[Live intelligence endpoint](http://127.0.0.1:10000/intelligence) -- production is the local WSL fleet since 2026-09-30; the Render host is retired.

The external endpoint behavior is the contract to preserve unless the task explicitly asks to change it.

This skill is also the incident-response workflow for repeated board failures. Use it when the live surface is stale, empty, queued-only, or returning 502 during deploy transitions.

Before relying on the live fleet for diagnosis, first try to reproduce the issue in a local fleet-equivalent run that matches the fleet's runtime as closely as possible: the same role env (built at `up` from `scripts/fleet_role_spec.json` -> `~/syndicate-prod/fleet_env/<role>.json` -> `~/syndicate-prod/local_production.env` -> forced keys, a later layer winning; `python3 scripts/local_production.py env --role <role>` prints it with secrets masked), the same worker/web split, a `SYNDICATE_DATA_ROOT` laid out like the fleet's one shared disk (`~/syndicate-prod/data`), and the same disabled or enabled background loops where applicable. Run it with paper money only: the fleet's own env trades live money. `scripts/fleet_local.py` is that rehearsal harness `[2026-11-17, lane fleet-local-env-source]`: it builds each role's env with the fleet's own `local_production.derive_role_env` from `scripts/fleet_role_spec.json` plus a credential-free copy of `fleet_env/` (make it once with `python3 scripts/fleet_local.py --mirror <M> snapshot --fleet-home ~/syndicate-prod` inside WSL, where `fleet_env/` is readable), never reads `local_production.env`, forces paper, replays the network, and cannot reach the fleet's own web (:10000), Redis (:6379) or data root; then `fleet_local.py --mirror <M> doctor` and `up --bounded`. What it does not reproduce, by design: the venue and OddsAPI credentials and the admin token (withheld), the hosted-only branches (it runs `--state file`, like the fleet's own `--state file`), and gunicorn on Windows (waitress there, the fleet's own fallback). Treat that local setup as the preferred place to reach a fleet-equivalent state before widening the investigation. `[2026-11-17]` This step used to say "Render-emulated"; Render was retired on 2026-09-30.

## Auto-Troubleshoot Triggers

If any of the following are observed, immediately switch into incident-mode troubleshooting before making code changes:
- `/versionz` does not match the latest pushed commit.
- `/healthz` is 200 but `/api/intelligence/status` still shows `candidate_count: 0` or `state_last_updated: null`.
- `/api/intelligence/query` is 200 but the board renders empty or `board_input` logs show zero cards.
- `/intelligence` or `/api/intelligence/status` returns 502 while the fleet supervisor reports web up (`python3 scripts/local_production.py status` in the fleet checkout).
- Logs show candidate generation happening upstream, but the visible board contract is empty.
- The board becomes empty again after a deploy that was supposed to be a fix.

When triggered, do all of the following automatically:
1. Capture deploy parity (`/versionz`) and confirm the live commit.
2. Check the live board, query, and status endpoints with cache-busting request URLs.
3. Map the failure to one primary bucket: deploy mismatch, request-path timeout, worker ownership/queue issue, cache/snapshot freshness, response-shape/alias drift, or template hydration.
4. Inspect the smallest owning layer that can explain the symptom and stop after the first falsifiable local hypothesis.
5. Reproduce the issue in the local fleet-equivalent run first if the symptom depends on runtime shape, startup behavior, disk state, or worker/web parity.
6. Prefer a self-heal if it is safe: refresh queued state, restore missing aliases, or fall back to the best valid cached snapshot.
7. If the fix would block the web role, do not compute inline; hand off to the worker and return quickly.

# System intent

The intelligence system should be evolved behind the endpoint through modular layers such as:
- request normalization
- routing
- pipeline orchestration
- intelligence engine invocation
- evidence extraction
- structured output mapping
- formatting / response assembly

The system should self-heal when possible, but never by blocking the web role long enough to trip its gunicorn worker timeout (`GUNICORN_TIMEOUT`), which surfaces as a 502 or a timeout at `http://127.0.0.1:10000`.

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
7. Any endpoint change must be grounded in repository code on `main`, which is what the fleet deploys. Pushing to `main` ships nothing by itself: a fleet deploy is an exact-SHA `git merge --ff-only <sha>` in `~/Syndicate`, then `local_production.py reload-web` for web.
8. Treat a healthy `/healthz` as necessary but not sufficient; `/versionz`, `/api/intelligence/status`, `/api/intelligence/query`, and `/intelligence` must also agree.
9. If the request path can compute safely and quickly, prefer a populated response over an empty shell.
10. If the request path would exceed web's gunicorn timeout (`GUNICORN_TIMEOUT`), stop computing inline and hand off to the worker or cached path.

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
5. Reproduce the issue locally in the fleet-equivalent run when the failure may depend on deploy runtime, disk layout, env vars, worker ownership, or startup timing.
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
10. Validate using the local fleet-equivalent path first when available, then the same live request path the UI uses.
11. Summarize changed files, the failure bucket, and any contract impact explicitly.

If the same failure has recurred across multiple deploys, perform the auto-troubleshoot sequence above before editing code so the incident is diagnosed as a system problem, not just a one-off bug.

# Endpoint contract policy

- The live endpoint is the public contract.
- Internal architecture may evolve.
- External request/response behavior should remain stable unless a contract change is explicitly requested.

# Failure matrix

- `502` on `/versionz`, `/intelligence`, or `/api/intelligence/status`: treat as deploy or runtime failure first, not a board-shape problem. On the fleet that is web at `http://127.0.0.1:10000` (a gunicorn worker recycle or starvation): check `/healthz` and read web's log with `py -3 scripts/fleet_logs.py --service web --text <substring> --start <UTC ISO8601>`.
- `healthz 200` but `status candidate_count: 0` / `state_last_updated: null`: treat as stale snapshot, worker, or persistence failure.
- `query 200` but board still empty: inspect response assembly, board contract shaping, and `top_opportunities` / `recommendations` aliases.
- `candidate_generation > 0` in logs but zero board cards: inspect response filtering, archived/final visibility rules, or alias hydration.
- `board_input` logs show `0` cards while upstream candidates exist: inspect `build_response()` and `build_intelligence_board_contract()` before chasing the worker again.
- live endpoint shows the wrong commit: deploy parity is broken and no further diagnosis should assume the latest code is running.

# Self-heal rules

1. If deploy parity is wrong, stop and fix the deploy first.
2. If the request path is slow enough to threaten web's gunicorn timeout, return a cached or queued response and let the worker own recompute.
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
- `scripts/fleet_role_spec.json` and `docs/ai_context/local_production_runbook.md` (each role's declared env and how the fleet runs; `render.yaml` is read by nothing since 2026-11-17)
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