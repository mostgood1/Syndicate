from __future__ import annotations

import unittest
from unittest.mock import patch

import syndicate.blueprints.wnba as wnba_routes
from syndicate.app import create_app


class WnbaApiSnapshotErrorTests(unittest.TestCase):
    def setUp(self) -> None:
        wnba_routes._WNBA_API_THROTTLE_STATE.clear()

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

    def test_wnba_api_cards_throttles_burst_requests(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        payload = {
            "ok": True,
            "date": "2026-06-19",
            "cards": [],
            "games": [],
        }
        with patch("syndicate.blueprints.wnba.build_cards_page_context", return_value={"date": "2026-06-19", "games": []}) as build_context, patch(
            "syndicate.blueprints.wnba.build_game_board_api_payload", return_value=payload
        ) as build_payload:
            first_response = client.get("/wnba/api/cards?date=2026-06-19")
            second_response = client.get("/wnba/api/cards?date=2026-06-19")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.get_json(), payload)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response.is_json, True)
        self.assertEqual(second_response.get_json()["error"], "throttled")
        self.assertEqual(second_response.headers.get("Retry-After"), "8")
        self.assertEqual(build_context.call_count, 1)
        self.assertEqual(build_payload.call_count, 1)

    def test_wnba_api_cards_render_fallback_keeps_requested_date(self) -> None:
        from syndicate.app import app as syndicate_app
        from syndicate.blueprints import wnba as wnba_blueprint

        def fake_build_cards_page_context(selected_date: str, *, allow_stored_date_fallback: bool = False):
            raise RuntimeError("dense board unavailable")

        def fake_build_source_cards_payload(selected_date: str, *, allow_stored_date_fallback: bool = False):
            self.assertEqual(selected_date, "2026-06-21")
            self.assertTrue(allow_stored_date_fallback)
            return {
                "date": "2026-06-21",
                "requested_date": "2026-06-21",
                "games": [],
                "source_title": "WNBA source cards fallback",
            }

        with patch.dict("os.environ", {"RENDER": "1"}, clear=False), patch.object(
            wnba_blueprint,
            "build_cards_page_context",
            side_effect=fake_build_cards_page_context,
        ), patch.object(
            wnba_blueprint,
            "build_source_cards_payload",
            side_effect=fake_build_source_cards_payload,
        ):
            with syndicate_app.test_client() as client:
                response = client.get("/wnba/api/cards?date=2026-06-21")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertEqual(payload.get("date"), "2026-06-21")
        self.assertEqual(payload.get("requested_date"), "2026-06-21")

    def test_wnba_live_lens_api_throttles_burst_requests(self) -> None:
        app = create_app()
        app.config.update(TESTING=True)
        client = app.test_client()

        payload = {"ok": True, "date": "2026-06-19", "cards": [], "games": []}
        with patch("syndicate.blueprints.wnba.build_live_lens_api_payload", return_value=payload) as build_payload:
            first_response = client.get("/wnba/api/live-lens?date=2026-06-19")
            second_response = client.get("/wnba/api/live-lens?date=2026-06-19")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.get_json(), payload)
        self.assertEqual(second_response.status_code, 429)
        self.assertEqual(second_response.is_json, True)
        self.assertEqual(second_response.get_json()["error"], "throttled")
        self.assertEqual(second_response.headers.get("Retry-After"), "8")
        self.assertEqual(build_payload.call_count, 1)


if __name__ == "__main__":
    unittest.main()