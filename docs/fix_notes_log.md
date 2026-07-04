# Fix Notes Log

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