"""ONE GAME, ONE BOARD on the combined board (lane `layer2-lookahead-live-dedupe`, todo `#779`).

Lead 2026-11-09 (lane `live-display-other-sports`): at 23:09Z Marshall @ Ohio State was live
and the served board carried two of its unders from the LOOK-AHEAD board date (11-10) with
the pregame projection 161.4, pregame edges 6.05 / 3.97 and no live number, beside the 11-09
board's live rows for the same game.

Measured 2026-11-10 19:51Z: the 11-11 NCAAB shortlist (written 19:26Z) was 274 rows, all of
them tonight's 11-10 games; 131 survived the board's line-level dedupe at OTHER lines, every
one with its game also on the 11-10 board.

Pinned:
  * a later board date's card for an EARLIER date's game that an earlier board carries is
    dropped -- at any line, whatever its state;
  * a week sport's game on boards BEFORE its own date is left alone (pregame-only duplicate);
  * a game only a later date carries is kept (no game is lost);
  * per kind: props from a later board are kept when the earliest board seats none;
  * a card with no event id is never dropped;
  * the earliest DATE wins, not the first one read;
  * reachability: the drop runs inside `_layer2_fallback_recommendations` BEFORE the live
    restate, and the served payload carries the count.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline import intelligence_state as state

TODAY = "2026-11-10"
TOMORROW = "2026-11-11"


def _card(board_date: str | None = None, **overrides) -> dict:
    card = {
        "sport": "ncaab",
        "sport_slug": "ncaab",
        "kind": "game",
        "market": "totals",
        "segment": "full",
        "side": "under",
        "line": 162.5,
        "event_id": "marshall-ohiostate",
        "home_team": "Ohio State Buckeyes",
        "away_team": "Marshall Thundering Herd",
        "matchup": "Marshall Thundering Herd @ Ohio State Buckeyes",
        "commence_time": "2026-11-10T23:00:00Z",
        "game_date": TODAY,
        "model_edge_pct": 5.39,
        "source": "layer2_shortlist",
    }
    if board_date is not None:
        card["source_board_date"] = board_date
    card.update(overrides)
    return card


class DropRuleTests(unittest.TestCase):
    def test_a_lookahead_copy_at_another_line_is_dropped_and_today_kept(self) -> None:
        today = _card(TODAY, line=162.5)
        lookahead = [_card(TOMORROW, line=162.0, model_edge_pct=6.05), _card(TOMORROW, line=161.5, model_edge_pct=3.97)]
        cards = [today, *lookahead]
        report = state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(cards, [today])
        self.assertEqual(report["rows_dropped"], 2)
        self.assertEqual(report["games"], 1)
        self.assertEqual(report["rows_dropped_with_model_edge"], 2)
        self.assertEqual(report["by_sport_board_date"], {f"ncaab|{TOMORROW}": 2})

    def test_a_game_only_a_later_date_carries_is_kept(self) -> None:
        cards = [_card(TODAY, event_id="a"), _card(TOMORROW, event_id="b")]
        report = state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual([c["event_id"] for c in cards], ["a", "b"])
        self.assertEqual(report["rows_dropped"], 0)

    def test_every_row_of_the_earliest_board_survives(self) -> None:
        today = [_card(TODAY, line=162.5), _card(TODAY, line=162.5, side="over"), _card(TODAY, market="h2h", line=None)]
        cards = [*today, _card(TOMORROW, market="spreads", line=-11.5)]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(cards, today)

    def test_props_survive_when_the_earliest_board_seats_no_props(self) -> None:
        prop = _card(TOMORROW, kind="prop", market="player_points", player_name="Bruce Thornton", line=15.5)
        cards = [_card(TODAY), prop]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertIn(prop, cards)
        self.assertEqual(len(cards), 2)

    def test_props_are_deduped_when_the_earliest_board_has_props_for_the_game(self) -> None:
        cards = [
            _card(TODAY, kind="prop", market="player_points", player_name="A", line=15.5),
            _card(TOMORROW, kind="prop", market="player_rebounds", player_name="B", line=6.5),
        ]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual([c["source_board_date"] for c in cards], [TODAY])

    def test_a_card_with_no_event_id_is_never_dropped(self) -> None:
        cards = [_card(TODAY, event_id=""), _card(TOMORROW, event_id=None)]
        report = state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(len(cards), 2)
        self.assertEqual(report["rows_dropped"], 0)

    def test_the_earliest_date_wins_not_the_first_read(self) -> None:
        tomorrow, today = _card(TOMORROW, line=162.0), _card(TODAY, line=162.5)
        cards = [tomorrow, today]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(cards, [today])

    def test_a_week_sport_game_on_boards_BEFORE_its_own_date_is_left_alone(self) -> None:
        # NCAAF Saturday game on the Tuesday, Wednesday and Thursday boards: a pregame-only
        # duplicate (those boards leave the window before Saturday), out of this lane's scope.
        sat = dict(sport="ncaaf", sport_slug="ncaaf", event_id="wyo-utep",
                   commence_time="2026-11-15T03:00:00Z", game_date="2026-11-14")
        cards = [_card(TODAY, line=48.5, **sat), _card(TOMORROW, line=49.5, **sat), _card("2026-11-12", line=47.5, **sat)]
        report = state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(len(cards), 3)
        self.assertEqual(report["rows_dropped"], 0)

    def test_a_game_on_its_own_date_board_is_kept_when_an_earlier_board_also_carries_it(self) -> None:
        own = dict(sport="ncaaf", sport_slug="ncaaf", event_id="wed-game", game_date=TOMORROW)
        cards = [_card(TODAY, line=50.5, **own), _card(TOMORROW, line=51.5, **own)]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(len(cards), 2)

    def test_a_card_with_no_game_date_is_never_dropped(self) -> None:
        cards = [_card(TODAY), _card(TOMORROW, line=162.0, game_date=None)]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(len(cards), 2)

    def test_same_event_id_in_another_sport_is_another_game(self) -> None:
        cards = [_card(TODAY, sport="ncaab"), _card(TOMORROW, sport="wncaab", sport_slug="wncaab")]
        state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(len(cards), 2)

    def test_nothing_dropped_prints_nothing_and_leaves_the_list(self) -> None:
        cards = [_card(TODAY)]
        before = list(cards)
        with patch("builtins.print") as printed:
            state._drop_lookahead_duplicate_game_cards(cards)
        self.assertEqual(cards, before)
        printed.assert_not_called()


class ReachabilityTests(unittest.TestCase):
    """off != on: the drop is wired where the combined board reads its cards."""

    def _shortlists(self) -> dict:
        return {
            TODAY: {"cards": [_card(line=162.5)]},
            TOMORROW: {"cards": [_card(line=162.0, model_edge_pct=6.05), _card(event_id="tomorrow-only")]},
        }

    def test_the_lookahead_copy_never_reaches_the_live_restate(self) -> None:
        shortlists = self._shortlists()
        seen: list[list[dict]] = []

        def _restate(cards, requested_dates, **_kw):
            seen.append([dict(c) for c in cards])
            return 0

        report: dict = {}
        with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
             patch.object(state, "_merge_inplay_overlay", return_value={"replaced": 0, "added": 0}), \
             patch.object(state, "_refresh_layer2_live_state", side_effect=_restate):
            rows = state._layer2_fallback_recommendations([TODAY, TOMORROW], lookahead_report=report)
        self.assertEqual(len(seen), 1)
        restated = {(c["source_board_date"], c["event_id"], c["line"]) for c in seen[0]}
        self.assertEqual(restated, {(TODAY, "marshall-ohiostate", 162.5), (TOMORROW, "tomorrow-only", 162.5)})
        self.assertEqual({(r["source_board_date"], r["event_id"]) for r in rows},
                         {(TODAY, "marshall-ohiostate"), (TOMORROW, "tomorrow-only")})
        self.assertEqual(report["rows_dropped"], 1)

    def test_a_failing_dedupe_leaves_the_cards_as_they_were(self) -> None:
        shortlists = self._shortlists()
        with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
             patch.object(state, "_merge_inplay_overlay", return_value={"replaced": 0, "added": 0}), \
             patch.object(state, "_refresh_layer2_live_state", return_value=0), \
             patch.object(state, "_drop_lookahead_duplicate_game_cards", side_effect=RuntimeError("boom")):
            rows = state._layer2_fallback_recommendations([TODAY, TOMORROW])
        self.assertEqual(len(rows), 3)

    def test_the_served_board_drops_the_copy_and_says_so(self) -> None:
        shortlists = self._shortlists()
        state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        try:
            with patch.object(state, "read_layer2_shortlist", side_effect=lambda d: shortlists.get(str(d))), \
                 patch.object(state, "_merge_inplay_overlay", return_value={"replaced": 0, "added": 0}), \
                 patch.object(state, "_refresh_layer2_live_state", return_value=0), \
                 patch.object(state, "_read_single_date_response_for_combining", return_value=None), \
                 patch.object(state, "board_l2a_fallback_enabled", return_value=True):
                served = state.read_combined_intelligence_response(dates=[TODAY, TOMORROW])
        finally:
            state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
        self.assertEqual(served.get("layer2_lookahead_rows_dropped"), 1)
        self.assertEqual(served.get("layer2_lookahead_dropped_by_sport_board_date"), {f"ncaab|{TOMORROW}": 1})
        lines = sorted(
            (str(c.get("source_board_date")), str(c.get("event_id")), c.get("line"))
            for c in served.get("ranked_all") or []
        )
        self.assertNotIn((TOMORROW, "marshall-ohiostate", 162.0), lines)
        self.assertEqual(served.get("layer2_fallback_rows"), 2)


if __name__ == "__main__":
    unittest.main()
