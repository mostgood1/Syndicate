from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaaf.cards import build_cards_page_context


class NcaafCardsLocalTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()