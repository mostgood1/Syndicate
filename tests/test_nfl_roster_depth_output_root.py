"""`nfl-roster-depth-autorun` lane — the `#389` write-side bug, applied to
the roster and depth-chart snapshot builders.

Mirrors `test_nfl_projection_output_root.py`'s shape and reasoning exactly:
`default_nfl_source_root()` picks a root by probing for an UNRELATED file
(`upcoming_recs_*.csv`), which is correct for reads and wrong for writes —
a snapshot built on refresh-worker with the old code would land on the
ephemeral repo checkout (which HAS that unrelated file) instead of the
mounted disk (which does not), and be discarded on the next deploy with
nothing ever having read it.

THE FALSIFICATION CASE (`OldPathWouldHaveMissed`): reproduces the exact
scenario and shows the OLD `default_nfl_source_root()`-based expression
picks a DIFFERENT root than the fixed `nfl_artifact_output_root()`-based
one, so the bug is demonstrated, not assumed by analogy to the pbp/
projections precedent alone.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from syndicate.features.football.ingestion.depth_chart_snapshot_builder import depth_chart_snapshot_output_path
from syndicate.features.football.ingestion.roster_snapshot_builder import roster_snapshot_output_path
from syndicate.features.nfl import sources


class RosterOutputPathUsesTheConfiguredRoot(unittest.TestCase):
    def test_env_var_wins_and_is_not_probed(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/mnt/disk/nfl_source"}):
            path = roster_snapshot_output_path(season=2026)
        expected_root = Path("/mnt/disk/nfl_source").expanduser().resolve()
        self.assertEqual(path.parent, expected_root / "source_artifacts" / "data" / "processed" / "rosters")

    def test_does_not_consult_the_filesystem(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/nonexistent/nfl_source"}):
            path = roster_snapshot_output_path(season=2026)
        self.assertEqual(
            path.parent,
            Path("/nonexistent/nfl_source").expanduser().resolve() / "source_artifacts" / "data" / "processed" / "rosters",
        )


class DepthOutputPathUsesTheConfiguredRoot(unittest.TestCase):
    def test_env_var_wins_and_is_not_probed(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/mnt/disk/nfl_source"}):
            path = depth_chart_snapshot_output_path(season=2026)
        expected_root = Path("/mnt/disk/nfl_source").expanduser().resolve()
        self.assertEqual(path.parent, expected_root / "source_artifacts" / "data" / "processed" / "depth")

    def test_does_not_consult_the_filesystem(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/nonexistent/nfl_source"}):
            path = depth_chart_snapshot_output_path(season=2026)
        self.assertEqual(
            path.parent,
            Path("/nonexistent/nfl_source").expanduser().resolve() / "source_artifacts" / "data" / "processed" / "depth",
        )


class OldPathWouldHaveMissed(unittest.TestCase):
    """THE FALSIFICATION TEST. Reproduces the exact production shape `#389`
    measured for SmartSim2 projections, one layer down for these two
    builders: a root chosen by probing for `upcoming_recs_*.csv` disagrees
    with the actually-configured mounted-disk root."""

    def test_probing_root_and_configured_root_disagree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = base / "checkout" / "nfl_source"
            checkout.mkdir(parents=True)
            (checkout / "upcoming_recs_2025_wk17.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            mounted_disk = base / "mounted" / "nfl_source"
            mounted_disk.mkdir(parents=True)

            with patch.object(sources, "_source_roots", return_value=[checkout, mounted_disk]), \
                 patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": str(mounted_disk)}):
                # The trap is real in this fixture: the probe picks the checkout.
                self.assertEqual(sources.default_nfl_source_root(), checkout)
                # Pre-fix expression (what both builders used to compute):
                old_roster_path = sources.default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "rosters" / "roster_2026_snapshot.csv"
                old_depth_path = sources.default_nfl_source_root() / "source_artifacts" / "data" / "processed" / "depth" / "depth_2026_snapshot.csv"
                # Fixed functions:
                new_roster_path = roster_snapshot_output_path(season=2026)
                new_depth_path = depth_chart_snapshot_output_path(season=2026)

            # `old_*_path` goes through the mocked `_source_roots()` list
            # verbatim (no resolve), while `new_*_path` goes through
            # `nfl_artifact_output_root()`'s `.expanduser().resolve()` -- so
            # the two sides of each comparison are built to match each
            # function's own actual resolution behaviour, not forced equal.
            # (A raw tempdir path can differ from its resolved form, e.g.
            # Windows 8.3 short names, even naming the same real directory.)
            expected_old_roster = checkout / "source_artifacts" / "data" / "processed" / "rosters" / "roster_2026_snapshot.csv"
            expected_new_roster = mounted_disk.resolve() / "source_artifacts" / "data" / "processed" / "rosters" / "roster_2026_snapshot.csv"
            expected_old_depth = checkout / "source_artifacts" / "data" / "processed" / "depth" / "depth_2026_snapshot.csv"
            expected_new_depth = mounted_disk.resolve() / "source_artifacts" / "data" / "processed" / "depth" / "depth_2026_snapshot.csv"

            self.assertEqual(old_roster_path, expected_old_roster)
            self.assertEqual(new_roster_path, expected_new_roster)
            self.assertNotEqual(old_roster_path, new_roster_path, "the bug must reproduce: old and new must disagree")
            self.assertEqual(old_depth_path, expected_old_depth)
            self.assertEqual(new_depth_path, expected_new_depth)
            self.assertNotEqual(old_depth_path, new_depth_path, "the bug must reproduce: old and new must disagree")


class DepthChartReadPathResolution(unittest.TestCase):
    """`nfl_depth_chart_snapshot_path` (the READ-side twin) -- mirrors
    `test_nfl_injuries_path_root.py`'s shape."""

    def test_found_on_a_later_root_when_the_first_only_has_upcoming_recs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = base / "checkout" / "nfl_source"
            checkout.mkdir(parents=True)
            (checkout / "upcoming_recs_2025_wk17.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            disk = base / "disk" / "nfl_source"
            depth_dir = disk / "source_artifacts" / "data" / "processed" / "depth"
            depth_dir.mkdir(parents=True)
            (depth_dir / "depth_2026_snapshot.csv").write_text("team,player_id\n", encoding="utf-8")

            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                self.assertEqual(sources.default_nfl_source_root(), checkout)
                resolved = sources.nfl_depth_chart_snapshot_path(2026)
            self.assertEqual(resolved, depth_dir / "depth_2026_snapshot.csv")
            self.assertTrue(resolved.is_file())

    def test_missing_everywhere_still_names_a_concrete_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            only = base / "only" / "nfl_source"
            only.mkdir(parents=True)
            (only / "upcoming_recs_2025_wk17.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            with patch.object(sources, "_source_roots", return_value=[only]):
                resolved = sources.nfl_depth_chart_snapshot_path(2026)
            self.assertEqual(resolved.name, "depth_2026_snapshot.csv")
            self.assertFalse(resolved.is_file())


if __name__ == "__main__":
    unittest.main()
