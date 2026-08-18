"""The NCAAF board must not silently truncate an FBS slate to an NFL-sized one.

WHY THIS FILE EXISTS. `_collapse_games` capped the NCAAF cards board at 16
games, and two more `runtime_rows[:16]` slices did the same on the other two
branches of the same page. 16 is the NFL's natural weekly slate (32 teams / 2),
where the cap can never bind. FBS plays 50-60.

Measured on production 2026-08-18: weeks 1, 2, 3, 5, 8 and 12 ALL served exactly
16 games while CFBD listed 51 FBS-vs-FBS for week 1 alone. Six weeks landing on
the cap exactly is the cap binding, not six coincidences.

THE ONE THAT MATTERED MOST was not the one serving the board that day. The route
(`blueprints/ncaaf.py:85,91`) calls `build_smartsim_cards_page_context`, and its
SmartSim2-standalone branch was returning zero rows only because the projection
artifact was missing (`CFBD_API_KEY` absent). The moment that key lands the
branch returns ~51 rows -- and the old `[:16]` would have cut them straight back
to 16, re-breaking the board at the exact moment it started working. A fix
applied only to `_collapse_games` would have passed every test here except the
one that counts.

So these tests assert on the SHARED constant and on every branch, not on one.
"""
from __future__ import annotations

import unittest

from syndicate.features.ncaaf import cards


def _summary(matchups: int) -> dict:
    return {
        "results": [
            {
                "home_team": f"Home {i}",
                "away_team": f"Away {i}",
                "edge": float(i),
                "stake": 1.0,
                "market": "ML",
                "side": "Home",
                "provider": "Book",
            }
            for i in range(matchups)
        ]
    }


class NcaafBoardSlateCoverageTest(unittest.TestCase):
    def test_limit_is_large_enough_for_a_real_fbs_week(self) -> None:
        """51 FBS-vs-FBS is the real measured 2026 wk1 size; 60+ happens."""
        self.assertGreaterEqual(
            cards._NCAAF_BOARD_GAME_LIMIT,
            60,
            "the NCAAF board limit must clear a real FBS week (51 measured for 2026 wk1, "
            "60+ in a full week). A 16 here is an NFL-shaped number on a non-NFL sport.",
        )

    def test_a_full_fbs_slate_is_not_truncated(self) -> None:
        counts: dict = {}
        games = cards._collapse_games(_summary(51), 1, counts=counts)
        self.assertEqual(len(games), 51)
        self.assertFalse(counts["truncated"])
        self.assertEqual(counts["dropped"], 0)

    def test_the_old_16_cap_would_have_dropped_35_of_51(self) -> None:
        """The regression this file exists to prevent, stated as a measurement.

        Not a redundant test: it proves the slate size actually reaches the old
        cap, so `test_a_full_fbs_slate_is_not_truncated` above is exercising a
        real change rather than passing vacuously.
        """
        counts: dict = {}
        games = cards._collapse_games(_summary(51), 1, limit=16, counts=counts)
        self.assertEqual(len(games), 16)
        self.assertTrue(counts["truncated"])
        self.assertEqual(counts["dropped"], 35)

    def test_the_cap_still_guards_and_still_announces(self) -> None:
        """Raised, not removed. An unbounded board is a real memory risk on a
        2GB display service (~9.8 KB/game measured)."""
        over = cards._NCAAF_BOARD_GAME_LIMIT + 40
        counts: dict = {}
        games = cards._collapse_games(_summary(over), 1, counts=counts)
        self.assertEqual(len(games), cards._NCAAF_BOARD_GAME_LIMIT)
        self.assertTrue(counts["truncated"], "a cap that bites must say so")
        self.assertEqual(counts["dropped"], over - cards._NCAAF_BOARD_GAME_LIMIT)

    def test_counts_are_recorded_even_when_nothing_is_dropped(self) -> None:
        """`truncated: False` is a reading. An absent key is not.

        A caller that has to distinguish "not truncated" from "this build does
        not report truncation" cannot do it if the key only appears on failure.
        """
        counts: dict = {}
        cards._collapse_games(_summary(4), 1, counts=counts)
        for key in ("summary_result_rows", "distinct_matchups", "limit", "truncated", "dropped"):
            self.assertIn(key, counts)
        self.assertFalse(counts["truncated"])

    def test_no_hardcoded_slice_cap_survives_in_code(self) -> None:
        """The other two caps were `runtime_rows[:16]` literals, on the branches
        the route actually reaches. Nothing here may reintroduce one.

        AST, NOT A TEXT SEARCH. The first version of this test read the source as
        text and failed against the module's own DOCSTRINGS, which quote
        `runtime_rows[:16]` while explaining why it is gone. A text search cannot
        tell a cap from a comment about a cap; parsing can. It also generalises:
        this catches `[:20]` or `[:32]`, not just the one literal I happened to
        remember.
        """
        import ast
        from pathlib import Path

        # Only BOARD-SIZED caps. The module legitimately slices small constants
        # for prose and abbreviations -- `lead_phrases[:2]`, `ordered_items[:3]`,
        # `ordered_items[:5]`, `tokens[0][:3]` for a team abbr. Those are not
        # slate caps and flagging them would make this test noise, which is how
        # a test gets deleted instead of fixed. 10 sits well above the prose
        # slices and well below any real weekly slate.
        BOARD_SIZED = 10

        tree = ast.parse(Path(cards.__file__).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Slice):
                continue
            upper = node.slice.upper
            if isinstance(upper, ast.Constant) and isinstance(upper.value, int) and upper.value >= BOARD_SIZED:
                offenders.append((getattr(node, "lineno", "?"), upper.value))
        self.assertEqual(
            offenders,
            [],
            f"board-sized hardcoded slice cap(s) back in ncaaf/cards.py at {offenders} -- use "
            "_NCAAF_BOARD_GAME_LIMIT and report truncation via _note_board_truncation",
        )

    def test_note_board_truncation_reports_both_ways(self) -> None:
        """The helper guarding the two non-legacy branches."""
        under: dict = {}
        cards._note_board_truncation(under, "smartsim2_standalone", list(range(51)), 1)
        self.assertFalse(under["truncated"])
        self.assertEqual(under["runtime_rows"], 51)
        self.assertEqual(under["source"], "smartsim2_standalone")

        over: dict = {}
        n = cards._NCAAF_BOARD_GAME_LIMIT + 5
        cards._note_board_truncation(over, "legacy_engine", list(range(n)), 1)
        self.assertTrue(over["truncated"])
        self.assertEqual(over["dropped"], 5)


if __name__ == "__main__":
    unittest.main()
