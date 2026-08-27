"""`#565` -- one sport's slate window must not become every sport's cost.

THE BUG, found by the user: *"we flipped weekly sports to 7 days out for nfl and
ncaaf. this hammered us with soccer that we didn't intend."*

`_book_grid_forward_days()` returns `max_slate_window_days() - 1` -- the MAXIMUM
across all sports -- and the book-grid tick then built EVERY sport for EVERY date
in that span. `_SLATE_WINDOW_DAYS` is `{nfl: 7, ncaaf: 3, ncaab: 1, soccer: 7,
...}`, so ncaab was being built seven days out to serve a board that asks for
one, and each pair costs an HTTP Range pull plus its `.state.json` sidecar.

MEASURED COST on refresh-worker `-fzb6v` 2026-08-26: boot 00:45:38Z -> first
`[layer2_shortlist]` line 01:05:21Z is 19m43s inside `_build_candidate_pool`,
against a shortlist that is itself 58 seconds.

THE PROPERTY THAT MUST SURVIVE, because it is why the max was there: `#329` made
`max_slate_window_days` public so "the worker cannot build four days while the
board asks for seven". Per-sport windows keep that -- each sport still gets its
OWN full window -- while dropping the coupling. The two goals were never in
tension; the max was just the coarser way to reach the first.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "run_refresh_worker.py"),
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

from syndicate.features.shared.layer1_board import slate_window_days

ANCHOR = "2026-08-26"


def _plus(days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(ANCHOR) + timedelta(days=days)).isoformat()


class PerSportWindowTests(unittest.TestCase):
    def test_today_is_always_built_for_every_sport(self):
        for sport in ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer"):
            with self.subTest(sport=sport):
                self.assertTrue(worker._sport_covers_date(sport, ANCHOR, ANCHOR))

    def test_each_sport_still_gets_its_OWN_FULL_window(self):
        # The `#329` property. Narrowing a sport below its own window would be a
        # worse bug than the one being fixed -- the board would ask for a date
        # the producer never built.
        for sport in ("nfl", "ncaaf", "ncaab", "soccer", "mlb"):
            span = slate_window_days(sport)
            with self.subTest(sport=sport, span=span):
                self.assertTrue(
                    worker._sport_covers_date(sport, ANCHOR, _plus(span - 1)),
                    f"{sport} must still cover its own last window day",
                )

    def test_a_sport_is_not_built_past_its_own_window(self):
        # ncaab asks for 1 day and was being built across the widest sport's 7.
        self.assertFalse(worker._sport_covers_date("ncaab", ANCHOR, _plus(1)))
        self.assertFalse(worker._sport_covers_date("ncaaf", ANCHOR, _plus(3)))

    def test_the_weekly_sports_keep_their_seven_days(self):
        # The change that started this must not be undone by the fix to it.
        self.assertTrue(worker._sport_covers_date("nfl", ANCHOR, _plus(6)))
        self.assertFalse(worker._sport_covers_date("nfl", ANCHOR, _plus(7)))

    def test_soccer_keeps_its_own_week(self):
        # Soccer's 7 predates the weekly-sport change and is correct on its own
        # merits (week-scoped since 2026-07-24). The fix is the COUPLING, not
        # soccer's number.
        self.assertTrue(worker._sport_covers_date("soccer", ANCHOR, _plus(6)))

    def test_how_many_pairs_this_actually_removes(self):
        # The saving, stated as a number rather than a hope. Over the widest
        # span, count (sport, date) pairs kept vs. built before.
        sports = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer")
        span = worker._book_grid_forward_days() + 1
        dates = [_plus(offset) for offset in range(span)]
        before = len(sports) * len(dates)
        after = sum(
            1 for d in dates for s in sports if worker._sport_covers_date(s, ANCHOR, d)
        )
        self.assertLess(after, before)
        # Not a threshold pulled from the air: every sport whose window is
        # narrower than the max contributes (max - own) skipped dates.
        expected_skips = sum(max(0, span - slate_window_days(s)) for s in sports)
        self.assertEqual(before - after, expected_skips)

    def test_the_off_switch_restores_the_old_behaviour(self):
        with patch.dict(os.environ, {"SYNDICATE_BOOK_GRID_PER_SPORT_WINDOW": "0"}):
            self.assertTrue(worker._sport_covers_date("ncaab", ANCHOR, _plus(6)))

    def test_an_unreadable_date_is_BUILT_not_skipped(self):
        # The permissive branch costs one shard; the strict branch would
        # silently stop publishing a date some board is reading.
        self.assertTrue(worker._sport_covers_date("ncaab", ANCHOR, "not-a-date"))
        self.assertTrue(worker._sport_covers_date("ncaab", "not-a-date", _plus(3)))

    def test_an_unknown_sport_is_BUILT_not_skipped(self):
        # slate_window_days defaults unknown sports to 1; a new sport must not
        # silently lose its forward dates before anyone adds it to the table.
        # Today always builds, and that is the honest floor here.
        self.assertTrue(worker._sport_covers_date("cricket", ANCHOR, ANCHOR))


if __name__ == "__main__":
    unittest.main()
