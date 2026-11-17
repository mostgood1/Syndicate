# Render config retirement — the fleet stops reading Render's files, and every marker reader prefers a neutral name

`[2026-11-17, lane render-config-retirement, session 267d8859; todo #766 reopened]`

**User, 2026-11-17:** "we should not depend on render at all". This reopens the 2026-11-16
decision D2' ("keep the `RENDER_*` markers"). Scope agreed when the lane opened (all three
answers were the recommended option):
- "Steps 1+2, load later": steps 1 and 2 land on main; nothing loads on the fleet in this
  lane without the user's go; step 3 (dropping the `RENDER*` fakes) is a separate decision.
- "Yes, copy now": copy the env snapshot to `fleet_env/` on the fleet before the code lands.
- "Yes, take the loan": borrow `local_production.py`'s env-build sections from lane
  `syndicate-decision-engine`.

Not touched: the Render account and its suspended services, and `render.yaml`, which was
neither edited nor pushed.

## Where it stands

| step | state |
|---|---|
| 1. launcher stops reading `render.yaml` and `render_env/` | **ON MAIN `ac2cbc2fc`.** The fleet's `fleet_env/` exists (migrated 17:24:08Z). The launcher builds a byte-identical env from it (measured below). It takes effect on the fleet at the next `up` that runs this code. |
| 2. neutral `SYNDICATE_*` markers; every reader prefers them | **ON MAIN `cc90fb653`.** The launcher sets both spellings to one value at its next `up`. Until then every reader falls back to the `RENDER*` names the running roles carry, so the answer is the same. |
| 3. stop setting `RENDER*`; delete the fallbacks | **NOT STARTED — the user's decision** (below). |
| fleet load (a drained full `down`/`up`) | **NOT DONE — the user's go.** Plan and readings below. |

**Tests (2026-11-17, 6 workers at Idle, 12:12-12:27 PM CST):** every test file that mentions a `RENDER*` marker (44, the new ones included) plus `test_request_path_guard.py`: **2050 passed, 36 skipped, 0 failed**; 146 passed again on the rebased tree. A first serial run at normal priority hit its 30-minute timeout at 41% with no failure.

## Step 1 — the role spec and the env snapshot

**Measured 2026-11-17 (re-measured before relying on the 11-17 brief):**
- `local_production.py` parsed `render.yaml` at every `up`, `doctor`, `env`, `status`, `init`
  (`load_blueprint`), and read `<home>/render_env/<role>.json`
  (`live_env_path`). It rewrote `/opt/render/project/{data,src}` prefixes in every layer.
- **The start commands were never parsed from `render.yaml`.** `role_command` hard-codes
  them; the comment at it only cited render.yaml's `startCommand`. Nothing to move.
- `render.yaml` declares 52 / 84 / 76 keys (web / refresh-worker / live-odds-worker), with no
  duplicates. Every `/opt/render` value is a DATA path (16 per role); there are no `src` paths.
- On the fleet `render_env/` holds 88 / 182 / 148 keys and no `RENDER*` key. 16 / 17 / 16
  values per role carry `/opt/render/project/data`. `local_production.env`: 78 keys, no
  `/opt/render` value, no `RENDER*` key, and no `SYNDICATE_PUBLIC_URL`. **So
  `RENDER_EXTERNAL_URL` is NOT set on the fleet.**

**Built:**
- `scripts/fleet_role_spec.json`: each role's declared keys, in order, frozen from
  `render.yaml` at origin/main `3179b1ff1`, with `/opt/render/project/data` turned into
  `{data_root}`. `load_role_spec` refuses a malformed file rather than start a role on a
  partial env.
- `scripts/fleet_env_snapshot.py`: **the only code that reads `render_env/`**. `migrate`
  writes `<home>/fleet_env/<role>.json` (files 0600, directory 0700). It drops Render's
  `service_id` / `pages`, keeps `fetched_at` as `snapshot_taken_at`, and turns the disk
  prefixes into placeholders under exactly the old rewrite's condition. It never
  overwrites a differing file. `check` compares the two directories key by key. It also
  converts a secrets backup taken before the rename (`fleet_secrets_backup.py restore`, then
  `migrate --home <restored dir>`).
- `local_production.py`: `load_role_spec` / `expand_path` / `env_snapshot_path` replace
  `load_blueprint` / `rewrite_path` / `live_env_path`. **New:**
  - `up` REFUSES a role with no snapshot, naming the fix; the override is
    `--allow-missing-env-snapshot`. Before, a missing snapshot was a doctor WARN, and `up`
    started the roles from the spec alone: absent venue keys and `*_AUTORUN` switches, a
    silently different fleet.
  - `doctor` now FAILs on a missing snapshot instead of WARNing.
- `fleet_secrets_backup.py` backs up `fleet_env/`.

**Fleet action, 2026-11-17 17:24:08Z (11:24 AM CST), user "Yes, copy now":**
`fleet_env_snapshot.py migrate --home ~/syndicate-prod`, run from this worktree with the
fleet venv's python. It wrote 88 / 182 / 148 keys and placeholdered 16 / 17 / 16 values.
`check`: SAME for all three roles, mode 0600, directory 0700. `render_env/` was left
untouched, mtimes unchanged; it is the rollback for any checkout older than `ac2cbc2fc`.
That includes its `live-odds-worker.json.bak_nba_20261004T174221Z`, which was not carried
over. No process was started, stopped or signalled.

**Equivalence, measured 17:2xZ (11:2x AM CST), read-only.** Old and new launcher were
loaded side by side, both rooted at `/home/amyn/Syndicate`, against the live home. Each
role's env was built as `cmd_env` builds it (`base_env={}`, a fixed instance id) and
compared per key by sha256; no value was printed:

| state | role | keys old / new | differing | only old / only new | audit (rewritten, local, unset, forced, snapshot count) |
|---|---|---|---|---|---|
| redis | web | 138 / 138 | 0 | 0 / 0 | all equal |
| redis | refresh-worker | 240 / 240 | 0 | 0 / 0 | all equal |
| redis | live-odds-worker | 213 / 213 | 0 | 0 / 0 | all equal |
| file | web / refresh-worker / live-odds-worker | 135 / 237 / 210, both sides | 0 | 0 / 0 | all equal |

## Step 2 — neutral markers

`syndicate/features/shared/service_identity.py`: `service_marker("SYNDICATE_X")` returns the
neutral key's value when it is PRESENT (even empty), else the Render-era key's, else None.
Every reader asks it where it used to call `os.environ.get("RENDER_X")`, and keeps its own
predicate on the answer unchanged. The launcher (`SERVICE_MARKERS`, pinned equal to the
helper's table) sets each neutral key to EXACTLY the value of the Render key it mirrors,
and only where that key was set before:

| neutral | Render-era | set by the launcher |
|---|---|---|
| `SYNDICATE_HOSTED` | `RENDER` | `true`, redis state mode only |
| `SYNDICATE_SERVICE_NAME` / `_ID` | `RENDER_SERVICE_NAME` / `_ID` | `local-<role>` |
| `SYNDICATE_INSTANCE_ID` | `RENDER_INSTANCE_ID` | `local-<role>-<epoch>`, re-stamped on a role restart |
| `SYNDICATE_GIT_COMMIT` | `RENDER_GIT_COMMIT` | HEAD at `up`, when git answers |
| `SYNDICATE_EXTERNAL_URL` | `RENDER_EXTERNAL_URL` | only with `SYNDICATE_PUBLIC_URL`, which is unset |
| `SYNDICATE_GIT_BRANCH` | `RENDER_GIT_BRANCH` | never (Render injected it) |

**Measured 17:5xZ (11:5x AM CST), read-only, same method as step 1** (origin/main
launcher vs the step-2 launcher, live home). Per role, the ONLY difference is the
neutral markers added:
- redis mode, all three roles: `SYNDICATE_GIT_COMMIT`, `SYNDICATE_HOSTED`,
  `SYNDICATE_INSTANCE_ID`, `SYNDICATE_SERVICE_ID`, `SYNDICATE_SERVICE_NAME`
  (138→143 / 240→245 / 213→218 keys);
- file mode: the same minus `SYNDICATE_HOSTED`.

0 pre-existing keys differ by sha256, every `RENDER*` value included.

Names chosen value-identical rather than the 11-07 inventory's `SYNDICATE_SERVICE_ROLE` =
`web`, so equivalence holds by construction. `SYNDICATE_SERVICE_ROLE` keeps its two existing
readers and is still set by nothing.

**Why the launcher spells the table out instead of importing it:** importing `syndicate`
runs `install_http_compression()`, which installs a global urllib opener. The supervisor
process imports `syndicate` today only in `down`, so `up` must not start importing it.

## Every reader and its default

"Default" = what the reader does with NO marker. "Fleet today" = which input decides it on
the running fleet (read 2026-11-17 17:1xZ from each role's `/proc/<pid>/environ`, allowlisted
names only: `RENDER=true`, `RENDER_SERVICE_NAME` / `_ID` = `local-<role>`, `RENDER_INSTANCE_ID`,
`RENDER_GIT_COMMIT=5b30d24…`; also `SYNDICATE_WEB_DYNO` true/false/false,
`SYNDICATE_REFRESH_LANE` = role, `SYNDICATE_REQUIRE_HOSTED_STORAGE=true`,
`SYNDICATE_LOCAL_PRODUCTION=1`). Tests: `tests/test_service_marker_readers.py` checks each
reader under neither / legacy / neutral / both: legacy == neutral == both, and
neutral != neither.

### H1 — "hosted web"

| reader | marker(s) | default (absent) | fleet today |
|---|---|---|---|
| `syndicate/app.py:300` `_is_render_web_dyno` | HOSTED truthy, or EXTERNAL_URL, or SERVICE_ID | False → `_start_background_loops` starts the intelligence + live-refresh loops on web on first request WITHOUT reading their flags: a second board builder on the shared disk | **the marker decides** (`RENDER` / `RENDER_SERVICE_ID`) |
| `syndicate/blueprints/home.py:297` `_render_web_dyno` | same | False → full `build_home_overview` on the request path | **the marker decides** |
| `syndicate/features/shared/portfolio_auth.py:96` `_on_render` | same | False → auth `required` only if a portfolio credential is set | marker, but web's credentials also hold `required` |
| `syndicate/features/{mlb,wnba}/cards.py`, `shared/game_board_contract.py` `_render_web_dyno` | `SYNDICATE_WEB_DYNO` FIRST, then same | False | `SYNDICATE_WEB_DYNO` decides (set per role) |
| `syndicate/features/nba/cards.py:52` `_render_web_dyno` | `SYNDICATE_WEB_DYNO` first, then HOSTED | False | `SYNDICATE_WEB_DYNO` decides |

### H2 — "hosted storage"

| reader | marker | default (absent) | fleet today |
|---|---|---|---|
| `blueprints/intelligence.py:211` `_render_hosted_request` | HOSTED `or` `SYNDICATE_REQUIRE_HOSTED_STORAGE` (one chained lookup) | REQUIRE flag alone | marker (`RENDER=true` is read first); REQUIRE=true would hold it anyway |
| `shared/refresh_state_store.py` `_strict_hosted_storage_enabled` (:51), `_refresh_state_backend_name` (:42), `assert_refresh_state_backend_ready` (:373), `reports_root` (:430) | HOSTED | strict iff REQUIRE flag; backend auto-pick filesystem; workers ALLOW a file backend; `reports_root` raises without a root | REQUIRE=true and the explicit `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue` decide; `assert_...` and `reports_root`'s hosted branch still read the marker |
| `shared/source_roots.py` `_root_env_fingerprint` (:45), `_strict_hosted_storage_enabled` (:71), `_preferred_source_roots_cached` (:106/:127/:133), `_preferred_artifact_roots_cached` (:214/:223) | HOSTED | no repo-`data/` fallback roots; with REQUIRE set and no data root: RuntimeError | **the marker decides** the repo-mirror fallback candidates |
| `shared/request_path_guard.py:128` `hosted_signal` / `_is_render_hosted` | flags: HOSTED, REQUIRE; markers: SERVICE_ID, INSTANCE_ID, SERVICE_NAME, EXTERNAL_URL | None → guard warn-only | armed (HOSTED first). **After the load it reports `SYNDICATE_HOSTED` instead of `RENDER`**: web's `COMBINED_BOARD_OVERLAY_WARMER_STARTED ... armed_by=hosted:SYNDICATE_HOSTED` (`pipeline/intelligence_state.py:10132`). Arming is unchanged |
| `shared/disk_compaction.py:82` `disk_compaction_wanted` | HOSTED (after `SYNDICATE_DISK_COMPACTION`) | False → refresh-worker compaction stops | **the marker decides** |

### S — "which service am I"

| reader | marker | default (absent) | fleet today |
|---|---|---|---|
| `scripts/run_refresh_worker.py:4242` `_running_job_process_count` + `:4223` `_job_belongs_elsewhere` (own environ, and each job's `/proc` environ or psutil environ) | SERVICE_NAME | no own name → nothing filtered → refresh-worker counts live-odds-worker's jobs (2026-10-03: 17 of 18 ticks `JOB_CAP_THROTTLED`); a job with no name still counts | **the marker decides.** Test-pinned with fake `/proc` under every child spelling |
| `scripts/build_soccer_artifacts.py:1397` `_prekickoff_service_tag` | SERVICE_NAME | `local` → both workers write one freeze file | **the marker decides** |
| `shared/ops_refresh.py:413` `_this_service_identity`, `:417` `_this_instance_identity` | SERVICE_ID else SERVICE_NAME; INSTANCE_ID | "" → run liveness falls back to pid + cmdline | **the marker decides** |
| `shared/disk_maintenance.py:77` `_service_slug`, `shared/win_prob_null_diag.py:84` `service_slug`, `shared/artifact_retention.py:315` `_cursor_path` | `SYNDICATE_REFRESH_LANE` FIRST, then SERVICE_NAME / SERVICE_ID | `local` | `SYNDICATE_REFRESH_LANE` decides |
| labels: `shared/slate_phase.py:509` `publish_phases`, `shared/live_refresh_loop.py:2912` `_launch_mlb_daily_sim`, `scripts/refresh_odds_sources.py:2764` `_record_step_in_sim_ledger`, `scripts/run_refresh_worker.py:5847` `_record_season_projection_in_sim_ledger` | SERVICE_NAME | None | label only |
| `shared/opportunity_contract_metrics.py:133` `snapshot`, `scripts/fetch_mlb_oddsapi_local.py:656` `diagnose_odds_history_provenance` | `SYNDICATE_SERVICE_ROLE` first (set by nothing), then SERVICE_NAME | `unknown` | label only |

### C — "which commit", and the rest

| reader | marker | default (absent) | fleet today |
|---|---|---|---|
| `shared/model_version.py:53` `code_version` (lru-cached) | GIT_COMMIT, then `GIT_COMMIT` / `SOURCE_VERSION` | `git rev-parse` → `unknown` | the marker (HEAD at `up`; wrong after a role-only restart or a HUP, which is already known) |
| `blueprints/home.py:309` / `:349` and `blueprints/ops.py:195` version payloads | GIT_COMMIT, GIT_BRANCH; SERVICE_NAME, INSTANCE_ID, EXTERNAL_URL | `GIT_COMMIT` / `SOURCE_VERSION` / git; fields null | display. **The payload KEYS stay `render_service_name` / `render_instance_id` / `render_external_url`**: renaming an API field is outside this lane |
| `shared/deploy_drain.py:230` `publish_worker_state`, `shared/worker_shutdown.py:143` `build_shutdown_record`, `shared/win_prob_null_diag.py:122` `_commit` | GIT_COMMIT | None | record only. `_commit` used to read `RENDER_GIT_COMMIT` BEFORE `SYNDICATE_GIT_COMMIT`; it is neutral-first now, and with both set to one value the answer is the same |
| `scripts/local_production.py` `role_loaded_commit`, `role_spawn_stamp` (`status`) | GIT_COMMIT, INSTANCE_ID via `read_marker` | None | record |
| `features/{nba,wnba}/live_tick/tick.py` `_maybe_fetch_remote_processed` | `GIT_BRANCH` env first, then GIT_BRANCH marker | `main` | never set on the fleet: `main` |
| `scripts/refresh_mlb_oddsapi.py:1150` base URL | `..., RENDER_URL, SYNDICATE_EXTERNAL_URL, RENDER_EXTERNAL_URL` | `""` | none set on the fleet |
| `scripts/run_refresh_worker.py:3861` diagnostics dump | HOSTED | null | key renamed `RENDER` → `SYNDICATE_HOSTED` in `_env_as_seen_by_process` |

### Scrubbers (child environments that must NOT look hosted)

`scripts/run_ci_suite.py _step_env` (adds `NEUTRAL_MARKER_ENV`), `scripts/replay_diff_gate.py
_child_env` (pops `SYNDICATE_HOSTED` too), `scripts/fleet_local.py FORCED_ENV_BASE`
(`SYNDICATE_HOSTED=""` too), `local_production.derive_role_env` (strips a stray neutral marker
from the operator's shell as it did `RENDER*`). **This is the one trap in step 2.** A
scrubber that removed only `RENDER` would leave a child "hosted" through an inherited
`SYNDICATE_HOSTED` once the launcher sets it. All four are test-pinned. No other code sets
or clears a marker; checked with `git grep` for assignments, `setdefault`, `KEY=` strings
and `putenv`.

**Enforced:** `test_no_non_test_file_reads_a_render_marker_directly` parses every tracked
non-test `.py`. It fails on any string constant equal to a Render-era marker name, or any
bytes constant starting `RENDER`, outside six allowlisted files: the two tables, three
scrubbers, and one fallback that sits after its neutral name. A positive control proves the
scan flags a direct read.

## Still named "Render" — NOT a dependency, left on purpose

- `render.yaml` itself (never pushed; the guard refuses it). `test_fleet_role_spec.py` reads
  it only to prove the spec equals it, and skips once the file is gone.
- `~/syndicate-prod/render_env/` on the fleet: the rollback copy. Delete it only after a
  load of `ac2cbc2fc`+ has run cleanly (owed; the user's call).
- `RENDER_URL` in `refresh_mlb_oddsapi.py`: a Render-era OPERATOR variable, not a marker; set
  nowhere on the fleet.
- Function names `_is_render_web_dyno` / `_render_web_dyno` / `_render_hosted_request` /
  `_on_render`, API fields `render_*`, `scripts/render_logs.py`, `_normalize_render_base_url`,
  and `syndicate.onrender.com` in test fixtures. These are names only.
- `RENDER_API_KEY` in the `NEVER_CARRY` / strip lists: protective.
- `local_production.cmd_backup_and_secrets`'s docstring still says `render_env/`: outside the
  borrowed sections.

## The load (OWED — the user's go)

Steps 1+2 reach the fleet only at a drained full `down` + `Start-ScheduledTask
SyndicateLocalProduction`, from an ff to a SHA that carries both. **Restarting
refresh-worker kills an in-flight MLB sim**, so the load needs the deploy claim and
`deploy_preflight` CLEAR. Readings:
- **before** (same instant): each role's `/proc/<pid>/environ` marker keys (allowlisted
  names, as above);
- **after**:
  - every role carries both spellings with equal values;
  - every NON-marker key's sha256 equals its pre-load value, apart from `RENDER_INSTANCE_ID`
    and `RENDER_GIT_COMMIT` / `SYNDICATE_*` twins, which change by design;
  - `local_production.py status` reads the same commit;
  - web logs `armed_by=hosted:SYNDICATE_HOSTED`;
  - `JOB_CAP_THROTTLED` share, compaction runs and the request-guard refusal counts are in
    their pre-load band.
- **betting change: no.** No bet is placed, sized, held or exited differently: every reader
  returns the same value, and job counting is test-pinned under every child spelling. If a
  reading shows any reader changed, that is a falsification, and the answer becomes `yes`.

## Step 3 — the decision this lane does not make

Stop setting the `RENDER*` names in `derive_role_env`, and delete the fallback half of
`service_marker` plus the six allowlisted sites. Prerequisites: a load of steps 1+2 with the
readings above, and a grep showing no tool reads `RENDER*` from a role's environ
(`_pipeline_diag`, `check_deploy_safety`, `deploy_preflight`, `execution_watchdog`; none
did at `ac2cbc2fc`). Risk if done wrong: the H1/H2/S defaults above. Each is silent, on a
live-money fleet.
