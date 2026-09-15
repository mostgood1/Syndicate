"""Legacy prop and game rows leave the board once Layer 2 has rows.

Lane `layer2-row-parity`, user decision 2026-09-15 ("Server-side"). On the served
board that morning 58 of 3,070 rows came from the legacy candidate pool, and 16
of its 39 MLB props were the SAME BET as a Layer 2 row with contradictory numbers
(Kyle Freeland over 11.5 outs: legacy "edge 43.3%", Layer 2 EV -5.1%).

What must NOT change, and is pinned here too: `legacy_candidate_count` still
reports the pool's own size (`#308`), steam rows are kept, and a Layer 2 outage
still shows the legacy board rather than nothing.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state


def _layer2_card(**overrides):
    card = {
        "sport": "mlb",
        "sport_slug": "mlb",
        "selection": "Sean Manaea",
        "player_name": "Sean Manaea",
        "display_name": "Sean Manaea",
        "market": "strikeouts",
        "line": 6.5,
        "odds": 138,
        "edge": 0.0513,
        "side": "over",
        "event_id": "e1",
        "kind": "prop",
        "home_team": "New York Mets",
        "away_team": "Baltimore Orioles",
        "commence_time": "2026-09-15T23:10:00Z",
        "score": {"score": 5.7},
        "quote": {"price": 138, "bookmaker": "polymarket"},
        "surface_key": "layer2",
        "source": "layer2_shortlist",
    }
    card.update(overrides)
    return card


def _legacy(candidate_type, **overrides):
    row = {
        "candidate_type": candidate_type,
        "sport": "mlb",
        "sport_slug": "mlb",
        "pick": "OVER Sean Manaea",
        "name": "OVER Sean Manaea",
        "selection": "OVER Sean Manaea",
        "player_name": "Sean Manaea",
        "market": "Pitcher Strikeouts",
        "line": 6.5,
        "odds": 113,
        "edge": 0.093,
        "matchup": "BAL @ NYM",
        "game_date": "2026-09-15",
    }
    row.update(overrides)
    return row


class LegacyRowsWithheldTests(unittest.TestCase):
    def _read(self, *, cards, legacy):
        date_response = {"by_sport": {"mlb": list(legacy)}, "candidate_count": len(legacy)}
        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        with patch.object(
            state, "read_layer2_shortlist", return_value={"cards": list(cards), "written_at": "2026-09-15T15:00:00Z"}
        ), patch.object(state, "_read_single_date_response_for_combining", return_value=date_response), patch.object(
            state, "board_l2a_fallback_enabled", return_value=True
        ):
            return state.read_combined_intelligence_response(dates=["2026-09-15"])

    @staticmethod
    def _rows(out):
        return list(out.get("top_opportunities") or out.get("ranked_all") or [])

    def test_legacy_prop_and_game_rows_leave_when_layer2_has_rows(self):
        game = _legacy("game", pick="Home ML", name="Home ML", selection="Home ML", player_name=None,
                       market="Moneyline", line=None, odds=-130)
        out = self._read(cards=[_layer2_card()], legacy=[_legacy("prop"), game])
        rows = self._rows(out)
        self.assertTrue(rows, "the Layer 2 card must still be served")
        self.assertEqual(
            [r.get("source") for r in rows], ["layer2_shortlist"] * len(rows),
            [(r.get("source"), r.get("candidate_type")) for r in rows],
        )
        self.assertEqual(out.get("legacy_candidate_count"), 2, "the pool's own size is still reported (#308)")
        self.assertEqual(out.get("legacy_rows_withheld"), 2)

    def test_steam_rows_are_kept(self):
        steam = _legacy("steam", market="To Receive Card · Steam", pick="Player over 0.5",
                        name="Player to receive card steam move", selection="Player over 0.5")
        out = self._read(cards=[_layer2_card()], legacy=[steam])
        self.assertIn("steam", [r.get("candidate_type") for r in self._rows(out)])
        self.assertEqual(out.get("legacy_rows_withheld"), 0)

    def test_without_layer2_rows_the_legacy_board_still_shows(self):
        out = self._read(cards=[], legacy=[_legacy("prop")])
        self.assertTrue(self._rows(out), "a Layer 2 outage must not empty the board")
        self.assertEqual(out.get("legacy_rows_withheld"), 0)


if __name__ == "__main__":
    unittest.main()
