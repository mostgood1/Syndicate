"""Joining the live capture to its pregame anchor -- and publishing no price.

TWO THINGS ARE PINNED HERE and they are equally important.

1. **No probability escapes.** `build_live_prop_index` keys on
   `liveModelProbOver`; a row carrying one would be picked up and priced by the
   prop join. These rows carry none, because the live remainder distribution is
   unmeasured -- see the module docstring. If a probability-shaped key ever
   appears, someone has routed around the same refusal the board already makes
   by name for the un-backtested totals estimator.
2. **An unmatched player is COUNTED, not dropped.** Name-joining is the
   machinery whose 91% miss (`miss_no_market_alias`, 903 of 989) this project
   has already paid a full investigation for. A silent zero and a zero with a
   named cause need different fixes.
"""
from __future__ import annotations

import unittest

from syndicate.features.shared.wnba_live_prop_rows import (
    build_live_prop_rows,
    index_sim_players,
    normalize_name,
)


def _sim(rows_home, rows_away=()):
    return {"players": {"home": list(rows_home), "away": list(rows_away)}}


_ANCHOR = {"player_name": "Paige Bueckers", "min_mean": 30.0,
           "pts_mean": 18.0, "reb_mean": 6.0, "ast_mean": 4.0, "threes_mean": 2.0}
_LIVE = {"player": "Paige Bueckers", "team_tri": "DAL", "mp": "9",
         "pts": 6.0, "reb": 2.0, "ast": 1.0, "threes_made": 1.0}


class NameMatchingTests(unittest.TestCase):
    def test_accents_and_punctuation_fold_to_one_key(self) -> None:
        for variant in ("A'ja Wilson", "Aja Wilson", "A’ja  Wilson", "AJA WILSON"):
            with self.subTest(variant=variant):
                self.assertEqual(normalize_name(variant), "aja wilson")

    def test_hyphens_fold(self) -> None:
        self.assertEqual(normalize_name("Olivia Nelson-Ododa"),
                         normalize_name("Olivia Nelson Ododa"))

    def test_index_covers_both_sides(self) -> None:
        idx = index_sim_players(_sim([_ANCHOR], [{"player_name": "Kelsey Mitchell",
                                                  "min_mean": 33.0, "pts_mean": 20.0}]))
        self.assertIn("paige bueckers", idx)
        self.assertIn("kelsey mitchell", idx)

    def test_a_shapeless_sim_yields_an_empty_index_not_a_raise(self) -> None:
        for bad in (None, {}, {"players": None}, {"players": {"home": 3}}):
            with self.subTest(bad=bad):
                self.assertEqual(index_sim_players(bad), {})


class RowTests(unittest.TestCase):
    def test_a_matched_player_gets_a_row_per_stat_with_a_projection(self) -> None:
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]), game_minutes_remaining=30.0)
        self.assertEqual(out["players_matched"], 1)
        self.assertEqual(len(out["rows"]), 4, "pts, reb, ast, threes")
        markets = {r["market"] for r in out["rows"]}
        self.assertEqual(markets, {"points", "rebounds", "assists", "threes"})
        pts = next(r for r in out["rows"] if r["market"] == "points")
        self.assertIsNotNone(pts["liveProjectedStat"])
        self.assertEqual(pts["current"], 6.0)
        self.assertEqual(out["rows_projected"], 4)

    def test_the_projection_sits_between_the_anchor_and_the_pace(self) -> None:
        """6 pts in 9 min against an 18-pt anchor: pulled up, not chasing 20."""
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]))
        pts = next(r for r in out["rows"] if r["market"] == "points")
        self.assertGreater(pts["liveProjectedStat"], 6.0)
        self.assertLess(pts["liveProjectedStat"], 20.0)

    def test_an_unmatched_player_is_NAMED_not_dropped(self) -> None:
        stranger = dict(_LIVE, player="Nobody Here")
        out = build_live_prop_rows([stranger], _sim([_ANCHOR]))
        self.assertEqual(out["players_seen"], 1)
        self.assertEqual(out["players_matched"], 0)
        self.assertEqual(out["players_unmatched"], ["Nobody Here"])
        self.assertEqual(out["rows"], [])

    def test_a_bench_player_with_no_minutes_is_withheld_BY_REASON(self) -> None:
        bench = {"player": "Paige Bueckers", "team_tri": "DAL", "mp": None,
                 "pts": None, "reb": None, "ast": None, "threes_made": None}
        out = build_live_prop_rows([bench], _sim([_ANCHOR]))
        self.assertEqual(out["rows_projected"], 0)
        self.assertEqual(sum(out["withheld_by_reason"].values()), 4)
        self.assertIn("no_live_stat_or_minutes_for_this_player", out["withheld_by_reason"])

    def test_counters_survive_shapeless_input(self) -> None:
        out = build_live_prop_rows([None, 3, _LIVE], _sim([_ANCHOR]))
        self.assertEqual(out["players_seen"], 1)


class NoPriceEscapesTests(unittest.TestCase):
    def test_no_row_carries_a_probability_shaped_key(self) -> None:
        """THE GUARD. A liveModelProbOver here would be picked up and PRICED."""
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]))
        banned = ("liveModelProbOver", "prob", "probability", "p_over",
                  "edge", "edge_pp", "model_prob_over")
        for row in out["rows"]:
            for key in banned:
                self.assertNotIn(key, row, f"{key} would reach the prop join")

    def test_every_row_says_it_is_unpriced_and_why(self) -> None:
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]))
        for row in out["rows"]:
            self.assertFalse(row["priceable"])
            self.assertEqual(row["not_priced_reason"],
                             "live_prop_projection_has_no_measured_interval")
        self.assertEqual(out["priced"], 0)


if __name__ == "__main__":
    unittest.main()
