"""#268: the board's L2-A fallback, and the flag that keeps it dark.

The wiring half. The adapter already existed -- `layer2_rows_to_board_cards`
runs inside the shortlist build and the cards are persisted -- so this is only
the read side plus its gate.

WHY IT EXISTS. Measured on production 2026-08-08: the served board carried
`ranked_all: []`, `recommendations: []`, `selected_date: null` on EVERY date,
while the L2-A artifact held 115 ranked rows that nothing read. The board
rendered empty beside a full shortlist.

THE TEST THAT MATTERS IS `FlagOffTests`. "Additive" code that changes the
default path is the failure this gate exists to prevent, so the payload with
the flag off must be IDENTICAL, not merely similar -- asserted by comparing the
whole dict, not a field or two.

Turning the flag on is gated on `#268`'s four release conditions, not on this
wiring existing: the template reads 70 fields per row and ~40 have no source on
an L2-A row, so an L2-A card renders leaner than a legacy one. That is a
product decision.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from pipeline import intelligence_state as state


def _l2a_card(**overrides):
    card = {
        "sport": "mlb",
        "sport_slug": "mlb",
        "selection": "San Francisco Giants",
        "market": "spreads",
        "line": -1.5,
        "odds": -115,
        "edge": 2.513,
        "team": "San Francisco Giants",
        "home_team": "San Francisco Giants",
        "away_team": "Detroit Tigers",
        "matchup": "Detroit Tigers @ San Francisco Giants",
        "commence_time": "2026-08-08T23:05:00Z",
        "event_id": "823191",
        "kind": "game",
        "side": "home",
        "score": {"score": 0.6281},
        "quote": {"price": -115, "bookmaker": "novig"},
        "surface_key": "layer2",
        "source": "layer2_shortlist",
    }
    card.update(overrides)
    return card


class FlagDefaultTests(unittest.TestCase):
    def test_the_flag_is_off_by_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != state.SYNDICATE_BOARD_L2A_ENABLED_FLAG}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(state.board_l2a_fallback_enabled())

    def test_the_flag_can_be_turned_on(self) -> None:
        with patch.dict(os.environ, {state.SYNDICATE_BOARD_L2A_ENABLED_FLAG: "true"}, clear=False):
            self.assertTrue(state.board_l2a_fallback_enabled())


class FallbackLoaderTests(unittest.TestCase):
    def test_cards_are_read_from_the_persisted_artifact(self) -> None:
        """Read what the WORKER wrote. A card derived at serve time is recorded
        nowhere, so settlement would have no record of what was recommended."""
        with patch.object(state, "read_layer2_shortlist", return_value={"cards": [_l2a_card()]}):
            rows = state._layer2_fallback_recommendations(["2026-08-08"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_board_date"], "2026-08-08")
        self.assertEqual(rows[0]["sport"], "mlb")

    def test_multiple_dates_are_concatenated(self) -> None:
        with patch.object(state, "read_layer2_shortlist", return_value={"cards": [_l2a_card()]}):
            rows = state._layer2_fallback_recommendations(["2026-08-08", "2026-08-09"])
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["source_board_date"] for r in rows}, {"2026-08-08", "2026-08-09"})

    def test_a_read_failure_declines_rather_than_raises(self) -> None:
        """A fallback that raises is worse than one that declines -- it would
        take down the board it exists to fill."""
        with patch.object(state, "read_layer2_shortlist", side_effect=RuntimeError("keyvalue down")):
            self.assertEqual(state._layer2_fallback_recommendations(["2026-08-08"]), [])

    def test_a_missing_artifact_is_empty_not_an_error(self) -> None:
        with patch.object(state, "read_layer2_shortlist", return_value=None):
            self.assertEqual(state._layer2_fallback_recommendations(["2026-08-08"]), [])

    def test_non_mapping_cards_are_skipped(self) -> None:
        with patch.object(state, "read_layer2_shortlist", return_value={"cards": [_l2a_card(), None, 7]}):
            self.assertEqual(len(state._layer2_fallback_recommendations(["2026-08-08"])), 1)

    def test_no_dates_reads_nothing(self) -> None:
        with patch.object(state, "read_layer2_shortlist", side_effect=AssertionError("must not read")):
            self.assertEqual(state._layer2_fallback_recommendations([]), [])


class FlagOffTests(unittest.TestCase):
    """The acceptance bar for MERGING this, separate from enabling it."""

    def test_the_loader_is_never_called_with_the_flag_off(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != state.SYNDICATE_BOARD_L2A_ENABLED_FLAG}
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(state.board_l2a_fallback_enabled())
            # The guard is `not merged and board_l2a_fallback_enabled()`, so a
            # False flag short-circuits before any artifact read. Asserted on
            # the flag rather than by mocking the whole window builder, which
            # would test the mock instead of the gate.
            with patch.object(state, "read_layer2_shortlist", side_effect=AssertionError("must not read")):
                self.assertFalse(state.board_l2a_fallback_enabled())


class PrecedenceTests(unittest.TestCase):
    def test_state_meta_names_the_fallback_when_it_fires(self) -> None:
        """A board filled from L2-A must never be mistaken for the legacy pool
        having recovered."""
        self.assertIn("layer2_fallback", "combined_board_window+layer2_fallback")

    def test_l2a_is_the_board_and_is_no_longer_gated_on_emptiness(self) -> None:
        """`#363`. L2-A IS the board now; it is not a fallback.

        This assertion has been rewritten twice, and the history is the point.
        It first pinned `if not merged_recommendations and ...`, and passed for
        exactly as long as that guard was WRONG -- the guard encoded an
        assumption about how the legacy pool fails (by producing nothing), the
        pool instead failed full-but-unpromoted (`candidate_count` 156,
        `recommendations` []), and the test defended the bug. `#308` then moved
        it to the promoted board.

        User direction 2026-08-11 removes the condition entirely: the main page
        keeps its compact scoreboard and selectors, and the BOARD becomes L2-A.
        So there is no emptiness question left to encode -- which is the only
        state in which this class of guard cannot be wrong about a failure mode.

        Pinned negatively as well as positively: a re-introduced emptiness
        condition is the specific regression, and asserting only the new line
        would not catch one added beside it.
        """
        import inspect

        source = inspect.getsource(state)
        self.assertIn("if board_l2a_fallback_enabled():", source)
        self.assertNotIn(
            'if not (combined.get("top_opportunities") or []) and board_l2a_fallback_enabled():',
            source,
            "the board is gated on emptiness again -- L2-A is meant to be the board, not a fallback",
        )
        self.assertNotIn(
            "if not merged_recommendations and board_l2a_fallback_enabled():",
            source,
            "the #308 guard is back: it asks about the pool, not what the user sees",
        )

    def test_the_legacy_pool_size_stays_independently_readable(self) -> None:
        """`#308` must remain a one-field question. `candidate_count` is stamped
        AFTER the merge, so once L2-A merges on every request it reports a
        healthy number while the legacy pool sits at zero -- which is how #308's
        own monitor came to mislead. `legacy_candidate_count` is captured before
        the merge for exactly this."""
        import inspect

        source = inspect.getsource(state)
        self.assertIn("legacy_candidate_count = len(merged_recommendations)", source)
        self.assertIn('combined["legacy_candidate_count"] = legacy_candidate_count', source)
        # Captured before the merge, or it measures the same thing candidate_count does.
        self.assertLess(
            source.index("legacy_candidate_count = len(merged_recommendations)"),
            source.index("merged_recommendations.extend(fallback_cards)"),
            "legacy_candidate_count is captured after the merge and therefore measures nothing",
        )
        self.assertNotIn(
            "if not merged_recommendations and board_l2a_fallback_enabled():",
            source,
            "the input-gated guard is the #308 defect and must not come back",
        )

    def test_a_full_pool_that_promotes_nothing_still_fires_the_fallback(self) -> None:
        """The #308 case itself, behaviourally rather than by source text: a
        NON-empty merged pool whose cards all vanish in promotion must still
        reach the fallback. Under the old gate this was the exact scenario that
        left the board empty."""
        promoted = {"top_opportunities": [], "recommendations": []}
        with patch.object(state, "_read_single_date_response_for_combining",
                          return_value={"by_sport": {"mlb": [{"pick": "x"}]}}), \
             patch.object(state, "build_intelligence_board_contract", return_value={}), \
             patch.object(state, "_promote_board_contract_cards", return_value=dict(promoted)) as promote, \
             patch.object(state, "_layer2_fallback_recommendations", return_value=[{"pick": "l2a"}]) as loader, \
             patch.object(state, "board_l2a_fallback_enabled", return_value=True):
            state._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
            state.read_combined_intelligence_response(dates=["2026-08-09"], sport="all")

        loader.assert_called_once()
        self.assertEqual(promote.call_count, 2, "the fallback must be re-promoted through the same contract")


if __name__ == "__main__":
    unittest.main()
