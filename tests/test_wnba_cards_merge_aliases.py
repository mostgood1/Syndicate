from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
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
            merged_games, _, supplemented_count, _ = _supplement_games_with_live_state(processed_games, "2026-05-30")

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
            merged_games, _, supplemented_count, _ = _supplement_games_with_live_state(processed_games, "2026-05-30")

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
            payload = build_source_cards_payload("2026-06-15", allow_stored_date_fallback=True)

        self.assertEqual(payload["date"], "2026-06-11")
        self.assertTrue(payload["lookahead_applied"])
        self.assertEqual(len(payload["games"]), 1)

    def test_source_cards_payload_keeps_explicit_today_date_without_stored_fallback(self) -> None:
        empty_bundle = {"rows": [], "recommendations": {}, "sim": {}, "props": {}}

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-23"), patch(
            "syndicate.features.wnba.cards.available_dates",
            return_value=["2026-06-22", "2026-06-23"],
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=empty_bundle,
        ):
            payload = build_source_cards_payload("2026-06-23", allow_stored_date_fallback=False)

        self.assertEqual(payload["date"], "2026-06-23")
        self.assertFalse(payload["lookahead_applied"])
        self.assertEqual(payload["requested_date"], "2026-06-23")

    def test_source_cards_payload_uses_live_supplement_for_today(self) -> None:
        artifact_bundle = {
            "rows": [
                {"away_tri": "CHI", "home_tri": "CON", "gamePk": "1", "commence_time": "2026-06-22T18:00:00Z"},
                {"away_tri": "TOR", "home_tri": "ATL", "gamePk": "2", "commence_time": "2026-06-22T20:00:00Z"},
            ],
            "recommendations": {},
            "sim": {},
            "props": {},
        }

        live_games = [
            {"gamePk": "401857012", "event_id": "401857012", "away_tri": "CHI", "home_tri": "CON", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857012", "away": "CHI", "home": "CON"}},
            {"gamePk": "401857013", "event_id": "401857013", "away_tri": "TOR", "home_tri": "ATL", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857013", "away": "TOR", "home": "ATL"}},
            {"gamePk": "401857014", "event_id": "401857014", "away_tri": "PHX", "home_tri": "IND", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857014", "away": "PHX", "home": "IND"}},
            {"gamePk": "401857015", "event_id": "401857015", "away_tri": "DAL", "home_tri": "SEA", "status": "Scheduled", "detail": "Scheduled", "live_state": {"event_id": "401857015", "away": "DAL", "home": "SEA"}},
        ]

        with patch("syndicate.features.wnba.cards.central_today_iso", return_value="2026-06-22"), patch(
            "syndicate.features.wnba.cards._resolved_source_cards_date",
            return_value="2026-06-22",
        ), patch(
            "syndicate.features.wnba.cards._artifact_bundle",
            return_value=artifact_bundle,
        ), patch(
            "syndicate.features.wnba.cards._games_from_live_state_fallback",
            return_value=(live_games, "espn_scoreboard_fallback"),
        ):
            payload = build_source_cards_payload("2026-06-22")

        self.assertEqual(payload["date"], "2026-06-22")
        self.assertEqual(len(payload["games"]), 4)
        self.assertEqual([game.get("event_id") for game in payload["games"]], ["401857012", "401857013", "401857014", "401857015"])

    def test_source_cards_payload_keeps_full_sim_player_rows(self) -> None:
        artifact_bundle = {
            "rows": [
                {
                    "away_tri": "LAS",
                    "home_tri": "CON",
                    "visitor_team": "Las Vegas Aces",
                    "home_team": "Connecticut Sun",
                    "game_id": "1",
                    "commence_time": "2026-06-22T18:00:00Z",
                }
            ],
            "recommendations": {},
            "sim": {
                ("LAS", "CON"): {
                    "sim": {
                        "players_summary": {
                            "away": 4,
                            "home": 5,
                            "missing_away": 0,
                            "missing_home": 0,
                            "injured_away": 0,
                            "injured_home": 0,
                        },
                        "players": {
                            "away": [
                                {"player_name": "Away Player", "pts_mean": 10.5, "reb_mean": 4.2, "ast_mean": 2.1, "pra_mean": 16.8}
                            ],
                            "home": [
                                {"player_name": "Home Player", "pts_mean": 11.3, "reb_mean": 5.1, "ast_mean": 3.0, "pra_mean": 19.4}
                            ],
                        },
                        "pregame_context": {"available": True, "source": "sim"},
                        "quarters": [{"quarter": 1, "away_mean": 20.0, "home_mean": 22.0}],
                    }
                }
            },
            "props": {},
        }

        with patch("syndicate.features.wnba.cards._artifact_bundle", return_value=artifact_bundle):
            payload = build_source_cards_payload("2026-06-22", allow_stored_date_fallback=False)

        games = payload.get("games") or []
        self.assertGreaterEqual(len(games), 1)

        first_game = games[0]
        sim = first_game.get("sim") if isinstance(first_game, dict) else {}
        self.assertTrue(sim.get("players_loaded"))
        self.assertGreater(len((sim.get("players") or {}).get("away") or []), 0)
        self.assertGreater(len((sim.get("players") or {}).get("home") or []), 0)
        self.assertIn("pregame_context", sim)
        self.assertGreater(len(sim.get("pregame_context") or {}), 0)
        self.assertIn("quarters", sim)
        self.assertGreaterEqual(int((sim.get("players_summary") or {}).get("away") or 0), 0)
        self.assertGreaterEqual(int((sim.get("players_summary") or {}).get("home") or 0), 0)


if __name__ == "__main__":
    unittest.main()
