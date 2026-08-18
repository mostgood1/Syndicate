"""Regression coverage for `_static_season_payload_is_stale_vs_canonical`.

Added alongside the fix for the gap traced in docs/ai_context/todo.md
("RE-MEASURED 2026-08-18 ... READER WAS NEVER BUILT gap"): a historical
`season_betting_day_*.json` static payload with SOME settlement was served
forever, even when far thinner than the canonical daily settlement already
on disk for that date. 2026-08-17 was measured serving a static payload
carrying exactly 1 graded moneyline row against an 11-game freeze already
present that day.
"""

from __future__ import annotations

import unittest

from vendor.mlb_bettingv2.tools.web.flask_frontend import (
    _static_season_payload_is_stale_vs_canonical,
)


class StaticSeasonPayloadStalenessTests(unittest.TestCase):
    def test_zero_settlement_is_stale_regardless_of_canonical(self) -> None:
        static_payload = {"games": {}}
        self.assertTrue(_static_season_payload_is_stale_vs_canonical(static_payload, None))
        self.assertTrue(
            _static_season_payload_is_stale_vs_canonical(
                static_payload, {"selected_counts": {"combined": 0}}
            )
        )

    def test_thin_settlement_is_stale_when_canonical_has_more(self) -> None:
        # The measured 08-17 shape: 1 graded row in the static payload,
        # against an 11-game freeze/canonical settlement already on disk.
        static_payload = {
            "games": {"824320": {"markets": {"ml": {"settlement": {"result": "win"}}}}},
            "summary": {"selected_counts": {"ml": 1, "combined": 1}},
        }
        canonical_settlement = {"selected_counts": {"ml": 11, "combined": 11}}
        self.assertTrue(
            _static_season_payload_is_stale_vs_canonical(static_payload, canonical_settlement)
        )

    def test_settled_payload_is_not_stale_without_a_canonical_settlement(self) -> None:
        # No canonical settlement available for this date at all -- the old
        # behaviour (trust the static payload) must be preserved, not
        # downgraded to "always stale".
        static_payload = {
            "games": {"824320": {"markets": {"ml": {"settlement": {"result": "win"}}}}},
            "summary": {"selected_counts": {"ml": 1, "combined": 1}},
        }
        self.assertFalse(_static_season_payload_is_stale_vs_canonical(static_payload, None))

    def test_settled_payload_is_not_stale_when_already_at_least_as_complete(self) -> None:
        # A genuinely complete static payload must not be discarded just
        # because a canonical settlement also exists -- no regression on the
        # common (already-correct) case.
        one_settled_game = {"markets": {"ml": {"settlement": {"result": "win"}}}}
        static_payload = {
            "games": {f"g{i}": one_settled_game for i in range(15)},
            "summary": {"selected_counts": {"ml": 15, "combined": 15}},
        }
        canonical_settlement = {"selected_counts": {"ml": 2, "combined": 2}}
        self.assertFalse(
            _static_season_payload_is_stale_vs_canonical(static_payload, canonical_settlement)
        )
        # Equal counts also must not flip to stale.
        canonical_settlement_equal = {"selected_counts": {"ml": 15, "combined": 15}}
        self.assertFalse(
            _static_season_payload_is_stale_vs_canonical(static_payload, canonical_settlement_equal)
        )


if __name__ == "__main__":
    unittest.main()
