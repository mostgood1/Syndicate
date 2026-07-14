from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.ncaaf import picks as ncaaf_picks_route
from syndicate.features.ncaaf.picks import build_picks_page_context
from syndicate.features.ncaaf.picks import build_smartsim_picks_page_context


class NcaafPicksLocalTests(unittest.TestCase):
    def test_smartsim_picks_runtime_uses_prediction_rows(self) -> None:
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

        with patch("syndicate.features.ncaaf.picks._prediction_weeks", return_value=[1]), patch(
            "syndicate.features.ncaaf.picks._runtime_prediction_rows", return_value=runtime_rows
        ), patch("syndicate.features.ncaaf.picks._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")):
            context = build_smartsim_picks_page_context(1)

        self.assertEqual(context["source_title"], "NCAAF SmartSim picks runtime")
        self.assertEqual(context["rank_cards"][0]["meta"], "UNLV at Sam Houston")
        self.assertEqual(context["rank_cards"][0]["eyebrow"], "SmartSim runtime")
        self.assertIn("SmartSim projects Sam Houston", context["rank_cards"][0]["summary"])

    def test_smartsim_picks_runtime_falls_back_to_summaries(self) -> None:
        fallback_context = {"date": "2025-01-01", "rank_cards": [], "source_title": "Fallback"}

        with patch("syndicate.features.ncaaf.picks._prediction_weeks", return_value=[]), patch(
            "syndicate.features.ncaaf.picks.build_picks_page_context", return_value=fallback_context
        ):
            context = build_smartsim_picks_page_context(1)

        self.assertEqual(context, fallback_context)

    def test_picks_route_uses_smartsim_runtime_builder(self) -> None:
        app = create_app()
        runtime_context = {"date": "2025-01-01", "rank_cards": [], "week": 1, "available_weeks": [1], "season": 2025}

        with app.test_request_context("/ncaaf/picks?week=1"), patch(
            "syndicate.blueprints.ncaaf.build_smartsim_picks_page_context", return_value=runtime_context
        ) as build_context, patch("syndicate.blueprints.ncaaf.render_template", return_value="rendered") as render_template:
            response = ncaaf_picks_route()

        self.assertEqual(response, "rendered")
        build_context.assert_called_once()
        render_template.assert_called_once()
        self.assertEqual(render_template.call_args.kwargs["week"], 1)

    def test_existing_summary_backed_picks_context_still_works(self) -> None:
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

        with patch("syndicate.features.ncaaf.picks.default_season", return_value=2025), patch(
            "syndicate.features.ncaaf.picks.available_weeks", return_value=[1]
        ), patch("syndicate.features.ncaaf.picks.summary_path", return_value="week_1.json"), patch(
            "syndicate.features.ncaaf.picks.load_json", return_value=summary
        ):
            context = build_picks_page_context(1)

        self.assertEqual(context["rank_cards"][0]["eyebrow"], "DraftKings")
        self.assertIn("recommendation summary", context["intro_body"].lower())


if __name__ == "__main__":
    unittest.main()
