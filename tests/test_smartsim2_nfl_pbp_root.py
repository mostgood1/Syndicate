"""`#441` — the pbp READ path must not be decided by an unrelated artifact.

The production failure these pin, measured 2026-08-16 on refresh-worker:

    DATA_ROOT  : /opt/render/project/src/data/nfl_source        <- the CHECKOUT
    looked for : .../src/data/nfl_source/tracking/nflverse/pbp/pbp_2026.csv
    DegenerateProjectionRun: NO PLAY-BY-PLAY DATA

`_first_existing_root` picks a root by probing for `upcoming_recs_*.csv`. The
repo checkout ships 5 of those (git-tracked) and does NOT ship the pbp
(`.gitignore:96` excludes `data/nfl_source/tracking/`). So the selector chose the
checkout, the pbp loaded zero plays, and the guard refused to write -- correctly
-- for 2.36 days at ~107 relaunches/day.

THE SHAPE THESE TESTS ENCODE, and it is the reusable part: a root chosen by
probing for file A is not a root that contains file B. Where A is git-tracked and
B is gitignored, the two are guaranteed to disagree.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from syndicate.features.nfl import sources


def _make_root(base: Path, name: str, *, with_upcoming_recs: bool, with_pbp_season: int | None) -> Path:
    root = base / name / "nfl_source"
    root.mkdir(parents=True, exist_ok=True)
    if with_upcoming_recs:
        (root / "upcoming_recs_2025_wk17.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    if with_pbp_season is not None:
        pbp_dir = root / "tracking" / "nflverse" / "pbp"
        pbp_dir.mkdir(parents=True, exist_ok=True)
        (pbp_dir / f"pbp_{with_pbp_season}.csv").write_text("season_type,play_type\n", encoding="utf-8")
    return root


class NflPbpPathResolution(unittest.TestCase):
    def test_pbp_found_on_a_later_root_when_the_first_only_has_upcoming_recs(self):
        """THE PRODUCTION CASE, reproduced exactly.

        Candidate 1 = the checkout: has `upcoming_recs_*.csv`, no pbp.
        Candidate 2 = the mounted disk: has the pbp, no `upcoming_recs`.

        `default_nfl_source_root()` picks candidate 1; the pbp is on candidate 2.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = _make_root(base, "src_data", with_upcoming_recs=True, with_pbp_season=None)
            disk = _make_root(base, "data", with_upcoming_recs=False, with_pbp_season=2026)
            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                # The selector really does pick the wrong one -- assert that, so
                # the test fails loudly if the underlying behaviour ever changes
                # and this test starts passing for the wrong reason.
                self.assertEqual(sources.default_nfl_source_root(), checkout)
                resolved = sources.nfl_pbp_path(2026)
            self.assertEqual(resolved, disk / "tracking" / "nflverse" / "pbp" / "pbp_2026.csv")
            self.assertTrue(resolved.is_file())

    def test_prefers_the_earlier_root_when_both_have_the_pbp(self):
        """Preference order still wins when the file genuinely exists on both."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = _make_root(base, "first", with_upcoming_recs=False, with_pbp_season=2026)
            second = _make_root(base, "second", with_upcoming_recs=True, with_pbp_season=2026)
            with patch.object(sources, "_source_roots", return_value=[first, second]):
                resolved = sources.nfl_pbp_path(2026)
            self.assertEqual(resolved, first / "tracking" / "nflverse" / "pbp" / "pbp_2026.csv")

    def test_missing_everywhere_still_names_a_concrete_path(self):
        """A miss must degrade to a NAMED path, not to None or an exception.

        The degenerate-run guard prints this path, and that message is the whole
        diagnostic -- it is what told us DATA_ROOT was the checkout. Returning
        None here would turn a precise error into 'not found'.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            only = _make_root(base, "only", with_upcoming_recs=True, with_pbp_season=None)
            with patch.object(sources, "_source_roots", return_value=[only]):
                resolved = sources.nfl_pbp_path(2026)
            self.assertEqual(resolved.name, "pbp_2026.csv")
            self.assertFalse(resolved.is_file())

    def test_per_season_resolution_is_independent(self):
        """Prior-season fallback must resolve on its own merits.

        `assert_ratings_data_available` accepts current OR prior plays, so a root
        holding only 2025 must be found when 2026 is asked for separately --
        otherwise a preseason run (which legitimately has no current-season pbp)
        would resolve both seasons to the same wrong root.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            checkout = _make_root(base, "src_data", with_upcoming_recs=True, with_pbp_season=None)
            disk = _make_root(base, "data", with_upcoming_recs=False, with_pbp_season=2025)
            with patch.object(sources, "_source_roots", return_value=[checkout, disk]):
                self.assertTrue(sources.nfl_pbp_path(2025).is_file())
                self.assertFalse(sources.nfl_pbp_path(2026).is_file())


class GeneratorUsesTheResolver(unittest.TestCase):
    def test_generator_pbp_path_delegates_to_the_resolver(self):
        """The generator must not rebuild the path from DATA_ROOT.

        DATA_ROOT is bound at import time from `default_nfl_source_root()`, so a
        regression here is invisible at runtime until a slate goes stale for
        days -- exactly how `#441` presented.
        """
        import scripts.generate_smartsim2_nfl_projections as gen

        sentinel = Path("/sentinel/pbp_2026.csv")
        with patch.object(gen, "nfl_pbp_path", return_value=sentinel) as resolver:
            self.assertEqual(gen._pbp_path(2026), sentinel)
        resolver.assert_called_once_with(2026)

    def test_preseason_generator_shares_the_fixed_loader(self):
        """The preseason generator imports `load_pbp_plays` from the regular one,
        so it inherits this fix rather than needing its own. Pinned because a
        future split would silently reintroduce `#441` for preseason only."""
        import scripts.generate_smartsim2_nfl_preseason_projections as pre
        import scripts.generate_smartsim2_nfl_projections as gen

        self.assertIs(pre.load_pbp_plays, gen.load_pbp_plays)


if __name__ == "__main__":
    unittest.main()
