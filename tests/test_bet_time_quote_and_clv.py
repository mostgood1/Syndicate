"""Bet-time quote capture and price CLV (#213).

The defect these guard, measured on production 2026-08-06:
/api/portfolio/summary returned total_tracked 5, settled_count 0, avg_clv null.
Bets logged fine and nothing could ever have a closing-line value, because the
price struck was never recorded and the only CLV available was a LINE
difference -- undefined for moneyline, which is most of what gets bet.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared.odds_book_quotes import append_book_quotes, quote_ref_for_bet
from syndicate.features import prediction_ledger as ledger_module
from syndicate.features.prediction_ledger import record_prediction, record_result


def _rows() -> list[dict]:
    common = {
        "kind": "game",
        "event_id": "evt-1",
        "commence_time": "2026-08-06T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "segment": "full",
        "book_updated_at": "2026-08-06T21:00:00Z",
    }
    return [
        {**common, "bookmaker": "fanduel", "market": "h2h", "selection": "home", "price": -120},
        {**common, "bookmaker": "draftkings", "market": "h2h", "selection": "home", "price": -108},
        {**common, "bookmaker": "betmgm", "market": "h2h", "selection": "home", "price": -115},
        {**common, "bookmaker": "fanduel", "market": "totals", "selection": "over", "line": 8.5, "price": -110},
        {**common, "bookmaker": "draftkings", "market": "totals", "selection": "over", "line": 8.5, "price": 100},
        {**common, "bookmaker": "fanduel", "market": "totals", "selection": "over", "line": 9.0, "price": 130},
    ]


class BetTimeQuoteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(quotes_module, "data_root", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        append_book_quotes(
            sport="mlb",
            date_str="2026-08-06",
            rows=_rows(),
            captured_at="2026-08-06T21:02:00Z",
            publish=False,
        )

    def test_board_wording_resolves_to_the_oddsapi_market(self) -> None:
        """The board says "moneyline"; the log says "h2h". A lookup that
        required an exact match would silently record no quote for every
        moneyline bet ever logged."""
        ref = quote_ref_for_bet(
            sport="mlb", date_str="2026-08-06", event_id="evt-1", market="moneyline", selection="home"
        )
        self.assertIsNotNone(ref)
        self.assertEqual(ref["books_quoting"], 3)
        self.assertEqual(ref["best_bookmaker"], "draftkings")

    def test_team_name_resolves_to_a_side(self) -> None:
        ref = quote_ref_for_bet(
            sport="mlb", date_str="2026-08-06", event_id="evt-1", market="h2h", selection="New York Yankees"
        )
        self.assertIsNotNone(ref)
        self.assertEqual(ref["best_price"], -108)

    def test_the_book_actually_bet_is_ranked_not_replaced(self) -> None:
        ref = quote_ref_for_bet(
            sport="mlb", date_str="2026-08-06", event_id="evt-1",
            market="moneyline", selection="home", bookmaker="fanduel",
        )
        self.assertEqual(ref["bookmaker"], "fanduel")
        self.assertEqual(ref["price"], -120)
        self.assertEqual(ref["price_rank"], 3)
        self.assertEqual(ref["best_price"], -108)

    def test_line_selects_the_right_total(self) -> None:
        ref = quote_ref_for_bet(
            sport="mlb", date_str="2026-08-06", event_id="evt-1",
            market="total", selection="over", line=9.0,
        )
        self.assertEqual(ref["price"], 130)
        self.assertEqual(ref["books_quoting"], 1)

    def test_no_log_for_the_date_returns_none_rather_than_an_empty_shell(self) -> None:
        self.assertIsNone(quote_ref_for_bet(sport="mlb", date_str="1999-01-01", event_id="evt-1", market="h2h"))
        self.assertIsNone(quote_ref_for_bet(sport="nfl", date_str="2026-08-06", event_id="evt-1", market="h2h"))

    def test_narrowing_falls_back_rather_than_returning_nothing(self) -> None:
        """Progressive narrowing is deliberate: an unrecognised market or a
        selection the log words differently must not wipe out an otherwise good
        event match, or every bet whose wording drifts records no quote at all.
        The fallback still describes a real market on the right event."""
        ref = quote_ref_for_bet(
            sport="mlb", date_str="2026-08-06", event_id="evt-1",
            market="some-market-we-do-not-know", selection="whatever",
        )
        self.assertIsNotNone(ref)
        self.assertGreaterEqual(ref["books_quoting"], 1)


class PriceClvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Path(self.tmp.name) / "prediction_ledger.json"

    def test_beating_the_close_is_positive(self) -> None:
        """Bet -110, market closes -130: the market moved toward us, so we beat
        the close. The raw American numbers move the opposite way to the
        intuition, which is exactly why the sign is pinned here."""
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, ledger_path=self.ledger
        )
        result = record_result(
            prediction_id=record["id"], outcome="win",
            original_price=-110, closing_price=-130, ledger_path=self.ledger,
        )
        self.assertGreater(result["clv_pct"], 0)
        self.assertTrue(result["beat_close"])

    def test_losing_to_the_close_is_negative(self) -> None:
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-130, ledger_path=self.ledger
        )
        result = record_result(
            prediction_id=record["id"], outcome="loss",
            original_price=-130, closing_price=-110, ledger_path=self.ledger,
        )
        self.assertLess(result["clv_pct"], 0)
        self.assertFalse(result["beat_close"])

    def test_moneyline_gets_clv_where_line_clv_is_structurally_undefined(self) -> None:
        """The whole reason price CLV exists. A moneyline has no line, so
        _clv_from_lines can only ever return None for it -- which is why the
        live ledger reads avg_clv: null across the board."""
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, ledger_path=self.ledger
        )
        result = record_result(
            prediction_id=record["id"], outcome="win",
            original_price=-110, closing_price=-125, ledger_path=self.ledger,
        )
        self.assertIsNone(result["clv"], "line CLV should be undefined for a moneyline")
        self.assertIsNotNone(result["clv_pct"], "price CLV must still be defined")

    def test_unknown_clv_is_none_not_false(self) -> None:
        """'We did not beat the close' and 'we cannot tell' must stay
        distinguishable, or any beat-the-close rate built over this column
        silently counts unknowns as losses."""
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-110, ledger_path=self.ledger
        )
        result = record_result(
            prediction_id=record["id"], outcome="win", original_price=-110, ledger_path=self.ledger
        )
        self.assertIsNone(result["clv_pct"])
        self.assertIsNone(result["beat_close"])

    def test_quote_survives_the_ledger_round_trip(self) -> None:
        quote = {"bookmaker": "draftkings", "price": -108, "price_rank": 1, "books_quoting": 6}
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-108,
            quote=quote, ledger_path=self.ledger,
        )
        self.assertEqual(record["quote"]["bookmaker"], "draftkings")
        reloaded = ledger_module.load_all_predictions(ledger_path=self.ledger)
        stored = next(item for item in reloaded if item["id"] == record["id"])
        self.assertEqual(stored["quote"]["books_quoting"], 6)


if __name__ == "__main__":
    unittest.main()
