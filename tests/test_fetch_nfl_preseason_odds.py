from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
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


class PreseasonOddsSnapshotPathTests(unittest.TestCase):
    def test_uses_provided_snapshot_date(self) -> None:
        path = fetch_odds.preseason_odds_snapshot_path(2026, data_root=Path("/tmp/nfl_source"), snapshot_date=date(2026, 8, 6))
        self.assertEqual(path, Path("/tmp/nfl_source/preseason_odds_snapshot_2026_08_06.csv"))

    def test_defaults_to_todays_utc_date_when_not_provided(self) -> None:
        with patch.object(fetch_odds, "datetime") as mock_datetime:
            mock_datetime.now.return_value.date.return_value = date(2026, 8, 6)
            path = fetch_odds.preseason_odds_snapshot_path(2026, data_root=Path("/tmp/nfl_source"))
        self.assertEqual(path, Path("/tmp/nfl_source/preseason_odds_snapshot_2026_08_06.csv"))


class WritePreseasonOddsSnapshotTests(unittest.TestCase):
    """The core regression coverage for the data-loss bug this task exists
    to prevent: preseason_odds_{season}.csv is fully overwritten every
    refresh (see fetch_nfl_preseason_odds.py's module docstring), so once a
    game is played and drops out of OddsAPI's live response, its real
    closing line is gone from that file forever unless a dated snapshot
    already captured it."""

    _HOF_GAME_ROW = {
        "game_id": "401873271", "season": "2026", "week": "1",
        "home_team": "ARI", "away_team": "CAR",
        "home_moneyline": "-150", "away_moneyline": "130",
        "spread_home": "-3.5", "total_line": "35.5",
        "book": "draftkings", "fetched_at": "2026-08-06T12:00:00+00:00",
    }

    def test_writes_new_snapshot_file_with_header_and_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = fetch_odds.write_preseason_odds_snapshot(
                [self._HOF_GAME_ROW], season=2026, data_root=root, snapshot_date=date(2026, 8, 6)
            )
            self.assertEqual(path, root / "preseason_odds_snapshot_2026_08_06.csv")
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "401873271")
            self.assertEqual(rows[0]["spread_home"], "-3.5")

    def test_second_call_same_day_does_not_duplicate_existing_game_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fetch_odds.write_preseason_odds_snapshot([self._HOF_GAME_ROW], season=2026, data_root=root, snapshot_date=date(2026, 8, 6))
            # Re-run later the same day with a (hypothetically) updated line for the same game_id.
            updated_row = dict(self._HOF_GAME_ROW, spread_home="-4.5")
            path = fetch_odds.write_preseason_odds_snapshot([updated_row], season=2026, data_root=root, snapshot_date=date(2026, 8, 6))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            # The row captured on the first run of the day is preserved, not overwritten.
            self.assertEqual(rows[0]["spread_home"], "-3.5")

    def test_second_call_same_day_appends_a_genuinely_new_game_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fetch_odds.write_preseason_odds_snapshot([self._HOF_GAME_ROW], season=2026, data_root=root, snapshot_date=date(2026, 8, 6))
            other_row = dict(self._HOF_GAME_ROW, game_id="401873272", home_team="DAL", away_team="LAC")
            path = fetch_odds.write_preseason_odds_snapshot([other_row], season=2026, data_root=root, snapshot_date=date(2026, 8, 6))
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual({row["game_id"] for row in rows}, {"401873271", "401873272"})

    def test_game_disappearing_from_live_feed_after_it_is_played_does_not_lose_data(self) -> None:
        """The exact scenario this task exists to prevent: run the real
        fetch-odds flow (build_odds_rows -> write live CSV -> write dated
        snapshot) once while the Hall of Fame Game is still active in
        OddsAPI's feed, then again after it has been played and OddsAPI no
        longer lists it. The live file loses the game (the pre-existing
        bug); the dated snapshots do not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schedule_row = {"game_id": "401873271", "week": "1", "home_team": "ARI", "away_team": "CAR"}
            _write_schedule(root, 2026, [schedule_row])

            real_event = {
                "away_team": "Carolina Panthers",
                "home_team": "Arizona Cardinals",
                "bookmakers": [
                    {
                        "key": "draftkings",
                        "markets": [
                            {"key": "h2h", "outcomes": [{"name": "Arizona Cardinals", "price": -150}, {"name": "Carolina Panthers", "price": 130}]},
                            {"key": "spreads", "outcomes": [{"name": "Arizona Cardinals", "price": -110, "point": -3.5}, {"name": "Carolina Panthers", "price": -110, "point": 3.5}]},
                            {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 35.5}, {"name": "Under", "price": -110, "point": 35.5}]},
                        ],
                    }
                ],
            }

            with patch.object(fetch_odds, "DATA_ROOT", root):
                lookup = fetch_odds.load_schedule_lookup(2026)

                # Run 1 (before kickoff): OddsAPI still has a real, active line.
                rows_before = fetch_odds.build_odds_rows([real_event], lookup, 2026)
                live_path = fetch_odds.preseason_odds_path(2026)
                with live_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(fetch_odds.ODDS_COLUMNS))
                    writer.writeheader()
                    for row in rows_before:
                        writer.writerow(row)
                snapshot_path_day1 = fetch_odds.write_preseason_odds_snapshot(
                    rows_before, season=2026, snapshot_date=date(2026, 8, 6)
                )

                # Run 2 (after the game was played): OddsAPI no longer lists it.
                rows_after = fetch_odds.build_odds_rows([], lookup, 2026)
                with live_path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(fetch_odds.ODDS_COLUMNS))
                    writer.writeheader()
                    for row in rows_after:
                        writer.writerow(row)
                snapshot_path_day2 = fetch_odds.write_preseason_odds_snapshot(
                    rows_after, season=2026, snapshot_date=date(2026, 8, 7)
                )

            # The pre-existing bug, reproduced: the live-overwritten file lost the game.
            with live_path.open("r", encoding="utf-8-sig", newline="") as handle:
                live_rows = list(csv.DictReader(handle))
            self.assertEqual(live_rows, [])

            # Two real, durable, distinct dated snapshot artifacts exist.
            self.assertNotEqual(snapshot_path_day1, snapshot_path_day2)
            self.assertTrue(snapshot_path_day1.exists())
            self.assertTrue(snapshot_path_day2.exists())

            # The fix: day 1's snapshot still has the real closing line, untouched by day 2's run.
            with snapshot_path_day1.open("r", encoding="utf-8-sig", newline="") as handle:
                day1_rows = list(csv.DictReader(handle))
            self.assertEqual(len(day1_rows), 1)
            self.assertEqual(day1_rows[0]["game_id"], "401873271")
            self.assertEqual(day1_rows[0]["spread_home"], "-3.5")
            self.assertEqual(day1_rows[0]["total_line"], "35.5")


if __name__ == "__main__":
    unittest.main()
