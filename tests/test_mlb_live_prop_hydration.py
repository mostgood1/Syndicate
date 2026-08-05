from __future__ import annotations

import unittest

from syndicate.features.intelligence import _mlb_hydrate_live_prop_projection


class MlbLivePropHydrationLineGateTests(unittest.TestCase):
    """A line mismatch silently discarded real live numbers.

    The match required the board's line to equal the live-lens registry's
    line before attaching anything. Confirmed against production 2026-08-05:
    of 9 live MLB prop candidates, 8 matched on player+market but 2 were
    rejected on line alone -- Luis Arraez (board 2.5, lens 1.5) carrying
    actual=2.0 / liveProjection=2.081, and Luis Torrens (board 4.5, lens
    0.5) carrying actual=6.0. Both numbers were real; both were dropped, and
    the card rendered a live game with no live numbers.

    The gate was wrong in kind: `actual` and `liveProjection` are STAT-level,
    not bet-level. Arraez has two hits whether the line is 1.5 or 2.5, and
    the rest-of-game projection of his hit total does not change either.
    Only the over/under verdict depends on the line, and that is computed
    downstream from these values.
    """

    ARRAEZ_AT_1_5 = {"playerName": "Luis Arraez", "marketLabel": "Hits", "line": 1.5, "actual": 2.0, "liveProjection": 2.081}
    ARRAEZ_AT_2_5 = {"playerName": "Luis Arraez", "marketLabel": "Hits", "line": 2.5, "actual": 2.0, "liveProjection": 2.5}

    def _candidate(self, line: float | None = 2.5) -> dict:
        return {"player_name": "Luis Arraez", "market": "Hitter Hits", "line": line}

    def test_a_line_mismatch_no_longer_discards_the_live_numbers(self) -> None:
        candidate = self._candidate(2.5)
        _mlb_hydrate_live_prop_projection(candidate, [self.ARRAEZ_AT_1_5])
        self.assertEqual(candidate["actual"], "2.0")
        self.assertEqual(candidate["live_projection"], "2.1")

    def test_an_exact_line_row_is_still_preferred_when_one_exists(self) -> None:
        # The registry priced that same market, so its numbers are the most
        # directly comparable -- order in the feed must not decide this.
        candidate = self._candidate(2.5)
        _mlb_hydrate_live_prop_projection(candidate, [self.ARRAEZ_AT_1_5, self.ARRAEZ_AT_2_5])
        self.assertEqual(candidate["live_projection"], "2.5")

    def test_a_different_player_never_matches(self) -> None:
        candidate = {"player_name": "Somebody Else", "market": "Hitter Hits", "line": 2.5}
        _mlb_hydrate_live_prop_projection(candidate, [self.ARRAEZ_AT_1_5])
        self.assertNotIn("actual", candidate)
        self.assertNotIn("live_projection", candidate)

    def test_a_different_market_never_matches(self) -> None:
        candidate = {"player_name": "Luis Arraez", "market": "Hitter Home Runs", "line": 0.5}
        _mlb_hydrate_live_prop_projection(candidate, [self.ARRAEZ_AT_1_5])
        self.assertNotIn("actual", candidate)

    def test_no_rows_is_a_no_op(self) -> None:
        candidate = self._candidate()
        _mlb_hydrate_live_prop_projection(candidate, [])
        self.assertNotIn("actual", candidate)

    def test_a_candidate_without_a_line_still_hydrates(self) -> None:
        candidate = self._candidate(None)
        _mlb_hydrate_live_prop_projection(candidate, [self.ARRAEZ_AT_1_5])
        self.assertEqual(candidate["actual"], "2.0")


if __name__ == "__main__":
    unittest.main()
