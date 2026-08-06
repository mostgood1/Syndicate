"""#214 -- feeding the starving reconciliation autorun, end to end.

The defect: settlement was never broken, it was STARVED.
`RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN=true` on refresh-worker and
`reconcile_prediction_results_for_date` globs for `closing_lines_{date}.csv` /
`game_results_{date}.json`. Nothing emitted them, so every prediction logged
"no match found", was skipped, and `/api/portfolio/summary` read
`settled_count: 0` with `avg_clv: null` (production, 2026-08-06).

These run the REAL emitter and the REAL reconciler rather than asserting on
return values -- the #207 lesson that correct code on an unreached path proves
nothing.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_book_quotes as quotes_module
from syndicate.features.shared.odds_book_quotes import append_book_quotes
from syndicate.features.prediction_ledger import record_prediction
from syndicate.features.prediction_reconciliation import reconcile_prediction_results_for_date

DATE = "2026-08-06"
COMMENCE = "2026-08-06T23:05:00Z"
HOME, AWAY = "New York Yankees", "Boston Red Sox"


def _game(book: str, price: int, *, when: str) -> dict:
    return {
        "kind": "game", "event_id": "evt-1", "commence_time": COMMENCE,
        "home_team": HOME, "away_team": AWAY, "segment": "full",
        "market": "h2h", "selection": "home", "bookmaker": book,
        "price": price, "book_updated_at": when,
    }


def _prop(book: str, price: int, *, when: str) -> dict:
    return {
        "kind": "prop", "event_id": "evt-1", "commence_time": COMMENCE,
        "home_team": HOME, "away_team": AWAY, "segment": "full",
        "market": "batter_hits", "player_name": "Aaron Judge", "selection": "over",
        "line": 0.5, "bookmaker": book, "price": price, "book_updated_at": when,
    }


class SettlementInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = patch.object(quotes_module, "data_root", lambda: self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.out_dir = self.root / "settlement_inputs"
        self.ledger = self.root / "prediction_ledger.json"

        # Separate append calls, because that is what separate refresh cycles
        # are. Passing a whole time series in ONE call would be deduped to the
        # first observation per key -- correct for a single payload, wrong as a
        # simulation of the market moving.
        append_book_quotes(sport="mlb", date_str=DATE, publish=False,
                           captured_at="2026-08-06T18:05:00Z",
                           rows=[_game("fanduel", -140, when="2026-08-06T18:00:00Z"),
                                 _prop("fanduel", -140, when="2026-08-06T18:00:00Z")])
        append_book_quotes(sport="mlb", date_str=DATE, publish=False,
                           captured_at="2026-08-06T22:35:00Z",
                           rows=[_game("fanduel", -155, when="2026-08-06T22:00:00Z"),
                                 _game("draftkings", -150, when="2026-08-06T22:30:00Z"),
                                 _prop("draftkings", -150, when="2026-08-06T22:30:00Z")])
        # After first pitch -- must never be mistaken for a closing line.
        append_book_quotes(sport="mlb", date_str=DATE, publish=False,
                           captured_at="2026-08-07T00:35:00Z",
                           rows=[_game("betmgm", 400, when="2026-08-07T00:30:00Z")])

    def _emit(self, *, finals: list[dict] | None = None) -> None:
        import scripts.emit_settlement_inputs as emitter

        payload = finals if finals is not None else [{
            "sport": "mlb", "date": DATE, "event_id": "823358",
            "home_team": HOME, "away_team": AWAY, "home_score": 5, "away_score": 2,
        }]
        with patch.object(emitter, "_mlb_finals", lambda date_str: payload):
            emitter.main(["--date", DATE, "--days", "1", "--sports", "mlb", "--out-dir", str(self.out_dir)])

    def _rows(self) -> list[dict]:
        return list(csv.DictReader((self.out_dir / f"closing_lines_{DATE}.csv").open(encoding="utf-8")))

    def test_close_is_the_best_book_at_the_last_pregame_observation(self) -> None:
        self._emit()
        row = next(item for item in self._rows() if item["market"] == "h2h")
        # -150 (draftkings) pays better than fanduel's -155 close.
        self.assertEqual(row["closing_price"], "-150")
        self.assertEqual(row["closing_bookmaker"], "draftkings")
        # The +400 in-play quote must not have been taken as the close.
        self.assertNotEqual(row["closing_price"], "400")

    def test_outcome_and_closing_price_ride_on_the_same_row(self) -> None:
        """Reconciliation reads BOTH off one matched row. Splitting them across
        two files means whichever matches first wins and the bet settles with a
        null closing price -- which is how this was written the first time."""
        self._emit()
        row = next(item for item in self._rows() if item["market"] == "h2h")
        self.assertEqual(row["result"], "win", "home won 5-2")
        self.assertTrue(row["closing_price"])

    def test_reconciliation_settles_a_game_bet_and_computes_price_clv(self) -> None:
        self._emit()
        record = record_prediction(
            sport="mlb", market="h2h", selection="home", odds=-140,
            features_snapshot={"pick": "home", "event_id": "evt-1", "game_date": DATE},
            quote={"bookmaker": "fanduel", "price": -140, "price_rank": 1, "books_quoting": 2},
            ledger_path=self.ledger,
        )
        outcome = reconcile_prediction_results_for_date(
            DATE, ledger_path=self.ledger, result_roots=[self.out_dir]
        )
        self.assertEqual(outcome["summary"]["resolved"], 1, "the bet did not settle")
        result = next(item for item in outcome["predictions"] if item["id"] == record["id"])["result"]
        self.assertEqual(result["outcome"], "win")
        # Struck at -140, closed -150: the market moved toward us.
        self.assertEqual(result["original_price"], -140)
        self.assertEqual(str(result["closing_price"]), "-150")
        self.assertGreater(result["clv_pct"], 0)
        self.assertTrue(result["beat_close"])

    def test_props_get_a_closing_price_but_do_not_settle_yet(self) -> None:
        """The known, stated gap. Grading a prop needs the player's actual stat
        line and no actuals source is wired. The closing price is captured and
        ready, but the bet stays pending -- and because CLV is written at
        settlement, it has no CLV either. Pinned so a later actuals source
        turns this test red rather than passing silently."""
        self._emit()
        prop_row = next(item for item in self._rows() if item["market"] == "batter_hits")
        # -140 beats -150: risk 140 to win 100 is a better price than risk 150
        # to win 100. Worth spelling out -- the first version of this assertion
        # picked -150 by reading "bigger number" as "better price".
        self.assertEqual(prop_row["closing_price"], "-140")
        self.assertEqual(prop_row["closing_bookmaker"], "fanduel")
        self.assertFalse(prop_row.get("result"), "no actuals source should mean no grade")

        record = record_prediction(
            sport="mlb", market="batter_hits", selection="Aaron Judge", odds=-140,
            features_snapshot={"pick": "Over", "line": 0.5, "event_id": "evt-1", "game_date": DATE},
            ledger_path=self.ledger,
        )
        outcome = reconcile_prediction_results_for_date(
            DATE, ledger_path=self.ledger, result_roots=[self.out_dir]
        )
        settled = next(item for item in outcome["predictions"] if item["id"] == record["id"])
        self.assertNotIn("result", settled)

    def test_a_date_with_no_quotes_emits_nothing_rather_than_an_empty_file(self) -> None:
        import scripts.emit_settlement_inputs as emitter

        with patch.object(emitter, "_mlb_finals", lambda date_str: []):
            emitter.main(["--date", "1999-01-01", "--days", "1", "--sports", "mlb", "--out-dir", str(self.out_dir)])
        # An empty file would make reconciliation report it "found a result
        # file" for a date it has nothing for.
        self.assertFalse((self.out_dir / "closing_lines_1999-01-01.csv").exists())

    def test_game_results_json_is_not_emitted_under_a_reconciliation_pattern(self) -> None:
        """finals_{date}.json on purpose: game_results_{date}.json sorts ahead of
        closing_lines in RECONCILIATION_PATTERNS and would shadow the merged
        file, reintroducing the null-closing-price bug."""
        self._emit()
        self.assertTrue((self.out_dir / f"finals_{DATE}.json").exists())
        self.assertFalse((self.out_dir / f"game_results_{DATE}.json").exists())


if __name__ == "__main__":
    unittest.main()
