"""A producer null must never reach the calibration fit — `#624` step 2.

This guard exists because the first run of `fit_mlb_prop_calibration.py` walked
straight into the trap and produced a confident wrong conclusion. Measured
2026-09-01: `hits_runs_rbis_*` was **100% p=0.0 on six dates** (2026-06-14..
06-25) and **0% on all 43 dates from 07-20**, so a chronological 60/20/20 split
put 1,422 of 7,074 HRR observations (20.1%) of literal zeros into the fit set.
The fitter pinned the slope at its clamp floor — the only sane response to a
mass of zeros — and that was read as "HRR carries no usable signal", which was
a statement about a broken window, not about HRR. On clean dates the same prop
fits healthy slopes (0.77–1.14).

Nothing failed while that happened: no exception, no warning, and a plausible
config. The guard turns it into a printed exclusion.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "fit_mlb_prop_calibration_under_test", REPO_ROOT / "scripts" / "fit_mlb_prop_calibration.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MOD = _load()
PROP = "hits_runs_rbis_2plus"
CONTROL = "hits_1plus"


def _report(rows: dict[str, list[tuple[float, int]]]) -> dict:
    """One report shaped like the fitter's real input."""
    backtest = {
        prop: {"scored": [{"p": p, "y": y} for p, y in pairs]}
        for prop, pairs in rows.items()
    }
    return {"games": [{"hitter_props_backtest": backtest}]}


def _write(directory: Path, date: str, rows: dict[str, list[tuple[float, int]]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"sim_vs_actual_{date}.json").write_text(json.dumps(_report(rows)), encoding="utf-8")


class DegenerateDateDetectionTests(unittest.TestCase):
    def test_a_wholly_degenerate_date_is_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-06-14", {PROP: [(0.0, 0), (0.0, 1), (0.0, 0)]})
            self.assertEqual(MOD.degenerate_dates(batch, PROP), ["2026-06-14"])

    def test_a_clean_date_is_not_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-08-22", {PROP: [(0.41, 0), (0.55, 1)]})
            self.assertEqual(MOD.degenerate_dates(batch, PROP), [])

    def test_a_PARTIALLY_zero_date_is_kept(self) -> None:
        """The rule is 100%, deliberately. A partial zero rate is a real if ugly
        distribution, and excluding it would be editing the data rather than
        removing an outage."""
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-08-22", {PROP: [(0.0, 0), (0.44, 1), (0.51, 0)]})
            self.assertEqual(MOD.degenerate_dates(batch, PROP), [])

    def test_detection_is_per_prop_so_a_control_stays_clean(self) -> None:
        """`hits_1plus` had zero zeros on every date, which is exactly what
        separated 'producer outage' from 'the data looks like this'."""
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-06-14", {PROP: [(0.0, 0), (0.0, 1)], CONTROL: [(0.66, 1), (0.71, 0)]})
            self.assertEqual(MOD.degenerate_dates(batch, PROP), ["2026-06-14"])
            self.assertEqual(MOD.degenerate_dates(batch, CONTROL), [])

    def test_the_real_shape_is_reproduced_end_to_end(self) -> None:
        """Six degenerate dates then clean ones, as production actually had."""
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            for date in ("2026-06-14", "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-19", "2026-06-25"):
                _write(batch, date, {PROP: [(0.0, 0)] * 6, CONTROL: [(0.6, 1)] * 6})
            for date in ("2026-07-20", "2026-08-11"):
                _write(batch, date, {PROP: [(0.42, 1), (0.38, 0)], CONTROL: [(0.6, 1), (0.7, 0)]})
            found = MOD.degenerate_dates(batch, PROP)
        self.assertEqual(len(found), 6)
        self.assertEqual(found[0], "2026-06-14")
        self.assertEqual(found[-1], "2026-06-25")


class ExclusionIsAnnouncedTests(unittest.TestCase):
    """A silent exclusion is how a fit starts describing a population nobody
    chose — the same failure mode as the silent inclusion it replaces."""

    def test_the_dropped_dates_are_printed_and_returned(self) -> None:
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-06-14", {PROP: [(0.0, 0), (0.0, 1)]})
            _write(batch, "2026-08-22", {PROP: [(0.4, 1), (0.5, 0)]})
            from unittest.mock import patch
            with patch("builtins.print") as printer:
                found = MOD.report_degenerate(batch, [PROP])
        self.assertEqual(found, {PROP: ["2026-06-14"]})
        printed = " ".join(str(call.args[0]) for call in printer.call_args_list if call.args)
        self.assertIn("DEGENERATE", printed)
        self.assertIn("EXCLUDED", printed)
        self.assertIn(PROP, printed)

    def test_a_clean_batch_reports_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            batch = Path(tmp)
            _write(batch, "2026-08-22", {PROP: [(0.4, 1), (0.5, 0)]})
            self.assertEqual(MOD.report_degenerate(batch, [PROP]), {})


class GuardIsWiredIntoTheFitTests(unittest.TestCase):
    """Presence is not reachability: a detector the fit does not consult is a
    detector that changes nothing."""

    def test_the_fit_uses_the_cleaned_directory(self) -> None:
        source = (REPO_ROOT / "scripts" / "fit_mlb_prop_calibration.py").read_text(encoding="utf-8-sig")
        self.assertIn("report_degenerate(", source)
        self.assertIn('"--batch-dir", str(fit_dir)', source)
        self.assertIn("fit_clean", source)

    def test_the_exclusions_reach_the_report(self) -> None:
        source = (REPO_ROOT / "scripts" / "fit_mlb_prop_calibration.py").read_text(encoding="utf-8-sig")
        self.assertIn("degenerate_dates_excluded", source)


if __name__ == "__main__":
    unittest.main()
