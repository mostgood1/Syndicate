"""Board prop rows for a player OUT on the injury feed are flagged and carry no edge.

The baseline props path refuses OUT players at export_props_edges_local
(basketball_props_availability), but Layer 1 / Layer 2 rows are built from
bookmaker QUOTES: an OUT player's quote still reached both boards -- with no
projection, and in Layer 2 ranked on market EV alone. attach_projections now
flags those rows (Layer 1 keeps the quote, marked) using the same
latest-snapshot, confirmed-OUT rule, so the three surfaces agree.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import board_enrichment as be

DATE = "2026-10-07"


def _feed(root: Path, rows: list[tuple[str, str, str, str]]) -> None:
    path = root / "data" / "raw" / "injuries.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team", "player", "status", "injury", "date"])
        for team, player, status, date in rows:
            writer.writerow([team, player, status, status.title(), date])


def _prop(player: str, edge: float | None = 0.4) -> dict:
    return {"kind": "prop", "market": "player_threes", "player_name": player, "line": 1.5,
            "projection": {"projected": 1.9, "edge_vs_line": edge, "edge_vs_market_pct": None}}


class OutPlayerBoardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _feed(self.root, [
            ("ATL", "Allisha Gray", "OUT", "2026-10-06"),
            ("LVA", "Jewell Loyd", "OUT", "2026-10-05"),       # off the 10-06 snapshot: back
            ("ATL", "Rhyne Howard", "DOUBTFUL", "2026-10-06"),  # not confirmed OUT: stays priced
        ])
        self.grid = [_prop("Allisha Gray"), _prop("Jewell Loyd"), _prop("Rhyne Howard"),
                     {"kind": "game", "market": "h2h", "projection": {"edge_vs_market_pct": 2.0}}]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, root: Path | None) -> dict:
        with patch.object(be, "_injury_feed_root", return_value=root), \
                patch.object(be, "_attach_projections_by_sport", return_value={"supported": True}):
            return be.attach_projections(self.grid, sport="wnba", selected_date=DATE)

    def test_only_the_confirmed_out_player_is_flagged(self) -> None:
        coverage = self._run(self.root)
        gray, loyd, howard, game = self.grid
        self.assertEqual(gray["player_availability"]["reason"], "player OUT on the injury feed")
        self.assertIsNone(gray["projection"]["edge_vs_line"])
        self.assertEqual(gray["projection"]["edge_unavailable_reason"], "player OUT on the injury feed")
        for row in (loyd, howard, game):
            self.assertNotIn("player_availability", row)
        self.assertEqual(loyd["projection"]["edge_vs_line"], 0.4)
        self.assertEqual(coverage["out_player_props"]["rows_flagged"], 1)
        self.assertEqual(coverage["out_player_props"]["players"], ["Allisha Gray"])

    def test_flag_is_the_branch_that_did_it(self) -> None:
        # off != on: with no feed, the same grid is untouched and the sweep still reports.
        coverage = self._run(None)
        self.assertNotIn("player_availability", self.grid[0])
        self.assertEqual(self.grid[0]["projection"]["edge_vs_line"], 0.4)
        self.assertEqual(coverage["out_player_props"], {"feed_status": "absent", "rows_flagged": 0})

    def test_rows_are_flagged_not_removed(self) -> None:
        self._run(self.root)
        self.assertEqual(len(self.grid), 4)

    def test_other_sports_are_not_swept(self) -> None:
        with patch.object(be, "_injury_feed_root", return_value=self.root) as feed_root, \
                patch.object(be, "_attach_projections_by_sport", return_value={"supported": True}):
            coverage = be.attach_projections(self.grid, sport="nfl", selected_date=DATE)
        feed_root.assert_not_called()
        self.assertNotIn("out_player_props", coverage)

    def test_sweep_failure_is_loud(self) -> None:
        with patch.object(be, "_flag_out_player_props", side_effect=RuntimeError("boom")), \
                patch.object(be, "_attach_projections_by_sport", return_value={"supported": True}):
            coverage = be.attach_projections(self.grid, sport="nba", selected_date=DATE)
        self.assertEqual(coverage["out_player_props"]["feed_status"], "failed")


if __name__ == "__main__":
    unittest.main()
