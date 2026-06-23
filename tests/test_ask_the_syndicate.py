from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask

from pipeline.intelligence_models import IntelligenceResult
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_query_api
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

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)) as mocked_snapshot:
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
        mocked_snapshot.assert_called_once()

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

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)):
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
            "evaluation_record": {"kind": "bundle", "title": "Evaluation record"},
            "evaluation_history": {"kind": "bundle", "title": "Evaluation history", "history_status": "available"},
            "readiness_gate": {"ok": True},
        }

        class _FakeResult:
            def to_dict(self) -> dict[str, object]:
                return dict(fake_result)

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={"question": "top edges today", "context": {"sport": "nba"}},
            )

        payload = response.get_json()
        self.assertEqual(payload["schema_type"], "market_summary")
        self.assertEqual(payload["schema"]["top_opportunities"][0]["selection"], "Jayson Tatum Over 28.5")
        self.assertEqual(payload["schema"]["rationale_summary"]["analysis_brief"]["title"], "Brief")
        self.assertEqual([section["title"] for section in payload["supporting_evidence"]], ["Brief", "Evidence", "Recommendation evidence"])
        self.assertEqual(payload["evaluation_record"]["title"], "Evaluation record")
        self.assertEqual(payload["engine"]["evaluation_record"]["title"], "Evaluation record")
        self.assertEqual(payload["evaluation_history"]["title"], "Evaluation history")
        self.assertEqual(payload["engine"]["evaluation_history"]["history_status"], "available")

    def test_query_route_requires_question(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        response = app.test_client().post("/api/syndicate/query", json={"context": {"sport": "nba"}})

        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("question is required", payload["error"])

    def test_query_route_sets_cors_headers_for_post_and_preflight(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        post_response = app.test_client().post(
            "/api/syndicate/query",
            json={"question": "top edges today", "context": {"sport": "nba"}},
            headers={"Origin": "https://example.com"},
        )

        preflight_response = app.test_client().options(
            "/api/syndicate/query",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        self.assertEqual(post_response.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("POST", post_response.headers.get("Access-Control-Allow-Methods", ""))
        self.assertEqual(preflight_response.status_code, 200)
        self.assertEqual(preflight_response.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("OPTIONS", preflight_response.headers.get("Access-Control-Allow-Methods", ""))

    def test_query_router_routes_by_intent(self) -> None:
        router = SyndicateQueryRouter()

        self.assertEqual(router.route("What do you think of this spread?").intent, "bet_analysis")
        self.assertEqual(router.route("Lakers vs Celtics").intent, "matchup_analysis")
        self.assertEqual(router.route("Compare NBA and WNBA picks tonight").intent, "comparison")
        self.assertEqual(router.route("best bets today").intent, "market_summary")
        self.assertEqual(router.route("top edges on these player props").intent, "market_summary")

    def test_query_router_prefers_comparison_over_matchup_when_both_match(self) -> None:
        router = SyndicateQueryRouter()

        self.assertEqual(router.route("Compare Lakers vs Celtics tonight").intent, "comparison")

    def test_blueprint_shapes_comparison_prompts_for_matchup_execution(self) -> None:
        payload = ask_the_syndicate_query_api
        shaped = payload.__globals__["_smart_route_payload"]({"question": "Compare NBA and WNBA picks tonight", "context": {"sport": "nba"}})

        self.assertEqual(shaped["query_type"], "comparison")
        self.assertEqual(shaped["mode"], "comparison")
        self.assertTrue(shaped["include_games"])
        self.assertTrue(shaped["include_props"])

    def test_query_cache_key_treats_comparison_as_comparison_intent(self) -> None:
        payload = ask_the_syndicate_query_api
        cache_key = payload.__globals__["_query_cache_key"](
            "Compare NBA and WNBA picks tonight",
            {"question": "Compare NBA and WNBA picks tonight", "context": {"sport": "nba"}},
            RouteDecision(intent="comparison", handler_name="handle_matchup_analysis", matched_terms=("compare",), score=351),
        )

        self.assertTrue(cache_key)

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

    def test_adapter_exposes_routing_context_and_context_awareness(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "query_type": "comparison",
                "summary": "Cross-sport comparison",
                "structured_response": {
                    "context_awareness": {
                        "detected_sports": ["nba", "wnba"],
                        "multi_sport": True,
                    }
                },
                "recommendations": [{"name": "NBA side", "summary": "Primary NBA angle."}],
            },
            pipeline_context={
                "routing_context": {
                    "question": "Compare NBA and WNBA picks tonight",
                    "query_type": "comparison",
                    "sport": "nba",
                }
            },
        )

        payload = build_syndicate_query_response(
            question="Compare NBA and WNBA picks tonight",
            context={"sport": "nba"},
            decision=RouteDecision(intent="market_summary", handler_name="handle_market_summary", matched_terms=("compare",), score=280),
            result=result,
        )

        self.assertEqual(payload["routing_context"]["query_type"], "comparison")
        self.assertEqual(payload["routing_context"]["question"], "Compare NBA and WNBA picks tonight")
        self.assertEqual(payload["context_awareness"]["detected_sports"], ["nba", "wnba"])
        self.assertTrue(payload["context_awareness"]["multi_sport"])
        self.assertEqual(payload["engine"]["routing_context"]["sport"], "nba")

    def test_adapter_carries_daily_update_simulation_contract(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "query_type": "bet_analysis",
                "summary": "Snapshot summary",
                "daily_update": {
                    "simulation_contract": {
                        "scope": "daily_update",
                        "sport_count": 7,
                        "advanced_by_sport": {"mlb": {"available": True}},
                    }
                },
            }
        )

        payload = build_syndicate_query_response(
            question="Who stands out today?",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=("stand out",), score=0.8),
            result=result,
        )

        self.assertEqual(payload["daily_update"]["simulation_contract"]["scope"], "daily_update")
        self.assertEqual(payload["simulation_contract"]["advanced_by_sport"]["mlb"]["available"], True)
        self.assertEqual(payload["engine"]["simulation_contract"]["sport_count"], 7)

    def test_query_route_returns_comparison_schema_for_compare_prompts(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        snapshot = {
            "query_type": "comparison",
            "summary": "Cross-sport comparison",
            "recommendations": [
                {"name": "NBA side", "summary": "Primary NBA angle."},
                {"name": "WNBA side", "summary": "Primary WNBA angle."},
            ],
            "parsed_request": {"requested_subjects": ["NBA side", "WNBA side"]},
            "structured_response": {
                "supporting_evidence": [
                    {"kind": "bundle", "title": "Comparison evidence"},
                    {"kind": "bundle", "title": "Cross-sport reasoning"},
                ],
                "context_awareness": {"detected_sports": ["nba", "wnba"], "multi_sport": True},
            },
            "analysis_views": {},
            "analysis_brief": {"kind": "bundle", "title": "Brief"},
            "supporting_evidence": {"kind": "bundle", "title": "Evidence"},
            "readiness_gate": {"ok": True},
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(snapshot)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "Compare NBA and WNBA picks tonight",
                    "context": {"sport": "nba"},
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["intent"], "comparison")
        self.assertEqual(payload["schema_type"], "matchup_analysis")
        self.assertEqual(payload["routing"]["handler"], "handle_matchup_analysis")
        self.assertEqual(payload["schema"]["teams"], ["NBA side", "WNBA side"])
        self.assertEqual([section["title"] for section in payload["supporting_evidence"]], ["Comparison evidence", "Cross-sport reasoning"])
        self.assertEqual(payload["routing_context"]["sport"], "nba")

    def test_query_route_returns_safe_fallback_message_when_snapshot_is_missing(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value={}):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "What do you think of this spread?",
                    "context": {"sport": "nba"},
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["schema_type"], "bet_analysis")
        self.assertEqual(payload["schema"]["recommendation"], "No saved intelligence snapshot is available yet.")
        self.assertEqual(payload["schema"]["explanation"]["analysis_brief"]["title"], "Snapshot unavailable")

    def test_query_route_preserves_routing_context_on_latest_state_responses(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        cached_state = {
            "latestKey": "cache-key",
            "latestComputedAt": "2026-06-12T22:16:54Z",
            "top_opportunities": [
                {
                    "name": "NBA side",
                    "summary": "Primary NBA angle.",
                }
            ],
            "response": {
                "recommendations": [
                    {
                        "name": "NBA side",
                        "summary": "Primary NBA angle.",
                    }
                ],
                "analysis_views": {},
            },
            "structured_response": {
                "context_awareness": {
                    "detected_sports": ["nba", "wnba"],
                    "multi_sport": True,
                }
            },
            "pipeline_context": {
                "routing_context": {
                    "question": "Compare NBA and WNBA picks tonight",
                    "sport": "nba",
                }
            },
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(cached_state)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "Compare NBA and WNBA picks tonight",
                    "context": {"sport": "nba"},
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["routing_context"]["question"], "Compare NBA and WNBA picks tonight")
        self.assertEqual(payload["routing_context"]["sport"], "nba")
        self.assertEqual(payload["context_awareness"]["detected_sports"], ["nba", "wnba"])
        self.assertTrue(payload["context_awareness"]["multi_sport"])
        self.assertEqual(payload["board_contract"]["schema"], "intelligence_board_v1")

    def test_query_route_hydrates_opportunities_from_analysis_only_state(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        cached_state = {
            "analysis": {
                "recommendations": [{"name": "NBA side", "summary": "Primary NBA angle."}],
                "picks": [],
                "top_live_opportunities": [],
                "portfolio": {},
                "parlays": [],
            },
            "response": {
                "analysis": {
                    "recommendations": [{"name": "NBA side", "summary": "Primary NBA angle."}],
                    "picks": [],
                    "top_live_opportunities": [],
                    "portfolio": {},
                    "parlays": [],
                }
            },
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_board_snapshot_response", return_value=None):
            with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state_response", return_value=dict(cached_state)):
                response = app.test_client().post(
                    "/api/syndicate/query",
                    json={
                        "question": "What do you think of this spread?",
                        "context": {"sport": "nba"},
                    },
                )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["schema"]["selection"], "NBA side")
        self.assertEqual(payload["schema"]["recommendation"], "Primary NBA angle.")


if __name__ == "__main__":
    unittest.main()