"""Both sides of a market are recorded at selection time — `#626`(g), Phase 0.

MEASURED (lane `mlb-accuracy-assessment`, 2026-08-31): **0 of 8,778** graded
player-date-market-line keys carried both sides. Only the side we took is ever
recorded, so our own ledger cannot answer whether the side selection was right,
what the two-way hold cost, or what the de-vigged fair was at the instant of
choice. That lane had to rebuild the opposite price from a separate odds
history at 81.5% coverage and price the inversion on an estimate.

The board holds every side's best price at row-build time (`best`, `sides`), so
this is a persistence gap, not a data gap.

`test_the_payload_cost_is_two_scalars_per_other_side` is the guard that matters
as much as the feature: the shortlist is one keyvalue write whose ceiling has
corrupted production once, so the shape must stay two scalars and must not grow
the per-book fan-out `book_prices` has.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared.clv_opening_ledger import _opening_record, record_openings


class OpeningLedgerCarriesBothSidesTests(unittest.TestCase):
    def _row(self, other_sides):
        return {
            "sport": "mlb",
            "event_id": "evt-1",
            "market": "batter_hits",
            "side": "over",
            "line": 0.5,
            "player_name": "A Batter",
            "quote": {
                "price": -120,
                "bookmaker": "draftkings",
                "book_prices": {"draftkings": -120, "fanduel": -118},
                "fair_probability": 0.52,
                "fair_method": "consensus",
                "other_sides": other_sides,
            },
        }

    def test_the_other_side_is_persisted(self) -> None:
        record = _opening_record(
            self._row({"under": {"price": 100, "bookmaker": "fanduel"}}), "k", "2026-09-01T00:00:00Z"
        )
        self.assertEqual(record["other_sides"], {"under": {"price": 100, "bookmaker": "fanduel"}})

    def test_a_three_way_market_keeps_both_others(self) -> None:
        """Named by side, not "opposite": soccer h2h_3_way has two others."""
        others = {
            "draw": {"price": 240, "bookmaker": "pinnacle"},
            "away": {"price": 310, "bookmaker": "betmgm"},
        }
        record = _opening_record(self._row(others), "k", "2026-09-01T00:00:00Z")
        self.assertEqual(set(record["other_sides"]), {"draw", "away"})

    def test_absent_stays_absent_never_an_empty_dict(self) -> None:
        """A one-way row has no other side; `None` says so, `{}` would imply we
        looked and found nothing quoted."""
        self.assertIsNone(_opening_record(self._row(None), "k", "2026-09-01T00:00:00Z")["other_sides"])
        self.assertIsNone(_opening_record(self._row({}), "k", "2026-09-01T00:00:00Z")["other_sides"])

    def test_it_survives_the_write_and_read_round_trip(self) -> None:
        """Off-is-not-on at the artifact level: the field must be in the file
        on disk, not merely in the dict the builder returned."""
        with TemporaryDirectory() as tmp:
            report = record_openings(
                [self._row({"under": {"price": 100, "bookmaker": "fanduel"}})],
                date="2026-09-01",
                now=datetime(2026, 9, 1, tzinfo=timezone.utc),
                root=Path(tmp),
            )
            self.assertEqual(report["openings_written"], 1)
            written = [json.loads(line) for line in Path(report["path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["other_sides"], {"under": {"price": 100, "bookmaker": "fanduel"}})

    def test_the_payload_cost_is_two_scalars_per_other_side(self) -> None:
        """The shortlist is ONE keyvalue write and its ceiling has corrupted
        production once, so this field must never grow a per-book fan-out."""
        record = _opening_record(
            self._row({"under": {"price": 100, "bookmaker": "fanduel"}}), "k", "2026-09-01T00:00:00Z"
        )
        for side_payload in record["other_sides"].values():
            self.assertEqual(
                set(side_payload),
                {"price", "bookmaker"},
                "two scalars only — a nested dict per book would multiply the artifact",
            )


class BoardStampsBothSidesTests(unittest.TestCase):
    """The board is where both sides are in scope; pin that it stamps them.

    Structural rather than a full board build: `build_layer2_rows` needs a
    complete grid row, and what this guards is the one dict-comprehension that
    reads `best`/`sides` for the sides NOT taken.
    """

    def test_the_quote_stamps_every_side_except_this_one(self) -> None:
        source = Path("syndicate/features/shared/layer2_board.py").read_text(encoding="utf-8-sig")
        self.assertIn('"other_sides": {', source)
        self.assertIn("for other in sides", source)
        self.assertIn("if other != side and isinstance(best.get(other), Mapping)", source)

    def test_the_opening_ledger_carries_it_through_rather_than_re_deriving(self) -> None:
        source = Path("syndicate/features/shared/clv_opening_ledger.py").read_text(encoding="utf-8-sig")
        self.assertIn('"other_sides": quote.get("other_sides") or None,', source)


if __name__ == "__main__":
    unittest.main()
