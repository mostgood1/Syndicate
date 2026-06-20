from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app


class WnbaApiSnapshotErrorTests(unittest.TestCase):
    def test_wnba_cards_api_returns_json_on_snapshot_failure(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        with patch("syndicate.blueprints.wnba.build_cards_page_context", side_effect=RuntimeError("boom")), patch(
            "syndicate.blueprints.wnba.build_source_cards_payload", side_effect=RuntimeError("boom source")
        ):
            response = client.get("/wnba/api/cards?date=2026-06-19")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.is_json, True)
        self.assertEqual(response.get_json(), {"ok": False, "error": "snapshot_unavailable", "cards": []})

    def test_wnba_live_lens_api_returns_json_on_snapshot_failure(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        with patch("syndicate.blueprints.wnba.build_live_lens_api_payload", side_effect=RuntimeError("boom")):
            response = client.get("/wnba/api/live-lens?date=2026-06-19")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.is_json, True)
        self.assertEqual(response.get_json(), {"ok": False, "error": "snapshot_unavailable", "cards": []})


if __name__ == "__main__":
    unittest.main()