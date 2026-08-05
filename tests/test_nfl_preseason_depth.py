"""Coverage for syndicate/features/nfl/preseason_depth.py -- real
depth-chart-informed preseason snap-leader/starters-sitting context. Same
tempdir-patched-source-root fixture pattern as
tests/test_nfl_injury_adjustment.py, since both modules read the same
real depth_{season}_snapshot.csv shape.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import injury_adjustment as inj
from syndicate.features.nfl import preseason_depth as pd


_DEPTH_FIELDNAMES = ["team", "player_id", "player_name", "position", "positional_group", "depth_rank", "role", "roster_status"]


class PreseasonDepthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = patch.object(inj, "default_nfl_source_root", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_depth_chart(self, season: int, rows: list[dict]) -> None:
        directory = self.root / "source_artifacts" / "data" / "processed" / "depth"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / f"depth_{season}_snapshot.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_DEPTH_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in _DEPTH_FIELDNAMES}
                full.update(row)
                writer.writerow(full)

    def _row(self, *, player_id, player_name, position, depth_rank, role="Depth", roster_status="Active"):
        return {"team": "KC", "player_id": player_id, "player_name": player_name, "position": position,
                "positional_group": position, "depth_rank": str(depth_rank), "role": role, "roster_status": roster_status}


class LikelySnapLeadersTests(PreseasonDepthTestCase):
    def test_week_1_excludes_the_real_starter(self) -> None:
        self._write_depth_chart(2026, [
            self._row(player_id="00-1111111", player_name="Starter QB", position="QB", depth_rank=1, role="Starter"),
            self._row(player_id="00-2222222", player_name="Backup QB", position="QB", depth_rank=2, role="Depth 2"),
        ])
        leaders = pd.likely_snap_leaders(2026, "KC", week=1)
        names = [row["player_name"] for row in leaders]
        self.assertNotIn("Starter QB", names)
        self.assertIn("Backup QB", names)

    def test_week_3_dress_rehearsal_includes_the_real_starter(self) -> None:
        self._write_depth_chart(2026, [
            self._row(player_id="00-1111111", player_name="Starter QB", position="QB", depth_rank=1, role="Starter"),
            self._row(player_id="00-2222222", player_name="Backup QB", position="QB", depth_rank=2, role="Depth 2"),
        ])
        leaders = pd.likely_snap_leaders(2026, "KC", week=3)
        names = [row["player_name"] for row in leaders]
        self.assertIn("Starter QB", names)
        self.assertIn("Backup QB", names)

    def test_ordered_by_real_depth_rank(self) -> None:
        self._write_depth_chart(2026, [
            self._row(player_id="00-3333333", player_name="Third String", position="RB", depth_rank=3),
            self._row(player_id="00-2222222", player_name="Second String", position="RB", depth_rank=2),
        ])
        leaders = pd.likely_snap_leaders(2026, "KC", week=1)
        self.assertEqual([row["player_name"] for row in leaders], ["Second String", "Third String"])

    def test_top_n_limits_results(self) -> None:
        rows = [self._row(player_id=f"00-{n:07d}", player_name=f"Player {n}", position="WR", depth_rank=n) for n in range(2, 10)]
        self._write_depth_chart(2026, rows)
        leaders = pd.likely_snap_leaders(2026, "KC", week=1, top_n=3)
        self.assertEqual(len(leaders), 3)

    def test_no_epa_rating_attached(self) -> None:
        self._write_depth_chart(2026, [self._row(player_id="00-2222222", player_name="Backup QB", position="QB", depth_rank=2)])
        leaders = pd.likely_snap_leaders(2026, "KC", week=1)
        self.assertNotIn("epa", leaders[0])
        self.assertNotIn("rating", leaders[0])

    def test_no_depth_chart_returns_empty(self) -> None:
        self.assertEqual(pd.likely_snap_leaders(2026, "KC", week=1), [])


class LikelyStartersSittingTests(PreseasonDepthTestCase):
    def test_returns_only_real_rank_1_players(self) -> None:
        self._write_depth_chart(2026, [
            self._row(player_id="00-1111111", player_name="Starter QB", position="QB", depth_rank=1, role="Starter"),
            self._row(player_id="00-2222222", player_name="Backup QB", position="QB", depth_rank=2, role="Depth 2"),
        ])
        sitting = pd.likely_starters_sitting(2026, "KC", week=1)
        self.assertEqual(len(sitting), 1)
        self.assertEqual(sitting[0]["player_name"], "Starter QB")

    def test_week_1_status_note_is_resting(self) -> None:
        self._write_depth_chart(2026, [self._row(player_id="00-1111111", player_name="Starter QB", position="QB", depth_rank=1)])
        sitting = pd.likely_starters_sitting(2026, "KC", week=1)
        self.assertEqual(sitting[0]["status_note"], "Likely resting")

    def test_week_3_status_note_is_limited_reps(self) -> None:
        self._write_depth_chart(2026, [self._row(player_id="00-1111111", player_name="Starter QB", position="QB", depth_rank=1)])
        sitting = pd.likely_starters_sitting(2026, "KC", week=3)
        self.assertEqual(sitting[0]["status_note"], "May see limited first-half reps")


class ParticipationShareConstantsTests(unittest.TestCase):
    def test_all_four_weeks_have_a_share(self) -> None:
        for week in (1, 2, 3, 4):
            self.assertIn(week, pd.NONSTARTER_PARTICIPATION_SHARE)
            self.assertGreater(pd.NONSTARTER_PARTICIPATION_SHARE[week], 0.0)
            self.assertLessEqual(pd.NONSTARTER_PARTICIPATION_SHARE[week], 1.0)

    def test_dress_rehearsal_week_has_lowest_share(self) -> None:
        share = pd.NONSTARTER_PARTICIPATION_SHARE
        self.assertLess(share[3], share[1])
        self.assertLess(share[3], share[2])
        self.assertLess(share[3], share[4])


if __name__ == "__main__":
    unittest.main()
