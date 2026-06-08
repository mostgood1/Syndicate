from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.intelligence_entrypoint import route_intelligence_request
from pipeline.intelligence_entrypoint import run_routed_intelligence_pipeline


class IntelligenceEntrypointTests(unittest.TestCase):
    def test_route_intelligence_request_attaches_classification(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "What are the best live bets right now?"}, form={})

        payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "live")
        self.assertEqual(payload["query_type"], "live_analysis")

    def test_route_intelligence_request_detects_game_preview(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "Preview the Celtics game tonight"}, form={})

        payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "pregame")
        self.assertEqual(payload["query_type"], "game_preview")
        self.assertEqual(payload["preview_subject"], "Celtics")
        self.assertTrue(payload["include_games"])
        self.assertTrue(payload["include_props"])

    def test_route_intelligence_request_detects_player_analysis(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "Analyze Jayson Tatum tonight"}, form={})

        payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "pregame")
        self.assertEqual(payload["query_type"], "player_analysis")
        self.assertEqual(payload["player_subject"], "Jayson Tatum")
        self.assertTrue(payload["include_games"])
        self.assertTrue(payload["include_props"])

    def test_route_intelligence_request_resolves_preview_date_and_subject(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "preview the Lakers game tonight"}, form={})

        with patch("router.query_router.central_today_iso", return_value="2026-06-07"):
            payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "pregame")
        self.assertEqual(payload["query_type"], "game_preview")
        self.assertEqual(payload["preview_subject"], "Lakers")
        self.assertEqual(payload["selected_date"], "2026-06-07")
        self.assertEqual(payload["date"], "2026-06-07")

    def test_route_intelligence_request_resolves_player_date(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "break down Aaron Judge today"}, form={})

        with patch("router.query_router.central_today_iso", return_value="2026-06-07"):
            payload = route_intelligence_request(request)

        self.assertEqual(payload["mode"], "pregame")
        self.assertEqual(payload["query_type"], "player_analysis")
        self.assertEqual(payload["player_subject"], "Aaron Judge")
        self.assertEqual(payload["selected_date"], "2026-06-07")
        self.assertEqual(payload["date"], "2026-06-07")

    def test_run_routed_intelligence_pipeline_uses_routed_payload(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "Compare Player A vs Player B"}, form={})

        with patch("pipeline.intelligence_entrypoint.run_intelligence_pipeline", return_value="ok") as mocked_pipeline:
            result = run_routed_intelligence_pipeline(request)

        self.assertEqual(result, "ok")
        mocked_pipeline.assert_called_once()
        routed_payload = mocked_pipeline.call_args.args[0]
        self.assertEqual(routed_payload["mode"], "comparison")
        self.assertEqual(routed_payload["query_type"], "comparison")


if __name__ == "__main__":
    unittest.main()