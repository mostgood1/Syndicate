from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()