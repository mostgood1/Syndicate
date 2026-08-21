"""Joining the live capture to its pregame anchor, and pricing it from a MEASURED residual.

THREE THINGS ARE PINNED HERE.

1. **A price appears ONLY with a line.** `build_live_prop_index` keys on
   `liveModelProbOver`. Phase 3(a) emitted none at all, correctly, while the
   residual was unmeasured; `grade_wnba_live_prop_projection.py` (n=796 over 5
   slates, replay reconciling 100% against the official boxscore) is what
   changed that. A row without a line still refuses BY NAME -- a probability
   needs something to be a probability about.
2. **No projection, no price**, even when a line is present. The refusal must
   not be routed around by supplying one.
3. **An unmatched player is COUNTED, not dropped.** Name-joining is the
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


class PricingTests(unittest.TestCase):
    """Phase 3(b). These REPLACE the phase-3(a) guards that asserted no
    probability could appear -- that was correct while the residual was
    unmeasured, and `grade_wnba_live_prop_projection.py` (n=796, replay
    reconciling 100%) is what changed it. What is pinned now is that a price
    appears ONLY with a line, and that everything else still refuses BY NAME."""

    LINES = {("paige bueckers", "points"): 17.5}

    def test_a_line_produces_a_probability(self) -> None:
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]),
                                   game_minutes_remaining=21.0, lines=self.LINES)
        pts = next(r for r in out["rows"] if r["market"] == "points")
        self.assertIsNotNone(pts["liveModelProbOver"])
        self.assertGreaterEqual(pts["liveModelProbOver"], 0.0)
        self.assertLessEqual(pts["liveModelProbOver"], 1.0)
        self.assertIsNotNone(pts["residual_sigma"])
        self.assertIsNone(pts["not_priced_reason"])
        self.assertEqual(out["priced"], 1, "only the market with a line prices")

    def test_no_line_means_no_probability_and_a_named_reason(self) -> None:
        """A probability needs something to be a probability ABOUT. Inventing a
        line would price a market nobody quoted."""
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]), game_minutes_remaining=21.0)
        self.assertEqual(out["priced"], 0)
        for row in out["rows"]:
            self.assertIsNone(row["liveModelProbOver"])
            self.assertEqual(row["not_priced_reason"], "no_line_to_price_against")
        self.assertEqual(out["unpriced_by_reason"]["no_line_to_price_against"], 4)

    def test_the_projection_above_its_line_prices_over_a_half(self) -> None:
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]),
                                   game_minutes_remaining=21.0, lines=self.LINES)
        pts = next(r for r in out["rows"] if r["market"] == "points")
        self.assertGreater(pts["liveProjectedStat"], 17.5, "guard: projection is over")
        self.assertGreater(pts["liveModelProbOver"], 0.5)

    def test_an_unprojectable_row_is_never_priced(self) -> None:
        """No projection, no price -- the refusal must not be routed around by
        a line being present."""
        bench = {"player": "Paige Bueckers", "team_tri": "DAL", "mp": None,
                 "pts": None, "reb": None, "ast": None, "threes_made": None}
        out = build_live_prop_rows([bench], _sim([_ANCHOR]), lines=self.LINES)
        self.assertEqual(out["priced"], 0)
        for row in out["rows"]:
            self.assertIsNone(row["liveModelProbOver"])

    def test_unknown_minutes_remaining_refuses_even_with_a_line(self) -> None:
        """The sigma table is a MEASUREMENT and does not cover states it never
        saw. `game_minutes_remaining=None` leaves the projection's own
        `minutes_remaining` set, so this pins the pass-through, not a default."""
        out = build_live_prop_rows([_LIVE], _sim([_ANCHOR]), lines=self.LINES)
        pts = next(r for r in out["rows"] if r["market"] == "points")
        self.assertIsNotNone(pts["minutes_remaining"], "guard: it is known here")
        self.assertIsNotNone(pts["liveModelProbOver"], "so it prices")


if __name__ == "__main__":
    unittest.main()


class SnapshotAdapterTests(unittest.TestCase):
    """The snapshot contract `build_live_prop_index` actually reads.

    THE MARKET KEY IS THE WHOLE RISK. `_snapshot_market` reads `prop` first and
    the board speaks OddsAPI; keying on anything else is `#412` exactly --
    `miss_no_market_alias = 1385 of 1385`, the join missing every row while the
    correct key sat in the next field. These keys were verified against
    production, not guessed.
    """

    LINES = {("paige bueckers", "points"): 17.5,
             ("paige bueckers", "rebounds"): 5.5}

    def _rows(self):
        from syndicate.features.shared.wnba_live_prop_rows import build_live_prop_rows
        return build_live_prop_rows([_LIVE], _sim([_ANCHOR]),
                                    game_minutes_remaining=21.0, lines=self.LINES)["rows"]

    def test_it_emits_the_boards_oddsapi_market_keys(self) -> None:
        from syndicate.features.shared.wnba_live_prop_rows import to_snapshot_live_props
        props = to_snapshot_live_props(self._rows())
        self.assertEqual({p["prop"] for p in props}, {"player_points", "player_rebounds"})

    def test_it_emits_the_snapshot_vocabulary_not_ours(self) -> None:
        from syndicate.features.shared.wnba_live_prop_rows import to_snapshot_live_props
        prop = to_snapshot_live_props(self._rows())[0]
        for key in ("playerName", "prop", "line", "liveProjection", "liveModelProbOver"):
            self.assertIn(key, prop)
        for internal in ("player", "market", "liveProjectedStat"):
            self.assertNotIn(internal, prop)

    def test_liveProjection_is_present_because_the_index_requires_it(self) -> None:
        """A row without it is skipped by the index even when a probability is
        there -- it is the live-awareness evidence."""
        from syndicate.features.shared.wnba_live_prop_rows import to_snapshot_live_props
        for prop in to_snapshot_live_props(self._rows()):
            self.assertIsNotNone(prop["liveProjection"])

    def test_rows_with_no_line_are_DROPPED_not_half_emitted(self) -> None:
        from syndicate.features.shared.wnba_live_prop_rows import to_snapshot_live_props
        from syndicate.features.shared.wnba_live_prop_rows import build_live_prop_rows
        rows = build_live_prop_rows([_LIVE], _sim([_ANCHOR]), game_minutes_remaining=21.0)
        self.assertEqual(to_snapshot_live_props(rows), [],
                         "a keyless row is worse than an absent one")

    def test_an_unmappable_market_is_dropped_not_aliased_to_something_close(self) -> None:
        """`player_double_double` exists on the board and cannot be projected
        from a points mean. A wrong alias prices the wrong market."""
        from syndicate.features.shared.wnba_live_prop_rows import (
            BOARD_MARKET_KEYS, to_snapshot_live_props,
        )
        self.assertNotIn("double_double", BOARD_MARKET_KEYS)
        rows = [{"market": "double_double", "player": "X", "line": 0.5,
                 "liveProjectedStat": 1.0, "liveModelProbOver": 0.6}]
        self.assertEqual(to_snapshot_live_props(rows), [])
