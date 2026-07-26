from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.shared.game_board_contract import apply_game_board_contract


class GameBoardSimulationContractTests(unittest.TestCase):
    def test_apply_game_board_contract_attaches_simulation_contract(self) -> None:
        with patch("syndicate.features.shared.simulation_adapter.central_today_iso", return_value="2026-06-22"):
            context = apply_game_board_contract(
                {
                    "date": "2026-06-22",
                    "requested_date": "2026-06-22",
                    "source_title": "WNBA live scoreboard supplement",
                    "source_path": "/tmp/fake-source",
                    "games": [
                        {
                            "gamePk": "game-1",
                            "event_id": "401000001",
                            "away_tri": "AWY",
                            "home_tri": "HME",
                            "away": {"abbr": "AWY", "score": 101},
                            "home": {"abbr": "HME", "score": 103},
                            "status": "Scheduled",
                            "detail": "Scheduled",
                            "summary": "Example game",
                            "betting": {"market": "spread", "edge": 0.12},
                            "sim": {
                                "score": {"away_mean": 100.5, "home_mean": 104.5},
                                "players": {"home": [{"player": "Home Player", "pts_mean": 21.2}], "away": [{"player": "Away Player", "pts_mean": 19.8}]},
                            },
                            "live_state": {"status": "Scheduled", "final": False},
                        }
                    ],
                    "wnba_advanced_contract": {
                        "available": True,
                        "sport": "wnba",
                        "game_count": 1,
                        "coverage": {"games_with_intervals": 1},
                    }
                },
                sport="wnba",
                module="cards",
                # #75/#43: building the simulation contract is now opt-IN. It
                # defaulted to on for every non-web caller, which meant the
                # refresh-worker built it for every sport every cycle with no
                # reader anywhere. This test is about the contract's CONTENT, so
                # it asks for one explicitly; the default is covered below.
                include_simulation_contract=True,
            )

        simulation_contract = context.get("simulation_contract")
        self.assertIsInstance(simulation_contract, dict)
        self.assertEqual(simulation_contract.get("sport"), "wnba")
        self.assertEqual(simulation_contract.get("game_count"), 1)
        self.assertEqual((simulation_contract.get("games") or [])[0].get("event_id"), "401000001")
        self.assertEqual((simulation_contract.get("selection") or {}).get("kind"), "date")
        self.assertTrue((simulation_contract.get("freshness") or {}).get("is_current_day"))
        self.assertEqual(((simulation_contract.get("advanced") or {}).get("page") or {}).get("wnba_advanced_contract", {}).get("coverage", {}).get("games_with_intervals"), 1)

    def test_apply_game_board_contract_omits_simulation_contract_by_default(self) -> None:
        # #75/#43. The default flipped to OFF. Nothing in syndicate/ reads
        # context["simulation_contract"] -- the only other reference reads it
        # off the daily_update payload, a different structure -- and building it
        # on the worker for every sport every cycle is what left no memory
        # headroom for the board build to run beside an MLB sim.
        context = apply_game_board_contract(
            {"date": "2026-06-22", "games": []},
            sport="wnba",
            module="cards",
        )
        self.assertNotIn("simulation_contract", context)

    def test_apply_game_board_contract_skips_simulation_contract_on_render_web(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "RENDER": "1",
                "RENDER_EXTERNAL_URL": "https://syndicate-an21.onrender.com",
                "RENDER_SERVICE_ID": "srv-test",
            },
            clear=False,
        ):
            context = apply_game_board_contract(
                {
                    "date": "2026-06-22",
                    "requested_date": "2026-06-22",
                    "source_title": "WNBA live scoreboard supplement",
                    "source_path": "/tmp/fake-source",
                    "games": [
                        {
                            "gamePk": "game-1",
                            "event_id": "401000001",
                            "away_tri": "AWY",
                            "home_tri": "HME",
                            "away": {"abbr": "AWY", "score": 101},
                            "home": {"abbr": "HME", "score": 103},
                            "status": "Scheduled",
                            "detail": "Scheduled",
                            "summary": "Example game",
                            "betting": {"market": "spread", "edge": 0.12},
                            "sim": {
                                "score": {"away_mean": 100.5, "home_mean": 104.5},
                                "players": {"home": [{"player": "Home Player", "pts_mean": 21.2}], "away": [{"player": "Away Player", "pts_mean": 19.8}]},
                            },
                            "live_state": {"status": "Scheduled", "final": False},
                        }
                    ],
                    "wnba_advanced_contract": {
                        "available": True,
                        "sport": "wnba",
                        "game_count": 1,
                        "coverage": {"games_with_intervals": 1},
                    }
                },
                sport="wnba",
                module="cards",
            )

        self.assertNotIn("simulation_contract", context)
        self.assertEqual(context.get("board_contract", {}).get("sport"), "wnba")

    def test_apply_game_board_contract_emits_shared_publication_adapter_fields(self) -> None:
        context = apply_game_board_contract(
            {
                "date": "2026-07-09",
                "requested_date": "2026-07-09",
                "source_title": "NFL weekly recommendation snapshot",
                "source_path": "/tmp/fake-nfl-source",
                "games": [
                    {
                        "gamePk": "nfl-1",
                        "event_id": "401000010",
                        "away": {"abbr": "DAL", "name": "Dallas"},
                        "home": {"abbr": "PHI", "name": "Philadelphia"},
                        "detail": "Week 1",
                        "summary": "Example weekly snapshot",
                        "betting": {
                            "home_ml": -145,
                            "away_ml": 128,
                            "home_spread": -3.5,
                            "away_spread": 3.5,
                            "total": 47.5,
                            "p_home_win": 0.58,
                            "p_away_win": 0.42,
                        },
                        "sim": {
                            "score": {
                                "away_mean": 22.1,
                                "home_mean": 25.4,
                                "total_mean": 47.5,
                                "margin_mean": 3.3,
                            }
                        },
                        "status": "Scheduled",
                    }
                ],
            },
            sport="nfl",
            module="cards",
        )

        game = (context.get("games") or [{}])[0]
        self.assertIsInstance(game.get("shared_game_state"), dict)
        self.assertEqual(game.get("shared_game_state", {}).get("status"), "Scheduled")
        self.assertIsInstance(game.get("shared_predictions"), dict)
        self.assertEqual(game.get("shared_predictions", {}).get("away_mean"), 22.1)
        self.assertEqual(game.get("shared_predictions", {}).get("home_mean"), 25.4)
        self.assertIsInstance(game.get("shared_markets"), dict)
        self.assertEqual((game.get("shared_markets") or {}).get("moneyline", {}).get("home"), -145)
        self.assertEqual((game.get("shared_markets") or {}).get("total", {}).get("line"), 47.5)
        self.assertEqual((game.get("predictions") or {}).get("away_mean"), 22.1)
        self.assertEqual((game.get("markets") or {}).get("moneyline", {}).get("away"), 128)


if __name__ == "__main__":
    unittest.main()