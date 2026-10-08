"""`_nhl_headshot_url` builds the team-independent `mugs/nhl/latest/{id}.png` URL.

Measured 2026-10-08: `/mugs/nhl/2026/TOR/8479318.png` (the old
`/{calendar year}/{TEAM}/` form) answered 302 for Auston Matthews, while
`/mugs/nhl/latest/8479318.png` answered 200.
"""

from __future__ import annotations

import unittest

from syndicate.features.nhl.cards import _nhl_headshot_url


class NhlHeadshotUrlTests(unittest.TestCase):
    def test_uses_latest_form(self) -> None:
        self.assertEqual(_nhl_headshot_url("8479318"), "https://assets.nhle.com/mugs/nhl/latest/8479318.png")

    def test_accepts_int_and_padded_ids(self) -> None:
        self.assertEqual(_nhl_headshot_url(8479318), "https://assets.nhle.com/mugs/nhl/latest/8479318.png")
        self.assertEqual(_nhl_headshot_url(" 8479318 "), "https://assets.nhle.com/mugs/nhl/latest/8479318.png")

    def test_no_calendar_year_or_team_segment(self) -> None:
        url = _nhl_headshot_url("8479318") or ""
        self.assertNotIn("/2026/", url)
        self.assertNotIn("/TOR/", url)

    def test_rejects_missing_or_non_numeric_ids(self) -> None:
        for value in (None, "", "abc", "8479318.0"):
            self.assertIsNone(_nhl_headshot_url(value), value)


if __name__ == "__main__":
    unittest.main()
