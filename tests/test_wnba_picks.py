from __future__ import annotations

import unittest

from syndicate.blueprints.home import _prop_item_from_rank_card
from syndicate.features.wnba.picks import _card_from_pick
from syndicate.features.wnba.picks import _line_from_selection


REAL_PICK_SHAPE = {
    "market": "PROPS",
    "team": "GSV",
    "display_pick": "Gabby Williams OVER 1.5",
    "selection": "OVER 1.5",
    "projection": 1.98,
    "projected": 1.98,
    "odds": -118.0,
    "price": -118.0,
    "score": 18.908454399167518,
    "ev_pct": 18.908454399167518,
    "win_prob": 0.5412844036697247,
    "p_win": 0.5412844036697247,
    "basketball_summary": "Prop projection -",
    "top_play_reasons": ["EV 18.9%", "Regular price range (-150 to +150)"],
    "matchup": "GSV @ PHX",
}


class LineFromSelectionTests(unittest.TestCase):
    def test_parses_trailing_line_from_selection(self) -> None:
        self.assertEqual(_line_from_selection({"selection": "OVER 1.5"}), 1.5)

    def test_falls_back_to_display_pick_when_selection_missing(self) -> None:
        self.assertEqual(_line_from_selection({"display_pick": "Gabby Williams OVER 1.5"}), 1.5)

    def test_returns_none_when_no_numeric_line_present(self) -> None:
        self.assertIsNone(_line_from_selection({"selection": "MONEYLINE"}))
        self.assertIsNone(_line_from_selection({}))


class CardFromPickTests(unittest.TestCase):
    # #131: confirmed live 2026-07-29 -- the WNBA betting board showed
    # no projection and no line movement for every rank-card-sourced
    # candidate, even though recommendations_slate_<date>.json's raw pick
    # rows carry a real `projection` value. _card_from_pick's `metrics` list
    # never included a "Projected"/"Line" entry, and _prop_item_from_rank_card
    # (home.py) only ever reads those two fields by scanning metrics for
    # those exact label families -- so the real projection/line data one
    # level up in `pick` never reached the board candidate at all.
    def test_metrics_include_projected_and_line(self) -> None:
        card = _card_from_pick({"matchup": "GSV @ PHX"}, REAL_PICK_SHAPE)
        labels = {str(metric.get("label")): metric.get("value") for metric in card["metrics"]}
        self.assertIn("Projected", labels)
        self.assertEqual(labels["Projected"], "2")  # format_num(1.98) -> "2"
        self.assertIn("Line", labels)
        self.assertEqual(labels["Line"], "1.5")

    def test_projected_and_line_survive_into_the_board_candidate_item(self) -> None:
        card = _card_from_pick({"matchup": "GSV @ PHX"}, REAL_PICK_SHAPE)
        item = _prop_item_from_rank_card(card, sport_slug="wnba")
        self.assertIsNotNone(item)
        self.assertIsNotNone(item.get("projected"))
        self.assertNotEqual(item.get("projected"), "-")
        self.assertIsNotNone(item.get("line"))
        self.assertEqual(item.get("line"), "1.5")

    def test_missing_projection_and_line_degrade_to_placeholder_not_crash(self) -> None:
        pick = dict(REAL_PICK_SHAPE)
        pick["selection"] = "MONEYLINE"
        pick["display_pick"] = "GSV MONEYLINE"
        pick["projection"] = None
        pick["projected"] = None
        card = _card_from_pick({"matchup": "GSV @ PHX"}, pick)
        labels = {str(metric.get("label")): metric.get("value") for metric in card["metrics"]}
        self.assertEqual(labels["Line"], "-")
        self.assertEqual(labels["Projected"], "-")


if __name__ == "__main__":
    unittest.main()
