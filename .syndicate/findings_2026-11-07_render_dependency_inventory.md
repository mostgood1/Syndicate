# Render dependency inventory — what still assumes Render, now that production is the WSL fleet

`[2026-11-08 00:05Z (18:05 CST 11-07), lane render-retirement-inventory, session 36cc0a0e; origin/main 44984ae61]`

**Question (user, via session 5d941771):** why is Render still needed?
**Short answer: for running production, it isn't.** Nothing the fleet does at run time
calls Render. What remains is (a) a NAMING convention (`RENDER_*` env markers the fleet
fakes), (b) one deploy-guard check that reads the Render API on `render.yaml` pushes,
(c) a 2026-10-01 env snapshot that was pulled from Render once and is now a local file,
(d) some operator tools with a Render default, and (e) stale docs. If the Render account
vanished tomorrow, production would keep trading. Two things would stop working, both
operator-side: re-importing the env snapshot, and `render.yaml` pushes (the guard
would block them until overridden). **The one real exposure:** the snapshot
(`<home>/render_env/*.json`) holds 88 / 182 / 148 live keys. It is excluded from the
nightly backup by design, and its documented recovery is "re-import from Render". So
with Render gone, a lost fleet host could not rebuild those values from anywhere
(§1, D3).

Constraints honoured: no Render API call was made, no Render service touched, no fleet
behaviour changed. Fleet reads below were read-only and printed key NAMES, counts and
non-secret enums only.

---

## 0. Corrections to the brief (re-derived, not inherited)

1. **`deploy_preflight.py` on `main` does NOT read Render by default.** A fleet path
   landed 2026-10-25 (lane `preflight-fleet-path`, `scripts/deploy_preflight.py:507-546`).
   `--target auto` resolves to the fleet unless an operator base-URL var points
   elsewhere (`target_is_fleet`, `:535`; `_base_url.default_base_url`, `scripts/_base_url.py:86`).
   Live commit comes from `local_production.py status code=`. Jobs come from a `ps`
   snapshot. Board build comes from the fleet log. **Evidence it is what deploys use:** the
   receipts in the primary tree's `.syndicate/deploy/preflight/` dated 2026-11-07
   (`web.json` 17:56, `live-odds-worker.json` 17:55, `refresh-worker.json` 17:38, local
   time) carry `sample_source = "fleet: ..."`.
2. **The HTTP 503 / UNKNOWN symptom comes from the PRIMARY TREE, not from `main`.** The
   primary checkout (`C:\Users\tempadmin\OneDrive\Coding\Syndicate`) is at `f5427e385`,
   **2,488 commits behind `origin/main`**. Its `scripts/deploy_preflight.py` has **0**
   occurrences of `target_is_fleet`, so a session that runs preflight from there reads
   the suspended Render API. This matches the memory note *"primary tree's
   deploy_preflight.py ... has no --target, so it reads Render. Run preflight from a
   worktree at origin/main."* The deploys.md lines that say "deploy_preflight does not
   apply (reads suspended Render)" (45291, 46493) predate 10-25 or ran from that tree.
3. **`deploy-guard.py` already gates fleet deploys.** Lane `deploy-guard-fleet`
   (2026-10-25) covers a fleet-checkout ff, `reload-web`, a role TERM and `down`
   (`.claude/hooks/deploy-guard.py:509-800`). Its only Render read is the
   `render.yaml`-push drift check (§2.2).
4. **`render_logs.py` reads the fleet by default since 2026-10-06** (`--render` or
   `SYNDICATE_LOG_SOURCE=render` for the API; `state_worker.md [local-production-host]`).
5. **`publish_model_scorecard.base_url()` no longer falls back to onrender.** It uses
   `default_base_url(...)` (`scripts/publish_model_scorecard.py:132-133`), so its
   fallback is the fleet. `live_lens_loop._wnba_live_box_base_url` still does (§3.1).

---

## 1. `render.yaml` — the fleet's env source, and mostly inert

`scripts/local_production.py` builds each role's env in four layers
(`derive_role_env`, `:330-445`):

    render.yaml (per service)  ->  <home>/render_env/<role>.json  ->  <home>/local_production.env  ->  forced
                                    (Render snapshot)                 (incl. ROLE__KEY pins)

A later layer wins (`:376-394`, live overrides blueprint; local overrides live).

**MEASURED on the fleet 2026-11-08 00:0xZ** (fleet checkout `af4244afd`, the module's
own `load_blueprint` / `parse_env_file` / `role_local_view`, key names only):

| role | `render.yaml` `value:` keys | decided by render.yaml alone | same as snapshot | overridden by snapshot | snapshot keys not in render.yaml |
|---|---|---|---|---|---|
| web | 48 | **0** | 47 | 1 (`ODDS_API_KEY`) | 37 |
| refresh-worker | 77 | **0** | 76 | 1 (`ODDS_API_KEY`) | 98 |
| live-odds-worker | 72 | **0** | 71 | 1 (`ODDS_API_KEY`) | 72 |

Snapshot: `render_env/{web,refresh-worker,live-odds-worker}.json`, `fetched_at`
2026-10-01T01:11:31-32Z, 88 / 182 / 148 keys. `render.yaml` has had **no commit since
before 2026-09-29**.

**Consequences:**

- **Editing an existing `value:` in `render.yaml` changes NOTHING on the fleet.** Every
  declared key is also in the snapshot, which wins. **Adding** a key that the
  snapshot lacks does apply, at the next full `up`. **Deleting** a key does nothing,
  because the snapshot still supplies it. The working env-change path is
  `local_production.env` (global or `ROLE__KEY`) plus a full `down`/`up`
  (learnings 2026-10-26, *"a fleet env change needs a DRAIN, a SHA guard on the env file,
  and a LIVE operator"*).
- **If Render vanished:** `up` keeps working, because it reads the snapshot FILE, not the
  API. Lost: `local_production.py import-render-env` (`:843`, calls
  `snapshot_render_env.fetch_env`), so the snapshot can never be refreshed. It is
  already frozen in practice. The only copies of those values are those three files
  and their backups. Per the runbook, `render_env/` is deliberately excluded from the
  nightly backup.
- **SECURITY, not fixed (it is the fleet host):** `render_env/live-odds-worker.json` is
  mode **0644** (world-readable). The other two are 0600, and the runbook (`:111`)
  says 600. It was rewritten 2026-10-04 12:42 (beside
  `live-odds-worker.json.bak_nba_20261004T174221Z`, which is 0600), and the rewrite
  lost the mode. It holds plaintext venue and API secrets. Fix: `chmod 600` on that
  file. It needs the user's OK because it touches the fleet host.
- `render.yaml` carries a literal `ODDS_API_KEY` value at 3 sites (`:37`, `:290`, `:763`),
  i.e. a secret in git. On the fleet the snapshot overrides it at all three. The value
  is not repeated here.

**Proposal R1 (user decision):** stop treating `render.yaml` as the fleet's env source.
Pick one:
  (a) **Freeze and say so**: header comment in `render.yaml`, plus a `local_production.py
      doctor` line that names any `render.yaml` key whose value differs from the
      effective env. Zero behaviour change.
  (b) **Fold the snapshot into one fleet-owned file** (`<home>/fleet_env/<role>.env`,
      mode 600, backed up encrypted or at least off-disk), make it the layer under
      `local_production.env`, and drop `render.yaml` from `derive_role_env`. This is a
      fleet env change, so it needs a full drained `down`/`up`. The proof would be byte
      equality of each role's `/proc/<pid>/environ` key set and values before and after.
  (c) Keep as is.
  Recommendation: (a) now, (b) only if Render is actually cancelled.

---

## 2. Deploy tooling that reads the Render API

### 2.1 `scripts/deploy_preflight.py` — fleet by default; Render only on `--target render`

- Render-only reads, all behind `not on_fleet`:
  - `_api_key` `:302`
  - `/v1/logs` `:397`
  - `/v1/services/<id>/deploys` `:724`, `:782`
  - `/v1/services/<id>/events` `:862`
  - `web_processes()` against `WEB_BASE_URL` (default onrender) `:330`, `:371`.
    On the fleet the web branch `:1179` comes first, so this is never reached.
- Cron-named services (`ci-suite`, `model-scorecard`, `sim-input-reports`) on the fleet
  return `UNKNOWN: "Render cron services are suspended; on the fleet this is a
  supervisor job"` (`:1171-1178`). That is correct: on the fleet those are supervisor
  `SCHEDULED_JOBS` (`local_production.py:928+`) and load code at each run.
- **If Render vanished:** nothing changes for `--target auto` / `fleet`. `--target render`
  fails as it does today.
- **The real gap is the PRIMARY TREE (§0.2)**, not this file.

### 2.2 `.claude/hooks/deploy-guard.py` -> `scripts/check_blueprint_drift.py` — the guard's one Render read

- The guard detects a push carrying `render.yaml` (`:898-912`, `:1051-1053`). It then runs
  `check_blueprint_drift.py` (`:933-955`, `:1096-1115`) and requires claims plus a
  preflight on ALL THREE services (`:882-883`).
- `check_blueprint_drift.py` reads `GET /v1/services/<id>/env-vars` (`:70`). With no key
  or an API error it exits **2 (UNKNOWN)**. The guard treats any nonzero exit as
  BLOCKED, with override `SYNDICATE_ALLOW_BLUEPRINT_DRIFT=1`.
- **What it compares is no longer the fleet's env.** It diffs `render.yaml` against
  Render's frozen service env. On the fleet, per §1, the push changes nothing for
  existing keys, and the only effect comes later, at a fleet ff plus full `up` (which
  the guard gates separately).
- **But the push may still reach Render.** If the Render blueprint is still linked,
  `blueprint_sync` could rewrite env vars on the SUSPENDED services. Not tested: that
  would touch Render.
- **If Render vanished:** every `render.yaml` push blocks (exit 2) until overridden.

**Proposal R2 (coupled to R1, user decision):** give `check_blueprint_drift.py` a fleet
mode. It would report, per role, which changed keys are INERT (shadowed by the
snapshot or the local file) and which are EFFECTIVE (would change at the next full
`up`), using `local_production`'s own layering, key names only. It would print beside
the Render verdict, NOT instead of it, as long as the Render blueprint may still be
linked. That keeps the guard from reading a suspended service only once the user
decides Render will not be resumed. Until then the Render read protects the suspended
services, and that read is cheap: it runs only on `render.yaml` pushes.

### 2.3 Other Render-API scripts (operator tools, none on a run-time path)

These read `api.render.com`. None is imported by the fleet roles or the supervisor;
all fail with no harm if Render vanishes:

    _pipeline_diag.py, audit_blueprint_drift.py, bandwidth_tripwire.py, blueprint_sync_preview.py,
    build_consolidated_graft.py, check_worker_memory_gate.py, one_shot_restore_web_access_log.py,
    oom_band_report.py, ratchet_sample.py, render_bandwidth_report.py, render_deploy.py,
    render_env_set.py, render_events.py, snapshot_render_env.py, survey_nhl_club_tokens.py,
    verify_nfl_autorun_obligations.py

The exceptions have fleet defaults:
- `check_deploy_safety.py` uses the fleet readers for a local base URL (state_worker).
- `render_logs.py` reads local by default.

**Proposal R3:** move the Render-only ones to `scripts/render_legacy/` with a README, in
ONE commit, after checking each for importers (memory *"CLI gate has no importer"*:
ask the lanes first). Do this only after R1/R2 are decided.

---

## 3. Fallbacks to the public onrender host

| site | reached on the fleet? | if Render vanished |
|---|---|---|
| `syndicate/features/shared/live_lens_loop.py:432` `_wnba_live_box_base_url` | **No.** `local_production.py` forces `SYNDICATE_WNBA_LIVE_BOX_BASE_URL` / `SYNDICATE_INTERNAL_WEB_BASE_URL` to the local web (`:416-417`) | nothing. Off-fleet runs would fail the WNBA live box. Lane `wnba-native-live-cutover` holds this file |
| `scripts/_base_url.py:65` `RENDER_BASE_URL` | only on a "Render host" (`RENDER` set AND `SYNDICATE_LOCAL_PRODUCTION` unset/0, `:80-83`); fleet roles set `SYNDICATE_LOCAL_PRODUCTION=1` | nothing |
| **`.claude/skills/daily-accuracy/driver.py:57`** `DEFAULT_BASE_URL = onrender` | **Yes, for every operator run without `SYNDICATE_BASE_URL`**; token only from `ADMIN_TOKEN` env (`:342`) | **already broken**: reads a suspended host and exits 4. **FIXED in this lane** (§6) |
| `scripts/deploy_preflight.py:330` `WEB_BASE_URL` | No (Render path only, §2.1) | nothing |
| `scripts/watch_unknown_submit.ps1:39` | only if someone runs it; referenced only by ledger/todo | it would poll a dead URL |
| `.github/workflows/daily-update.yml:273` | manual dispatch only (schedule removed 2026-08-20, last run 08-19) | the manual backup step fails |
| `syndicate/features/mlb/native/tools/daily_update.py:1535-1556` and copies in `eval/sync_render_live_lens_history.py:39-56` and `smoke/smoke_render_frontend.py:35-50` | Only if MLB `daily_update` runs its prior-day live-lens sync, pitcher-correction refresh or Render validation with no `MLB_BETTING_BASE_URL`/`BASE_URL`/`RENDER_URL`/`RENDER_EXTERNAL_URL`. The inference takes the FIRST `name:` in `render.yaml`, which is the keyvalue `syndicate-refresh-state` (`render.yaml:16`). The URL is nonsense either way. **Not determined** whether the fleet's MLB path invokes these stages; owed: grep the refresh-worker log for `render_base_url` | those stages fail soft (`stage.status`) |
| docstring/comment-only: `grade_nhl_predictions_vs_market.py:60` (code uses `default_base_url`, `:116`), `basketball_sim_input_checklist.py:621`, `poll_basketball_momentum.py:718`, `prop_evidence_checklist.py:18`, `render_cron_enqueue_refresh.py:54`, `request_path_guard.py:31`, `venue_quote_fanin.py:130`, `render.yaml:427` | — | nothing |

---

## 4. Code that branches on `RENDER*` markers — the convention the fleet fakes

The fleet sets them in `derive_role_env` (`local_production.py:422-447`): `RENDER_SERVICE_NAME`/`_ID`
= `local-<role>`, `RENDER_INSTANCE_ID`, `RENDER_GIT_COMMIT` (HEAD at `up`),
`RENDER_EXTERNAL_URL` (only with `SYNDICATE_PUBLIC_URL`), and `RENDER=true` in redis
state mode. The function first strips any `RENDER*` from the operator's shell (`:345-347`).
**Read 2026-11-08 00:0xZ from `/proc/<pid>/environ` (key names plus non-secret values):**
- web (gunicorn): `RENDER=true`, `RENDER_SERVICE_NAME=local-web`, `SYNDICATE_WEB_DYNO=true`,
  `SYNDICATE_LOCAL_PRODUCTION=1`
- refresh-worker: `RENDER=true`, `RENDER_SERVICE_NAME=local-refresh-worker`,
  `SYNDICATE_WEB_DYNO=false`
- live-odds-worker: not read (its process is `run_live_odds_refresh_worker.py`); same
  function sets it.

**What each group gates — and what silently changes if the marker is removed without a replacement:**

| group | sites | gates | removal without replacement would |
|---|---|---|---|
| **H1 "hosted web dyno"**: `RENDER` or `RENDER_EXTERNAL_URL` or `RENDER_SERVICE_ID` | `syndicate/app.py:299-304` | `_start_background_loops` (`:648-676`, `:757-764`): hosted, it starts the intelligence loop only if `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` and **never** the live-refresh loop. Not hosted, it starts **both on first request, flags unread**. Also `_bootstrap_render_data` `:171` | **start a second board builder on web**, on the same disk as refresh-worker (state_worker `[local-production-host]`) |
| same predicate, restated | `syndicate/features/shared/portfolio_auth.py:86-93`, used at `:149` | `auth_mode()`: `required` if hosted OR any portfolio credential is set | **nothing today**: web carries `SYNDICATE_PORTFOLIO_USERNAME` + `_PASSWORD` (key names read from `/proc` 2026-11-08 00:1xZ), so it stays `required`. Auth would turn `off` only if those were absent too |
| same predicate | `syndicate/blueprints/home.py:296-301`, used at `:8517` | hosted web serves `_build_light_home_sports`; otherwise `build_home_overview(...)` | **move the full home-overview build onto web's request path** |
| `SYNDICATE_WEB_DYNO` first, then RENDER heuristics | `syndicate/features/shared/game_board_contract.py:66-86`, `mlb/cards.py:226-243`, `wnba/cards.py:95-112`, `nba/cards.py:60-66` | web takes the cached-attach path, workers the heavy contract build | nothing while `SYNDICATE_WEB_DYNO` is set per role (it is: true/false read above) |
| **H2 "hosted storage"**: `RENDER` (or `SYNDICATE_REQUIRE_HOSTED_STORAGE`) | `refresh_state_store.py:44,53,374,433`; `source_roots.py:50,74,105,126,132,213,222`; `blueprints/intelligence.py:211` | keyvalue backend auto-selection, strict hosted roots, no repo `data/` fallback | nothing for the backend (`SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` is set explicitly). **The hosted-storage strictness and the repo-fallback refusal would switch off** unless `SYNDICATE_REQUIRE_HOSTED_STORAGE=1` |
| `RENDER` alone | `shared/disk_compaction.py:89` | the default compaction path, which DELETES/rewrites files, runs only with `RENDER` | stop disk compaction on refresh-worker |
| `RENDER`/`SYNDICATE_REQUIRE_HOSTED_STORAGE` OR any of `RENDER_SERVICE_ID`/`_INSTANCE_ID`/`_SERVICE_NAME`/`RENDER_EXTERNAL_URL` | `request_path_guard.py:24,34,135-138` (`_HOSTED_FLAGS`, `_HOSTED_MARKERS`) | the request-path compute guard | **disable the guard that refuses on-request recompute** on web, once ALL of them are gone |
| **S "which service am I"**: `RENDER_SERVICE_NAME` / `_ID` / `_INSTANCE_ID` | `ops_refresh.py:413-424, 543, 656-671`; `run_refresh_worker.py:4217-4300` (`_job_belongs_elsewhere`); `artifact_retention.py:317`; `disk_maintenance.py:79`; `win_prob_null_diag.py:86`; `build_soccer_artifacts.py:1397`; `refresh_odds_sources.py:2801`; `run_refresh_worker.py:5864`; `live_refresh_loop.py:3003`; `slate_phase.py:523`; `opportunity_contract_metrics.py:142-143`; `fetch_mlb_oddsapi_local.py:741` | job ownership and liveness (pointer liveness by instance id), per-service lanes, telemetry labels | **break refresh-worker vs live-odds-worker job ownership**: on one host both share `/proc`, and `_job_belongs_elsewhere` reads the child's `RENDER_SERVICE_NAME`. Concurrency caps would count the other role's jobs |
| **C "which commit"**: `RENDER_GIT_COMMIT` | `model_version.py:60`; `home.py:310,351`; `ops.py:197`; `deploy_drain.py:245`; `worker_shutdown.py:153`; `win_prob_null_diag.py:120`; `local_production.py:2024-2032` (status env stamp) | model-version stamp and `/api/ops/version`. On the fleet it is HEAD at `up`, so it is WRONG after a HUP or a role-only restart (state_worker: `status` prefers the reflog) | fall back to `git rev-parse` / "unknown" |
| ops payload fields | `home.py:383-385`, `ops.py:222-224` (`render_service_name` etc.) | display only | show null |
| tooling | `scripts/_base_url.py:80-83`; `run_ci_suite.py:161-167` (scrubs them from CI); `run_refresh_worker.py:4041` (diag dump) | — | — |

Counts: 13 source files read `RENDER_SERVICE_ID`, 15 `RENDER_SERVICE_NAME`, 8
`RENDER_GIT_COMMIT`, 6 `RENDER_INSTANCE_ID`, 14 `RENDER_EXTERNAL*`, 18 `"RENDER"`;
tests: 7 / 13 / 4 / 2 / 5 / 20 (`git grep -l`, excluding `data/`).

### Proposal M (DECISION FOR THE USER — not implemented)

Replace the faked `RENDER_*` markers with neutral ones, without changing what any branch does:

- `SYNDICATE_SERVICE_ROLE` = `web` | `refresh-worker` | `live-odds-worker`. It replaces
  group S and the "am I web" half of H1. Two readers already prefer it
  (`fetch_mlb_oddsapi_local.py:741`, `opportunity_contract_metrics.py:142`).
- `SYNDICATE_HOSTED=1` replaces `RENDER=true` / the H1+H2 "this is production" half. It
  should be distinct from `SYNDICATE_LOCAL_PRODUCTION`, which means "shared-disk fleet"
  (`artifact_publisher.shared_disk_fleet()`).
- `SYNDICATE_INSTANCE_ID` and `SYNDICATE_GIT_COMMIT` replace `RENDER_INSTANCE_ID` and
  `RENDER_GIT_COMMIT`. `win_prob_null_diag.py:120` already reads `SYNDICATE_GIT_COMMIT`.

**Shape:** one helper module (`syndicate/features/shared/service_identity.py`:
`service_role()`, `is_hosted()`, `is_web_role()`, `instance_id()`, `git_commit()`) that
reads the neutral key FIRST and the `RENDER_*` key SECOND. Every site above is
repointed to it, and `local_production.py` sets BOTH sets of keys for one release. The
`RENDER_*` reads are deleted only after a fleet restart proves equivalence.
**Equivalence test before deploy:** for each role, every predicate in the table above
evaluates identically under {old keys only} and {new keys only}, over
`dataclasses`/function calls, not a name grep (`model_engine_standard`'s reachability
rule).
**Cost:** ~35 source sites plus ~50 test files; touches files held by lanes
`cheat-sheets`/`wncaab-module` (`syndicate/app.py`), `wnba-native-live-cutover`
(`live_lens_loop.py`), and four lanes on `local_production.py`. It needs their releases,
or it must be split per file.
**Risk if done wrong:** the bold "would" cells above. All are silent: a second board
builder on web, the home-overview build on the request path, the request guard off,
compaction stopped, and the two workers counting each other's jobs. Portfolio auth is
held today by credentials, not by the marker.
**Options:** (1) do it, as above; (2) do only the helper plus the neutral keys, and
leave the `RENDER_*` reads as a permanent fallback; (3) leave the markers and document
them as the fleet's role convention. **Recommendation: (3) now; (1) only if Render is
cancelled.** The fake is load-bearing but well-understood. The rename buys clarity, not
capability, and it spans 7+ claimed files on a live-money fleet.

---

## 5. Documentation that is stale

| where | stale claim | true since 2026-09-30 |
|---|---|---|
| `CLAUDE.md` "Outstanding work" | "Render auto-deploy is OFF — but that is true of CODE and false of CONFIG"; `logger.info` never reaches Render's log collector | Render is suspended; code reaches the fleet by ff + restart; the logs are the fleet's role logs |
| `CLAUDE.md` "Pushing `render.yaml` IS a production change (`#284`)" | a push applies to production via `blueprint_sync` | it applies nothing on the fleet for existing keys (§1). It may still touch the suspended Render services |
| `CLAUDE.md` "Render is the source of truth" | `data/**` vs Render's disk | the fleet's `<home>/data` is the source of truth; `/api/ops/...` on `http://127.0.0.1:10000` |
| `CLAUDE.md` "Render (web) vs. worker split" | "Render's Redis-backed disk cannot be shared" | one shared disk (`SYNDICATE_WEB_PUBLISH_URL` unset); the web-does-no-compute rule still holds |
| `CLAUDE.md` Session protocol "Before any deploy" | `render.yaml` pushes fire `blueprint_sync`; deploys = Render deploys | fleet deploy = exact-SHA ff of `~/Syndicate` (remote `github`) + `reload-web` / role TERM / drained full `down`/`up`; every restart comes back LIVE money |
| `CLAUDE.md` "Model engines" | "A local cache cannot reach Render" | the same rule holds for the fleet: use `SYNDICATE_DATA_ROOT` |
| `.claude/commands/preflight.md` Q4 | "stop-then-start with downtime, instances cannot overlap" | web reloads by rolling HUP; workers restart by supervisor; env needs full `up` |
| `docs/ai_context/local_production_runbook.md:111` | snapshot files are mode 600 | one is 0644 (§1). File held by lane `syndicate-decision-engine`; not edited |
| `.claude/skills/daily-accuracy/SKILL.md:38-42` | "against production by default" with `ADMIN_TOKEN=...` | production = the fleet; token in WSL — **fixed in this lane** (§6) |

**CLAUDE.md + `/preflight` change: LANDED on main as `1ead99fbe`** (2026-11-08, user
"Yes, land it"; draft was `9fcd9e25b`).

---

## 6. Changes made in this lane

1. This file.
2. `.claude/skills/daily-accuracy/driver.py`: default base URL changed from onrender to
   the fleet (`http://127.0.0.1:10000`), plus the fleet `ADMIN_TOKEN` read from WSL when
   none is exported. This mirrors `daily-optimizer/review.py`, which is already
   fleet-native. The skill stays stdlib-only. Read-only operator tooling; no fleet
   behaviour change.
3. The CLAUDE.md + `.claude/commands/preflight.md` docs fix: on main as `1ead99fbe`
   (user-approved 2026-11-08).
4. Nothing in `deploy_preflight.py` / `deploy-guard.py` / `check_blueprint_drift.py`:
   preflight's fleet path already exists (§0.1), and the guard's one Render read is
   coupled to D3.

## 7. Decisions owed to the user

- ~~**D1**~~ CLAUDE.md docs fix: DONE, `1ead99fbe`.
- **D2** Marker replacement (Proposal M): options 1 / 2 / 3. Recommended: 3.
- **D3** `render.yaml` role (R1 a/b/c) and the guard's Render read (R2). Recommended: R1(a), R2 additive.
- **D4** `chmod 600 ~/syndicate-prod/render_env/live-odds-worker.json` on the fleet host.
- **Follow-up, not a decision:** fast-forward the primary tree (2,488 behind). It is the
  cause of every "preflight reads Render" report. Recipe: memory
  `project_primary_tree_fast_forward_recipe`. It needs a uniqueness check of the
  primary tree's uncommitted work first.
