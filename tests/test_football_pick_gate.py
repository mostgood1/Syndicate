"""The football pick-serving gate: suppression must be REACHABLE and REVERSIBLE.

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
        kept, suppressed = filter_pick_rows("ncaaf", rows)
        self.assertEqual(kept, [])
        self.assertEqual(suppressed, {"spread": 2, "moneyline": 1, "total": 1})

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


class NcaafPickServingGateTests(unittest.TestCase):
    """The gate on the path production actually serves."""

    def test_served_board_yields_no_cards_while_suppressed(self) -> None:
        context = ncaaf_picks.build_smartsim_picks_page_context(1)
        self.assertEqual(len(context.get("rank_cards") or []), 0)
        self.assertIn("picks_gate", context)

    def test_suppressed_board_explains_itself(self) -> None:
        """A blank board with no reason reads as an outage and gets 'fixed'."""
        context = ncaaf_picks.build_smartsim_picks_page_context(1)
        empty = context.get("empty_state") or {}
        self.assertEqual(empty.get("eyebrow"), "Picks suppressed")
        self.assertIn("closing line", empty.get("title", ""))
        self.assertTrue(empty.get("list_items"))

    def test_suppressed_board_keeps_navigation(self) -> None:
        """Projections stay reachable; only the BET is withheld."""
        context = ncaaf_picks.build_smartsim_picks_page_context(1)
        self.assertTrue(context.get("available_weeks"))
        self.assertIsNotNone(context.get("week"))

    def test_off_is_not_on(self) -> None:
        """THE test. Gate open must serve cards the closed gate withholds.

        Without this, 'zero cards' is equally consistent with a working gate and
        with a board that had nothing to show -- and the second reads as success.
        """
        closed = ncaaf_picks.build_smartsim_picks_page_context(1)
        self.assertEqual(len(closed.get("rank_cards") or []), 0)
        with _open_ncaaf_markets():
            opened = ncaaf_picks.build_smartsim_picks_page_context(1)
        self.assertGreater(
            len(opened.get("rank_cards") or []),
            0,
            "gate-open board served nothing, so the closed board proves nothing",
        )
        self.assertNotIn("picks_gate", opened)

    def test_collapse_results_drops_suppressed_rows(self) -> None:
        summary = {
            "results": [
                {"home_team": "UGA", "away_team": "BAMA", "market": "spread", "side": "UGA -3.5", "provider": "b", "edge": 0.04},
                {"home_team": "UGA", "away_team": "BAMA", "market": "total", "side": "Over 52.5", "provider": "b", "edge": 0.03},
            ]
        }
        counts: dict[str, int] = {}
        cards = ncaaf_picks._collapse_results(summary, gate_counts=counts)
        self.assertEqual(cards, [])
        self.assertEqual(counts, {"spread": 1, "total": 1})


if __name__ == "__main__":
    unittest.main()
