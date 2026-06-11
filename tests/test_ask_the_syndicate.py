from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from pipeline.intelligence_models import IntelligenceResult
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter


class AskTheSyndicateApiTests(unittest.TestCase):
    def test_query_route_returns_bet_analysis_schema(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        fake_result = {
            "query_type": "player_analysis",
            "recommendations": [
                {
                    "selection": "Jayson Tatum Over 28.5",
                    "model_probability": 0.62,
                    "market_probability": 0.54,
                    "edge": 0.08,
                    "expected_value": 0.12,
                    "confidence": 0.63,
                    "summary": "Model edge on the spread.",
                    "rationale": "Model edge on the spread.",
                }
            ],
            "analysis_brief": {"kind": "bundle", "title": "Brief"},
            "supporting_evidence": {"kind": "bundle", "title": "Evidence"},
            "readiness_gate": {"ok": True},
            "local_only": True,
        }

        class _FakeResult:
            def to_dict(self) -> dict[str, object]:
                return dict(fake_result)

        with patch("syndicate.blueprints.ask_the_syndicate.run_intelligence_query", return_value=fake_result) as mocked_pipeline:
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "What do you think of this spread?",
                    "context": {"selected_date": "2026-06-10", "sport": "nba", "limit": 3},
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schema_type"], "bet_analysis")
        self.assertEqual(payload["schema"]["selection"], "Jayson Tatum Over 28.5")
        self.assertEqual(payload["schema"]["explanation"]["analysis_brief"]["title"], "Brief")
        mocked_pipeline.assert_called_once()

    def test_query_route_returns_matchup_schema(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        fake_result = {
            "query_type": "comparison",
            "analysis_views": {
                "focus": "subject_comparison",
                "table": {
                    "rows": [
                        {
                            "label": "Lakers",
                            "matchup": "Lakers vs Celtics",
                            "model_probability": 0.57,
                            "market_probability": 0.49,
                            "expected_value": 0.07,
                            "confidence": 0.58,
                            "reasoning": "Lakers have the cleaner path.",
                        },
                        {
                            "label": "Celtics",
                            "matchup": "Lakers vs Celtics",
                            "model_probability": 0.43,
                            "market_probability": 0.51,
                            "expected_value": -0.04,
                            "confidence": 0.44,
                            "reasoning": "Celtics are priced tighter.",
                        },
                    ]
                },
            },
            "recommendations": [
                {
                    "label": "Lakers",
                    "matchup": "Lakers vs Celtics",
                    "model_probability": 0.57,
                    "market_probability": 0.49,
                    "expected_value": 0.07,
                    "confidence": 0.58,
                    "market_fit_note": "Matchup edge leans Lakers.",
                }
            ],
            "board_notes": ["Rotation note"],
            "readiness_gate": {"ok": True},
        }

        class _FakeResult:
            def to_dict(self) -> dict[str, object]:
                return dict(fake_result)

        with patch("syndicate.blueprints.ask_the_syndicate.run_intelligence_query", return_value=fake_result):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={"question": "Lakers vs Celtics", "context": {"sport": "nba"}},
            )

        payload = response.get_json()
        self.assertEqual(payload["schema_type"], "matchup_analysis")
        self.assertEqual(payload["schema"]["teams"], ["Lakers", "Celtics"])
        self.assertEqual(payload["schema"]["simulation_summary"]["analysis_focus"], "subject_comparison")
        self.assertEqual(payload["schema"]["hidden_factors"][0]["factor"], "Rotation note")

    def test_query_route_returns_market_summary_schema(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        fake_result = {
            "query_type": "market_summary",
            "summary": "Top edges are concentrated in NBA props.",
            "recommendations": [
                {
                    "name": "Jayson Tatum Over 28.5",
                    "market": "PTS",
                    "model_probability": 0.62,
                    "market_probability": 0.54,
                    "edge": 0.08,
                    "expected_value": 0.12,
                    "confidence": 0.63,
                    "summary": "Clear model edge on the board.",
                }
            ],
            "analysis_brief": {"kind": "bundle", "title": "Brief"},
            "supporting_evidence": {"kind": "bundle", "title": "Evidence"},
            "readiness_gate": {"ok": True},
        }

        class _FakeResult:
            def to_dict(self) -> dict[str, object]:
                return dict(fake_result)

        with patch("syndicate.blueprints.ask_the_syndicate.run_intelligence_query", return_value=fake_result):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={"question": "top edges today", "context": {"sport": "nba"}},
            )

        payload = response.get_json()
        self.assertEqual(payload["schema_type"], "market_summary")
        self.assertEqual(payload["schema"]["top_opportunities"][0]["selection"], "Jayson Tatum Over 28.5")
        self.assertEqual(payload["schema"]["rationale_summary"]["analysis_brief"]["title"], "Brief")

    def test_query_route_requires_question(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        response = app.test_client().post("/api/syndicate/query", json={"context": {"sport": "nba"}})

        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("question is required", payload["error"])

    def test_query_router_routes_by_intent(self) -> None:
        router = SyndicateQueryRouter()

        self.assertEqual(router.route("What do you think of this spread?").intent, "bet_analysis")
        self.assertEqual(router.route("Lakers vs Celtics").intent, "matchup_analysis")
        self.assertEqual(router.route("best bets today").intent, "market_summary")
        self.assertEqual(router.route("top edges on these player props").intent, "market_summary")

    def test_adapter_uses_engine_explainability(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "query_type": "bet_analysis",
                "summary": "Scanned 2 candidates.",
                "recommendations": [
                    {
                        "name": "Jayson Tatum Over 28.5",
                        "confidence": 0.63,
                        "analysis_brief": {"kind": "bundle", "title": "Brief"},
                    }
                ],
                "analysis_brief": {"kind": "bundle", "title": "Brief"},
                "supporting_evidence": {"kind": "bundle", "title": "Evidence"},
                "readiness_gate": {"ok": True},
            }
        )

        payload = build_syndicate_query_response(
            question="What do you think of the spread?",
            context={"sport": "nba"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=("what_do_you_think_of",), score=301),
            result=result,
        )

        self.assertEqual(payload["schema_type"], "bet_analysis")
        self.assertEqual(payload["schema"]["selection"], "Jayson Tatum Over 28.5")
        self.assertEqual(payload["schema"]["explanation"]["analysis_brief"]["title"], "Brief")
        self.assertEqual(payload["schema"]["explanation"]["supporting_evidence"]["title"], "Evidence")


if __name__ == "__main__":
    unittest.main()