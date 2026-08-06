"""The quote_ref contract and the two-clock rule.

Guards the object the read path never had. A Layer 2 candidate row is built from
display_pick/ev_pct/p_win/market_label/selection and carries no price, no book
and no timestamp -- which is why "which book has the edge" had nowhere to live
and CLV had no opening price to record against a bet.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared.odds_book_quotes import (
    append_book_quotes,
    market_key_for_quote,
    quote_ref,
    quotes_by_market,
    read_book_quotes,
)

NOW = datetime(2026, 8, 6, 19, 0, 0, tzinfo=timezone.utc)


def _quote(book: str, price: int, *, book_updated_at: str | None = "2026-08-06T18:59:00Z") -> dict:
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": "e1",
        "segment": "full",
        "market": "h2h",
        "selection": "home",
        "player_name": None,
        "line": None,
        "bookmaker": book,
        "price": price,
        "book_updated_at": book_updated_at,
        "captured_at": "2026-08-06T18:59:30Z",
    }


class QuoteRefTests(unittest.TestCase):
    def test_best_price_is_the_highest_payout_across_both_signs(self) -> None:
        # -108 pays more than -120; +140 pays more than either. Comparing raw
        # American ints gets this right without a branch, which is the one thing
        # worth pinning because it looks like it should need one.
        ref = quote_ref([_quote("fanduel", -120), _quote("draftkings", -108), _quote("betmgm", 140)])
        self.assertEqual(ref["best_bookmaker"], "betmgm")
        self.assertEqual(ref["price_rank"], 1)
        self.assertEqual(ref["books_quoting"], 3)

    def test_chosen_book_is_ranked_against_the_others_not_silently_replaced(self) -> None:
        rows = [_quote("fanduel", -120), _quote("draftkings", -108), _quote("betmgm", -115)]
        ref = quote_ref(rows, chosen_bookmaker="fanduel")
        # Describes the price we actually took...
        self.assertEqual(ref["bookmaker"], "fanduel")
        self.assertEqual(ref["price"], -120)
        # ...while still saying we were on the worst of three.
        self.assertEqual(ref["price_rank"], 3)
        self.assertEqual(ref["best_price"], -108)
        self.assertEqual(ref["best_bookmaker"], "draftkings")
        self.assertLess(ref["edge_vs_consensus_pct"], 0)

    def test_consensus_is_probability_averaged_not_odds_averaged(self) -> None:
        # Averaging American odds across the +/-100 discontinuity is meaningless:
        # the naive mean of -110 and +110 is 0, which is not a price at all.
        ref = quote_ref([_quote("a", -110), _quote("b", 110)])
        self.assertLess(abs(ref["consensus_price"]), 1000)
        self.assertNotEqual(ref["consensus_price"], 0)
        # Symmetric inputs sit at the even-money boundary.
        self.assertLessEqual(abs(abs(ref["consensus_price"]) - 100), 2)

    def test_beating_consensus_is_signed_positive(self) -> None:
        ref = quote_ref([_quote("a", -108), _quote("b", -120), _quote("c", -122)])
        self.assertEqual(ref["bookmaker"], "a")
        self.assertGreater(ref["edge_vs_consensus_pct"], 0)

    def test_unknown_book_clock_stays_unknown(self) -> None:
        """The two-clock rule. A missing book timestamp must NOT fall back to
        capture time -- that is exactly the conflation the field exists to
        remove, and it would render a dead market as fresh."""
        ref = quote_ref([_quote("fanduel", -110, book_updated_at=None)], now=NOW)
        self.assertIsNone(ref["book_updated_at"])
        self.assertIsNone(ref["book_age_seconds"])
        # Capture age is still known and must not be confused for it.
        self.assertIsNotNone(ref["capture_age_seconds"])

    def test_two_clocks_diverge_independently(self) -> None:
        """A price the book last moved four hours ago, polled 30 seconds ago, is
        a dead market. One number cannot say that; two can."""
        stale = _quote("fanduel", -110, book_updated_at="2026-08-06T15:00:00Z")
        stale["captured_at"] = "2026-08-06T18:59:30Z"
        ref = quote_ref([stale], now=NOW)
        self.assertGreater(ref["book_age_seconds"], 4 * 3600 - 60)
        self.assertLess(ref["capture_age_seconds"], 120)

    def test_empty_input_returns_none_rather_than_a_hollow_ref(self) -> None:
        self.assertIsNone(quote_ref([]))
        self.assertIsNone(quote_ref([{**_quote("fanduel", -110), "price": None}]))

    def test_grouping_keeps_one_row_per_book_freshest_wins(self) -> None:
        old = _quote("fanduel", -130, book_updated_at="2026-08-06T17:00:00Z")
        new = _quote("fanduel", -110, book_updated_at="2026-08-06T18:59:00Z")
        grouped = quotes_by_market([old, new, _quote("draftkings", -115)])
        key = market_key_for_quote(new)
        self.assertEqual(len(grouped[key]), 2, "one row per book, not one per observation")
        fanduel = next(row for row in grouped[key] if row["bookmaker"] == "fanduel")
        self.assertEqual(fanduel["price"], -110, "stale observation shadowed the fresh one")

    def test_line_is_part_of_market_identity(self) -> None:
        """Totals 8.5 and 9.0 are different markets. Grouping them together
        would report a best price that cannot actually be bet."""
        over_85 = {**_quote("a", -110), "market": "totals", "selection": "over", "line": 8.5}
        over_90 = {**_quote("b", 105), "market": "totals", "selection": "over", "line": 9.0}
        self.assertNotEqual(market_key_for_quote(over_85), market_key_for_quote(over_90))
        self.assertEqual(len(quotes_by_market([over_85, over_90])), 2)


class QuoteLogExtraFieldTests(unittest.TestCase):
    """`extra` exists for soccer's league, the one dimension a single sport slug
    cannot express -- all eight leagues share the soccer_source tree."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(quotes_module, "data_root", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_extra_fields_are_stamped_on_every_row(self) -> None:
        append_book_quotes(
            sport="soccer",
            date_str="2026-08-06",
            rows=[{**_quote("fanduel", -110), "sport": "soccer"}],
            captured_at="2026-08-06T18:59:30Z",
            publish=False,
            extra={"league": "epl"},
        )
        rows = read_book_quotes("soccer", "2026-08-06")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["league"], "epl")

    def test_book_clock_survives_the_round_trip_and_stays_none_when_absent(self) -> None:
        append_book_quotes(
            sport="nhl",
            date_str="2026-08-06",
            rows=[
                {**_quote("fanduel", -110), "sport": "nhl", "event_id": "with"},
                {**_quote("draftkings", -115, book_updated_at=None), "sport": "nhl", "event_id": "without"},
            ],
            captured_at="2026-08-06T18:59:30Z",
            publish=False,
        )
        rows = {row["event_id"]: row for row in read_book_quotes("nhl", "2026-08-06")}
        self.assertEqual(rows["with"]["book_updated_at"], "2026-08-06T18:59:00Z")
        self.assertIsNone(rows["without"]["book_updated_at"])
        # And capture time is present on both, so "unknown book clock" is never
        # mistaken for "no data at all".
        self.assertTrue(rows["without"]["captured_at"])


if __name__ == "__main__":
    unittest.main()
