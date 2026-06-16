from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.wnba.cards import _supplement_games_with_live_state
from syndicate.features.wnba.cards import build_source_cards_payload


class WnbaCardsMergeAliasTests(unittest.TestCase):
    def test_live_aliases_do_not_create_duplicate_cards(self) -> None:
        processed_games = [
            {
                "gamePk": "1",
                "event_id": "",
                "away_tri": "LA",
                "home_tri": "WSH",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "LAS@WSH",
                "event_id": "",
                "away_tri": "LAS",
                "home_tri": "WSH",
                "status": "Final",
                "detail": "Final",
                "live_state": {
                    "away": "LAS",
                    "home": "WSH",
                    "status": "Final",
                    "final": True,
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)

    def test_live_event_id_variant_does_not_duplicate_matchup(self) -> None:
        processed_games = [
            {
                "gamePk": "3",
                "event_id": "",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Scheduled",
                "detail": "2026-05-31T00:00:00+00:00",
            }
        ]
        live_games = [
            {
                "gamePk": "IND@POR",
                "event_id": "401772472",
                "away_tri": "IND",
                "home_tri": "POR",
                "status": "Live",
                "detail": "Q3",
                "live_state": {
                    "away": "IND",
                    "home": "POR",
                    "status": "Q3",
                    "event_id": "401772472",
                },
            }
        ]

        with patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_live_fetch"),
        ):
            merged_games, _, supplemented_count = _supplement_games_with_live_state(processed_games, "2026-05-30")

        self.assertEqual(len(merged_games), 1)
        self.assertEqual(supplemented_count, 0)

    def test_source_cards_payload_falls_back_to_latest_stored_slate_for_today(self) -> None:
        empty_bundle = {"rows": [], "recommendations": {}, "sim": {}, "props": {}}
        fallback_bundle = {
            "rows": [{"away_tri": "LAS", "home_tri": "CON", "gamePk": "1", "commence_time": "2026-06-11T18:00:00Z"}],
            "recommendations": {},
            "sim": {},
            "props": {},
        }

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-15"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-11", "2026-06-15"],
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            side_effect=lambda selected_date: fallback_bundle if selected_date == "2026-06-11" else empty_bundle,
        ):
            payload = build_source_cards_payload("2026-06-15")

        self.assertEqual(payload["date"], "2026-06-11")
        self.assertTrue(payload["lookahead_applied"])
        self.assertEqual(len(payload["games"]), 1)


if __name__ == "__main__":
    unittest.main()
