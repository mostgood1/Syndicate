# Syndicate End-to-End Context

> **Purpose.** This is the single orientation document for how Syndicate actually runs as a
> living system — how work moves between **local ↔ git ↔ Render**, how the **web/worker split**
> serves it, and how every feature subsystem (artifacts, board contract, simulation,
> intelligence, evaluation, Ask-the-Syndicate) fits together. Read this first when you need to
> code an improvement or diagnose a production bug fast. It is a map, not a substitute for the
> deep docs it links to.
>
> **Baseline:** written against `main` @ `bef3a026`, Python 3.11.9, Render blueprint in
> `render.yaml`. When a specific line number is cited, treat it as a *starting point that may
> drift* — verify the symbol still exists before relying on it.

**Golden rule that explains 80% of the architecture:** *the web service does no heavy
computation; workers write artifacts, the web reads them.* If you internalize only one thing,
make it this. Everything below is a consequence.

---

## 0. The 60-second mental model

```
                         ┌──────────────────────── RENDER (live source of truth) ─────────────────────────┐
                         │                                                                                 │
  The Odds API ─────────▶│  live-odds-worker ──┐                                                           │
  ESPN / StatsAPI  ──────▶│  refresh-worker  ──┼─▶ writes artifacts to its own 50GB disk                  │
                         │      (heavy compute) │       + POSTs "hot" artifacts ──▶ syndicate (web)        │
                         │                      │       + shared coordination via ──▶ syndicate-refresh-   │
                         │                      │                                       state (Redis/KV)   │
                         │  syndicate (web) ◀───┘  reads artifacts, hydrates, serves HTML/JSON. NO compute │
                         │      │  gunicorn wsgi:application, /healthz                                       │
                         └──────┼──────────────────────────────────────────────────────────────────────────┘
                                │  (2) GitHub Action pulls hot artifacts back over HTTP (daily 06:00 UTC)
                                ▼
  (1) You push code ──▶  GITHUB (mostgood1/Syndicate, branch main)  ──(3) manual/​hook deploy──▶ Render
                          • git = code transport + artifact BACKUP snapshot, NOT the live data path
                          • CI runs `unittest tests.test_archives` on push/PR
                                ▲
                                │  git pull / push
                          LOCAL (Windows, `py -3 app.py`, Flask dev server, filesystem state)
                          • full pipeline CAN run here (daily_update*.ps1) but normally doesn't
                          • local is a dev + validation mirror, never assumed complete
```

Three environments, three different jobs:

| Environment | Role | Compute? | State backend | "Truth"? |
|---|---|---|---|---|
| **Local** (Windows) | Develop, run gate/tests, optionally regenerate | Yes (dev-only) | filesystem (`reports/`, `data/`) | No — a mirror; assume incomplete |
| **Git** (GitHub) | Transport code; **snapshot/backup** of artifacts | CI only (archive tests) | git-tracked files | No — a durable backup |
| **Render** | Serve users + **own daily generation** | Workers only | Redis KV + per-service disks | **Yes** — the live source of truth |

> **Memory anchor** (`memory/project_render_source_of_truth.md`): *Render is source of truth; the
> local checkout is never assumed complete. Check prod before diagnosing a "data gap."* The daily
> GitHub Action **pulls** hot artifacts *from* Render and commits them to git — data flows
> Render→git, not git→Render, for the runtime bundles.

---

## 1. The three environments and how data moves between them

### 1.1 Local (developer machine)

- **Run:** `py -3 app.py` → `app.run(debug=True, use_reloader=False)` — a single-process Flask dev
  server. No gunicorn, no workers, no Redis.
- **State:** with no `RENDER`/hosted env vars set, `refresh_state_store` resolves to the
  **filesystem** backend; roots default to `<repo>/data` and `<repo>/reports`.
- **What local is for:** writing code; running the migration gate / archive tests / browser smoke;
  optionally regenerating artifacts via the PowerShell daily-update wrappers. Local **can** run the
  entire pipeline (`scripts/daily_update*.ps1`, `refresh_and_gate.ps1`) but in the current operating
  model that is a *fallback*, not the norm — Render owns daily generation.
- **The `run-syndicate` skill** launches the app + a headless browser to prove pages actually
  render. Prefer it over guessing for UI verification.

### 1.2 Git (GitHub `mostgood1/Syndicate`, default branch `main`)

Git plays **two** roles, and conflating them causes confusion:

1. **Code transport.** Normal: branch off `main`, PR, merge. `autoDeploy: false` in `render.yaml`,
   so **merging to `main` does not deploy** — deploys are manual or hook-triggered.
2. **Artifact backup snapshot.** The `data/**` and `reports/**` trees are git-tracked. They are a
   *durable backup* of what Render generated, refreshed by the daily backup Action (§1.4). This is
   why `git status` on this repo is perpetually noisy with modified JSON/JSONL/CSV under
   `data/` and `reports/` — those are regenerated artifacts, not hand edits. **Do not** treat that
   churn as meaningful diffs, and don't hand-edit generated artifacts.

**CI** (`.github/workflows/ci.yml`): on push/PR to `main`, Ubuntu + Py3.11, installs
`requirements.txt`, runs **only** `python -m unittest tests.test_archives` (the archive regression
suite — shared rank/game transport parity across MLB/NBA/NCAAB/NCAAF/NFL/NHL/WNBA). No deploy step.
This is the single automated gate on code changes; the fuller `migration_gate.py` is a *local*
pre-push tool, not wired into CI.

### 1.3 Render (production — the live system)

`render.yaml` (a Render **Blueprint**; there is no Procfile/Dockerfile/app.json) defines **four
resources**. All compute services are `env: python`, `plan: standard`, `autoDeploy: false`,
`buildCommand: pip install -r requirements.txt`.

| Resource | Type | Start command | Disk | Loops it runs |
|---|---|---|---|---|
| **`syndicate`** | web | `gunicorn wsgi:application` (2 workers, 1 thread, `/healthz`) | own 50GB @ `/opt/render/project/data` | none by default (compute offloaded) |
| **`refresh-worker`** | worker | `python scripts/run_refresh_worker.py` | own 50GB (same path) | intelligence-state loop; MLB sim; look-ahead; reconciliation; weekly-sports autorun |
| **`live-odds-worker`** | worker | `python scripts/run_live_odds_refresh_worker.py` | own 50GB (same path) | live-odds refresh loop; live-lens loop |
| **`syndicate-refresh-state`** | keyvalue (Redis/Valkey) | managed | — | — (shared coordination) |

Critical Render constraint: **a persistent disk attaches to exactly one service** — the three
compute services each mount their *own* 50GB disk at the same path, so they **cannot** share files.
Cross-service coordination therefore happens two ways:

- **Shared state** (refresh manifests, run history, per-lane indexes, intelligence-state queue) →
  the **Redis KV** service. `syndicate-refresh-state.connectionString` is injected as
  `SYNDICATE_REFRESH_STATE_URL` into all three compute services; all set
  `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`.
- **Hot artifacts** (the freshly generated per-sport files the web must serve) → workers **POST**
  them to the web service at `POST /api/ops/artifacts/publish` (auth `Bearer ADMIN_TOKEN`, allowlist
  via `is_hot_artifact_relative_path`), and pull via `GET /api/ops/artifacts/export`.
  `SYNDICATE_WEB_PUBLISH_URL=https://syndicate-an21.onrender.com` on both workers.
  Implemented in `syndicate/features/shared/artifact_publisher.py`; web endpoints in
  `syndicate/blueprints/ops.py`.

**Web URL:** `https://syndicate-an21.onrender.com`. **Deploy IDs** for scripted API calls live in
`deploy_ids.json` (`srv-…`/`dep-…` per service).

### 1.4 The daily cycle — who generates, who commits, who deploys

`.github/workflows/daily-update.yml` (cron `0 6 * * *` UTC + manual `workflow_dispatch`), on
`windows-latest`, has **two mutually exclusive paths** gated by the `run_full_pipeline` input:

- **Default = "backup-only"** (`run_full_pipeline != 'true'`): does **not** regenerate anything.
  It `GET {base_url}/api/ops/artifacts/export` (base `https://syndicate-an21.onrender.com`,
  `Authorization: Bearer ADMIN_TOKEN`), writes the pulled hot artifacts under `data/`, and commits
  as `github-actions[bot]`. **No redeploy** — the data is already live on Render. This path
  encodes the current reality: *"Render workers own the daily generation."*
- **Full pipeline = manual fallback** (`run_full_pipeline == 'true'`): runs
  `scripts/daily_update.ps1` / `daily_update_in_season.ps1` locally-in-CI, commits outputs, then
  **triggers a Render web redeploy** via `secrets.RENDER_WEB_DEPLOY_HOOK_URL`.

Always-run test gates in that workflow: `tests.test_daily_update_smoke` (soft), a
`tests.test_migration_gate` active-sport gate, and a batch of daily-update contract regressions.

**So the end-to-end lifecycle of a betting number is:**
```
live-odds-worker fetches odds ─▶ refresh_odds_sources.py generates candidates+artifacts on worker disk
   ─▶ worker POSTs hot artifacts to web  ─▶ web serves them to users (live)
   ─▶ (next 06:00 UTC) GitHub Action pulls them from web ─▶ commits to git as the backup snapshot
```

### 1.5 Startup bootstrap (how a fresh Render dyno gets its data)

Every service sets `SYNDICATE_BOOTSTRAP_ON_START=1`. On boot, `syndicate/app.py::_bootstrap_render_data`
runs `scripts/bootstrap_data_root.main`, which syncs the git-committed `data/**` and `reports/**`
seed trees into the mounted disk (`SYNDICATE_DATA_ROOT=/opt/render/project/data`). On the **web
dyno** this runs in a daemon thread that sleeps 20s and takes an atomic
`O_CREAT|O_EXCL` lock at `<data_root>/.bootstrap_sync.lock` — because `WEB_CONCURRENCY=2` means two
gunicorn workers each import the app with no `--preload`, and a synchronous bootstrap would 502 the
health check. This is the one place git→Render data flow still happens: the committed backup is the
**seed** a cold dyno starts from before the workers refresh it live.

---

## 2. Runtime architecture (the web tier)

### 2.1 App factory — `syndicate/app.py`

- Entrypoints: `app.py` (dev) and `wsgi.py` (`application = app`, prod gunicorn target) both import
  `app` from `syndicate.app`, where `app = create_app()` (module bottom).
- `create_app()` builds `Flask(template_folder="templates", static_folder="static")` →
  `syndicate/templates/`, `syndicate/static/`. It seeds `app.config["SYNDICATE_SPORTS"]` (8 sport
  descriptors driving the home/hub UI), `SYNDICATE_ACTIVE_SPORTS = ["mlb", "wnba"]`, and a context
  processor exposing `syndicate_sports` to every template.
- **Blueprint registration order matters:** `home → intelligence → ask_the_syndicate → ops → mlb →
  nba → nhl → nfl → wnba → ncaaf → ncaab → soccer → sports`. `sports_bp` (catch-all `/<sport_slug>`)
  is **last** so concrete sport prefixes win; it `abort(404)`s the 8 known slugs and only renders a
  generic hub for other configured slugs.

### 2.2 Blueprints (`syndicate/blueprints/`)

Every sport blueprint follows one shape: HTML `/cards` (+ root), JSON `/api/*` mirrors, game detail,
live-lens, market/accuracy, picks/props, archive, and season betting-card lanes. Internal names are
`syndicate_<sport>`.

| Blueprint | Prefix | Role | Notes |
|---|---|---|---|
| `home.py` | — | Home dashboard + **health/version** (`/healthz`, `/api/health`, `/versionz`) | 5.5k lines; cross-sport dashboard assembly |
| `intelligence.py` | — | Betting board / portfolio brain; `POST /api/intelligence/query`, `/api/portfolio/*` | status API *queues* refresh, never computes inline |
| `ask_the_syndicate.py` | — | NL Q&A; `POST /api/syndicate/query` | reads latest snapshot, optional LLM narration |
| `ops.py` | — | **All `/api/ops/*` + `/ops/*`** — admin-gated | see §2.4 |
| `mlb.py` | `/mlb` | Reference module; richest surface (HR/K/RFI/ladders, market board, season) | fully local |
| `nba.py` | `/nba` | Deepest live lane (`/api/live_state`, `live_player_lens`, …) | fully local (fallback removed `35e0b4d5`) |
| `nhl.py` | `/nhl` | Cards/picks/props-reconciliation/props-lines; no game_detail | |
| `wnba.py` | `/wnba` | Mirrors NBA live lanes; serves own CSS/JS/logos | source-app fallback present |
| `nfl.py` | `/nfl` | **Weekly** cadence; `/api/weeks` | leans on `features/football/` engine |
| `ncaaf.py` | `/ncaaf` | Weekly; own `smartsim2` engine + CFBD | |
| `ncaab.py` | `/ncaab` | Partial (no picks/props); `/results` season archive | |
| `soccer.py` | `/soccer` | Only league-parameterized (`/soccer/<league>/…`); SoccerSim | picks ship (no /picks route); no settlement/accuracy lanes |
| `sports.py` | — | Catch-all generic hub | 20 lines |

Some assets are served through **blueprint routes** (not `/static`) so they can be versioned or
sourced from feature dirs — e.g. `/mlb/assets/cards.css`, `/nba/assets/betting-card-v2.js`,
`/wnba/styles.css`, WNBA team-logo SVG routes.

### 2.3 Routes read, they don't compute (verified pattern)

Handlers resolve a date/week, delegate to a feature-layer builder that **reads precomputed
artifacts**, then `jsonify`/`render_template`. Canonical examples:
- `mlb.py api_cards()` → `build_cards_page_context(date)` (reads processed CSV/JSON) →
  `build_game_board_api_payload`; the handler only reshapes + attaches `sources` paths.
- `intelligence.py intelligence_status_api()` → `read_latest_intelligence_state(...)`; if stale, it
  only **queues** a refresh (`_safe_queue_intelligence_state_refresh`) for the worker — never runs
  `build_intelligence_overview` inline.
The heavy compute lives in §2.5 loops and in `scripts/`+`pipeline/` jobs. On Render web dynos the
loops are disabled entirely, which is what structurally enforces the golden rule.

### 2.4 Ops blueprint (`syndicate/blueprints/ops.py`) — the control plane

`@ops_bp.before_request _require_admin_token()` gates **every** ops route (503 if `ADMIN_TOKEN`
unset; 401 on mismatch; accepts `Authorization: Bearer`, `X-Admin-Token`, `?admin_token=`, or form).
Key endpoints:
- Refresh control: `GET /api/ops/odds-refresh/status|plan|logs`, `POST …/run`, `POST …/cancel`,
  `POST /api/ops/full-refresh/run`.
- Artifact transport: `POST /api/ops/artifacts/publish` (worker→web push, allowlisted, traversal-
  guarded), `GET /api/ops/artifacts/export` (backup-Action pull + worker pulls).
- Observability: `GET /api/ops/version`, `/api/ops/memory` (per-process RSS for OOM tuning),
  `/api/ops/live-refresh/state` (reads the loop state files), `/api/ops/intelligence/candidate-trace`
  (reproduces the worker's candidate path to root-cause **zero-candidate** boards),
  `/api/ops/mlb/sims-list|live-check`, `/api/ops/wnba/artifact-counts|status-trace`.
- Force levers: `POST /api/ops/live-refresh/force-mlb-resim` (invalidate sim fingerprints for
  specific `game_pks`), `POST /api/ops/live-refresh-loop/reset-lineup-gate`,
  `POST /api/ops/bootstrap/run`.
- HTML: `GET /ops/odds-refresh` (status + plan form).

These are your **first-line production debugging tools** — see §7.

### 2.5 Background loops (worker-owned)

Both start from `syndicate/app.py::_start_background_loops`; on a Render web dyno they start **only**
if `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` is truthy (it isn't on web), so the web
tier normally runs neither.

- **Intelligence-state loop** (`pipeline/intelligence_state.py`,
  `start_intelligence_state_background_loop`) — runs on **refresh-worker**. Daemon thread
  `syndicate-intelligence-state-loop`; interval `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS`
  (default 30, min 10). Single-ownership: in-process lock + non-blocking `_execution_guard` +
  module-level `_INTELLIGENCE_EXECUTION_GUARD`. The **web queues** work through the shared state
  store; the **worker drains** it. Writes intelligence snapshots (§5).
- **Live-refresh loop** (`syndicate/features/shared/live_refresh_loop.py`,
  `start_live_refresh_background_loop`) — runs on **live-odds-worker**, gated by
  `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP`. Single-ownership: in-process lock **plus** a
  cross-process OS advisory file lock (`fcntl.flock`/`msvcrt.locking`). Each tick fetches live
  odds/state, fires gated recomputes (MLB daily-sim, lineup/injury, look-ahead), republishes hot
  artifacts, and writes `reports/live_refresh_loop/latest_live_refresh_tick.json` (+ gate-state
  files). Interval is **adaptive** (`SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS` default 60, idle
  interval when nothing is live).
- **Live-lens loop** (`syndicate/features/shared/live_lens_loop.py`) — also on live-odds-worker,
  gated by `SYNDICATE_ENABLE_LIVE_LENS_LOOP`. Covers **MLB, NBA, WNBA, soccer**
  (`_LIVE_LENS_SPORTS`; soccer added 2026-07-31). Per tick: builder →
  validator → `write_json_file(snapshot_path)`. MLB's `estimate_live` runs a real 120-sim Monte
  Carlo per live game (memory-gated); soccer resimulates each in-progress match from live state
  (`poll_soccer_live_state.py`).

---

## 3. The data & artifact pipeline

The canonical chain (worth memorizing — §7 debugs it backwards):
```
Odds sources → candidate generation → artifact generation → artifact storage
             → artifact read → API response → UI
```

### 3.1 Stage-by-stage

| Stage | Code | Output |
|---|---|---|
| Odds sources | `scripts/refresh_<sport>_oddsapi*.py` (MLB/NBA/NHL/NCAAB/NFL/WNBA/soccer) | raw odds snapshots |
| Candidate + artifact generation | orchestrated by `scripts/refresh_odds_sources.py` (`REGISTRY`/`SportSpec`/`RefreshStep`, per-sport `_build_<sport>_steps`) | predictions/edges/recommendations/live-lens |
| Artifact storage | `data/<sport>_source/` bundles + published manifests (`manifest.py::publish_sport_manifest` → `reports/manifests/<sport>.json`) | bundle + manifest |
| Artifact read | `artifact_manifests.py::load_artifact_manifest` (published-first, else FS scan) + per-sport readers | in-memory context |
| API response | `syndicate/blueprints/<sport>.py` + `game_board_contract.py` + `live_lens_contract.py` | JSON/HTML |
| UI | templates + shared polling | degraded/empty if artifacts missing |

Worker runtime invocation chain: `live_refresh_loop._run_live_refresh_tick` →
`ops_refresh.launch_refresh_run` → subprocess `scripts/run_refresh_odds_job.py` →
`scripts/refresh_odds_sources.py`.

### 3.2 The per-sport bundle (`data/<sport>_source/`, reference `data/mlb_source/`)

- `source_artifacts/` — raw mirrored source bundle (`data/{daily,live_lens,market,eval,processed,
  raw,statcast,tuning,…}`; the statcast BvP cache is ~32k hashed JSON files).
- `data/` — the working tree the app reads (`daily/daily_summary_<date>.json` + variants,
  `live_lens/live_lens_<date>.jsonl`, `market/`, `eval/`, …).
- `manifests/` — `mirror_refresh_<date>.json` + `mirror_refresh_latest.json` (fields:
  `copiedArtifactCount`, `artifactGroups`, `usedArtifactBundle`, `missingOddsSnapshots`,
  `copiedArtifacts`). The migration gate validates this for the core MLB artifact families.
- `tracking/` — `odds_history.json` + per-day odds-tracking CSVs (game-lines/props: history /
  opening / movement-signals triplets).

Mirror scripts `scripts/refresh_<sport>_source_mirror.ps1` populate the bundle. Two modes: default
(prefer repo-owned bundle / published `SYNDICATE_ARTIFACT_ROOT_<SPORT>`) and
`-UseExistingMirrorArtifacts` (rebuild manifest from already-mirrored files — hosted-safe ingest).

### 3.3 Manifests — `manifest.py` (writer) + `artifact_manifests.py` (reader)

- Writer: `publish_sport_manifest(sport, artifact_paths, metadata)` → `reports/manifests/<sport>.json`
  via `refresh_state_store.write_json_file` (KV-aware). Payload: `sport`, `last_updated`,
  `artifact_paths`, `status` (`complete`/`failed` — forced `failed` if
  `metadata.required_artifact_failures`), `metadata` (incl. `refresh_contract` required/optional
  artifact families + nested `odds_control_plane`).
- Reader: `load_artifact_manifest(slug, date)` → published-manifest first, else `_load_scanned_manifest`
  (FS scan over sport roots honoring `SYNDICATE_<SPORT>_SOURCE_ROOT`/`_ARTIFACT_ROOT`, classifying
  files into `ARTIFACT_CATEGORIES = (predictions, edges, recommendations, live_data)`).

### 3.4 Shared state store — `syndicate/features/shared/refresh_state_store.py`

The seam that makes the multi-service Render deploy coherent.
- **Backend selection:** explicit `SYNDICATE_REFRESH_STATE_BACKEND` wins; else if hosted
  (`RENDER`/`SYNDICATE_REQUIRE_HOSTED_STORAGE`) **and** a URL present → `keyvalue`, else `filesystem`.
  `assert_refresh_state_backend_ready` **hard-fails** a hosted multi-service deploy that tries to use
  a local file backend.
- **filesystem:** atomic temp-file + `os.replace`; JSON under `<repo>/reports/`.
- **keyvalue (Redis/Valkey):** keys namespaced `syndicate:…`; `redis.from_url` (lru_cached), one-retry
  reconnect on `ConnectionError`. `read_json_file_result` returns `(payload, read_ok)` so a transient
  store failure is distinguishable from "key absent" (used by the refresh concurrency guard).
  **Gotcha (fixed 2026-07-23):** `delete_text_file` must actively delete KV copies — a filesystem-only
  unlink once left stale KV keys serving stale boards.
- Stores: `reports/refresh_state.json` (step-level incremental-compute ledger — `should_recompute`/
  `record_refresh_state`, `build_input_hash`/`path_fingerprint`), refresh-status history index
  (`syndicate:refresh-state-history`, capped 50), known-lane index, and the intelligence-state queue.
- **Per-service lanes:** `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES=true` + `SYNDICATE_REFRESH_LANE=<service>`
  give each service its own refresh mutex lane (fixes a globally-shared-mutex starvation bug).

### 3.5 Odds framework (`syndicate/features/shared/odds_*.py`)

- `odds_framework.py` — `normalize_odds_entry` → canonical candidate dict (market/model prob, `edge`,
  `confidence`, `rank_score`); `rank_normalized_odds_entries` sorts by `(rank_score, |edge|, confidence)`.
- `odds_control_plane.py` — resolves odds-history roots with precedence
  `shared_history → artifact_history → tracking_history`; shard key = date (daily) or `<season>_wk<week>`
  (NFL/NCAAF). Writes `reports/odds_control_plane/latest.json`.
- `odds_lifecycle.py` — per-date event log; `build_market_history_view`/`build_market_features`
  (line movement, implied prob from American odds) feeding line-movement UI.
- `odds_refresh_tracking.py` — `sync_sport_post_refresh_tracking(...)` (called by the orchestrator)
  reads fresh snapshots, computes lifecycle events + movement signals, persists odds-history shards
  to all three precedence locations, writes tracking CSVs, and **re-scores impacted recommendations**.

### 3.6 `reports/` generated state (what's actually in there)

`refresh_state.json` (incremental ledger) · `refresh_status/…/refresh_status_latest.json` +
`refresh_worker_status.json` · `manifests/<sport>.json` (8) · `odds_control_plane/latest.json` +
`odds_history/<sport>/<shard>.json` · `intelligence/*` (§5) · `migration_gate/` · `daily_update/…` ·
`live_refresh_loop/` (tick + gate state) · `live_lens_loop/` (tick + status + lock) ·
`performance_summary.json`. Plus stray `tmp_*` scratch — **not** part of the contract.

---

## 4. Feature modules & the shared board contract

### 4.1 `game_board_contract.py` — the convergence point

Every sport's card/board funnels through here so one frontend contract serves all sports.
- `apply_game_board_contract(context, *, sport, module, schema="game_board_v1", …)` normalizes a
  per-sport context: stamps a `board_contract` block (`schema=game_board_v1`,
  `surface=<sport>_dense_board_v1`, `sport`, `module`, `source_kind`, `live_lens_integrated`) and runs
  each game through `_normalize_game` → `normalize_publication_game`, attaching a family of `shared_*`
  presentation keys that templates consume regardless of sport: `shared_is_live`, `shared_period_rows`
  (per-inning/quarter/half projections + a summed "Full Game" row), `shared_probability_rows`,
  `shared_total_rows`, `shared_box_sections`, `shared_prop_rows`, `shared_top_play_rows`, `market_tiles`.
- `build_game_board_api_payload(context)` serializes the uniform API envelope (`games`, `scoreboard`,
  `board_contract`, `live_lens_contract`, `pregame_portfolio`, `nav`, dual camel/snake aliases).
- `build_single_game_board_context(...)` — single-game convenience wrapper.

**The three "parities"** are enforced concretely, not just conceptually:
- **Data parity** — `normalize_publication_game` guarantees every non-MLB/WNBA game carries
  `shared_game_state`/`shared_predictions`/`shared_markets` in the MLB shape (MLB & WNBA short-circuit
  because they emit it natively). `publish_parity.py` audits that each sport actually published the
  expected artifact paths.
- **Presentation parity** — the `shared_*` builders mean one template renders every sport; a sport
  missing a lane gets a graceful placeholder (`_build_box_sections` → "Box score unavailable").
- **Service parity** — `build_game_board_api_payload` emits the same envelope for every sport.

> **Web-dyno gate:** the heavy `simulation_contract` build is skipped on the request-serving web dyno
> (`_render_web_dyno()` via `SYNDICATE_WEB_DYNO`) and computed off-request. Another instance of the
> golden rule.

### 4.2 Per-sport modules (`syndicate/features/<sport>/`) & maturity

| Sport | Board | game_detail | picks | props | live_lens | archive | source-app fallback | Status |
|---|---|---|---|---|---|---|---|---|
| **MLB** | ✅ (`cards.py` 5.5k) | ✅ | in cards | `top_props` | ✅ | ✅ | **None (fully local)** | **Reference / complete** |
| **NBA** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **None** (HTTP fallback removed `35e0b4d5`; producer script still shells into `vendor/nba_betting_repo`) | complete; serving path fully local |
| **WNBA** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **In-repo vendor only** (`_load_source_app` loads `vendor/wnba_betting_repo/app.py` in-process; no network) | complete; ~90% local |
| **NHL** | ✅ | ❌ | ✅ | `props_lines`+reconciliation | ✅ | ✅ | No | mostly complete; no game_detail |
| **NFL** | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | No | lean; uses `features/football/` engine (weekly) |
| **NCAAF** | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | No | own `smartsim2_*` engine + `cfbd.py` (weekly) |
| **NCAAB** | ✅ | ✅ | ❌ | ❌ | ✅ | `results_archive` | No | most partial |
| **Soccer** | ✅ | ✅ | ✅ (`picks_{date}.csv`, no `/picks` route) | ✅ | ✅ | ✅ | No | self-contained (`soccersim`); league-parameterized |

- **MLB is the only fully-local sport** (canonical `card_variant="mlb_main"`, short-circuited in both
  `_normalize_game` and `normalize_publication_game`; `mlb/sources.py` resolves purely from
  `data/mlb_source/`).
- **No external source-app HTTP fallback remains** (verified 2026-08-02: zero `SOURCE_APP` hits in
  `syndicate/`). NBA's HTTP fallback was deleted in `35e0b4d5`; WNBA's only residual coupling is
  `SYNDICATE_WNBA_SOURCE_APP_FALLBACK` gating an **in-process** load of the vendored
  `vendor/wnba_betting_repo/app.py` (no network), used for live-lines/live-state exports after
  local builders are tried first. The broad `fallback` grep (600+ hits) is otherwise defensive
  `_safe_*(…, fallback=…)` and local artifact-date fallbacks — **not** external dependencies.
- `features/football/` is a shared NFL/NCAAF **engine** package (ingestion + `sim_engine/smartsim2` +
  evaluation), not a board sport.

### 4.3 Simulation engine — `syndicate/features/simulation_engine.py`

A generic Monte Carlo engine (`SimulationEngine.run_monte_carlo(context, iterations=1000)` →
frozen `SimulationResult` with distributions/EVs/variance). Sport-aware std-dev model
(`_baseline_std_dev`: MLB/NHL `×0.18`, NBA/WNBA/NCAAB `×0.12`, NFL/NCAAF `×0.14`, plus stat-keyword
branches). Win prob from `model_probability`/`confidence` nudged by clamped `edge`.

**Per-sport sims plug in via composition, not subclassing:** `shared/simulation_adapter.py`
`_normalize_game_context` maps each sport's `game.sim`/`betting`/`live_state` into the generic
engine context; `build_simulation_contract_from_context` is what the board contract calls to attach
`simulation_contract`; `SPORT_ADAPTERS` maps each slug to its `cards.build_cards_page_context`
loader. Bespoke engines (soccer `soccersim`, NFL/NCAAF `smartsim2`, basketball
`basketball_props_smart_sim.py`) run upstream and hand results in as `sim` payloads.

### 4.4 Recommendations / candidates — `syndicate/features/shared/recommendation_engine.py`

Two-stage pipeline (both memoize per-market reliability profiles — a real 48.5s/161-candidate
regression drove that):
- `filter_candidates(...)` — reprices probabilities, computes `edge` via `calculate_edge`, applies a
  **per-market dynamic threshold** (base `min_edge + policy.min_edge_bias`, raised when market ROI
  < −0.04, calibration error > 0.18, or reliability multiplier < 0.88). Survivors enriched with
  `fair_probability`, `edge`, `expected_value`, `risk_flags`, `recommendation_id`, `model_version`.
- `rank_recommendations(...)` — selects a policy (§5.5), filters, then scores survivors by per-market
  reliability + repriced probabilities + tracking snapshot; optionally truncates to `limit`.

### 4.5 Live-lens contract (`shared/live_lens_contract.py`)

`attach_live_lens_contract(context, sport, module, refresh_interval_ms=30000, …)` is the read-side
shaping: Central-timezone-normalizes `generatedAt`/`oddsRefreshedAt`, attaches a `refresh_policy`
(`intervalMs`, `refreshOnVisible/Focus`, `poller: "shared.polling"`) and a `live_lens_contract`
block (`schema: live_lens_v1`). The worker produces the snapshot; the route attaches the contract;
the client re-fetches on the policy interval. Per-sport request-path readers (e.g.
`mlb/live_lens.py`, freshness-gated by `MLB_LIVE_LENS_REPORT_MAX_AGE_SECONDS` default 60s) hydrate
the snapshot through `apply_game_board_contract` + `attach_live_lens_contract`.

---

## 5. Intelligence, evaluation & Ask-the-Syndicate

### 5.1 The intelligence pipeline (`pipeline/`)

- `intelligence_entrypoint.py` — `run_routed_intelligence_pipeline()` routes via `QueryRouter`, tries
  `acquire_intelligence_execution_guard`; if another compute is in flight it returns
  `get_latest_intelligence_cached_response()` instead of recomputing.
- `intelligence_pipeline.py` — `run_intelligence_pipeline()` runs 4 timed stages:
  `input_normalization` → `context_enrichment` → `intelligence_call` (the black box
  `features/intelligence.run_intelligence_query()`, 2 retries then partial fallback so the UI never
  breaks) → `post_processing` (builds `IntelligenceResult`, evidence, structured response, evaluation
  record). Compound/comparison/risk questions get optional multi-step reasoning decomposition.
- `intelligence_models.py` (frozen `Evidence`/`Insight`/`IntelligenceResult`), `evidence_builder.py`
  (deduped evidence records), `formatter.py` (thin response wrapper).

### 5.2 Intelligence **state** & the recomputation owner (`pipeline/intelligence_state.py`, 2.6k lines)

"Intelligence state" = a persisted, per-date snapshot of the fully-computed betting board (ranked
candidates, `by_sport`, board contract, live-pipeline summary, metadata). **It is the authoritative
served artifact — request handlers read it, they don't rebuild it.**

- `IntelligenceStateService` (singleton) daemon loop drains a shared queue, acquires
  `_execution_guard`, calls `_compute_board_publication_response()` → `write_latest_intelligence_state()`.
- **Ownership:** web (`SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`) **queues** work;
  refresh-worker (`true`) **drains** it. Queue crosses processes via the shared state store.
- `candidate_count` is deliberately derived from `by_sport` totals (the true pool), **not** the
  request-sliced `top_opportunities` — this is the fix for the "stuck at 10" bug (documented in-file).
- **Canonical-board migration** (flag `SYNDICATE_INTELLIGENCE_CANONICAL_BOARD_STATE`, shadow-compared):
  `_build_intelligence_board_state()` writes one unsliced file per date
  (`board_state_<date>.json` + `board_state_latest_pointer.json`);
  `slice_intelligence_board_state_for_request()` is the pure read-time narrower. A canonical build can
  exceed 10 minutes, so it drains on a **separate** thread.

Files under `reports/intelligence/`: `intelligence_state.json` (+ dated),
`intelligence_state_history.jsonl` (append-only time series of top opportunities/candidate depth),
`board_snapshot.json` (+ dated), `board_state_<date>.json`, plus caches
(`query_state_cache.json`, `status_response_cache.json`, `live_pipeline_last_successful.json`).

### 5.3 The black box (`syndicate/features/intelligence.py`, ~7.5k lines)

`run_intelligence_query(question, *, selected_date, mode, sport, limit, include_props, include_games,
policy, force_refresh, …)` builds preferences, resolves date, calls `build_intelligence_overview()`,
loads per-sport odds history + advanced signals, ranks candidates over artifacts + sim output, and
`record_prediction`s into the prediction ledger. `intelligence_state.py` imports the ranking helpers
(`rank_global_recommendations`, `collect_candidates_with_fallback_merge`,
`_balanced_recommendation_order`, `_greedy_low_correlation_selection`, `candidate_identity_key`).

### 5.4 Evaluation layer (`shared/intelligence_evaluation.py`, 1.5k lines)

Records `IntelligencePredictionRecord`/`RecommendationRecord`/`PortfolioEventRecord` (stable SHA1
IDs) via `build_intelligence_evaluation_bundle()`. **Storage is date-chunked** under
`reports/intelligence/evaluation_ledger_chunks/` with `index.json` (dedupe) + `manifest.json`.
`compute_metrics` (latest-per-rec-id + settled): **win rate** (`_win_rate`), **ROI** (`_roi`),
**CLV** (`_clv`: `(open−close)×direction`), **calibration** (`_calibration`: MAE + Brier).
`build_reliability_profile()` → `reliability_multiplier` (0.78–1.06) → `adjust_confidence()`;
`build_recommendation_performance_analytics()` aggregates by sport/market/tier/edge-bucket. This is
the feedback loop that tightens the per-market thresholds in §4.4.

### 5.5 Experimentation / policy promotion (`shared/recommendation_engine.py`)

`POLICY_REGISTRY = {balanced (default/incumbent), conservative, aggressive}` (`DecisionPolicy` with
edge/confidence/roi/calibration/market_fit weights + `promotion_margin`/`min_sample_size`).
`compare_policies()` scores each over settled ledger rows → `promotion_score`.
`build_policy_optimization_summary()` promotes the leader **only if** samples ≥ `min_sample_size`
AND `lead_delta ≥ promotion_margin`; within-margin + an `experiment_key` present → A/B split via
`_policy_bucket()` (SHA1 mod 100). Each recommendation carries `decision_strategy` +
`historical_profile.policy_comparison`. Early-stage but functional.

### 5.6 Prediction ledger (`data/prediction_ledger.json`, ~2.4MB) — distinct from the eval ledger

`{schema_version, predictions:[], results:[], updated_at}`. Writer
`syndicate/features/prediction_ledger.py` (`record_prediction`/`record_result`, path via
`data_root()`). Callers: portfolio bet-record API (`blueprints/intelligence.py`), auto-record during
query (`features/intelligence.py`), settlement (`prediction_reconciliation.py`). `record_result` also
nudges `data/signal_weights.json` (a lightweight online learner, ±0.03·contribution, clamped
0.5–1.5). `pipeline/performance_aggregator.py` prefers the eval ledger and **falls back** to the
prediction ledger, writing `reports/performance_summary.json`.

### 5.7 Ask the Syndicate (`syndicate/blueprints/ask_the_syndicate*.py`)

`POST /api/syndicate/query`. Routes intent (`bet_analysis`/`matchup_analysis`/`market_summary`/
`comparison`), reads the **latest persisted snapshot** (canonical state → board snapshot → worker
state — **never recomputes**), attaches deterministic `visuals` from `collect_focused_evidence`, and
if a snapshot exists calls `generate_briefing()`.
- **LLM engine** (`_engine.py`): Anthropic Claude via the `anthropic` SDK, default model
  `claude-haiku-4-5` (override `SYNDICATE_ASK_MODEL`), enabled only when `ANTHROPIC_API_KEY` set and
  `SYNDICATE_ASK_LLM_ENABLED ≠ false`. `max_tokens=2048`, per-process sliding-window rate limiter
  (`SYNDICATE_ASK_LLM_MAX_CALLS=30` / `_WINDOW_SECONDS=600`). Output is a JSON briefing enforced by
  `BRIEFING_SCHEMA` (`headline, verdict, confidence, narrative, key_drivers, risks, invalidators,
  top_picks, data_quality_note`).
- **Honesty guarantee:** `_data.py` computes *all numbers in Python* from sim artifacts on disk; the
  LLM only narrates them (system prompt: sim primary, market secondary, no fabrication). Without
  `ANTHROPIC_API_KEY`, responses degrade to snapshot-only (`answer_source="snapshot"`).

---

## 6. Environment variable reference (the load-bearing ones)

| Var | Controls | Prod value / default |
|---|---|---|
| `SYNDICATE_REFRESH_STATE_BACKEND` | shared-state backend | `keyvalue` on all 3 services; local → `filesystem` |
| `SYNDICATE_REFRESH_STATE_URL` (`REDIS_URL` fallback) | KV connection | injected from `syndicate-refresh-state` |
| `SYNDICATE_REQUIRE_HOSTED_STORAGE` | force hosted mode (data/reports roots mandatory) | `true` on all 3 |
| `RENDER` | platform flag (also flips hosted on) | set by Render |
| `SYNDICATE_BOOTSTRAP_ON_START` | sync committed seed → mounted disk on boot | `1` all 3 |
| `SYNDICATE_WEB_DYNO` | mark web process (async-locked bootstrap; skip heavy sim-contract) | web `true`, workers `false` |
| `SYNDICATE_DATA_ROOT` / `SYNDICATE_REPORTS_ROOT` / `SYNDICATE_STATE_ROOT` | data/reports roots | `/opt/render/project/data[/reports]` |
| `SYNDICATE_<SPORT>_SOURCE_ROOT` | per-sport source tree | `/opt/render/project/data/<sport>_source` |
| `SYNDICATE_ARTIFACT_ROOT_<SPORT>` | optional published bundle for ingest | **not set in render.yaml** (deployment-specific) |
| `SYNDICATE_WEB_PUBLISH_URL` | worker→web artifact push/pull base | `https://syndicate-an21.onrender.com` on workers |
| `ADMIN_TOKEN` / `SYNDICATE_ADMIN_TOKEN` | ops-endpoint + publish auth | generated on web, shared to workers |
| `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` | intelligence loop | web/live-odds `false`, refresh-worker `true` |
| `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP` | live-odds loop | **only** live-odds-worker `true` |
| `SYNDICATE_ENABLE_LIVE_LENS_LOOP` | live-lens sweeps | on for live-odds-worker |
| `SYNDICATE_REFRESH_RUN_PER_SERVICE_LANES` + `_LANE` | per-service refresh mutex | `true`; lane = service name |
| `SYNDICATE_REFRESH_LAUNCH_MODE` | how ops launches refresh (`detached_subprocess`/`manifest_only`/`external_runner`) | `detached_subprocess` |
| `SYNDICATE_INTELLIGENCE_REFRESH_INTERVAL_SECONDS` | intel loop interval / freshness SLA | 30 (min 10) |
| `SYNDICATE_LIVE_ODDS_REFRESH_INTERVAL_SECONDS` | live loop base interval | 60 (adaptive idle) |
| `SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS` | periodic self-exit (Render restarts → cache reset) | 21600 (6h ±10%) |
| `ODDS_API_KEY` | The Odds API | **hardcoded in render.yaml** ⚠ (see §8) |
| `ANTHROPIC_API_KEY` | Ask-the-Syndicate LLM | `sync:false` (set in dashboard; absent → snapshot-only) |
| `SYNDICATE_ASK_MODEL` / `_LLM_MAX_CALLS` / `_LLM_WINDOW_SECONDS` | Ask model + rate limit | `claude-haiku-4-5` / 30 / 600 |
| `WEB_CONCURRENCY`, `GUNICORN_*` | gunicorn tuning | web workers=2; timeout 60/30/5 |
| `TZ`, `PYTHON_VERSION` | timezone, python | `America/Chicago`, `3.11.9` |

---

## 7. Debugging discipline — where to look first

**Never start at the UI.** Work *backwards* through the pipeline and find the first stage that is
zero. Production artifact/telemetry counts outrank unit-test success when triaging an incident.

```
Odds sources → candidate gen → artifact gen → artifact storage → artifact read → API → UI
             (find the FIRST stage that's 0; don't touch readers/UI until earlier counts are known)
```

Triage checklist for a "missing data" / "empty board" symptom:
1. **Which environment?** Render is truth. A local gap usually means nothing (local isn't refreshed).
   Reproduce against `https://syndicate-an21.onrender.com` before touching code.
2. **Is it pipeline / runtime / deployment?** (per `runtime_infrastructure.md`)
   - pipeline-level → data never generated (check worker logs, `refresh_status`, manifests);
   - runtime-level → data generated but not consumed (check readers/contract);
   - deployment-level → web/worker split or a stale rollout.
3. **Ops endpoints (admin-token gated) are your instruments:**
   - `GET /api/ops/odds-refresh/status` + `/logs` — did the refresh run/fail?
   - `GET /api/ops/live-refresh/state` — is the live loop ticking? last tick/error/anyLive?
   - `GET /api/ops/intelligence/candidate-trace` — reproduces the worker candidate path to root-cause
     a **zero-candidate** board.
   - `GET /api/ops/<sport>/artifact-counts` / `mlb/sims-list` / `mlb/live-check` — artifact existence.
   - `GET /api/ops/memory` — per-process RSS if you suspect OOM.
   - `GET /api/ops/version` — confirm the deployed commit (rule out stale rollout).
4. **Force levers when a gate is stuck:** `POST /api/ops/live-refresh/force-mlb-resim` (specific
   `game_pks`), `POST /api/ops/live-refresh-loop/reset-lineup-gate`.
5. **State-store sanity:** if boards look *frozen/stale*, suspect KV vs filesystem staleness
   (the `delete_text_file` class of bug) or the intelligence-state queue not draining
   (web queues / refresh-worker drains).

**Local repro of the full pipeline** (when you must): `refresh_and_gate.ps1` (refresh mirrors + gate)
or `refresh_odds_sources.py --dry-run --json` (resolve the command plan without executing).

---

## 8. Known sharp edges, gotchas & tech debt

- **⚠ `ODDS_API_KEY` is hardcoded in `render.yaml`** (committed to git). Treat as a real secret-hygiene
  issue: rotate it and move to a dashboard-only `sync:false` var. (Do not paste the value into logs,
  PRs, or docs.)
- **The three compute disks are NOT shared.** Any instinct to "write a file on the worker and read it
  on the web" is wrong — it must go through KV (state) or the publish/export HTTP path (artifacts).
- **Git churn is noise.** `data/**` and `reports/**` diffs are regenerated artifacts. Don't review
  them as code; don't hand-edit generated artifacts; don't `git add -A` blindly.
- **`autoDeploy:false`** — merging to `main` does not deploy. Deploys are the full-pipeline Action's
  hook or a manual Render deploy.
- **Fail-closed on KV read errors.** Several gates (look-ahead, refresh concurrency) deliberately treat
  a transient KV read failure as "unknown," *not* as "never happened / nothing running." Preserve that
  semantics (`read_json_file_result` returns `(payload, read_ok)`) when editing those paths.
- **Memory is a first-class constraint** on the workers. WNBA's refresh leg is the measured OOM
  offender and is deferred under headroom pressure (`SYNDICATE_LIVE_LENS_MIN_HEADROOM_MB` default
  1800MB); MLB sim ownership was moved to refresh-worker to isolate it; live-odds-worker self-recycles
  every ~6h. `pandas==2.2.2`, `onnxruntime==1.22.0` are pinned for a reason — don't bump casually.
- **NBA serving is fully local; WNBA is ~90% local** — the NBA HTTP source-app fallback was removed
  (`35e0b4d5`; `render.yaml`'s `SYNDICATE_NBA_SOURCE_APP_FALLBACK` blocks are dead config). WNBA's
  residual coupling is the in-repo vendored app loaded in-process for a few live exports, plus the
  vendored `cards-parity.js` frontend (`wnba/source_proxy.py` is a static-asset rewriter, not a
  network proxy). The migration direction is still to eliminate these; don't add new ones.
- **Repo-root clutter** — the `tmp_*` scratch, `ops_state_check*.json`, `ops_status.json`, and
  `prod_final_check.html` debug dumps were removed (see cleanup below); `.gitignore` covers
  `tmp_*.{log,json,py,txt,xml}` to stop recurrence. **`deploy_ids.json`** is intentionally kept —
  it holds the Render `srv-…`/`dep-…` IDs for scripted deploys. The 51 former root `*_report.md` files
  (`smartsim_*`, `ncaaf_*`, `nfl_*`, `soccersim_*`) were relocated to `docs/reports/` (substantive
  committed analysis reports, not dead code); the six `scripts/build_ncaaf_*_snapshot.py` generators
  that write those reports were repointed to `docs/reports/`.
- **`vendor/` is live code, not legacy** — `vendor/mlb_bettingv2` is imported by
  `syndicate/features/mlb/live_lens.py` and `scripts/run_live_odds_refresh_worker.py`; the
  `vendor/{nba,wnba}_betting_repo` trees back `schedule_adapter.py`, `bootstrap_data_root.py`, and the
  basketball refresh scripts (models/src/schedule). Only the 2.2 MB root `app.py` inside
  `vendor/{nba,wnba}_betting_repo` is an unused legacy Flask app (`vendor/nhl_betting_repo/app.py`
  does not exist) — leave the vendored trees alone unless doing a deliberate, separately-reviewed
  vendor prune.
- **`system_map.md` is ~450KB** (generated). Don't read it whole; grep it.

---

## 9. Cross-reference index (the deeper docs)

| Topic | Doc |
|---|---|
| The load-bearing web/worker rule | `docs/ai_context/runtime_execution_model.md`, `worker_architecture.md` |
| Render hosting model | `docs/ai_context/runtime_infrastructure.md`, `docs/render_data_authority.md`, `docs/render_container_memory_breakdown.md` |
| Data flow (system) | `docs/ai_context/data_flow_system.md`, `daily_pipeline.md` |
| Simulation internals | `docs/ai_context/simulation_system.md`, `simulation_engine_map.md`, `simulation_adapter_design.md`, `simulation_timing.md`, `simulation_patterns.md`, `simulation_gaps.md` |
| Intelligence layer call graph | `docs/intelligence_call_graph_reference.md`, `docs/intelligence_execution_paths_and_polling.md`, `docs/intelligence_ask_projection_architecture.md` |
| Board / betting-board assessment | `docs/intelligence_betting_board_assessment.md` |
| Daily-update control plane | `docs/daily_update_control_plane.md`, `docs/daily_update_workflow.md`, `docs/shared_refresh_hydration_contract.md` |
| Self-host roadmap | `RENDER_SELF_HOST_BACKLOG.md`, `RENDER_SELF_HOST_REFACTOR_PLAN.md` |
| Phased migration plan | `docs/syndicate_world_class_implementation_plan.md`, `docs/syndicate_world_class_execution_backlog.md` |
| Debug playbook / fix log | `docs/debug_playbook.md`, `docs/fix_notes_log.md` |
| Operational reference (long) | `README.md`, `CLAUDE.md` |

---

*This document is a synthesis of the live codebase as of `bef3a026`. When it disagrees with the code,
the code wins — update this doc.*
