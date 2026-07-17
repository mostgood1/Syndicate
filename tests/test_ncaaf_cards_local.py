from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.ncaaf import cards as ncaaf_cards_route
from syndicate.features.ncaaf.game_detail import build_game_detail_page_context
from syndicate.features.ncaaf.cards import build_cards_page_context
from syndicate.features.ncaaf.cards import build_smartsim_cards_page_context
from syndicate.features.ncaaf.cards import _normalize_probability


class NcaafCardsLocalTests(unittest.TestCase):
    def test_normalize_probability_handles_percent_and_fraction_inputs(self) -> None:
        self.assertEqual(_normalize_probability("68.5%"), 0.685)
        self.assertEqual(_normalize_probability(71), 0.71)
        self.assertEqual(_normalize_probability(0.71), 0.71)

    def test_smartsim_cards_runtime_uses_prediction_rows(self) -> None:
        runtime_rows = [
            {
                "week": "1",
                "home_team": "Sam Houston",
                "away_team": "UNLV",
                "predicted_home_points": "34.2",
                "predicted_away_points": "24.1",
                "predicted_total_points": "58.3",
                "predicted_win_margin": "10.1",
                "model_home_win_prob": "0.731",
                "start_date": "2025-09-01T19:00:00Z",
                "venue": "Test Stadium",
            }
        ]

        with patch("syndicate.features.ncaaf.cards.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.cards._prediction_weeks", return_value=[1]
        ), patch("syndicate.features.ncaaf.cards._prediction_rows", return_value=tuple(runtime_rows)), patch(
            "syndicate.features.ncaaf.cards._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            context = build_smartsim_cards_page_context(1)

        self.assertEqual(context["source_title"], "NCAAF Enhanced Totals Engine cards runtime")
        self.assertEqual(context["board_contract"]["source_kind"], "smartsim_runtime")
        self.assertEqual(context["games"][0]["detail"], "Enhanced Totals Engine")
        self.assertIn("Enhanced Totals Engine projects Sam Houston", context["games"][0]["summary"])
        self.assertEqual(context["games"][0]["ncaaf_card"]["scoreboard"]["home_points"], "34.2")
        self.assertEqual(context["games"][0]["ncaaf_card"]["scoreboard"]["away_points"], "24.1")
        self.assertIn("team_context", context["games"][0]["ncaaf_card"])
        self.assertEqual(len(context["games"][0]["ncaaf_card"]["team_context"]["items"]), 4)
        self.assertEqual(
            [item["label"] for item in context["games"][0]["ncaaf_card"]["team_context"]["items"]],
            ["Returning Production", "Portal Impact", "Coach Continuity", "Roster Experience"],
        )
        self.assertIn("matchup_context", context["games"][0]["ncaaf_card"])
        self.assertEqual(
            [item["label"] for item in context["games"][0]["ncaaf_card"]["matchup_context"]["items"]],
            ["Conference Context", "Returning Production", "Portal Impact", "Coach Continuity", "Roster Comparison"],
        )
        self.assertIn("smartsim_reasons", context["games"][0]["ncaaf_card"])
        self.assertTrue(context["games"][0]["ncaaf_card"]["smartsim_reasons"]["summary"].startswith("Enhanced Totals Engine favors"))
        self.assertIsNotNone(context["games"][0]["ncaaf_card"]["summary"]["coverage_score"])
        self.assertIn(context["games"][0]["ncaaf_card"]["summary"]["publication_status"], {"publishable", "suppressed"})
        self.assertIn(context["games"][0]["ncaaf_card"]["summary"]["publication_priority"], {0, 1, 2, 3})

    def test_smartsim_cards_runtime_skips_incomplete_projection_rows(self) -> None:
        runtime_rows = [
            {
                "week": "1",
                "home_team": "Sam Houston",
                "away_team": "UNLV",
                "predicted_home_points": "34.2",
                "predicted_away_points": "24.1",
                "predicted_total_points": "58.3",
                "predicted_win_margin": "10.1",
                "model_home_win_prob": "0.731",
                "start_date": "2025-09-01T19:00:00Z",
                "venue": "Test Stadium",
            },
            {
                "week": "1",
                "home_team": "Placeholder Home",
                "away_team": "Placeholder Away",
                "predicted_home_points": "",
                "predicted_away_points": "",
                "predicted_total_points": "",
                "predicted_win_margin": "",
                "model_home_win_prob": "0.923",
                "start_date": "2025-09-01T19:00:00Z",
                "venue": "Placeholder Stadium",
            },
        ]

        with patch("syndicate.features.ncaaf.cards.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.cards._prediction_weeks", return_value=[1]
        ), patch("syndicate.features.ncaaf.cards._prediction_rows", return_value=tuple(runtime_rows)), patch(
            "syndicate.features.ncaaf.cards._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")
        ):
            context = build_smartsim_cards_page_context(1)

        self.assertEqual(len(context["games"]), 1)
        self.assertEqual(context["games"][0]["home"]["name"], "Sam Houston")

    def test_smartsim_cards_runtime_falls_back_to_summaries(self) -> None:
        fallback_context = {"date": "2025 Week 1", "games": [], "source_title": "Fallback"}

        with patch("syndicate.features.ncaaf.cards._prediction_weeks", return_value=[]), patch(
            "syndicate.features.ncaaf.cards.build_cards_page_context", return_value=fallback_context
        ):
            context = build_smartsim_cards_page_context(1)

        self.assertEqual(context, fallback_context)

    def test_cards_route_uses_smartsim_runtime_builder(self) -> None:
        app = create_app()
        runtime_context = {"date": "2025 Week 1", "games": [], "source_title": "Runtime"}

        with app.test_request_context("/ncaaf/cards?week=1"), patch(
            "syndicate.blueprints.ncaaf.build_smartsim_cards_page_context", return_value=runtime_context
        ) as build_context, patch("syndicate.blueprints.ncaaf.render_template", return_value="rendered") as render_template:
            response = ncaaf_cards_route()

        self.assertEqual(response, "rendered")
        build_context.assert_called_once()
        render_template.assert_called_once()
        self.assertEqual(render_template.call_args.kwargs["source_title"], "Runtime")

    def test_week1_publishable_game_exposes_smartsim_metadata(self) -> None:
        summary = {
            "results": [
                {
                    "home_team": "Sam Houston",
                    "away_team": "UNLV",
                    "market": "ML",
                    "side": "Away",
                    "provider": "DraftKings",
                    "price_american": 295,
                    "model_prob": 0.8309,
                    "implied_prob": 0.2532,
                    "edge": 2.2819,
                    "kelly_f": 0.1,
                    "stake": 50.0,
                }
            ]
        }

        with patch("syndicate.features.ncaaf.cards.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.cards.available_weeks", return_value=[1]
        ), patch("syndicate.features.ncaaf.cards.summary_path", return_value="week_1.json"), patch(
            "syndicate.features.ncaaf.cards.load_json", return_value=summary
        ):
            context = build_cards_page_context(1)

        game = context["games"][0]
        self.assertEqual(game["card_variant"], "ncaaf_main")
        self.assertIn("ncaaf_card", game)
        self.assertTrue(game["ncaaf_card"]["summary"]["publication_ready"])
        self.assertEqual(game["coverage_score"], 1.0)
        self.assertEqual(game["coverage_tier"], "A")
        self.assertEqual(game["publication_status"], "publishable")
        self.assertEqual(game["publication_priority"], 3)
        self.assertIn("context_sections", game["ncaaf_card"])
        self.assertEqual(len(game["ncaaf_card"]["context_sections"]), 4)

    def test_week1_suppressed_game_exposes_smartsim_metadata(self) -> None:
        summary = {
            "results": [
                {
                    "home_team": "Army",
                    "away_team": "Tarleton State",
                    "market": "ML",
                    "side": "Away",
                    "provider": "DraftKings",
                    "price_american": 295,
                    "model_prob": 0.5,
                    "implied_prob": 0.4,
                    "edge": 0.25,
                    "kelly_f": 0.05,
                    "stake": 10.0,
                }
            ]
        }

        with patch("syndicate.features.ncaaf.cards.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.cards.available_weeks", return_value=[1]
        ), patch("syndicate.features.ncaaf.cards.summary_path", return_value="week_1.json"), patch(
            "syndicate.features.ncaaf.cards.load_json", return_value=summary
        ):
            context = build_cards_page_context(1)

        game = context["games"][0]
        self.assertEqual(game["card_variant"], "ncaaf_main")
        self.assertIn("ncaaf_card", game)
        self.assertFalse(game["ncaaf_card"]["summary"]["publication_ready"])
        self.assertEqual(game["coverage_score"], 0.675)
        self.assertEqual(game["coverage_tier"], "C")
        self.assertEqual(game["publication_status"], "suppressed")
        self.assertEqual(game["publication_priority"], 1)

    def test_game_detail_page_uses_smartsim_hub_metadata(self) -> None:
        runtime_context = {
            "date": "2025 Week 1",
            "control_value": "1",
            "prev_date": "1",
            "next_date": "1",
            "source_path": "/tmp/predicted_totals.csv",
            "games": [
                {
                    "gamePk": "1_UNLV_Sam_Houston",
                    "away": {"abbr": "UNLV", "name": "UNLV"},
                    "home": {"abbr": "SHU", "name": "Sam Houston"},
                    "status": "Week 1",
                    "detail": "SmartSim runtime",
                    "summary": "SmartSim projects Sam Houston 34.2 - 24.1 UNLV with a total of 58.3 and a home win probability of 73.1%.",
                    "href": "/ncaaf/game/1_UNLV_Sam_Houston?week=1",
                    "href_label": "Open NCAAF game detail",
                    "ncaaf_card": {
                        "scoreboard": {
                            "home_points": "34.2",
                            "away_points": "24.1",
                            "total_points": "58.3",
                            "spread_label": "Sam Houston by 10.1",
                            "win_probability": "73.1%",
                            "source_label": "Enhanced Totals Engine",
                            "kickoff": "2025-09-01T19:00:00Z",
                            "venue": "Test Stadium",
                        },
                        "summary": {"ready_label": "Publication blocked"},
                        "smartsim_reasons": {
                            "lead": "Enhanced Totals Engine favors Sam Houston because of higher returning production, stronger roster experience, and positive portal balance.",
                            "summary": "SmartSim favors Sam Houston because of higher returning production, stronger roster experience, and positive portal balance.",
                            "favored_team": "Sam Houston",
                            "items": [
                                {"label": "Returning Production", "value": "Higher returning production", "detail": "Sam Houston 0.650 | UNLV 0.420", "tone": "positive"},
                                {"label": "Roster Experience", "value": "Stronger roster experience", "detail": "Sam Houston experience 0.701 | UNLV experience 0.662", "tone": "positive"},
                                {"label": "Portal Activity", "value": "Positive portal balance", "detail": "Sam Houston net 1 | UNLV net -1", "tone": "positive"},
                                {"label": "Coach Continuity", "value": "More stable coach continuity", "detail": "Sam Houston 0.820 | UNLV 0.810", "tone": "positive"},
                                {"label": "Conference / Subdivision Context", "value": "Comparable conference / subdivision context", "detail": "Sam Houston AAC / FBS | UNLV AAC / FBS", "tone": "neutral"},
                            ],
                        },
                        "matchup_context": {
                            "items": [
                                {"label": "Conference Context", "value": "AAC vs AAC", "detail": "Both teams are in the AAC", "tone": "neutral"},
                                {"label": "Returning Production", "value": "Sam Houston +12%", "detail": "Sam Houston 0.650% | UNLV 0.420%", "tone": "positive"},
                                {"label": "Portal Impact", "value": "Sam Houston Advantage", "detail": "Sam Houston 1 | UNLV -1", "tone": "positive"},
                                {"label": "Coach Continuity", "value": "Even", "detail": "Sam Houston 0.820 | UNLV 0.810", "tone": "neutral"},
                                {"label": "Roster Comparison", "value": "Sam Houston Advantage", "detail": "Roster size 83 vs 79 | Experience Sam Houston 0.701 | UNLV 0.662", "tone": "positive"},
                            ]
                        },
                        "context_sections": [
                            {
                                "label": "Returned production",
                                "home": "1.0 starters | PPA 0.650 | Usage 0.620",
                                "away": "0.0 starters | PPA 0.420 | Usage 0.300",
                                "detail": "Starter estimate, production share, and usage from the published snapshot.",
                            }
                        ],
                    },
                }
            ],
        }

        with patch("syndicate.features.ncaaf.game_detail.build_smartsim_cards_page_context", return_value=runtime_context):
            context = build_game_detail_page_context(1, "1_UNLV_Sam_Houston")

        self.assertEqual(context["board_header_title"], "UNLV @ Sam Houston")
        self.assertTrue(context["show_source_summary"])
        self.assertTrue(context["show_matchup_context"])
        self.assertEqual(context["source_title"], "NCAAF Enhanced Totals Engine game hub")
        self.assertEqual(context["header_stats"][1]["value"], "34.2 - 24.1")
        self.assertEqual(context["cards_header_meta"], "NCAAF Game Hub | Enhanced Totals Engine")
        self.assertTrue(context["show_smartsim_reasons"])
        self.assertTrue(context["smartsim_reasons"]["lead"].startswith("Enhanced Totals Engine favors Sam Houston because of"))
        self.assertEqual(
            [item["label"] for item in context["smartsim_reasons"]["items"]],
            ["Returning Production", "Roster Experience", "Portal Activity", "Coach Continuity", "Conference / Subdivision Context"],
        )
        self.assertEqual(
            [item["label"] for item in context["matchup_context"]["items"]],
            ["Conference Context", "Returning Production", "Portal Impact", "Coach Continuity", "Roster Comparison"],
        )


if __name__ == "__main__":
    unittest.main()