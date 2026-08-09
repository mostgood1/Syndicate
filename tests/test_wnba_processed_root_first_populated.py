"""`processed_root()` returned a directory with 0 of 6 artifact families.

`current_odds_root_for_sport("wnba")` took `preferred_artifact_roots(...)[0]`,
and that helper unconditionally puts the `source_artifacts` variant first
whether or not anything was ever written there.
`/api/ops/wnba/artifact-counts` exists BECAUSE of this mismatch -- its own
comment says "processed_root() unconditionally prefers a source_artifacts
candidate root whether or not that location actually has anything written to
it" -- and the endpoint was built to report it rather than fix it.

MEASURED on production web 2026-08-08 through that endpoint:

    .../wnba_source/source_artifacts/data/processed    0 of 6 families
    .../wnba_source/data/processed                     game_cards,
                                                       props_recommendations,
                                                       top_by_game,
                                                       recommendations_slate

The visible consequence: WNBA `market-accuracy` served `available: false` across
07-19..08-08 and graded 0 rows while soccer graded 385 and MLB 53 --
indistinguishable from an unplayed slate, which is the failure shape this
project keeps mistaking for "no data".

UNLIKE the branding instance of the same `[0]` defect (`92823414`), the file
really is present on another candidate root here, so the root-order fix ALONE
is sufficient. That is the question to ask at every one of these sites: is the
data absent, or merely looked for in the wrong place first?
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared import odds_control_plane


class WnbaProcessedRootTests(unittest.TestCase):
    def test_the_empty_preferred_root_is_skipped_for_the_populated_one(self) -> None:
        """The production shape: `source_artifacts` first and empty, the real
        artifacts one candidate later."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            empty = base / "wnba_source" / "source_artifacts"
            (empty / "data" / "processed").mkdir(parents=True)
            populated = base / "wnba_source"
            (populated / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (populated / "data" / "processed" / "game_cards_2026-08-08.csv").write_text("x", encoding="utf-8")

            with patch.object(odds_control_plane, "preferred_artifact_roots", return_value=[empty, populated]):
                resolved = odds_control_plane.current_odds_root_for_sport("wnba")

            self.assertEqual(resolved, (populated / "data" / "processed").resolve())

    def test_the_preferred_root_still_wins_when_it_has_files(self) -> None:
        """Root ORDER is still respected -- this is "first populated", not
        "last" or "the other one". A deployment that does write to
        source_artifacts must be unaffected."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "wnba_source" / "source_artifacts"
            (first / "data" / "processed").mkdir(parents=True)
            (first / "data" / "processed" / "game_cards_2026-08-08.csv").write_text("x", encoding="utf-8")
            second = base / "wnba_source"
            (second / "data" / "processed").mkdir(parents=True, exist_ok=True)
            (second / "data" / "processed" / "game_cards_2026-08-08.csv").write_text("y", encoding="utf-8")

            with patch.object(odds_control_plane, "preferred_artifact_roots", return_value=[first, second]):
                resolved = odds_control_plane.current_odds_root_for_sport("wnba")

            self.assertEqual(resolved, (first / "data" / "processed").resolve())

    def test_nothing_populated_anywhere_keeps_todays_answer(self) -> None:
        """A genuinely empty deployment must report the same path it always
        did, so this change cannot turn "no artifacts yet" into a new and
        different-looking failure."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "wnba_source" / "source_artifacts"
            (first / "data" / "processed").mkdir(parents=True)
            second = base / "wnba_source"
            (second / "data" / "processed").mkdir(parents=True, exist_ok=True)

            with patch.object(odds_control_plane, "preferred_artifact_roots", return_value=[first, second]):
                resolved = odds_control_plane.current_odds_root_for_sport("wnba")

            self.assertEqual(resolved, (first / "data" / "processed").resolve())

    def test_nba_and_nhl_are_deliberately_untouched(self) -> None:
        """WNBA only. nba/nhl are the same shape and their roots have NOT been
        measured -- a sweep is how a fix for one sport becomes an outage for
        another, which this repo did to itself earlier the same day."""
        import inspect

        source = inspect.getsource(odds_control_plane.current_odds_root_for_sport)
        nba_block = source.split('if slug == "wnba"')[0]
        self.assertIn("roots[0]", nba_block, "nba's root resolution must be unchanged")


if __name__ == "__main__":
    unittest.main()
