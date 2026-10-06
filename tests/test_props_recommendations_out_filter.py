"""A player the SmartSim drops as unavailable gets no prop recommendation.

Found 2026-10-06 on the fleet: props_recommendations_2026-10-07.csv recommended
Allisha Gray (ATL, OUT on the injury feed 10-04..10-06; threes OVER 1.5 +118,
EV 31.7%) while the 10-07 SmartSim had dropped her. The recommendations
exporter -- shared by NBA and WNBA, and the source of the slate, top-by-game,
cards snapshot and home-board files -- had no availability check at all. Run
over production's real 10-07 inputs, the fixed exporter drops exactly the three
players absent from both sim files (Gray, Loyd, Talbot).
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import basketball_props_recommendations as recs

DATE = "2026-10-07"


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _edge(player: str, team: str) -> dict[str, object]:
    return {"player_name": player, "team": team, "stat": "threes", "side": "OVER", "line": 1.5,
            "price": 118, "edge": 0.14, "ev": 0.31, "bookmaker": "fanduel"}


class OutFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.processed = root / "data" / "processed"
        _write(self.processed / f"props_edges_{DATE}.csv",
               [_edge("Allisha Gray", "ATL"), _edge("Rhyne Howard", "ATL"), _edge("Jewell Loyd", "LVA")])
        _write(self.processed / f"props_predictions_{DATE}.csv",
               [{"player_name": "Allisha Gray", "team": "ATL", "pred_threes": 1.84},
                {"player_name": "Rhyne Howard", "team": "ATL", "pred_threes": 2.9},
                {"player_name": "Jewell Loyd", "team": "LVA", "pred_threes": 1.6}])
        # The feed lists Loyd on her old team; the shared helper re-keys her to the
        # one team the props data places her on, exactly as the sim does.
        _write(root / "data" / "raw" / "injuries.csv",
               [{"team": "ATL", "player": "Allisha Gray", "status": "OUT", "injury": "Out", "date": "2026-10-06"},
                {"team": "IND", "player": "Jewell Loyd", "status": "OUT", "injury": "Out", "date": "2026-10-05"},
                {"team": "ATL", "player": "Rhyne Howard", "status": "DAY-TO-DAY", "injury": "Ankle", "date": "2026-10-06"}])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _players(self) -> set[str]:
        _, out = recs.export_props_recommendations_local(processed_root=self.processed, date_str=DATE)
        with out.open(encoding="utf-8") as handle:
            return {row["player"] for row in csv.DictReader(handle)}

    def test_out_players_get_no_recommendation(self) -> None:
        self.assertEqual(self._players(), {"Rhyne Howard"})

    def test_filter_is_the_branch_that_removed_them(self) -> None:
        # off != on: with the lookup returning nobody, all three come back -- so the
        # result above is the availability check, not some other filter.
        with patch.object(recs, "_excluded_players_for_date", return_value=({}, recs._normalize_player_name)):
            self.assertEqual(self._players(), {"Allisha Gray", "Rhyne Howard", "Jewell Loyd"})

    def test_no_edges_branch_also_filters(self) -> None:
        (self.processed / f"props_edges_{DATE}.csv").unlink()
        self.assertEqual(self._players(), {"Rhyne Howard"})

    def test_failed_lookup_is_loud_not_silent(self) -> None:
        with patch.object(recs, "_excluded_players_for_date", side_effect=RuntimeError("boom")), \
                patch("builtins.print") as printed:
            players = self._players()
        self.assertEqual(players, {"Allisha Gray", "Rhyne Howard", "Jewell Loyd"})
        lines = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        self.assertIn("AVAILABILITY_CHECK_FAILED", lines)


if __name__ == "__main__":
    unittest.main()
