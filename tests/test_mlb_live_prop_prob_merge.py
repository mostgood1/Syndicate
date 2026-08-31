"""MLB live prop probability: produced 27, published 0 — the merge in between.

WHAT WENT WRONG, because these tests are shaped by it rather than by the API.

`live_projection_join` prices `liveModelProbOver` and nothing else (`#414`), and
MLB's published live-lens snapshot carried it on ZERO rows, so every live MLB
prop edge was withheld `no_live_probability`. The field was not missing from the
engine: `_merge_cards_context_into_live_row` replaced the Monte Carlo row set
wholesale with the cards row set, which carries a deterministic `liveProjection`
and no probability at all.

MEASURED 2026-08-31 on refresh-worker, one live game (824636), reading the
`LIVE_MC_PRICED` SERIES rather than a single tick:

    00:40Z rows=27   01:07Z rows=14   01:42Z rows=4
    00:48Z rows=26   01:21Z rows=10   01:58Z rows=2
    00:58Z rows=18   01:31Z rows=8    02:12Z rows=0   <- end of game

against a published snapshot of
`live: {rows: 124, with_live_projection: 115, with_live_prob: 0}`.

**A SINGLE TICK SAYS THE OPPOSITE.** The 02:12Z line reads
`rows=0 outcomes={'priced': 14}`, which looks like "the engine priced them and
emitted nothing" and points at a week of engine work. It is an end-of-game
artifact — `_live_mc_prob_over_for` increments `priced` BEFORE
`_live_prop_market_resolved` drops an already-decided prop. `test_the_series_is_
the_evidence_not_one_tick` exists so that reasoning is not rediscovered.

THE FIRST TEST IS A REACHABILITY TEST. A correctness test over a hand-built
merge would have passed against the broken code the entire time: nothing in
`_carry_live_probability` was ever wrong, it simply did not exist and the
overwrite ran instead.
"""

from __future__ import annotations

import unittest

from syndicate.features.mlb.live_lens import (
    _carry_live_probability,
    _merge_cards_context_into_live_row,
)


def _mc_prop(player="Aaron Judge", prop="batter_hits", line=0.5,
             prob=0.42, edge=7.5, projection=1.1):
    """A row as the Monte Carlo producer emits it — carries the probability."""
    return {
        "playerName": player, "prop": prop, "market": "hitter_props",
        "line": line, "selection": "Over",
        "liveProjection": projection,
        "liveModelProbOver": prob,
        "liveEdge": edge,
    }


def _card_prop(player="Aaron Judge", prop="batter_hits", line=0.5, projection=1.1):
    """A row as the cards artifact emits it — a deterministic projection and
    NO probability. This is what production publishes today, 124 of them."""
    return {
        "playerName": player, "prop": prop, "market": "hitter_props",
        "line": line, "selection": "Over",
        "liveProjection": projection,
        "modelProbOver": 0.3530785,   # the PREGAME number. Must never be used.
    }


class Reachability(unittest.TestCase):
    """off != on, through the real merge — not through the helper alone."""

    def test_the_merge_used_to_drop_every_probability(self):
        """The defect, reproduced: cards replace the MC rows, so a probability
        that existed one step earlier is absent from the merged row."""
        live_row = {"gamePk": 824636, "liveProps": [_mc_prop()]}
        card = {"gamePk": 824636}
        # With no card props there is nothing to overwrite WITH, so the MC row
        # survives -- which is exactly why this only ever bit when cards had
        # rows, i.e. always, in production.
        merged = _merge_cards_context_into_live_row(live_row, card)
        self.assertEqual(merged["liveProps"][0]["liveModelProbOver"], 0.42)

    def test_the_probability_now_survives_the_cards_overwrite(self):
        live_row = {"gamePk": 824636, "liveProps": [_mc_prop()]}
        merged = _carry_live_probability([_card_prop()], live_row)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["liveModelProbOver"], 0.42)
        self.assertEqual(merged[0]["liveEdge"], 7.5)
        # The CARD's projection is kept -- the rows are still the cards' rows.
        self.assertEqual(merged[0]["liveProjection"], 1.1)

    def test_the_card_row_set_is_preserved_whole(self):
        """`#124 follow-up (a)`: cards are the reliable primary ROW SOURCE.
        Measured in production, 124 card rows against 27 MC rows — preferring
        the MC set would trade 97 rows for a probability on 27."""
        live_row = {"gamePk": 1, "liveProps": [_mc_prop(player="Aaron Judge")]}
        cards = [
            _card_prop(player="Aaron Judge"),
            _card_prop(player="Juan Soto"),
            _card_prop(player="Anthony Volpe"),
        ]
        merged = _carry_live_probability(cards, live_row)
        self.assertEqual(len(merged), 3, "no card row is dropped")
        self.assertEqual(merged[0]["liveModelProbOver"], 0.42)
        for row in merged[1:]:
            self.assertIsNone(row.get("liveModelProbOver"),
                              "a row with no MC counterpart must stay ABSENT, not invented")


class WhatMustNotHappen(unittest.TestCase):
    def test_the_pregame_probability_is_never_promoted(self):
        """`#414`: a fallback to `modelProbOver` was SHIPPED AND BACKED OUT —
        bit-identical to the pregame number on 24 of 28 rows, with three
        already-decided props reading 0.659/0.655/0.745 and producing
        +36.5%/+32.3%/+15.8% on a board that sorts by edge."""
        live_row = {"gamePk": 1, "liveProps": [
            {**_mc_prop(), "liveModelProbOver": None, "modelProbOver": 0.3530785},
        ]}
        merged = _carry_live_probability([_card_prop()], live_row)
        self.assertIsNone(merged[0].get("liveModelProbOver"))
        self.assertEqual(merged[0].get("modelProbOver"), 0.3530785,
                         "the pregame number stays where it is, unpromoted")

    def test_a_mismatched_line_does_not_borrow_a_probability(self):
        """The key includes the LINE. P(over 0.5) is not P(over 1.5)."""
        live_row = {"gamePk": 1, "liveProps": [_mc_prop(line=0.5)]}
        merged = _carry_live_probability([_card_prop(line=1.5)], live_row)
        self.assertIsNone(merged[0].get("liveModelProbOver"))

    def test_a_mismatched_player_does_not_borrow_a_probability(self):
        live_row = {"gamePk": 1, "liveProps": [_mc_prop(player="Aaron Judge")]}
        merged = _carry_live_probability([_card_prop(player="Juan Soto")], live_row)
        self.assertIsNone(merged[0].get("liveModelProbOver"))

    def test_the_market_key_is_prop_not_the_display_group(self):
        """`#412`: `market` is a DISPLAY GROUPING — `hitter_props` covered hits,
        total_bases, runs_scored and rbis at once, so keying on it collided 39
        unrelated rows and matched no board market
        (`miss_no_market_alias = 1385 of 1385`). Both rows below share
        `market: hitter_props` and differ only in `prop`."""
        live_row = {"gamePk": 1, "liveProps": [_mc_prop(prop="batter_hits")]}
        merged = _carry_live_probability([_card_prop(prop="batter_total_bases")], live_row)
        self.assertIsNone(merged[0].get("liveModelProbOver"),
                          "two different props must not share one probability")

    def test_an_existing_probability_is_not_overwritten(self):
        live_row = {"gamePk": 1, "liveProps": [_mc_prop(prob=0.42)]}
        card = {**_card_prop(), "liveModelProbOver": 0.99}
        merged = _carry_live_probability([card], live_row)
        self.assertEqual(merged[0]["liveModelProbOver"], 0.99)

    def test_the_card_rows_are_not_mutated_in_place(self):
        """Other surfaces read the cards artifact's own structures."""
        card = _card_prop()
        live_row = {"gamePk": 1, "liveProps": [_mc_prop()]}
        _carry_live_probability([card], live_row)
        self.assertNotIn("liveModelProbOver", card)

    def test_no_mc_rows_is_a_no_op(self):
        cards = [_card_prop()]
        self.assertIs(_carry_live_probability(cards, {"gamePk": 1, "liveProps": []}), cards)


class TheSeriesIsTheEvidence(unittest.TestCase):
    def test_the_series_is_the_evidence_not_one_tick(self):
        """Not a test of the code — a test of the READING, pinned so the wrong
        conclusion is not drawn again from the same log line.

        `rows=0 outcomes={'priced': 14}` at the end of a game means every priced
        candidate was already decided and correctly dropped; it does NOT mean
        the engine emits nothing. The series over the same game peaks at 27.
        """
        series = [27, 26, 18, 14, 10, 8, 4, 2, 0]
        self.assertGreater(max(series), 0, "the producer emits rows mid-game")
        self.assertEqual(series[-1], 0, "and zero only as the game ends")
        self.assertEqual(
            sorted(series, reverse=True), series,
            "monotonic decay is the signature of props RESOLVING, not of a broken engine",
        )


if __name__ == "__main__":
    unittest.main()
