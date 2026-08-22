"""The backfill's safety properties, pinned.

A backfill applies whatever it gets across every historical date at once, so its
failure mode is not "did nothing" — it is "settled months of positions wrongly,
in bulk". These tests exist for the refusals, not the happy path.

The one that matters most is `PreviewNeverTouchesTheRealLedger`: without
`--commit`, the real `data/prediction_ledger.json` must be byte-identical after
a run. `reconcile_prediction_results_for_date` has no `dry_run` and writes, so
the preview redirects it at a throwaway copy — and a redirect that silently
failed would write to production while printing "PREVIEW".
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import backfill_portfolio_settlement as backfill


class DateSelection(unittest.TestCase):
    def test_range_is_inclusive_and_oldest_first(self) -> None:
        """Oldest-first so a partial run leaves a contiguous settled prefix."""
        self.assertEqual(
            backfill._date_range("2026-08-19", "2026-08-22"),
            ["2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22"],
        )

    def test_a_reversed_range_is_refused_not_silently_empty(self) -> None:
        with self.assertRaises(SystemExit):
            backfill._date_range("2026-08-22", "2026-08-19")

    def test_a_malformed_date_raises_rather_than_skewing_the_window(self) -> None:
        with self.assertRaises(ValueError):
            backfill._iso("not-a-date")

    def test_a_single_day_range_is_one_date(self) -> None:
        self.assertEqual(backfill._date_range("2026-08-22", "2026-08-22"), ["2026-08-22"])


class PreviewNeverTouchesTheRealLedger(unittest.TestCase):
    def test_the_preview_copy_is_not_the_real_path(self) -> None:
        copy = backfill._preview_ledger_copy()
        try:
            from syndicate.features.prediction_ledger import _default_ledger_path

            self.assertNotEqual(copy.resolve(), _default_ledger_path().resolve())
            self.assertTrue(copy.exists(), "the preview target must exist so writes land somewhere real")
        finally:
            copy.unlink(missing_ok=True)

    def test_a_preview_run_leaves_the_real_ledger_byte_identical(self) -> None:
        """The whole safety claim, asserted end to end."""
        from syndicate.features.prediction_ledger import _default_ledger_path, record_prediction

        record_prediction(sport="mlb", market="moneyline", selection="NYY", stake=10.0, odds=-110)
        real = _default_ledger_path()
        before = real.read_bytes()

        seen: list[Path | None] = []

        def _fake_reconcile(date_value, *, ledger_path=None, result_roots=None):
            seen.append(ledger_path)
            # Write through the path we were handed, exactly as the real one does.
            if ledger_path is not None:
                Path(ledger_path).write_text(json.dumps({"predictions": [], "results": []}), encoding="utf-8")
            return {"summary": {"matched": 0}}

        with patch(
            "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date",
            _fake_reconcile,
        ):
            backfill.main(["--from", "2026-08-21", "--to", "2026-08-21", "--mode", "local",
                           "--result-root", "/tmp/nonexistent-pulled-root"])

        self.assertEqual(real.read_bytes(), before, "a preview run wrote to the REAL ledger")
        self.assertTrue(seen, "reconciliation was never invoked, so this proved nothing")
        for handed in seen:
            self.assertIsNotNone(handed, "preview must hand reconciliation a redirected path, not None")
            self.assertNotEqual(Path(handed).resolve(), real.resolve())

    def test_commit_uses_the_real_ledger_path(self) -> None:
        """`off != on`: the redirect must be absent when --commit is given."""
        seen: list[Path | None] = []

        def _fake_reconcile(date_value, *, ledger_path=None, result_roots=None):
            seen.append(ledger_path)
            return {"summary": {"matched": 0}}

        with patch(
            "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date",
            _fake_reconcile,
        ):
            backfill.main(["--from", "2026-08-21", "--to", "2026-08-21", "--mode", "local",
                           "--result-root", "/tmp/nonexistent-pulled-root", "--commit"])

        self.assertEqual(seen, [None], "--commit must let the ledger resolve to its real default")


class Bounding(unittest.TestCase):
    def test_max_dates_caps_a_first_run(self) -> None:
        calls: list[str] = []

        def _fake_reconcile(date_value, *, ledger_path=None, result_roots=None):
            calls.append(date_value)
            return {"summary": {}}

        with patch(
            "syndicate.features.prediction_reconciliation.reconcile_prediction_results_for_date",
            _fake_reconcile,
        ):
            backfill.main(["--from", "2026-08-01", "--to", "2026-08-31", "--mode", "local",
                           "--result-root", "/tmp/nonexistent-pulled-root", "--max-dates", "3"])

        self.assertEqual(len(calls), 3)
        self.assertEqual(calls, ["2026-08-01", "2026-08-02", "2026-08-03"])

    def test_local_mode_demands_an_explicit_result_root(self) -> None:
        """Defaulting to the repo's data/ would reconcile against a lossy mirror."""
        with self.assertRaises(SystemExit):
            backfill.main(["--from", "2026-08-21", "--to", "2026-08-21", "--mode", "local"])

    def test_no_date_selection_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            backfill.main([])


class DocumentsWhatItCannotDo(unittest.TestCase):
    def test_the_parlay_limitation_is_stated_in_local_mode(self) -> None:
        """A backfill that silently skips parlays reads as a backfill that ran."""
        # Case-insensitive: the assertion is that the limitation is DOCUMENTED,
        # not that it is phrased in one exact way. Pinning the casing made this
        # fail on a docstring that says it perfectly well.
        self.assertIn("cannot settle parlays", (backfill.__doc__ or "").lower())
        import inspect

        src = inspect.getsource(backfill.main)
        self.assertIn("parlays need the bridge", src)

    def test_the_unreachable_artifacts_are_named(self) -> None:
        """`evaluation_ledger_chunks` cannot be pulled; the docstring must say so
        rather than let someone plan a local backfill around it."""
        doc = backfill.__doc__ or ""
        self.assertIn("NOT REACHABLE", doc)
        self.assertIn("evaluation_ledger_chunks", doc)


if __name__ == "__main__":
    unittest.main()
