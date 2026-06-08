from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pipeline.formatter import format_intelligence_query_response
from pipeline.intelligence_pipeline import run_intelligence_pipeline
from pipeline.evidence_builder import build_evidence_records
from pipeline.intelligence_models import Evidence
from pipeline.intelligence_models import IntelligenceResult
from pipeline.intelligence_models import Insight


class IntelligencePipelineTests(unittest.TestCase):
    def test_pipeline_normalizes_request_and_preserves_structured_response(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "What are the best live bets?",
                "date": "2026-06-04",
                "mode": "live",
                "sport": "nba",
                "limit": "3",
                "timing": "live",
                "include_props": "true",
                "include_games": "false",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Test headline",
                "selected_date": "2026-06-04",
                "recommendations": [{"name": "Darius Garland Over 7.5 Assists", "score": 91.2}],
                "supporting_evidence": {
                    "kind": "bundle",
                    "title": "Supporting evidence",
                    "sections": [{"kind": "metrics", "title": "Top case evidence", "items": [{"label": "Projection", "value": 8.3}]}],
                },
            },
        ) as mocked_query, patch("pipeline.intelligence_pipeline.logger.info") as mocked_log_info:
            result = run_intelligence_pipeline(fake_request)

        self.assertIsInstance(result, IntelligenceResult)
        self.assertEqual(result.pipeline_request["question"], "What are the best live bets?")
        self.assertEqual(result.pipeline_request["selected_date"], "2026-06-04")
        self.assertEqual(result.pipeline_request["limit"], 3)
        self.assertTrue(result.pipeline_request["include_props"])
        self.assertFalse(result.pipeline_request["include_games"])
        self.assertEqual(result.pipeline_stages, ("input_normalization", "context_enrichment", "intelligence_call", "post_processing"))
        self.assertEqual(result.query_type, "live_analysis")
        self.assertEqual(result.headline, "Test headline")
        self.assertTrue(result.recommendations)
        self.assertIsInstance(result.recommendations[0], Insight)
        self.assertIsInstance(result.supporting_evidence, Evidence)
        self.assertTrue(result.evidence)
        self.assertEqual(result.evidence[0].source_type, "recommendation")
        self.assertIsNotNone(result.evidence[0].entity)
        self.assertIsNotNone(result.evidence[0].timestamp)
        self.assertEqual(result.to_dict()["headline"], "Test headline")
        self.assertEqual(result.to_dict()["recommendations"][0]["name"], "Darius Garland Over 7.5 Assists")
        self.assertTrue(result.to_dict()["evidence"])
        self.assertIn("structured_response", result.to_dict())
        self.assertEqual(result.to_dict()["structured_response"]["intent"], "live_analysis")
        self.assertIn("clear_summary", result.to_dict()["structured_response"])
        self.assertTrue(result.to_dict()["structured_response"]["deep_analysis"])
        self.assertIn("final_takeaway", result.to_dict()["structured_response"])
        logged_events = [json.loads(call.args[0]) for call in mocked_log_info.call_args_list]
        self.assertIn("pipeline_query_received", {event["event"] for event in logged_events})
        self.assertIn("pipeline_stage_timing", {event["event"] for event in logged_events})
        mocked_query.assert_called_once_with(
            "What are the best live bets?",
            selected_date="2026-06-04",
            mode="live",
            sport="nba",
            limit=3,
            timing="live",
            include_props=True,
            include_games=False,
            force_refresh=True,
        )

    def test_intelligence_result_round_trips_top_level_fields(self) -> None:
        raw = {
            "selected_date": "2026-06-04",
            "headline": "Top board",
            "summary": "summary",
            "preferences": {"limit": 3},
            "parsed_request": {"chips": ["$100 bankroll"]},
            "recommendations": [{"name": "Play 1", "score": 88.4}],
            "parlays": [{"label": "Parlay 1"}],
            "analysis_views": {"focus": "live"},
            "analysis_brief": {"title": "Brief", "sections": [{"title": "Section A"}]},
            "supporting_evidence": {"title": "Evidence", "sections": [{"kind": "metrics", "title": "Top case evidence"}]},
            "board_notes": ["note 1"],
            "readiness_gate": {"ok": True},
            "local_only": True,
            "extra_field": "kept",
        }

        result = IntelligenceResult.from_raw(raw)

        self.assertEqual(result.selected_date, "2026-06-04")
        self.assertEqual(result.headline, "Top board")
        self.assertEqual(result.recommendations[0].name, "Play 1")
        self.assertEqual(result.supporting_evidence.title, "Evidence")
        self.assertEqual(result.to_dict()["extra_field"], "kept")
        self.assertEqual(result.to_dict()["recommendations"][0]["name"], "Play 1")
        self.assertEqual(result.evidence, ())

    def test_structured_result_keeps_pipeline_metadata(self) -> None:
        raw = {"headline": "Top board"}
        result = IntelligenceResult.from_raw(
            raw,
            pipeline_request={"question": "q"},
            pipeline_context={"enriched": False},
            pipeline_stages=("input_normalization", "context_enrichment"),
        )

        self.assertEqual(result.pipeline_request["question"], "q")
        self.assertFalse(result.pipeline_context["enriched"])
        self.assertEqual(result.pipeline_stages, ("input_normalization", "context_enrichment"))

    def test_risk_queries_generate_structured_response(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "What are the biggest risks and uncertainty factors?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Risk screen",
                "summary": "This board leans slightly positive but is not clean.",
                "board_notes": ["Line movement is modest."],
                "recommendations": [{"name": "Player A Over 18.5 Points", "summary": "Still playable but thin."}],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        self.assertEqual(result.query_type, "risk_evaluation")
        self.assertEqual(structured["intent"], "risk_evaluation")
        self.assertTrue(structured["risks_uncertainty"])
        self.assertTrue(structured["summary"].startswith("This board leans slightly positive but is not clean"))
        self.assertIn("Best takeaway:", structured["recommended_interpretation"])
        self.assertIn("clear_summary", structured)
        self.assertIn("final_takeaway", structured)

    def test_preview_queries_build_game_preview_sections(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "Preview the Celtics game tonight",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Celtics preview",
                "summary": "The board points toward a tight game preview with a few strong prop angles.",
                "recommendations": [
                    {
                        "candidate_type": "game",
                        "name": "BOS at NYK",
                        "matchup": "BOS at NYK",
                        "summary": "The game edge leans Boston in a close matchup.",
                        "score": 97.4,
                    },
                    {
                        "candidate_type": "prop",
                        "name": "Jayson Tatum Over 28.5 Points",
                        "matchup": "BOS at NYK",
                        "summary": "Best single play from the Celtics game.",
                        "score": 95.1,
                    },
                    {
                        "candidate_type": "prop",
                        "name": "Jaylen Brown Over 3.5 Threes",
                        "matchup": "BOS at NYK",
                        "summary": "Secondary prop tied to the same matchup.",
                        "score": 91.0,
                    },
                ],
                "parlays": [
                    {
                        "parlay_type": "same_game",
                        "label": "2-leg same-game parlay",
                        "legs": [
                            {"matchup": "BOS at NYK", "name": "BOS at NYK"},
                            {"matchup": "BOS at NYK", "name": "Jayson Tatum Over 28.5 Points"},
                        ],
                    }
                ],
                "board_notes": ["Line movement is modest."],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        preview = structured["preview"]
        formatted = format_intelligence_query_response(question="Preview the Celtics game tonight", result=result)

        self.assertEqual(result.query_type, "game_preview")
        self.assertEqual(result.pipeline_request["preview_subject"], "Celtics")
        self.assertEqual(preview["matchup"], "BOS at NYK")
        self.assertTrue(preview["game_recommendation_recap"]["plays"])
        self.assertTrue(preview["prop_recommendation_recap"]["plays"])
        self.assertTrue(preview["top_selected_single_plays"])
        self.assertTrue(preview["top_same_game_parlays"])
        self.assertTrue(preview["risks_uncertainty"])
        self.assertTrue(preview["what_to_watch_before_lock"])
        self.assertEqual(formatted["preview"]["matchup"], "BOS at NYK")

    def test_player_analysis_queries_build_player_sections(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "Analyze Jayson Tatum tonight",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Jayson Tatum player analysis",
                "summary": "The board shows a strong scoring and usage outlook.",
                "recommendations": [
                    {
                        "candidate_type": "prop",
                        "name": "Jayson Tatum Over 28.5 Points",
                        "matchup": "BOS at NYK",
                        "summary": "Primary player angle and top prop recap.",
                        "score": 98.1,
                    },
                    {
                        "candidate_type": "game",
                        "name": "BOS at NYK",
                        "matchup": "BOS at NYK",
                        "summary": "Matchup supports Tatum volume.",
                        "score": 94.5,
                    },
                    {
                        "candidate_type": "prop",
                        "name": "Jayson Tatum Over 4.5 Rebounds",
                        "matchup": "BOS at NYK",
                        "summary": "Secondary prop tied to the same game.",
                        "score": 92.0,
                    },
                ],
                "parlays": [
                    {
                        "parlay_type": "same_game",
                        "label": "2-leg same-game parlay",
                        "legs": [
                            {"matchup": "BOS at NYK", "name": "Jayson Tatum Over 28.5 Points"},
                            {"matchup": "BOS at NYK", "name": "Jayson Tatum Over 4.5 Rebounds"},
                        ],
                    }
                ],
                "board_notes": ["Minutes projection is sensitive to blowout risk."],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        player_analysis = structured["player_analysis"]
        formatted = format_intelligence_query_response(question="Analyze Jayson Tatum tonight", result=result)

        self.assertEqual(result.query_type, "player_analysis")
        self.assertEqual(result.pipeline_request["player_subject"], "Jayson Tatum")
        self.assertEqual(player_analysis["player"], "Jayson Tatum")
        self.assertEqual(player_analysis["matchup"], "BOS at NYK")
        self.assertTrue(player_analysis["player_outlook"]["selected_player_play"])
        self.assertTrue(player_analysis["matchup_analysis"]["plays"])
        self.assertTrue(player_analysis["prop_recap"]["plays"])
        self.assertTrue(player_analysis["top_single_plays"])
        self.assertTrue(player_analysis["same_game_parlays"])
        self.assertTrue(player_analysis["risks"])
        self.assertTrue(player_analysis["final_recommendation"])
        self.assertEqual(formatted["player_analysis"]["matchup"], "BOS at NYK")

    def test_bet_evaluation_queries_build_decision_sections(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "Is Jayson Tatum over 28.5 points a good bet?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Jayson Tatum bet evaluation",
                "summary": "The board shows a positive edge on the scoring prop.",
                "recommendations": [
                    {
                        "candidate_type": "prop",
                        "name": "Jayson Tatum Over 28.5 Points",
                        "matchup": "BOS at NYK",
                        "summary": "Top betting angle and the best value on the board.",
                        "basketball_summary": "Recent form is already clearing the number with a last-five average above the line.",
                        "why_explain": "Projected minutes and usage both support the over.",
                        "writeup": "Model confidence and price edge line up.",
                        "confidence": "63%",
                        "edge": "+5.4%",
                        "odds": "+102",
                        "line": 28.5,
                    },
                    {
                        "candidate_type": "game",
                        "name": "BOS at NYK",
                        "matchup": "BOS at NYK",
                        "summary": "Game context supports the same read.",
                        "score": 94.5,
                    },
                ],
                "board_notes": ["Minutes projection is sensitive to blowout risk."],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        bet_evaluation = structured["bet_evaluation"]
        formatted = format_intelligence_query_response(question="Is Jayson Tatum over 28.5 points a good bet?", result=result)

        self.assertEqual(result.query_type, "bet_evaluation")
        self.assertEqual(result.pipeline_request["bet_subject"], "Jayson Tatum over 28.5 points")
        self.assertEqual(bet_evaluation["bet_details"]["selection"], "Jayson Tatum Over 28.5 Points")
        self.assertIn(bet_evaluation["verdict"], {"yes", "lean yes", "pass", "no"})
        self.assertTrue(bet_evaluation["reasoning"])
        self.assertTrue(bet_evaluation["edge_explanation"])
        self.assertTrue(bet_evaluation["risk_factors"])
        self.assertIn("bet_evaluation", formatted)
        self.assertEqual(formatted["bet_evaluation"]["bet_details"]["selection"], "Jayson Tatum Over 28.5 Points")

    def test_vague_queries_include_context_awareness_and_assumptions(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "What should I play?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "General board read",
                "summary": "The board is mixed but playable in a few spots.",
                "recommendations": [{"name": "Best available target", "summary": "The best available angle is a low-risk board read."}],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        context_awareness = structured["context_awareness"]
        self.assertTrue(context_awareness["is_vague"])
        self.assertEqual(context_awareness["confidence"], "low")
        self.assertTrue(context_awareness["assumptions"])
        self.assertTrue(context_awareness["clarifying_questions"])
        self.assertIn("reasoning", context_awareness)
        self.assertIn("Best takeaway:", structured["final_takeaway"])

    def test_vague_queries_return_contextual_assumptions(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "Any good picks?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            return_value={
                "headline": "Vague request handled",
                "summary": "A board-wide view was used because the prompt did not specify a sport or market.",
                "recommendations": [{"name": "Board read", "summary": "The best assumption was to keep the answer broad."}],
            },
        ):
            result = run_intelligence_pipeline(fake_request)

        structured = result.to_dict()["structured_response"]
        context_awareness = structured["context_awareness"]
        self.assertTrue(context_awareness["is_vague"])
        self.assertGreaterEqual(len(context_awareness["assumptions"]), 1)
        self.assertGreaterEqual(len(context_awareness["clarifying_questions"]), 1)
        self.assertEqual(context_awareness["confidence"], "low")
        self.assertIn("board-wide", structured["summary"])

    def test_pipeline_requires_question(self) -> None:
        fake_request = SimpleNamespace(get_json=lambda silent=True: {"date": "2026-06-04"}, form={})

        with self.assertRaises(ValueError):
            run_intelligence_pipeline(fake_request)

    def test_pipeline_retries_once_before_succeeding(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "What are the best live bets?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch(
            "pipeline.intelligence_pipeline.run_intelligence_query",
            side_effect=[RuntimeError("temporary failure"), {"headline": "Recovered headline"}],
        ) as mocked_query:
            result = run_intelligence_pipeline(fake_request)

        self.assertEqual(result.headline, "Recovered headline")
        self.assertEqual(mocked_query.call_count, 2)

    def test_pipeline_returns_partial_result_after_retry_failure(self) -> None:
        fake_request = SimpleNamespace(
            get_json=lambda silent=True: {
                "question": "What are the best live bets?",
                "date": "2026-06-04",
            },
            form={},
        )

        with patch("pipeline.intelligence_pipeline.run_intelligence_query", side_effect=RuntimeError("upstream down")) as mocked_query:
            with patch("pipeline.intelligence_pipeline.logger.info") as mocked_log_info:
                result = run_intelligence_pipeline(fake_request)

        self.assertEqual(mocked_query.call_count, 2)
        self.assertTrue(result.to_dict().get("pipeline_partial"))
        self.assertEqual(result.to_dict().get("pipeline_error"), "upstream down")
        self.assertEqual(result.headline, "Intelligence temporarily unavailable")
        self.assertEqual(result.pipeline_request["question"], "What are the best live bets?")
        self.assertTrue(result.recommendations == ())
        self.assertTrue(result.parlays == ())
        logged_events = [json.loads(call.args[0]) for call in mocked_log_info.call_args_list]
        self.assertIn("pipeline_error", {event["event"] for event in logged_events})

    def test_evidence_builder_extracts_generic_records(self) -> None:
        raw = {
            "selected_date": "2026-06-04",
            "recommendations": [
                {"name": "Player A Over 18.5 Points", "market": "PTS", "projected": 20.1, "why": "Usage plus minutes support the over.", "timestamp": "2026-06-04T12:00:00Z"},
            ],
            "analysis_brief": {
                "title": "Brief",
                "sections": [
                    {"title": "Data inputs", "items": [{"label": "Usage", "value": 0.31}]},
                ],
            },
        }

        evidence = build_evidence_records(raw, selected_date="2026-06-04")

        self.assertTrue(evidence)
        self.assertEqual(evidence[0].source_type, "recommendation")
        self.assertEqual(evidence[0].entity, "Player A Over 18.5 Points")
        self.assertEqual(evidence[0].metric, "PTS")
        self.assertEqual(evidence[0].value, 20.1)
        self.assertEqual(evidence[0].context, "Usage plus minutes support the over.")
        self.assertEqual(evidence[0].timestamp, "2026-06-04T12:00:00Z")


if __name__ == "__main__":
    unittest.main()