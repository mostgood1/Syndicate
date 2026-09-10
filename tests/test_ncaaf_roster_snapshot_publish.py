"""`ncaaf-roster-snapshot-publish` lane -- making the NCAAF roster snapshot
able to REACH the web service at all.

THE SITUATION THIS PINS, measured on production 2026-09-09 23:2xZ. Commit
`16d5d811` shipped per-side NCAAF sim projection tables (`'<ABBR> player
projections'`, chip `Sim`). They render on all 51 cards with **0 rows** and an
honest body: *"The 2026 roster snapshot carries no skill-position players for
<team>."* **That empty state is CORRECT -- the code works and the data is
missing.** `ncaaf_roster_snapshot.csv` holds 15,496 rows across 138 teams for
2026 locally and `/api/ops/artifacts/export?pattern=ncaaf_source/**/
ncaaf_roster_snapshot.csv` returned **0 artifacts**; nothing in
`HOT_ARTIFACT_PATTERNS` matched it.

REACHABILITY BEFORE CORRECTNESS, because this lane is ENTIRELY a reachability
fix and there is no arithmetic in it. `ReachabilityFirst` below asserts the two
links that carry this artifact -- the allowlist admits it, and something
actually calls the publish -- and BOTH were absent before this lane, with a
green suite either way. `#208`'s lesson, applied rather than restated: an
allowlist entry alone would have been inert, because there is no blanket sweep
on refresh-worker (`sweep_changed_hot_artifacts`'s only production caller is
`live_lens_loop`, on another service).

WHAT THESE TESTS DO **NOT** SHOW. Nothing here publishes anything. They show the
artifact is PUBLISHABLE and that a completed build pushes it. The card will not
show rows until the writer next runs AND web has the file AND web's reader picks
it up -- the last of which is `_roster_index_cached`'s `(path, mtime_ns, size)`
cache key, asserted at the bottom of this file because that is what makes a
republished file appear without a web restart.
"""
from __future__ import annotations

import fnmatch
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.build_ncaaf_roster_snapshot as build_script
from syndicate.features.ncaaf.sources import roster_snapshot_path
from syndicate.features.shared import artifact_publisher
from syndicate.features.shared.artifact_publisher import (
    HOT_ARTIFACT_PATTERNS,
    is_export_only_artifact_relative_path,
    is_exportable_artifact_relative_path,
    is_hot_artifact_relative_path,
)

#: The one file the NCAAF per-side projection table joins against, relative to
#: `data_root()`. Reconstructed from `sources.roster_snapshot_path()`'s own
#: tail in the first test below rather than only retyped here, so a rename of
#: the writer's path breaks a test instead of silently leaving the allowlist
#: pointed at nothing.
ARTIFACT = "ncaaf_source/source_artifacts/data/processed/roster/ncaaf_roster_snapshot.csv"

#: Measured 2026-09-09 on the local snapshot, not estimated: 44,395 rows over
#: seasons 2025 (28,899) and 2026 (15,496 across 138 teams).
MEASURED_BYTES = 2_588_538
MEASURED_ROWS = 44_395


class ReachabilityFirst(unittest.TestCase):
    """Can the artifact reach a reader AT ALL. Both assertions were FALSE
    before this lane."""

    def test_the_writer_and_the_allowlist_name_the_same_path(self):
        """The allowlist entry is not a guess about where the file lands."""
        tail = roster_snapshot_path().as_posix()
        self.assertTrue(
            tail.endswith("source_artifacts/data/processed/roster/ncaaf_roster_snapshot.csv"),
            tail,
        )
        self.assertTrue(ARTIFACT.endswith(tail.split("ncaaf_source/", 1)[-1]) or tail.endswith(
            ARTIFACT.split("ncaaf_source/", 1)[-1]
        ), tail)

    def test_the_artifact_is_allowlisted(self):
        self.assertTrue(is_hot_artifact_relative_path(ARTIFACT))

    def test_a_publish_call_exists_for_this_path(self):
        """An allowlist entry PERMITS a transfer; it does not make one happen.

        Nothing published this path before today -- checked, the script had no
        `publish_hot_artifact` call of any kind -- and with no blanket sweep on
        refresh-worker the entry above would have stayed inert while every
        upstream stage reported success.
        """
        source = inspect.getsource(build_script)
        self.assertIn("publish_hot_artifact", source)
        self.assertIn("artifact_published", source)


class _Result:
    def __init__(self, output_path: Path, *, validation_issues=()):
        self.rows = [{"player_id": "1"}]
        self.output_path = output_path
        self.identity_path = output_path
        self.validation_issues = tuple(validation_issues)
        self.source_system = "cfbd"
        self.source_snapshot_date = "2026-08-27"
        self.connectivity = {"season": 2026}


def _run_main(tmp: Path, *, validation_issues=()):
    """Drive `main()` over stubs and return (exit_code, publish_mock)."""
    out = tmp / "ncaaf_roster_snapshot.csv"
    out.write_text("player_id\n1\n", encoding="utf-8")
    result = _Result(out, validation_issues=validation_issues)
    argv = [
        "build_ncaaf_roster_snapshot.py",
        "--season",
        "2026",
        "--report-path",
        str(tmp / "report.md"),
    ]
    publish = MagicMock(return_value=True)
    with patch.object(sys, "argv", argv), \
         patch.object(build_script, "CfbdClient") as client, \
         patch.object(build_script, "run_cfbd_player_identity_build", return_value=result), \
         patch.object(build_script, "write_ncaaf_roster_snapshot_csv", return_value=result), \
         patch.object(build_script, "build_ncaaf_roster_generation_report", return_value="report"), \
         patch.object(artifact_publisher, "publish_hot_artifact", publish):
        client.from_env.return_value = MagicMock()
        code = build_script.main()
    return code, publish, out


class ThePublishIsReachedOnACompletedRun(unittest.TestCase):
    """The call is not merely present in the file -- a real `main()` reaches it."""

    def setUp(self):
        self._tmp = Path(__file__).resolve().parent / "_tmp_ncaaf_roster_publish"
        self._tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        for path in self._tmp.glob("*"):
            path.unlink()
        self._tmp.rmdir()

    def test_a_completed_run_publishes_the_file_it_just_wrote(self):
        code, publish, out = _run_main(self._tmp)
        self.assertEqual(code, 0)
        publish.assert_called_once_with(out)

    def test_it_is_unconditional_validation_issues_still_publish(self):
        """UNCONDITIONAL ON A COMPLETED RUN, so a stale bootstrapped copy on web
        converges. The CSV is written before validation is scored;
        `validation_issues` changes only this process's EXIT CODE."""
        code, publish, out = _run_main(self._tmp, validation_issues=("bad row",))
        self.assertEqual(code, 1)
        publish.assert_called_once_with(out)

    def test_a_publish_failure_never_fails_the_build(self):
        out = self._tmp / "ncaaf_roster_snapshot.csv"
        out.write_text("player_id\n1\n", encoding="utf-8")
        result = _Result(out)
        argv = ["x", "--season", "2026", "--report-path", str(self._tmp / "report.md")]
        boom = MagicMock(side_effect=RuntimeError("network"))
        with patch.object(sys, "argv", argv), \
             patch.object(build_script, "CfbdClient") as client, \
             patch.object(build_script, "run_cfbd_player_identity_build", return_value=result), \
             patch.object(build_script, "write_ncaaf_roster_snapshot_csv", return_value=result), \
             patch.object(build_script, "build_ncaaf_roster_generation_report", return_value="report"), \
             patch.object(artifact_publisher, "publish_hot_artifact", boom):
            client.from_env.return_value = MagicMock()
            code = build_script.main()
        self.assertEqual(code, 0)


class AllowlistScope(unittest.TestCase):
    """The entry is a LITERAL path. fnmatch `*` crosses `/`, so a wildcard here
    would reach into a directory a future producer may share."""

    def test_the_entry_is_literal(self):
        self.assertIn(ARTIFACT, HOT_ARTIFACT_PATTERNS)
        self.assertNotIn("*", ARTIFACT)
        self.assertNotIn("?", ARTIFACT)
        self.assertNotIn("[", ARTIFACT)

    def test_it_matches_nothing_beside_the_one_artifact(self):
        # Asserted first so this test cannot pass VACUOUSLY: with the entry
        # absent, "no pattern equal to ARTIFACT matched a neighbour" is
        # trivially true and says nothing.
        self.assertIn(ARTIFACT, HOT_ARTIFACT_PATTERNS)
        neighbours = [
            # Same directory, a different file -- e.g. a future per-season split.
            "ncaaf_source/source_artifacts/data/processed/roster/ncaaf_roster_2026.csv",
            "ncaaf_source/source_artifacts/data/processed/roster/scratch.csv",
            # Deeper, which is what a trailing `*` would have swept in.
            "ncaaf_source/source_artifacts/data/processed/roster/raw/week_1.csv",
            # A different sport's root with the identical tail.
            "nfl_source/source_artifacts/data/processed/roster/ncaaf_roster_snapshot.csv",
            # The separately-allowlisted sibling this must NOT swallow.
            "ncaaf_source/source_artifacts/data/processed/team_registry/ncaaf_team_registry_snapshot.csv",
        ]
        for path in neighbours:
            with self.subTest(path=path):
                self.assertFalse(
                    any(
                        fnmatch.fnmatch(path, pattern) and pattern == ARTIFACT
                        for pattern in HOT_ARTIFACT_PATTERNS
                    ),
                    f"the new literal entry matched {path}",
                )

    def test_the_ncaaf_sibling_snapshots_stay_where_they_were(self):
        """Unaffected in BOTH directions: `team_registry` was already
        allowlisted by its own pattern and still is; `player_identity` and
        `transfers` were not and still are not."""
        self.assertTrue(
            is_hot_artifact_relative_path(
                "ncaaf_source/source_artifacts/data/processed/team_registry/ncaaf_team_registry_snapshot.csv"
            )
        )
        for unlisted in (
            "ncaaf_source/source_artifacts/data/processed/player_identity/ncaaf_player_identity_snapshot.csv",
            "ncaaf_source/source_artifacts/data/processed/transfers/ncaaf_transfer_portal_snapshot.csv",
        ):
            with self.subTest(path=unlisted):
                self.assertFalse(is_hot_artifact_relative_path(unlisted))

    def test_it_is_hot_not_export_only(self):
        """`#413`'s test is a serving HAZARD, and there is none here: the reader
        filters every row on the requested season, so PRESENCE cannot fabricate
        or freeze a projection."""
        self.assertFalse(is_export_only_artifact_relative_path(ARTIFACT))
        self.assertTrue(is_exportable_artifact_relative_path(ARTIFACT))


class SizeAgainstTheCeiling(unittest.TestCase):
    """MEASURED, not guessed. The `player_game_stats` sibling is 4.2 MB and its
    author flagged that a full season approaches `_PUBLISH_MAX_BYTES`; this one
    is not near it."""

    def test_the_measured_file_is_under_the_publish_ceiling(self):
        self.assertLess(MEASURED_BYTES, artifact_publisher._PUBLISH_MAX_BYTES)

    def test_a_full_second_season_still_fits(self):
        """~58 B/row. 2025 (28,899) plus a FULL 2026 at the same size lands near
        3.4 MB; it would take four more accumulated seasons to reach 12 MiB."""
        per_row = MEASURED_BYTES / MEASURED_ROWS
        projected = per_row * (28_899 * 2)
        self.assertLess(projected, artifact_publisher._PUBLISH_MAX_BYTES)

    def test_the_sweep_would_not_refuse_it_at_this_size(self):
        """The real predicate, not the arithmetic: `_publish_skip_reason` is the
        sweep's ceiling, and it is the repair path a too-large file loses."""
        tmp = Path(__file__).resolve().parent / "_tmp_roster_size_probe.csv"
        try:
            with tmp.open("wb") as handle:
                handle.write(b"0" * MEASURED_BYTES)
            from datetime import date

            self.assertIsNone(
                artifact_publisher._publish_skip_reason(tmp, date(2026, 9, 9))
            )
        finally:
            if tmp.exists():
                tmp.unlink()


class TheReaderStillPicksUpARepublishedFile(unittest.TestCase):
    """`player_projections` keys its roster cache on `(path, mtime_ns, size)`
    DELIBERATELY, so a republished file appears WITHOUT a web restart -- unlike
    `player_stats.py:68`, whose plain `@lru_cache` served a stale empty result
    for 25 minutes on 2026-09-09 until a deploy cleared it.

    This lane does not touch that module; the test exists so that if anyone
    later swaps the stamp for a season key, the reason it was a stamp is not
    lost with it.
    """

    def test_the_roster_cache_key_is_the_file_stamp_not_the_season(self):
        from syndicate.features.ncaaf import player_projections

        stamp_source = inspect.getsource(player_projections._stamp)
        self.assertIn("st_mtime_ns", stamp_source)
        self.assertIn("st_size", stamp_source)
        signature = inspect.signature(player_projections._roster_index_cached.__wrapped__)
        self.assertEqual(list(signature.parameters), ["season", "stamp"])

    def test_the_stamp_covers_the_published_copy(self):
        """The stamp must include `roster_snapshot_path()` -- the MOUNTED disk
        path a publish writes -- and not only the repo checkout, or a published
        file would never invalidate the cache."""
        source = inspect.getsource(
            __import__(
                "syndicate.features.ncaaf.player_projections", fromlist=["_roster_stamp"]
            )._roster_stamp
        )
        self.assertIn("roster_snapshot_path()", source)


if __name__ == "__main__":
    unittest.main()
