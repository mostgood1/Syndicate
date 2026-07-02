# Fix Notes Log

## 2026-07-02 - Stale running refresh manifests blocked new odds launches
- Symptom: Render kept reporting a failed odds refresh state with an old 2026-06-24 manifest, a dead PID, and no fresh odds updates.
- Root cause: The refresh guards treated any `running` manifest as active even when the recorded PID was gone and no result payload existed, so the stale contract could block new launches indefinitely.
- Fix: Auto-heal dead `running` refresh manifests to `failed` before launch checks run, and let the queued-refresh runner reclaim stale running external contracts with dead PIDs.
- Validation: Focused regressions now pass for stale-running recovery in both `ops_refresh` and `run_queued_refresh_job` paths.
- Follow-up: Redeploy and confirm the Render status endpoint advances past the old 2026-06-24 contract on the next refresh tick.

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