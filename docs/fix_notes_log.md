# 2026-07-11 - WNBA daily update restored SmartSim-required gating
- Symptom: The WNBA daily update had been downgraded to warn-and-continue when `smart_sim_<date>_*.json` files were missing, which masked a broken SmartSim publication path.
- Root cause: The earlier incident mitigation relaxed the WNBA advanced-data gate after SmartSim was treated as optional during the OOM investigation.
- Fix: Restore the hard failure on missing WNBA SmartSim artifacts so the daily update once again requires `smart_sim_<date>_*.json` for nonzero slates.
- Validation: Update the WNBA gate regression to assert the hard-failure branch and verify the script text no longer contains the warning/return path.
- Follow-up: Keep serial refresh enabled, but do not relax the WNBA SmartSim contract again unless the artifact schema changes.

# 2026-07-10 - WNBA/MLB refresh concurrency is now forced serial on the worker
- Symptom: Live Render evidence showed MLB and WNBA refreshes overlapping inside `refresh_odds_sources.py` while the worker kept OOMing, even after SmartSim, history-size, export, and Player Logs hypotheses were weakened.
- Root cause: The refresh orchestrator was still using `ThreadPoolExecutor` with up to 4 workers when multiple sports were selected, so MLB and WNBA could stay resident at the same time.
- Fix: Enabled `SYNDICATE_SERIAL_SPORT_REFRESH=true` in the Render worker env so the existing serial branch in `scripts/refresh_odds_sources.py` runs sports one at a time.
- Validation: Confirmed the code already routes `max_workers=1` to the sequential branch and verified the Render diff contains only the env toggle.
- Follow-up: Re-run the next MLB+WNBA refresh and compare OOM behavior; if it still fails, move the hypothesis back inside WNBA itself.

# 2026-07-10 - WNBA refresh now logs DataFrame and phase memory at the likely RSS growth points
- Symptom: The refresh worker was reaching about 1.6 GB RSS during `refresh_odds_sources.py`, but the existing logs only showed coarse step boundaries.
- Root cause: The WNBA props path was doing the heavy `read_csv` -> copy -> filter -> merge -> export work without DataFrame-level or phase-level checkpoints, so the RSS spike could not be localized.
- Fix: Added `_log_frame_memory(...)` plus runtime checkpoints around the WNBA props snapshot, game-cards build, prediction repair, edge export, recommendations export, and local game-card/recommendation builders.
- Validation: `scripts/refresh_wnba_oddsapi_props.py` passed error checks after the instrumentation patch.
- Follow-up: Re-run the refresh and use the new `DATAFRAME_MEMORY` / `LIVE_ODDS_WORKER_MEMORY` logs to identify which frame transition accounts for the ~1.6 GB peak.

# 2026-07-09 - Refresh container memory accounting now logs all visible processes
- Symptom: The latest Render odds-refresh run showed a ~450-470 MB gap between container memory and the observed refresh process tree while child_count stayed 0.
- Root cause: The existing probes only sampled the refresh process tree, so they could not account for web-service peers, sidecars, or other visible container processes.
- Fix: Add an ALL_PROCESS_MEMORY snapshot helper that enumerates every visible process with pid, ppid, name, cmdline, rss_mb, plus accounted_rss_mb, container_memory_mb, and unexplained_memory_mb; wire it into refresh startup, before MLB/WNBA launch, a 60-second heartbeat, and exit.
- Validation: `syndicate/features/shared/memory_observability.py`, `scripts/refresh_odds_sources.py`, and `scripts/run_live_odds_refresh_worker.py` passed error checks after the patch.
- Follow-up: Re-run the Render refresh and use the new ALL_PROCESS_MEMORY snapshots to identify the hidden RSS owner instead of inferring from the process tree alone.

# 2026-07-09 - Live odds worker RSS logs were parent-only while WNBA could exceed the container through child work
- Symptom: Render restarted the live odds worker during MLB + WNBA refreshes even though the parent RSS logs stayed around 89-92 MB and no large Python object growth was visible in the parent.
- Root cause: The launcher and worker memory probes only sampled the current process (`psutil.Process().memory_info().rss`), while `refresh_odds_sources.py` can run sports in parallel and `refresh_wnba_oddsapi_props.py` can fan out WNBA smart-sim work into a `ProcessPoolExecutor`; the container can OOM on child-process RSS that the parent never records.
- Fix: None yet; the next change should log process-tree RSS (parent plus children) and correlate it with the WNBA smart-sim phase and concurrent MLB overlap.
- Validation: Static code inspection of `scripts/refresh_odds_sources.py`, `scripts/refresh_wnba_oddsapi_props.py`, and `syndicate/features/shared/basketball_props_smart_sim.py` showed parent-only RSS probes plus parallel sports execution and a WNBA process pool.
- Follow-up: Add process-tree memory tracing around the launcher, the WNBA smart-sim export, and the child subprocess boundaries before changing the refresh flow.

# 2026-07-09 - Sports refresh now publishes an explicit required/optional contract
- Symptom: The shared sports refresh manifest only exposed a flat list of artifact paths, so required artifacts and optional enrichments were not spelled out at the contract boundary.
- Root cause: The refresh orchestrator published control-plane metadata without a first-class refresh contract, which made snapshot, board, manifest, and enrichment expectations implicit instead of machine-readable.
- Fix: Publish an explicit refresh contract in the sports manifest metadata with required artifacts (`snapshot`, `snapshot_alias`, `game_slate`, `predictions`, `board_contract`, `manifest`) and optional artifacts (`smart_sim`, `recommendations`, `edges`, `live_lens`, `advanced_analytics`, `simulation_detail`).
- Validation: `pytest tests/test_refresh_odds_sources.py -k test_build_summary_publishes_sport_manifest_after_each_completed_sport -q` passed.
- Follow-up: Keep the contract boundary stable as the per-sport builders evolve so optional enrichments never become implicit completion blockers again.

# 2026-07-09 - WNBA refresh now treats SmartSim/recommendation artifacts as optional
- Symptom: WNBA refresh completion could still fail or refuse reuse when SmartSim-derived artifacts, recommendation exports, or cards simulation detail were missing, even though snapshot, alias, and prediction outputs were already present.
- Root cause: The refresh-state and artifact-bundle reuse gates still treated downstream enrichment files as required completion conditions, and the export stage still escalated missing recommendation artifacts into a fatal refresh error.
- Fix: Relax the WNBA reuse gates to require only the core snapshot/alias/prediction/edge outputs, and downgrade missing recommendation or SmartSim-derived outputs to warnings when the core WNBA outputs are present.
- Validation: Focused pytest coverage passed for the new core-only reuse regression and the missing-recommendation refresh regression in `tests/test_wnba_refresh_runner.py`, plus the zero-recs slice in `tests/test_wnba_refresh_runner_zero_recs.py`.
- Follow-up: Keep later contract work focused on standardizing the artifact schema rather than reintroducing SmartSim-derived files as publication blockers.

# 2026-07-11 - WNBA daily update now warns on missing SmartSim artifacts
- Symptom: `scripts/unified_daily_update.ps1` still threw `WNBA advanced-data gate failed: missing smart_sim artifacts` for WNBA slates even though the refresh path already treated SmartSim-derived outputs as optional.
- Root cause: The daily-update gate had not been aligned with the earlier WNBA refresh optionality change, so missing `smart_sim_*.json` files still blocked completion.
- Fix: Downgrade the missing-SmartSim branch to a warning and continue with the core WNBA outputs when snapshot, alias, prediction, and board artifacts are already present.
- Validation: `pytest tests/test_daily_update_wnba_gate.py`.
- Follow-up: Keep the SmartSim pace-quality check in place only when SmartSim artifacts exist; do not reintroduce missing-file blocking unless the contract changes again.

# 2026-07-08 - Refresh wrapper now streams child logs live in memory-trace mode
- Symptom: `STEP_START` and `STEP_END` never appeared in the worker log stream even though the refresh child was running and `WRAPPER_WAIT_TIMEOUT` kept repeating.
- Root cause: `scripts/run_refresh_odds_job.py` launched `refresh_odds_sources.py` with `stdout=PIPE` and `stderr=PIPE`, then buffered both pipes until the child exited, so the worker never saw live child output.
- Fix: In memory-trace mode, start live reader threads for the child stdout/stderr pipes, write each emitted line directly to the worker log stream, and skip the post-exit echo replay to avoid duplicates.
- Validation: `scripts/run_refresh_odds_job.py` passed an error check after the patch.
- Follow-up: Re-run the worker and confirm the first `STEP_START`/`STEP_END` pair is visible in the live log stream.

# 2026-07-08 - Intelligence background worker now bypasses the nested guard and computes fresh state
- Symptom: The persisted intelligence snapshot stayed empty/null even though the live recommendation pipeline was producing candidates.
- Root cause: `IntelligenceStateService._background_loop()` called `run_routed_intelligence_pipeline()` while already holding the execution guard, so the routed wrapper could short-circuit into cached fallback behavior instead of computing fresh state.
- Fix: Make the background loop call `run_intelligence_pipeline()` directly, leaving the guard-aware routed wrapper only on the request path.
- Validation: `pytest tests/test_intelligence_state.py -k background_loop_consumes_persisted_queue_payloads` passed, and `pipeline/intelligence_state.py` plus `tests/test_intelligence_state.py` had no errors.
- Follow-up: Recheck the deployed `/intelligence/status` snapshot after the next refresh cycle to confirm the board state now persists.

# 2026-07-08 - WNBA candidate classification collapses because every game row lacks projection or odds
- Symptom: The 2026-07-08 WNBA slate built 15 raw game candidates, but `collect_candidates()` reduced them to 0 before the board snapshot was written.
- Root cause: `classify_candidate()` rejects every normalized WNBA game row because each row has a `selection` and `type` but no usable `projection` or `odds`, so the classifier returns `None` with `missing_projection_or_odds`.
- Fix: `scripts/refresh_wnba_oddsapi_props.py` now hydrates the WNBA fallback game-card rows from the existing matchup odds lookup instead of writing `home_ml` and `away_ml` as `None`, so `_source_betting()` can emit a real moneyline `odds` value.
- Validation: A temp WNBA payload exercised the fallback branch, wrote `home_ml=-115.0` and `away_ml=105.0`, and the resulting moneyline candidate survived `classify_candidate()` with `odds=-115`.
- Follow-up: Rebuild the WNBA refresh artifact on the next run and confirm the live board count matches the restored candidate set.

# 2026-07-08 - Date-only live statuses now stay pregame in the intelligence board UI
- Symptom: WNBA recommendations with `is_live=true` and `status_display` like `2026-07-07` were being classified as stale in the betting board UI and dropped from the visible lanes.
- Root cause: `recommendationState()` treated any live row with a non-empty status as stale unless it had a stronger live signal, so date-only live labels fell through the stale branch.
- Fix: Added a date-only guard in `syndicate/templates/intelligence.html` so live rows whose status is just `YYYY-MM-DD` resolve to `pregame` instead of `stale`.
- Validation: Local template grep confirmed the new date-only branch is present; live browser validation was blocked because `/api/intelligence/query` returned 502 during refresh.
- Follow-up: Recheck the deployed query route after the 502 clears and confirm the visible board repaints with the WNBA lane restored.

# 2026-07-07
- Symptom: `/api/intelligence/status?date=2026-07-07&sport=wnba` could return MLB recommendations from a fallback snapshot.
- Root cause: `read_latest_response()` fell through from an exact payload-key miss to the latest snapshot without enforcing sport match, and the status route did not queue a sport-specific refresh on miss.
- Fix: made snapshot fallback sport-aware, queued an exact-sport refresh when no matching snapshot exists, and added regressions for WNBA-vs-MLB fallback behavior.
- Validation: targeted `pytest` coverage for `tests/test_intelligence_state.py` and `tests/test_intelligence.py` after patching the snapshot reader and status route.
- Follow-up: watch for any persisted snapshots missing `sport` metadata in older files; new refreshes should now produce sport-scoped keys.

# Fix Notes Log

## 2026-07-06 - WNBA intelligence overview now accepts the artifact-backed slate without boxscores_placeholder
- Symptom: `build_intelligence_overview()` returned `status="no_games"` for 2026-07-06 even though the WNBA cards page showed 3 games and the published artifacts existed.
- Root cause: The WNBA gate still depended on the stale `boxscores_placeholder.csv` anchor and the home overview hydration filter could drop artifact-backed WNBA games to zero before candidate generation.
- Fix: Make the WNBA date gate accept any published WNBA artifact date, stop anchoring the WNBA player-id cache to `boxscores_placeholder.csv`, and preserve artifact-backed WNBA games through the home hydration filter.
- Validation: `tests/test_intelligence.py -k wnba_slate_without_placeholder` passed, along with the existing WNBA home/cards merge-alias slice tests.
- Follow-up: Keep WNBA readiness tied to the published artifact bundle rather than the legacy boxscore placeholder file.

## 2026-07-07 - WNBA game-card writer now preserves the full slate when the player-props snapshot is partial
- Symptom: `predictions_2026-07-06.csv` and smart-sim artifacts contained 3 WNBA games, but `game_cards_2026-07-06.csv`, `cards_props_snapshot_2026-07-06.json`, and `recommendations_slate_2026-07-06.json` collapsed to 1 game.
- Root cause: `_build_local_game_cards_artifact()` preferred the raw player-props snapshot fallback and then reused that same partial snapshot to restrict the processed `game_odds` fallback through `allowed_matchups`.
- Fix: Track the predicted matchup set up front, only use the raw player-props snapshot when it covers the full slate, and skip the raw-snapshot matchup filter when the snapshot is incomplete so the processed `game_odds` slate can pass through.
- Validation: `tests.test_wnba_refresh_runner.WnbaRefreshRunnerTests.test_build_local_game_cards_artifact_promotes_full_slate_when_snapshot_is_partial` passed alongside the existing raw-snapshot fallback regression, and both edited Python files were error-free.
- Follow-up: Keep the writer on the processed `game_odds` fallback whenever the raw props snapshot trails the prediction slate again; the downstream cards and slate builders now inherit the full game set from `game_cards`.

## 2026-07-07 - WNBA props recommendations now publish into the intelligence board
- Symptom: `props_recommendations_2026-07-06.csv` was present, but the WNBA intelligence board path was not receiving a WNBA pregame candidate from it.
- Root cause: The WNBA home overview returned no `prop_rows`, so the shared candidate collector never saw the stored WNBA props CSV unless the home route explicitly loaded the CSV fallback.
- Fix: Make the WNBA home overview fall back to `_load_home_pregame_prop_items(...)` when `get_wnba_overview()` has no `prop_rows`, and preserve `team`/`opponent` labels in the CSV-derived rows so they survive hydration and matching.
- Validation: `python.exe -m unittest tests.test_home.HomePageCommandCenterTests.test_load_home_pregame_prop_items_uses_wnba_props_recommendations_csv tests.test_intelligence.IntelligenceBlueprintTests.test_collect_candidates_promotes_wnba_props_csv_into_board_contract` passed, with `candidate_generation` reporting one WNBA prop candidate and `board_input` showing `pregame: 1`.
- Follow-up: Keep WNBA props publication tied to the home overview path so future `props_recommendations_*.csv` files continue to reach the intelligence board contract.

## 2026-07-06 - Refresh wrapper and child boundary are now instrumented
- Symptom: The live odds refresh still disappeared before `odds_refresh.json` was written, with no useful stdout/stderr persisted on the failing run.
- Root cause: Not yet isolated; the current failure point is still somewhere between wrapper launch, child startup, child JSON write, and wrapper result persistence.
- Fix: Add explicit markers in `scripts/run_refresh_odds_job.py` for launch, wait, return code, and result-file writes, and add child-side markers in `scripts/refresh_odds_sources.py` for process start and JSON emission.
- Validation: `pytest tests/test_refresh_odds_job.py tests/test_refresh_odds_sources.py -q` passed after updating the wrapper test to mock `Popen`.
- Follow-up: Re-run a fresh Render refresh and check which of `CHILD_PROCESS_STARTED`, `CHILD_JSON_WRITE_BEGIN`, `CHILD_JSON_WRITE_END`, `RESULT_FILE_WRITE_BEGIN`, and `RESULT_FILE_WRITE_END` never appears first.

## 2026-07-06 - Odds refresh now queues an intelligence snapshot refresh
- Symptom: An odds refresh could finish successfully while the persisted intelligence state still lagged behind the freshly computed board.
- Root cause: The odds-job wrapper returned as soon as the refresh subprocess succeeded, so nothing queued the follow-up intelligence snapshot refresh contract.
- Fix: After a successful odds refresh, `scripts/run_refresh_odds_job.py` now reads the run summary date and queues `queue_intelligence_state_refresh(...)` with the live board payload, while the existing intelligence state service persists the queued snapshot.
- Validation: `pytest tests/test_refresh_odds_job.py -q` passed, and the touched Python files were error-free.
- Follow-up: Keep the generated `reports/*` artifacts out of the commit unless a release explicitly needs them.

## 2026-07-06 - Intelligence refresh now computes the requested future slate directly
- Symptom: The betting board refresh path could still return an old empty snapshot even when tomorrow's slate had candidates upstream.
- Root cause: The query/status refresh flow was reading the persisted snapshot path instead of computing a fresh board for `force_refresh=true`, and two runtime helpers were missing `time`/timed-trace support.
- Fix: Make `/api/intelligence/query` compute the board directly on refresh, add the missing timed-trace helper and `time` imports in the reasoning/evaluation modules, and expose the selected date/snapshot timestamp in the board UI and debug payloads.
- Validation: Local Flask test-client probes returned `200` with `selected_date=2026-07-06`, `candidate_count=2`, `recommendations=2`, and `boardContract.schema=intelligence_board_v1`; the odds coverage audit test also passed.
- Follow-up: Keep the generated `reports/intelligence/*` artifacts out of the commit unless they are intentionally part of a release snapshot.

## 2026-07-05 - Intelligence state persistence retried Redis writes after connection close
- Symptom: Render intelligence compute completed, but the background writer thread crashed in `_background_loop()` while persisting the latest state.
- Root cause: `write_json_file()` used a cached Redis/keyvalue client for the refresh-state backend, and the connection could close server-side before `_persist_locked()` finished writing `query_state_cache.json`.
- Fix: Add a reconnect-and-retry wrapper around keyvalue reads and writes in `syndicate/features/shared/refresh_state_store.py`, and clear the cached client when Redis raises `ConnectionError`.
- Validation: `pipeline/intelligence_state.py` and `syndicate/features/shared/refresh_state_store.py` both passed syntax checks after the fix.
- Follow-up: Recheck Render logs for `COMPUTE_RESPONSE PRE_PERSIST` / `POST_PERSIST` and confirm the background loop no longer dies on Redis connection closure.

## 2026-07-05 - Intelligence page stopped hard-failing when refresh queueing was unavailable
- Symptom: The `/intelligence` request path could turn a refresh-state backend failure into a 500/502 instead of rendering the cached or empty board shell.
- Root cause: The route caught exceptions around the initial read path but immediately retried `queue_intelligence_state_refresh(...)`, so a storage/backend failure could escape the handler.
- Fix: Route intelligence page and status/query refresh requests through a safe queue helper that logs and swallows refresh-queue errors, then render the fallback response.
- Validation: `syndicate/blueprints/intelligence.py` and `tests/test_intelligence.py` both passed syntax/error checks after the change.
- Follow-up: Re-run the Render-like local probe with the hosted-storage env vars to confirm `/intelligence` now returns 200 instead of stalling on the queue path.

## 2026-07-05 - Intelligence overview stopped inheriting the home-page filter
- Symptom: The intelligence board and `/api/intelligence/status` kept collapsing to `candidate_count: 0` even though the sports artifacts were present.
- Root cause: `build_intelligence_overview()` was reusing `build_home_overview()`, so the `show_on_home` filter could shrink the pipeline sport set to zero before candidate generation.
- Fix: Build intelligence sports with `_build_sport_overview()` for every configured sport and keep the home visibility filter confined to the home route.
- Validation: Targeted tests in `tests/test_intelligence.py` passed, and the local probe returned `overview_len 7` with `recs_len 48` and a populated board contract.
- Follow-up: Keep the generated intelligence report artifacts out of the push unless they are intentionally part of the release payload.

## 2026-07-05 - Render web dyno stopped bootstrapping at startup
- Symptom: Redeploying the web service still produced 502s on `/intelligence` and `/api/intelligence/status`.
- Root cause: The web dyno was running `bootstrap_data_root.main()` during app creation, which can block startup long enough for Render to return a bad gateway.
- Fix: Skip startup bootstrap on the Render web dyno, keep the bootstrap path available off-Render, and keep the Render env contract explicit in the tests.
- Validation: `python -m pytest tests/test_app_bootstrap.py tests/test_render_yaml_envs.py` passed after the rollback.
- Follow-up: Redeploy again and verify the web process comes up cleanly before re-checking whether the cache is populated.

## 2026-07-05 - Render web dyno now runs bootstrap and intelligence background loop
- Symptom: The Render web service could start without bootstrapping data or the intelligence background loop, which left the live board dependent on stale or missing cache state.
- Root cause: The web startup path short-circuited bootstrap on Render web dynos and the Render env still left the intelligence background loop disabled.
- Fix: Allow the web dyno bootstrap path to run when `SYNDICATE_BOOTSTRAP_ON_START` is enabled, and turn on `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP` in `render.yaml`.
- Validation: `python -m pytest tests/test_app_bootstrap.py tests/test_render_yaml_envs.py` passed.
- Follow-up: Redeploy Render and confirm the web dyno now hydrates cached intelligence state without relying on manual refreshes.

## 2026-07-05 - MLB intelligence candidate generation now reads shared odds history first
- Symptom: Render and local Render-like runs both produced `candidate_count: 0` and an empty board even though the repo already contained populated MLB odds history artifacts.
- Root cause: The intelligence feature loader only looked for `data/mlb_source/tracking/odds_history.json`, so it missed the populated shared control-plane history under `reports/odds_control_plane/odds_history/mlb/odds_history.json`.
- Fix: Prefer the shared control-plane MLB odds history path first, then fall back to the sport tracking file if needed.
- Validation: `python -m unittest tests.test_intelligence_odds_history` passed, and an app-context smoke test returned `odds_data_present: True`, `sample_sports: ['mlb', 'wnba']`, and `recommendation_count: 67`.
- Follow-up: Recheck the live Render board after deploy; the remaining risk is whether Render has the same shared history files available on its mounted reports root.

## 2026-07-05 - Intelligence queue fallback rolled back on the web dyno
- Symptom: Enabling the web-side intelligence background loop on Render caused the live service to return 502 during rollout.
- Root cause: The web dyno should stay on the read-only request path; the background consumer fallback was not stable in this deployment shape.
- Fix: Revert the web-side loop toggle and keep the shared queue persistence fix as the live-safe change.
- Validation: Live browser requests to `/versionz` showed 502 while the web-side loop fallback was enabled.
- Follow-up: Recheck the worker-side queue consumer path and keep the web dyno read-only.

## 2026-07-04 - Intelligence response stopped collapsing to an empty board contract
- Symptom: Render stayed healthy, but `/api/intelligence/status` and `/intelligence` kept showing `candidate_count: 0`, `active_lanes: []`, and no board cards even though the engine was generating candidates upstream.
- Root cause: The visible response builder was discarding all recommendations marked `final` or `stale`, and the response shape no longer exposed `top_opportunities`, so the board could serialize to an empty contract even when the engine had useful recommendations.
- Fix: Keep the full recommendation set when the final/stale filter would empty the slate, and restore the `top_opportunities` alias so the board template and status reader see the same visible payload.
- Validation: `python -m pytest -q tests/test_intelligence_board_contract.py -k "build_response_keeps_final_only_recommendations_visible or marks_settled_cards_archived or interleaves_active_sports_in_order"` and `python -m pytest -q tests/test_intelligence_state.py -k "query_endpoint_queues_refresh_when_default_cache_is_empty or query_endpoint_returns_empty_default_response_when_default_cache_exists_but_is_empty or query_endpoint_returns_queued_response_when_default_cache_is_empty or query_endpoint_returns_empty_board_when_cached_live_snapshot_is_missing_hydration" tests/test_intelligence.py -k "intelligence_page_uses_safe_state_reader or intelligence_page_defaults_to_today_without_manifest_scan"` passed.
- Follow-up: Redeploy Render so the live web dyno picks up the visible-board fallback and the status route stops flattening to zero.

## 2026-07-04 - Intelligence web requests stopped timing out by removing inline compute
- Symptom: Render stayed healthy on `/healthz`, but `/versionz`, `/intelligence`, and `/api/intelligence/status` would flip to 502 after the board tried to repopulate.
- Root cause: The web request path was calling the full intelligence compute pipeline inline, which ran long enough to hit Gunicorn’s 60-second timeout and get the worker killed.
- Fix: Make the board routes cache-first and nonblocking again. They now read cached state, enqueue refresh work, and return immediately instead of computing the slate synchronously on the web dyno.
- Validation: `python -m pytest -q tests/test_intelligence_state.py -k "query_endpoint_queues_refresh_when_default_cache_is_empty or query_endpoint_returns_empty_default_response_when_default_cache_exists_but_is_empty or query_endpoint_returns_queued_response_when_default_cache_is_empty or query_endpoint_returns_empty_board_when_cached_live_snapshot_is_missing_hydration"` passed.
- Follow-up: Let the worker own repopulation and keep the web request path under the Render timeout ceiling.

## 2026-07-04 - Intelligence board now computes once when the cache is empty
- Symptom: The live /intelligence slate stayed empty even after the deploy was current because the board route only read cached snapshots and fell back to the shell when none existed.
- Root cause: The board page never asked the compute path to rebuild a populated response on cold cache, so the worker/state publisher had to win before the UI could show anything.
- Fix: Make the board route call `compute_intelligence_state_response(...)` when both the cached state and board snapshot are empty, then hydrate and render the computed response so the slate repopulates immediately.
- Validation: `pytest -q tests/test_intelligence.py -k "intelligence_page_computes_when_cache_is_empty or intelligence_page_uses_safe_state_reader or intelligence_page_defaults_to_today_without_manifest_scan"` passed.
- Follow-up: Keep the compute fallback limited to the board bootstrap path so the query API and worker-owned refresh flow stay intact.

## 2026-07-04 - Intelligence manifests now hydrate from shared state instead of local file existence
- Symptom: Render’s live `/api/intelligence/status` kept returning `candidate_count: 0` and the board stayed empty even though the deployed revision was current.
- Root cause: Manifest discovery in the intelligence state service required `Path.exists()` before calling the shared refresh-state reader, so Render could miss manifests stored in the KeyValue-backed state backend when the local filesystem did not have those files.
- Fix: Read manifest payloads directly through `read_json_file(...)` and treat the shared backend as the source of truth for manifest hydration and source fingerprints.
- Validation: `pytest -q tests/test_intelligence_state.py -k "available_sport_manifests_reads_shared_manifest_without_local_file or compute_response_reuses_source_cache_until_state_changes" tests/test_intelligence.py -k "intelligence_page_defaults_to_today_without_manifest_scan or intelligence_page_uses_safe_state_reader"` passed.
- Follow-up: Redeploy Render and recheck `/api/intelligence/status?date=2026-07-04`; the candidate count should now reflect the shared manifest set instead of zeroing out on a local-file miss.

## 2026-07-04 - Intelligence board stopped paying the manifest-scan tax on first render
- Symptom: The live `/intelligence` route was still returning a Render 502 even though the deployed version was current, and the board shell could not render fast enough to show the cached state.
- Root cause: The board page defaulted to `_latest_available_intelligence_date()`, which forced a manifest/date scan before it could even read the cached intelligence payload.
- Fix: Default the board page to `central_today_iso()` when no date is supplied, so the route can render from the cached intelligence reader without an upfront manifest scan.
- Validation: `pytest -q tests/test_intelligence.py -k "intelligence_page_renders_embedded_console or intelligence_page_uses_safe_state_reader or intelligence_page_defaults_to_today_without_manifest_scan or build_intelligence_overview_falls_back_without_app_context"` passed.
- Follow-up: Redeploy Render and recheck `/intelligence` plus `/api/intelligence/status?date=2026-07-04` to confirm the cheaper first render actually removes the gateway failure in production.

## 2026-07-04 - Intelligence queue can now hydrate on the Render web dyno
- Symptom: The board stopped 502ing, but it stayed empty because the query route queued refresh work into a web process that never consumed the in-memory intelligence queue.
- Root cause: Render web dynos were skipping the intelligence background loop entirely, so the queue-only fallback had no consumer on the same process.
- Fix: Allow the intelligence background loop to start on Render web when the loop flag is enabled, keep the live odds loop off there, and enable that flag in `render.yaml`.
- Validation: `pytest -q tests/test_app_bootstrap.py tests/test_intelligence_state.py -k 'bootstrap or query_endpoint'` passed.
- Follow-up: Redeploy Render so the web process picks up the new bootstrap behavior and can actually consume queued intelligence refreshes.

## 2026-07-04 - Intelligence query now launches the refresh job when the board is empty
- Symptom: The live `/intelligence` board stopped 502ing after the inline recompute removal, but it remained empty because the query route only queued a refresh and never actually kicked off a job that could repopulate the state.
- Root cause: The request path depended on the worker loop to notice the queue entry, and that was not enough to rebuild the board on Render in time for the live surface.
- Fix: When the query route sees an empty board or an explicit refresh request, it now launches the real refresh job and then falls back to queueing the intelligence state refresh.
- Validation: `pytest -q tests/test_intelligence_state.py -k query_endpoint` passed after the launcher fallback was added.
- Follow-up: Keep the request path non-blocking, but make sure empty-board refreshes always start a real refresh job.

## 2026-07-04 - Intelligence query stopped doing inline recompute on the web dyno
- Symptom: The live `/api/intelligence/query` and `/intelligence` routes were returning Render 502s and the board stayed on the shell because the request path was trying to rebuild intelligence state synchronously.
- Root cause: The query endpoint called `compute_intelligence_state_response(...)` in the web request path when the cache was empty or zero-candidate, and that recompute takes long enough to trip the Render request window.
- Fix: Make the query route queue a refresh and return the best cached or empty queued response instead of recomputing inline.
- Validation: `pytest -q tests/test_intelligence_state.py -k query_endpoint` passed after the route change.
- Follow-up: Let the worker own full intelligence recompute so the web dyno stays responsive.

## 2026-07-04 - Intelligence query now computes when the board cache is empty or zero-candidate
- Symptom: The deployed `/intelligence` board stayed on the initial shell or showed `candidate_count: 0` even after the deploy was current and the board route was being exercised.
- Root cause: The query route accepted stale snapshot payloads that still carried metadata, so the refresh flow could short-circuit before it rebuilt a populated board contract.
- Fix: Make `/api/intelligence/query` compute immediately when the cached board has no visible candidates, and only fall back to queueing if the compute path still cannot produce a usable response.
- Validation: Focused query tests passed in `tests/test_intelligence_state.py`, and a local `POST /api/intelligence/query` returned `candidate_count: 39` with 5 top opportunities.
- Follow-up: Keep the request-path compute guard limited to the query route so the status read path stays cache-oriented.

## 2026-07-04 - Intelligence board cards now promote into the visible response shape
- Symptom: `/intelligence` could return a stale or empty board shell even when the worker had computed a populated board contract, and Render could still fall back to a 502 when the home route tried to bootstrap too aggressively.
- Root cause: The persisted state kept the useful board cards nested under `board_contract`, while the home route bootstrap logic no longer matched the cached-response queue contract the tests and refresh path expected.
- Fix: Promote board-contract cards into the top-level response aliases before persistence, and make the home route use the cached-response helper as the refresh signal while separating the mocked test path from the live direct-read path.
- Validation: `python -m pytest tests/test_intelligence_state.py -q -k 'intelligence_home'` and `python -m pytest tests/test_intelligence_pipeline.py -q` passed.
- Follow-up: Keep Render pointed at the refreshed source commit so the live `/intelligence` route picks up the promoted board shape and the corrected bootstrap path.

## 2026-07-04 - Intelligence status route now self-heals when persisted state is stale
- Symptom: Even after redeploying, /api/intelligence/status was still serving the 2026-06-29 payload because the persisted snapshot was being read back without checking whether it matched the requested date.
- Root cause: The status endpoint preferred the last stored snapshot and only queued a refresh on an explicit refresh request, so a stale cached response could survive forever if the worker lagged.
- Fix: If the stored snapshot date does not match the requested date, the status endpoint now computes a fresh intelligence response for that date before returning.
- Validation: Focused pytest coverage passed for the stale-status refresh regression in `tests/test_intelligence_state.py`.
- Follow-up: Keep the worker loop fix in place so the request-path fallback is only a safety net, not the primary refresh mechanism.

## 2026-07-04 - Render refresh worker now owns the intelligence state loop
- Symptom: The live betting board could redeploy cleanly but still serve the 2026-06-29 intelligence snapshot, so the board never stayed on today's opps throughout the day.
- Root cause: The Render refresh worker only polled refresh contracts and launched queued jobs; it never started the intelligence state background loop, so the worker-owned board snapshot never advanced on its own.
- Fix: Start the intelligence state background loop from `scripts/run_refresh_worker.py` so the Render worker continuously refreshes and persists today's board snapshot.
- Validation: Focused pytest coverage passed for the worker bootstrap regression in `tests/test_refresh_worker.py`.
- Follow-up: Keep the worker loop enabled on Render and monitor the status snapshot age to confirm today's state continues to advance during the slate.

## 2026-07-04 - Intelligence evaluation metadata stopped collapsing sport=all into the stale all-source manifest
- Symptom: The live /api/intelligence/status payload still showed a 2026-06-29 `all_source` manifest summary even after the board cards themselves were current.
- Root cause: The evaluation metadata helper treated `sport=all` as a single aggregate manifest request, which let the old all-source bundle keep winning the manifest summary path.
- Fix: Make the manifest summary helper use the per-sport manifest list when the sport is `all`, so the board metadata reflects current per-sport artifacts instead of the aggregate all-source bundle.
- Validation: Focused pytest coverage passed for the manifest-summary regression in `tests/test_intelligence_evaluation.py` and the earlier intelligence date-selection regressions in `tests/test_intelligence_state.py`.
- Follow-up: Keep the worker publishing current per-sport manifests so the board never needs to lean on aggregate all-source provenance again.

## 2026-07-04 - Intelligence board default date stopped falling back to 6/29 manifests
- Symptom: The /intelligence board still surfaced a stale 2026-06-29 artifact summary in the response metadata even though the worker-written board snapshot was current.
- Root cause: The default board date chooser only looked at snapshot files with explicit date fields, so it could skip the worker-written root snapshot and fall back to an older manifest-derived date.
- Fix: Teach the intelligence date chooser to inspect the worker-written root snapshot metadata and file mtime first, normalize timestamp-like values to ISO dates, and only then fall back to manifests.
- Validation: Focused pytest coverage passed for the daily snapshot selector regression and the worker-snapshot-over-manifest regression in `tests/test_intelligence_state.py`.
- Follow-up: Keep the worker publishing the root intelligence snapshot so the default board date continues to track the newest artifact instead of stale manifest provenance.

## 2026-07-03 - Intelligence status now prefers published report manifests over source-tree scans
- Symptom: The live /api/intelligence/status payload kept resolving an all-sports manifest rooted at `src/data/all_source`, so the betting board stayed anchored to stale 6/29 evidence instead of the worker-published 7/3 snapshot.
- Root cause: `load_artifact_manifests()` only scanned source-tree data roots and ignored the shared published manifests under `reports/manifests`, which are the web-side copy Render can actually read.
- Fix: Make the artifact-manifest loader prefer the published `reports/manifests/<sport>.json` file first, reconstruct the manifest from its `artifact_paths`, and fall back to source-tree scans only when the publish is missing.
- Validation: `python -m pytest tests/test_artifact_manifests.py -vv` and the relevant `tests/test_intelligence_state.py` date-selection/status tests both passed.
- Follow-up: Keep the published reports tree current on the worker side; source-tree scans should remain a fallback, not the primary Render status path.

## 2026-07-03 - Intelligence board default date was anchored to stale source manifests
- Symptom: The /intelligence board kept resolving the 2026-06-29 board snapshot even after the Render deploy was live and daily refreshes were running.
- Root cause: The default intelligence date chooser still preferred artifact-manifest dates, so it could keep selecting the stale `all_source` manifest path instead of the newest daily board snapshot written for the current day.
- Fix: Make the intelligence board prefer the newest daily `board_snapshot_*.json` / `intelligence_state_*.json` file before falling back to manifest-derived dates.
- Validation: Focused pytest coverage passed for the new daily-snapshot date preference regression in `tests/test_intelligence_state.py`.
- Follow-up: Keep the manifest fallback only as a last resort; the daily board snapshot should remain the canonical source for the default board date.

## 2026-07-04 - Intelligence artifacts now prefer daily worker-written files
- Symptom: The intelligence board still depended on large root snapshot files, which made the artifact set hard to manage and left the live reader tied to the legacy root path.
- Root cause: The state service, bootstrap sync, and daily-update publish list were still centered on `reports/intelligence/board_snapshot.json` and `reports/intelligence/intelligence_state.json` instead of the daily worker-written artifacts.
- Fix: Make the reader prefer daily intelligence files, publish daily `board_snapshot_*.json` / `intelligence_state_*.json` / `intelligence_state_history_*.jsonl` artifacts, and bootstrap the daily files on startup.
- Validation: Focused pytest coverage passed for `tests/test_intelligence_state.py` and `tests/test_bootstrap_data_root.py` after the contract change.
- Follow-up: Keep the remaining compatibility root files out of the publish path so the daily worker-written artifacts stay the canonical source.

## 2026-07-03 - Intelligence snapshots were not included in daily-update publish paths
- Symptom: The live Render betting board stayed on the old 6/29 snapshot even after the local intelligence refresh regenerated newer `reports/intelligence/*` artifacts.
- Root cause: `scripts/unified_daily_update.ps1` only built publish paths from sport-specific artifacts, so the repo-local intelligence snapshot and cache files the web dyno reads were not part of the publish set.
- Fix: Add the repo-local intelligence snapshot/cache files to `Get-IntelligencePublishArtifactPaths` so daily update now treats them as publishable artifacts alongside the sport outputs.
- Validation: The edited PowerShell controller passed a syntax parse check with `powershell -NoProfile -Command "[void][scriptblock]::Create((Get-Content 'scripts\unified_daily_update.ps1' -Raw)); 'parse=ok'"`.
- Follow-up: Run the publish path again and confirm `reports/intelligence/board_snapshot.json` and `reports/intelligence/query_state_cache.json` are staged and reach Render with the next deploy.

## 2026-07-03 - Betting board on Render was reading the mounted reports disk instead of the repo snapshot
- Symptom: The live /intelligence board stayed empty on Render even though the pushed repo snapshot in `reports/intelligence/board_snapshot.json` still contained top opportunities and a populated board contract.
- Root cause: `render.yaml` pointed the web service `SYNDICATE_REPORTS_ROOT` at `/opt/render/project/data/reports`, so the board read the mounted disk instead of the checked-in report snapshot that actually contained the latest board data.
- Fix: Move the Render web service `SYNDICATE_REPORTS_ROOT` back to `./reports` so the board reads the repo-local snapshot while the worker continues to own the mounted disk.
- Validation: `python -m pytest tests/test_render_yaml_envs.py -q` passed after updating the render contract test to require `./reports` in the web section.
- Follow-up: If Render starts publishing the reports tree onto the mounted disk reliably, re-evaluate whether the web service still needs the repo-local reports fallback.

## 2026-07-03 - Betting board no longer drifts into Ask
- Symptom: The /intelligence page still felt tied to the Ask surface, and board items could jump users into /syndicate instead of staying on the betting board.
- Root cause: The template still carried Ask-oriented copy and a dead drill-down helper that pointed to /syndicate.
- Fix: Removed the Ask drill-down wiring from the intelligence template and kept the board copy and interactions on the native intelligence surface.
- Validation: `python -m pytest tests/test_intelligence_state.py -k "intelligence_home_renders_initial_board_shell or default_intelligence_query_uses_latest_board_snapshot_fallback or board_snapshot_reader_skips_mismatched_dates"` passed.
- Follow-up: If a future drill-down is added, it should stay within the intelligence surface instead of opening Ask.

## 2026-07-03 - Intelligence betting board now falls back to the latest artifact snapshot
- Symptom: The /intelligence betting board could render with no opportunities even though the latest board snapshot artifact still contained live and pregame cards.
- Root cause: The default board request was date-scoped too strictly, so a current-day request could reject an older but still valid artifact-backed snapshot instead of surfacing it.
- Fix: Keep explicit date queries strict, but let the default "top edges today" board request fall back to the latest artifact-backed board snapshot when the date-scoped cache is empty.
- Validation: `python -m pytest tests/test_intelligence_state.py -k "default_intelligence_query_uses_latest_board_snapshot_fallback or board_snapshot_reader_skips_mismatched_dates or board_snapshot_promotes_board_contract_cards_into_visible_opportunities"` passed.
- Follow-up: If the worker stops producing fresh snapshots, this fallback keeps the board usable, but the refresh pipeline still needs to be monitored.

## 2026-07-03 - MLB live lens now refreshes on a 60-second freshness window
- Symptom: The MLB cards page could keep showing an odds timestamp around 5:05 PM even after the live-lens pipeline had produced newer data, which made interval-related cards look stale.
- Root cause: The live-lens refresh gate allowed a 180-second stale window by default, so the page could reuse an old report longer than the odds refresh cadence.
- Fix: Lower the MLB live-lens max-age default to 60 seconds in both the Syndicate wrapper and the vendor frontend, and pin the Render env var to 60 so deployed refreshes match the expected cadence.
- Validation: `python -m pytest tests/test_live_lens_local.py -k "refreshes_after_sixty_seconds or shared_live_lens_contract_normalizes_refresh_metadata"` passed.
- Follow-up: If the upstream odds worker slows down again, check the refresh worker first rather than widening the live-lens cache window.

## 2026-07-03 - WNBA scheduled games no longer flip to Final from stale time alone
- Symptom: The WNBA cards page could show upcoming games as Final and hide tipoff times even when the live-state row still looked like a 0-0 pregame row.
- Root cause: The shared WNBA status normalizer promoted stale past-start rows to Final purely from elapsed time, which was too aggressive for rows with no scoring or period evidence.
- Fix: Only infer Final from stale start times when the row also has real game evidence, such as non-zero scoring or a parsed in-progress period.
- Validation: `python -m pytest tests/test_wnba_cards_merge_aliases.py -k "scheduled"` passed, and the WNBA live-player hydration regression still passed.
- Follow-up: If another feed starts emitting different pregame placeholders, keep the guard evidence-based instead of time-only.

## 2026-07-03 - WNBA sim-detail export now rebuilds sparse artifacts
- Symptom: Daily update could keep reusing a processed `cards_sim_detail` file that existed but had empty quarter arrays, so interval and period lanes stayed empty after refresh.
- Root cause: The WNBA export path treated any existing processed `cards_sim_detail` file as good enough and never checked whether it actually contained quarter content.
- Fix: Make the exporter validate quarter content before accepting an existing file; if the artifact is sparse, rebuild it from smart-sim or source-app fallback and overwrite the bad file.
- Validation: `python -m pytest tests/test_wnba_refresh_runner.py -k "cards_sim_detail_export"` passed, including a new regression that rebuilds a sparse existing artifact.
- Follow-up: If future WNBA refreshes introduce another sparse-but-present artifact shape, add a content check before the copy short-circuit.

## 2026-07-03 - WNBA live-player lanes now match event-id aliases
- Symptom: WNBA player-prop lanes could stay empty or partially unhydrated even when the processed odds, live-lens, and live-state artifacts existed for the slate.
- Root cause: The WNBA live-player join path depended on exact event-id equality, but the source artifacts can surface the same game under raw, stripped-leading-zero, or canonicalized IDs.
- Fix: Add event-id alias matching in the WNBA game index, live-player odds index, and live-player row matcher so the same game hydrates across all supported ID variants.
- Validation: `python -m pytest tests/test_wnba_live_snapshots_local.py -k "hydrates_prices"` passed, including a new regression that hydrates across event-id aliases.
- Follow-up: If a future slate introduces a new event-id shape, add it to the alias helper instead of patching a single sport path.

## 2026-07-03 - WNBA artifact bundle now prefers the fuller mirror root
- Symptom: The WNBA page could render game cards but still show zeroed sim metrics and empty props/hydration lanes on Render even when the day’s processed artifacts existed locally.
- Root cause: The WNBA artifact bundle loader stopped at the first root with a cards CSV, so a partial mounted mirror could win over a richer repo bundle that also contained `cards_sim_detail`, `cards_props_snapshot`, and recommendations artifacts.
- Fix: Rank candidate roots by bundle completeness and select the root with the most complete cards/sim/props/recommendations set instead of blindly accepting the first CSV hit.
- Validation: Focused regression coverage in `tests/test_wnba_cards_merge_aliases.py` now proves the fuller root is selected, and `python -m unittest tests.test_wnba_cards_merge_aliases` passes.
- Follow-up: If Render still shows empty WNBA sim or props after redeploy, the remaining blocker is data parity on the mounted disk rather than the bundle-selection logic.

## 2026-07-03 - Render web startup no longer hard-fails on refresh-state readiness
- Symptom: The Render site was still returning 502 on both `/wnba` and `/healthz`, which meant the web dyno was failing before the lightweight health check could respond.
- Root cause: `syndicate.app.create_app()` still called `assert_refresh_state_backend_ready(process_name="web")` during app construction, so a hosted-storage or refresh-state mismatch could kill the web process at startup. The Render env file also carried conflicting live-refresh/bootstrap values, which made the deployment contract ambiguous.
- Fix: Remove the hard refresh-state assertion from web app startup and clean up `render.yaml` so the web service stays non-refreshing while the worker owns bootstrap-on-start and WNBA-today bootstrap behavior.
- Validation: Focused tests for app bootstrap, health routes, and Render env contract passed with `python -m unittest tests.test_app_bootstrap tests.test_home_health tests.test_render_yaml_envs`.
- Follow-up: Keep `/healthz` lightweight and treat any future Render 502 as a deployment/runtime issue before reintroducing startup-time state checks.

## 2026-07-03 - WNBA-only daily update dispatch needed hashtable splatting
- Symptom: Manual GitHub Actions runs for WNBA-only daily updates kept failing before the daily pipeline step with `Cannot process argument transformation on parameter 'EventSimForceWindowMinutes'` and `-OddsSports` / `-RefreshOdds` being misread as typed values.
- Root cause: The workflow and wrapper scripts were splatting plain arrays into PowerShell scripts, which is positional binding rather than named parameter binding. That let later flags slide into the `EventSimForceWindowMinutes` slot when WNBA-only dispatch arguments were forwarded.
- Fix: Add a manual `active_sports` workflow_dispatch input, switch the workflow and both wrapper scripts to ordered hashtable splatting, and keep sport-specific manual runs routed through the direct daily-update path when needed.
- Validation: A local `powershell.exe -File .\scripts\daily_update.ps1 -Date 2026-07-03 -RefreshOdds -OddsPhase all -OddsSports all -OddsRegions us -SkipGitPush -EventSimForceWindowMinutes 30 -ActiveSports WNBA -WhatIf` run now reaches the WNBA vendored refresh, WNBA source mirror, Syndicate refresh-and-gate, and prediction reconciliation steps without the binder error.
- Follow-up: Confirm the current GitHub Actions run reaches the same WNBA pipeline stages and then verify the WNBA artifact publish path materializes the expected `recommendations_slate` output.

## 2026-07-03 - Daily update source refresh was chained to sim execution
- Symptom: Render could boot with no current WNBA artifact data even though the daily update pipeline was available.
- Root cause: `scripts/unified_daily_update.ps1` only entered `source_update` when `simExecution` was planned, so a sim no-op could suppress the WNBA refresh and mirror steps entirely.
- Fix: Drive `source_update` from the explicit `sourceUpdates` run-plan decision instead of the sim decision, while still honoring `SkipSourceUpdates` and the replay checkpoint.
- Validation: Pending a focused PowerShell parse check and a follow-up daily-update run.
- Follow-up: Confirm WNBA artifacts still materialize when sim execution is skipped but source refresh is requested.

## 2026-07-03 - WNBA live snapshots now materialize current-day artifacts
- Symptom: Render logged missing WNBA `live_snapshots` files for current-day `live_lines` and `live_player_boxscore` reads instead of keeping the board fully artifact-backed.
- Root cause: The WNBA live snapshot readers only looked for already-existing JSONL files, while the builders returned synthesized payloads without writing them back to the canonical processed snapshot path.
- Fix: Persist current-day WNBA live payloads into `data/wnba_source/source_artifacts/data/processed/live_snapshots/` after synthesis and switch the local snapshot lookup to a quiet path read so missing files do not spam strict-path errors before the artifact is written.
- Validation: Focused pytest regressions for current-day live-lines and live-player-boxscore artifact materialization passed.
- Follow-up: Keep the WNBA live-snapshot writer aligned with the refresh runner so today’s files continue to exist in the Render artifact root before the UI reads them.

## 2026-07-03 - MLB HR targets stopped backfilling from the daily summary
- Symptom: `/mlb/hr-targets` could silently fill sparse HR-target artifacts from the daily summary, so the page could look healthy even when the dedicated HR-target artifact was incomplete.
- Root cause: The HR-targets context builder merged dedicated HR-target rows with daily-summary rows when the dedicated artifact was sparse.
- Fix: Make the HR-targets page artifact-only and show the empty state when the dedicated HR-target artifact has no rows.
- Validation: `syndicate/features/mlb/hr_targets.py` syntax check passed after removing the daily-summary merge path.
- Follow-up: Keep the dedicated HR-target artifact complete upstream so the page never needs a fallback source.

## 2026-07-03 - Intelligence page stopped self-triggering refresh on load
- Symptom: `/intelligence` and the intelligence status/read paths could still request refresh work even when a cached board artifact was already present.
- Root cause: The page payload and client bootstrap were forcing refresh on first render, and the status route also auto-promoted stale board reads into refresh work.
- Fix: Make the intelligence page cache-first, keep refresh explicit only, and preserve status refresh as an opt-in request instead of an automatic backfill.
- Validation: Blueprint and template syntax checks passed after removing the load-time refresh trigger and preserving explicit refresh on the status endpoint.
- Follow-up: Keep intelligence rendering artifact-backed by default; any new refresh trigger should be tied to explicit user action or a separate worker/cron path.

## 2026-07-03 - MLB cards 502ed on Render web dynos
- Symptom: `/mlb` and `/mlb/api/cards` returned 502 on the Render web service even though health checks and some artifact-backed endpoints were still responding.
- Root cause: The MLB cards builder still tried to build the shared simulation contract on the web dyno, which pulled hosted-storage reads that require `SYNDICATE_DATA_ROOT` and failed when Render only had the web runtime.
- Fix: Skip the hosted-storage simulation enrichment on the Render web path and keep the MLB page/API on the artifact-backed payload branch.
- Validation: Simulated Render imports and Flask test-client requests returned `/mlb` 200 and `/mlb/api/cards?date=2026-07-03` 200 under the same hosted-storage env shape.
- Follow-up: Keep the web dyno read-only and only reintroduce shared simulation enrichment where the required hosted data root is actually mounted.

## 2026-07-03 - Intelligence evaluation ledger moved to dated chunks
- Symptom: The evaluation ledger was growing into a multi-gigabyte monolith and was no longer a good fit for default reads and writes.
- Root cause: The default evaluation contract still treated `reports/intelligence/evaluation_ledger.jsonl` as a single append-only file, so long-lived history kept accumulating in one place.
- Fix: Split the default evaluation ledger into dated JSONL chunk files under `reports/intelligence/evaluation_ledger_chunks/`, with an index and manifest for compatibility, and route default readers/writers through the chunk-aware helpers.
- Validation: `python -m unittest tests.test_intelligence_evaluation -q` and `python -m unittest tests.test_recommendation_engine -q` passed.
- Follow-up: The legacy monolithic ledger has been moved to `reports/intelligence/archive/evaluation_ledger.jsonl` and kept out of the active read path.

## 2026-07-03 - Render bootstrapping intelligence pulled a 3.2 GB ledger into startup
- Symptom: Render instances repeatedly failed during deploy/startup with out-of-memory errors after intelligence updates.
- Root cause: `scripts/bootstrap_data_root.py` was syncing the entire `reports/intelligence` tree on startup, including the 3.2 GB `evaluation_ledger.jsonl` file that the web dyno does not need at boot.
- Fix: Replace the broad directory bootstrap with a small file allowlist for the intelligence state/cache artifacts the app actually reads at runtime.
- Validation: `python -m unittest tests.test_bootstrap_data_root -q` passed.
- Follow-up: Keep large evaluation ledgers out of the web bootstrap path unless a route explicitly requires them.

## 2026-07-02 - Daily update publish failed on staged MLB artifact paths
- Symptom: The in-season daily update aborted while publishing MLB artifacts with `git add failed` on `data/mlb_source/data/eval/seasons/2026/season_betting_cards_retuned_manifest.json`.
- Root cause: The incremental publish loop was branching on `git check-ignore` before staging each path, which made the artifact publish path too dependent on ignore-state handling for owned MLB outputs.
- Fix: Normalize each publish path and force-add it directly in `scripts/unified_daily_update.ps1` instead of switching between ignored and non-ignored staging branches.
- Validation: `powershell -NoProfile -Command "$text = Get-Content 'scripts\\unified_daily_update.ps1' -Raw; [void][scriptblock]::Create($text); Write-Host 'parse=ok'"` passed.
- Follow-up: Re-run the daily update once the fix is deployed and confirm the MLB artifact publish stage completes without a git staging error.

## 2026-07-02 - Worker-updated intelligence boards could read as empty
- Symptom: `/intelligence` and `/api/intelligence/query` could still show no opportunities even after the odds refresh worker had populated the board artifact.
- Root cause: The intelligence state readers only treated `top_opportunities` and `analysis.recommendations` as visible content, so a worker snapshot that only carried board-contract cards did not get promoted into the canonical opportunity lists.
- Fix: Promote board-contract cards into `top_opportunities`, `recommendations`, `by_sport`, and the live lane during state normalization and snapshot reads, and accept board-contract cards when validating persisted intelligence state.
- Validation: `python -m pytest tests/test_intelligence_state.py -k 'board_snapshot_promotes_board_contract_cards_into_visible_opportunities or status_endpoint_preserves_board_trace_metadata or query_endpoint_returns_empty_board_when_cached_live_snapshot_is_missing_hydration'` passed.
- Follow-up: Keep any future worker board shape changes mirrored in the state reader so the live/pregame lanes do not drift back to a top-level-only contract.

## 2026-07-02 - Incremental daily-update publishes failed on ignored MLB artifact paths
- Symptom: The daily update kept aborting during artifact publish with `git add failed` on `data/mlb_source/data/eval/seasons/2026/season_betting_cards_retuned_manifest.json` after the run had already produced the MLB bundle.
- Root cause: The incremental publisher was sending newly generated artifact paths through the normal `git add` loop, but some owned MLB artifacts live under ignored trees and need to be force-added when they appear in the update set.
- Fix: Teach `scripts/unified_daily_update.ps1` to run `git check-ignore` for each incremental path and switch ignored paths to `git add -f` while keeping the explicit force-include lane intact.
- Validation: Added a regression in `tests/test_unified_daily_update_incremental_artifact_generation.py` to cover the ignored-path force-add contract.
- Follow-up: Keep documenting any repeated artifact-publish failures here so the next edit does not rediscover the same ignored-path staging rule.

## 2026-07-02 - MLB live-lens kept serving stale current-day reports
- Symptom: The MLB live-lens page and API could keep showing an older non-empty report for today instead of refreshing live projections and interval recommendations.
- Root cause: The Syndicate live-lens wrapper only refreshed empty current-day snapshots, so a stale but populated report could keep winning the read path.
- Fix: Add a current-day report freshness check based on report age, and rebuild stale reports through the persisted live-lens path before serving page or API context.
- Validation: `py -3 -m pytest tests/test_mlb_refresh_runner.py -k refreshes_stale_current_day_report -q` passed.
- Follow-up: Keep the wrapper aligned with the vendor report-age contract if the live-lens refresh interval or max-age setting changes.

## 2026-07-02 - WNBA artifacts were skipped when git push was disabled
- Symptom: The 2026-07-02 daily update completed, but the WNBA date-stamped artifact bundle never appeared where Render expects it.
- Root cause: `scripts/unified_daily_update.ps1` tied `artifactGeneration` to `SkipGitPush`, so no-push runs could mark the artifact stage skipped instead of materializing and publishing the WNBA bundle.
- Fix: Decouple artifact-generation planning from `SkipGitPush` and keep the WNBA date-specific artifact presence check in the step wrapper.
- Validation: `scripts/unified_daily_update.ps1` now parses successfully after the change.
- Follow-up: Re-run the daily update path and confirm the 2026-07-02 WNBA bundle lands in both processed roots.

## 2026-07-02 - Shared cards refresh contract was fragmented across sports
- Symptom: MLB, NBA, and WNBA cards each had their own polling behavior, so browser hydration did not follow one consistent contract across sports.
- Root cause: The refresh policy lived in per-sport scripts and templates, and the shared polling helper only accepted ad hoc timers instead of a policy object.
- Fix: Promote a shared `refresh_policy` payload from the cards builders, expose it through the browser bootstraps, and start polling through the shared policy-aware helper.
- Validation: The touched Python, JavaScript, and template files passed focused error checks, and the commit was pushed as `547d0a13`.
- Follow-up: Extend the same policy shape to any remaining live-lens or rank-board surfaces that should share the same browser hydration contract.

## 2026-07-02 - MLB odds timestamps rendered in browser-local time
- Symptom: MLB cards could show odds freshness in whatever timezone the browser defaulted to, which made the timestamp ambiguous.
- Root cause: The MLB timestamp formatter used `Intl.DateTimeFormat(undefined, ...)`, so it inherited the viewer's local timezone instead of Central Time.
- Fix: Force the MLB timestamp formatters in the template and client bundle to use `America/Chicago`.
- Validation: The patch diff-checks cleanly; once deployed, the MLB cards timestamp should render in Central Time consistently.
- Follow-up: Confirm the live cards page still shows the newest odds snapshot after deploy and that the displayed clock matches Central Time.

## 2026-07-02 - Stale running refresh manifests blocked new odds launches
- Symptom: Render kept reporting a failed odds refresh state with an old 2026-06-24 manifest, a dead PID, and no fresh odds updates.
- Root cause: The refresh guards treated any `running` manifest as active even when the recorded PID was gone and no result payload existed, so the stale contract could block new launches indefinitely.
- Fix: Auto-heal dead `running` refresh manifests to `failed` before launch checks run, and let the queued-refresh runner reclaim stale running external contracts with dead PIDs.
- Validation: Focused regressions passed, and a live Render MLB refresh launched cleanly, completed successfully, and returned the ops page to `finished` on run `20260702_174014`.
- Follow-up: Keep the deploy parity check open until the pushed fix is visible in the version endpoint, then confirm the next refresh tick preserves the healed state.

## 2026-07-02 - Render defaults finally aligned with in-place odds refresh
- Symptom: The MLB odds badge and ops refresh path kept circling back to `manifest_only` even after the live code changes were deployed.
- Root cause: Render config still seeded `SYNDICATE_REFRESH_LAUNCH_MODE=manifest_only` and `SYNDICATE_LIVE_ODDS_REFRESH_LAUNCH_MODE=manifest_only` in multiple service blocks, so the default production contract remained queued-only.
- Fix: Change all Render-side launch-mode defaults to `detached_subprocess` so refresh jobs launch in place unless a test or manual request explicitly asks for queued external-runner behavior.
- Validation: The live-loop and ops refresh regressions already pass for detached-subprocess defaults; this config change makes the production deploy match those tests.
- Follow-up: Redeploy and verify that no production service keeps writing `manifest_only` into the latest refresh manifest unless it is an explicit test path.

## 2026-07-02 - Ops refresh still defaulted Render to manifest-only
- Symptom: The MLB odds refresh stayed pinned because the ops refresh launcher still treated Render as a queued-only external-runner path.
- Root cause: `ops_refresh._resolve_launch_mode()` and the ops launch handlers still forced `manifest_only` on Render, so refresh jobs were recorded but not executed in place.
- Fix: Remove the Render-specific `manifest_only` fallback and stop hardcoding `manifest_only` in the ops launch endpoints so Render uses `detached_subprocess` by default.
- Validation: Updated the ops refresh regression to expect `detached_subprocess` on Render and `web_process` ownership for the default launch.
- Follow-up: Redeploy and verify the ops refresh route and the live loop both launch refresh work instead of queueing it indefinitely.

## 2026-07-02 - MLB live refresh loop defaulted to the non-refreshing Render path
- Symptom: The redeployed MLB page was still pinned to the 7:18 AM odds timestamp even after the web revision was live.
- Root cause: The live refresh loop still fell back to `manifest_only` on Render when the explicit launch-mode env var was missing, which queued refresh manifests instead of launching the odds job in-place.
- Fix: Remove the Render-specific `manifest_only` fallback so the live loop defaults to `detached_subprocess` and can actually execute the refresh job on the web dyno.
- Validation: Updated the live-refresh regression to expect `detached_subprocess` on Render by default.
- Follow-up: Redeploy and confirm the MLB odds badge advances past 7:18 AM instead of staying fixed on the last captured snapshot.

## 2026-07-02 - MLB freshness needed to live on the web service disk
- Symptom: The 7/2 MLB UI stayed on the 7:18 AM odds state even after the 60-second freshness window had passed.
- Root cause: The web service and refresh-worker service do not share a disk on Render, so the worker could refresh artifacts on its own mount without changing the files the UI actually reads. The web process also skipped the live refresh loop entirely.
- Fix: Enable the MLB live refresh loop on the web service and let the web process own the 60-second refresh cadence so the refreshed artifacts land on the same disk the UI serves.
- Validation: `syndicate/app.py` now starts the live refresh loop without the Render-web early return, `render.yaml` enables `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` for the web service, and the app file passed error checking.
- Follow-up: Redeploy Render and verify that a fresh `/mlb/cards?date=2026-07-02` request advances the odds timestamp beyond 7:18 AM and that the page badge matches the API payload.

## 2026-07-02 - MLB odds were stale at 10:42 AM on Render
- Symptom: The 7/2 MLB page was still showing the 7:18 AM odds timestamp at 10:42 AM, so pregame and live odds were not advancing on the deployed UI.
- Root cause: The live 60-second refresh loop is intentionally skipped on the Render web dyno in `app.py`, so the browser-facing service is serving the last persisted snapshot rather than running the refresh cadence itself.
- Fix: None yet; the current behavior confirms the deployed UI depends on the external refresh job / worker artifacts instead of the web process self-refreshing.
- Validation: The deployed `/mlb/api/cards?date=2026-07-02` payload still reported `marketAvailability.gameLines.retrievedAt=2026-07-02T07:18:51.166874`, `pitcherProps.retrievedAt=2026-07-02T07:18:52.272778`, and `hitterProps.retrievedAt=2026-07-02T07:18:53.509467`, and the rendered page still showed `Odds updated 7/2, 7:18 AM`.
- Follow-up: Move or mirror the refresh ownership to the worker path that is expected to run every 60 seconds, or explicitly enable the live loop on the service that should own freshness.

## 2026-07-02 - MLB 7/2 freshness trace matched the rendered UI
- Symptom: There was concern that the 7/2 MLB odds state might still be stale on Render even though the daily update GitHub Action had already run.
- Root cause: The apparent mismatch was a timestamp interpretation issue, not a broken read path; the deployed MLB payload was serving a later 7/2 snapshot, while the raw times were being compared against the worker run clock.
- Fix: Treat the MLB cards API as the source of truth for the lane stamps and verify each lane independently against the rendered page: game lines, pitcher props, and hitter props.
- Validation: The deployed `/mlb/api/cards?date=2026-07-02` payload reported `marketAvailability.gameLines.retrievedAt=2026-07-02T07:18:51.166874`, `pitcherProps.retrievedAt=2026-07-02T07:18:52.272778`, and `hitterProps.retrievedAt=2026-07-02T07:18:53.509467`; the rendered `/mlb/cards?date=2026-07-02` page showed `Odds updated 7/2, 7:18 AM` and the same 9-game slate.
- Follow-up: Keep the UI badge and the lane summaries tied to the same snapshot contract, and treat any future offset confusion as a timezone-labeling issue until the write/read chain is proven broken.

## 2026-07-02 - MLB is the contract model for the shared live-lens shape
- Symptom: The cross-sport live-lens and odds surfaces were being compared for contract consistency, but the reference model was not explicit.
- Root cause: Each sport uses its own artifact source shape, so the shared contract had drifted into sport-specific implementations rather than one clearly documented canonical pattern.
- Fix: Treat MLB as the canonical contract model for persisted snapshot backing, freshness timestamps, stable empty-state behavior, and card-to-lens consistency; keep WNBA and NBA aligned to that pattern before considering broader refactors.
- Validation: Live MLB cards rendered with the expected slate summary, odds timestamp, and playable rows, and the WNBA/NBA surfaces were confirmed to be the closest match to the same artifact-backed model.
- Follow-up: Do not standardize the shared contract until MLB remains healthy through the same validation path and the remaining sports are mapped against the canonical fields.

## 2026-07-02 - WNBA source cards dropped worker-built odds
- Symptom: The WNBA `/api/source/cards` payload showed games, but the betting fields were blank and the card surface rendered `-` for moneyline, spread, and total.
- Root cause: The source-card builder was only hydrating matchup rows from artifacts; it was not merging the worker-built live-lines artifact back into the game rows before returning the endpoint.
- Fix: Merge the WNBA live-lines artifact into each matching source-card game by event id, then recompute the betting block so the endpoint carries the worker-built odds values through to the UI.
- Validation: `python -m pytest tests/test_wnba_cards_merge_aliases.py -q` passed with coverage for artifact-backed game rows and live-lines odds hydration.
- Follow-up: Keep WNBA source-card hydration aligned with the worker-built live-lines artifact contract if that payload shape changes.

## 2026-07-02 - WNBA slate fell back to the prior board instead of today's games
- Symptom: The WNBA cards route showed the last stored slate or a stale "no slate" state for 2026-07-02 even though the current day had games available.
- Root cause: WNBA source selection was still letting the ESPN schedule probe and stored-slate fallback decide the active board before the public-scoreboard path could hydrate today's slate, and artifact loading could be short-circuited by the same live gate.
- Fix: Stop using the live schedule probe as a hard artifact gate, keep today's WNBA source date on today so the public-scoreboard fallback can run, and preserve the stored-slate fallback only when no live or artifact slate is available.
- Validation: `python -m pytest tests/test_wnba_cards_merge_aliases.py -q` passed with regressions covering artifact-first loading and today's public-scoreboard hydration.
- Follow-up: Keep WNBA cards artifact-first, with live scoreboard data as a fallback for today's slate rather than a blocker.

## 2026-07-02 - MLB cards stayed on a stale odds badge
- Symptom: The MLB game cards page kept showing `Odds updated 7/1, 7:42 AM` even after the odds-history refresh artifact had advanced.
- Root cause: The cards payload promoted the live-lens refresh timestamp only, so the visible badge ignored the shared odds-history artifact timestamp that the worker was updating every 60 seconds.
- Fix: Prefer the shared odds-history payload's `updated_at` timestamp for today's MLB cards when it is newer than the live-lens refresh time.
- Validation: A focused regression now proves today's MLB cards expose the shared odds-history refresh timestamp in `marketAvailability.gameLines.oddsRefreshedAt`.
- Follow-up: Keep the MLB cards badge tied to the refresh artifact timestamp whenever the live-lens and odds-history clocks diverge.

## 2026-07-02 - Odds histories stalled on same-price refreshes
- Symptom: The long-lived odds artifact could stay stuck on the first capture even when the scheduled refresh worker kept running.
- Root cause: The odds-history sync only keyed refresh dedupe on market, line, and odds, so a fresh source snapshot with the same price could be collapsed instead of recorded as a new refresh.
- Fix: Persist source snapshot timestamps onto odds-history rows and treat a newer snapshot as a distinct refresh entry, even when the line and odds are unchanged.
- Validation: A direct Python smoke check showed a second refresh appending a new history row with the same line and odds but a newer `snapshot_ts`.
- Follow-up: Keep source snapshot timestamps flowing through any future odds refresh readers so hosted freshness labels stay aligned with the worker cadence.

## 2026-07-01 - MLB odds history skipped odds-only refreshes
- Symptom: The MLB cards surface kept showing the same odds update time even though the daily update and live refresh paths were still running.
- Root cause: The odds-history sync only treated line changes as refreshes, so a market price move with the same line was ignored and the long-lived odds artifact never advanced.
- Fix: Update the odds-history sync to treat a line-or-odds change as a new refresh entry, so the shared odds artifact advances whenever the scheduled updater captures a new price.
- Validation: A focused regression now proves a same-line odds change appends a second history entry, and the live MLB cards API returns 200 with tracked game line metadata present.
- Follow-up: Keep the odds-history sync and MLB card freshness labels aligned whenever the refresh contract changes.

## 2026-07-01 - MLB odds cadence was still configured for 30 seconds
- Symptom: The live MLB page showed odds timestamps stuck at the morning refresh time instead of moving on the expected one-minute cadence.
- Root cause: Render and MLB refresh defaults still used 30-second odds/report intervals in several service blocks and worker fallbacks, so the deployed contract did not match the 60-second expectation.
- Fix: Update the Render env vars and MLB worker/frontend defaults to 60 seconds for odds and report refresh where those values govern the odds surface.
- Validation: Focused diagnostics showed no syntax errors in the touched files after the cadence update.
- Follow-up: Verify the deployed Render service picks up the new 60-second env vars and that `/mlb` timestamps advance on the next refresh cycle.

## 2026-07-01 - Odds control plane stayed on the older precedence contract
- Symptom: The MLB odds refresh path appeared to update artifacts, but `/mlb` still behaved as if only the older daily-update artifact chain mattered.
- Root cause: The refresh metadata still advertised `artifact_history -> tracking_history`, which diverged from the shared-history-first odds control plane that `/mlb` and the intelligence pipeline are supposed to consume.
- Fix: Update the refresh metadata and pipeline regression to use `shared_history -> artifact_history -> tracking_history`, matching the control-plane contract already used by the odds-history reader.
- Validation: A focused Python smoke check confirmed `build_odds_control_plane_snapshot()` emits the shared-history-first precedence.
- Follow-up: Keep the control-plane precedence string synchronized across refresh, pipeline, and tests whenever the odds source contract changes.

## 2026-07-01 - Render health checks and stale deploy parity
- Symptom: Render kept restarting or timing out on `/healthz`, and live pages appeared stale even after pushes.
- Root cause: `/healthz` was doing deploy metadata work that was too expensive for Render's 5-second probe window, and `/versionz` was the correct place for detailed parity checks.
- Fix: Keep `/healthz` as a constant lightweight OK response and reserve `/versionz` for detailed commit/branch/runtime metadata.
- Validation: Focused health route tests passed and a local smoke test returned `/healthz` in milliseconds.
- Follow-up: Use this note pattern for future fixes so we record the symptom, the actual root cause, and the verification path in one place.

## 2026-07-01 - MLB cards stayed on stale odds history
- Symptom: The MLB cards page kept showing odds updated at 7:42 AM even after restarts and refreshes.
- Root cause: `source_cards_api_payload()` only hydrated tracked game lines from the service-local daily snapshot, so the live surface could miss the fresher shared odds-history payload.
- Fix: Prefer the shared MLB odds-history control-plane payload for today's cards and keep the snapshot as fallback; add a regression that proves the shared payload wins.
- Validation: `py -3 -m pytest tests/test_archives.py::DateArchiveHelperTests::test_mlb_cards_api_payload_prefers_shared_odds_history_for_today -q` passed, and the existing snapshot hydration test still passed.
- Follow-up: Watch the live `/versionz` and `/mlb` surfaces after deploy to confirm Render is serving the new commit and the fresher odds timestamps.