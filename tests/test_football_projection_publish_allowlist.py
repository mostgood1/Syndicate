"""The NFL/NCAAF season-projection artifacts must be publishable to web.

WHY THIS EXISTS. Both generators have called `publish_hot_artifact` on their
output since 2026-08-19 and both calls were no-ops for 13 days, because neither
path was in `HOT_ARTIFACT_PATTERNS`. Measured on refresh-worker 2026-09-01:

    projections_written=51
    artifact_path=/opt/render/project/data/ncaaf_source/data/smartsim2_projections_2026_wk1.csv
    artifact_published=False

while `/ncaaf/api/cards` served values byte-identical to the CSV committed on
2026-08-19. The worker regenerated the model output daily and the board could
only move when someone COMMITTED a CSV and rode a web deploy.

`generate_smartsim2_nfl_projections.py` states in its own comment that "the
allowlist pattern covers both". It did not exist. That is what makes this worth
a test rather than a one-line fix: the publish side was written, reviewed and
believed, and nothing anywhere asserted the two halves met.

SO THE TEST DERIVES THE PATH FROM THE WRITER, NEVER FROM A LITERAL. A test that
hardcoded `"ncaaf_source/data/smartsim2_projections_2026_wk1.csv"` would keep
passing after a writer moved its output, which is the `#389` defect exactly --
the guard and the writer diverging while both look correct in isolation.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared.artifact_publisher import relative_to_data_root


class FootballProjectionPublishAllowlistTest(unittest.TestCase):
    def _env(self, root: str) -> dict[str, str]:
        """The production shape: one data root, per-sport roots inside it."""
        return {
            "SYNDICATE_DATA_ROOT": root,
            "SYNDICATE_NFL_SOURCE_ROOT": str(Path(root) / "nfl_source"),
            "SYNDICATE_NCAAF_SOURCE_ROOT": str(Path(root) / "ncaaf_source"),
        }

    def test_ncaaf_projection_artifact_is_publishable(self) -> None:
        from syndicate.features.ncaaf.smartsim2_projection import projection_artifact_path

        with TemporaryDirectory() as tmp:
            root = str(Path(tmp).resolve())
            with patch.dict(os.environ, self._env(root), clear=False):
                from syndicate.features.ncaaf.sources import default_ncaaf_source_root

                # The generator's own write root: `DATA_ROOT` in
                # scripts/generate_smartsim2_ncaaf_projections.py.
                written = projection_artifact_path(
                    season=2026, week=1, data_root=default_ncaaf_source_root() / "data",
                )
                relative = relative_to_data_root(written)

            self.assertIsNotNone(relative, f"{written} did not resolve under the data root")
            self.assertTrue(
                is_hot_artifact_relative_path(relative),
                f"NCAAF projections cannot be published to web: {relative} matches no HOT_ARTIFACT_PATTERN",
            )

    def test_nfl_projection_artifact_is_publishable(self) -> None:
        from syndicate.features.nfl.smartsim2_projection import projection_artifact_path

        with TemporaryDirectory() as tmp:
            root = str(Path(tmp).resolve())
            with patch.dict(os.environ, self._env(root), clear=False):
                from syndicate.features.nfl.sources import nfl_artifact_output_root

                # `#389`: the WRITE root, not the probing read root. This is the
                # same function run_refresh_worker's staleness guard calls.
                written = projection_artifact_path(
                    season=2026, week=1, data_root=nfl_artifact_output_root(),
                )
                relative = relative_to_data_root(written)

            self.assertIsNotNone(relative, f"{written} did not resolve under the data root")
            self.assertTrue(
                is_hot_artifact_relative_path(relative),
                f"NFL projections cannot be published to web: {relative} matches no HOT_ARTIFACT_PATTERN",
            )

    def test_patterns_do_not_sweep_the_sidecar_or_the_preseason_family(self) -> None:
        """The two additions are scoped, and the omission is deliberate.

        `_injury_notes.json` is a per-run diagnostic sidecar written next to the
        NFL CSV; publishing it would be egress for something no board reads.

        `smartsim2_preseason_projections_*` is left out ON PURPOSE: that
        generator has no `publish_hot_artifact` call, so an entry would be the
        inert half of this same defect. When a publisher is wired there, add the
        pattern IN THE SAME CHANGE and delete it from this test.
        """
        self.assertFalse(
            is_hot_artifact_relative_path("nfl_source/smartsim2_projections_2026_wk1_injury_notes.json")
        )
        self.assertFalse(
            is_hot_artifact_relative_path("nfl_source/smartsim2_preseason_projections_2026_wk2.csv")
        )


if __name__ == "__main__":
    unittest.main()
