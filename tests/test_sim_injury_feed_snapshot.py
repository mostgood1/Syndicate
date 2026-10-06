"""SmartSim reads the injury feed as daily snapshots, not as each player's latest row.

data/raw/injuries.csv stacks one snapshot per day; a player who returns simply
drops off the next one. The sim kept each player's latest row within 30 days,
so a returned player stayed excluded. Measured 2026-10-06 on the fleet: Jewell
Loyd and Stephanie Talbot were OUT on the 10-04/10-05 snapshots, absent from
10-06, and both 10-07 sims still left them out. The props path already uses the
latest-snapshot rule (basketball_props_availability.out_players_for_date).
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from syndicate.features.shared import basketball_props_smart_sim as sim

DATE = "2026-10-07"


def _feed(root: Path, rows: list[tuple[str, str, str, str]]) -> None:
    path = root / "data" / "raw" / "injuries.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team", "player", "status", "injury", "date"])
        for team, player, status, date in rows:
            writer.writerow([team, player, status, status.title(), date])


class SnapshotFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data" / "processed").mkdir(parents=True)
        self.props = pd.DataFrame(
            [{"team": "ATL", "player_name": "Allisha Gray"}, {"team": "LVA", "player_name": "Jewell Loyd"},
             {"team": "ATL", "player_name": "Rhyne Howard"}]
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _excluded(self) -> set[str]:
        out = sim._smart_sim_injuries_excluded_map_for_date_local(
            processed_root=self.root / "data" / "processed", raw_root=self.root / "data" / "raw",
            date_str=DATE, props_df=self.props,
        )
        return {name for names in out.values() for name in names}

    def test_returned_player_is_not_excluded(self) -> None:
        _feed(self.root, [
            ("ATL", "Allisha Gray", "OUT", "2026-10-05"), ("LVA", "Jewell Loyd", "OUT", "2026-10-05"),
            ("ATL", "Allisha Gray", "OUT", "2026-10-06"),  # Loyd is off the 10-06 snapshot: she is back
        ])
        excluded = self._excluded()
        self.assertIn(sim._norm_name_key("Allisha Gray"), excluded)
        self.assertNotIn(sim._norm_name_key("Jewell Loyd"), excluded)
        self.assertNotIn(sim._norm_name_key("Rhyne Howard"), excluded)

    def test_status_change_on_latest_snapshot_wins(self) -> None:
        _feed(self.root, [("ATL", "Allisha Gray", "OUT", "2026-10-05"), ("ATL", "Allisha Gray", "DAY-TO-DAY", "2026-10-06")])
        self.assertNotIn(sim._norm_name_key("Allisha Gray"), self._excluded())

    def test_future_snapshot_is_ignored(self) -> None:
        _feed(self.root, [("ATL", "Allisha Gray", "OUT", "2026-10-06"), ("LVA", "Jewell Loyd", "OUT", "2026-10-08")])
        excluded = self._excluded()
        self.assertIn(sim._norm_name_key("Allisha Gray"), excluded)
        self.assertNotIn(sim._norm_name_key("Jewell Loyd"), excluded)

    def test_stale_snapshot_keeps_only_season_ending(self) -> None:
        _feed(self.root, [("ATL", "Allisha Gray", "OUT FOR SEASON", "2026-08-01"), ("LVA", "Jewell Loyd", "OUT", "2026-08-01")])
        excluded = self._excluded()
        self.assertIn(sim._norm_name_key("Allisha Gray"), excluded)
        self.assertNotIn(sim._norm_name_key("Jewell Loyd"), excluded)

    def test_partial_latest_snapshot_falls_back_to_previous(self) -> None:
        # Lender's guard: a partial fetch must not clear the exclusions. 1 row vs 4 -> previous snapshot.
        _feed(self.root, [
            ("ATL", "Allisha Gray", "OUT", "2026-10-05"), ("LVA", "Jewell Loyd", "OUT", "2026-10-05"),
            ("NYL", "Kara Dunn", "OUT", "2026-10-05"), ("NYL", "Kelsey Plum", "OUT", "2026-10-05"),
            ("GSV", "Tyasha Harris", "DAY-TO-DAY", "2026-10-06"),
        ])
        excluded = self._excluded()
        self.assertIn(sim._norm_name_key("Allisha Gray"), excluded)
        self.assertIn(sim._norm_name_key("Jewell Loyd"), excluded)

    def test_full_sized_latest_snapshot_is_trusted(self) -> None:
        # Same shape, but the latest snapshot is >= half the previous one: it wins.
        _feed(self.root, [
            ("ATL", "Allisha Gray", "OUT", "2026-10-05"), ("LVA", "Jewell Loyd", "OUT", "2026-10-05"),
            ("NYL", "Kara Dunn", "OUT", "2026-10-05"), ("NYL", "Kelsey Plum", "OUT", "2026-10-05"),
            ("ATL", "Allisha Gray", "OUT", "2026-10-06"), ("NYL", "Kara Dunn", "OUT", "2026-10-06"),
        ])
        excluded = self._excluded()
        self.assertIn(sim._norm_name_key("Allisha Gray"), excluded)
        self.assertNotIn(sim._norm_name_key("Jewell Loyd"), excluded)

    def test_rekey_still_applies_to_snapshot_rows(self) -> None:
        # Talbot's feed team is IND; props_df puts her on LVA. The re-key must still land her on LVA.
        self.props = pd.concat([self.props, pd.DataFrame([{"team": "LVA", "player_name": "Stephanie Talbot"}])])
        _feed(self.root, [("IND", "Stephanie Talbot", "OUT", "2026-10-06")])
        out = sim._smart_sim_injuries_excluded_map_for_date_local(
            processed_root=self.root / "data" / "processed", raw_root=self.root / "data" / "raw",
            date_str=DATE, props_df=self.props,
        )
        self.assertIn(sim._norm_name_key("Stephanie Talbot"), out.get("LVA", set()))


if __name__ == "__main__":
    unittest.main()
