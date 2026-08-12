"""`#400` -- one prop family took half the board.

Measured on the served board 2026-08-12: soccer contributed 100 of 200 sampled
rows and EVERY one was `player_first_goal_scorer` (45) or
`player_last_goal_scorer` (55). `#391` caps any one GAME at 6 rows; nothing
capped a market FAMILY.

They are structurally unfit for an actionable board: one-sided by construction
so `#384`'s consensus path cannot run (all 100 fell back to `book_margin_model`,
an estimate), the hold applied is measured mostly on moneylines, and the family
sat uniformly at ~-6.9 EV so it was never ranked on merit.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from syndicate.features.shared.layer2_board import select_shortlist

_NOW = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)


def _row(*, market, sport="soccer", ev=2.0, event_id="e1"):
    return {
        "sport": sport,
        "kind": "prop",
        "event_id": event_id,
        "market": market,
        "ev_pct": ev,
        "commence_time": (_NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        "quote": {"book_age_seconds": 60.0},
        "score": {"score": ev},
    }


class ExcludedMarketTests(unittest.TestCase):
    def test_goalscorer_props_are_excluded_and_counted(self) -> None:
        rows = [
            _row(market="player_first_goal_scorer"),
            _row(market="player_last_goal_scorer"),
            _row(market="h2h"),
        ]
        out = select_shortlist(rows, now=_NOW)
        kept = [r["market"] for r in out["rows"]]
        self.assertEqual(kept, ["h2h"])
        self.assertEqual(out["rows_excluded_market"], 2)
        self.assertEqual(out["excluded_markets"], ["goal_scorer"])

    def test_the_anytime_variant_is_covered_by_the_same_substring(self) -> None:
        """Substring match on purpose -- first/last/anytime are one family and a
        literal list would silently miss whichever variant a book adds next."""
        out = select_shortlist([_row(market="player_anytime_goal_scorer")], now=_NOW)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["rows_excluded_market"], 1)

    def test_exclusion_beats_the_kind_floor(self) -> None:
        """kind_floor guarantees 30 prop slots. If exclusion ran after bucketing
        the guarantee would drag these back -- the same ordering bug the value
        floor and the game cap each had to avoid."""
        rows = [_row(market="player_first_goal_scorer", event_id=f"g{i}") for i in range(40)]
        out = select_shortlist(rows, now=_NOW, kind_floor=30)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["rows_excluded_market"], 40)

    def test_an_unrelated_prop_is_untouched(self) -> None:
        out = select_shortlist([_row(market="player_shots_on_target")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_excluded_market"], 0)

    def test_env_can_widen_or_disable_the_rule(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": ""}, clear=False):
            out = select_shortlist([_row(market="player_first_goal_scorer")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1, "empty env must DISABLE the rule, not keep the default")
        self.assertEqual(out["excluded_markets"], [])

        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": "shots_on_target"}, clear=False):
            out = select_shortlist(
                [_row(market="player_shots_on_target"), _row(market="player_first_goal_scorer")],
                now=_NOW,
            )
        kept = [r["market"] for r in out["rows"]]
        self.assertEqual(kept, ["player_first_goal_scorer"], "env must REPLACE the default list")


if __name__ == "__main__":
    unittest.main()
