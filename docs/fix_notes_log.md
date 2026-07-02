# Fix Notes Log

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