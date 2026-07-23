from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.features.intelligence import collect_all_recommendations
from syndicate.features.intelligence import run_intelligence_query
from syndicate.features.intelligence.api.response_builder import build_response
from syndicate.features.intelligence_board import build_intelligence_board_contract
from syndicate.blueprints.intelligence import _hydrate_board_response_payload


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
    def test_build_intelligence_board_contract_prefers_structured_board_dictionary(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "board": {
                    "top_overall": [
                        {
                            "sport": "nba",
                            "team": "Boston Celtics",
                            "name": "Jayson Tatum",
                            "market": "points",
                            "line": 28.5,
                            "movement": {"delta": 0.5, "trend": "up"},
                            "edge": 0.071,
                            "is_live": True,
                            "tier": "tier_1",
                            "type": "prop",
                        },
                        {
                            "sport": "mlb",
                            "team": "New York Yankees",
                            "name": "Aaron Judge",
                            "market": "home_runs",
                            "line": 1.5,
                            "movement": {"delta": 0.0, "trend": "flat"},
                            "score": 0.42,
                            "is_live": False,
                            "tier": "tier_2",
                            "type": "prop",
                        },
                    ],
                    "by_sport": {
                        "nba": [{"name": "Jayson Tatum"}],
                        "mlb": [{"name": "Aaron Judge"}],
                    },
                    "live": [{"name": "Jayson Tatum"}],
                    "pregame": [{"name": "Aaron Judge"}],
                    "props": [{"name": "Jayson Tatum"}, {"name": "Aaron Judge"}],
                    "games": [],
                    "parlays": [],
                },
                "recommendations": [],
            }
        )

        self.assertEqual(contract["recommendation_count"], 2)
        self.assertEqual([card["name"] for card in contract["cards"]], ["Jayson Tatum", "Aaron Judge"])
        self.assertEqual(contract["cards"][1]["lane"], "pregame")

    def test_build_intelligence_board_contract_keeps_all_cards_and_exposes_waterfall(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "recommendations": [
                    {
                        "sport": "nba",
                        "team": f"Team {index}",
                        "name": f"Player {index}",
                        "market": "points",
                        "line": 10.5 + index,
                        "movement": {"delta": 0.1, "trend": "flat"},
                        "odds": -110,
                        "is_live": index % 2 == 0,
                    }
                    for index in range(12)
                ],
            }
        )

        self.assertEqual(contract["recommendation_count"], 12)
        self.assertEqual(len(contract["cards"]), 12)
        self.assertGreaterEqual(len(contract["waterfall"]), 5)
        self.assertEqual(contract["waterfall"][0]["step"], "source_response")

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
        self.assertEqual(contract["cards"][0]["movement_summary"], "+0.5 (up)")
        self.assertEqual(contract["cards"][0]["movement"]["delta"], 0.5)
        self.assertEqual(contract["cards"][0]["movement"]["trend"], "up")
        self.assertEqual(contract["cards"][1]["lane"], "pregame")

    def test_build_intelligence_board_contract_exposes_structured_movement_fields(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "recommendations": [
                    {
                        "sport": "mlb",
                        "team": "New York Yankees",
                        "name": "Aaron Judge",
                        "market": "home_runs",
                        "line": 1.5,
                        "movement": {
                            "previous_line": 1.5,
                            "last_line": 1.75,
                            "delta": 0.25,
                            "trend": "up",
                            "percent_change": 16.67,
                            "history": [{"line": 1.5}, {"line": 1.75}],
                        },
                        "edge": 0.08,
                        "is_live": True,
                    }
                ],
            }
        )

        card = contract["cards"][0]
        self.assertIn("movement_summary", contract["card_fields"])
        self.assertEqual(card["movement"]["previous_line"], 1.5)
        self.assertEqual(card["movement"]["last_line"], 1.75)
        self.assertEqual(card["movement"]["delta"], 0.25)
        self.assertEqual(card["movement"]["percent_change"], 16.67)
        self.assertEqual(card["movement"]["history"], [{"line": 1.5}, {"line": 1.75}])
        self.assertEqual(card["movement_summary"], "+0.2 (up)")

    def test_build_intelligence_board_contract_marks_settled_cards_archived(self) -> None:
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
                        "movement": {"delta": 0.0, "trend": "flat"},
                        "expected_value": 0.044,
                        "is_live": False,
                        "settlement": {"status": "settled", "result": "won"},
                    }
                ],
            }
        )

        self.assertEqual(contract["lane_counts"]["archived"], 1)
        self.assertEqual(contract["cards"][0]["lane"], "archived")

    def test_build_response_keeps_final_only_recommendations_visible(self) -> None:
        response = build_response(
            recommendations=[
                {
                    "sport": "nba",
                    "sport_slug": "nba",
                    "team": "Boston Celtics",
                    "name": "Jayson Tatum",
                    "market": "points",
                    "line": 28.5,
                    "score": 200.0,
                    "confidence": "91%",
                    "edge": 0.16,
                    "is_live": False,
                    "settlement": {"status": "settled", "result": "won"},
                }
            ]
        )

        self.assertEqual(len(response["recommendations"]), 1)
        self.assertEqual(response["recommendations"][0]["name"], "Jayson Tatum")
        self.assertEqual(response["top_opportunities"][0]["name"], "Jayson Tatum")
        self.assertEqual(build_intelligence_board_contract(response)["lane_counts"]["archived"], 1)

    def test_build_intelligence_board_contract_keeps_time_like_mlb_props_pregame(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "recommendations": [
                    {
                        "sport": "mlb",
                        "sport_slug": "mlb",
                        "team": "Houston Astros",
                        "player_name": "Kai-Wei Teng",
                        "name": "Kai-Wei Teng Over 15.5 Outs Recorded",
                        "market": "outs recorded",
                        "line": 15.5,
                        "projected": 16.2,
                        "sim_projection": 16.2,
                        "live_projection": "-",
                        "movement": {"trend": "up", "delta": 0.4},
                        "is_live": True,
                        "status_display": "12:10 PM CT",
                        "status_context": "12:10 PM CT",
                        "game_pk": 824255,
                        "matchup": "HOU @ DET",
                    }
                ],
            }
        )

        card = contract["cards"][0]
        self.assertEqual(card["lane"], "pregame")
        self.assertEqual(card["game_pk"], 824255)
        self.assertEqual(card["team"], "Houston Astros")
        self.assertEqual(card["movement_summary"], "+0.4 (up)")
        self.assertEqual(card["movement"]["delta"], 0.4)
        self.assertEqual(card["movement"]["trend"], "up")

    def test_build_intelligence_board_contract_reads_nested_worker_payloads(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "analysis": {
                    "recommendations": [
                        {
                            "sport": "wnba",
                            "team": "Las Vegas Aces",
                            "name": "A'ja Wilson",
                            "market": "points",
                            "line": 24.5,
                            "movement": {"delta": 0.4, "trend": "up"},
                            "expected_value": 0.052,
                            "is_live": True,
                        }
                    ]
                },
                "top_opportunities": [
                    {
                        "sport": "nba",
                        "team": "Boston Celtics",
                        "name": "Jayson Tatum",
                        "market": "points",
                        "line": 28.5,
                        "movement": {"delta": 0.0, "trend": "flat"},
                        "edge": 0.071,
                        "is_live": False,
                    }
                ],
            }
        )

        self.assertEqual(contract["recommendation_count"], 2)
        self.assertEqual(contract["lane_counts"]["live"], 1)
        self.assertEqual(contract["lane_counts"]["pregame"], 1)
        # cards.sort ranks purely by (publication_priority, coverage_score,
        # simulated_edge, confidence) -- no is_live component, deliberately,
        # to avoid the crowd-out bug already fixed twice elsewhere this
        # session (a weak live pick outranking a stronger pregame one).
        # Tatum's edge (0.071) beats Wilson's expected_value-derived edge
        # (0.052), so Boston Celtics is correctly first regardless of which
        # one is live. This assertion was previously backwards -- it never
        # matched cards.sort's actual (and correct) behavior; confirmed via
        # git archaeology that the sort key never had an is_live term.
        self.assertEqual(contract["cards"][0]["team"], "Boston Celtics")
        self.assertEqual(contract["cards"][1]["team"], "Las Vegas Aces")

    def test_build_intelligence_board_contract_emits_trace_bundle(self) -> None:
        contract = build_intelligence_board_contract(
            {
                "headline": "The Syndicate board",
                "recommendations": [
                    {
                        "sport": "mlb",
                        "sport_slug": "mlb",
                        "team": "New York Yankees",
                        "player_name": "Aaron Judge",
                        "name": "Aaron Judge Over 1.5 Hits",
                        "market": "hits",
                        "surface_key": "pregame",
                        "surface_title": "Top props artifact",
                        "selection": "Aaron Judge Over 1.5 Hits",
                        "provenance": {
                            "source": "reports/intelligence/query_state_cache.json",
                            "source_id": "cand_123",
                            "selected_date": "2026-06-25",
                        },
                        "sport_context": {"matchup": "NYY at BOS"},
                    }
                ],
            }
        )

        card = contract["cards"][0]
        self.assertEqual(card["trace_path"], "reports/intelligence/query_state_cache.json")
        self.assertEqual(card["trace"]["source_id"], "cand_123")
        self.assertEqual(card["trace"]["selected_date"], "2026-06-25")
        self.assertEqual(card["trace"]["matchup"], "NYY at BOS")

    def test_build_response_interleaves_active_sports_in_order(self) -> None:
        response = build_response(
            recommendations=[
                {
                    "sport": "mlb",
                    "sport_slug": "mlb",
                    "team": "New York Yankees",
                    "name": "Aaron Judge",
                    "market": "home_runs",
                    "line": 1.5,
                    "score": 200.0,
                    "confidence": "91%",
                    "edge": 0.16,
                    "is_live": True,
                },
                {
                    "sport": "mlb",
                    "sport_slug": "mlb",
                    "team": "Houston Astros",
                    "name": "Yordan Alvarez",
                    "market": "hits",
                    "line": 1.5,
                    "score": 190.0,
                    "confidence": "90%",
                    "edge": 0.14,
                    "is_live": True,
                },
                {
                    "sport": "wnba",
                    "sport_slug": "wnba",
                    "team": "Las Vegas Aces",
                    "name": "A'ja Wilson",
                    "market": "points",
                    "line": 24.5,
                    "score": 180.0,
                    "confidence": "88%",
                    "edge": 0.12,
                    "is_live": False,
                },
                {
                    "sport": "wnba",
                    "sport_slug": "wnba",
                    "team": "Seattle Storm",
                    "name": "Nneka Ogwumike",
                    "market": "rebounds",
                    "line": 9.5,
                    "score": 170.0,
                    "confidence": "87%",
                    "edge": 0.11,
                    "is_live": False,
                },
            ],
            parlays=[],
        )

        ordered_sports = [item.get("sport_slug") for item in response.get("recommendations") or []]
        self.assertEqual(ordered_sports[:4], ["mlb", "wnba", "mlb", "wnba"])

    def test_hydrate_board_response_payload_promotes_nested_recommendations(self) -> None:
        payload = _hydrate_board_response_payload(
            {
                "headline": "The Syndicate brief",
                "top_opportunities": [],
                "board_contract": {"schema": "intelligence_board_v1", "lane_counts": {"live": 0, "pregame": 5, "archived": 0}},
                "response": {
                    "headline": "The Syndicate brief",
                    "recommendations": [
                        {
                            "sport": "mlb",
                            "team": "Tampa Bay Rays",
                            "name": "Tobias Myers",
                            "market": "outs recorded",
                            "line": 7.5,
                            "is_live": False,
                        }
                    ],
                    "parlays": [
                        {
                            "legs": [],
                            "combined_edge": 0.08,
                        }
                    ],
                },
            }
        )

        self.assertEqual(len(payload.get("top_opportunities") or []), 1)
        self.assertEqual((payload.get("top_opportunities") or [])[0].get("name"), "Tobias Myers")
        self.assertEqual(len(payload.get("recommendations") or []), 1)
        self.assertEqual(len(payload.get("parlays") or []), 1)

    def test_hydrate_board_response_payload_synthesizes_board_contract(self) -> None:
        payload = _hydrate_board_response_payload(
            {
                "headline": "The Syndicate brief",
                "recommendations": [
                    {
                        "sport": "nba",
                        "team": "Boston Celtics",
                        "name": "Jayson Tatum",
                        "market": "points",
                        "line": 28.5,
                        "movement": {"delta": 0.2, "trend": "up"},
                        "edge": 0.071,
                        "is_live": False,
                    }
                ],
            }
        )

        board_contract = payload.get("board_contract") or {}
        self.assertEqual(board_contract.get("schema"), "intelligence_board_v1")
        self.assertGreaterEqual(len(board_contract.get("waterfall") or []), 1)
        self.assertEqual((payload.get("boardContract") or {}).get("schema"), "intelligence_board_v1")

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