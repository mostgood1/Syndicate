from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaab.cards import build_cards_page_context
from syndicate.features.ncaab.game_detail import build_game_detail_page_context
from syndicate.features.ncaab.sources import mirrored_available_dates


class NcaabCardsLocalTests(unittest.TestCase):
    def test_mirrored_available_dates_reads_local_mirror_only(self) -> None:
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value={"dates": ["2026-04-06"], "latest": "2026-04-06"}):
            dates = mirrored_available_dates()

        self.assertEqual(dates, ["2026-04-06"])

    def test_cards_page_context_uses_mirrored_source_metadata(self) -> None:
        payload = {
            "data": [
                {
                    "game_id": "game-1",
                    "away_team": "Away",
                    "home_team": "Home",
                    "date": "2026-04-06",
                    "display_date": "2026-04-06",
                    "display_time_str": "7:00 PM",
                    "bet_label": "Home -3.5",
                    "rec_code": "ATS",
                }
            ]
        }
        with patch("syndicate.features.ncaab.cards.mirrored_recommendations_payload", return_value=payload), patch(
            "syndicate.features.ncaab.cards.mirrored_available_dates", return_value=["2026-04-06"]
        ):
            context = build_cards_page_context("2026-04-06")

        self.assertIn("data/ncaab_source/api/recommendations/recommendations_2026-04-06.json", context["source_path"])
        self.assertEqual(context["source_title"], "NCAAB mirrored cards")

    def test_game_detail_uses_mirrored_source_metadata(self) -> None:
        with patch(
            "syndicate.features.ncaab.game_detail.build_cards_page_context",
            return_value={
                "date": "2026-04-06",
                "prev_date": "2026-04-05",
                "next_date": "2026-04-07",
                "games": [
                    {
                        "gamePk": "game-1",
                        "away": {"abbr": "AWY", "name": "Away"},
                        "home": {"abbr": "HME", "name": "Home"},
                        "status": "Scheduled",
                        "detail": "7:00 PM",
                        "summary": "Mirror-backed card",
                        "metrics": [],
                        "panels": [],
                    }
                ],
                "using_sample_data": False,
                "source_path": "data/ncaab_source/api/recommendations/recommendations_2026-04-06.json",
                "control_value": "2026-04-06",
            },
        ):
            context = build_game_detail_page_context("2026-04-06", "game-1")

        self.assertEqual(context["source_title"], "NCAAB mirrored game card")
        self.assertIn("data/ncaab_source/api/recommendations/recommendations_2026-04-06.json", context["source_path"])


if __name__ == "__main__":
    unittest.main()