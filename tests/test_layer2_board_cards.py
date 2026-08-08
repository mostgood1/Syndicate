"""The L2-A -> board-card adapter, and the parity test that makes it safe.

**THE POINT OF THIS FILE IS THE PARITY TEST.** `#268` exists because the board
template reads **70 fields** off a row while an L2-A row carries **18**, overlap
**9**. Pointing the template at L2-A rows without an adapter blanks most of the
card. The failure mode that matters is not "a field is wrong" -- it is "a field
is silently absent", because a missing key and a deliberate blank render
identically and only one of them is a decision.

So `test_every_template_field_is_handled` derives the template's own field list
by parsing `intelligence.html` and asserts the adapter answers every one. A
template that starts reading something new fails here rather than showing an
empty cell on the page. That is the guard against repeating how "L2-A becomes
the board" came to be recorded in `todo.md` for a board that never read it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from syndicate.features.shared.layer2_board_cards import (
    board_card_fields,
    to_board_card,
    to_board_cards,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = _REPO_ROOT / "syndicate" / "templates" / "intelligence.html"

# Read off a row-like object in the template but not part of the row contract.
_NOT_ROW_FIELDS = {"getAttribute"}


def _template_row_fields() -> set[str]:
    """Every `item.x` / `row.x` the board template reads."""
    source = _TEMPLATE.read_text(encoding="utf-8", errors="replace")
    found = set(re.findall(r"item\.([a-zA-Z_][a-zA-Z0-9_]*)", source))
    found |= set(re.findall(r"row\.([a-zA-Z_][a-zA-Z0-9_]*)", source))
    return found - _NOT_ROW_FIELDS


def _l2a_row(**overrides):
    row = {
        "sport": "mlb",
        "kind": "game",
        "event_id": "823191",
        "market": "spreads",
        "segment": "full",
        "line": -1.5,
        "player_name": "",
        "home_team": "San Francisco Giants",
        "away_team": "Detroit Tigers",
        "commence_time": "2026-08-08T23:05:00Z",
        "side": "home",
        "ev_pct": 2.513,
        "market_state": "pregame",
        "board_lane": "opportunity",
        "model_edge_pct": 14.86,
        "game": {"matchup": "DET @ SF", "state": "live", "home_score": 2, "away_score": 1},
        "quote": {"price": -115, "bookmaker": "novig", "books_quoting": 4, "fair_probability": 0.53},
        "score": {"score": 0.6281, "value_pct": 2.513, "sim_component": 0.0},
    }
    row.update(overrides)
    return row


class ParityTests(unittest.TestCase):
    def test_every_template_field_is_handled(self) -> None:
        """The load-bearing test. Not "most fields" -- every one."""
        template_fields = _template_row_fields()
        self.assertGreater(len(template_fields), 50, "template parse looks wrong, not a real contract")

        handled = set(board_card_fields())
        missing = sorted(template_fields - handled)
        self.assertEqual(
            missing,
            [],
            "the template reads these and the adapter does not answer them; add a mapping "
            "or an explicit None to layer2_board_cards rather than letting them render blank",
        )

    def test_the_card_actually_contains_every_promised_field(self) -> None:
        """`board_card_fields()` is a promise; this checks it is kept."""
        card = to_board_card(_l2a_row())
        for field in board_card_fields():
            self.assertIn(field, card, f"{field} promised but absent from the card")

    def test_unsourced_fields_are_present_and_none_not_missing(self) -> None:
        """A missing key and a deliberate blank render identically. Only one is
        a decision, so unsourced fields must be PRESENT and None."""
        card = to_board_card(_l2a_row())
        for field in ("writeup", "headshot_url", "settlement_status", "live_projection", "quality"):
            self.assertIn(field, card)
            self.assertIsNone(card[field])


class MappingTests(unittest.TestCase):
    def test_identity_and_market(self) -> None:
        card = to_board_card(_l2a_row())
        self.assertEqual(card["sport"], "mlb")
        self.assertEqual(card["sport_slug"], "mlb")
        self.assertEqual(card["game_id"], "823191")
        self.assertEqual(card["gamePk"], "823191")
        self.assertEqual(card["market"], "spreads")
        self.assertEqual(card["market_label"], "Spreads")

    def test_the_bet_itself(self) -> None:
        card = to_board_card(_l2a_row())
        self.assertEqual(card["selection"], "home")
        self.assertEqual(card["pick"], "home")
        self.assertEqual(card["line"], -1.5)
        self.assertEqual(card["odds"], -115)
        self.assertEqual(card["odds_current"], -115)

    def test_fair_price_is_converted_to_american(self) -> None:
        """The board shows a price next to the book's, not a probability."""
        card = to_board_card(_l2a_row())
        self.assertEqual(card["fair_price"], -113)

    def test_value_fields_all_come_from_ev_pct(self) -> None:
        card = to_board_card(_l2a_row())
        for field in ("ev_pct", "ev_current", "edge", "expected_value"):
            self.assertEqual(card[field], 2.513)

    def test_score_is_carried_whole(self) -> None:
        card = to_board_card(_l2a_row())
        self.assertEqual(card["board_score"], 0.6281)
        self.assertEqual(card["board_score_components"]["sim_component"], 0.0)

    def test_matchup_prefers_the_game_block(self) -> None:
        self.assertEqual(to_board_card(_l2a_row())["matchup"], "DET @ SF")

    def test_matchup_falls_back_to_the_team_names(self) -> None:
        row = _l2a_row(game={"state": "live"})
        self.assertEqual(to_board_card(row)["matchup"], "Detroit Tigers @ San Francisco Giants")

    def test_team_is_the_side_being_bet(self) -> None:
        self.assertEqual(to_board_card(_l2a_row(side="home"))["team"], "San Francisco Giants")
        self.assertEqual(to_board_card(_l2a_row(side="away"))["team"], "Detroit Tigers")

    def test_a_prop_titles_on_the_player(self) -> None:
        card = to_board_card(_l2a_row(kind="prop", player_name="Alex Bregman", market="batter_hits"))
        self.assertEqual(card["display_name"], "Alex Bregman")
        self.assertEqual(card["player_name"], "Alex Bregman")

    def test_a_game_line_titles_on_the_matchup(self) -> None:
        self.assertEqual(to_board_card(_l2a_row())["display_name"], "DET @ SF")

    def test_a_prop_carries_no_team(self) -> None:
        """A prop's `team` on the legacy card is the PLAYER's team, which L2-A
        does not carry -- guessing it from the side would be wrong half the
        time, so it stays empty rather than plausible."""
        card = to_board_card(_l2a_row(kind="prop", player_name="Alex Bregman", side="over"))
        self.assertIsNone(card["team"])


class GameStateTests(unittest.TestCase):
    def test_live_state_is_reported(self) -> None:
        card = to_board_card(_l2a_row())
        self.assertEqual(card["game_state"], "live")
        self.assertIs(card["is_live"], True)

    def test_pregame_is_not_live(self) -> None:
        card = to_board_card(_l2a_row(game={"matchup": "DET @ SF", "state": "pregame"}))
        self.assertIs(card["is_live"], False)

    def test_absent_state_is_unknown_not_false(self) -> None:
        """`is_live: False` would be a claim we cannot support -- for nine of
        ten soccer leagues the state is permanently pregame, so an absent state
        must read as unknown."""
        card = to_board_card(_l2a_row(game={"matchup": "DET @ SF"}))
        self.assertIsNone(card["game_state"])
        self.assertIsNone(card["is_live"])


class BatchTests(unittest.TestCase):
    def test_written_at_is_stamped_on_every_card(self) -> None:
        cards = to_board_cards([_l2a_row(), _l2a_row()], written_at="2026-08-08T20:30:04Z")
        self.assertEqual(len(cards), 2)
        for card in cards:
            self.assertEqual(card["last_updated"], "2026-08-08T20:30:04Z")
            self.assertEqual(card["updated_at"], "2026-08-08T20:30:04Z")

    def test_non_mapping_rows_are_skipped_not_crashed(self) -> None:
        self.assertEqual(len(to_board_cards([_l2a_row(), None, "nonsense", 7])), 1)

    def test_empty_input_is_empty_output(self) -> None:
        self.assertEqual(to_board_cards([]), [])
        self.assertEqual(to_board_cards(None), [])


if __name__ == "__main__":
    unittest.main()
