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

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
    def test_processed_roots_returns_every_candidate_in_preference_order(self) -> None:
        from syndicate.features.wnba import sources

        roots = sources.processed_roots()

        self.assertGreaterEqual(len(roots), 1)
        for root in roots:
            self.assertEqual(root.name, "processed")
            self.assertEqual(root.parent.name, "data")
        # `processed_root()` is deliberately LEFT ALONE: ~20 call sites in
        # wnba/cards.py depend on its exact behaviour and several carry their
        # own workarounds for this defect. It must still be the first candidate.
        self.assertEqual(sources.processed_root(), roots[0])


if __name__ == "__main__":
    unittest.main()
