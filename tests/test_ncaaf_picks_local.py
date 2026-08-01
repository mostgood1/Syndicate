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

        with patch("syndicate.features.ncaaf.picks._resolve_ncaaf_active_season_and_weeks", return_value=(2025, [1])), patch(
            "syndicate.features.ncaaf.picks._engine_rows_for_season_week", return_value=runtime_rows
        ), patch(
            "syndicate.features.ncaaf.picks._runtime_prediction_rows", return_value=runtime_rows
        ), patch("syndicate.features.ncaaf.picks._prediction_source_path", return_value=Path("/tmp/predicted_totals.csv")):
            context = build_smartsim_picks_page_context(1)

        self.assertEqual(context["source_title"], "NCAAF Enhanced Totals Engine picks runtime")
        self.assertEqual(context["rank_cards"][0]["meta"], "UNLV at Sam Houston")
        self.assertEqual(context["rank_cards"][0]["eyebrow"], "Enhanced Totals Engine")
        self.assertIn("Enhanced Totals Engine projects Sam Houston", context["rank_cards"][0]["summary"])

    def test_smartsim_picks_runtime_falls_back_to_summaries(self) -> None:
        # Neither the legacy engine (season-aware check) nor the real
        # SmartSim2 standalone artifacts have anything for this
        # season/week -- only then should this fall all the way back to
        # the historical summary-artifact path.
        fallback_context = {"date": "2025-01-01", "rank_cards": [], "source_title": "Fallback"}

        with patch("syndicate.features.ncaaf.picks._resolve_ncaaf_active_season_and_weeks", return_value=(2025, [1])), patch(
            "syndicate.features.ncaaf.picks._engine_rows_for_season_week", return_value=[]
        ), patch(
            "syndicate.features.ncaaf.picks._smartsim2_standalone_rows", return_value=[]
        ), patch(
            "syndicate.features.ncaaf.picks.build_picks_page_context", return_value=fallback_context
        ):
            context = build_smartsim_picks_page_context(1)

        self.assertEqual(context, fallback_context)

    def test_smartsim_picks_runtime_falls_back_to_standalone_smartsim2(self) -> None:
        # New behavior: when the engine has nothing for this season/week
        # but real SmartSim2 standalone projections DO exist (e.g. a new
        # season the legacy engine hasn't been refreshed for), show those
        # instead of jumping straight to the historical summary fallback.
        from syndicate.features.ncaaf.smartsim2_projection import SmartSimNcaafProjection

        projection = SmartSimNcaafProjection(
            game_id="g1", season=2026, week=1, home_team="Notre Dame", away_team="Wisconsin",
            home_score_mean=33.5, away_score_mean=25.7, margin_mean=7.8, total_mean=59.2,
            margin_stdev=12.0, total_stdev=10.0, home_win_rate=0.72, seeds_used=300,
            profile_name="ncaaf_v2", rating_source="test", generated_at="2026-01-01T00:00:00Z",
        )
        standalone_rows = [{"home_team": "Notre Dame", "away_team": "Wisconsin", "projection": projection}]

        with patch("syndicate.features.ncaaf.picks._resolve_ncaaf_active_season_and_weeks", return_value=(2026, [1])), patch(
            "syndicate.features.ncaaf.picks._engine_rows_for_season_week", return_value=[]
        ), patch(
            "syndicate.features.ncaaf.picks._smartsim2_standalone_rows", return_value=standalone_rows
        ):
            context = build_smartsim_picks_page_context(1)

        self.assertEqual(context["season"], 2026)
        self.assertEqual(context["week"], 1)
        self.assertEqual(len(context["rank_cards"]), 1)
        self.assertEqual(context["rank_cards"][0]["eyebrow"], "SmartSim 2.0")
        self.assertIn("Notre Dame", context["rank_cards"][0]["title"])

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
