from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.soccer import props


class NormalizePlayerNameTests(unittest.TestCase):
    def test_strips_accents_and_case(self) -> None:
        self.assertEqual(props._normalize_player_name("Kévin Denkey"), "kevin denkey")


class PropRankCardTests(unittest.TestCase):
    # #150 follow-up. _prop_rank_card originally never carried a real
    # market/odds/edge -- only the simulated anytime-goalscorer probability
    # -- so home.py's _prop_item_from_rank_card had nothing to read into
    # "market"/"line"/"odds"/"projected"/"edge", and every soccer prop
    # candidate was rejected downstream as missing_projection_or_odds.
    _ROW = {
        "player_name": "Kevin Denkey",
        "team": "Arsenal",
        "side": "home",
        "match_id": "12345",
        "anytime_scorer_probability": 0.35,
        "anytime_scorer_probability_if_playing": 0.38,
        "expected_shots": 2.1,
        "expected_shots_on_target": 0.9,
        "expected_minutes_share": 0.9,
    }

    def test_no_pick_leaves_market_none_and_omits_odds_metrics(self) -> None:
        card = props._prop_rank_card(self._ROW, league="epl", week=1, season=2026, pick=None)
        self.assertIsNone(card["market"])
        labels = {m["label"] for m in card["metrics"]}
        self.assertNotIn("Odds", labels)
        self.assertNotIn("Edge", labels)

    def test_matched_pick_populates_market_and_odds_metrics(self) -> None:
        pick = {"price": 150.0, "model_probability": 0.35, "market_probability": 0.40, "edge": -0.05}
        card = props._prop_rank_card(self._ROW, league="epl", week=1, season=2026, pick=pick)
        self.assertEqual(card["market"], "Anytime Goalscorer")
        metrics_by_label = {m["label"]: m["value"] for m in card["metrics"]}
        self.assertEqual(metrics_by_label["Odds"], "+150")
        self.assertEqual(metrics_by_label["Model probability"], "35.0%")
        self.assertEqual(metrics_by_label["Edge"], "-5.0%")


class PropPicksByPlayerTests(unittest.TestCase):
    def test_matches_by_normalized_player_name_across_dates(self) -> None:
        rows_by_date = {
            "2026-08-20": ({"player": "Some Other Player", "market": "PROP", "price": "100"},),
            "2026-08-21": (
                {"player": "Kévin Denkey", "market": "PROP", "price": "150", "model_probability": "0.35"},
                {"player": "Ghost", "market": "ML", "price": "-110"},
            ),
        }
        with patch.object(props, "week_date_list", return_value=list(rows_by_date.keys())), patch.object(
            props, "picks_rows", side_effect=lambda league, date_str: rows_by_date[date_str]
        ):
            picks = props._prop_picks_by_player("mls", 1, 2026)
        self.assertIn("kevin denkey", picks)
        self.assertEqual(picks["kevin denkey"]["price"], "150")
        self.assertNotIn("ghost", picks)


if __name__ == "__main__":
    unittest.main()
