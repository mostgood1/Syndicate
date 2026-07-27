from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.ncaab.results_archive import build_results_archive_page_context
from syndicate.features.ncaab.season import build_season_betting_card_page_context
from syndicate.features.ncaab.season import build_season_page_context
from syndicate.features.ncaab.sources import mirrored_recommendations_payload
from syndicate.features.ncaab.sources import mirrored_results_by_date_payload
from syndicate.features.ncaab.sources import mirrored_results_dates


class NcaabHistoricalLocalTests(unittest.TestCase):
    def test_mirrored_results_dates_reads_local_mirror_only(self) -> None:
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value={"dates": ["2026-04-06"], "latest": "2026-04-06"}):
            dates = mirrored_results_dates()

        self.assertEqual(dates, ["2026-04-06"])

    def test_mirrored_results_by_date_payload_reads_local_mirror_only(self) -> None:
        payload = {"rows": [{"game_id": "1"}], "summary": {"ats_accuracy": 75.0}}
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value=payload):
            resolved = mirrored_results_by_date_payload("2026-04-06")

        self.assertEqual(resolved, payload)

    def test_mirrored_recommendations_payload_reads_local_mirror_only(self) -> None:
        payload = {"data": [{"game_id": "1"}]}
        with patch("syndicate.features.ncaab.sources._load_mirror_json", return_value=payload):
            resolved = mirrored_recommendations_payload("2026-04-06")

        self.assertEqual(resolved, payload)

    def test_results_archive_uses_mirrored_source_metadata(self) -> None:
        with patch("syndicate.features.ncaab.results_archive.mirrored_results_dates", return_value=["2026-04-06"]), patch(
            "syndicate.features.ncaab.results_archive.mirrored_results_by_date_payload",
            return_value={
                "rows": [{"game_id": "1"}],
                "summary": {"ats_accuracy": 75.0, "totals_accuracy": 50.0, "ats_correct": 3, "ats_total": 4, "totals_correct": 2, "totals_total": 4},
            },
        ):
            context = build_results_archive_page_context("2026-04-06")

        self.assertIn("data/ncaab_source/api/results_dates.json", context["source_path"])
        self.assertEqual(context["source_title"], "NCAAB mirrored daily archive")

    def test_season_review_uses_mirrored_payloads(self) -> None:
        recommendation_payload = {
            "data": [
                {
                    "game_id": "game-1",
                    "away_team": "Away",
                    "home_team": "Home",
                    "date": "2026-04-06",
                    "display_date": "2026-04-06",
                    "display_time_str": "7:00 PM",
                    "bet_label": "Home -3.5",
                }
            ]
        }
        results_payload = {
            "rows": [
                {
                    "game_id": "game-1",
                    "away_team": "Away",
                    "home_team": "Home",
                    "home_score": 70,
                    "away_score": 65,
                }
            ],
            "summary": {},
        }
        with patch("syndicate.features.ncaab.season.mirrored_season_dates", return_value=["2026-04-06"]), patch(
            "syndicate.features.ncaab.season.mirrored_schedule_dates", return_value=["2026-04-06"]
        ), patch("syndicate.features.ncaab.season.mirrored_results_dates", return_value=["2026-04-06"]), patch(
            "syndicate.features.ncaab.season.mirrored_recommendations_payload", return_value=recommendation_payload
        ), patch("syndicate.features.ncaab.season.mirrored_results_by_date_payload", return_value=results_payload):
            context = build_season_page_context(2025, "2026-04-06")
            betting_context = build_season_betting_card_page_context(2025, "2026-04-06")

        self.assertIn("data/ncaab_source/api/recommendations/recommendations_2026-04-06.json", context["source_path"])
        self.assertEqual(context["source_title"], "NCAAB 2025 season review data")
        self.assertEqual(betting_context["source_title"], "NCAAB mirrored historical betting card data")