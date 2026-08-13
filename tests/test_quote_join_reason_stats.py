"""Count quote-join misses BY REASON, not just by outcome.

`quote_ref_for_bet` decides identity with a full scan of the day's book-quote
rows and no early exit. Two very different things look identical from outside:

  - the cheap `event_id` key matched, and the scan was incidental;
  - the cheap key missed, and EVERY row fell through to `_row_teams_match` and
    full alias resolution.

The second is the expensive path, and MLB is in it by construction --
`quote_ref_for_bet`'s own docstring records that board rows carry a StatsAPI
`gamePk` while quote rows carry an OddsAPI event hash, so `event_id` can never
match. The same key mismatch shows up elsewhere as a SILENT null rather than a
slow scan (`#412`), which is why the reason split is worth more than the total:
it distinguishes "the join is broken" from "the key is wrong" in one reading,
and it keeps working as a regression guard after a fix.

`rows_walked` is the number that sizes the problem before anything is optimised.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import odds_book_quotes as obq


def _rows() -> list[dict]:
    return [
        {"event_id": "evt-1", "market": "h2h", "selection": "home", "price": -110,
         "bookmaker": "bk", "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels"},
        {"event_id": "evt-1", "market": "h2h", "selection": "away", "price": 120,
         "bookmaker": "bk", "home_team": "Baltimore Orioles", "away_team": "Los Angeles Angels"},
    ]


class ReasonSplit(unittest.TestCase):
    def setUp(self) -> None:
        obq.reset_quote_join_stats()

    def _call(self, **kwargs):
        with patch.object(obq, "read_book_quotes", lambda *a, **k: _rows()):
            return obq.quote_ref_for_bet(sport="mlb", date_str="2026-08-13", **kwargs)

    def test_cheap_event_key_is_counted_as_by_event(self) -> None:
        self._call(event_id="evt-1", market="moneyline", selection="home")
        stats = obq.reset_quote_join_stats()
        self.assertEqual(stats.get("by_event"), 1)
        self.assertIsNone(stats.get("by_teams_fallthrough"))

    def test_the_mlb_shape_is_counted_as_a_fallthrough(self) -> None:
        """A StatsAPI gamePk against OddsAPI event hashes -- the production case.

        The call still SUCCEEDS, via teams. That is exactly why this needs its
        own counter: a correct answer reached by the expensive path is
        indistinguishable from a cheap one in any outcome-based metric.
        """
        self._call(
            event_id="823833",  # never matches an OddsAPI hash
            market="moneyline",
            selection="home",
            matchup="LAA @ BAL",
        )
        stats = obq.reset_quote_join_stats()
        self.assertEqual(stats.get("by_teams_fallthrough"), 1)
        self.assertIsNone(stats.get("by_event"))

    def test_rows_walked_sizes_the_scan(self) -> None:
        """len(rows) every call -- there is no early exit. This is the figure
        that says how big the problem is before anything is changed."""
        self._call(event_id="evt-1")
        self._call(event_id="evt-1")
        stats = obq.reset_quote_join_stats()
        self.assertEqual(stats.get("calls"), 2)
        self.assertEqual(stats.get("rows_walked"), 2 * len(_rows()))

    def test_no_identity_is_its_own_reason(self) -> None:
        self._call(event_id="nope", matchup="XXX @ YYY")
        stats = obq.reset_quote_join_stats()
        self.assertEqual(stats.get("no_identity"), 1)

    def test_reset_starts_a_fresh_window(self) -> None:
        self._call(event_id="evt-1")
        self.assertTrue(obq.reset_quote_join_stats())
        self.assertEqual(obq.reset_quote_join_stats(), {})


class CountingIsNotItselfThePerRowCost(unittest.TestCase):
    def test_no_counter_increment_runs_inside_the_row_loop(self) -> None:
        """The loop runs ~122k times per candidate. A `_bump` inside it would be
        part of the cost it exists to measure -- so the increments live after the
        loop and are asserted here to stay there."""
        import inspect
        import textwrap

        src = textwrap.dedent(inspect.getsource(obq.quote_ref_for_bet))
        lines = src.splitlines()
        # `#414` renamed the loop when identity stopped being a full scan:
        # `for row in rows:` became `for position in sorted(positions):` over the
        # indexed candidate union. The anchor is matched by SHAPE rather than by
        # that exact literal, because the previous version failed with
        # StopIteration the moment the loop was renamed -- a test that breaks on
        # a rename reports a defect that is not there, and the temptation is
        # then to delete it rather than re-aim it.
        start = next(
            i for i, ln in enumerate(lines)
            if ln.strip().startswith("for ") and ln.strip().endswith(":")
            and ("in rows" in ln or "sorted(positions)" in ln)
        )
        loop_indent = len(lines[start]) - len(lines[start].lstrip())

        # The loop body is every following line indented deeper than `for`.
        # Slicing on the next named statement instead swept in the post-loop
        # increments and made this assertion pass vacuously in reverse -- it
        # failed while the code was correct.
        body = []
        for line in lines[start + 1:]:
            if line.strip() and (len(line) - len(line.lstrip())) <= loop_indent:
                break
            body.append(line)

        self.assertTrue(body, "loop body not found")
        self.assertNotIn("_bump(", "\n".join(body))
        # And the increments must genuinely exist somewhere -- an assertion that
        # only checks absence would also pass if the counters were deleted.
        self.assertIn('_bump("rows_walked"', src)


if __name__ == "__main__":
    unittest.main()
