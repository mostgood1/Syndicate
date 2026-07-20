from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from flask import Flask

import json
import tempfile

from pipeline.intelligence_models import IntelligenceResult
from syndicate.blueprints import ask_the_syndicate as ask_module
from syndicate.blueprints import ask_the_syndicate_data as ask_data
from syndicate.blueprints import ask_the_syndicate_engine as ask_engine
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_query_api
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp
from syndicate.blueprints.ask_the_syndicate_adapter import build_syndicate_query_response
from syndicate.blueprints.ask_the_syndicate_router import RouteDecision
from syndicate.blueprints.ask_the_syndicate_router import SyndicateQueryRouter


class AskTheSyndicateApiTests(unittest.TestCase):
    def setUp(self) -> None:
        ask_module._RESPONSE_CACHE.clear()
        env_patcher = patch.dict(os.environ, {"SYNDICATE_ASK_LLM_ENABLED": "false"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        # Keep route tests hermetic: no scanning of the real data disk.
        evidence_patcher = patch(
            "syndicate.blueprints.ask_the_syndicate.collect_focused_evidence", return_value=None
        )
        evidence_patcher.start()
        self.addCleanup(evidence_patcher.stop)

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


class AskTheSyndicateLlmBriefingTests(unittest.TestCase):
    def setUp(self) -> None:
        ask_module._RESPONSE_CACHE.clear()
        evidence_patcher = patch(
            "syndicate.blueprints.ask_the_syndicate.collect_focused_evidence", return_value=None
        )
        evidence_patcher.start()
        self.addCleanup(evidence_patcher.stop)

    @staticmethod
    def _snapshot() -> dict[str, object]:
        return {
            "query_type": "player_analysis",
            "summary": "Model edge on the spread.",
            "recommendations": [
                {
                    "selection": "Jayson Tatum Over 28.5",
                    "model_probability": 0.62,
                    "market_probability": 0.54,
                    "expected_value": 0.12,
                    "confidence": 0.63,
                    "summary": "Model edge on the spread.",
                }
            ],
            "readiness_gate": {"ok": True},
        }

    @staticmethod
    def _briefing_payload() -> dict[str, object]:
        return {
            "briefing": {
                "headline": "Tatum over is the board's cleanest edge",
                "verdict": "Take the over at current pricing.",
                "confidence": "Medium (62%)",
                "narrative": "SmartSim projects Tatum above the line in 62% of runs while the market implies 54%.",
                "key_drivers": ["8-point probability gap vs market"],
                "risks": ["Blowout scenario trims minutes"],
                "invalidators": ["Late injury news"],
                "top_picks": [],
                "data_quality_note": "",
            },
            "model": "claude-haiku-4-5",
            "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 0},
        }

    def test_query_route_attaches_briefing_and_merges_into_schema(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=self._snapshot()):
            with patch("syndicate.blueprints.ask_the_syndicate.generate_briefing", return_value=self._briefing_payload()) as mocked_briefing:
                response = app.test_client().post(
                    "/api/syndicate/query",
                    json={"question": "What do you think of the Tatum spread?", "context": {"sport": "nba"}},
                )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["answer_source"], "llm")
        self.assertEqual(payload["briefing"]["headline"], "Tatum over is the board's cleanest edge")
        self.assertEqual(payload["llm"]["model"], "claude-haiku-4-5")
        self.assertEqual(payload["schema"]["recommendation"], "Take the over at current pricing.")
        self.assertIn("SmartSim projects", payload["schema"]["explanation"]["summary"])
        mocked_briefing.assert_called_once()

    def test_llm_responses_are_cached_per_question(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)
        request_body = {"question": "What do you think of the Tatum spread?", "context": {"sport": "nba"}}

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=self._snapshot()):
            with patch("syndicate.blueprints.ask_the_syndicate.generate_briefing", return_value=self._briefing_payload()) as mocked_briefing:
                first = app.test_client().post("/api/syndicate/query", json=request_body)
                second = app.test_client().post("/api/syndicate/query", json=request_body)

        self.assertEqual(first.get_json()["briefing"], second.get_json()["briefing"])
        mocked_briefing.assert_called_once()

    def test_briefing_failure_falls_back_to_snapshot_response(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=self._snapshot()):
            with patch("syndicate.blueprints.ask_the_syndicate.generate_briefing", return_value=None):
                response = app.test_client().post(
                    "/api/syndicate/query",
                    json={"question": "What do you think of the Tatum spread?", "context": {"sport": "nba"}},
                )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["answer_source"], "snapshot")
        self.assertNotIn("briefing", payload)
        self.assertEqual(payload["schema"]["selection"], "Jayson Tatum Over 28.5")

    def test_missing_snapshot_skips_llm_entirely(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value={}):
            with patch("syndicate.blueprints.ask_the_syndicate.generate_briefing") as mocked_briefing:
                response = app.test_client().post(
                    "/api/syndicate/query",
                    json={"question": "What do you think of the Tatum spread?", "context": {"sport": "nba"}},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["answer_source"], "snapshot")
        mocked_briefing.assert_not_called()


class AskTheSyndicateFocusedEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def _write_mlb_fixtures(self) -> None:
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        summary = {
            "date": "2026-07-12",
            "outputs": [
                {
                    "game_pk": 823358,
                    "away": "MIL",
                    "home": "PIT",
                    "starter_names": {"away": "Jacob Misiorowski", "home": "Paul Skenes"},
                    "full": {
                        "home_win_prob": 0.495,
                        "away_win_prob": 0.505,
                        "away_runs_mean": 4.06,
                        "home_runs_mean": 3.78,
                        "total_runs_dist": {"5": 110, "7": 100, "9": 83, "3": 91},
                        "run_margin_dist": {"1": 151, "-1": 122, "2": 105},
                    },
                    "pitcher_props": {
                        "111": {"so_dist": {"4": 100, "6": 200, "8": 50}, "so_mean": 5.9, "outs_mean": 18.0, "pitches_mean": 92.0, "walks_mean": 2.1, "er_mean": 2.5},
                        "694973": {"so_dist": {"6": 120, "8": 180, "10": 60}, "so_mean": 7.8, "outs_mean": 19.5, "pitches_mean": 97.0, "walks_mean": 1.4, "er_mean": 1.9},
                    },
                }
            ],
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)
        hr_targets = {
            "games": [
                {
                    "game_pk": 823358,
                    "away": "Milwaukee Brewers",
                    "home": "Pittsburgh Pirates",
                    "away_abbr": "MIL",
                    "home_abbr": "PIT",
                    "targets": [
                        {"opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes"},
                        {"opponent_pitcher_id": 111, "opponent_pitcher_name": "Jacob Misiorowski"},
                    ],
                }
            ]
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)

    def _write_wnba_fixtures(self) -> None:
        processed = os.path.join(self.root, "wnba", "processed")
        os.makedirs(processed, exist_ok=True)
        detail = {
            "date": "2026-07-15",
            "games": [
                {
                    "home_tri": "CHI",
                    "away_tri": "SEA",
                    "sim": {
                        "players": {
                            "home": [
                                {
                                    "team": "CHI", "opponent": "SEA", "player_name": "Kamilla Cardoso",
                                    "pts_mean": 15.1, "reb_mean": 9.6, "ast_mean": 2.0,
                                    "threes_mean": 0.0, "pra_mean": 26.6,
                                    "pts_sd": 3.8, "reb_sd": 2.4, "ast_sd": 1.0, "threes_sd": 1.0, "pra_sd": 6.7,
                                    "minutes": 26.1,
                                }
                            ],
                            "away": [],
                        }
                    },
                }
            ],
        }
        with open(os.path.join(processed, "cards_sim_detail_2026-07-15.json"), "w", encoding="utf-8") as f:
            json.dump(detail, f)
        props = {
            "date": "2026-07-15",
            "games": [
                {
                    "home_tri": "CHI",
                    "away_tri": "SEA",
                    "prop_recommendations": {
                        "home": [
                            {"market": "rebounds", "side": "OVER", "line": 8.5, "price": -110.0, "book": "fanduel", "player": "Kamilla Cardoso", "edge": 0.12, "ev_pct": 14.2, "tier": "High", "basketball_summary": "model 9.6 vs line 8.5"}
                        ],
                        "away": [],
                    },
                }
            ],
        }
        with open(os.path.join(processed, "cards_props_snapshot_2026-07-15.json"), "w", encoding="utf-8") as f:
            json.dump(props, f)

    def test_mlb_game_question_yields_table_and_total_runs_chart(self) -> None:
        self._write_mlb_fixtures()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data.collect_focused_evidence(
                "How do the Brewers look against the Pirates tonight?", {"sport": "mlb"}
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["sport"], "mlb")
        self.assertEqual(result["as_of"], "2026-07-12")
        self.assertIn("Milwaukee Brewers @ Pittsburgh Pirates", result["tables"][0]["title"])
        chart_titles = [c["title"] for c in result["charts"]]
        self.assertTrue(any("total runs" in t.lower() for t in chart_titles))
        game_section = next(s for s in result["evidence"] if s["source"] == "mlb_daily_sim")
        self.assertAlmostEqual(game_section["win_probability"]["away"], 0.505)

    def test_mlb_strikeout_question_adds_pitcher_chart_with_name(self) -> None:
        self._write_mlb_fixtures()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data.collect_focused_evidence(
                "How many strikeouts for Paul Skenes vs the Brewers?", {"sport": "mlb"}
            )

        self.assertIsNotNone(result)
        table_titles = [t["title"] for t in result["tables"]]
        self.assertTrue(any("Starter sim projections" in t for t in table_titles))
        chart_titles = [c["title"] for c in result["charts"]]
        self.assertTrue(any("Paul Skenes" in t for t in chart_titles))
        game_section = next(s for s in result["evidence"] if s["source"] == "mlb_daily_sim")
        starters = {s["pitcher"] for s in game_section["starters"]}
        self.assertIn("Paul Skenes", starters)

    def test_wnba_player_question_yields_projection_and_market_lines(self) -> None:
        self._write_wnba_fixtures()
        with patch.dict(os.environ, {"WNBA_BETTING_DATA_ROOT": os.path.join(self.root, "wnba")}):
            result = ask_data.collect_focused_evidence(
                "What is the outlook for Kamilla Cardoso tonight?", {"sport": "wnba"}
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["sport"], "wnba")
        self.assertIn("Kamilla Cardoso", result["tables"][0]["title"])
        sim_section = next(s for s in result["evidence"] if s["source"] == "wnba_sim_detail")
        self.assertEqual(sim_section["market_lines"][0]["market"], "rebounds")
        self.assertEqual(result["charts"][0]["points"][0]["x"], "PTS")

    def test_wnba_team_question_yields_top_projections(self) -> None:
        self._write_wnba_fixtures()
        with patch.dict(os.environ, {"WNBA_BETTING_DATA_ROOT": os.path.join(self.root, "wnba")}):
            result = ask_data.collect_focused_evidence(
                "Who leads the Sky against the Storm?", {"sport": "wnba"}
            )

        self.assertIsNotNone(result)
        self.assertIn("Chicago Sky", result["tables"][0]["title"])
        sim_section = next(s for s in result["evidence"] if s["source"] == "wnba_sim_detail")
        self.assertEqual(sim_section["top_projections"][0]["player"], "Kamilla Cardoso")

    def test_unmatched_question_returns_none(self) -> None:
        self._write_mlb_fixtures()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data.collect_focused_evidence(
                "best bets across the board today", {"sport": "mlb"}
            )
        self.assertIsNone(result)

    def _write_wnba_boxscores(self) -> None:
        processed = os.path.join(self.root, "wnba", "processed")
        os.makedirs(processed, exist_ok=True)
        header = "game_id,gameId,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,OREB,DREB,PF,FGM,FGA,FG3M,FG3A,FTM,FTA,PLUS_MINUS,STARTER,START_POSITION,source,date"
        rows = []
        for i in range(12):
            day = f"2026-07-{i + 1:02d}"
            rows.append(f"g{i},g{i},CHI,4433405,Kamilla Cardoso,28.0,{14 + i},{8 + (i % 3)},2,1,1,2,3,5,2,6,11,0,0,2,4,5,True,C,espn,{day}")
            rows.append(f"g{i},g{i},SEA,999,Other Player,20.0,8,4,3,0,0,1,1,3,1,3,8,1,3,1,2,-2,False,G,espn,{day}")
        with open(os.path.join(processed, "boxscores_history.csv"), "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n".join(rows) + "\n")

    def test_wnba_last10_game_log_and_hit_rate(self) -> None:
        self._write_wnba_boxscores()
        with patch.dict(os.environ, {"WNBA_BETTING_DATA_ROOT": os.path.join(self.root, "wnba")}):
            result = ask_data._basketball_last10_evidence(
                "Has Cardoso cleared 18.5 points recently?", {}, "wnba"
            )

        self.assertIsNotNone(result)
        table = result["tables"][0]
        self.assertIn("Kamilla Cardoso", table["title"])
        self.assertEqual(len(table["rows"]), 11)  # 10 games + averages row
        self.assertEqual(result["as_of"], "2026-07-12")
        hits = result["evidence"]["hit_rates_vs_question_lines"][0]
        self.assertEqual(hits["line"], 18.5)
        # pts run 16..25 for the last 10 games (i=2..11): 7 of 10 clear 18.5
        self.assertEqual(hits["over_counts"]["pts"], 7)
        self.assertEqual(len(result["charts"][0]["points"]), 10)

    def _write_nhl_fixtures(self) -> None:
        raw = os.path.join(self.root, "nhl", "raw")
        os.makedirs(raw, exist_ok=True)
        header = "gamePk,date,team,player_id,player,primary_position,role,shots,goals,assists,blocked,timeOnIce,saves,shotsAgainst,decision"
        rows = [
            f"1{i},2026-06-{i + 1:02d},COL,801,Nathan MacKinnon,C,skater,{3 + i % 4},1,1,0,21:3{i % 6},,,"
            for i in range(12)
        ]
        with open(os.path.join(raw, "player_game_stats.csv"), "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n".join(rows) + "\n")

    def test_nhl_last10_game_log(self) -> None:
        self._write_nhl_fixtures()
        with patch.dict(os.environ, {"NHL_DATA_DIR": os.path.join(self.root, "nhl")}):
            result = ask_data.collect_focused_evidence(
                "How is MacKinnon trending?", {"sport": "nhl"}
            )

        self.assertIsNotNone(result)
        self.assertIn("Nathan MacKinnon", result["tables"][0]["title"])
        self.assertEqual(result["evidence"][0]["role"], "skater")
        self.assertEqual(len(result["evidence"][0]["last_games"]), 10)

    def _write_bvp_fixtures(self) -> None:
        bvp_dir = os.path.join(self.root, "mlb", "cache", "statcast", "bvp", "statcast_bvp_file_daily")
        os.makedirs(bvp_dir, exist_ok=True)
        index = {
            "by_date": {
                "2024-05-01": {"694973": {"694192": {"pa": 3, "hr": 1, "hits": 2, "so": 0, "bb": 0, "hbp": 0, "inplay_pa": 3, "inplay_hits": 2}}},
                "2025-08-10": {"694973": {"694192": {"pa": 4, "hr": 0, "hits": 1, "so": 2, "bb": 1, "hbp": 0, "inplay_pa": 3, "inplay_hits": 1}}},
            }
        }
        with open(os.path.join(bvp_dir, "aaa.json"), "w", encoding="utf-8") as f:
            json.dump(index, f)
        # Overlapping second file repeats a date -- must not double count.
        with open(os.path.join(bvp_dir, "bbb.json"), "w", encoding="utf-8") as f:
            json.dump({"by_date": {"2024-05-01": index["by_date"]["2024-05-01"]}}, f)
        # hr_targets needs batter names on the slate.
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        hr_targets = {
            "games": [
                {
                    "game_pk": 823358,
                    "targets": [
                        {
                            "player_name": "Jackson Chourio", "batter_id": 694192,
                            "opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes",
                            "batter_k_rate": 0.21, "batter_hr_rate": 0.045,
                            "batter_inplay_hit_rate": 0.31, "p_hr_1plus": 0.08,
                            "park_hr_mult": 0.95, "weather_hr_mult": 1.02,
                        }
                    ],
                }
            ]
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)

    def test_mlb_bvp_batter_question(self) -> None:
        self._write_bvp_fixtures()
        ask_data._BVP_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does Jackson Chourio fare vs Skenes?", {})

        self.assertIsNotNone(result)
        table = result["tables"][0]
        self.assertIn("Jackson Chourio vs Paul Skenes", table["rows"][0][0])
        # 3 PA + 4 PA, deduped across the overlapping file
        self.assertEqual(table["rows"][0][1], 7)
        self.assertEqual(table["rows"][0][3], 1)  # HR
        self.assertEqual(result["evidence"]["career_bvp"]["pa"], 7)
        self.assertIn("matchup_profile", result["evidence"])

    def test_mlb_bvp_pitcher_question_builds_lineup_table(self) -> None:
        self._write_bvp_fixtures()
        ask_data._BVP_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does the lineup hit against Paul Skenes?", {})

        self.assertIsNotNone(result)
        self.assertIn("today's lineup vs Paul Skenes", result["tables"][0]["title"])
        self.assertEqual(result["evidence"]["lineup_bvp"][0]["batter"], "Jackson Chourio")

    def _write_accuracy_fixtures(self) -> None:
        eval_dir = os.path.join(self.root, "mlb", "eval", "batches", "season_2026_ui_daily_live")
        os.makedirs(eval_dir, exist_ok=True)
        for day, accuracy in (("2026-07-10", 0.6), ("2026-07-11", 0.5), ("2026-07-12", 0.4)):
            payload = {
                "assessment": {
                    "full_game": {
                        "totals": {"games": 15, "mae": 2.87},
                        "moneyline": {"games": 15, "accuracy": accuracy},
                        "pitcher_props_starters": {"so_mae": 2.27},
                    }
                }
            }
            with open(os.path.join(eval_dir, f"sim_vs_actual_{day}.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f)

    def test_mlb_accuracy_trend(self) -> None:
        self._write_accuracy_fixtures()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_accuracy_evidence("How accurate has the sim been lately?", {})

        self.assertIsNotNone(result)
        self.assertEqual(len(result["evidence"]["daily"]), 3)
        self.assertAlmostEqual(result["evidence"]["overall"]["avg_moneyline_accuracy"], 0.5)
        self.assertEqual(result["charts"][0]["points"][-1]["y"], 40.0)

    def test_sections_merge_for_pitcher_question(self) -> None:
        # A Skenes strikeout question should merge game-sim and BvP sections.
        self._write_mlb_fixtures()
        self._write_bvp_fixtures()
        ask_data._BVP_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data.collect_focused_evidence(
                "How many strikeouts for Paul Skenes?", {"sport": "mlb"}
            )

        self.assertIsNotNone(result)
        sources = {section["source"] for section in result["evidence"]}
        self.assertIn("mlb_daily_sim", sources)
        self.assertIn("mlb_bvp", sources)
        self.assertLessEqual(len(result["tables"]), 5)

    def test_route_attaches_visuals_even_without_llm(self) -> None:
        ask_module._RESPONSE_CACHE.clear()
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)
        fake_visuals = {
            "evidence": {"source": "mlb_daily_sim"},
            "tables": [{"title": "T", "columns": ["A"], "rows": [["1"]]}],
            "charts": [],
            "as_of": "2026-07-12",
            "sport": "mlb",
        }

        with patch.dict(os.environ, {"SYNDICATE_ASK_LLM_ENABLED": "false"}):
            with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value={"summary": "s", "recommendations": []}):
                with patch("syndicate.blueprints.ask_the_syndicate.collect_focused_evidence", return_value=fake_visuals):
                    response = app.test_client().post(
                        "/api/syndicate/query",
                        json={"question": "Brewers vs Pirates", "context": {"sport": "mlb"}},
                    )

        payload = response.get_json()
        self.assertEqual(payload["answer_source"], "snapshot")
        self.assertEqual(payload["visuals"]["tables"][0]["title"], "T")
        self.assertEqual(payload["visuals"]["as_of"], "2026-07-12")

    def test_evidence_pack_includes_focused_evidence(self) -> None:
        pack = ask_engine.build_evidence_pack(
            question="Brewers vs Pirates",
            context={"sport": "mlb"},
            intent="matchup_analysis",
            snapshot={"summary": "s"},
            focused_evidence={
                "evidence": {"win_probability": {"away": 0.505}},
                "tables": [{"title": "T", "columns": [], "rows": []}],
                "charts": [{"type": "bar"}],
                "as_of": "2026-07-12",
                "sport": "mlb",
            },
        )
        self.assertEqual(pack["focused_evidence"]["as_of"], "2026-07-12")
        self.assertEqual(pack["focused_evidence"]["data"]["win_probability"]["away"], 0.505)
        self.assertNotIn("charts", pack["focused_evidence"])  # charts stay out of the token budget


class AskTheSyndicateEngineTests(unittest.TestCase):
    def test_llm_disabled_without_api_key(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ASK_LLM_ENABLED": "true"}, clear=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ANTHROPIC_API_KEY", None)
                self.assertFalse(ask_engine.llm_enabled())
                self.assertIsNone(
                    ask_engine.generate_briefing(
                        question="best bets", context={}, intent="market_summary", snapshot={"summary": "x"}
                    )
                )

    def test_llm_disabled_by_flag_even_with_key(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ASK_LLM_ENABLED": "false", "ANTHROPIC_API_KEY": "sk-test"}):
            self.assertFalse(ask_engine.llm_enabled())

    def test_build_evidence_pack_bounds_candidates_and_question(self) -> None:
        snapshot = {
            "selected_date": "2026-07-19",
            "summary": "s" * 5000,
            "board_notes": [f"note {i}" for i in range(25)],
            "top_opportunities": [
                {"selection": f"Pick {i}", "model_probability": 0.6, "summary": "why " * 300}
                for i in range(40)
            ],
        }
        pack = ask_engine.build_evidence_pack(
            question="q" * 2000,
            context={"sport": "mlb", "selected_date": "2026-07-19"},
            intent="market_summary",
            snapshot=snapshot,
        )

        self.assertLessEqual(len(pack["question"]), ask_engine.MAX_QUESTION_CHARS)
        self.assertLessEqual(len(pack["snapshot"]["candidates"]), ask_engine.MAX_CANDIDATES)
        self.assertLessEqual(len(pack["snapshot"]["board_notes"]), 10)
        import json as _json

        self.assertLessEqual(
            len(_json.dumps(pack, default=str)),
            ask_engine.MAX_EVIDENCE_CHARS + 2000,
        )

    def test_rate_limiter_blocks_after_max_calls(self) -> None:
        limiter = ask_engine._RateLimiter(max_calls=2, window_seconds=60.0)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())


if __name__ == "__main__":
    unittest.main()