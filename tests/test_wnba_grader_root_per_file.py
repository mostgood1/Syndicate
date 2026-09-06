"""`#309`. The WNBA grader read ONE root, chosen before any filename was known.

MEASURED on production 2026-08-09, web and refresh-worker both live on
`27a7e9df`:

    processed_root  -> /opt/render/project/data/wnba_source/source_artifacts/data/processed
    the refresh pipeline writes
                    -> /opt/render/project/data/wnba_source/data/processed

    /api/ops/wnba/artifact-counts?date=2026-08-08     root1    root2
      game_cards_2026-08-08.csv                       False    True
      props_recommendations_2026-08-08.csv            False    True

So `_score_market_{games,props}_day` read an unrelated directory, every WNBA
date scored `{"available": False}`, and settlement reported
`graded_rows_available wnba:2026-08-05 = 0` -- indistinguishable from an
unplayed slate.

THE PART THAT MATTERS BEYOND WNBA, and the reason the previous fix did not
work: `17d4f203` changed `current_odds_root_for_sport("wnba")` to return the
"first root that HAS files" via `any(candidate.iterdir())`. That commit is an
ancestor of the live `27a7e9df` -- it is DEPLOYED -- and it is inert, because
root1 holds 427 files. **"Does this directory contain anything" is not "does it
contain the file you asked for."**

`wnba/sources.py::_strict_artifact_path` already resolved per requested file and
is the model these tests pin.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.live_lens_local import _artifact_path


class ArtifactPathPerFileResolutionTests(unittest.TestCase):
    def _production_shape(self, tmp: str) -> tuple[Path, Path]:
        """root1 non-empty but WITHOUT the requested date; root2 has the data."""
        root1 = Path(tmp) / "wnba_source" / "source_artifacts" / "data" / "processed"
        root2 = Path(tmp) / "wnba_source" / "data" / "processed"
        root1.mkdir(parents=True)
        root2.mkdir(parents=True)
        # root1 is populated with STALE artifacts for a different date -- this is
        # what makes `any(iterdir())` return True and the old fix a no-op.
        for name in ("game_cards_2026-07-01.csv", "recommendations_2026-07-01.csv"):
            (root1 / name).write_text("stale\n", encoding="utf-8")
        return root1, root2

    def test_the_populated_root_wins_per_file_not_per_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root1, root2 = self._production_shape(tmp)
            (root2 / "recon_games_2026-08-08.csv").write_text("real\n", encoding="utf-8")

            resolved = _artifact_path([root1, root2], "recon_games_2026-08-08.csv")

            self.assertEqual(resolved.parent, root2)
            self.assertTrue(resolved.is_file())

    def test_any_iterdir_would_have_picked_the_wrong_root(self) -> None:
        """The refuted heuristic, pinned so it is not reintroduced."""
        with TemporaryDirectory() as tmp:
            root1, root2 = self._production_shape(tmp)
            (root2 / "recon_props_2026-08-08.csv").write_text("real\n", encoding="utf-8")

            # `17d4f203`'s test, reproduced: root1 "has files", so it wins...
            self.assertTrue(any(root1.iterdir()))
            # ...but it does not have the file anyone asked for.
            self.assertFalse((root1 / "recon_props_2026-08-08.csv").exists())

            resolved = _artifact_path([root1, root2], "recon_props_2026-08-08.csv")
            self.assertEqual(resolved.parent, root2)

    def test_the_preferred_root_still_wins_when_it_has_the_file(self) -> None:
        """Order is still preference order -- this is not "prefer the last root"."""
        with TemporaryDirectory() as tmp:
            root1, root2 = self._production_shape(tmp)
            (root1 / "game_cards_2026-08-08.csv").write_text("preferred\n", encoding="utf-8")
            (root2 / "game_cards_2026-08-08.csv").write_text("fallback\n", encoding="utf-8")

            resolved = _artifact_path([root1, root2], "game_cards_2026-08-08.csv")

            self.assertEqual(resolved.parent, root1)
            self.assertEqual(resolved.read_text(encoding="utf-8"), "preferred\n")

    def test_missing_everywhere_reports_the_first_candidate_unchanged(self) -> None:
        """A genuinely absent artifact must name the same path it always did, so
        this fix cannot turn "no data" into a new and different-looking failure."""
        with TemporaryDirectory() as tmp:
            root1, root2 = self._production_shape(tmp)

            resolved = _artifact_path([root1, root2], "recon_games_1999-01-01.csv")

            self.assertEqual(resolved.parent, root1)
            self.assertFalse(resolved.exists())

    def test_a_single_path_is_unchanged_behaviour(self) -> None:
        """nba and nhl pass one root and must be byte-identical to before."""
        with TemporaryDirectory() as tmp:
            root1, _root2 = self._production_shape(tmp)

            self.assertEqual(
                _artifact_path(root1, "anything_2026-08-08.csv"),
                root1 / "anything_2026-08-08.csv",
            )


class WnbaProcessedRootsTests(unittest.TestCase):
    """THE ROOT SET IS PINNED HERE, and it was not.

    `processed_root()` and `processed_roots()[0]` are NOT the same rule.
    `processed_roots()` is every candidate in preference order;
    `processed_root()` goes through `current_odds_root_for_sport("wnba")`,
    which returns the first candidate that IS A DIRECTORY AND HAS FILES
    (`odds_control_plane.py:66-75`) and only falls back to `candidates[0]` when
    NOTHING is populated. The two coincide exactly while candidate[0] happens
    to have files in it -- which, unpinned, is a fact about the machine running
    the tests, not about the code.

    MEASURED 2026-09-04: this passed alone and failed a full-suite run with
    `processed_root()` returning the REPO mirror while `roots[0]` was a pytest
    tmp dir. By then something had pointed a root env var at a scratch
    directory; candidate[0] was empty, so `processed_root()` skipped it and
    returned a populated later candidate, while `roots[0]` stayed the empty
    first one. Reproduced with either `SYNDICATE_DATA_ROOT` or
    `SYNDICATE_WNBA_SOURCE_ROOT` pointed at an empty directory.

    Pinning the root AND populating it restores what the assertion was written
    to check -- that `processed_root()` still returns the first candidate --
    and makes it independent of what is on disk anywhere else.
    """

    def test_processed_roots_returns_every_candidate_in_preference_order(self) -> None:
        from syndicate.features.shared.source_roots import clear_source_root_caches
        from syndicate.features.wnba import sources

        with TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"SYNDICATE_WNBA_SOURCE_ROOT": str(Path(tmp) / "wnba_source")},
                clear=False,
            ):
                clear_source_root_caches()
                try:
                    roots = sources.processed_roots()

                    self.assertGreaterEqual(len(roots), 1)
                    for root in roots:
                        self.assertEqual(root.name, "processed")
                        self.assertEqual(root.parent.name, "data")

                    # POPULATE roots[0] ITSELF. Pinning the env var is not
                    # enough: `preferred_artifact_roots` ALWAYS appends the repo
                    # mirror after the env roots, and on a dev checkout that
                    # mirror is the populated one (427 files), so
                    # `processed_root()` walks straight past the empty scratch
                    # candidates and answers with the repo. Giving roots[0] a
                    # file makes its "first candidate that HAS FILES" rule stop
                    # where this assertion expects.
                    roots[0].mkdir(parents=True, exist_ok=True)
                    (roots[0] / "game_cards_2026-08-08.csv").write_text("", encoding="utf-8")

                    # `processed_root()` is deliberately LEFT ALONE: ~20 call
                    # sites in wnba/cards.py depend on its exact behaviour and
                    # several carry their own workarounds for this defect. It
                    # must still be the first candidate.
                    self.assertEqual(sources.processed_root(), roots[0])
                finally:
                    clear_source_root_caches()

    def test_processed_root_skips_an_empty_candidate_for_a_populated_later_one(self) -> None:
        """The two accessors legitimately DISAGREE, and the old comment did not
        say so. `processed_roots()` is every candidate in preference order;
        `processed_root()` returns the first that HAS FILES
        (`odds_control_plane.py:66-75`). Leaving roots[0] empty and populating
        roots[1] is the case the unpinned test was silently hitting in a
        full-suite run -- it just reached the repo mirror instead, which is why
        it looked like pollution rather than an unpinned fixture."""
        from syndicate.features.shared.source_roots import clear_source_root_caches
        from syndicate.features.wnba import sources

        with TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"SYNDICATE_WNBA_SOURCE_ROOT": str(Path(tmp) / "wnba_source")},
                clear=False,
            ):
                clear_source_root_caches()
                try:
                    roots = sources.processed_roots()
                    self.assertGreaterEqual(len(roots), 2)

                    roots[0].mkdir(parents=True, exist_ok=True)  # left EMPTY
                    roots[1].mkdir(parents=True, exist_ok=True)
                    (roots[1] / "game_cards_2026-08-08.csv").write_text("", encoding="utf-8")

                    self.assertEqual(sources.processed_root(), roots[1])
                    self.assertNotEqual(sources.processed_root(), roots[0])
                finally:
                    clear_source_root_caches()


if __name__ == "__main__":
    unittest.main()
