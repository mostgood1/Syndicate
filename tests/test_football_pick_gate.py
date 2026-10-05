"""The football model's per-market record: a LABEL on every pick, never a filter.

`[2026-10-05, user directive, lane stop-market-withholding]`: "WE HAVE TO STOP
WITHHOLDING MARKETS! ... each bet is at the line level". These tests used to pin
that the gate SUPPRESSED NCAAF model picks; they now pin that nothing is dropped
and that every pick on an unproven model carries the measurement. The registry
tests (unknown -> not servable, the measurement and criterion text) still hold:
"servable" now means "has a recorded win", which is what the label reads.
The original rationale follows.

Measured 2026-08-19, and the reason this gate exists: the NCAAF margin model
loses to the closing line by +3.563 MAE (SE 0.207, t=+17.20) over 2,233 graded
rows -- CLEAN and OUT-OF-SAMPLE (2023 SP+ on 2024 games, production generator,
graded_leak_status {'clean': 2236}). It loses to the OPENING line by nearly as
much, so a served NCAAF pick sells an edge the model has not demonstrated.

The tests that matter here are not "does the gate return False". They are:

  1. off != on -- with the gate closed the served board yields ZERO cards, and
     with it open the SAME board yields cards. A suppression test that only
     asserts emptiness passes just as happily when the board was empty anyway,
     which is how an inert guard gets banked as a win.
  2. the gate is on the SERVED path. Both /ncaaf/picks and /ncaaf/api/picks
     enter build_smartsim_picks_page_context, NOT build_picks_page_context;
     gating only the latter would be invisible in production.
  3. unknown defaults to DENY, so a market nobody measured cannot be served by
     omission.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.football import pick_gate
from syndicate.features.shared.market_basis_edge import MODEL_BASIS
from syndicate.features.football.pick_gate import MarketVerdict
from syndicate.features.football.pick_gate import LIFT_CONDITION
from syndicate.features.football.pick_gate import board_notice
from syndicate.features.football.pick_gate import filter_pick_rows
from syndicate.features.football.pick_gate import is_servable
from syndicate.features.football.pick_gate import market_verdict
from syndicate.features.football.pick_gate import notice_for
from syndicate.features.ncaaf import picks as ncaaf_picks


def _open_ncaaf_markets():
    """Force the three board markets open, leaving the rest of the registry."""
    patched = dict(pick_gate._SERVING_REGISTRY)
    for market in ("spread", "moneyline", "total"):
        # THREE-TUPLE KEY. The registry gained a BASIS dimension on 2026-08-29
        # so a market-basis edge stops sharing a verdict with the model's. A
        # two-tuple key here does not raise -- it simply never matches, so the
        # gate stays shut and `test_off_is_not_on` fails with "gate-open board
        # served nothing", which reads as a broken board rather than a stale
        # fixture.
        patched[("ncaaf", market, MODEL_BASIS)] = MarketVerdict(
            servable=True, reason="TEST: forced open"
        )
    return patch.dict(pick_gate._SERVING_REGISTRY, patched, clear=True)


class DefaultDenyTests(unittest.TestCase):
    def test_unknown_market_is_denied(self) -> None:
        """Absent measurement must not land on the permissive branch."""
        self.assertFalse(is_servable("ncaaf", "some_new_market"))
        self.assertIn("no recorded", market_verdict("ncaaf", "some_new_market").reason)

    def test_unknown_sport_is_denied(self) -> None:
        self.assertFalse(is_servable("cricket", "spread"))

    def test_blank_market_is_denied(self) -> None:
        self.assertFalse(is_servable("ncaaf", ""))
        self.assertFalse(is_servable("ncaaf", None))

    def test_ncaaf_margin_markets_are_suppressed(self) -> None:
        for market in ("spread", "moneyline", "total"):
            self.assertFalse(is_servable("ncaaf", market), market)

    def test_verdict_carries_the_measurement(self) -> None:
        """A suppression without its numbers is an opinion.

        Pins the CLEAN out-of-sample measurement (2023 SP+ -> 2024 games, all
        15 weeks, production generator, graded_leak_status {'clean': 2236}).
        It deliberately fails if the numbers are edited, so an improved
        measurement is a conscious update rather than a silent drift.
        """
        verdict = market_verdict("ncaaf", "spread")
        self.assertEqual(verdict.sample_size, 2233)
        self.assertGreater(verdict.model_metric, verdict.market_metric)
        self.assertIn("12.212", verdict.summary())
        self.assertIn("OUT-OF-SAMPLE", verdict.detail)


class LiftConditionTests(unittest.TestCase):
    """The exit criterion, REPLACED 2026-08-20 and pinned so it cannot drift.

    The old condition -- "paired error at or below the closing line's" -- was
    necessary but far too weak: a model can approach the close on MAE while
    still losing money ATS and still being WORSE THAN A MINDLESS SIDE BET.
    Measured: the model trails always-bet-the-underdog by 4.4 points in NCAAF
    (735 bets) and 4.2 in NFL preseason (95 bets).
    """

    def test_criterion_names_the_naive_baseline(self) -> None:
        """The bar the model currently FAILS, and the reason it was replaced."""
        self.assertIn("naive baseline", LIFT_CONDITION)
        self.assertIn("underdog", LIFT_CONDITION)

    def test_criterion_uses_breakeven_not_fifty_percent(self) -> None:
        """A 51% system loses money; 50% is how a loser reads as an edge."""
        self.assertIn("52.4%", LIFT_CONDITION)
        self.assertIn("LOWER BOUND", LIFT_CONDITION)

    def test_criterion_refuses_mae_as_evidence(self) -> None:
        """MAE is an ENGINE diagnostic, not proof of playability."""
        self.assertIn("NOT evidence of playability", LIFT_CONDITION)

    def test_criterion_requires_bets_not_rows(self) -> None:
        """Per-book rows overstated significance 3.4x on the NFL grade."""
        self.assertIn("BETS, not rows", LIFT_CONDITION)

    def test_both_notice_paths_serve_the_same_criterion(self) -> None:
        """board_notice is what the LIVE page renders.

        Two copies where only one gets updated would show users a criterion
        that is no longer in force -- which is how the old one survived this
        long in the served payload.
        """
        _, suppressed = filter_pick_rows("ncaaf", [{"market": "spread"}])
        self.assertEqual(notice_for("ncaaf", suppressed)["lift_condition"], LIFT_CONDITION)
        self.assertEqual(
            board_notice("ncaaf", ("spread", "moneyline", "total"))["lift_condition"],
            LIFT_CONDITION,
        )


class MarketSpellingTests(unittest.TestCase):
    """The same market reaches this code under several spellings."""

    def test_moneyline_variants_fold_together(self) -> None:
        for spelling in ("moneyline", "MONEYLINE", "moneyline_home", "moneyline_away", "ml", "h2h"):
            self.assertFalse(is_servable("ncaaf", spelling), spelling)

    def test_spread_variants_fold_together(self) -> None:
        for spelling in ("spread", "SPREAD", "spread_home", "ats", "handicap"):
            self.assertFalse(is_servable("ncaaf", spelling), spelling)

    def test_total_variants_fold_together(self) -> None:
        for spelling in ("total", "TOTAL", "totals", "over_under", "ou"):
            self.assertFalse(is_servable("ncaaf", spelling), spelling)

    def test_variants_reach_the_registry_not_just_the_default(self) -> None:
        """Folding must hit the real verdict, not the generic unknown-deny.

        Both are False, so a bare is_servable() assertion cannot tell a working
        fold from a spelling that fell through to the default -- and a fall-
        through would silently lose the measurement in the UI notice.
        """
        self.assertEqual(
            market_verdict("ncaaf", "moneyline_home").reason,
            market_verdict("ncaaf", "moneyline").reason,
        )
        self.assertIsNotNone(market_verdict("ncaaf", "moneyline_home").measured_on)


class FilterAndNoticeTests(unittest.TestCase):
    def test_filter_counts_what_it_withheld(self) -> None:
        rows = [
            {"market": "SPREAD"},
            {"market": "spread"},
            {"market": "moneyline_home"},
            {"market": "total"},
        ]
        kept, unproven = filter_pick_rows("ncaaf", rows)
        self.assertEqual(len(kept), 4, "no row may be dropped")
        self.assertTrue(all(row.get("model_verdict") for row in kept))
        self.assertEqual(unproven, {"spread": 2, "moneyline": 1, "total": 1})

    def test_notice_is_none_when_nothing_suppressed(self) -> None:
        self.assertIsNone(notice_for("ncaaf", {}))
        self.assertIsNone(notice_for("ncaaf", None))

    def test_notice_states_reason_and_lift_condition(self) -> None:
        _, suppressed = filter_pick_rows("ncaaf", [{"market": "spread"}])
        notice = notice_for("ncaaf", suppressed)
        self.assertIn("closing line", notice["headline"])
        self.assertTrue(notice["lift_condition"])
        self.assertIn("12.212", notice["reasons"][0]["reason"])

    def test_board_notice_clears_when_any_market_opens(self) -> None:
        """The board must come back on its own, with no second edit."""
        markets = ("spread", "moneyline", "total")
        self.assertIsNotNone(board_notice("ncaaf", markets))
        patched = dict(pick_gate._SERVING_REGISTRY)
        patched[("ncaaf", "total", MODEL_BASIS)] = MarketVerdict(servable=True, reason="TEST")
        with patch.dict(pick_gate._SERVING_REGISTRY, patched, clear=True):
            self.assertIsNone(board_notice("ncaaf", markets))


class NcaafPickServingTests(unittest.TestCase):
    """The served path (/ncaaf/picks and /ncaaf/api/picks both enter
    build_smartsim_picks_page_context): model picks are SHOWN with their record."""

    def _context(self, cards):
        base = {"rank_cards": cards, "week": 1, "available_weeks": [1], "empty_state": None}
        with patch.object(ncaaf_picks, "_model_picks_context", return_value=base), patch.object(
            ncaaf_picks, "_market_basis_pick_cards", return_value=[]
        ):
            return ncaaf_picks.build_smartsim_picks_page_context(1)

    def test_model_picks_are_served_with_their_record(self) -> None:
        card = {"title": "UGA vs BAMA", "eyebrow": "SmartSim", "list_items": ["Projected spread: UGA by 3"]}
        context = self._context([card])
        self.assertEqual(len(context["rank_cards"]), 1)
        served = context["rank_cards"][0]
        self.assertTrue(any(item.startswith("Model record:") for item in served["list_items"]))
        self.assertIn("closing line", context["warning_panel"]["title"])
        self.assertIsNone(context.get("empty_state"))

    def test_off_equals_on_for_what_is_served(self) -> None:
        """THE test now. A market without a recorded win must serve the SAME
        picks as one with a recorded win -- only the label differs."""
        card = {"title": "UGA vs BAMA", "eyebrow": "SmartSim", "list_items": []}
        closed = self._context([card])
        with _open_ncaaf_markets():
            opened = self._context([card])
        self.assertEqual(len(closed["rank_cards"]), len(opened["rank_cards"]))
        self.assertIn("picks_gate", closed)
        self.assertNotIn("picks_gate", opened)

    def test_the_board_keeps_navigation(self) -> None:
        context = self._context([])
        self.assertTrue(context.get("available_weeks"))
        self.assertIsNotNone(context.get("week"))

    def test_collapse_results_keeps_and_labels_every_row(self) -> None:
        summary = {
            "results": [
                {"home_team": "UGA", "away_team": "BAMA", "market": "spread", "side": "UGA -3.5", "provider": "b", "edge": 0.04},
                {"home_team": "UGA", "away_team": "BAMA", "market": "total", "side": "Over 52.5", "provider": "b", "edge": 0.03},
            ]
        }
        counts: dict[str, int] = {}
        cards = ncaaf_picks._collapse_results(summary, gate_counts=counts)
        self.assertEqual(len(cards), 2)
        for card in cards:
            self.assertTrue(any(item.startswith("Model record:") for item in card["list_items"]))
        self.assertEqual(counts, {"spread": 1, "total": 1})


if __name__ == "__main__":
    unittest.main()
