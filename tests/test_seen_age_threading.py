"""Seen-age threaded book_quotes -> grid -> layer2 -> score.

The half that changes the board. `6a78566b` made last-seen exist; nothing read
it, so the board still discounted stable markets.

`book_quotes` is a change log, so `age_seconds` means "time since this price
last MOVED". `_freshness_factor` consumed it as staleness and decayed to 0.25.
Measured on the served board 2026-08-08, all 100 MLB rows sat at ~11.9h inside a
1.2-minute window -- 100 motionless markets, every one scored down for not
moving overnight, on a board rebuilt 1.4 minutes earlier.

End to end, one market whose price last moved 11.9h ago but which we observed 4
minutes ago:

    without last_seen   book_age 42840  seen_age None   freshness 0.25
    with    last_seen   book_age 42840  seen_age  240   freshness 1.00

Absent seen-age must stay ABSENT rather than collapsing to the movement age --
dates predating the tracking have no entry, and substituting would recreate the
confusion the field exists to end.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from syndicate.features.shared.book_grid import build_book_grid
from syndicate.features.shared.layer2_board import build_layer2_rows
from syndicate.features.shared.odds_book_quotes import quote_key
from syndicate.features.shared.opportunity_signals import _freshness_factor

_NOW = datetime(2026, 8, 8, 18, 0, tzinfo=timezone.utc)
_MOVED = (_NOW - timedelta(hours=11.9)).isoformat()
_LOOKED = (_NOW - timedelta(minutes=4)).isoformat()


def _quote_rows():
    def row(selection: str) -> dict:
        return {
            "sport": "mlb",
            "kind": "game",
            "event_id": "e1",
            "bookmaker": "novig",
            "segment": "full",
            "market": "h2h",
            "selection": selection,
            "player_name": "",
            "line": None,
            "price": "-110",
            "book_updated_at": _MOVED,
            "captured_at": _MOVED,
        }

    return [row("home"), row("away")]


def _first_opportunity(last_seen):
    grid = build_book_grid(_quote_rows(), now=_NOW, last_seen=last_seen)
    return (build_layer2_rows(grid).get("opportunities") or [None])[0]


class FreshnessFactorTests(unittest.TestCase):
    def test_seen_age_wins_over_movement_age(self) -> None:
        self.assertEqual(_freshness_factor(11.9 * 3600, 240.0), 1.0)

    def test_movement_age_is_the_fallback_when_seen_is_unknown(self) -> None:
        """Conservative, not equivalent: pre-tracking dates keep old behaviour."""
        self.assertEqual(_freshness_factor(11.9 * 3600, None), _freshness_factor(11.9 * 3600))

    def test_a_genuinely_unobserved_market_is_still_discounted(self) -> None:
        """The fix must not become "everything is fresh"."""
        self.assertLess(_freshness_factor(60.0, 11.9 * 3600), 1.0)


class GridThreadingTests(unittest.TestCase):
    def test_grid_cell_carries_seen_age(self) -> None:
        rows = _quote_rows()
        seen = {quote_key(row): _LOOKED for row in rows}
        grid = build_book_grid(rows, now=_NOW, last_seen=seen)
        best = (grid[0].get("best") or {})
        side = best.get("home") or {}
        self.assertAlmostEqual(float(side["seen_age_seconds"]), 240.0, places=0)
        self.assertAlmostEqual(float(side["age_seconds"]), 11.9 * 3600, places=0)

    def test_absent_last_seen_leaves_the_field_none(self) -> None:
        grid = build_book_grid(_quote_rows(), now=_NOW)
        side = (grid[0].get("best") or {}).get("home") or {}
        self.assertIsNone(side.get("seen_age_seconds"))
        self.assertIsNotNone(side.get("age_seconds"), "movement age must still be reported")


class EndToEndTests(unittest.TestCase):
    def test_stable_market_observed_recently_scores_full_freshness(self) -> None:
        rows = _quote_rows()
        opportunity = _first_opportunity({quote_key(row): _LOOKED for row in rows})
        self.assertIsNotNone(opportunity)
        self.assertAlmostEqual(float(opportunity["quote"]["quote_seen_age_seconds"]), 240.0, places=0)
        self.assertEqual(opportunity["score"]["freshness_factor"], 1.0)

    def test_same_market_without_last_seen_is_discounted_as_before(self) -> None:
        """The regression this fixes, and proof the default path is unchanged."""
        opportunity = _first_opportunity(None)
        self.assertIsNone(opportunity["quote"]["quote_seen_age_seconds"])
        self.assertEqual(opportunity["score"]["freshness_factor"], 0.25)

    def test_movement_age_is_still_reported_either_way(self) -> None:
        """Time-since-moved remains a real market-activity signal; the fix
        reinterprets it, it does not delete it."""
        for last_seen in (None, {quote_key(row): _LOOKED for row in _quote_rows()}):
            opportunity = _first_opportunity(last_seen)
            self.assertAlmostEqual(float(opportunity["quote"]["book_age_seconds"]), 11.9 * 3600, places=0)


if __name__ == "__main__":
    unittest.main()
