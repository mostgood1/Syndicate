from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.fetch_nfl_preseason_odds as fetch_odds


def _write_schedule(root: Path, season: int, rows: list[dict]) -> None:
    fieldnames = ["game_id", "season", "game_type", "week", "gameday", "gametime", "away_team", "home_team", "away_score", "home_score", "status", "venue"]
    path = root / f"schedule_preseason_{season}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            full = {key: "" for key in fieldnames}
            full.update(row)
            writer.writerow(full)


class LoadScheduleLookupTests(unittest.TestCase):
    def test_keys_by_normalized_team_names_preserves_real_abbreviations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_schedule(root, 2026, [{"game_id": "401873271", "week": "1", "home_team": "ARI", "away_team": "CAR"}])
            with patch.object(fetch_odds, "DATA_ROOT", root):
                lookup = fetch_odds.load_schedule_lookup(2026)
        self.assertIn(("Carolina Panthers", "Arizona Cardinals"), lookup)
        matched = lookup[("Carolina Panthers", "Arizona Cardinals")]
        self.assertEqual(matched["game_id"], "401873271")
        self.assertEqual(matched["week"], "1")
        self.assertEqual(matched["away_team"], "CAR")
        self.assertEqual(matched["home_team"], "ARI")

    def test_missing_schedule_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(fetch_odds, "DATA_ROOT", root):
                lookup = fetch_odds.load_schedule_lookup(2026)
        self.assertEqual(lookup, {})


class BuildOddsRowsTests(unittest.TestCase):
    def _real_event(self):
        return {
            "away_team": "Carolina Panthers",
            "home_team": "Arizona Cardinals",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "markets": [
                        {"key": "h2h", "outcomes": [{"name": "Arizona Cardinals", "price": 105}, {"name": "Carolina Panthers", "price": -125}]},
                        {"key": "spreads", "outcomes": [{"name": "Arizona Cardinals", "price": -110, "point": 1.5}, {"name": "Carolina Panthers", "price": -110, "point": -1.5}]},
                        {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 35.5}, {"name": "Under", "price": -110, "point": 35.5}]},
                    ],
                }
            ],
        }

    def test_real_event_matches_schedule_and_extracts_all_markets(self) -> None:
        lookup = {("Carolina Panthers", "Arizona Cardinals"): {"game_id": "401873271", "week": "1", "away_team": "CAR", "home_team": "ARI"}}
        rows = fetch_odds.build_odds_rows([self._real_event()], lookup, 2026)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["game_id"], "401873271")
        self.assertEqual(row["week"], "1")
        self.assertEqual(row["away_team"], "CAR")
        self.assertEqual(row["home_team"], "ARI")
        self.assertEqual(row["home_moneyline"], "105")
        self.assertEqual(row["away_moneyline"], "-125")
        self.assertEqual(row["spread_home"], "1.5")
        self.assertEqual(row["total_line"], "35.5")
        self.assertEqual(row["book"], "draftkings")

    def test_unmatched_event_is_dropped(self) -> None:
        rows = fetch_odds.build_odds_rows([self._real_event()], {}, 2026)
        self.assertEqual(rows, [])

    def test_no_bookmakers_is_dropped(self) -> None:
        event = {"away_team": "Carolina Panthers", "home_team": "Arizona Cardinals", "bookmakers": []}
        lookup = {("Carolina Panthers", "Arizona Cardinals"): {"game_id": "401873271", "week": "1", "away_team": "CAR", "home_team": "ARI"}}
        rows = fetch_odds.build_odds_rows([event], lookup, 2026)
        self.assertEqual(rows, [])


class PreseasonOddsPathTests(unittest.TestCase):
    def test_uses_provided_data_root(self) -> None:
        path = fetch_odds.preseason_odds_path(2026, data_root=Path("/tmp/nfl_source"))
        self.assertEqual(path, Path("/tmp/nfl_source/preseason_odds_2026.csv"))


if __name__ == "__main__":
    unittest.main()
