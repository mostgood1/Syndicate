from __future__ import annotations

import unittest

from syndicate.features.shared.game_board_contract import _normalize_game


class GameBoardContractPropTeamTests(unittest.TestCase):
    def test_shared_prop_rows_carry_team_abbreviation(self) -> None:
        # _build_prop_rows iterates ("away", away_abbr) / ("home", home_abbr)
        # -- it already knows which team each prop row belongs to, but never
        # stored it, so every downstream consumer (_compact_prop_rows in
        # home.py, and from there _prop_candidate_from_item in
        # intelligence.py) had no way to attribute a team to these props.
        game = {
            "away": {"abbr": "BOS"},
            "home": {"abbr": "NYK"},
            "prop_recommendations": {
                "away": [{"player": "Jayson Tatum", "display_pick": "Over 28.5", "market": "points"}],
                "home": [{"player": "Julius Randle", "display_pick": "Over 24.5", "market": "points"}],
            },
        }

        normalized = _normalize_game(game)
        prop_rows = normalized.get("shared_prop_rows") or []

        self.assertEqual(len(prop_rows), 2)
        by_name = {row.get("name"): row for row in prop_rows}
        self.assertEqual(by_name["Jayson Tatum"]["team"], "BOS")
        self.assertEqual(by_name["Julius Randle"]["team"], "NYK")


if __name__ == "__main__":
    unittest.main()
