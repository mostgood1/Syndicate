from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from unittest.mock import patch
from urllib.error import URLError

from syndicate.app import create_app
from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import publish_hot_artifact
from syndicate.features.shared.artifact_publisher import publish_changed_hot_artifacts


class HotArtifactAllowlistTests(unittest.TestCase):
    def test_accepts_known_hot_artifact_shapes(self) -> None:
        self.assertTrue(
            is_hot_artifact_relative_path(
                "mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_07_13.json"
            )
        )
        self.assertTrue(is_hot_artifact_relative_path("reports/intelligence/board_snapshot.json"))
        self.assertTrue(is_hot_artifact_relative_path("reports/intelligence/intelligence_state.json"))
        self.assertTrue(
            is_hot_artifact_relative_path(
                "wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-13.json"
            )
        )

    def test_rejects_paths_outside_allowlist(self) -> None:
        self.assertFalse(is_hot_artifact_relative_path("reports/intelligence/evaluation_ledger_chunks/part_1.json"))
        self.assertFalse(is_hot_artifact_relative_path("mlb_source/source_artifacts/data/statcast/2026.csv"))
        self.assertFalse(is_hot_artifact_relative_path(""))

    def test_rejects_path_traversal_and_absolute_paths(self) -> None:
        self.assertFalse(is_hot_artifact_relative_path("../../etc/passwd"))
        self.assertFalse(
            is_hot_artifact_relative_path("/reports/intelligence/board_snapshot.json")
        )
        self.assertFalse(
            is_hot_artifact_relative_path("mlb_source/../../../reports/intelligence/board_snapshot.json")
        )


class PublishHotArtifactClientTests(unittest.TestCase):
    def test_noop_when_publish_url_not_configured(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / "reports" / "intelligence" / "board_snapshot.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ,
                {"SYNDICATE_DATA_ROOT": str(data_root), "ADMIN_TOKEN": "secret-token"},
                clear=False,
            ):
                os.environ.pop("SYNDICATE_WEB_PUBLISH_URL", None)
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    result = publish_hot_artifact(target)
        self.assertFalse(result)
        mocked_urlopen.assert_not_called()

    def test_noop_when_path_not_in_allowlist(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / "mlb_source" / "source_artifacts" / "data" / "statcast" / "2026.csv"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("data", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen") as mocked_urlopen:
                    result = publish_hot_artifact(target)
        self.assertFalse(result)
        mocked_urlopen.assert_not_called()

    def test_publishes_allowlisted_file_with_expected_request(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / "reports" / "intelligence" / "board_snapshot.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"candidate_count": 3}), encoding="utf-8")

            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = b"{}"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    result = publish_hot_artifact(target)

        self.assertTrue(result)
        mocked_urlopen.assert_called_once()
        sent_request = mocked_urlopen.call_args.args[0]
        self.assertEqual(sent_request.full_url, "https://syndicate.onrender.com/api/ops/artifacts/publish")
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer secret-token")
        body = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(body["relative_path"], "reports/intelligence/board_snapshot.json")
        self.assertIn("candidate_count", body["content"])

    def test_network_failure_is_swallowed(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            target = data_root / "reports" / "intelligence" / "board_snapshot.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", side_effect=URLError("boom")):
                    result = publish_hot_artifact(target)
        self.assertFalse(result)

    def test_publish_changed_hot_artifacts_only_publishes_recent_matching_files(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            fresh = data_root / "reports" / "intelligence" / "board_snapshot.json"
            stale_dir = data_root / "reports" / "intelligence"
            fresh.parent.mkdir(parents=True, exist_ok=True)
            fresh.write_text("{}", encoding="utf-8")
            not_allowlisted = data_root / "reports" / "intelligence" / "evaluation_ledger_chunks" / "part_1.json"
            not_allowlisted.parent.mkdir(parents=True, exist_ok=True)
            not_allowlisted.write_text("{}", encoding="utf-8")

            import time

            since_epoch = time.time() - 3600

            mocked_response = MagicMock()
            mocked_response.__enter__.return_value = mocked_response
            mocked_response.read.return_value = b"{}"

            with patch.dict(
                os.environ,
                {
                    "SYNDICATE_DATA_ROOT": str(data_root),
                    "ADMIN_TOKEN": "secret-token",
                    "SYNDICATE_WEB_PUBLISH_URL": "https://syndicate.onrender.com",
                },
                clear=False,
            ):
                with patch("urllib.request.urlopen", return_value=mocked_response) as mocked_urlopen:
                    published_count = publish_changed_hot_artifacts(since_epoch)

        self.assertEqual(published_count, 1)
        mocked_urlopen.assert_called_once()


class ArtifactPublishEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_requires_admin_token(self) -> None:
        response = self.client.post(
            "/api/ops/artifacts/publish",
            json={"relative_path": "reports/intelligence/board_snapshot.json", "content": "{}"},
        )
        self.assertEqual(response.status_code, 503)

    def test_rejects_unauthorized_request(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": "reports/intelligence/board_snapshot.json", "content": "{}"},
                headers={"Authorization": "Bearer wrong-token"},
            )
        self.assertEqual(response.status_code, 401)

    def test_rejects_path_not_in_allowlist(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={"relative_path": "mlb_source/source_artifacts/data/statcast/2026.csv", "content": "data"},
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 403)

    def test_rejects_path_traversal(self) -> None:
        with patch.dict(os.environ, {"ADMIN_TOKEN": "secret-token"}, clear=False):
            response = self.client.post(
                "/api/ops/artifacts/publish",
                json={
                    "relative_path": "../../reports/intelligence/board_snapshot.json",
                    "content": "{}",
                },
                headers={"Authorization": "Bearer secret-token"},
            )
        self.assertEqual(response.status_code, 400)

    def test_writes_allowlisted_artifact_atomically(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            data_root = Path(tmp_dir)
            with patch.dict(
                os.environ,
                {"ADMIN_TOKEN": "secret-token", "SYNDICATE_DATA_ROOT": str(data_root)},
                clear=False,
            ):
                response = self.client.post(
                    "/api/ops/artifacts/publish",
                    json={
                        "relative_path": "reports/intelligence/board_snapshot.json",
                        "content": json.dumps({"candidate_count": 5}),
                    },
                    headers={"Authorization": "Bearer secret-token"},
                )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            written_path = data_root / "reports" / "intelligence" / "board_snapshot.json"
            self.assertTrue(written_path.exists())
            self.assertEqual(json.loads(written_path.read_text(encoding="utf-8"))["candidate_count"], 5)
            # No leftover temp files from the atomic write.
            leftovers = list(written_path.parent.glob("board_snapshot.json.*.tmp"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
