"""`#389` follow-up. The generator wrote where the guard never looked.

MEASURED IN PRODUCTION 2026-08-12, from the generator's own log line:

    artifact_path=/opt/render/project/src/data/nfl_source/smartsim2_projections_2026_wk1.csv

while `run_refresh_worker`'s staleness guard read

    /opt/render/project/data/nfl_source/smartsim2_projections_2026_wk1.csv

`src/data` is the repo checkout -- ephemeral, replaced every deploy. `data` is
the mounted disk. So the sim ran to completion ~90 times a day, wrote a real
artifact each time, and every one was invisible to the guard and discarded on
the next deploy.

CAUSE: `default_nfl_source_root()` picks the first candidate root that contains
`upcoming_recs_*.csv`. The repo mirror ships that file; the mounted disk does
not. An unrelated artifact's presence decided where projections were written.
That probe is correct for READS and wrong for WRITES.

The test that matters is `test_guard_and_writer_resolve_the_same_path`: the two
halves diverging is the whole defect, and either half alone can be "correct"
while the pair is broken.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import sources as nfl_sources


def _worker():
    spec = importlib.util.spec_from_file_location(
        "run_refresh_worker_for_nfl_root_tests", REPO_ROOT / "scripts" / "run_refresh_worker.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_refresh_worker_for_nfl_root_tests"] = mod
    spec.loader.exec_module(mod)
    return mod


class NflArtifactOutputRootTests(unittest.TestCase):
    def test_env_var_wins_and_is_not_probed(self) -> None:
        """The configured root is the answer even when it holds nothing.

        This is the production case exactly: the mounted disk had no
        `upcoming_recs_*.csv`, so the probe rejected it -- the one root that
        actually had to receive the write.
        """
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/mnt/disk/nfl_source"}):
            self.assertEqual(
                nfl_sources.nfl_artifact_output_root(), Path("/mnt/disk/nfl_source").expanduser().resolve()
            )

    def test_falls_back_to_the_shared_data_root(self) -> None:
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "", "SYNDICATE_DATA_ROOT": "/mnt/disk"}):
            # .resolve() is applied by data_root(), which on Windows prepends a drive --
            # compare against the same resolution rather than a bare posix string.
            self.assertEqual(
                nfl_sources.nfl_artifact_output_root(),
                Path("/mnt/disk").expanduser().resolve() / "nfl_source",
            )

    def test_does_not_consult_the_filesystem(self) -> None:
        """No probing. A write destination that depends on what happens to be on
        disk is how this broke -- and it fails in the direction that looks fine,
        because the probe finds a root that does exist."""
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/nonexistent/nfl_source"}):
            self.assertEqual(
                nfl_sources.nfl_artifact_output_root(), Path("/nonexistent/nfl_source").expanduser().resolve()
            )


class GuardAndWriterAgreeTests(unittest.TestCase):
    """The defect was a DISAGREEMENT, so the assertion has to be about the pair."""

    def test_guard_and_writer_resolve_the_same_path(self) -> None:
        worker = _worker()
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/mnt/disk/nfl_source"}):
            writer_root = nfl_sources.nfl_artifact_output_root()
            season_guard = worker._season_projection_artifact_path("nfl", 2026, 1)
            preseason_guard = worker._preseason_projection_artifact_path(2026, 2)

        self.assertEqual(season_guard.parent, writer_root)
        self.assertEqual(preseason_guard.parent, writer_root)
        self.assertEqual(season_guard.name, "smartsim2_projections_2026_wk1.csv")
        self.assertEqual(preseason_guard.name, "smartsim2_preseason_projections_2026_wk2.csv")

    def test_the_guard_follows_the_env_var_it_previously_ignored(self) -> None:
        """Before the fix the guard hardcoded data_root()/nfl_source and ignored
        SYNDICATE_NFL_SOURCE_ROOT entirely -- which is how it could point
        somewhere the writer never wrote."""
        worker = _worker()
        with patch.dict("os.environ", {"SYNDICATE_NFL_SOURCE_ROOT": "/elsewhere/nfl_source", "SYNDICATE_DATA_ROOT": "/mnt/disk"}):
            self.assertEqual(
                worker._season_projection_artifact_path("nfl", 2026, 1).parent,
                Path("/elsewhere/nfl_source").expanduser().resolve(),
            )

    def test_ncaaf_is_left_alone_deliberately(self) -> None:
        """Its generator has not been audited. Generalising one sport's bug to
        another sport's layout would be inventing a fact."""
        worker = _worker()
        with patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": "/mnt/disk", "SYNDICATE_NFL_SOURCE_ROOT": "/elsewhere/nfl_source"}):
            self.assertEqual(
                worker._season_projection_artifact_path("ncaaf", 2026, 1),
                Path("/mnt/disk").expanduser().resolve() / "ncaaf_source" / "data" / "smartsim2_projections_2026_wk1.csv",
            )


if __name__ == "__main__":
    unittest.main()
