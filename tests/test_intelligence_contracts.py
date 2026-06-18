from __future__ import annotations

import unittest

from pipeline.intelligence_models import IntelligenceResult
from syndicate.features.intelligence import _candidate_summary
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.shared.intelligence_contracts import build_intelligence_evaluation_record
from syndicate.features.shared.intelligence_contracts import UniversalCandidate


class UniversalCandidateSchemaTests(unittest.TestCase):
    def test_universal_candidate_normalizes_numeric_odds_and_metadata(self) -> None:
        candidate = UniversalCandidate.from_raw(
            {
                "candidate_id": "cand_123",
                "sport": "MLB",
                "type": "prop",
                "selection": "Bryce Eldridge Over 1.5 Total Bases",
                "market": "total_bases",
                "odds": "+110",
                "projection": "1.8",
                "model_probability": "58",
                "implied_probability": "47.62",
                "edge": "10.38",
                "normalized_edge": "0.1038",
                "confidence": "72",
                "score": "91.5",
                "scoring_mode": "full",
                "source_strength": "0.83",
                "is_live": False,
                "timestamp": "2026-06-18T12:34:56Z",
                "sport_context": {"matchup": "SF at LAA", "line": "1.5", "market_key": "total_bases"},
                "provenance": {"source": "mlb_pipeline"},
                "quality": {"score_inputs_missing": []},
            }
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.candidate_id, "cand_123")
        self.assertEqual(candidate.sport, "MLB")
        self.assertEqual(candidate.type, "prop")
        self.assertEqual(candidate.odds, 110.0)
        self.assertEqual(candidate.projection, 1.8)
        self.assertEqual(candidate.model_probability, 0.58)
        self.assertEqual(candidate.implied_probability, 0.4762)
        self.assertEqual(candidate.edge, 0.1038)
        self.assertEqual(candidate.normalized_edge, 0.1038)
        self.assertEqual(candidate.confidence, 0.72)
        self.assertEqual(candidate.score, 91.5)
        self.assertEqual(candidate.scoring_mode, "full")
        self.assertEqual(candidate.source_strength, 0.83)
        self.assertFalse(candidate.is_live)
        self.assertEqual(candidate.timestamp, "2026-06-18T12:34:56Z")
        self.assertEqual(candidate.sport_context["matchup"], "SF at LAA")
        self.assertEqual(candidate.provenance["source"], "mlb_pipeline")
        self.assertEqual(candidate.quality["score_inputs_missing"], [])

    def test_universal_candidate_supports_minimal_data_without_sport_specific_branching(self) -> None:
        candidate = UniversalCandidate.from_raw(
            {
                "sport": "nba",
                "selection": "Jayson Tatum Over 28.5 Points",
                "market": "points",
                "odds": -105,
                "is_live": True,
                "timestamp": "2026-06-18T15:00:00Z",
                "scoring_mode": "minimal",
            }
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.sport, "nba")
        self.assertEqual(candidate.odds, -105.0)
        self.assertEqual(candidate.source_strength, 0.5)
        self.assertTrue(candidate.is_live)
        self.assertEqual(candidate.timestamp, "2026-06-18T15:00:00Z")
        self.assertEqual(candidate.scoring_mode, "minimal")
        self.assertTrue(candidate.quality["has_market_price"])
        self.assertFalse(candidate.quality["has_model"])


class IntelligenceContractsTest(unittest.TestCase):
    def test_build_intelligence_evaluation_record_normalizes_query_and_response(self) -> None:
        record = build_intelligence_evaluation_record(
            query={
                "question": "preview the Celtics game tonight",
                "selected_date": "2026-06-08",
                "query_type": "game_preview",
                "intent": "game_preview",
                "sport": "nba",
                "preview_subject": "celtics",
                "requested_markets": ["moneyline", "total"],
                "limit": 3,
                "mode": "analysis",
            },
            response={
                "headline": "The Syndicate preview",
                "summary": "Scanned 3 board candidates across 1 sports.",
                "analysis_views": {"focus": "nba_matchups"},
                "recommendations": [
                    {
                        "name": "Boston Celtics",
                        "market": "moneyline",
                        "score": 9.8,
                        "market_fit_score": 7.4,
                    }
                ],
            },
            outcome={"status": "pending"},
        )

        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["query"]["query_type"], "game_preview")
        self.assertEqual(record["query"]["subject"], "celtics")
        self.assertEqual(record["query"]["requested_markets"], ["moneyline", "total"])
        self.assertEqual(record["recommendation_count"], 1)
        self.assertEqual(record["top_recommendation"]["name"], "Boston Celtics")
        self.assertEqual(record["analysis_focus"], "nba_matchups")
        self.assertEqual(record["outcome"]["status"], "pending")

    def test_intelligence_result_build_evaluation_record_uses_pipeline_request(self) -> None:
        result = IntelligenceResult.from_raw(
            {
                "selected_date": "2026-06-08",
                "query_type": "player_analysis",
                "headline": "The Syndicate player brief",
                "summary": "Example summary.",
                "parsed_request": {"question": "analyze Tatum tonight", "selected_date": "2026-06-08"},
                "recommendations": [
                    {
                        "name": "Jayson Tatum Over 28.5 Points",
                        "market": "points",
                        "score": 10.1,
                    }
                ],
                "analysis_views": {"focus": "nba_matchups"},
            },
            pipeline_request={
                "question": "analyze Tatum tonight",
                "selected_date": "2026-06-08",
                "query_type": "player_analysis",
                "player_subject": "Jayson Tatum",
                "sport": "nba",
            },
        )

        record = result.build_evaluation_record(outcome={"status": "final", "actual": "hit"})

        self.assertEqual(record["query"]["question"], "analyze Tatum tonight")
        self.assertEqual(record["query"]["player_subject"], "Jayson Tatum")
        self.assertEqual(record["response"]["recommendation_count"], 1)
        self.assertEqual(record["top_recommendation"]["name"], "Jayson Tatum Over 28.5 Points")
        self.assertEqual(record["outcome"]["actual"], "hit")

    def test_candidate_summary_includes_settlement_metadata(self) -> None:
        summary = _candidate_summary(
            {
                "candidate_type": "prop",
                "sport": "NBA",
                "sport_slug": "nba",
                "matchup": "LAL @ BOS",
                "market": "Points",
                "pick": "Over 28.5",
                "name": "Jayson Tatum",
                "line": 28.5,
                "actual": 31,
                "status_display": "Final",
                "is_final": True,
            }
        )

        self.assertEqual(summary["actual"], "31")
        self.assertEqual(summary["settlement"]["status"], "settled")
        self.assertEqual(summary["settlement"]["result"], "won")

    def test_top_live_opportunities_include_actual_and_settlement(self) -> None:
        opportunities = get_top_live_opportunities(
            [
                {
                    "is_live": True,
                    "sport": "NBA",
                    "sport_slug": "nba",
                    "market": "Points",
                    "name": "Jayson Tatum",
                    "selection": "Over 28.5",
                    "ev_current": 0.12,
                    "line": 28.5,
                    "actual": 19,
                    "status_display": "In Progress",
                }
            ],
            limit=1,
        )

        self.assertEqual(opportunities[0]["actual"], "19")
        self.assertEqual(opportunities[0]["settlement"]["status"], "live")


if __name__ == "__main__":
    unittest.main()