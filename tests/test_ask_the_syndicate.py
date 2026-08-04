from __future__ import annotations

import csv
import os
import unittest
from pathlib import Path
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

    def test_read_latest_intelligence_state_prefers_canonical_board_state_when_enabled(self) -> None:
        # Plan item 1F: this function used to be a third parallel read
        # cascade (board_snapshot -> worker state), separate from the
        # Board's own _cached_intelligence_response_with_source. Confirms
        # it now tries the canonical board state first, behind the same
        # flag, before falling through to its existing order.
        canonical_response = {"top_opportunities": [{"name": "Canonical Play"}]}
        with patch("syndicate.blueprints.intelligence._load_canonical_board_response", return_value=(canonical_response, "canonical_board_state")):
            with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_board_snapshot_response") as mocked_board_snapshot:
                with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state_response") as mocked_state_response:
                    result = ask_module.read_latest_intelligence_state({"selected_date": "2026-06-10"})

        self.assertEqual(result.get("top_opportunities"), [{"name": "Canonical Play"}])
        mocked_board_snapshot.assert_not_called()
        mocked_state_response.assert_not_called()

    def test_read_latest_intelligence_state_falls_back_when_canonical_disabled(self) -> None:
        # canonical_board_state_enabled defaults off in the real code path,
        # so _load_canonical_board_response itself would return (None,
        # "canonical_disabled") unmocked -- this test just confirms the
        # existing board_snapshot -> worker-state order survives untouched
        # when canonical genuinely has nothing to offer.
        board_snapshot = {"top_opportunities": [{"name": "Board Snapshot Play"}]}
        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_board_snapshot_response", return_value=board_snapshot):
            with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state_response") as mocked_state_response:
                result = ask_module.read_latest_intelligence_state({"selected_date": "2026-06-10"})

        self.assertEqual(result.get("top_opportunities"), [{"name": "Board Snapshot Play"}])
        mocked_state_response.assert_not_called()

    def test_query_route_response_is_strict_json_safe_even_with_nan_upstream(self) -> None:
        # Reported live 2026-08-04: the Ask-the-Syndicate panel on the main
        # board page never returned an answer -- "Unexpected token 'N', ...
        # is not valid JSON" in the browser console. Root cause: a
        # pandas-derived NaN reached this route's response (a board
        # candidate's "line" sub-object, e.g. away_line/home_odds), and
        # Flask's default JSON provider serializes float('nan') as the
        # bareword `NaN` -- valid to Python's own json.loads but not to a
        # browser's strict JSON.parse. syndicate/blueprints/intelligence.py
        # had a call-site-scoped fix for this exact failure mode from
        # 2026-07-31, but this blueprint's own response never routed
        # through it. Must use syndicate.app.create_app() here, not a bare
        # Flask(__name__) like this file's other route tests -- the real
        # fix is the app-level JSON provider (syndicate/app.py's
        # _NaNSafeJSONProvider), which only exists on the real app factory.
        from syndicate.app import create_app

        app = create_app()
        app.testing = True

        fake_result = {
            "query_type": "market_summary",
            "recommendations": [],
            "board_contract": {
                "cards": [
                    {
                        "line": {
                            "away_line": float("nan"),
                            "away_odds": float("nan"),
                            "home_line": float("nan"),
                            "home_odds": float("nan"),
                            "line": 183.5,
                        },
                        "adjusted_edge": float("inf"),
                    }
                ],
            },
            "readiness_gate": {"ok": True},
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={"question": "summarize the board", "context": {}},
            )

        raw = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        # The actual bug: a literal NaN/Infinity token anywhere in the raw
        # body is invalid JSON per spec, even though Python's own (lenient)
        # json.loads and response.get_json() above would both accept it.
        self.assertNotIn("NaN", raw)
        self.assertNotIn("Infinity", raw)
        payload = json.loads(raw)
        self.assertTrue(payload["ok"])

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

    def test_ask_about_this_pick_button_flow_returns_real_bet_analysis(self) -> None:
        # Reproduces the exact request ask_bar.js's "Ask about this pick"
        # button sends (wireAskButtons): a fixed "What's the case for and
        # against <selection>?" question plus a context object naming the
        # clicked card. Reported live 2026-08-04: this always came back as
        # the generic market_summary board recap regardless of which pick
        # was clicked, discarding the attached context entirely.
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        fake_result = {
            "query_type": "player_analysis",
            "recommendations": [
                {
                    "selection": "Colorado Rockies steam move",
                    "model_probability": 0.81,
                    "market_probability": 0.42,
                    "edge": 0.39,
                    "expected_value": 0.85,
                    "confidence": 0.81,
                    "summary": "Sharp money moved the total after the lineup card dropped.",
                    "rationale": "Sharp money moved the total after the lineup card dropped.",
                }
            ],
            "readiness_gate": {"ok": True},
            "local_only": True,
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "What's the case for and against Colorado Rockies steam move?",
                    "context": {"sport": "mlb", "selection": "Colorado Rockies steam move", "candidate_type": "game"},
                },
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        # The actual bug: this used to be "market_summary" every time.
        self.assertEqual(payload["schema_type"], "bet_analysis")
        self.assertEqual(payload["schema"]["selection"], "Colorado Rockies steam move")

    def test_ask_about_this_pick_surfaces_the_same_prose_the_board_renders(self) -> None:
        # Reported live 2026-08-04, same session as the routing fix above:
        # even with the correct pick matched, the real board-quality
        # writeup the candidate already carries (intelligence.html's
        # pickReasoning reads it under "detail" first) never made it into
        # Ask's answer -- this schema's text lookup checked
        # summary/rationale/writeup/why but never "detail", where the
        # prose actually lives.
        app = Flask(__name__)
        app.register_blueprint(ask_the_syndicate_bp)

        fake_result = {
            "query_type": "player_analysis",
            "recommendations": [
                {
                    "selection": "OVER Corbin Carroll",
                    "model_probability": 0.545,
                    "market_probability": 0.105,
                    "edge": 0.153,
                    "expected_value": 4.17,
                    "detail": "The model lands on the over side in 54.5% of sims, while the market is pricing it closer to 10.5%.",
                }
            ],
            "readiness_gate": {"ok": True},
            "local_only": True,
        }

        with patch("syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(fake_result)):
            response = app.test_client().post(
                "/api/syndicate/query",
                json={
                    "question": "What's the case for and against OVER Corbin Carroll?",
                    "context": {"sport": "mlb", "selection": "OVER Corbin Carroll", "candidate_type": "prop"},
                },
            )

        payload = response.get_json()
        self.assertEqual(payload["schema_type"], "bet_analysis")
        self.assertEqual(
            payload["schema"]["recommendation"],
            "The model lands on the over side in 54.5% of sims, while the market is pricing it closer to 10.5%.",
        )
        self.assertEqual(
            payload["schema"]["explanation"]["summary"],
            "The model lands on the over side in 54.5% of sims, while the market is pricing it closer to 10.5%.",
        )

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

    def test_adapter_promotes_question_relevant_recommendation(self) -> None:
        # Reproduces the reported bug: "How do the Brewers look against the
        # Pirates?" returned the board-wide #1 pick (an unrelated WNBA
        # player prop) instead of anything about that game, because the
        # schema always took recommendations[0] with no relevance check.
        snapshot = {
            "query_type": "bet_analysis",
            "recommendations": [
                {"selection": "Courtney Williams OVER 1.5", "market": "assists", "model_probability": 0.7, "confidence": 0.6},
                {"selection": "Milwaukee Brewers ML", "market": "moneyline", "model_probability": 0.55, "confidence": 0.5, "matchup": "Milwaukee Brewers vs Pittsburgh Pirates"},
                {"selection": "Some Other Pick", "market": "total", "model_probability": 0.5, "confidence": 0.5},
            ],
        }

        payload = build_syndicate_query_response(
            question="How do the Brewers look against the Pirates?",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=(), score=0),
            result=dict(snapshot),
        )

        self.assertEqual(payload["schema"]["selection"], "Milwaukee Brewers ML")

    def test_adapter_leaves_order_unchanged_for_generic_question(self) -> None:
        # Regression guard: a question naming no specific subject must keep
        # today's "top board pick" behavior -- this is the desired result
        # for questions like "what's the best bet today".
        snapshot = {
            "query_type": "market_summary",
            "recommendations": [
                {"selection": "Courtney Williams OVER 1.5", "market": "assists", "model_probability": 0.7, "confidence": 0.6},
                {"selection": "Milwaukee Brewers ML", "market": "moneyline", "model_probability": 0.55, "confidence": 0.5},
            ],
        }

        payload = build_syndicate_query_response(
            question="best bets today",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="market_summary", handler_name="handle_market_summary", matched_terms=(), score=0),
            result=dict(snapshot),
        )

        self.assertEqual(payload["schema"]["top_opportunities"][0]["selection"], "Courtney Williams OVER 1.5")

    def test_bet_analysis_suppresses_unrelated_fallback_pick(self) -> None:
        # Regression guard (reported live, 2026-07-31): asking about a
        # specific player who has no matching recommendation on today's
        # board used to silently return an unrelated top-of-board pick
        # (e.g. a Dodgers steam move) as if it answered the question. An
        # explanatory note alone (first fix attempt) still wasn't enough --
        # a bettor skimming "100% model probability" under a player's name
        # could still misread it, so the unrelated pick's data must not be
        # presented at all, only a clear "nothing found" explanation.
        snapshot = {
            "query_type": "bet_analysis",
            "recommendations": [
                {"selection": "Los Angeles Dodgers steam move", "confidence": 0.7, "summary": "Steam move: line moved.", "model_probability": 1.0},
            ],
        }

        payload = build_syndicate_query_response(
            question="antony volpe bet analysis",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=(), score=0),
            result=dict(snapshot),
        )

        schema = payload["schema"]
        self.assertFalse(schema["relevance_matched"])
        self.assertIsNone(schema["selection"])
        self.assertIsNone(schema["model_probability"])
        self.assertIsNone(schema["recommendation"])
        self.assertIn("No board recommendation matches", schema["explanation"]["summary"])
        self.assertIn("antony volpe bet analysis", schema["explanation"]["summary"])

    def test_matchup_analysis_suppresses_unrelated_fallback_pick(self) -> None:
        # Same bug class as bet_analysis, same fix, different schema
        # (reported: "check all sports for the issue" -- relevance_matched
        # was computed but never wired into _matchup_analysis_schema at
        # all, so an unrelated pick's win probability/edges could be shown
        # as if they answered a matchup_analysis-routed question, for any
        # sport).
        snapshot = {
            "query_type": "matchup_analysis",
            "recommendations": [
                {"selection": "Los Angeles Dodgers steam move", "matchup": "LAD @ SF", "confidence": 0.7, "model_probability": 1.0},
            ],
        }

        payload = build_syndicate_query_response(
            question="how does nikola jokic look tonight",
            context={"sport": "nba"},
            decision=RouteDecision(intent="matchup_analysis", handler_name="handle_matchup_analysis", matched_terms=(), score=0),
            result=dict(snapshot),
        )

        schema = payload["schema"]
        self.assertFalse(schema["relevance_matched"])
        self.assertEqual(schema["teams"], [])  # not ["LAD", "SF"] from the unrelated pick's matchup
        self.assertIsNone(schema["win_probability"])
        self.assertEqual(schema["key_edges"], [])
        self.assertIn("No board recommendation matches", schema["simulation_summary"]["summary"])

    def test_market_summary_notes_unrelated_question_but_keeps_opportunities(self) -> None:
        # Different treatment than bet_analysis/matchup_analysis on purpose:
        # a market summary is inherently a plural "here's today's board",
        # not a single framed answer, so the opportunities list stays --
        # but it must say plainly that none of them are about what was
        # asked rather than silently implying they are.
        snapshot = {
            "query_type": "market_summary",
            "summary": "Top edges are concentrated in NBA props.",
            "recommendations": [
                {"selection": "Jayson Tatum Over 28.5", "confidence": 0.6},
            ],
        }

        payload = build_syndicate_query_response(
            question="how does nikola jokic look tonight",
            context={"sport": "nba"},
            decision=RouteDecision(intent="market_summary", handler_name="handle_market_summary", matched_terms=(), score=0),
            result=dict(snapshot),
        )

        schema = payload["schema"]
        self.assertFalse(schema["relevance_matched"])
        self.assertEqual(schema["top_opportunities"][0]["selection"], "Jayson Tatum Over 28.5")  # still shown
        self.assertIn("No board opportunity matches", schema["rationale_summary"]["summary"])
        self.assertIn("Top edges are concentrated in NBA props.", schema["rationale_summary"]["summary"])

    def test_adapter_relevance_reorder_preserves_pipeline_context_on_intelligence_result(self) -> None:
        # IntelligenceResult.to_dict() does not serialize pipeline_context
        # (repr=False field) -- the reorder must extract routing_context
        # before converting result, not after, or this silently disappears.
        result = IntelligenceResult.from_raw(
            {
                "query_type": "bet_analysis",
                "recommendations": [
                    {"name": "Unrelated Pick", "confidence": 0.6},
                    {"name": "Milwaukee Brewers ML", "confidence": 0.5, "matchup": "Milwaukee Brewers vs Pittsburgh Pirates"},
                ],
            },
            pipeline_context={"routing_context": {"question": "How do the Brewers look?", "sport": "mlb"}},
        )

        payload = build_syndicate_query_response(
            question="How do the Brewers look against the Pirates?",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=(), score=0),
            result=result,
        )

        self.assertEqual(payload["schema"]["selection"], "Milwaukee Brewers ML")
        self.assertEqual(payload["routing_context"]["sport"], "mlb")

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

    def test_bet_analysis_supporting_points_falls_back_to_evidence_when_reasoning_steps_empty(self) -> None:
        # reasoning_steps is structurally empty for almost every Ask the
        # Syndicate query (gated behind enable_reasoning_steps=False and a
        # compound-question heuristic single-subject questions never
        # satisfy) -- the frontend used to render a fixed "No supporting
        # steps returned" chip whenever that happened. supporting_points
        # must carry real content from analysis_brief/supporting_evidence/
        # board_notes instead.
        result = IntelligenceResult.from_raw(
            {
                "query_type": "bet_analysis",
                "recommendations": [{"name": "Los Angeles Dodgers steam move", "confidence": 0.7}],
                "analysis_brief": {"kind": "bundle", "title": "Steam move detected"},
                "supporting_evidence": {"kind": "bundle", "summary": "Line moved +425.0 and price moved +425."},
                "board_notes": ["This response was generated from local-only data."],
                "reasoning_steps": [],
            }
        )

        payload = build_syndicate_query_response(
            question="Los Angeles Dodgers steam move",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=(), score=0),
            result=result,
        )

        points = payload["schema"]["explanation"]["supporting_points"]
        self.assertEqual(
            points,
            [
                "Steam move detected",
                "Line moved +425.0 and price moved +425.",
                "This response was generated from local-only data.",
            ],
        )

    def test_bet_analysis_supporting_points_empty_when_nothing_returned(self) -> None:
        # The degenerate case (nothing at all populated) must produce an
        # empty list, not a placeholder string claiming something is missing
        # -- the frontend renders no chip row at all when this is empty.
        result = IntelligenceResult.from_raw(
            {
                "query_type": "bet_analysis",
                "recommendations": [{"name": "Some Pick", "confidence": 0.5}],
            }
        )

        payload = build_syndicate_query_response(
            question="Some Pick",
            context={"sport": "mlb"},
            decision=RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=(), score=0),
            result=result,
        )

        self.assertEqual(payload["schema"]["explanation"]["supporting_points"], [])

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

    def _write_wnba_matchup_fixtures(self) -> None:
        """Team pace/defense CSV + boxscore history with a real CHI-vs-SEA
        prior meeting -- extends _write_wnba_fixtures' CHI/SEA/Kamilla
        Cardoso sim-detail fixture with the two new data sources.
        """
        processed = os.path.join(self.root, "wnba", "processed")
        os.makedirs(processed, exist_ok=True)
        with open(os.path.join(processed, "team_advanced_stats_2026_asof_20260715.csv"), "w", encoding="utf-8") as f:
            f.write("team,pace,off_rtg,def_rtg,efg_pct,tov_pct,orb_pct,ft_rate,fg3a_rate,fg3_pct,ts_pct,ast_per_100\n")
            f.write("CHI,83.3,100.9,99.1,0.459,0.114,0.223,0.387,0.312,0.271,0.517,21.8\n")
            f.write("SEA,81.5,100.0,100.6,0.491,0.160,0.250,0.300,0.280,0.350,0.556,20.0\n")
        header = "game_id,gameId,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,OREB,DREB,PF,FGM,FGA,FG3M,FG3A,FTM,FTA,PLUS_MINUS,STARTER,START_POSITION,source,date"
        rows = [
            # 2026-06-01: CHI @ SEA -- a real prior meeting for the vs-opponent-history table.
            "g1,g1,CHI,4433405,Kamilla Cardoso,25.0,12,7,3,1,0,2,2,4,2,5,10,0,0,2,3,4,True,C,espn,2026-06-01",
            "g1,g1,SEA,999,Other Storm Player,22.0,14,5,4,0,1,1,1,2,1,5,9,1,2,3,4,-4,True,G,espn,2026-06-01",
            # 2026-06-10: CHI @ PHX -- a different opponent, must NOT count as a CHI/SEA meeting.
            "g2,g2,CHI,4433405,Kamilla Cardoso,26.0,10,8,2,0,0,1,2,4,2,4,9,0,0,2,2,2,True,C,espn,2026-06-10",
            "g2,g2,PHX,888,Other Suns Player,24.0,16,4,5,1,0,2,0,3,1,6,11,1,3,3,4,4,True,G,espn,2026-06-10",
        ]
        with open(os.path.join(processed, "boxscores_history.csv"), "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n".join(rows) + "\n")

    def test_wnba_player_question_includes_pace_defense_and_vs_opponent_history(self) -> None:
        # Additional matchup context requested alongside the WNBA feasibility
        # research: team pace/def_rtg (already computed upstream but never
        # surfaced to Ask the Syndicate) and this-season vs-opponent box
        # scores (derived by self-join, since boxscores_history.csv carries
        # no opponent column) -- the two pieces that ARE buildable from data
        # already on disk, unlike a true multi-season BvP-style archive.
        self._write_wnba_fixtures()
        self._write_wnba_matchup_fixtures()
        with patch.dict(os.environ, {"WNBA_BETTING_DATA_ROOT": os.path.join(self.root, "wnba")}):
            result = ask_data.collect_focused_evidence(
                "What is the outlook for Kamilla Cardoso tonight?", {"sport": "wnba"}
            )

        self.assertIsNotNone(result)
        table_titles = [t["title"] for t in result["tables"]]

        pace_table = next(t for t in result["tables"] if "Team pace & defense" in t["title"])
        self.assertIn(["Pace", "83.3", "81.5"], pace_table["rows"])

        vs_opp_table = next(t for t in result["tables"] if "vs Seattle Storm this season" in t["title"])
        self.assertIn("1 meeting", vs_opp_table["title"])
        self.assertEqual(vs_opp_table["rows"][0], ["2026-06-01", "25", "12", "7", "3"])
        self.assertNotIn("2026-06-10", [row[0] for row in vs_opp_table["rows"]])  # the PHX game must not leak in

        sim_section = next(s for s in result["evidence"] if s["source"] == "wnba_sim_detail")
        self.assertEqual(len(sim_section["vs_opponent_this_season"]), 1)
        self.assertEqual(sim_section["team_pace_defense"]["team"]["pace"], 83.3)

    def test_wnba_player_question_notes_no_meetings_yet_this_season(self) -> None:
        self._write_wnba_fixtures()
        self._write_wnba_matchup_fixtures()
        os.remove(os.path.join(self.root, "wnba", "processed", "boxscores_history.csv"))
        header = "game_id,gameId,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,OREB,DREB,PF,FGM,FGA,FG3M,FG3A,FTM,FTA,PLUS_MINUS,STARTER,START_POSITION,source,date"
        rows = [
            "g2,g2,CHI,4433405,Kamilla Cardoso,26.0,10,8,2,0,0,1,2,4,2,4,9,0,0,2,2,2,True,C,espn,2026-06-10",
            "g2,g2,PHX,888,Other Suns Player,24.0,16,4,5,1,0,2,0,3,1,6,11,1,3,3,4,4,True,G,espn,2026-06-10",
        ]
        with open(os.path.join(self.root, "wnba", "processed", "boxscores_history.csv"), "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n".join(rows) + "\n")

        with patch.dict(os.environ, {"WNBA_BETTING_DATA_ROOT": os.path.join(self.root, "wnba")}):
            result = ask_data.collect_focused_evidence(
                "What is the outlook for Kamilla Cardoso tonight?", {"sport": "wnba"}
            )

        self.assertIsNotNone(result)
        vs_opp_table = next(t for t in result["tables"] if "vs Seattle Storm this season" in t["title"])
        self.assertIn("No meetings between these teams yet this season", vs_opp_table["rows"][0][0])

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

    def test_no_sport_hint_still_matches_nba_and_nhl_players(self) -> None:
        # Regression guard ("check all sports for the issue", 2026-07-31):
        # a plain player-name question with no `?sport=` param and no
        # _SPORT_HINTS keyword (e.g. "How's Jokic looking tonight" has no
        # NBA keyword at all) lands in _fetchers_for_sport("") -- that
        # branch used to only cover MLB/WNBA, silently returning nothing
        # for NBA/NHL players even though their fetchers work fine when
        # sport is explicitly set. context={} (no sport key at all) is
        # exactly what a plain typed question with no URL param produces.
        self._write_nhl_fixtures()
        nba_processed = os.path.join(self.root, "nba", "processed")
        os.makedirs(nba_processed, exist_ok=True)
        header = "game_id,gameId,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,OREB,DREB,PF,FGM,FGA,FG3M,FG3A,FTM,FTA,PLUS_MINUS,STARTER,START_POSITION,source,date"
        rows = [
            f"g{i},g{i},DEN,203999,Nikola Jokic,32.0,{25 + i},{11 + (i % 3)},9,1,1,3,3,8,2,10,18,1,3,4,5,8,True,C,espn,2026-07-{i + 1:02d}"
            for i in range(11)
        ]
        with open(os.path.join(nba_processed, "boxscores_history.csv"), "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n".join(rows) + "\n")

        with patch.dict(os.environ, {
            "NBA_BETTING_DATA_ROOT": os.path.join(self.root, "nba"),
            "NHL_DATA_DIR": os.path.join(self.root, "nhl"),
        }):
            nba_result = ask_data.collect_focused_evidence("How's Jokic looking tonight", {})
            nhl_result = ask_data.collect_focused_evidence("How's MacKinnon trending", {})

        self.assertIsNotNone(nba_result)
        self.assertIn("Nikola Jokic", nba_result["tables"][0]["title"])
        self.assertIsNotNone(nhl_result)
        self.assertIn("Nathan MacKinnon", nhl_result["tables"][0]["title"])

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

    def test_mlb_bvp_pitcher_question_with_no_career_history_returns_note_not_none(self) -> None:
        # Regression guard for a young pitcher (e.g. Eury Pérez) whose career
        # BvP sample against today's lineup is empty -- the section used to
        # vanish silently (return None); it must now explain itself and
        # still surface the park/weather context.
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        hr_targets = {
            "games": [
                {
                    "game_pk": 1,
                    "targets": [
                        {
                            "player_name": "Some Batter", "batter_id": 1,
                            "opponent_pitcher_id": 777777, "opponent_pitcher_name": "Rookie Ace",
                            "park_hr_mult": 1.05, "weather_hr_mult": 0.97,
                        }
                    ],
                }
            ]
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)
        ask_data._BVP_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does the lineup hit against Rookie Ace?", {})

        self.assertIsNotNone(result)
        note_table = result["tables"][0]
        self.assertIn("today's lineup vs Rookie Ace", note_table["title"])
        self.assertIn("No recorded plate appearances", note_table["rows"][0][0])
        park_table = next(t for t in result["tables"] if "Park/weather" in t["title"])
        self.assertIn(["Park HR mult", "1.05"], park_table["rows"])
        self.assertIn(["Weather HR mult", "0.97"], park_table["rows"])

    def _write_matchup_fixtures(self) -> None:
        """hr_targets (with team/opponent/game_pk + season rates on both
        sides), a per-game roster snapshot carrying the opponent's bullpen,
        and a daily_summary with hitter_props_likelihood_topn -- covers the
        new bullpen-matchup and per-player simulated-probability tables.
        """
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        hr_targets = {
            "games": [
                {
                    "game_pk": 823358,
                    "targets": [
                        {
                            "player_name": "Jackson Chourio", "batter_id": 694192,
                            "team": "MIL", "opponent": "PIT", "game_pk": 823358,
                            "opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes",
                            "batter_k_rate": 0.21, "batter_bb_rate": 0.08, "batter_hr_rate": 0.045, "batter_inplay_hit_rate": 0.31,
                            "pitcher_k_rate": 0.31, "pitcher_bb_rate": 0.05, "pitcher_hr_rate": 0.02, "pitcher_inplay_hit_rate": 0.29,
                            "p_hr_1plus": 0.08, "park_hr_mult": 0.95, "weather_hr_mult": 1.02,
                        },
                        {
                            "player_name": "Other Brewer", "batter_id": 700001,
                            "team": "MIL", "opponent": "PIT", "game_pk": 823358,
                            "opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes",
                        },
                    ],
                }
            ]
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)

        summary = {
            "date": "2026-07-12",
            "outputs": [
                {
                    "game_pk": 823358, "away": "MIL", "home": "PIT",
                    "hitter_props_likelihood_topn": {
                        "hits_1plus": [
                            {"batter_id": 694192, "name": "Jackson Chourio", "team": "MIL", "p_h_1plus": 0.72, "p_h_1plus_cal": 0.70},
                        ],
                        "total_bases_1plus": [
                            {"batter_id": 694192, "name": "Jackson Chourio", "team": "MIL", "p_tb_1plus": 0.55, "p_tb_1plus_cal": 0.55},
                        ],
                        "doubles_1plus": [
                            {"batter_id": 700001, "name": "Other Brewer", "team": "MIL", "p_2b_1plus": 0.2, "p_2b_1plus_cal": 0.2},
                        ],
                        "runs_1plus": [
                            {"batter_id": 700099, "name": "Bench Regular", "team": "MIL", "p_r_1plus": 0.4, "p_r_1plus_cal": 0.4},
                        ],
                    },
                }
            ],
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)

        snapshot_dir = os.path.join(self.root, "mlb", "daily", "snapshots", "2026-07-12")
        os.makedirs(snapshot_dir, exist_ok=True)
        roster = {
            # "team" is a nested object in real snapshots (2026-06-04,
            # 2026-07-12 mirrored data), not a plain abbreviation string --
            # matching that shape here is what caught _mlb_side_team_abbr
            # originally assuming a flat string during manual verification.
            "away": {
                "team": {"team_id": 158, "name": "Milwaukee Brewers", "abbreviation": "MIL"},
                "bullpen_profiles": [],
                # A full-lineup batter who is NOT one of hr_targets' curated
                # ~30 HR-candidate rows -- covers the fallback path.
                "lineup": [
                    {"id": 700099, "name": "Bench Regular", "pos": "2B", "bat": "R", "throw": "R", "k_rate": 0.18, "bb_rate": 0.09, "hbp_rate": 0.01, "hr_rate": 0.02, "inplay_hit_rate": 0.33},
                ],
            },
            "home": {
                "team": {"team_id": 134, "name": "Pittsburgh Pirates", "abbreviation": "PIT"},
                "bullpen_profiles": [
                    {"id": 555111, "name": "Setup Man", "role": "SU", "leverage_skill": 0.7, "availability_mult": 1.0, "k_rate": 0.3, "bb_rate": 0.08, "hbp_rate": 0.01, "hr_rate": 0.02, "inplay_hit_rate": 0.28},
                    {"id": 555222, "name": "Closer Guy", "role": "CL", "leverage_skill": 0.9, "availability_mult": 0.8, "k_rate": 0.35, "bb_rate": 0.07, "hbp_rate": 0.0, "hr_rate": 0.015, "inplay_hit_rate": 0.25},
                ],
                "starter": {"id": 694973, "name": "Paul Skenes", "role": "SP"},
                "starter_profile": {"id": 694973, "name": "Paul Skenes", "k_rate": 0.31, "bb_rate": 0.05, "hr_rate": 0.02, "inplay_hit_rate": 0.29},
            },
        }
        with open(os.path.join(snapshot_dir, "roster_0_MIL_at_PIT_pk823358_g1.json"), "w", encoding="utf-8") as f:
            json.dump(roster, f)

    def test_mlb_bvp_batter_question_includes_matchup_probabilities_and_bullpen(self) -> None:
        self._write_matchup_fixtures()
        ask_data._BVP_CACHE.clear()
        ask_data._ROSTER_PAYLOAD_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does Jackson Chourio fare vs Skenes?", {})

        self.assertIsNotNone(result)
        table_titles = [t["title"] for t in result["tables"]]

        topn_table = next(t for t in result["tables"] if "simulated matchup probabilities" in t["title"])
        self.assertIn(["Hits 1+", "70.0%"], topn_table["rows"])  # calibrated prob preferred over raw
        self.assertIn(["Total Bases 1+", "55.0%"], topn_table["rows"])
        self.assertEqual(result["evidence"]["topn_probabilities"]["hits_1plus"], 0.70)

        season_table = next(t for t in result["tables"] if "Season tendencies" in t["title"])
        self.assertIn(["Strikeout rate", "21.0%", "31.0%"], season_table["rows"])

        bullpen_table = next(t for t in result["tables"] if "Opposing bullpen" in t["title"])
        # Sorted by leverage_skill desc: Closer Guy (0.9) before Setup Man (0.7).
        self.assertEqual(bullpen_table["rows"][0][0], "Closer Guy (CL)")
        self.assertEqual(bullpen_table["rows"][0][4], "no recorded history")
        bullpen_names = [row["pitcher"] for row in result["evidence"]["opposing_bullpen"]]
        self.assertEqual(bullpen_names, ["Closer Guy", "Setup Man"])
        self.assertNotIn("Other Brewer", table_titles)  # sanity: didn't match the wrong batter

    def test_mlb_bvp_batter_question_resolves_via_full_lineup_when_not_an_hr_target(self) -> None:
        # Regression guard (reported live, 2026-07-31): hr_targets only
        # carries the ~30 HR-candidate batters leaguewide/day, so a batter
        # who isn't one of them (e.g. a real-world report about Anthony
        # Volpe) used to make this entire fetcher return None -- no BvP, no
        # matchup probabilities, no bullpen table, nothing. "Bench Regular"
        # here is deliberately NOT one of the hr_targets rows written by
        # _write_matchup_fixtures, only present in the roster snapshot's
        # full lineup, to prove the fallback resolves it.
        self._write_matchup_fixtures()
        ask_data._BVP_CACHE.clear()
        ask_data._ROSTER_PAYLOAD_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does Bench Regular fare vs Skenes?", {})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["batter"], "Bench Regular")
        self.assertEqual(result["evidence"]["pitcher"], "Paul Skenes")
        table_titles = [t["title"] for t in result["tables"]]
        self.assertTrue(any("BvP" in t for t in table_titles))
        season_table = next(t for t in result["tables"] if "Season tendencies" in t["title"])
        self.assertIn(["Strikeout rate", "18.0%", "31.0%"], season_table["rows"])
        bullpen_table = next(t for t in result["tables"] if "Opposing bullpen" in t["title"])
        self.assertEqual(bullpen_table["rows"][0][0], "Closer Guy (CL)")

    def test_mlb_bvp_pitcher_question_resolves_reliever_via_slate_search(self) -> None:
        # "Closer Guy" is a bullpen arm, not a probable starter -- he never
        # appears as any hr_targets row's opponent_pitcher_name, so the
        # existing starter-only match must fall back to a bullpen-wide search
        # instead of returning None.
        self._write_matchup_fixtures()
        ask_data._BVP_CACHE.clear()
        ask_data._ROSTER_PAYLOAD_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does the lineup hit against Closer Guy?", {})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["pitcher"], "Closer Guy")
        self.assertEqual(result["evidence"]["role"], "CL")
        # The opposing lineup now comes from the full roster snapshot lineup
        # (MIL's "Bench Regular"), not hr_targets' curated HR-candidate rows
        # (Jackson Chourio/Other Brewer) -- confirmed against real mirrored
        # data that hr_targets can be entirely empty for a team even when
        # the opponent's pitcher IS represented there.
        probs_table = next(t for t in result["tables"] if "opposing lineup" in t["title"] and "simulated probabilities" in t["title"])
        self.assertIn("Bench Regular", [row[0] for row in probs_table["rows"]])
        self.assertEqual(result["evidence"]["lineup_topn_probabilities"]["Bench Regular"]["runs_1plus"], 0.4)

    def test_mlb_bvp_pitcher_question_for_named_starter_still_works(self) -> None:
        # Regression guard: a probable-starter lookup must still resolve via
        # the original hr_targets opponent_pitcher_name match, not the new
        # reliever-search fallback.
        self._write_matchup_fixtures()
        ask_data._BVP_CACHE.clear()
        ask_data._ROSTER_PAYLOAD_CACHE.clear()
        with patch.dict(os.environ, {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}):
            result = ask_data._mlb_bvp_evidence("How does the lineup hit against Paul Skenes?", {})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["pitcher"], "Paul Skenes")
        self.assertIsNone(result["evidence"]["role"])

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


class AskTheSyndicateTopCandidatesTests(unittest.TestCase):
    """Covers the ranking-intent leaderboard fetcher and the disambiguation
    fix for "best TB targets today" incorrectly resolving to the Tampa Bay
    Rays' game instead of a Total Bases leaderboard (reported 2026-07-20).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(self.daily_dir, exist_ok=True)

    def _write_daily_summary(self, *, extra_market_rows: dict | None = None) -> None:
        topn = {
            "total_bases_1plus": [
                {"name": "Tommy Edman", "team": "LAD", "p_tb_1plus": 0.788, "p_tb_1plus_cal": 0.788},
                {"name": "Luis Arraez", "team": "SF", "p_tb_1plus": 0.765, "p_tb_1plus_cal": 0.765},
            ],
            "rbi_1plus": [
                {"name": "Josh Rojas", "team": "KC", "p_rbi_1plus": 0.409, "p_rbi_1plus_cal": 0.409},
            ],
            # Mirrors the real bug found in production: every entry across
            # every game was exactly 0.0 for this market on 2026-07-12 --
            # an upstream data gap, not a genuinely rare-but-real signal.
            "hits_runs_rbis_2plus": [
                {"name": "Christian Yelich", "team": "MIL", "p_hrr_2plus": 0.0, "p_hrr_2plus_cal": 0.0},
                {"name": "Jackson Chourio", "team": "MIL", "p_hrr_2plus": 0.0, "p_hrr_2plus_cal": 0.0},
            ],
        }
        if extra_market_rows:
            topn.update(extra_market_rows)
        summary = {
            "date": "2026-07-20",
            "outputs": [
                {
                    "game_pk": 1,
                    "away": "SEA",
                    "home": "TB",
                    "starter_names": {"away": "Someone", "home": "Someone Else"},
                    "full": {"home_win_prob": 0.585, "away_win_prob": 0.415, "away_runs_mean": 3.56, "home_runs_mean": 4.33, "total_runs_dist": {"5": 10}, "run_margin_dist": {"1": 5}},
                    "pitcher_props": {},
                    "hitter_props_likelihood_topn": topn,
                },
                {
                    "game_pk": 2,
                    "away": "AZ",
                    "home": "LAD",
                    "starter_names": {"away": "P1", "home": "P2"},
                    "full": {"home_win_prob": 0.5, "away_win_prob": 0.5, "away_runs_mean": 4.0, "home_runs_mean": 4.0, "total_runs_dist": {"5": 10}, "run_margin_dist": {"1": 5}},
                    "pitcher_props": {},
                    "hitter_props_likelihood_topn": {},
                },
            ],
        }
        with open(os.path.join(self.daily_dir, "daily_summary_2026_07_20.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)

    def _write_hr_targets(self) -> None:
        hr_targets = {
            "games": [
                {
                    "game_pk": 1,
                    "away": "Seattle Mariners",
                    "home": "Tampa Bay Rays",
                    "away_abbr": "SEA",
                    "home_abbr": "TB",
                    "targets": [
                        {
                            "player_name": "Josh Rojas", "team": "KC", "batter_id": 1,
                            "opponent_pitcher_id": 5, "opponent_pitcher_name": "Shane Baz",
                            "hr_target_score": 34.7, "p_hr_1plus": 0.178,
                            "primary_reason": "Favorable park factor",
                        },
                        {
                            "player_name": "Luis Urías", "team": "TOR", "batter_id": 2,
                            "opponent_pitcher_id": 6, "opponent_pitcher_name": "Germán Márquez",
                            "hr_target_score": 32.2, "p_hr_1plus": 0.177,
                        },
                    ],
                }
            ]
        }
        with open(os.path.join(self.daily_dir, "daily_summary_2026_07_20_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)

    def _env(self) -> dict:
        return {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}

    def test_total_bases_ranking_question_returns_leaderboard_not_team_game(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "What are the best TB targets today", {"sport": "mlb"}
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"][0]["source"], "mlb_total_bases_candidates")
        table = result["tables"][0]
        self.assertIn("Total Bases", table["title"])
        self.assertEqual(table["rows"][0][0], "Tommy Edman")
        # Must NOT contain the Tampa Bay Rays game-outlook table -- this is
        # the exact regression: "TB" used to match the Rays' tricode.
        self.assertFalse(any("Tampa Bay" in t["title"] for t in result["tables"]))

    def test_hrr_ranking_question_with_all_zero_data_returns_none(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "What are the best HRR targets today", {"sport": "mlb"}
            )
        # Honest "no usable signal" rather than a table where every
        # candidate ties at a meaningless 0.0%.
        self.assertIsNone(result)

    def test_hrr_ranking_question_with_real_signal_returns_leaderboard(self) -> None:
        self._write_daily_summary(extra_market_rows={
            "hits_runs_rbis_2plus": [
                {"name": "Real Signal Guy", "team": "MIL", "p_hrr_2plus": 0.22, "p_hrr_2plus_cal": 0.22},
            ],
        })
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "best hrr candidates today", {"sport": "mlb"}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["tables"][0]["rows"][0][0], "Real Signal Guy")

    def test_hr_candidates_question_ranks_by_target_score(self) -> None:
        self._write_hr_targets()
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "What are the top HR candidates today", {"sport": "mlb"}
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"][0]["source"], "mlb_hr_targets")
        rows = result["tables"][0]["rows"]
        self.assertEqual(rows[0][0], "Josh Rojas")  # higher hr_target_score (34.7) sorts first
        self.assertEqual(rows[1][0], "Luis Urías")

    def test_rbi_ranking_question_works(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "best rbi targets today", {"sport": "mlb"}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["tables"][0]["rows"][0][0], "Josh Rojas")

    def test_non_ranking_question_mentioning_tb_still_matches_team_game(self) -> None:
        # Regression guard: the ranking-intent gate must not swallow
        # ordinary game questions that happen to contain a short tricode.
        self._write_daily_summary()
        self._write_hr_targets()  # supplies the away/home full-name resolution
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "How do the Rays look tonight, TB is at home", {"sport": "mlb"}
            )
        self.assertIsNotNone(result)
        self.assertIn("Tampa Bay", result["tables"][0]["title"])

    def test_ranking_intent_detection_is_narrow(self) -> None:
        # "best"/"top" alone must not trigger ranking intent -- too many
        # unrelated questions use those words (e.g. market_summary-routed
        # "what's the best bet today" is a different code path entirely).
        self.assertFalse(ask_data._is_ranking_intent_question({"best", "bet", "today"}))
        self.assertFalse(ask_data._is_ranking_intent_question({"top", "pick"}))
        self.assertTrue(ask_data._is_ranking_intent_question({"best", "hr", "targets", "today"}))
        self.assertTrue(ask_data._is_ranking_intent_question({"top", "candidates"}))

    def test_market_detection_hr_and_hrr_do_not_collide(self) -> None:
        hr = ask_data._detect_mlb_market("top hr candidates", {"top", "hr", "candidates"})
        hrr = ask_data._detect_mlb_market("top hrr candidates", {"top", "hrr", "candidates"})
        self.assertEqual(hr["key"], "hr")
        self.assertEqual(hrr["key"], "hrr")

    def test_ranking_intent_question_with_no_market_falls_through_to_none(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            result = ask_data.collect_focused_evidence(
                "who are the best targets today", {"sport": "mlb"}
            )
        self.assertIsNone(result)


class AskTheSyndicateNameDisambiguationTests(unittest.TestCase):
    """Regression coverage for the 2026-08-01 report: asking about "Yordan
    Alvarez" pulled in an unrelated game because a different starting
    pitcher on the slate ("Jose Alvarez") also matched on last name alone.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(self.daily_dir, exist_ok=True)

    def _write_daily_summary(self) -> None:
        # Game 1 sorts first in `outputs` and has a starter whose last name
        # collides with the batter the question is actually about. Game 2
        # is Houston's game but carries no team/starter text the question
        # mentions -- a bare "Yordan Alvarez" question shouldn't resolve to
        # either game via last-name-only matching.
        summary = {
            "date": "2026-08-01",
            "outputs": [
                {
                    "game_pk": 1,
                    "away": "LAA",
                    "home": "SEA",
                    "starter_names": {"away": "Jose Alvarez", "home": "Someone Else"},
                    "full": {"home_win_prob": 0.5, "away_win_prob": 0.5, "away_runs_mean": 4.0, "home_runs_mean": 4.0, "total_runs_dist": {"5": 10}, "run_margin_dist": {"1": 5}},
                    "pitcher_props": {},
                },
                {
                    "game_pk": 2,
                    "away": "HOU",
                    "home": "TEX",
                    "starter_names": {"away": "Framber Valdez", "home": "Someone Else Too"},
                    "full": {"home_win_prob": 0.45, "away_win_prob": 0.55, "away_runs_mean": 4.5, "home_runs_mean": 3.9, "total_runs_dist": {"5": 10}, "run_margin_dist": {"1": 5}},
                    "pitcher_props": {},
                },
            ],
        }
        with open(os.path.join(self.daily_dir, "daily_summary_2026_08_01.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)

    def _env(self) -> dict:
        return {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}

    def test_full_name_question_does_not_match_unrelated_last_name_starter(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            found = ask_data._mlb_match_game("What does Yordan Alvarez look like tonight?", {"sport": "mlb"})
        # Must not lock onto game 1 just because "Alvarez" (Jose Alvarez,
        # the starter) substring-matches -- that game has nothing to do
        # with Yordan Alvarez.
        self.assertIsNone(found)

    def test_full_starter_name_still_matches_its_own_game(self) -> None:
        self._write_daily_summary()
        with patch.dict(os.environ, self._env()):
            found = ask_data._mlb_match_game("How many strikeouts for Jose Alvarez tonight?", {"sport": "mlb"})
        self.assertIsNotNone(found)
        game, _names, _iso = found
        self.assertEqual(game["game_pk"], 1)

    def test_game_score_ranks_full_name_starter_above_last_name_only_starter(self) -> None:
        words = ask_data._question_words("What does Yordan Alvarez look like tonight?")
        game_with_collision = {"away": "LAA", "home": "SEA", "starter_names": {"away": "Jose Alvarez", "home": "Someone Else"}}
        game_unrelated = {"away": "HOU", "home": "TEX", "starter_names": {"away": "Framber Valdez", "home": "Someone Else Too"}}
        collision_score = ask_data._mlb_game_score("What does Yordan Alvarez look like tonight?", words, game_with_collision, {})
        unrelated_score = ask_data._mlb_game_score("What does Yordan Alvarez look like tonight?", words, game_unrelated, {})
        # Last-name-only collision scores low, and neither game should
        # outright win a question about a player who isn't on either slate.
        self.assertLess(collision_score, 90)
        self.assertEqual(unrelated_score, 0)

    def test_sentence_initial_capitalization_is_not_treated_as_a_first_name(self) -> None:
        # Regression guard for a false positive introduced while fixing the
        # Alvarez collision: English capitalizes the first word of a
        # sentence regardless of whether it's a name ("How's Jokic looking
        # tonight?", "Has Cardoso cleared 18.5 points?") -- that must not
        # register as a conflicting "First Last" mention and zero out an
        # otherwise-correct last-name-only match.
        words = ask_data._question_words("How's Jokic looking tonight?")
        self.assertEqual(ask_data._person_matches("Nikola Jokic", words, "How's Jokic looking tonight?"), 1)
        words2 = ask_data._question_words("Has Cardoso cleared 18.5 points recently?")
        self.assertEqual(ask_data._person_matches("Kamilla Cardoso", words2, "Has Cardoso cleared 18.5 points recently?"), 1)

    def test_person_matches_conflict_guard(self) -> None:
        words = ask_data._question_words("What does Yordan Alvarez look like tonight?")
        question = "What does Yordan Alvarez look like tonight?"
        # Full first+last match still scores 2 regardless of the question arg.
        self.assertEqual(ask_data._person_matches("Yordan Alvarez", words, question), 2)
        # A different same-surname person is downgraded from 1 to 0.
        self.assertEqual(ask_data._person_matches("Jose Alvarez", words, question), 0)
        # Without the question arg (back-compat), last-name-only still scores 1.
        self.assertEqual(ask_data._person_matches("Jose Alvarez", words), 1)


class AskTheSyndicateMlbPlayerHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.processed_dir = os.path.join(self.root, "mlb", "processed")
        os.makedirs(self.processed_dir, exist_ok=True)

    def _env(self) -> dict:
        return {"MLB_BETTING_DATA_ROOT": os.path.join(self.root, "mlb")}

    def _write_pitcher_log(self, rows: list[dict]) -> None:
        from syndicate.features.mlb.player_game_log import PITCHER_FIELDS
        from syndicate.features.mlb.player_game_log import PITCHER_LOG_FILENAME

        with open(os.path.join(self.processed_dir, PITCHER_LOG_FILENAME), "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=PITCHER_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in PITCHER_FIELDS})

    def _write_batter_log(self, rows: list[dict]) -> None:
        from syndicate.features.mlb.player_game_log import BATTER_FIELDS
        from syndicate.features.mlb.player_game_log import BATTER_LOG_FILENAME

        with open(os.path.join(self.processed_dir, BATTER_LOG_FILENAME), "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=BATTER_FIELDS)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in BATTER_FIELDS})

    def _write_slate_game(self) -> None:
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        summary = {
            "date": "2026-07-12",
            "outputs": [{
                "game_pk": 823358, "away": "MIL", "home": "PIT",
                "starter_names": {"away": "Jacob Misiorowski", "home": "Paul Skenes"},
                "full": {"home_win_prob": 0.5, "away_win_prob": 0.5, "away_runs_mean": 4.0, "home_runs_mean": 4.0, "total_runs_dist": {"5": 10}, "run_margin_dist": {"1": 5}},
                "pitcher_props": {},
            }],
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f)

    def test_full_name_batter_question_does_not_match_same_surname_pitcher_log(self) -> None:
        # Exact production repro (reported 2026-08-01): a full-name question
        # about a batter ("Yordan Alvarez") must not resolve to an unrelated
        # pitcher in the log who merely shares the surname ("Andrew
        # Alvarez") -- _mlb_player_history_evidence checks the pitcher log
        # first, and a last-name-only match there used to win by default.
        self._write_pitcher_log([
            {"date": "2026-07-20", "game_pk": 1, "player_id": 555, "player_name": "Andrew Alvarez", "team": "COL", "opponent": "COL", "is_starter": 1, "ip": "4.1", "outs": 13, "pitches": 74, "k": 2, "bb": 3, "er": 3, "h": 5, "r": 3, "hr": 1},
        ])
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                result = ask_data._mlb_player_history_evidence("What does Yordan Alvarez look like tonight?", {"sport": "mlb"})
        self.assertIsNone(result)

    def test_full_name_pitcher_question_still_matches_its_own_log(self) -> None:
        self._write_pitcher_log([
            {"date": "2026-07-20", "game_pk": 1, "player_id": 555, "player_name": "Andrew Alvarez", "team": "COL", "opponent": "COL", "is_starter": 1, "ip": "4.1", "outs": 13, "pitches": 74, "k": 2, "bb": 3, "er": 3, "h": 5, "r": 3, "hr": 1},
        ])
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                result = ask_data._mlb_player_history_evidence("How has Andrew Alvarez looked?", {"sport": "mlb"})
        self.assertIsNotNone(result)
        self.assertIn("Andrew Alvarez", result["tables"][0]["title"])

    def test_pitcher_last_n_starts_and_advanced_profile(self) -> None:
        self._write_pitcher_log([
            {"date": "2026-07-01", "game_pk": 1, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "CHC", "is_starter": 1, "ip": "6.0", "outs": 18, "pitches": 95, "k": 9, "bb": 1, "er": 1, "h": 3, "r": 1, "hr": 0},
            {"date": "2026-07-07", "game_pk": 2, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "STL", "is_starter": 1, "ip": "7.0", "outs": 21, "pitches": 101, "k": 10, "bb": 0, "er": 0, "h": 2, "r": 0, "hr": 0},
            # A reliever appearance for a different pitcher must not leak in.
            {"date": "2026-07-08", "game_pk": 3, "player_id": 111111, "player_name": "Someone Else", "team": "PIT", "opponent": "STL", "is_starter": 0, "ip": "1.0", "outs": 3, "pitches": 10, "k": 1, "bb": 0, "er": 0, "h": 0, "r": 0, "hr": 0},
        ])
        profile = {
            "pitcher": {
                "ev_mean_allowed": 86.0, "barrel_rate_allowed": 0.08, "hardhit_rate_allowed": 0.33,
                "xwoba_allowed": 0.29, "hr_mult": 0.9, "k_mult": 1.15, "inplay_mult": 0.95,
                "top_pitch_mix": [{"pitch_type": "FF", "share": 0.55}],
            },
            "generated_at": "2026-07-30T00:00:00",
        }
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=profile):
                result = ask_data._mlb_player_history_evidence("How has Paul Skenes looked lately?", {"sport": "mlb"})

        self.assertIsNotNone(result)
        last_n_table = result["tables"][0]
        self.assertIn("Last 2 starts", last_n_table["title"])
        self.assertIn("Paul Skenes", last_n_table["title"])
        # Most recent start first.
        self.assertEqual(last_n_table["rows"][0][0], "2026-07-07")
        self.assertEqual(last_n_table["rows"][0][3], "10")  # K column
        self.assertEqual(last_n_table["rows"][-1][0], "L2 avg")
        self.assertTrue(any("Actual strikeouts" in c["title"] for c in result["charts"]))
        advanced_table = next(t for t in result["tables"] if "Advanced Statcast profile" in t["title"])
        self.assertIn(["Barrel% allowed", "8.0%"], advanced_table["rows"])
        self.assertIn(["Top pitch mix", "FF 55%"], advanced_table["rows"])

    def test_pitcher_chart_stat_selection(self) -> None:
        # Regression guard: a question about outs must chart outs, not
        # default to strikeouts just because it's an MLB pitcher question.
        self.assertEqual(ask_data._mlb_pitcher_chart_stat({"eury", "perez", "outs"}), ("outs", "Outs", "outs recorded"))
        self.assertEqual(ask_data._mlb_pitcher_chart_stat({"how", "many", "strikeouts"}), ("k", "K", "strikeouts"))
        self.assertEqual(ask_data._mlb_pitcher_chart_stat({"walks", "today"}), ("bb", "BB", "walks"))
        self.assertEqual(ask_data._mlb_pitcher_chart_stat({"pitch", "count"}), ("pitches", "Pitches", "pitch count"))
        # "outs" alongside an explicit K word is still a strikeouts question
        # ("K's recorded via outs" reads as ambiguous English but the K
        # keyword should win since it's the more specific signal).
        self.assertEqual(ask_data._mlb_pitcher_chart_stat({"strikeout", "outs"}), ("k", "K", "strikeouts"))

    def test_pitcher_last_n_starts_charts_outs_when_asked(self) -> None:
        self._write_pitcher_log([
            {"date": "2026-07-01", "game_pk": 1, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "CHC", "is_starter": 1, "ip": "6.0", "outs": 18, "pitches": 95, "k": 9, "bb": 1, "er": 1, "h": 3, "r": 1, "hr": 0},
        ])
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                result = ask_data._mlb_player_history_evidence("Paul Skenes outs", {"sport": "mlb"})

        self.assertIsNotNone(result)
        chart = next(c for c in result["charts"] if "last 1 starts" in c["title"])
        self.assertIn("outs recorded", chart["title"])
        self.assertEqual(chart["y_label"], "Outs")
        self.assertEqual(chart["points"][0]["y"], 18.0)

    def test_opposing_lineup_statcast_table_present_for_matched_pitcher(self) -> None:
        self._write_pitcher_log([
            {"date": "2026-07-01", "game_pk": 1, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "CHC", "is_starter": 1, "ip": "6.0", "outs": 18, "pitches": 95, "k": 9, "bb": 1, "er": 1, "h": 3, "r": 1, "hr": 0},
        ])
        daily_dir = os.path.join(self.root, "mlb", "daily")
        os.makedirs(daily_dir, exist_ok=True)
        hr_targets = {
            "games": [{
                "game_pk": 1,
                "targets": [
                    {"player_name": "Big Bat", "batter_id": 1, "opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes"},
                    {"player_name": "Second Bat", "batter_id": 2, "opponent_pitcher_id": 694973, "opponent_pitcher_name": "Paul Skenes"},
                ],
            }]
        }
        with open(os.path.join(daily_dir, "daily_summary_2026_07_12_hr_targets.json"), "w", encoding="utf-8") as f:
            json.dump(hr_targets, f)

        def fake_profile(*, batter_id=None, pitcher_id=None):
            if batter_id == 1:
                return {"batter": {"xwoba": 0.400, "barrel_rate": 0.15, "hardhit_rate": 0.45, "k_mult": 0.9,
                                    "ev_mean": None, "la_mean": None, "hr_per_bip": None, "pulled_air_rate": None, "hr_mult": None, "inplay_mult": None}}
            if batter_id == 2:
                return {"batter": {"xwoba": 0.250, "barrel_rate": 0.05, "hardhit_rate": 0.20, "k_mult": 1.2,
                                    "ev_mean": None, "la_mean": None, "hr_per_bip": None, "pulled_air_rate": None, "hr_mult": None, "inplay_mult": None}}
            return None

        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", side_effect=fake_profile):
                result = ask_data._mlb_player_history_evidence("How has Paul Skenes looked lately?", {"sport": "mlb"})

        self.assertIsNotNone(result)
        lineup_table = next(t for t in result["tables"] if "Opposing lineup Statcast approach" in t["title"])
        # Higher xwOBA (bigger threat) sorts first.
        self.assertEqual(lineup_table["rows"][0][0], "Big Bat")
        self.assertEqual(lineup_table["rows"][0][1], "0.400")
        self.assertEqual(lineup_table["rows"][1][0], "Second Bat")

    def test_pitcher_history_vs_todays_opponent_when_game_matched(self) -> None:
        self._write_slate_game()
        self._write_pitcher_log([
            {"date": "2026-06-01", "game_pk": 1, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "MIL", "is_starter": 1, "ip": "6.0", "outs": 18, "pitches": 95, "k": 9, "bb": 1, "er": 1, "h": 3, "r": 1, "hr": 0},
            {"date": "2026-07-07", "game_pk": 2, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "STL", "is_starter": 1, "ip": "7.0", "outs": 21, "pitches": 101, "k": 10, "bb": 0, "er": 0, "h": 2, "r": 0, "hr": 0},
        ])
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                result = ask_data._mlb_player_history_evidence("How does Paul Skenes do against the Brewers tonight?", {"sport": "mlb"})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["vs_opponent_starts"], 1)
        vs_table = next(t for t in result["tables"] if "History vs MIL" in t["title"])
        self.assertEqual(vs_table["rows"][0][0], "2026-06-01")

    def test_batter_last_n_games_no_vs_opponent_table(self) -> None:
        self._write_batter_log([
            {"date": "2026-07-01", "game_pk": 1, "player_id": 694192, "player_name": "Jackson Chourio", "team": "MIL", "opponent": "PIT", "ab": 4, "h": 2, "r": 1, "rbi": 1, "hr": 1, "bb": 0, "so": 1, "tb": 6},
            {"date": "2026-07-02", "game_pk": 2, "player_id": 694192, "player_name": "Jackson Chourio", "team": "MIL", "opponent": "PIT", "ab": 3, "h": 0, "r": 0, "rbi": 0, "hr": 0, "bb": 1, "so": 2, "tb": 0},
        ])
        with patch.dict(os.environ, self._env()):
            with patch("syndicate.features.intelligence._mlb_statcast_profile_from_ids", return_value=None):
                result = ask_data._mlb_player_history_evidence("How has Jackson Chourio been hitting?", {"sport": "mlb"})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["role"], "batter")
        self.assertIn("Last 2 games", result["tables"][0]["title"])
        self.assertFalse(any("History vs" in t["title"] for t in result["tables"]))

    def test_no_csv_returns_none(self) -> None:
        with patch.dict(os.environ, self._env()):
            result = ask_data._mlb_player_history_evidence("How has Paul Skenes looked lately?", {"sport": "mlb"})
        self.assertIsNone(result)

    def test_unmatched_player_returns_none(self) -> None:
        self._write_pitcher_log([
            {"date": "2026-07-01", "game_pk": 1, "player_id": 694973, "player_name": "Paul Skenes", "team": "PIT", "opponent": "CHC", "is_starter": 1, "ip": "6.0", "outs": 18, "pitches": 95, "k": 9, "bb": 1, "er": 1, "h": 3, "r": 1, "hr": 0},
        ])
        with patch.dict(os.environ, self._env()):
            result = ask_data._mlb_player_history_evidence("What's the weather like today?", {"sport": "mlb"})
        self.assertIsNone(result)


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


class AskTheSyndicateNcaafEvidenceTests(unittest.TestCase):
    """Real bug found while building this against production data (not just
    unit fixtures): _ncaaf_teams_in_question originally reused _name_matches
    (word-set overlap), which matched "Kansas State vs Iowa State" against
    every "* State" school in the ~680-row registry since they all share
    the word "state". Fixed to require the full school name as a bounded
    substring of the question instead. A second real bug: a >=4-character
    minimum on that substring silently excluded real short school names
    (TCU's school_name is literally "TCU"), so "North Carolina vs TCU"
    resolved only one team. Both are covered below alongside the season-
    resolution fix (sources.default_season() reports a different, stale
    season than the live game slate cards.py is actually on)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.processed = os.path.join(self.root, "ncaaf_source", "source_artifacts", "data", "processed")
        self.data_dir = os.path.join(self.root, "ncaaf_source", "data")
        os.makedirs(self.data_dir, exist_ok=True)

    def _write_csv(self, subdir: str, filename: str, fieldnames: list[str], rows: list[dict]) -> None:
        directory = os.path.join(self.processed, subdir)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, filename), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_registry(self) -> None:
        fields = ["team_id", "canonical_team_name", "abbreviation", "conference", "subdivision", "aliases", "display_name", "conference_short_name", "school_name", "mascot_name", "source_system", "source_snapshot_date"]
        self._write_csv("team_registry", "ncaaf_team_registry.csv", fields, [
            {"team_id": "100", "canonical_team_name": "Kansas State", "abbreviation": "KSU", "conference": "Big 12", "subdivision": "FBS", "aliases": "kansas state|wildcats", "display_name": "Kansas State", "conference_short_name": "", "school_name": "Kansas State", "mascot_name": "Wildcats", "source_system": "cfbd", "source_snapshot_date": "2026-07-01"},
            {"team_id": "101", "canonical_team_name": "Iowa State", "abbreviation": "ISU", "conference": "Big 12", "subdivision": "FBS", "aliases": "iowa state|cyclones", "display_name": "Iowa State", "conference_short_name": "", "school_name": "Iowa State", "mascot_name": "Cyclones", "source_system": "cfbd", "source_snapshot_date": "2026-07-01"},
            {"team_id": "102", "canonical_team_name": "Adams State", "abbreviation": "ADM", "conference": "RMAC", "subdivision": "FCS", "aliases": "adams state", "display_name": "Adams State", "conference_short_name": "", "school_name": "Adams State", "mascot_name": "Grizzlies", "source_system": "cfbd", "source_snapshot_date": "2026-07-01"},
            {"team_id": "103", "canonical_team_name": "TCU", "abbreviation": "TCU", "conference": "Big 12", "subdivision": "FBS", "aliases": "horned frogs|tcu", "display_name": "TCU", "conference_short_name": "", "school_name": "TCU", "mascot_name": "Horned Frogs", "source_system": "cfbd", "source_snapshot_date": "2026-07-01"},
        ])

    def test_teams_in_question_matches_full_phrase_not_shared_words(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            teams = ask_data._ncaaf_teams_in_question("Kansas State vs Iowa State")
            names = {t["school_name"] for t in teams}
        self.assertEqual(names, {"Kansas State", "Iowa State"})
        self.assertNotIn("Adams State", names)

    def test_teams_in_question_matches_short_school_name(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            teams = ask_data._ncaaf_teams_in_question("who wins TCU this week")
        self.assertEqual([t["school_name"] for t in teams], ["TCU"])

    def test_teams_in_question_no_match_returns_empty(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            self.assertEqual(ask_data._ncaaf_teams_in_question("what is the weather like"), [])

    def test_team_profile_evidence_reads_real_fields(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            self._write_csv("returning_production", "ncaaf_returning_production_snapshot.csv",
                ["team_id", "team_name", "season", "returning_starter_estimate", "percent_ppa"],
                [{"team_id": "100", "team_name": "Kansas State", "season": "2025", "returning_starter_estimate": "5.5", "percent_ppa": "0.6"}])
            self._write_csv("coach_continuity", "ncaaf_coach_continuity_snapshot.csv",
                ["team_id", "team_name", "season", "head_coach_name", "coach_changed", "coach_tenure_years", "continuity_score"],
                [{"team_id": "100", "team_name": "Kansas State", "season": "2025", "head_coach_name": "Chris Klieman", "coach_changed": "0", "coach_tenure_years": "6", "continuity_score": "1"}])
            self._write_csv("transfers", "ncaaf_transfer_portal_snapshot.csv",
                ["player_id", "origin_team_id", "destination_team_id", "season"],
                [{"player_id": "1", "origin_team_id": "999", "destination_team_id": "100", "season": "2025"},
                 {"player_id": "2", "origin_team_id": "100", "destination_team_id": "999", "season": "2025"},
                 {"player_id": "3", "origin_team_id": "100", "destination_team_id": "999", "season": "2025"}])
            self._write_csv("roster", "ncaaf_roster_snapshot.csv",
                ["player_id", "team_id", "season", "roster_status"],
                [{"player_id": "1", "team_id": "100", "season": "2025", "roster_status": "active"},
                 {"player_id": "2", "team_id": "100", "season": "2025", "roster_status": "active"},
                 {"player_id": "3", "team_id": "100", "season": "2025", "roster_status": "inactive"}])

            result = ask_data._ncaaf_team_profile_evidence("tell me about Kansas State", {})

        self.assertIsNotNone(result)
        self.assertEqual(result["sport"], "ncaaf")
        evidence = result["evidence"]
        self.assertEqual(evidence["head_coach"], "Chris Klieman")
        self.assertEqual(evidence["returning_starter_estimate"], 5.5)
        self.assertEqual(evidence["transfers_in"], 1)
        self.assertEqual(evidence["transfers_out"], 2)
        self.assertEqual(evidence["transfers_net"], -1)
        self.assertEqual(evidence["active_roster_count"], 2)

    def test_team_profile_evidence_none_when_no_team_named(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            self.assertIsNone(ask_data._ncaaf_team_profile_evidence("what a great day for sports", {}))

    def test_matchup_projection_evidence_pairs_model_and_market(self) -> None:
        from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection
        from syndicate.features.ncaaf.smartsim2_projection import write_projection_artifact

        projection = SmartSimNcaafProjection(
            game_id="g1", season=2026, week=1, home_team="Kansas State", away_team="Iowa State",
            home_score_mean=30.0, away_score_mean=24.0, margin_mean=6.0, total_mean=54.0,
            margin_stdev=13.5, total_stdev=9.0, home_win_rate=0.62, seeds_used=500,
            profile_name="test", rating_source="test", generated_at="2026-07-01T00:00:00Z",
        )
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}), patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks", return_value=(2026, [1]),
        ):
            self._write_registry()
            write_projection_artifact([projection], season=2026, week=1, data_root=Path(self.data_dir))
            lines_payload = [{
                "homeTeam": "Kansas State", "awayTeam": "Iowa State",
                "lines": [{"spread": -6.5, "overUnder": 52.5, "homeMoneyline": -250, "awayMoneyline": 210}],
            }]
            with open(os.path.join(self.data_dir, "cfbd_lines_2026_wk1.json"), "w", encoding="utf-8") as handle:
                json.dump(lines_payload, handle)

            result = ask_data._ncaaf_matchup_projection_evidence("who wins Kansas State vs Iowa State", {})

        self.assertIsNotNone(result)
        evidence = result["evidence"]
        self.assertEqual(evidence["season"], 2026)
        self.assertEqual(evidence["week"], 1)
        self.assertEqual(evidence["model_margin"], 6.0)
        self.assertEqual(evidence["market_margin"], 6.5)
        self.assertEqual(evidence["market_total"], 52.5)

    def test_matchup_projection_evidence_none_with_only_one_team(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}), patch(
            "syndicate.features.ncaaf.cards._resolve_ncaaf_active_season_and_weeks", return_value=(2026, [1]),
        ):
            self._write_registry()
            self.assertIsNone(ask_data._ncaaf_matchup_projection_evidence("how good is Kansas State", {}))

    def test_ats_evidence_covers_losses_and_perspective_flip(self) -> None:
        rows = [
            # Home game: covers (actual 10 > market line 3)
            {"home_team": "Kansas State", "away_team": "Iowa State", "week": 1, "market_margin": 3.0, "actual_margin": 10.0},
            # Away game for Kansas State: market_margin/actual_margin are
            # from the HOME team's perspective (Iowa State here), so
            # Kansas State's own line/actual must be sign-flipped -- market
            # margin 5 (Iowa State favored by 5) flips to Kansas State's
            # line of -5; actual margin -2 (Iowa State won by 2) flips to
            # Kansas State's actual of +2, so Kansas State beat its own
            # line of -5 by covering (2 > -5).
            {"home_team": "Iowa State", "away_team": "Kansas State", "week": 2, "market_margin": 5.0, "actual_margin": -2.0},
            # Home game: loses the cover outright (actual -10 < market line 3)
            {"home_team": "Kansas State", "away_team": "TCU", "week": 3, "market_margin": 3.0, "actual_margin": -10.0},
            # Unrelated game, must be excluded
            {"home_team": "TCU", "away_team": "Iowa State", "week": 3, "market_margin": 1.0, "actual_margin": 1.0},
        ]
        log_path = os.path.join(self.data_dir, "smartsim2_performance_log.jsonl")
        with open(log_path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_registry()
            result = ask_data._ncaaf_ats_evidence("how has Kansas State done against the spread", {})

        self.assertIsNotNone(result)
        self.assertEqual(result["evidence"]["ats_record"], {"covers": 2, "losses": 1, "pushes": 0})
        self.assertEqual(len(result["tables"][0]["rows"]), 3)

    def test_infer_sport_routes_ncaaf_and_leaves_nfl_unaffected(self) -> None:
        self.assertEqual(ask_module._infer_sport("who wins the college football game this week", {}), "ncaaf")
        self.assertEqual(ask_module._infer_sport("cfb picks for saturday", {}), "ncaaf")
        self.assertEqual(ask_module._infer_sport("rushing touchdowns prop", {}), "nfl")

    def test_fetchers_for_sport_registers_ncaaf(self) -> None:
        fetchers = ask_data._fetchers_for_sport("ncaaf", "any question")
        self.assertIn(ask_data._ncaaf_team_profile_evidence, fetchers)
        self.assertIn(ask_data._ncaaf_matchup_projection_evidence, fetchers)
        self.assertIn(ask_data._ncaaf_ats_evidence, fetchers)


class AskTheSyndicateNflEvidenceTests(unittest.TestCase):
    """NFL has no external team-rating API (unlike NCAAF's CFBD) and no
    performance-log equivalent -- these fetchers derive everything from
    real nflverse play-by-play (final scores, for ATS) and the real
    smartsim2_projections_{season}_wk{week}.csv artifact (for the model
    side of a matchup), joined against real_betting_lines_*.json for the
    market side. Fixtures below mirror those three real file shapes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.nfl_root = os.path.join(self.root, "nfl_source")
        os.makedirs(self.nfl_root, exist_ok=True)

    def _write_branding(self) -> None:
        directory = os.path.join(self.nfl_root, "source_artifacts", "data", "processed", "team_branding")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "nfl_team_branding.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["team_id", "abbreviation", "location", "display_name", "primary_color", "secondary_color", "logo_url", "source_snapshot_date"])
            writer.writeheader()
            writer.writerow({"team_id": "1", "abbreviation": "SEA", "location": "Seattle", "display_name": "Seattle Seahawks", "primary_color": "#000", "secondary_color": "#fff", "logo_url": "x", "source_snapshot_date": "2026-01-01"})
            writer.writerow({"team_id": "2", "abbreviation": "ARI", "location": "Arizona", "display_name": "Arizona Cardinals", "primary_color": "#000", "secondary_color": "#fff", "logo_url": "x", "source_snapshot_date": "2026-01-01"})
            writer.writerow({"team_id": "3", "abbreviation": "DEN", "location": "Denver", "display_name": "Denver Broncos", "primary_color": "#000", "secondary_color": "#fff", "logo_url": "x", "source_snapshot_date": "2026-01-01"})

    def _write_real_lines(self, season: int, date: str, lines: dict) -> None:
        path = os.path.join(self.nfl_root, f"real_betting_lines_{season}_{date}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"lines": lines}, handle)

    def _write_pbp(self, season: int, rows: list[dict]) -> None:
        directory = os.path.join(self.nfl_root, "tracking", "nflverse", "pbp")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["season_type", "game_id", "week", "home_team", "away_team", "home_score", "away_score"]
        with open(os.path.join(directory, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_teams_in_question_matches_full_names(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            teams = ask_data._nfl_teams_in_question("Arizona Cardinals at Seattle Seahawks preview")
        self.assertEqual(set(teams), {"Arizona Cardinals", "Seattle Seahawks"})

    def test_teams_in_question_no_match_returns_empty(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self.assertEqual(ask_data._nfl_teams_in_question("what a great day"), [])

    def test_matchup_evidence_pairs_model_and_market(self) -> None:
        from syndicate.features.nfl.smartsim2_projection import SmartSimNflProjection
        from syndicate.features.nfl.smartsim2_projection import write_projection_artifact

        projection = SmartSimNflProjection(
            game_id="2025_10_ARI_SEA", season=2025, week=10, home_team="SEA", away_team="ARI",
            home_score_mean=23.2, away_score_mean=21.9, margin_mean=1.3, total_mean=45.1,
            margin_stdev=14.0, total_stdev=11.4, home_win_rate=0.533, seeds_used=300,
            profile_name="nfl_v1", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )
        # latest_season() now also scans real smartsim2_projections_*.csv
        # (this session's own fix, so a season the real production repo
        # has data for -- e.g. 2026 -- isn't invisible to it) -- pin it to
        # this fixture's own season so the test doesn't depend on
        # whatever real data happens to exist on disk outside the fixture.
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}), patch(
            "syndicate.features.nfl.sources.latest_season", return_value=2025,
        ):
            self._write_branding()
            write_projection_artifact([projection], season=2025, week=10, data_root=Path(self.nfl_root))
            self._write_real_lines(2025, "11_09", {
                "Arizona Cardinals @ Seattle Seahawks": {"moneyline": {"home": -125, "away": 105}, "run_line": {"home": -1.5}, "total_runs": {"line": 45.5}},
            })

            result = ask_data._nfl_matchup_evidence("who wins Arizona Cardinals vs Seattle Seahawks", {})

        self.assertIsNotNone(result)
        evidence = result["evidence"]
        self.assertEqual(evidence["season"], 2025)
        self.assertEqual(evidence["week"], 10)
        self.assertEqual(evidence["model_margin"], 1.3)
        self.assertEqual(evidence["market_spread"], -1.5)
        self.assertEqual(evidence["market_total"], 45.5)

    def test_matchup_evidence_none_with_only_one_team(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self.assertIsNone(ask_data._nfl_matchup_evidence("how good are the Seattle Seahawks", {}))

    def test_ats_evidence_covers_losses_and_perspective_flip(self) -> None:
        # Same real-vs-fixture season isolation as test_matchup_evidence_pairs_model_and_market above.
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}), patch(
            "syndicate.features.nfl.sources.latest_season", return_value=2025,
        ):
            self._write_branding()
            self._write_pbp(2025, [
                # Home game for SEA: covers (actual 10 > line -1.5, wait use simple numbers)
                {"season_type": "REG", "game_id": "2025_01_ARI_SEA", "week": "1", "home_team": "SEA", "away_team": "ARI", "home_score": "24", "away_score": "17"},
                # Away game for SEA (home=DEN): SEA is away
                {"season_type": "REG", "game_id": "2025_02_SEA_DEN", "week": "2", "home_team": "DEN", "away_team": "SEA", "home_score": "10", "away_score": "20"},
                # Unrelated game, must be excluded
                {"season_type": "REG", "game_id": "2025_03_ARI_DEN", "week": "3", "home_team": "DEN", "away_team": "ARI", "home_score": "14", "away_score": "14"},
            ])
            self._write_real_lines(2025, "09_07", {
                "Arizona Cardinals @ Seattle Seahawks": {"run_line": {"home": -3.0}},
            })
            self._write_real_lines(2025, "09_14", {
                "Seattle Seahawks @ Denver Broncos": {"run_line": {"home": 2.0}},
            })

            result = ask_data._nfl_ats_evidence("how has the Seattle Seahawks done against the spread", {})

        self.assertIsNotNone(result)
        # Game 1: SEA home, line -3.0, actual margin 24-17=7 -> 7 > -3 -> cover
        # Game 2: SEA away, home line +2.0 -> SEA's own line = -2.0, actual (away perspective) = 20-10=10 -> 10 > -2 -> cover
        self.assertEqual(result["evidence"]["ats_record"], {"covers": 2, "losses": 0, "pushes": 0})
        self.assertEqual(len(result["tables"][0]["rows"]), 2)

    def test_ats_evidence_none_when_no_team_named(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self.assertIsNone(ask_data._nfl_ats_evidence("what a great day for football", {}))

    def _write_roster(self, season: int, rows: list[dict]) -> None:
        directory = os.path.join(self.nfl_root, "source_artifacts", "data", "processed", "rosters")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["team_abbr", "position_group"]
        with open(os.path.join(directory, f"roster_{season}_snapshot.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_depth(self, season: int, rows: list[dict]) -> None:
        directory = os.path.join(self.nfl_root, "source_artifacts", "data", "processed", "depth")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["team", "depth_rank"]
        with open(os.path.join(directory, f"depth_{season}_snapshot.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def _write_injuries(self, season: int, rows: list[dict]) -> None:
        directory = os.path.join(self.nfl_root, "tracking", "nflverse", "injuries")
        os.makedirs(directory, exist_ok=True)
        fieldnames = ["team", "report_status"]
        with open(os.path.join(directory, f"injuries_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def test_team_profile_evidence_reads_real_roster_depth_and_injuries(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self._write_roster(2026, [
                {"team_abbr": "SEA", "position_group": "WR"},
                {"team_abbr": "SEA", "position_group": "WR"},
                {"team_abbr": "SEA", "position_group": "QB"},
                {"team_abbr": "ARI", "position_group": "QB"},
            ])
            self._write_depth(2026, [
                {"team": "SEA", "depth_rank": "1"},
                {"team": "SEA", "depth_rank": "1"},
                {"team": "SEA", "depth_rank": "2"},
                {"team": "ARI", "depth_rank": "1"},
            ])
            self._write_injuries(2026, [
                {"team": "SEA", "report_status": "Questionable"},
                {"team": "SEA", "report_status": ""},
                {"team": "ARI", "report_status": "Out"},
            ])

            result = ask_data._nfl_team_profile_evidence("Seattle Seahawks team profile", {})

        self.assertIsNotNone(result)
        evidence = result["evidence"]
        self.assertEqual(evidence["team"], "Seattle Seahawks")
        self.assertEqual(evidence["season"], 2026)
        self.assertEqual(evidence["roster_count"], 3)
        self.assertEqual(evidence["depth_chart_starters"], 2)
        self.assertEqual(evidence["current_season_injury_report_count"], 1)
        self.assertEqual(evidence["position_group_counts"].get("WR"), 2)

    def test_team_profile_evidence_none_when_no_team_named(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self.assertIsNone(ask_data._nfl_team_profile_evidence("what a great day for football", {}))

    def test_team_profile_evidence_none_without_any_snapshot(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_DATA_ROOT": self.root}):
            self._write_branding()
            self.assertIsNone(ask_data._nfl_team_profile_evidence("Seattle Seahawks team profile", {}))

    def test_fetchers_for_sport_registers_nfl(self) -> None:
        fetchers = ask_data._fetchers_for_sport("nfl", "any question")
        self.assertIn(ask_data._nfl_matchup_evidence, fetchers)
        self.assertIn(ask_data._nfl_team_profile_evidence, fetchers)
        self.assertIn(ask_data._nfl_ats_evidence, fetchers)


if __name__ == "__main__":
    unittest.main()