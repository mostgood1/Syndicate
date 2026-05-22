from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import ops_refresh
from syndicate.features.shared import refresh_state_store


class _FakeKeyValueClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> bool:
        self.store[key] = str(value)
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0


class RefreshStateStoreTests(unittest.TestCase):
    def tearDown(self) -> None:
        refresh_state_store.reset_state_store_caches()

    def test_keyvalue_backend_round_trips_json_and_text_by_path(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            manifest_path = Path(tmp_dir) / "reports" / "refresh_status" / "latest" / "refresh_status_latest.json"
            stderr_path = Path(tmp_dir) / "reports" / "migration_runs" / "x" / "odds_refresh.stderr.txt"

            refresh_state_store.write_json_file(manifest_path, {"state": "pending_external", "date": "2026-05-22"})
            refresh_state_store.write_text_file(stderr_path, "worker stderr")

            self.assertEqual(refresh_state_store.read_json_file(manifest_path), {"state": "pending_external", "date": "2026-05-22"})
            self.assertEqual(refresh_state_store.read_text_file(stderr_path), "worker stderr")
            self.assertTrue(refresh_state_store.path_exists(manifest_path))
            self.assertGreater(refresh_state_store.path_size(stderr_path), 0)

    def test_keyvalue_backend_tracks_refresh_history_paths(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
            manifest_path = Path(tmp_dir) / "reports" / "refresh_status" / "2026-05-22" / "20260522_120000" / "refresh_status_manifest.json"
            refresh_state_store.write_json_file(manifest_path, {"date": "2026-05-22", "runStamp": "20260522_120000"})

            history_paths = refresh_state_store.list_refresh_status_manifest_paths(limit=6)

            self.assertEqual(history_paths, [manifest_path.resolve()])

    def test_ops_status_reads_latest_manifest_and_artifacts_from_keyvalue_backend(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir:
            reports_root = Path(tmp_dir) / "reports"
            latest_manifest_path = reports_root / "refresh_status" / "latest" / "refresh_status_latest.json"
            artifacts_dir = reports_root / "migration_runs" / "2026-05-22" / "odds_refresh_20260522_120000"
            historical_manifest_path = reports_root / "refresh_status" / "2026-05-21" / "20260521_120000" / "refresh_status_manifest.json"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                    "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                    "SYNDICATE_REPORTS_ROOT": str(reports_root),
                    "ADMIN_TOKEN": "secret-token",
                },
                clear=False,
            ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client):
                refresh_state_store.write_json_file(
                    latest_manifest_path,
                    {
                        "date": "2026-05-22",
                        "artifactsDir": str(artifacts_dir),
                        "state": "finished",
                    },
                )
                refresh_state_store.write_json_file(artifacts_dir / "odds_refresh.json", {"ok": True, "sports": ["mlb"]})
                refresh_state_store.write_text_file(artifacts_dir / "odds_refresh.stderr.txt", "")
                refresh_state_store.write_json_file(
                    historical_manifest_path,
                    {
                        "date": "2026-05-21",
                        "runStamp": "20260521_120000",
                        "artifactsDir": str(reports_root / "migration_runs" / "2026-05-21" / "odds_refresh_20260521_120000"),
                        "state": "failed",
                    },
                )
                refresh_state_store.write_json_file(
                    reports_root / "daily_update" / "latest" / "daily_update_latest.json",
                    {"date": "2026-05-22"},
                )

                status = ops_refresh.load_latest_refresh_status()

            self.assertEqual(status["refresh_status"]["manifest"]["date"], "2026-05-22")
            self.assertTrue(status["refresh_status"]["manifest_exists"])
            self.assertTrue(status["refresh_status"]["artifacts"]["odds_refresh"]["exists"])
            self.assertGreaterEqual(len(status["refresh_status"]["history"]), 1)


if __name__ == "__main__":
    unittest.main()