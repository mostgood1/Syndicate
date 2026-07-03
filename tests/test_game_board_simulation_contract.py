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
            )

        simulation_contract = context.get("simulation_contract")
        self.assertIsInstance(simulation_contract, dict)
        self.assertEqual(simulation_contract.get("sport"), "wnba")
        self.assertEqual(simulation_contract.get("game_count"), 1)
        self.assertEqual((simulation_contract.get("games") or [])[0].get("event_id"), "401000001")
        self.assertEqual((simulation_contract.get("selection") or {}).get("kind"), "date")
        self.assertTrue((simulation_contract.get("freshness") or {}).get("is_current_day"))
        self.assertEqual(((simulation_contract.get("advanced") or {}).get("page") or {}).get("wnba_advanced_contract", {}).get("coverage", {}).get("games_with_intervals"), 1)

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


if __name__ == "__main__":
    unittest.main()