from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import run_intelligence_query


def _sample_overview() -> list[dict[str, object]]:
    return [
        {
            "slug": "nba",
            "name": "NBA",
            "context_label": "2026-06-04",
            "data_health": "healthy",
            "data_warnings": [],
            "home_rails": {
                "pregame": {
                    "title": "Pregame props",
                    "items": [
                        {
                            "name": "Jayson Tatum Over 28.5",
                            "market": "PTS",
                            "pick": "Over 28.5",
                            "matchup": "BOS at NYK",
                            "team_pace_signal": 1.08,
                            "usage_rate_advanced": 1.14,
                            "shot_profile_advanced": 1.06,
                            "minutes_role_advanced": 1.03,
                            "projected": 31.8,
                            "line": 28.5,
                            "odds": "+102",
                            "confidence": "63%",
                            "edge": "+5.4%",
                            "basketball_summary": "Recent form is already clearing this number with a last-five average of 31.2.",
                            "why_explain": "Projected minutes (36.0) sit above his last-10 workload (34.0).",
                            "writeup": "Projection is clearing the number with usage and minutes support.",
                            "display_pills": ["Line 28.5", "Odds +102", "Sim% 63%"],
                            "href": "/nba/prop-ladders?date=2026-06-04",
                        }
                    ],
                },
                "live": {"title": "Top Live Props", "items": []},
                "compact": {"items": []},
            },
            "dashboard_games": [],
        }
    ]


class IntelligenceBoardContractTests(unittest.TestCase):
    def test_build_intelligence_board_contract_splits_live_and_pregame_cards(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "recommendations": [
                    {
                        "sport": "nba",
                        "team": "Boston Celtics",
                        "name": "Jayson Tatum",
                        "market": "points",
                        "line": 28.5,
                        "movement": {"delta": 0.5, "trend": "up"},
                        "edge": 0.071,
                        "is_live": True,
                    },
                    {
                        "sport": "nba",
                        "team": "Los Angeles Lakers",
                        "name": "Anthony Davis",
                        "market": "rebounds",
                        "line": 11.5,
                        "movement": {"delta": 0.0, "trend": "flat"},
                        "expected_value": 0.044,
                        "is_live": False,
                    },
                ],
            }
        )

        self.assertEqual(contract["schema"], "intelligence_board_v1")
        self.assertEqual(contract["recommendation_count"], 2)
        self.assertEqual(contract["lane_counts"]["live"], 1)
        self.assertEqual(contract["lane_counts"]["pregame"], 1)
        self.assertIn("live", contract["active_lanes"])
        self.assertIn("pregame", contract["active_lanes"])
        self.assertEqual(contract["cards"][0]["lane"], "live")
        self.assertEqual(contract["cards"][0]["market"], "points")
        self.assertEqual(contract["cards"][0]["movement"], "+0.5 (up)")
        self.assertEqual(contract["cards"][1]["lane"], "pregame")

    def test_run_intelligence_query_emits_board_contract(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    result = run_intelligence_query("Analyze Jayson Tatum tonight", selected_date="2026-06-04")

        board_contract = result.get("board_contract") or {}
        self.assertEqual(result.get("selected_date"), "2026-06-04")
        self.assertEqual(board_contract.get("schema"), "intelligence_board_v1")
        self.assertEqual((board_contract.get("cards") or [])[0].get("name"), "Jayson Tatum Over 28.5")

    def test_run_intelligence_query_emits_evaluation_bundle(self) -> None:
        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch(
                        "syndicate.features.intelligence.build_intelligence_evaluation_bundle",
                        return_value={"schema_version": 1, "prediction": {"prediction_id": "pred_test"}, "recommendations": [], "artifact_metadata": {}, "metrics": {}, "history": {"history_status": "empty", "sample_size": 0}},
                    ) as mocked_bundle:
                            result = run_intelligence_query(
                                "Analyze Jayson Tatum tonight",
                                selected_date="2026-06-04",
                                force_refresh=True,
                            )

        self.assertEqual(result.get("evaluation_bundle", {}).get("schema_version"), 1)
        self.assertEqual(result.get("recommendation_history", {}).get("history_status"), "empty")
        mocked_bundle.assert_called_once()

    def test_collect_all_recommendations_falls_back_when_edge_filter_drops_everything(self) -> None:
        candidate = {
            "name": "Jayson Tatum Over 28.5",
            "sport": "NBA",
            "sport_slug": "nba",
            "market": "points",
            "pick": "Over 28.5",
            "score": 91.0,
            "odds": "-",
            "edge": "-",
        }

        with patch("syndicate.features.intelligence.build_intelligence_overview", return_value=_sample_overview()):
            with patch("syndicate.features.intelligence._tracked_repo_files", return_value=set()):
                with patch("syndicate.features.intelligence._advanced_input_rows_for_sport", return_value=[]):
                    with patch("syndicate.features.intelligence.collect_candidates", return_value=[candidate]):
                        with patch("syndicate.features.intelligence.filter_candidates", return_value=[]):
                            with patch("syndicate.features.intelligence.rank_candidates", return_value=[]):
                                with patch("syndicate.features.intelligence.rank_global_recommendations", return_value=[candidate]) as mocked_fallback:
                                    recommendations = collect_all_recommendations(selected_date="2026-06-04")

        self.assertEqual(recommendations, [candidate])
        mocked_fallback.assert_called_once()


if __name__ == "__main__":
    unittest.main()