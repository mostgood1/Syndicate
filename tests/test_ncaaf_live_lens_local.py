from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.blueprints.ncaaf import live_lens as ncaaf_live_lens_route
from syndicate.features.ncaaf.live_lens import build_live_lens_page_context
from syndicate.features.ncaaf.live_lens import build_smartsim_live_lens_page_context


class NcaafLiveLensLocalTests(unittest.TestCase):
    def test_smartsim_live_lens_runtime_uses_runtime_cards(self) -> None:
        runtime_cards_context = {
            "date": "2025 Week 1",
            "control_value": "1",
            "prev_date": "1",
            "next_date": "1",
            "source_path": Path("/tmp/predicted_totals.csv"),
            "board_contract": {"source_kind": "smartsim_runtime"},
            "available_weeks": [1],
            "games": [
                {
                    "gamePk": "1_UNLV_Sam_Houston",
                    "away": {"abbr": "UNLV", "name": "UNLV"},
                    "home": {"abbr": "SHU", "name": "Sam Houston"},
                    "summary": "Enhanced Totals Engine projects Sam Houston 34.2 - 24.1 UNLV with a total of 58.3 and a home win probability of 73.1%.",
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
                    },
                }
            ],
        }

        with patch("syndicate.features.ncaaf.live_lens.build_smartsim_cards_page_context", return_value=runtime_cards_context):
            context = build_smartsim_live_lens_page_context(1)

        self.assertEqual(context["source_title"], "NCAAF Enhanced Totals Engine live lens runtime")
        self.assertEqual(context["rank_cards"][0]["eyebrow"], "Enhanced Totals Engine")
        self.assertIn("34.2", context["rank_cards"][0]["list_items"][0])
        self.assertIn("73.1%", context["rank_cards"][0]["list_items"][3])
        self.assertEqual(context["rows"], 1)

    def test_smartsim_live_lens_runtime_falls_back_to_summary_builder(self) -> None:
        fallback_context = {"date": "2025 Week 1", "rank_cards": [], "source_title": "Fallback"}

        with patch("syndicate.features.ncaaf.live_lens.build_smartsim_cards_page_context", return_value={"board_contract": {"source_kind": "artifact_backed"}}), patch(
            "syndicate.features.ncaaf.live_lens.build_live_lens_page_context", return_value=fallback_context
        ):
            context = build_smartsim_live_lens_page_context(1)

        self.assertEqual(context, fallback_context)

    def test_live_lens_route_uses_smartsim_runtime_builder(self) -> None:
        app = create_app()
        runtime_context = {"date": "2025 Week 1", "rank_cards": [], "week": 1, "available_weeks": [1], "season": 2025}

        with app.test_request_context("/ncaaf/live-lens?week=1"), patch(
            "syndicate.blueprints.ncaaf.build_smartsim_live_lens_page_context", return_value=runtime_context
        ) as build_context, patch("syndicate.blueprints.ncaaf.render_template", return_value="rendered") as render_template:
            response = ncaaf_live_lens_route()

        self.assertEqual(response, "rendered")
        build_context.assert_called_once()
        render_template.assert_called_once()
        self.assertEqual(render_template.call_args.kwargs["week"], 1)

    def test_existing_summary_backed_live_lens_context_still_works(self) -> None:
        summary_cards_context = {
            "control_value": "1",
            "date": "2025 Week 1",
            "prev_date": "1",
            "next_date": "1",
            "source_path": "summary.json",
            "games": [
                {
                    "gamePk": "1_UNLV_Sam_Houston",
                    "away": {"abbr": "UNLV", "name": "UNLV"},
                    "home": {"abbr": "SHU", "name": "Sam Houston"},
                    "detail": "Historical summary",
                    "status": "Week 1",
                    "summary": "Historical summary row.",
                    "metrics": [{"label": "Model", "value": "83.1%"}, {"label": "Implied", "value": "25.3%"}, {"label": "Price", "value": "+295"}, {"label": "Stake", "value": "$50.00"}, {"label": "Edge", "value": "2.28%"}],
                }
            ],
        }

        with patch("syndicate.features.ncaaf.live_lens.build_cards_page_context", return_value=summary_cards_context), patch(
            "syndicate.features.ncaaf.live_lens.available_weeks", return_value=[1]
        ):
            context = build_live_lens_page_context(1)

        self.assertEqual(context["source_title"], "NCAAF live game lens")
        self.assertEqual(context["rank_cards"][0]["eyebrow"], "Week 1")
        self.assertEqual(context["rows"], 1)


if __name__ == "__main__":
    unittest.main()
