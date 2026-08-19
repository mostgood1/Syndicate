"""Stage 0 pick ledger: the properties that make it usable as evidence.

This table is what `pick_gate._SERVING_REGISTRY` reopens a market on, so its
failure modes are not "wrong number on a dashboard" -- they are "a suppressed
market reopens on evidence that was never real". The tests below target exactly
those:

  * an OPENING line is never rewritten (or open-vs-close silently becomes
    close-vs-close)
  * upsert is genuinely idempotent (or a weekly autorun inflates its own n)
  * the market's sign is not inverted (a flipped spread still produces
    plausible numbers)
  * leaked rating sources are FLAGGED and never pooled with clean ones
  * one book under two spellings does not grade as two books
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from syndicate.features.football.pick_ledger import (
    PickLedgerRow,
    coverage,
    evaluate,
    is_leaked_rating_source,
    leak_warning,
    load_ledger,
    ledger_path,
    normalise_provider,
    upsert,
)


def _row(**kw) -> PickLedgerRow:
    base = dict(
        sport="ncaaf", season=2025, week=1, game_id="g1",
        home_team="Home", away_team="Away", provider="DraftKings",
    )
    base.update(kw)
    return PickLedgerRow(**base)


class OpeningLineImmutabilityTests(unittest.TestCase):
    def test_opening_line_is_never_rewritten(self) -> None:
        """The whole open-vs-close comparison rests on this."""
        with tempfile.TemporaryDirectory() as td:
            upsert("ncaaf", 2025, [_row(spread_open=-10.0, spread_close=-10.0)], root=td)
            # line moves; a later capture must NOT restate the open
            upsert("ncaaf", 2025, [_row(spread_open=-3.5, spread_close=-3.5)], root=td)
            rows = load_ledger("ncaaf", 2025, root=td)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].spread_open, -10.0, "opening line was overwritten")
            self.assertEqual(rows[0].spread_close, -3.5, "closing line did not update")

    def test_opening_line_fills_in_when_initially_absent(self) -> None:
        """Immutability must not mean 'never settable'."""
        with tempfile.TemporaryDirectory() as td:
            upsert("ncaaf", 2025, [_row(spread_close=-7.0)], root=td)
            upsert("ncaaf", 2025, [_row(spread_open=-9.0)], root=td)
            rows = load_ledger("ncaaf", 2025, root=td)
            self.assertEqual(rows[0].spread_open, -9.0)


class IdempotenceTests(unittest.TestCase):
    def test_reapplying_identical_rows_changes_nothing(self) -> None:
        """A weekly autorun must not inflate its own denominator."""
        with tempfile.TemporaryDirectory() as td:
            rows = [_row(spread_close=-7.0, realised_margin=10.0)]
            first = upsert("ncaaf", 2025, rows, root=td)
            second = upsert("ncaaf", 2025, rows, root=td)
            self.assertEqual(first["added"], 1)
            self.assertEqual(second["added"], 0)
            self.assertEqual(second["unchanged"], 1)
            self.assertEqual(len(load_ledger("ncaaf", 2025, root=td)), 1)

    def test_providers_are_separate_rows_not_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            upsert("ncaaf", 2025, [
                _row(provider="DraftKings", spread_close=-7.0),
                _row(provider="Bovada", spread_close=-7.5),
            ], root=td)
            self.assertEqual(len(load_ledger("ncaaf", 2025, root=td)), 2)

    def test_round_trip_preserves_values(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            upsert("ncaaf", 2025, [_row(
                spread_open=-10.0, spread_close=-7.5, model_margin=3.25,
                realised_margin=-4.0, rating_source="cfbd_sp_plus_2026",
            )], root=td)
            r = load_ledger("ncaaf", 2025, root=td)[0]
            self.assertEqual(r.spread_open, -10.0)
            self.assertEqual(r.model_margin, 3.25)
            self.assertEqual(r.realised_margin, -4.0)
            self.assertEqual(r.rating_source, "cfbd_sp_plus_2026")


class ProviderNormalisationTests(unittest.TestCase):
    def test_one_book_two_spellings_folds(self) -> None:
        """Measured: CFBD served DraftKings (714) and Draft Kings (10) in one
        season, and they graded as two books with different verdicts."""
        self.assertEqual(normalise_provider("Draft Kings"), "DraftKings")
        self.assertEqual(normalise_provider("DraftKings"), "DraftKings")
        self.assertEqual(normalise_provider("draftkings"), "DraftKings")

    def test_folding_happens_at_construction(self) -> None:
        self.assertEqual(_row(provider="Draft Kings").provider, "DraftKings")

    def test_aliased_spellings_collapse_to_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            upsert("ncaaf", 2025, [
                _row(provider="DraftKings", spread_close=-7.0),
                _row(provider="Draft Kings", spread_open=-9.0),
            ], root=td)
            rows = load_ledger("ncaaf", 2025, root=td)
            self.assertEqual(len(rows), 1, "same book graded as two")
            self.assertEqual(rows[0].spread_close, -7.0)
            self.assertEqual(rows[0].spread_open, -9.0)

    def test_unknown_provider_is_preserved_not_dropped(self) -> None:
        self.assertEqual(normalise_provider("Some New Book"), "Some New Book")


class MarketSignTests(unittest.TestCase):
    def test_market_margin_is_the_negated_spread(self) -> None:
        """A flipped sign still yields plausible numbers, so assert it directly.

        Home favoured by 7 -> CFBD spread -7 -> implied home margin +7. If the
        model also says +7 and the game lands +7, BOTH errors must be 0.
        """
        rows = [
            _row(game_id=f"g{i}", spread_close=-7.0, model_margin=7.0, realised_margin=7.0)
            for i in range(5)
        ]
        result = evaluate(rows)["vs_close"]
        self.assertAlmostEqual(result["market_mae"], 0.0, places=6)
        self.assertAlmostEqual(result["model_mae"], 0.0, places=6)

    def test_model_better_is_detected(self) -> None:
        """Guard against a comparison that can only ever say MODEL_WORSE."""
        rows = [
            _row(game_id=f"g{i}", spread_close=-0.0, model_margin=14.0, realised_margin=14.0)
            for i in range(30)
        ]
        result = evaluate(rows)["vs_close"]
        self.assertEqual(result["verdict"], "MODEL_BETTER")
        self.assertLess(result["delta_mae"], 0)


class LeakFlaggingTests(unittest.TestCase):
    def test_season_aggregate_ppa_is_flagged(self) -> None:
        self.assertTrue(is_leaked_rating_source("cfbd_ppa_season_2025"))

    def test_sp_plus_is_not_flagged(self) -> None:
        self.assertFalse(is_leaked_rating_source("cfbd_sp_plus_2026[scale=10]"))
        self.assertFalse(is_leaked_rating_source(""))

    def test_warning_names_the_offending_rows(self) -> None:
        rows = [_row(model_margin=1.0, realised_margin=2.0, rating_source="cfbd_ppa_season_2025")]
        warn = leak_warning(rows)
        self.assertIsNotNone(warn)
        self.assertEqual(warn["leaked_rows"], 1)
        self.assertIn("FLATTERED", warn["message"])

    def test_clean_rows_produce_no_warning(self) -> None:
        rows = [_row(model_margin=1.0, realised_margin=2.0, rating_source="cfbd_sp_plus_2026")]
        self.assertIsNone(leak_warning(rows))

    def test_evaluate_segments_by_rating_source(self) -> None:
        """Leaked and clean must never share a verdict line."""
        rows = [
            _row(game_id="g1", spread_close=-3.0, model_margin=1.0, realised_margin=2.0,
                 rating_source="cfbd_ppa_season_2025"),
            _row(game_id="g2", spread_close=-3.0, model_margin=1.0, realised_margin=2.0,
                 rating_source="cfbd_sp_plus_2026"),
        ]
        by_src = evaluate(rows)["vs_close"]["by_rating_source"]
        self.assertIn("cfbd_ppa_season_2025", by_src)
        self.assertIn("cfbd_sp_plus_2026", by_src)


class CoverageTests(unittest.TestCase):
    def test_missing_open_is_counted_not_substituted(self) -> None:
        """Filling a missing open with the close would answer the open question
        with the close's own number."""
        rows = [
            _row(game_id="g1", spread_open=-10.0, spread_close=-7.0),
            _row(game_id="g2", spread_open=None, spread_close=-7.0),
        ]
        cov = coverage(rows)
        self.assertEqual(cov["open_missing"], 1)
        self.assertEqual(cov["with_spread_open"], 1)

    def test_gradable_requires_all_three_of_model_line_result(self) -> None:
        rows = [
            _row(game_id="g1", spread_close=-7.0, model_margin=3.0, realised_margin=1.0),
            _row(game_id="g2", spread_close=-7.0, model_margin=3.0),            # no result
            _row(game_id="g3", spread_close=-7.0, realised_margin=1.0),          # no model
        ]
        self.assertEqual(coverage(rows)["gradable_vs_close"], 1)

    def test_empty_ledger_reports_zero_not_crash(self) -> None:
        self.assertEqual(coverage([])["rows"], 0)


class PathTests(unittest.TestCase):
    def test_path_is_season_scoped_and_sport_scoped(self) -> None:
        p = ledger_path("ncaaf", 2026, root="/tmp/x")
        self.assertIn("ncaaf_source", str(p))
        self.assertTrue(str(p).endswith("pick_ledger_ncaaf_2026.csv"))

    def test_missing_ledger_loads_as_empty_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(load_ledger("ncaaf", 1999, root=td), [])


if __name__ == "__main__":
    unittest.main()
