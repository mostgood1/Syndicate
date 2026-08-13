# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Syndicate is a unified multi-sport analytics, simulation, and betting-intelligence platform (MLB, NBA, WNBA, NHL, NFL, NCAAF, NCAAB, soccer) that is progressively replacing separate sport-specific frontends. It is not "seven apps in one UI" — it is one Flask app with seven feature modules that must converge on the same board contract, artifact manifest, and intelligence layer.

The phased migration plan lives in `docs/syndicate_world_class_implementation_plan.md`. Read `README.md` for the full (long) operational reference — this file only covers what isn't obvious from the code.

## Outstanding work — read this first

**`docs/ai_context/todo.md` is the canonical cross-session TODO list.** Read it
before starting work and update it before finishing; don't keep a parallel list in
session-local task tools without reconciling it back. Closed items are archived to
`docs/ai_context/todo_closed.md` — that file is a record only, so read `todo.md`
first and treat its "Operational notes" as the place lessons live. Item IDs are
stable and never reused; check both files before taking a number, and before
finishing run the #71 check that shipped work actually reached one of them. It carries the current
priority order, what has been *validated* against production versus merely
believed, and a set of operational facts that are expensive to rediscover — among
them: **Render auto-deploy is OFF — but that is true of CODE and false of
CONFIG** (see below), **deploying kills an in-flight MLB sim**, and `logger.info`
never reaches Render's log collector (use `print(..., flush=True)`).

### Pushing `render.yaml` IS a production change (`#284`)

`autoDeploy = no` on all three services, so pushing `.py` to `main` really does
ship nothing. **`blueprint_sync` is a separate mechanism that bypasses it.**
Measured 2026-08-08: a web deploy at 23:02:26Z carried `trigger =
blueprint_sync` with no user in it, rewrote env vars on two live services
(refresh-worker 92 → 93 keys), and 502'd every route for ~2 minutes. Nobody
deployed it; a `render.yaml` commit had been pushed.

It fires on `render.yaml` changes, not on every push — 1 `blueprint_sync` against
19 `api` deploys over 20. So:

- **Pushing `.py` is free. Pushing `render.yaml` applies to production.** Get an
  explicit decision first; committing is still safe.
- **A sync writes the WHOLE env block, not your diff.** The blast radius of a
  one-key edit is every value in the file, including drift nobody has read.
  Enumerate before pushing: diff `render.yaml` against each service's live
  `/v1/services/<id>/env-vars` (paginate — `limit` > 100 returns HTTP 400).
- **Absent ≠ off. Check the code's default for any key you add or remove.**
  `_evaluation_settlement_auto_refresh_enabled` treats absent as **False**;
  `_mlb_refresh_tick_owner_here` defaults **True**. The same edit is a no-op in
  one case and a behaviour change in the other.
- A deploy nobody remembers ordering is findable: `/v1/services/<id>/deploys` →
  `trigger`.

**Why this is stated at this length:** the old one-liner was *literally true and
materially misleading*, which is the worst combination — it read as a guarantee
that pushes are free, and seven parallel sessions batched deploys all evening on
that basis. A near-miss the same night: `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS`
sat in the blueprint while absent from the live service, and setting that key
**at all** overrides the settlement autorun's daily gate (`int(raw or 86400)`) —
4 runs/day of a ~1.4GB job. It was commented out four hours before the sync fired.

## Render is the source of truth — `data/**` in git is a lossy mirror

**This applies to every task in this repo: analysis, modelling, backtests, and
debugging alike. Read it before drawing any conclusion from a file under
`data/`.**

The daily pipeline does **not** run off git. Workers write artifacts to
Render's mounted disk and the web service reads them from there (see the
worker-split rule below). The git-tracked `data/<sport>_source/` trees are a
**cold-start safety net** — periodically refreshed by
`scripts/refresh_<sport>_source_mirror.ps1` or pulled back over HTTP by the
backup workflow via `/api/ops/artifacts/export`. They are not a snapshot of
what production computed.

**The specific trap** (measured 2026-08-05, MLB): each artifact family is
synced on its own schedule, so their date windows do not line up. Any analysis
that needs to *join across families* silently collapses to the intersection:

| family | git-tracked dates | window |
|---|---|---|
| hitter/pitcher odds snapshots | 46 | broad |
| `daily_summary_*.json` | 33 | 05-28..07-12, **gaps 06-15..06-20, 06-22..06-28** |
| `roster_objs/` (v4, carries `batters_faced`) | 26 | 06-15..07-12 |
| `raw/statsapi/feed_live/` (actual outcomes) | 11 | 06-14..06-25 |

All four together: **one usable date.** A backtest built on these without
checking coverage will look like it ran on months of data and actually be
running on whatever the narrowest family happens to cover — or, worse, quietly
mix git-tracked and untracked on-disk files.

**How to apply:**
- Before any backtest or model evaluation, print the per-family date coverage
  and the intersection. Report the number of dates the result actually rests on.
- `git ls-files` vs. what is on disk is a real distinction here: much of
  `data/` on a dev machine is untracked mirror output of unknown vintage. Say
  which you used.
- Don't diagnose "missing data" from the local checkout — check production
  first (`/api/ops/...` with `ADMIN_TOKEN`, or the per-sport JSON APIs).
- Fixing thin coverage means refreshing the mirror from Render or widening
  `HOT_ARTIFACT_PATTERNS` — not quietly falling back to whatever is on disk.

## Commands

Run the app locally:
```powershell
py -3 -m pip install -r requirements.txt
py -3 app.py
```

Run tests (pytest is used day-to-day; CI only runs the archive suite via unittest):
```powershell
python -m pytest tests/                          # full suite
python -m pytest tests/test_intelligence.py       # single file
python -m pytest tests/test_intelligence.py::test_name -v   # single test
python -m unittest tests.test_archives            # what CI actually runs
```

Full migration/regression gate (audit + module tracker + archive suite + browser parity smoke, one pass/fail result):
```powershell
python .\scripts\migration_gate.py
python .\scripts\migration_gate.py --base-url http://127.0.0.1:5000 --write-dir .\reports\migration_gate\latest
```

Refresh local per-sport artifact mirrors then gate in one shot (the normal pre-push loop):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_and_gate.ps1 -Date 2026-05-18
```

Browser parity smoke only (needs `requirements-dev.txt` + `playwright install chromium`):
```powershell
python .\scripts\browser_parity_smoke.py
python .\scripts\browser_parity_smoke.py --base-url http://127.0.0.1:5000
```

Migration audit (finds source-shell routes / hub-shell / empty-state gaps):
```powershell
python .\scripts\audit_migration.py --format json
```

Central odds refresh orchestrator (reuses each sport's real fetch entrypoints, then mirrors):
```powershell
python .\scripts\refresh_odds_sources.py --date 2026-05-18 --phase live --sports mlb,nba --json
```

Per-sport mirror refresh (populates `data/<sport>_source/`):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_mlb_source_mirror.ps1 -Date 2026-05-15
powershell -ExecutionPolicy Bypass -File .\scripts\refresh_nba_source_mirror.ps1 -Date 2026-05-17 -UseExistingMirrorArtifacts
```

There's also a `run-syndicate` Claude Code skill that launches the app and drives it headlessly to prove pages actually render — prefer it over guessing for UI verification.

## Architecture

### Render (web) vs. worker split — the load-bearing rule

This is the single most important architectural constraint in the repo (see `docs/ai_context/runtime_execution_model.md` and `worker_architecture.md`):

- **The web service does no heavy computation.** It only reads precomputed artifacts, hydrates responses, and does light transformation for display.
- **All simulation, artifact generation, enrichment, and evaluation happens in background workers** (`refresh-worker`, `live-odds-worker`) or offline scripts — never synchronously inside a Flask route handler.
- Workers write artifacts → Render reads artifacts. There is no path where a request handler recomputes a simulation or rebuilds a full game context from scratch.
- If data is missing at request time, the correct behavior is a degraded/empty UI state, not an on-request backfill.
- Render's Redis-backed disk cannot be shared between the web service and the worker (Render constraint) — shared mutable state (refresh manifests, run history, logs) goes through `syndicate/features/shared/refresh_state_store.py` with `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, not the filesystem.

When debugging a "missing data" symptom, work backward through the pipeline and find the first stage that's zero — don't start at the UI:
```
Odds sources -> candidate generation -> artifact generation -> artifact storage -> artifact read -> API response -> UI
```
Do not spend time on readers/hydration/endpoints/UI until candidate and artifact counts at the earlier stages are known. Production artifact/telemetry counts outrank unit-test success when triaging an incident.

### Layered system

1. **Artifact layer** — per-sport data ingestion, storage, manifests (`data/<sport>_source/`, `syndicate/features/shared/artifact_manifests.py`, `manifest.py`)
2. **Sim engine** — Monte Carlo predictions/edges/recommendations (`syndicate/features/simulation_engine.py`, per-sport `syndicate/features/<sport>/`)
3. **Intelligence layer** — query/reasoning over artifacts + sim output (`syndicate/features/intelligence*.py`, `pipeline/intelligence_*.py`)
4. **Evaluation layer** — accuracy, calibration, CLV, ROI (`syndicate/features/shared/intelligence_evaluation.py`)
5. **Experimentation layer** — policy comparison/selection/promotion (early stage)

`run_intelligence_query()` is worker-owned, not a free request-path primitive — routes should prefer cached intelligence state and let the background loop (`pipeline/intelligence_state.py`, `start_intelligence_state_background_loop`) own recomputation, so only one owner ever recomputes state concurrently.

### Directory map

- `app.py` — thin entrypoint (`from syndicate.app import app`)
- `syndicate/app.py` — Flask app factory: registers all sport blueprints, starts the live-refresh and intelligence-state background loops, has Render-specific bootstrap-on-start logic (`_bootstrap_render_data`) guarded by `SYNDICATE_BOOTSTRAP_ON_START`
- `syndicate/blueprints/` — one Flask blueprint per sport (`mlb.py`, `nba.py`, ...) plus `home.py`, `intelligence.py`, `ops.py`, `sports.py`, and the `ask_the_syndicate*` LLM-briefing blueprint family
- `syndicate/features/<sport>/` — per-sport feature logic (cards, game detail, picks, props, live-lens, archive) — MLB is the reference implementation other sports converge toward
- `syndicate/features/shared/` — cross-sport contracts and services: board contract (`game_board_contract.py`), live-lens contract/loop, odds framework/lifecycle/refresh-tracking, rank board, props pipeline (`basketball_props_*.py`), refresh state store
- `pipeline/` — the intelligence pipeline proper: entrypoint, models, evidence builder, formatter, performance aggregator, state loop
- `scripts/` — operational tooling: mirror refreshers (`refresh_<sport>_source_mirror.ps1`), the odds orchestrator, migration gate/audit, daily-update wrappers, browser smoke
- `data/<sport>_source/` — mirrored per-sport artifact bundles the app reads at runtime (git-tracked; can be swapped for a `SYNDICATE_ARTIFACT_ROOT_<SPORT>` published bundle)
- `reports/` — generated state: refresh manifests, migration gate reports, daily-update run manifests, intelligence state snapshots — mostly regenerated output, not hand-edited
- `vendor/` — vendored sibling-repo code pulled in directly (e.g. `vendor/wnba_betting_repo/`)
- `tests/` — ~200 files; pytest-style tests with fixtures in `conftest.py` (note the autouse fixture that clears wall-clock-TTL `lru_cache`s in WNBA cards between tests — a pattern to follow if you add similarly time-keyed caches)

### Module maturity (informs where to be careful vs. where active migration work happens)

MLB is the reference module (phase-1 complete, first fully local runtime contract — no source-app fallback). NBA, NHL, WNBA, NCAAF, NCAAB are active artifact-backed migrations at varying completeness. NFL is the next near-complete module-family candidate. New sport work should match the MLB `game_board_v1` contract (data parity, presentation parity, service parity) rather than inventing a new shape — see the "Shared integration contract" section of `README.md` before adding a new board surface.

### Coding conventions specific to this repo

- Prefer explicit data contracts (schemas/dataclasses/typed dicts) over ad-hoc dicts passed between layers.
- Keep orchestration (planners, state handlers) separate from domain logic (sim math, evaluation scoring).
- Avoid adding new source-app fallback dependencies — the direction is toward fully local, Syndicate-owned artifact generation per sport.
- Preserve existing script entrypoints as compatibility shims when refactoring the daily-update root rather than deleting them outright.
- When touching the daily-update system, distinguish refresh vs. sim vs. artifact vs. manifest vs. evaluation work explicitly — it's moving from a time-driven wrapper toward a state-aware execution controller with run modes (full/incremental/sim_only/manifest_only/etc.).

---

# Syndicate — Session Protocol

> This block is loaded into every Claude Code session in this repo.
> It is short on purpose. The detail lives in `.syndicate/`.

## The rule

`.syndicate/` is the source of truth for what is true about this system,
what is being worked on, and what we have already learned the hard way.
Your context window is not. If a fact only exists in this conversation,
it does not exist.

## Start of every session

1. Read `.syndicate/state.md` — current, verified system state.
2. Read `.syndicate/lanes.md` — what other sessions are holding.
3. Read `.syndicate/learnings.md` — the rules that came from past mistakes.

Do not begin work until you have done this. If the user's request
contradicts `state.md`, say so before proceeding.

## Before touching code

- Claim a lane: `/lane open <slug> "<goal>"`.
- If another OPEN lane lists a file you need, stop and surface the
  conflict. Do not edit across lanes.
- If the task is diagnostic, write the hypothesis into the lane
  **before** testing it, and record the result — including exoneration.

## Before any deploy

Run `/preflight`. It is a hard gate, not a formality.

## End of every session (or every ~30 min of real work)

Run `/checkpoint`. If the session ends without a checkpoint, the work
is considered lost — the next session will not trust it.

## Escalate to the systems engineer

Use the `syndicate-engineer` subagent for anything that needs a survey
of the repo or the ledger rather than a single edit:
"is this safe to change", "what do we already know about X",
"what should I pick up", "did we try this before". It reads wide and
reports narrow, so it does not burn this session's context.

## Non-negotiables

- Never claim a fix works without a measurement written to
  `.syndicate/deploys.md`.
- Never revert or re-enable something that `learnings.md` marks
  EXONERATED or FORBIDDEN without an explicit user override,
  logged.
- One change per deploy when diagnosing. Staggered, measured, logged.
