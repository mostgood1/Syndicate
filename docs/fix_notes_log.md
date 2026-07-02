# Fix Notes Log

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