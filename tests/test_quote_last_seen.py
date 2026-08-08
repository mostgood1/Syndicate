"""Last-seen tracking on the book-quote change log.

THE DEFECT, measured on the served board 2026-08-08: all 100 MLB rows carried
`book_age_seconds` inside a 1.2-minute window ~11.9h wide, and that age GREW
with wall clock across rebuilds of an artifact only 1.4 minutes old. It read as
an 11.9h capture outage. It was not.

`append_book_quotes` is a CHANGE log by design -- a price that has not moved
writes no row -- so the newest row for a key keeps its ORIGINAL
`book_updated_at` and `captured_at`. Every age derived downstream therefore
means "time since this price last MOVED", never "time since we last LOOKED",
and `_freshness_factor` consumes it as if it were the latter. A market that is
simply motionless gets discounted to 0.25 as though the feed were dead.

Worse, nothing recorded the second quantity at all: `_write_state` only ran
`if appended`, so a refresh that confirmed every price unchanged left no trace
it had run. "Stable" and "we stopped observing this" were indistinguishable in
the stored data.

These pin the fix: observation is recorded even when nothing changes, and the
old 2-element state files still load.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes
from syndicate.features.shared.odds_book_quotes import append_book_quotes, read_quote_last_seen


def _row(price: str = "-110", line: float = 1.5) -> dict:
    return {
        "event_id": "evt1",
        "market": "spreads",
        "selection": "home",
        "bookmaker": "novig",
        "price": price,
        "line": line,
        "book_updated_at": "2026-08-08T06:43:00+00:00",
    }


class LastSeenTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        patcher = patch.object(
            odds_book_quotes, "book_quotes_path", lambda sport, date_str: root / f"{sport}_{date_str}.jsonl"
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        odds_book_quotes._BOOK_QUOTES_CACHE.clear()

    def test_unchanged_price_still_records_that_we_looked(self) -> None:
        """The regression. Second call appends nothing -- and previously wrote
        no state at all, losing the only evidence the refresh ran."""
        append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T06:43:00+00:00")
        second = append_book_quotes(
            sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T18:40:00+00:00"
        )

        self.assertEqual(second["appended"], 0, "an unchanged price must not append a row")
        seen = read_quote_last_seen("mlb", "2026-08-08")
        self.assertEqual(len(seen), 1)
        self.assertEqual(
            list(seen.values())[0],
            "2026-08-08T18:40:00+00:00",
            "last-seen must advance even though nothing changed",
        )

    def test_changed_price_also_advances_last_seen(self) -> None:
        append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T06:43:00+00:00")
        result = append_book_quotes(
            sport="mlb",
            date_str="2026-08-08",
            rows=[_row(price="-125")],
            captured_at="2026-08-08T18:40:00+00:00",
        )
        self.assertEqual(result["appended"], 1)
        self.assertEqual(list(read_quote_last_seen("mlb", "2026-08-08").values())[0], "2026-08-08T18:40:00+00:00")

    def test_dedupe_still_works_after_the_state_shape_change(self) -> None:
        """The equality check slices to (line, price); a third element must not
        make every price look changed and re-append the whole board."""
        append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T06:43:00+00:00")
        for stamp in ("2026-08-08T12:00:00+00:00", "2026-08-08T18:40:00+00:00"):
            out = append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at=stamp)
            self.assertEqual(out["appended"], 0)

    def test_legacy_two_element_state_still_loads_and_dedupes(self) -> None:
        """Every state file written before this has two elements."""
        append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T06:43:00+00:00")
        state_path = odds_book_quotes._state_path("mlb", "2026-08-08")
        legacy = {key: value[:2] for key, value in json.loads(state_path.read_text(encoding="utf-8")).items()}
        state_path.write_text(json.dumps(legacy), encoding="utf-8")

        # Unknown, not zero -- a legacy file must not claim we never looked.
        self.assertEqual(read_quote_last_seen("mlb", "2026-08-08"), {})
        out = append_book_quotes(
            sport="mlb", date_str="2026-08-08", rows=[_row()], captured_at="2026-08-08T18:40:00+00:00"
        )
        self.assertEqual(out["appended"], 0, "legacy state must still dedupe an unchanged price")
        self.assertEqual(len(read_quote_last_seen("mlb", "2026-08-08")), 1, "and be upgraded in place")

    def test_no_rows_writes_nothing(self) -> None:
        append_book_quotes(sport="mlb", date_str="2026-08-08", rows=[], captured_at="2026-08-08T18:40:00+00:00")
        self.assertEqual(read_quote_last_seen("mlb", "2026-08-08"), {})

    def test_missing_date_returns_empty_not_an_error(self) -> None:
        self.assertEqual(read_quote_last_seen("mlb", "2030-01-01"), {})


if __name__ == "__main__":
    unittest.main()
