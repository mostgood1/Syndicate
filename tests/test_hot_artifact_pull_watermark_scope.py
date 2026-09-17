"""The hot-artifact pull watermark is per (service, date), never one shared key.

MEASURED 2026-09-15 (lane soccer-live-scoreboard-range-stale). The watermark was
`reports_root()/refresh_status/latest/hot_artifact_pull_watermark.json`, written
through `write_json_file` -- keyvalue-backed, and both workers point at the same
store with the same `SYNDICATE_REPORTS_ROOT`. So it was ONE key:

- live-odds-worker pulls today's artifacts every ~2-3 min; refresh-worker pulls
  each board date every ~15-30 min, alternating today and tomorrow.
- refresh-worker's 20:41:05Z pull asked `since=20:39:04Z` -- the start of
  live-odds-worker's own pull -- so it could only receive files changed in the
  last two minutes, and never re-fetched an older change it already held.
- The Layer 2 soccer chips, built on refresh-worker, served a pre-deploy
  live_state for every publish 20:38-20:55Z while web held the fresh file.

`disk_maintenance._status_path` fixed the same shared-key shape on 2026-08-12.
These tests pin the scope: another service's pull, or the same service's pull
for another date, must not move this pull's floor.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import artifact_publisher


class _Store:
    """In-memory stand-in for the keyvalue-backed read/write pair."""

    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def read(self, path: Path):
        return self.data.get(str(path))

    def write(self, path: Path, payload: dict) -> None:
        self.data[str(path)] = dict(payload)


class HotArtifactPullWatermarkScopeTests(unittest.TestCase):
    NOW = 1789504865.0  # 2026-09-15T20:41:05Z, refresh-worker's measured pull
    OTHER_START = NOW - 121.0  # 20:39:04Z, live-odds-worker's pull start

    def setUp(self) -> None:
        self.store = _Store()
        self._patches = [
            patch("syndicate.features.shared.refresh_state_store.read_json_file", side_effect=self.store.read),
            patch("syndicate.features.shared.refresh_state_store.write_json_file", side_effect=self.store.write),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()

    def _as_service(self, name: str):
        return patch.dict("os.environ", {"RENDER_SERVICE_NAME": name, "SYNDICATE_REFRESH_LANE": ""}, clear=False)

    def _record(self, epoch: float, date_str: str | None) -> None:
        artifact_publisher._record_hot_artifact_pull_watermark(epoch, date_str=date_str)

    def _since(self, date_str: str | None) -> float | None:
        return artifact_publisher._hot_artifact_pull_since_epoch(pull_started_epoch=self.NOW, date_str=date_str)

    def test_another_services_pull_does_not_move_this_services_floor(self) -> None:
        with self._as_service("refresh-worker"):
            self._record(self.NOW - 1500.0, "2026-09-15")
        with self._as_service("live-odds-worker"):
            self._record(self.OTHER_START, "2026-09-15")
        with self._as_service("refresh-worker"):
            # The production value was OTHER_START. It must be refresh-worker's own.
            self.assertEqual(self._since("2026-09-15"), self.NOW - 1500.0)

    def test_another_dates_pull_does_not_move_this_dates_floor(self) -> None:
        with self._as_service("refresh-worker"):
            self._record(self.NOW - 1500.0, "2026-09-15")
            self._record(self.NOW - 60.0, "2026-09-16")
            self.assertEqual(self._since("2026-09-15"), self.NOW - 1500.0)
            self.assertEqual(self._since("2026-09-16"), self.NOW - 60.0)

    def test_first_pull_for_a_scope_is_the_bounded_window(self) -> None:
        with self._as_service("live-odds-worker"):
            self._record(self.OTHER_START, "2026-09-15")
        with self._as_service("refresh-worker"):
            # A DATED scope's first pull reaches back 24 h (lane `pull-window-dated-scope`):
            # other services' floors still never leak in; the bound is now the dated cap.
            self.assertEqual(
                self.NOW - self._since("2026-09-15"),
                getattr(artifact_publisher, "_MAX_DATED_PULL_WINDOW_SECONDS", None),
            )

    def test_scopes_are_distinct_paths_and_not_the_legacy_shared_key(self) -> None:
        with self._as_service("refresh-worker"):
            today = artifact_publisher._hot_artifact_pull_watermark_path("2026-09-15")
            tomorrow = artifact_publisher._hot_artifact_pull_watermark_path("2026-09-16")
            unscoped = artifact_publisher._hot_artifact_pull_watermark_path(None)
        with self._as_service("live-odds-worker"):
            other = artifact_publisher._hot_artifact_pull_watermark_path("2026-09-15")
        paths = {str(today), str(tomorrow), str(unscoped), str(other)}
        self.assertEqual(len(paths), 4)
        self.assertFalse(any(p.endswith("latest/hot_artifact_pull_watermark.json") for p in paths))
        self.assertIn("refresh-worker", str(today))
        self.assertIn("2026-09-15", str(today))

    def test_pull_reads_and_records_under_its_own_service_and_date(self) -> None:
        """Reachability: `pull_hot_artifacts` itself must use the scoped key."""
        seen_since: list[float | None] = []

        def _fake_export_url(pattern=None, since_epoch=None, exact_path=None):
            # Only the DATED pattern requests carry the watermark. The exact-path
            # fetches that follow (repair pass, live-lens snapshots) pass no
            # `since` by design and are not what this test is about.
            if pattern:
                seen_since.append(since_epoch)
            return f"http://web/export?pattern={pattern}&since={since_epoch}"

        with self._as_service("live-odds-worker"):
            self._record(self.OTHER_START, "2026-09-15")
        with self._as_service("refresh-worker"):
            self._record(self.NOW - 1500.0, "2026-09-15")
            with patch.object(artifact_publisher, "_admin_token", return_value="t"), patch.dict(
                "os.environ", {"SYNDICATE_WEB_PUBLISH_URL": "http://web/api/ops/artifacts/publish"}
            ), patch.object(artifact_publisher, "_export_url", side_effect=_fake_export_url), patch.object(
                # The dated pull calls the OUTCOME function (it needs `truncated`
                # and `next_since`); the tuple wrapper is kept for exact-path
                # callers. A complete, untruncated response records the pull's
                # start time exactly as before -- which is what this asserts.
                artifact_publisher, "_pull_hot_artifacts_request_outcome",
                return_value=artifact_publisher._PullOutcome(True, 0, False, None),
            ), patch.object(
                artifact_publisher, "_pull_hot_artifacts_request", return_value=(True, 0)
            ), patch.object(
                artifact_publisher, "_missing_required_artifact_relative_paths", return_value=[]
            ), patch.object(artifact_publisher.time, "time", return_value=self.NOW):
                artifact_publisher.pull_hot_artifacts(date_str="2026-09-15")
            self.assertTrue(seen_since)
            self.assertEqual(set(seen_since), {self.NOW - 1500.0})
            # Recorded under refresh-worker/2026-09-15; live-odds-worker's scope untouched.
            self.assertEqual(self._since("2026-09-15"), self.NOW)
        with self._as_service("live-odds-worker"):
            self.assertEqual(self._since("2026-09-15"), self.OTHER_START)


if __name__ == "__main__":
    unittest.main()
