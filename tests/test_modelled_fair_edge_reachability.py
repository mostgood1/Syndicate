"""The one-sided model view: is it REACHED, and does it reach Layer 2 (`#601`).

WHAT WENT WRONG, because these tests are shaped by it rather than by the API.

`book_margin_model.modelled_fair_edge` prices a projection against a modelled
fair on rows the market cannot price two-sidedly. It was written for that, has
its own field, its own basis, and a user decision behind it (2026-08-17). It had
never run in production. Two breaks in series:

  1. ORDERING. It reads `row["modelled_fair"]`, which `attach_margin_model`
     writes -- and all three production paths call `attach_projections` FIRST.
     The field was absent at the only moment it was ever read.
  2. THE READER. `layer2_board._model_edge_for` accepted `edge_vs_market_pct`
     and nothing else, so even a populated field would never have ranked.

Measured on production 2026-08-30, `/api/board/layer1?window=slate` over
mlb/wnba/ncaaf/soccer: 13,262 rows, 9,161 carrying a `modelled_fair`,
`edge_vs_modelled_fair_pct` present on **0**.

SO THE FIRST TEST HERE IS A REACHABILITY TEST, not a correctness test. `off !=
on` is the bar this repo sets for anything behind a hop, because a correctness
test over a hand-built projection would have passed against the broken code the
entire time -- `modelled_fair_edge` itself was never wrong.
"""

from __future__ import annotations

import unittest

from syndicate.features.shared.board_enrichment import (
    attach_margin_model,
    attach_modelled_fair_edges,
)
from syndicate.features.shared.book_margin_model import EDGE_FIELD
from syndicate.features.shared.layer2_board import (
    MODEL_EDGE_BASIS_MARKET,
    MODEL_EDGE_BASIS_MODELLED,
    _model_edge_for,
    model_edge_basis,
)


def _two_sided(player: str, over: int = -140, under: int = 115) -> dict:
    """A row whose hold the margin profile can measure. Twelve of these make a
    profile; without them `build_margin_profile` has nothing to fit and the
    one-sided row silently stays unmodelled."""
    return {
        "sport": "mlb", "market": "batter_hits", "kind": "prop", "segment": "full",
        "player_name": player, "line": 0.5, "sides": ["over", "under"],
        "home_team": "New York Yankees", "away_team": "Boston Red Sox",
        "commence_time": "2026-08-30T23:05:00+00:00",
        "best": {
            "over": {"price": over, "bookmaker": "fanduel", "books_quoting": 8},
            "under": {"price": under, "bookmaker": "fanduel", "books_quoting": 8},
        },
        "cells": {"fanduel": {"over": {"price": over}, "under": {"price": under}}},
    }


def _one_sided(*, market="batter_home_runs", sides=("over",), price=250,
               player="Aaron Judge", projection=None) -> dict:
    row = {
        "sport": "mlb", "market": market, "kind": "prop", "segment": "full",
        "player_name": player, "line": 0.5, "sides": list(sides),
        "home_team": "New York Yankees", "away_team": "Boston Red Sox",
        "commence_time": "2026-08-30T23:05:00+00:00",
        "best": {sides[0]: {"price": price, "bookmaker": "fanduel", "books_quoting": 8}},
        "cells": {"fanduel": {sides[0]: {"price": price}}},
    }
    if projection is not None:
        row["projection"] = projection
    return row


def _projection(prob=0.31, side="over", reason="one-sided market: no two-sided fair to price against"):
    return {
        "model_prob_over": prob,
        "side": side,
        "source": "test",
        "edge_vs_market_pct": None,
        "edge_unavailable_reason": reason,
    }


class ReachedFromTheMarginHop(unittest.TestCase):
    """`attach_margin_model` is the ONE hop every production path runs after
    projections. If the sweep is not reached from there it is not reached at
    all, and that is the defect this file exists for."""

    def _grid(self, one):
        return [_two_sided(f"P{i}") for i in range(12)] + [one]

    def test_off_vs_on_the_projection_hop_cannot_price_it(self):
        """The exact production ordering, reproduced: at the moment a projection
        join runs, `modelled_fair` does not exist, so the fallback is a no-op."""
        from syndicate.features.shared.book_margin_model import modelled_fair_edge

        row = _one_sided(projection=_projection())
        self.assertNotIn("modelled_fair", row)
        self.assertIsNone(modelled_fair_edge(row, model_prob=0.31, side="over"))

    def test_the_margin_hop_now_prices_it(self):
        one = _one_sided(projection=_projection())
        coverage = attach_margin_model(self._grid(one))
        self.assertEqual(coverage["rows_modelled"], 1, "the margin model must have filled the row")
        self.assertEqual(coverage["modelled_edge_rows_priced"], 1)
        self.assertIsNotNone(one["projection"].get(EDGE_FIELD))
        self.assertEqual(one["projection"].get("modelled_fair_side"), "over")

    def test_the_reason_no_longer_contradicts_the_row(self):
        """A row serving a priced number two columns over must not also say
        nothing could be priced."""
        one = _one_sided(projection=_projection())
        attach_margin_model(self._grid(one))
        reason = one["projection"]["edge_unavailable_reason"]
        self.assertIn("one-sided market", reason, "the original refusal is preserved")
        self.assertIn(EDGE_FIELD, reason, "and it now points at what WAS priced")

    def test_it_is_idempotent(self):
        one = _one_sided(projection=_projection())
        grid = self._grid(one)
        attach_margin_model(grid)
        first = one["projection"][EDGE_FIELD]
        second_pass = attach_margin_model(grid)
        self.assertEqual(one["projection"][EDGE_FIELD], first)
        self.assertEqual(second_pass["modelled_edge_rows_priced"], 0, "nothing left to price")


class SidePolarity(unittest.TestCase):
    """The key comes from the ROW; only the polarity comes from the projection.

    Measured on production: 1,278 soccer goal-scorer rows stamp `side: "over"`
    against a `("yes",)` row, 1,939 stamp the PLAYER'S NAME, and 73 stamp the
    genuine complement. Getting the third case wrong inverts an edge."""

    def _priced(self, row):
        modelled = {
            row["sides"][0]: {
                "fair_probability": 0.25,
                "fair_method": "book_margin_model",
                "assumed_hold_pct": 5.0,
                "basis": "fanduel/player_prop",
            }
        }
        row["modelled_fair"] = modelled
        return attach_modelled_fair_edges([row])

    def test_same_polarity_is_priced_directly(self):
        row = _one_sided(projection=_projection(prob=0.31, side="over"))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_rows_priced"], 1)
        self.assertEqual(report["modelled_edge_rows_complemented"], 0)
        self.assertAlmostEqual(row["projection"][EDGE_FIELD], (0.31 - 0.25) * 100, places=2)

    def test_over_prices_a_yes_only_market(self):
        """`over` and `yes` are the same outcome where there is no other side."""
        row = _one_sided(market="player_goal_scorer_anytime", sides=("yes",),
                         projection=_projection(prob=0.31, side="over"))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_rows_priced"], 1)
        self.assertEqual(row["projection"]["modelled_fair_side"], "yes")

    def test_opposite_polarity_is_COMPLEMENTED_not_stamped(self):
        """A model framed `under` against an `over`-only quote. Stamping 0.31
        here would publish P(under) as P(over) -- right number, wrong outcome."""
        row = _one_sided(sides=("over",), projection=_projection(prob=0.31, side="under"))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_rows_complemented"], 1)
        self.assertAlmostEqual(row["projection"][EDGE_FIELD], (0.69 - 0.25) * 100, places=2)

    def test_player_name_as_side_is_the_affirmative(self):
        row = _one_sided(market="player_first_goal_scorer", sides=("yes",),
                         player="Paulo Dybala",
                         projection=_projection(prob=0.10, side="paulo dybala"))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_rows_priced"], 1)
        self.assertAlmostEqual(row["projection"][EDGE_FIELD], (0.10 - 0.25) * 100, places=2)

    def test_an_unrecognised_side_REFUSES_and_says_so(self):
        """Never default to the affirmative. An unknown token could be either
        outcome, and guessing inverts an edge on a board that sorts by edge."""
        row = _one_sided(sides=("over",), player="",
                         projection=_projection(prob=0.31, side="somebody else"))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_rows_priced"], 0)
        self.assertEqual(report["modelled_edge_refusals"], {"projection_side_polarity_unknown": 1})
        self.assertIsNone(row["projection"].get(EDGE_FIELD))

    def test_an_empty_side_refuses(self):
        row = _one_sided(sides=("over",), player="",
                         projection=_projection(prob=0.31, side=""))
        report = self._priced(row)
        self.assertEqual(report["modelled_edge_refusals"], {"projection_side_polarity_unknown": 1})


class WhatMustNotBeTouched(unittest.TestCase):
    def test_a_measured_edge_is_never_displaced(self):
        row = _one_sided(projection=_projection())
        row["projection"]["edge_vs_market_pct"] = 4.2
        row["modelled_fair"] = {"over": {"fair_probability": 0.25, "fair_method": "book_margin_model"}}
        report = attach_modelled_fair_edges([row])
        self.assertEqual(report["modelled_edge_rows_considered"], 0)
        self.assertEqual(row["projection"]["edge_vs_market_pct"], 4.2)
        self.assertIsNone(row["projection"].get(EDGE_FIELD))

    def test_a_live_or_settled_row_is_skipped(self):
        """`live_edge_policy` refused these deliberately. Filling a modelled
        edge here would route around a suppression, which is the `gating one
        instance of a shared cause` shape."""
        for reason in (
            "game is live: a pregame projection cannot be priced against a live market",
            "game is final: the market is settled, so there is no price to beat",
            "the over is already decided, so the market is settled",
        ):
            with self.subTest(reason=reason):
                row = _one_sided(projection=_projection(reason=reason))
                row["modelled_fair"] = {"over": {"fair_probability": 0.25, "fair_method": "book_margin_model"}}
                report = attach_modelled_fair_edges([row])
                self.assertEqual(report["modelled_edge_rows_priced"], 0)
                self.assertEqual(report["modelled_edge_refusals"], {"live_or_settled_market": 1})

    def test_a_row_with_no_projection_is_not_invented(self):
        row = _one_sided()
        row["modelled_fair"] = {"over": {"fair_probability": 0.25, "fair_method": "book_margin_model"}}
        report = attach_modelled_fair_edges([row])
        self.assertEqual(report["modelled_edge_rows_considered"], 0)
        self.assertNotIn("projection", row)

    def test_a_non_margin_model_fair_is_refused(self):
        """A real two-sided consensus that happens to sit in `modelled_fair`
        must not be priced here -- that would duplicate `edge_vs_market_pct`
        under a name that says it is modelled."""
        row = _one_sided(projection=_projection())
        row["modelled_fair"] = {"over": {"fair_probability": 0.25, "fair_method": "two_sided_consensus"}}
        report = attach_modelled_fair_edges([row])
        self.assertEqual(report["modelled_edge_refusals"], {"modelled_fair_edge_refused": 1})


class ItReachesLayer2(unittest.TestCase):
    """Half a fix is inert. The enrichment can price every row on the board and
    change nothing unless `_model_edge_for` reads it."""

    def _row(self, *, edge=6.0, priced_side="over"):
        return {
            "sides": ["over"],
            "projection": {
                "model_prob_over": 0.31,
                "side": "over",
                "edge_vs_market_pct": None,
                EDGE_FIELD: edge,
                "modelled_fair_side": priced_side,
            },
        }

    def test_layer2_now_ranks_the_modelled_edge(self):
        self.assertEqual(_model_edge_for(self._row(), "over"), 6.0)

    def test_the_basis_says_which_fair_it_was(self):
        self.assertEqual(model_edge_basis(self._row(), "over"), MODEL_EDGE_BASIS_MODELLED)

    def test_a_measured_edge_still_wins_and_is_labelled_as_such(self):
        row = self._row()
        row["projection"]["edge_vs_market_pct"] = 2.5
        self.assertEqual(_model_edge_for(row, "over"), 2.5)
        self.assertEqual(model_edge_basis(row, "over"), MODEL_EDGE_BASIS_MARKET)

    def test_the_WRONG_side_is_dropped_and_never_negated(self):
        """There is no complement identity here. Each side of a one-sided quote
        is priced from its own book's hold, so the two do not sum to one and
        `-edge` answers nothing."""
        row = self._row(priced_side="over")
        self.assertIsNone(_model_edge_for(row, "under"))
        self.assertIsNone(model_edge_basis(row, "under"))

    def test_it_clears_the_same_ceiling_as_the_measured_edge(self):
        self.assertIsNone(_model_edge_for(self._row(edge=15.5), "over"))
        self.assertEqual(_model_edge_for(self._row(edge=14.9), "over"), 14.9)

    def test_an_unpriced_side_reports_no_basis(self):
        row = self._row()
        row["projection"].pop(EDGE_FIELD)
        self.assertIsNone(_model_edge_for(row, "over"))
        self.assertIsNone(model_edge_basis(row, "over"))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# `[2026-08-30, user decision]` -- EV against the MODEL's probability on rows
# whose market EV is a hold restatement.
# ---------------------------------------------------------------------------


class ModelBasedEv(unittest.TestCase):
    """The join fix alone left these rows unreachable, and that was measured.

    2,611 rows gained a correct model edge and still topped out at -4.73 against
    a live shortlist whose #50 was +0.64, because `expected_value_pct(price,
    book_margin_model_fair)` is `-hold` for every such row regardless of the
    bet. The value term now comes from the model's own probability instead.
    """

    def _row(self, price=250, model_prob=0.31, fair=0.25):
        return {
            "sides": ["over"],
            "best": {"over": {"price": price, "books_quoting": 6}},
            "modelled_fair": {
                "over": {
                    "fair_probability": fair,
                    "fair_method": "book_margin_model",
                    "assumed_hold_pct": 5.0,
                    "basis": "fanduel/player_prop",
                }
            },
            "projection": {
                "model_prob_over": model_prob,
                "side": "over",
                "edge_vs_market_pct": None,
            },
        }

    def test_a_hold_restatement_row_is_valued_on_the_model(self):
        from syndicate.features.shared.layer2_board import _model_value_ev
        from syndicate.features.shared.opportunity_signals import expected_value_pct

        row = self._row()
        got = _model_value_ev(row, "over", 250, "book_margin_model")
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got, expected_value_pct(250, 0.31), places=6)
        # And it is NOT the hold restatement it replaces.
        self.assertNotAlmostEqual(got, expected_value_pct(250, 0.25), places=3)

    def test_a_measured_two_sided_fair_is_left_alone(self):
        """Where a real consensus exists, `ev_pct` is a MEASURED market EV and
        the model already enters through the capped sim term. Substituting there
        would replace a measured number with a modelled one."""
        from syndicate.features.shared.layer2_board import _model_value_ev

        self.assertIsNone(
            _model_value_ev(self._row(), "over", 250, "two_sided_consensus")
        )
        self.assertIsNone(_model_value_ev(self._row(), "over", 250, None))

    def test_no_model_probability_means_no_substitution(self):
        from syndicate.features.shared.layer2_board import _model_value_ev

        row = self._row()
        row["projection"]["model_prob_over"] = None
        self.assertIsNone(_model_value_ev(row, "over", 250, "book_margin_model"))

    def test_a_degenerate_probability_is_refused(self):
        """P == 1 makes EV unbounded. An already-decided outcome priced as a
        live one is the largest fake number a board can carry (`#414`)."""
        from syndicate.features.shared.layer2_board import _model_value_ev

        for prob in (0.0, 1.0):
            with self.subTest(prob=prob):
                row = self._row(model_prob=prob)
                self.assertIsNone(_model_value_ev(row, "over", 250, "book_margin_model"))

    def test_the_wrong_side_gets_the_complement_not_the_over(self):
        from syndicate.features.shared.layer2_board import _model_value_ev
        from syndicate.features.shared.opportunity_signals import expected_value_pct

        row = self._row(model_prob=0.31)
        row["sides"] = ["over", "under"]
        got = _model_value_ev(row, "under", 250, "book_margin_model")
        self.assertAlmostEqual(got, expected_value_pct(250, 0.69), places=6)
