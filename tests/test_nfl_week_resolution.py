"""Regression tests for the NFL/NCAAF week-resolution fixed point.

The bug: both odds-refresh resolvers read current_week.json for the week and
then wrote the same value straight back (_ensure_current_week_file), so with
no explicit --week the refresh targeted the same week forever -- and the
Layer 2 NFL context preferred that same tracked file, freezing the board on
week 1 for the whole season. The real schedule (first week with an unplayed
game, nfl_target_week/ncaaf_target_week) must outrank the tracked file.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.refresh_nfl_oddsapi import _resolve_context
from scripts.refresh_odds_sources import _infer_nfl_context
from syndicate.features.ncaaf import sources as ncaaf_sources
from syndicate.features.nfl import sources as nfl_sources


class _TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write_current_week(self, root: Path, *, season: int, week: int) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "current_week.json").write_text(
            json.dumps({"season": season, "week": week}), encoding="utf-8"
        )


class ResolveContextTests(_TempDirTestCase):
    """scripts/refresh_nfl_oddsapi.py::_resolve_context"""

    def test_schedule_target_week_outranks_tracked_file(self) -> None:
        self._write_current_week(self.root, season=2026, week=1)
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=7):
            season, week = _resolve_context(source_data_root=self.root, season=None, week=None)
        self.assertEqual((season, week), (2026, 7))

    def test_explicit_week_arg_still_wins(self) -> None:
        self._write_current_week(self.root, season=2026, week=1)
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=7):
            season, week = _resolve_context(source_data_root=self.root, season=2026, week=3)
        self.assertEqual((season, week), (2026, 3))

    def test_tracked_file_is_fallback_when_schedule_unavailable(self) -> None:
        self._write_current_week(self.root, season=2026, week=5)
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=None):
            season, week = _resolve_context(source_data_root=self.root, season=None, week=None)
        self.assertEqual((season, week), (2026, 5))


class InferNflContextTests(_TempDirTestCase):
    """scripts/refresh_odds_sources.py::_infer_nfl_context"""

    def test_schedule_target_week_outranks_tracked_file(self) -> None:
        self._write_current_week(self.root, season=2026, week=1)
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=9):
            season, week = _infer_nfl_context(None, self.root, None, None)
        self.assertEqual((season, week), (2026, 9))

    def test_explicit_args_short_circuit(self) -> None:
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=9):
            season, week = _infer_nfl_context(None, self.root, 2026, 4)
        self.assertEqual((season, week), (2026, 4))

    def test_tracked_file_is_fallback_when_schedule_unavailable(self) -> None:
        self._write_current_week(self.root, season=2026, week=6)
        with patch("syndicate.features.nfl.sources.nfl_target_week", return_value=None):
            season, week = _infer_nfl_context(None, self.root, None, None)
        self.assertEqual((season, week), (2026, 6))


class NflDefaultWeekTests(unittest.TestCase):
    """syndicate/features/nfl/sources.py::default_week"""

    def test_target_week_wins_even_with_no_projection_weeks(self) -> None:
        # Previously `if not weeks: return 1` early-returned before the
        # target week was ever consulted.
        with patch.object(nfl_sources, "available_weeks", return_value=[]), patch.object(
            nfl_sources, "nfl_target_week", return_value=8
        ):
            self.assertEqual(nfl_sources.default_week(2026), 8)

    def test_target_week_wins_when_present_in_weeks(self) -> None:
        with patch.object(nfl_sources, "available_weeks", return_value=list(range(1, 19))), patch.object(
            nfl_sources, "nfl_target_week", return_value=3
        ):
            self.assertEqual(nfl_sources.default_week(2026), 3)

    def test_last_available_when_target_unknown(self) -> None:
        with patch.object(nfl_sources, "available_weeks", return_value=[1, 2, 3]), patch.object(
            nfl_sources, "nfl_target_week", return_value=None
        ):
            self.assertEqual(nfl_sources.default_week(2026), 3)

    def test_bare_fallback_when_nothing_available(self) -> None:
        with patch.object(nfl_sources, "available_weeks", return_value=[]), patch.object(
            nfl_sources, "nfl_target_week", return_value=None
        ):
            self.assertEqual(nfl_sources.default_week(2026), 1)


class NcaafDefaultWeekTests(unittest.TestCase):
    """syndicate/features/ncaaf/sources.py::default_week -- the empty
    recommendations_summary index must no longer pin the week to 1."""

    def test_target_week_wins_with_empty_summary_index(self) -> None:
        with patch.object(ncaaf_sources, "available_weeks", return_value=[]), patch.object(
            ncaaf_sources, "ncaaf_target_week", return_value=2
        ), patch.object(ncaaf_sources, "default_season", return_value=2026):
            self.assertEqual(ncaaf_sources.default_week(), 2)

    def test_target_week_wins_when_present_in_weeks(self) -> None:
        with patch.object(ncaaf_sources, "available_weeks", return_value=[1, 2, 3, 4]), patch.object(
            ncaaf_sources, "ncaaf_target_week", return_value=3
        ), patch.object(ncaaf_sources, "default_season", return_value=2026):
            self.assertEqual(ncaaf_sources.default_week(), 3)

    def test_last_available_when_target_unknown(self) -> None:
        with patch.object(ncaaf_sources, "available_weeks", return_value=[1, 2]), patch.object(
            ncaaf_sources, "ncaaf_target_week", return_value=None
        ), patch.object(ncaaf_sources, "default_season", return_value=2026):
            self.assertEqual(ncaaf_sources.default_week(), 2)

    def test_bare_fallback_when_nothing_available(self) -> None:
        with patch.object(ncaaf_sources, "available_weeks", return_value=[]), patch.object(
            ncaaf_sources, "ncaaf_target_week", return_value=None
        ), patch.object(ncaaf_sources, "default_season", return_value=2026):
            self.assertEqual(ncaaf_sources.default_week(), 1)


if __name__ == "__main__":
    unittest.main()
