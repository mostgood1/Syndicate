from __future__ import annotations

import unittest
from types import SimpleNamespace

from router.query_router import QueryRouter


class QueryRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = QueryRouter()

    def test_classifies_trend_queries(self) -> None:
        self.assertEqual(self.router.classify_query("What is the recent trend for points?"), "trend")

    def test_classifies_explanation_queries(self) -> None:
        self.assertEqual(self.router.classify_query("Why is this matchup strong?"), "explanation")

    def test_classifies_comparison_queries(self) -> None:
        self.assertEqual(self.router.classify_query("Compare Player A vs Player B"), "comparison")

    def test_classifies_live_queries(self) -> None:
        self.assertEqual(self.router.classify_query("What are the best live bets right now?"), "live")

    def test_routes_request_payload_with_mode(self) -> None:
        request = SimpleNamespace(get_json=lambda silent=True: {"question": "Compare Player A vs Player B", "date": "2026-06-04"}, form={})

        routed_payload = self.router.route_request(request)

        self.assertEqual(routed_payload["question"], "Compare Player A vs Player B")
        self.assertEqual(routed_payload["mode"], "comparison")
        self.assertEqual(routed_payload["query_type"], "comparison")

    def test_routes_generic_board_query_preserves_explicit_recommendation_mode(self) -> None:
        routed_payload = self.router.route_payload({"question": "top edges today", "mode": "recommendation", "date": "2026-06-25"})

        self.assertEqual(routed_payload["question"], "top edges today")
        self.assertEqual(routed_payload["mode"], "recommendation")
        self.assertEqual(routed_payload["query_type"], "explanation")


if __name__ == "__main__":
    unittest.main()