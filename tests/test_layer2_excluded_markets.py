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
    """DEFAULT EMPTY since 2026-09-16 (user decision): no family is excluded by name.
    The env knob still works when someone sets it explicitly, and is tested as such."""

    def test_by_default_goalscorer_props_are_KEPT_and_nothing_is_excluded(self) -> None:
        rows = [
            _row(market="player_first_goal_scorer"),
            _row(market="player_last_goal_scorer"),
            _row(market="h2h"),
        ]
        out = select_shortlist(rows, now=_NOW)
        kept = sorted(r["market"] for r in out["rows"])
        self.assertEqual(kept, ["h2h", "player_first_goal_scorer", "player_last_goal_scorer"])
        self.assertEqual(out["rows_excluded_market"], 0)
        self.assertEqual(out["excluded_markets"], [])

    def test_by_default_the_anytime_variant_is_kept_too(self) -> None:
        out = select_shortlist([_row(market="player_anytime_goal_scorer")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_excluded_market"], 0)

    def test_an_explicit_env_exclusion_is_a_substring_rule_and_counted(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": "goal_scorer"}, clear=False):
            out = select_shortlist([_row(market="player_anytime_goal_scorer"), _row(market="h2h")], now=_NOW)
        self.assertEqual([r["market"] for r in out["rows"]], ["h2h"])
        self.assertEqual(out["rows_excluded_market"], 1)
        self.assertEqual(out["excluded_markets"], ["goal_scorer"])

    def test_an_explicit_exclusion_beats_the_kind_floor(self) -> None:
        """kind_floor guarantees 30 prop slots. If exclusion ran after bucketing
        the guarantee would drag these back -- the ordering still matters when
        someone sets the knob."""
        import os
        from unittest.mock import patch

        rows = [_row(market="player_first_goal_scorer", event_id=f"g{i}") for i in range(40)]
        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": "goal_scorer"}, clear=False):
            out = select_shortlist(rows, now=_NOW, kind_floor=30)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["rows_excluded_market"], 40)

    def test_an_unrelated_prop_is_untouched(self) -> None:
        out = select_shortlist([_row(market="player_shots_on_target")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows_excluded_market"], 0)

    def test_env_can_disable_or_replace_the_list(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"SYNDICATE_SHORTLIST_EXCLUDED_MARKETS": ""}, clear=False):
            out = select_shortlist([_row(market="player_first_goal_scorer")], now=_NOW)
        self.assertEqual(len(out["rows"]), 1)
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
