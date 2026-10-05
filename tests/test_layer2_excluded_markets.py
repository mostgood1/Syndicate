"""`#400` -- one prop family took half the board. NO LONGER A RULE.

`[2026-10-05, user directive]`, lane `stop-market-withholding`: no market is
kept off the board by name. The exclusion list and its env knob
(`SYNDICATE_SHORTLIST_EXCLUDED_MARKETS`) are removed; these tests pin that a
value set in the environment excludes nothing. History follows.

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


class NoMarketIsExcludedTests(unittest.TestCase):
    def test_goalscorer_props_are_kept(self) -> None:
        rows = [
            _row(market="player_first_goal_scorer"),
            _row(market="player_last_goal_scorer"),
            _row(market="player_anytime_goal_scorer"),
            _row(market="h2h"),
        ]
        out = select_shortlist(rows, now=_NOW)
        self.assertEqual(len(out["rows"]), 4)
        self.assertNotIn("rows_excluded_market", out)
        self.assertNotIn("excluded_markets", out)

    def test_the_old_env_knob_excludes_nothing(self) -> None:
        import os
        from unittest.mock import patch

        rows = [_row(market="player_first_goal_scorer", event_id=f"g{i}") for i in range(4)]
        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": "goal_scorer"}, clear=False):
            out = select_shortlist(rows + [_row(market="h2h", event_id="h")], now=_NOW)
        self.assertEqual(len(out["rows"]), 5)


if __name__ == "__main__":
    unittest.main()
