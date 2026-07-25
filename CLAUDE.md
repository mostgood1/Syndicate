# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Syndicate is a unified multi-sport analytics, simulation, and betting-intelligence platform (MLB, NBA, WNBA, NHL, NFL, NCAAF, NCAAB, soccer) that is progressively replacing separate sport-specific frontends. It is not "seven apps in one UI" — it is one Flask app with seven feature modules that must converge on the same board contract, artifact manifest, and intelligence layer.

The phased migration plan lives in `docs/syndicate_world_class_implementation_plan.md`. Read `README.md` for the full (long) operational reference — this file only covers what isn't obvious from the code.

## Outstanding work — read this first

**`docs/ai_context/todo.md` is the canonical cross-session TODO list.** Read it
before starting work and update it before finishing; don't keep a parallel list in
session-local task tools without reconciling it back. It carries the current
priority order, what has been *validated* against production versus merely
believed, and a set of operational facts that are expensive to rediscover — among
them: **Render auto-deploy is OFF** (pushing to `main` ships nothing on its own),
**deploying kills an in-flight MLB sim**, and `logger.info` never reaches Render's
log collector (use `print(..., flush=True)`).

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
