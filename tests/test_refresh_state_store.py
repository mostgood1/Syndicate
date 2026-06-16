from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import ops_refresh
from syndicate.features.shared import refresh_state_store
from syndicate.features.shared.source_roots import preferred_artifact_roots
from syndicate.features.shared.source_roots import preferred_source_roots


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

    def test_hosted_storage_requires_explicit_roots(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                refresh_state_store.data_root()
            with self.assertRaises(RuntimeError):
                refresh_state_store.reports_root()

        with TemporaryDirectory() as tmp_dir:
            probe_file = Path(tmp_dir) / "probe.py"
            probe_file.write_text("", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_REQUIRE_HOSTED_STORAGE": "true",
                },
                clear=False,
            ):
                with self.assertRaises(RuntimeError):
                    preferred_source_roots(probe_file, env_var="SYNDICATE_SOURCE_ROOT_NBA", local_dir_name="nba_source")
                with self.assertRaises(RuntimeError):
                    preferred_artifact_roots(probe_file, env_var="SYNDICATE_ARTIFACT_ROOT_NBA", local_dir_name="nba_source")

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

    def test_refresh_state_hash_round_trips_and_reuses_identical_inputs(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            state_path = refresh_state_store.refresh_state_path()
            input_hash = refresh_state_store.build_input_hash({"step": "nba_live_lens", "inputs": ["a", "b"]})

            self.assertTrue(refresh_state_store.should_recompute("nba_live_lens", input_hash))
            refresh_state_store.record_refresh_state(
                "nba_live_lens",
                input_hash,
                outputs=[str(Path(tmp_dir) / "reports" / "nba_live_lens.jsonl")],
                metadata={"date": "2026-06-10"},
            )

            self.assertFalse(refresh_state_store.should_recompute("nba_live_lens", input_hash))
            self.assertEqual(
                refresh_state_store.read_json_file(state_path),
                {
                    "steps": {
                        "nba_live_lens": {
                            "inputHash": input_hash,
                            "outputs": [str(Path(tmp_dir) / "reports" / "nba_live_lens.jsonl")],
                            "metadata": {"date": "2026-06-10"},
                            "updatedAt": refresh_state_store.read_json_file(state_path)["steps"]["nba_live_lens"]["updatedAt"],
                        }
                    }
                },
            )

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

    def test_launch_refresh_run_writes_latest_manifest_through_keyvalue_backend(self) -> None:
        fake_client = _FakeKeyValueClient()
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REFRESH_STATE_BACKEND": "keyvalue",
                "SYNDICATE_REFRESH_STATE_URL": "redis://example",
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ), patch("syndicate.features.shared.refresh_state_store._get_keyvalue_client", return_value=fake_client), patch("syndicate.features.shared.ops_refresh.subprocess.Popen") as mocked_popen:
            mocked_popen.return_value.pid = 4321

            result = ops_refresh.launch_refresh_run(sports="wnba", phase="pregame", dry_run=True)
            status = ops_refresh.load_latest_refresh_status()

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "running")
        self.assertEqual(status["refresh_status"]["manifest"]["runStamp"], result["run_stamp"])
        self.assertEqual(status["refresh_status"]["runtime"]["pid"], 4321)
        self.assertEqual(status["refresh_status"]["runtime"]["launch_owner"], "web_process")

    def test_load_latest_refresh_status_prefers_unified_daily_update_manifest(self) -> None:
        with TemporaryDirectory() as tmp_dir, patch.dict(
            os.environ,
            {
                "SYNDICATE_REPORTS_ROOT": str(Path(tmp_dir) / "reports"),
            },
            clear=False,
        ):
            reports_root = Path(tmp_dir) / "reports"
            refresh_latest = reports_root / "refresh_status" / "latest"
            daily_latest = reports_root / "daily_update" / "latest"
            artifacts_dir = reports_root / "migration_runs" / "2026-06-04" / "20260604_110712"

            refresh_latest.mkdir(parents=True, exist_ok=True)
            daily_latest.mkdir(parents=True, exist_ok=True)
            artifacts_dir.mkdir(parents=True, exist_ok=True)

            refresh_state_store.write_json_file(
                refresh_latest / "refresh_status_latest.json",
                {
                    "date": "2026-06-04",
                    "artifactsDir": str(artifacts_dir),
                    "state": "finished",
                },
            )
            refresh_state_store.write_json_file(artifacts_dir / "odds_refresh.json", {"ok": True, "sports": ["wnba"]})
            refresh_state_store.write_text_file(artifacts_dir / "odds_refresh.stderr.txt", "")
            refresh_state_store.write_json_file(
                daily_latest / "daily_update_latest.json",
                {"date": "2026-05-18"},
            )
            refresh_state_store.write_json_file(
                daily_latest / "unified_daily_update_latest.json",
                {"date": "2026-06-04", "skipped": {"nba": True}},
            )

            status = ops_refresh.load_latest_refresh_status()

        self.assertEqual(status["daily_update"]["manifest"]["date"], "2026-06-04")
        self.assertTrue(status["daily_update"]["manifest_exists"])
        self.assertTrue(status["daily_update"]["manifest_path"].endswith("unified_daily_update_latest.json"))


if __name__ == "__main__":
    unittest.main()