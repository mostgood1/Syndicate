"""The game-market option-value measurement — item 05 / `#624`.

Every test here is a real error on the way to the number, or a guard against a
wrong one coming back:

  * THE 0.75 CONSTANT. The 08-31 assessment converts entry improvement to ROI
    at "each 1pp is worth roughly +0.75pp of ROI" and cites item 07's table for
    it. That table gives ~1.77. Pinned so the constant cannot return.
  * THE WRONG BOOK, which the corrected slope does not fix. Item 07's table
    prices a PROP book; the number it was spent on is a GAME-market
    measurement. Pinned by asserting the two tables give different answers at
    the cost each book actually pays.
  * THE ANCHOR. The price on a board row is OLDER than the order that takes it
    (median 16.5 min here). Anchoring the de-vig on `submitted_at` made the
    book's mean entry cost come out NEGATIVE — paying less than fair, which is
    not a thing. Pinned by a row whose book has moved since it showed the fill
    price.
  * THE SNAPSHOT KEY. `captured_at` is the refresh-cycle stamp shared by every
    book in one pass; `snapshot_ts` is each book's own last-update time.
    Grouping the superset on the latter finds almost no cross-book cells, and
    it does not error — it silently returns a tiny population that still looks
    like a measurement.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _stamp(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat()


def _load():
    spec = importlib.util.spec_from_file_location(
        "game_market_option_value_under_test",
        REPO_ROOT / "scripts" / "measure_game_market_option_value.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()


def _row(win, q_fill, p, stake=1.0, pnl=0.0, push=False, book="kalshi"):
    """A priced row, in the shape `price_book` emits."""
    return {"date": "2026-08-27", "market": "h2h", "segment": "full", "side": "home",
            "line": None, "book": book, "venue": "paper", "outcome": "won" if win else "lost",
            "win": 1.0 if win else 0.0, "push": push, "stake": stake, "pnl": pnl,
            "q_fill": q_fill, "p": p, "side_cost_pp": (q_fill - p) * 100.0,
            "hold_pct": 0.0, "quote_age_min": 0.0, "best_sportsbook": None,
            "best_exchange": None, "best_any": None,
            "holder_sportsbook": None, "holder_any": None}


class ImpliedProbabilityTests(unittest.TestCase):
    def test_real_prices_convert(self) -> None:
        self.assertAlmostEqual(MOD.implied(-110), 110 / 210, places=6)
        self.assertAlmostEqual(MOD.implied(+110), 100 / 210, places=6)
        self.assertAlmostEqual(MOD.implied(-100), 0.5, places=6)

    def test_impossible_prices_are_refused_not_coerced(self) -> None:
        for bad in (-89.125, -50, 0, 42, 99.9, None, "", "n/a"):
            self.assertIsNone(MOD.implied(bad), bad)

    def test_dead_prices_are_refused(self) -> None:
        """Section 1 of the assessment: settled/dead prices contaminate 6.7% of
        priced games and a naive backtest over them returned +101% to +331%."""
        for dead in (-100000, +99900, -1001, 1001):
            self.assertIsNone(MOD.implied(dead), dead)
        self.assertIsNotNone(MOD.implied(-999))


class OppositeSideTests(unittest.TestCase):
    def test_spreads_mirror_the_line(self) -> None:
        """`away -1.5` is the other side of `home +1.5`. Sharing the line
        instead would pair a side against itself and de-vig to an overround of
        exactly 2x one price."""
        self.assertEqual(MOD.opposite("spreads", "away", -1.5), ("home", 1.5))
        self.assertEqual(MOD.opposite("spreads_alt", "home", 2.5), ("away", -2.5))

    def test_totals_and_moneylines_share_the_line(self) -> None:
        self.assertEqual(MOD.opposite("totals", "over", 8.5), ("under", 8.5))
        self.assertEqual(MOD.opposite("h2h", "home", None), ("away", None))

    def test_a_three_way_market_has_no_single_opposite(self) -> None:
        """`h2h_3_way` carries a draw leg, so a two-way de-vig would drop a
        third of the overround and read the book as cheaper than it is."""
        self.assertEqual(MOD.opposite("h2h_3_way", "home", None), (None, None))
        self.assertNotIn("h2h_3_way", MOD.GAME_MARKETS)


class RoiTests(unittest.TestCase):
    def test_a_push_returns_the_stake_at_any_price(self) -> None:
        """It must not be scored as a loss and must not leave the denominator:
        both mistakes move the ROI in the same direction and neither errors."""
        rows = [_row(True, 0.5, 0.5), _row(False, 0.5, 0.5, push=True)]
        self.assertAlmostEqual(MOD.roi_at_quoted_price(rows), 50.0, places=6)

    def test_the_curve_passes_through_the_price_actually_paid(self) -> None:
        """The load-bearing invariant. It is what caught the anchor defect: with
        `submitted_at` as the anchor the curve read -1.05% where the ledger read
        +5.31%, and a table whose own operating point disagrees with the ledger
        by six points is not a table."""
        rows = [_row(True, 0.55, 0.52), _row(False, 0.40, 0.37), _row(True, 0.62, 0.60)]
        today = sum(r["side_cost_pp"] for r in rows) / len(rows)
        self.assertAlmostEqual(MOD.roi_at_book_cost(rows, today, today),
                               MOD.roi_at_quoted_price(rows), places=9)

    def test_zero_cost_is_entry_at_the_fair_price(self) -> None:
        rows = [_row(True, 0.55, 0.52), _row(False, 0.40, 0.37)]
        today = sum(r["side_cost_pp"] for r in rows) / len(rows)
        self.assertAlmostEqual(MOD.roi_at_book_cost(rows, 0.0, today),
                               MOD.roi_at_entry(rows, lambda r: r["p"]), places=9)

    def test_the_two_methods_coincide_when_the_vig_is_uniform(self) -> None:
        """Which is why item 07 could use either. Its prop book's vig ran
        3.07-4.63pp across ten market/line cells; this book's runs 0.60pp on
        exchange-booked rows against 2.55pp on sportsbook-booked ones, a 4x
        spread, and there the two methods part company."""
        uniform = [_row(True, 0.53, 0.50), _row(False, 0.43, 0.40), _row(True, 0.63, 0.60)]
        today = sum(r["side_cost_pp"] for r in uniform) / len(uniform)
        for target in (0.0, 1.0, 2.0, 3.0):
            self.assertAlmostEqual(MOD.roi_at_book_cost(uniform, target, today),
                                   MOD.roi_at_uniform_cost(uniform, target), places=6)

    def test_the_two_methods_diverge_when_it_is_not(self) -> None:
        mixed = [_row(True, 0.505, 0.50), _row(False, 0.44, 0.40), _row(True, 0.65, 0.60)]
        today = sum(r["side_cost_pp"] for r in mixed) / len(mixed)
        self.assertGreater(abs(MOD.roi_at_book_cost(mixed, 3.0, today)
                               - MOD.roi_at_uniform_cost(mixed, 3.0)), 1.0)

    def test_cheaper_entry_never_lowers_roi(self) -> None:
        rows = [_row(True, 0.55, 0.52), _row(False, 0.40, 0.37), _row(True, 0.62, 0.60)]
        today = sum(r["side_cost_pp"] for r in rows) / len(rows)
        previous = None
        for step in range(0, 41):
            roi = MOD.roi_at_book_cost(rows, step / 10.0, today)
            if previous is not None:
                self.assertLessEqual(roi, previous + 1e-9)
            previous = roi

    def test_an_empty_book_refuses_rather_than_returning_zero(self) -> None:
        """A ROI of 0.0% on no rows is indistinguishable from a break-even book."""
        with self.assertRaises(ValueError):
            MOD.roi_at_quoted_price([])


class SensitivityTests(unittest.TestCase):
    def test_both_tables_reproduce_themselves_at_their_own_points(self) -> None:
        for table in (MOD.PROP_SENSITIVITY, MOD.GAME_SENSITIVITY):
            for side_cost, roi in table:
                self.assertAlmostEqual(MOD.roi_from_table(side_cost, table), roi, places=6)

    def test_the_prop_slope_is_about_1_77_not_the_published_0_75(self) -> None:
        """The first of section 7h's two defects. The constant was cited to the
        very table that refutes it, and the citation is why nobody checked."""
        slope = MOD.table_slope(MOD.PROP_SENSITIVITY, 2.50, 4.05)
        self.assertAlmostEqual(slope, 1.7677, places=3)
        self.assertGreater(slope, 2 * 0.75, "0.75 understates by more than half")

    def test_the_game_slope_is_steeper_still(self) -> None:
        """Measured on 621 settled MLB game-market orders, 2026-08-22..08-31."""
        self.assertAlmostEqual(MOD.table_slope(MOD.GAME_SENSITIVITY, 2.50, 4.05), 1.91, places=2)
        self.assertAlmostEqual(MOD.table_slope(MOD.GAME_SENSITIVITY, 0.00, 1.00), 2.45, places=2)
        for span in ((2.50, 4.05), (0.00, 1.00)):
            self.assertGreater(MOD.table_slope(MOD.GAME_SENSITIVITY, *span), 2 * 0.75)

    def test_the_two_books_do_not_operate_in_the_same_place(self) -> None:
        """The second defect, and the one a corrected slope does not fix. The
        prop book pays 4.05pp per side; this one pays 0.88pp. Reading the prop
        curve at the game book's cost lands at the prop curve's own zero-hold
        end, where there is no measurement of a game market at all."""
        self.assertAlmostEqual(MOD.GAME_MEASURED_SIDE_COST_PP, 0.88, places=2)
        self.assertLess(MOD.GAME_MEASURED_SIDE_COST_PP, 4.05 / 4)

    def test_pricing_the_same_improvement_off_the_wrong_table_misleads(self) -> None:
        """+1.0pp of better entry, priced at each book's own operating point."""
        game = (MOD.roi_from_table(MOD.GAME_MEASURED_SIDE_COST_PP - 1.0, MOD.GAME_SENSITIVITY)
                - MOD.roi_from_table(MOD.GAME_MEASURED_SIDE_COST_PP, MOD.GAME_SENSITIVITY))
        prop = (MOD.roi_from_table(4.05 - 1.0, MOD.PROP_SENSITIVITY)
                - MOD.roi_from_table(4.05, MOD.PROP_SENSITIVITY))
        self.assertGreater(game, 0.0)
        self.assertGreater(prop, 0.0)
        self.assertGreater(abs(game - prop), 0.4,
                           "if these ever agree, say so instead of defending the split")

    def test_it_clamps_instead_of_extrapolating(self) -> None:
        """Past a measured endpoint there is no measurement, so it must not
        invent one -- a negative entry cost is not a bigger edge."""
        self.assertEqual(MOD.roi_from_table(-3.0, MOD.GAME_SENSITIVITY), MOD.GAME_SENSITIVITY[0][1])
        self.assertEqual(MOD.roi_from_table(99.0, MOD.GAME_SENSITIVITY), MOD.GAME_SENSITIVITY[-1][1])

    def test_it_interpolates_between_measured_points(self) -> None:
        low, high = MOD.GAME_SENSITIVITY[0], MOD.GAME_SENSITIVITY[1]
        middle = (low[0] + high[0]) / 2
        self.assertAlmostEqual(MOD.roi_from_table(middle, MOD.GAME_SENSITIVITY),
                               (low[1] + high[1]) / 2, places=6)

    def test_an_empty_table_refuses(self) -> None:
        """The published table starts empty in a fresh copy of this module; a
        silent 0.0% there would be a fabricated ROI."""
        with self.assertRaises(ValueError):
            MOD.roi_from_table(1.0, ())

    def test_both_tables_are_sorted_and_monotone(self) -> None:
        for table in (MOD.PROP_SENSITIVITY, MOD.GAME_SENSITIVITY):
            costs = [cost for cost, _ in table]
            rois = [roi for _, roi in table]
            self.assertEqual(costs, sorted(costs))
            self.assertEqual(rois, sorted(rois, reverse=True))


class AnchorTests(unittest.TestCase):
    """The price is older than the order. These pin the anchor that fixes it."""

    @staticmethod
    def _index(quotes):
        by_side, by_key = {}, {}
        for (book, selection, line), series in quotes.items():
            by_side[("e1", "h2h", "full", book, selection, line)] = sorted(series)
            by_key.setdefault(("e1", "h2h", "full", selection, line), {})[book] = sorted(series)
        return by_side, by_key

    @staticmethod
    def _order(**kwargs):
        base = {"_date": "2026-08-27", "sport": "mlb", "market": "h2h", "segment": "full",
                "side": "home", "line": None, "book": "kalshi", "event_id": "e1",
                "status": "filled", "outcome": "won", "fill_price": -110,
                "fill_stake_dollars": 1.0, "pnl_dollars": 0.9091,
                "submitted_at": "2026-08-27T20:00:00Z"}
        base.update(kwargs)
        return base

    def test_it_anchors_on_the_snapshot_that_showed_the_fill_price(self) -> None:
        """The book quoted -110 at 19:00 and has since moved to -150. The de-vig
        must use 19:00. Using 20:00 -- the submission -- would pair a -110 fill
        against a 19:00-less overround and can make the entry cost negative."""
        t19 = 1000000.0
        t20 = t19 + 3600.0
        index = {"2026-08-27": self._index({
            ("kalshi", "home", None): [(t19, -110), (t20, -150)],
            ("kalshi", "away", None): [(t19, -105), (t20, +120)],
        })}
        rows, refused, ages = MOD.price_book(
            [self._order(submitted_at=_stamp(t20))], index, 7200.0, MOD.EXCHANGES_NARROW)
        self.assertEqual(len(rows), 1, refused)
        row = rows[0]
        overround = MOD.implied(-110) + MOD.implied(-105)
        self.assertAlmostEqual(row["hold_pct"], (overround - 1.0) * 100.0, places=6)
        self.assertGreater(row["side_cost_pp"], 0.0)
        self.assertAlmostEqual(ages[0], 60.0, places=3)

    def test_a_fill_price_the_book_never_showed_is_refused_not_guessed(self) -> None:
        """Absent must not fall through to the permissive branch. 206 of 929
        orders land here -- overwhelmingly venue-direct prices `book_quotes`
        never captured -- and they are reported as a coverage bound."""
        t19 = 1000000.0
        index = {"2026-08-27": self._index({
            ("kalshi", "home", None): [(t19, -150)],
            ("kalshi", "away", None): [(t19, +120)],
        })}
        rows, refused, _ = MOD.price_book([self._order(submitted_at=_stamp(t19 + 60))], index,
                                          7200.0, MOD.EXCHANGES_NARROW)
        self.assertEqual(rows, [])
        self.assertEqual(refused["fill_price_never_quoted_before_submit"], 1)

    def test_a_price_first_shown_after_submission_does_not_anchor(self) -> None:
        """Time alignment: a quote from after the decision is not evidence about
        it. This is the defect class that inverted item 05's first measurement."""
        t19, t21 = 1000000.0, 1000000.0 + 7200.0
        index = {"2026-08-27": self._index({
            ("kalshi", "home", None): [(t19, -150), (t21, -110)],
            ("kalshi", "away", None): [(t19, +120), (t21, -105)],
        })}
        rows, refused, _ = MOD.price_book([self._order(submitted_at=_stamp(t19 + 3600))], index,
                                          7200.0, MOD.EXCHANGES_NARROW)
        self.assertEqual(rows, [])
        self.assertEqual(refused["fill_price_never_quoted_before_submit"], 1)

    def test_best_available_separates_execution_venues_from_the_rest(self) -> None:
        """Item 05 proposes making the board read the VENUE feeds. It cannot
        make the board bet at `onexbet`, so a residual held there is not a prize
        this item can claim -- 63.7% of the measured residual sits exactly
        there."""
        at = 1000000.0
        books = {"kalshi": [(at, -105)], "onexbet": [(at, +120)], "fanduel": [(at, -130)]}
        best, holder = MOD.best_available(books, at, 3600.0, MOD.EXCHANGES_NARROW)
        self.assertEqual(holder["any"], "onexbet")
        self.assertEqual(holder["exchange"], "kalshi")
        self.assertEqual(holder["sportsbook"], "onexbet")
        self.assertLess(best["any"], best["exchange"])

    def test_best_available_ignores_a_price_that_was_gone_by_the_anchor(self) -> None:
        """Scanning a window for its lowest tick would credit a price nobody
        could still take."""
        at = 1000000.0
        books = {"fanduel": [(at - 7200, +300), (at - 60, -130)]}
        best, _ = MOD.best_available(books, at, 3600.0, MOD.EXCHANGES_NARROW)
        self.assertAlmostEqual(best["sportsbook"], MOD.implied(-130), places=9)


class SupersetKeyTests(unittest.TestCase):
    """`captured_at` is the refresh cycle; `snapshot_ts` is per book."""

    def _shard(self, directory: Path, rows) -> Path:
        path = directory / "game_quotes_2026-08-27.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return path

    def test_books_in_one_refresh_cycle_land_in_one_cell(self) -> None:
        """Their `snapshot_ts` differ by a second, as they really do in the
        shard. Grouping on that would find no cross-book cell at all and would
        report a real-looking measurement over a near-empty population."""
        rows = [
            {"captured_at": "2026-08-27T06:16:04.694009+00:00", "snapshot_ts": "2026-08-27T06:15:32Z",
             "event_id": "e1", "bookmaker": "fanduel", "market": "h2h", "segment": "full",
             "selection": "home", "line": None, "price": -130},
            {"captured_at": "2026-08-27T06:16:04.694009+00:00", "snapshot_ts": "2026-08-27T06:15:31Z",
             "event_id": "e1", "bookmaker": "kalshi", "market": "h2h", "segment": "full",
             "selection": "home", "line": None, "price": -110},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._shard(Path(tmp), rows)
            result = MOD.superset_option_value({"2026-08-27": path}, MOD.EXCHANGES_NARROW)
        self.assertEqual(result["2026-08-27"]["n"], 1)
        self.assertEqual(result["2026-08-27"]["wins"], 1)
        gain = result["2026-08-27"]["gains"][0]
        self.assertAlmostEqual(gain, (MOD.implied(-130) - MOD.implied(-110)) * 100.0, places=6)

    def test_a_cell_with_no_exchange_is_not_counted(self) -> None:
        """It contributes a guaranteed zero and would dilute the rate toward the
        answer we want to avoid reporting."""
        rows = [
            {"captured_at": "c1", "snapshot_ts": "s1", "event_id": "e1", "bookmaker": "fanduel",
             "market": "h2h", "segment": "full", "selection": "home", "line": None, "price": -130},
            {"captured_at": "c1", "snapshot_ts": "s2", "event_id": "e1", "bookmaker": "betmgm",
             "market": "h2h", "segment": "full", "selection": "home", "line": None, "price": -120},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = self._shard(Path(tmp), rows)
            result = MOD.superset_option_value({"2026-08-27": path}, MOD.EXCHANGES_NARROW)
        self.assertEqual(result, {})

    def test_sides_and_lines_do_not_share_a_cell(self) -> None:
        """Comparing `over 8.5` against `under 8.5` as if they were the same
        selection would read the whole two-way hold as an improvement."""
        rows = []
        for selection, price in (("over", -130), ("under", -110)):
            rows.append({"captured_at": "c1", "snapshot_ts": "s1", "event_id": "e1",
                         "bookmaker": "fanduel", "market": "totals", "segment": "full",
                         "selection": selection, "line": 8.5, "price": price})
            rows.append({"captured_at": "c1", "snapshot_ts": "s2", "event_id": "e1",
                         "bookmaker": "kalshi", "market": "totals", "segment": "full",
                         "selection": selection, "line": 8.5, "price": price})
        with tempfile.TemporaryDirectory() as tmp:
            path = self._shard(Path(tmp), rows)
            result = MOD.superset_option_value({"2026-08-27": path}, MOD.EXCHANGES_NARROW)
        self.assertEqual(result["2026-08-27"]["n"], 2)
        for gain in result["2026-08-27"]["gains"]:
            self.assertAlmostEqual(gain, 0.0, places=9)


if __name__ == "__main__":
    unittest.main()
