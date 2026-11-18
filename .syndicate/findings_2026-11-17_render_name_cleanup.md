# Render name cleanup — the names, comments and docs that still said "Render"

`[2026-11-17, lane render-name-cleanup, session ac50ee6a; todo #766 follow-up]`

Started by the parent session after lane `render-config-retirement` closed (step 3b, `f1a278ed8`):
the user wants no reliance on Render ("we should have removed reliance on render"). That lane
removed every functional dependency. What was left: names, stale comments, docs, and
`render.yaml` itself. Nothing in this lane touched the fleet, loaded code, or called Render.

## Where it stands

| part | state |
|---|---|
| 1. stale comments/docstrings (the case-sensitive `RENDER*` grep) | **ON MAIN `4c777e4d0`.** 19 files. Comment-only: each file's AST, docstrings stripped, is identical to HEAD's. |
| 2. Render-named identifiers, API fields, `RENDER_URL`, test fixtures | **ON MAIN** (commit below). Targeted tests: see "Tests". |
| 3. README, `docs/`, `.github/` | **ON MAIN** (commit below). 55 files. |
| 4. delete `render.yaml` + its guard rule | **OWED: waits on the user** confirming Render's GitHub App is uninstalled from the repo (or the services deleted). Exact list below. |
| 5. protective strip lists | **LEFT ON PURPOSE** (below). |

## Part 2 — every rename and every consumer checked

Consumers were searched with `git grep` over the whole repo (code, `templates/`, `static/` JS,
scripts, tests, `.claude/`), plus `~/.claude/scheduled-tasks` (no hit for any old name).

| old | new | defined in | consumers updated |
|---|---|---|---|
| `_is_render_web_dyno` | `_is_web_role` | `syndicate/app.py` | app.py (3 calls, local var `render_web_dyno` -> `web_role`); `portfolio_auth.py` comment; `tests/test_app_bootstrap.py`, `tests/test_service_marker_readers.py` |
| `_render_web_dyno` | `_is_web_role` | `blueprints/home.py`, `features/{mlb,nba,wnba}/cards.py`, `shared/game_board_contract.py` | `shared/simulation_adapter.py` (import), `blueprints/ops.py` (debug trace), docstrings in `mlb/game_state.py`, `nba/live_player_box.py`, `scripts/measure_cards_context_rss.py`; mlb/cards local var -> `web_role`; 15 test files that patch it |
| `_render_hosted_request` | `_is_hosted_request` | `blueprints/intelligence.py` | `tests/test_intelligence.py`, `tests/test_intelligence_state.py`, `tests/test_service_marker_readers.py` |
| `_on_render` | `_is_hosted` | `shared/portfolio_auth.py` | its boot line key `on_render=` -> `hosted=` (`PORTFOLIO_AUTH_MODE`; no watcher greps it, ledger readings before 11-17 say `on_render=`); `tests/test_service_marker_readers.py`; 3 test names in `tests/test_portfolio_auth.py` |
| `_is_render_hosted` | `_is_hosted` | `shared/request_path_guard.py` | `tests/test_service_marker_readers.py` |
| `_bootstrap_render_data` | `_bootstrap_hosted_data` | `syndicate/app.py` | comments in `scripts/run_refresh_worker.py` (2), `pipeline/novig_odds_refresh.py`, `tests/test_refresh_worker.py`, `tests/test_soccer_espn_stats_seed.py`; `tests/test_app_bootstrap.py`; CLAUDE.md directory map |
| `_normalize_render_base_url` | `_normalize_base_url` | `scripts/refresh_mlb_oddsapi.py` | its one caller |
| `RENDER_URL` in that caller's `_env_first(...)` | **removed** | same | **Confirmed set nowhere, ~5:15 PM CST (23:1xZ), names only, read-only:** 0 lines in `fleet_env/{web,refresh-worker,live-odds-worker}.json` and `local_production.env`, no `RENDER*` key name in any of the four, 0 in `scripts/fleet_role_spec.json`, and 0 in the environ of the 5 running role processes |
| `scripts/render_logs.py` | `scripts/fleet_logs.py` (`git mv`) | — | **`render_logs.py` is now a shim**: `import render_logs` IS the `fleet_logs` module (same object), and `py -3 scripts/render_logs.py ...` runs the same CLI. Callers moved: `check_venue_odds_hydration_census.py`, `measure_board_window_clip_rate.py`, `read_venue_capture_lag.py`, `venue_order_family_census.py` (`from fleet_logs import fetch_window`), `watch_488_convergence.py`, `watch_branch_overlap.py`; comments in `fetch_ncaaf_oddsapi_props_local.py`, `refresh_ncaaf_oddsapi.py`, `local_logstamp/sitecustomize.py`; `tests/test_local_logstamp.py`. `tests/test_render_logs_local.py` -> `tests/test_fleet_logs.py`, plus two shim tests |
| version payload `render_service_name` / `render_instance_id` / `render_external_url` (`/versionz`, `/healthz`, `/api/ops/version`; `home.py`, `ops.py`) | `service_name` / `instance_id` / `external_url` | — | **The old keys are KEPT as deprecated twins, same values**, because ledger readings and session tooling outside the repo read `version.render_*` (e.g. `deploys.md`, the 21:53Z 11-17 reading). In-repo readers: `scripts/mirror_manifest.py` now reads `instance_id` (falls back to `render_instance_id` for an older web) and writes manifest key `instance_id` (nothing reads that key); `tests/test_home_health.py`, `tests/test_ops.py` assert both. No template or JS reads any of them |
| ops debug trace `render_web_dyno` / `render_web_dyno_error` (`/api/ops/...` WNBA trace, `ops.py`) | `web_role` / `web_role_error` | — | `render_web_dyno` kept as a twin; no in-repo reader |
| substrate label `render` (`scripts/measure_correlation_arm_value.py` output) | `fleet` | — | matches `model_engine_standard.md` §3b, which now labels substrate 1 `fleet` (`render` before 2026-11-17) |
| fixtures `https://syndicate.onrender.com` | `http://127.0.0.1:10000` | — | `tests/test_artifact_publisher.py` (30), `tests/test_quote_state_publish_retry.py` (1); a `--publish-loopback` fleet sets exactly this URL. `SYNDICATE_EXTERNAL_URL` fixture in `tests/test_game_board_simulation_contract.py` too |

Test names renamed with their subjects: 8 (`test_bootstrap_hosted_data_*`, `..._on_the_web_role`,
`test_hosted_*` in `test_portfolio_auth.py`, `..._on_hosted_web`).

## Left on purpose (names)

- **Negative controls that name Render to prove it is refused:** `tests/test_base_url.py`
  (`RETIRED_RENDER_URL`), `tests/test_check_deploy_safety_fleet_logs.py`, `tests/test_local_production.py`
  (stray `RENDER_EXTERNAL_URL` must not leak), `tests/test_deploy_guard.py`,
  `tests/test_portfolio_monitor_probe.py`, and `fleet_logs.resolve_source("render")`, which exits.
- **Payload values / fields with no consumer, kept for shape compatibility:** `nba/cards.py`'s
  `source: "render_web_dyno_empty"` label and `live_lens_local.py`'s constant
  `running_on_render: False`. Renaming a served value is a contract change for no reader; do it
  only with a consumer check of stored artifacts.
- **Files held by other OPEN lanes (not section-scoped for these lines):**
  `scripts/local_production.py:475` (comment naming `_is_render_web_dyno()`) and `:525`
  (`render_logs --local`); `syndicate/features/football/sim_engine/smartsim2/ncaaf_calibration_profile.py:275`
  (`render_logs --text`, history); `syndicate/features/shared/artifact_publisher.py:934`/`:1427`
  (dated history, still true).
- **`.claude/hooks/deploy-guard.py:51`** docstring names `render_logs.py`: part 4's file, left
  for that commit.
- **The MLB native tools family** (frozen vendor code; ~150 lines over 9 files under
  `syndicate/features/mlb/native/tools/`): `daily_update.py`'s `_infer_render_base_url` /
  `_normalize_render_base_url`, CLI flags `--render-base-url` / `--render-cron-token` /
  `--render-timeout-seconds` / `--validate-render-frontend` / `--render-validation-*`, the
  `render-sync` subcommand, report stage `render_frontend_validation`, source value
  `render_api`, `eval/sync_render_live_lens_history.py`, `smoke/smoke_render_frontend.py`,
  and the on-disk directory `live_lens/render_sync/`. Already repointed at the fleet
  (render-retirement `193df776e`); only names remain. Renaming needs flag aliases, report-key
  twins and a data-path decision, and `.ps1` callers (`unified_daily_update.ps1`,
  `refresh_mlb_source_mirror.ps1`) — a task of its own. **Follow-up, not done here.**
- **`scripts/fleet_local.py`**: a `render_plan` field and comments "straight from `render.yaml`".
  Also a FUNCTIONAL gap found by the docs pass: `up` wants an `--env-snapshot` in the format of
  `snapshot_render_env.py`, a producer that was retired, so the local rehearsal harness may not
  run as-is. **Follow-up, not done here.**
- **Lowercase "Render" in code comments:** ~594 lines in 227 files under `syndicate/`,
  `scripts/`, `pipeline/` and ~194 in 111 test files. Nearly all are dated incident history
  ("Render's health check timed out at 5s", "measured on Render 2026-08-14"), which is why the
  code is shaped as it is. Only the comments the case-sensitive `RENDER*` grep found, and those
  next to a renamed name, were rewritten. Test function names that mention Render (several
  dozen, e.g. `test_run_tick_defaults_to_detached_subprocess_on_render`) were not renamed.

## Part 3 — docs

Rewritten to the fleet (present-tense Render instructions only; dated history kept, with
"(Render, retired 2026-09-30)" where it would read as current):
- `README.md` — the "Render deploy" section and badge are now "Production: the local fleet".
- `docs/ai_context/`: `end_to_end_context.md` (diagram, environments table, env table),
  `worker_architecture.md`, `runtime_execution_model.md`, `runtime_infrastructure.md`,
  `model_engine_standard.md` (§3b substrate label `render` -> `fleet`, with a note on reading old
  `render` citations), `season_opener_checklist_2026.md`, `render_retirement.md` (rename pointer),
  the four engine references, `nhl_model_inventory.md`, `basketball_model_inventory.md`,
  `local_production_runbook.md` (the log-lines paragraph only), `prop_evidence_reference.md`,
  `venue_order_reconciliation.md`.
- `docs/`: `render_data_authority.md`, `render_container_memory_breakdown.md` (records, now with a
  "what is true now" note), `nba_wnba_source_fallback_runbook.md`, `debug_playbook.md`,
  `intelligence_*` (3), `syndicate-skills.md`, `shared_refresh_hydration_contract.md`.
- Repo root: `RENDER_SELF_HOST_BACKLOG.md`, `RENDER_SELF_HOST_REFACTOR_PLAN.md` (a dated
  "Render-era record" note on top).
- `.github/`: `copilot-instructions.md` ("RENDER 502 STATUS" bucket -> "WEB 502 STATUS"), the 5
  `betting-board-*` agents and 21 skills ("Render parity" -> "fleet parity", the
  "Render-emulated" step -> a fleet-equivalent run with paper money only).

Left as records: `docs/ai_context/todo.md` / `todo_closed.md`, `docs/fix_notes_log.md`,
`docs/reports/**`, dated handoffs and preregistrations, `docs/ai_context/patches/`,
`mlb_sim_accuracy_assessment_and_optimization_plan.md` (dated 2026-07-16), and
`.github/workflows/daily-update.yml` (its Render lines are retirement notes).

Also noticed by the docs pass, not changed (outside this lane): the runbook's line 152 says
"the four Render dashboard crons" (`SCHEDULED_JOBS` now holds more) and that a HUP keeps the
old `RENDER_GIT_COMMIT`; `deploy_ids.json` holds Render `srv-`/`dep-` ids and nothing reads it;
`scripts/fleet_role_spec.json` carries the `ODDS_API_KEY` value frozen from `render.yaml`
(secret hygiene, as before in `render.yaml`).

## Part 4 — OWED, waits on the user

Do ONLY after the user confirms in chat that Render's GitHub App is uninstalled from
`mostgood1/Syndicate` (or the three Render services are deleted). Until then the deploy guard
refuses any push carrying `render.yaml`, which is correct; do not use the override.
1. `git rm render.yaml`.
2. `tests/test_fleet_role_spec.py`: delete the comparison against `render.yaml`
   (`test_spec_is_render_yaml_key_for_key_and_values_expand_identically`; it already skips when
   the file is gone). Keep `test_env_build_never_opens_render_yaml_or_render_env`.
3. `tests/test_render_yaml_envs.py`: delete it. It READS `render.yaml` and would fail without it.
4. `scripts/pending_deploys.py`: `_RUNTIME_SEED_FILES` seeds its reachability closure with
   `render.yaml` ("what Render actually starts"). Repoint it at what the fleet starts
   (`scripts/local_production.py` role commands + `SCHEDULED_JOBS`, `scripts/fleet_role_spec.json`)
   BEFORE the delete, or the closure silently loses every script only `render.yaml` named.
5. `.claude/hooks/deploy-guard.py`: delete the `render.yaml` push rule (shape 3,
   `_push_carries_render_yaml`, `_render_yaml_push_reason`, `RENDER_YAML_PUSH_OVERRIDE` /
   `SYNDICATE_ALLOW_RENDER_YAML_PUSH`) and its tests: `tests/test_deploy_guard.py`
   `test_render_yaml_push_needs_no_commit_binding`, `test_push_carrying_render_yaml_is_blocked`,
   `test_render_yaml_push_is_blocked_even_with_all_three_locks`, the bare-override test at
   `:589-600`, `test_render_yaml_push_requires_all_three_services`,
   `test_render_yaml_push_allowed_with_a_reason_and_all_three_locks`; and
   `tests/test_deploy_locks_cron.py` `test_a_render_yaml_push_does_not_demand_cron_claims`.
   Rename `render_logs.py` -> `fleet_logs.py` in its docstring (`:51`).
6. `CLAUDE.md`: delete the bullet "A `render.yaml` push is REFUSED by the deploy guard".
7. `.claude/hooks/lane_claims.py` and `tests/test_lane_guard_prohibition_marker.py` mention
   `render.yaml` as a claim-parsing example (a lane's "never `render.yaml`" prohibition); they
   do not read the file and need no change.

## Part 5 — left in place, protective

`scripts/local_production.py` strips stray `RENDER*` names from the operator's shell
(`derive_role_env`) and never carries `RENDER_API_KEY` (`NEVER_CARRY`); `run_ci_suite.py`,
`replay_diff_gate.py` and `fleet_local.py` strip `RENDER_API_KEY` from children. These guard
against a leftover shell variable and need nothing from Render. Remove only if the user asks.
