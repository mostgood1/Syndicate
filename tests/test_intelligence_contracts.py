from __future__ import annotations

import unittest

from pipeline.intelligence_models import IntelligenceResult
from syndicate.features.intelligence import _candidate_summary
from syndicate.features.intelligence.scoring.edge import get_top_live_opportunities
from syndicate.features.shared.intelligence_contracts import build_intelligence_evaluation_record


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