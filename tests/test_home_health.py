from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from syndicate.app import create_app


class HomeHealthRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_healthz_returns_lightweight_ok_payload(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "service": "syndicate"})

    def test_api_health_alias_returns_same_payload(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "service": "syndicate"})

    def test_versionz_exposes_public_deploy_and_checkout_metadata(self) -> None:
        with patch.dict(
            os.environ,
            {
                "RENDER_GIT_COMMIT": "e6aa9a6",
                "RENDER_GIT_BRANCH": "main",
                "RENDER_SERVICE_NAME": "syndicate-web",
            },
            clear=False,
        ), patch("syndicate.blueprints.home._git_value", side_effect=["ebb2136d", "main"]), patch(
            "syndicate.blueprints.home.socket.gethostname",
            return_value="host-123",
        ), patch("syndicate.blueprints.home.os.getpid", return_value=4321), patch(
            "syndicate.blueprints.home.time.time",
            return_value=1234.5,
        ):
            response = self.client.get("/versionz")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        version = payload["version"]
        self.assertEqual(version["commit"], "e6aa9a6")
        self.assertEqual(version["env_commit"], "e6aa9a6")
        self.assertEqual(version["git_commit"], "ebb2136d")
        self.assertFalse(version["commit_matches_checkout"])
        self.assertEqual(version["branch"], "main")
        self.assertEqual(version["render_service_name"], "syndicate-web")
        self.assertEqual(version["hostname"], "host-123")
        self.assertEqual(version["pid"], 4321)
        self.assertEqual(version["served_at"], 1234.5)


if __name__ == "__main__":
    unittest.main()