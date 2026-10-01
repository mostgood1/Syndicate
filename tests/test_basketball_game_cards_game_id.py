"""game_cards built from processed game_odds never use the row index as game_id.

Found 2026-10-01: every 2026 NBA Finals game_cards row read `game_id "1"` --
the builders fell back to `enumerate(..., start=1)` when a game_odds row had no
id -- and the live-lens projection builder copied it, so projections joined to
nothing and repeated across dates. On the fleet no NBA game_cards file had ever
carried a real id (3 empty, 4 row-index), and 1,364 WNBA rows were row-index.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import refresh_nba_oddsapi_props as nba
from scripts import refresh_wnba_oddsapi_props as wnba
from syndicate.features.shared.basketball_boxscores_history import espn_event_ids_by_matchup

_DATE = "2026-06-13"


def _scoreboard(*games: tuple[str, str, str]) -> dict:
    return {
        "events": [
            {
                "id": event_id,
                "competitions": [{"competitors": [
                    {"homeAway": "home", "team": {"abbreviation": home}},
                    {"homeAway": "away", "team": {"abbreviation": away}},
                ]}],
            }
            for event_id, home, away in games
        ]
    }


class EspnEventIdsByMatchupTests(unittest.TestCase):
    def test_maps_home_away_tricodes_to_event_ids(self) -> None:
        board = _scoreboard(("401859967", "SA", "NY"), ("401859968", "GS", "LAL"))
        with patch("syndicate.features.shared.basketball_props_smart_sim._espn_scoreboard_local", return_value=board):
            ids = espn_event_ids_by_matchup(processed_root=Path("."), date_str=_DATE, league_code="nba")
        self.assertEqual(ids.get(("GSW", "LAL")), "401859968")
        self.assertIn("401859967", ids.values())

    def test_a_failed_fetch_is_an_empty_map_not_an_exception(self) -> None:
        with patch("syndicate.features.shared.basketball_props_smart_sim._espn_scoreboard_local", side_effect=RuntimeError("down")):
            self.assertEqual(espn_event_ids_by_matchup(processed_root=Path("."), date_str=_DATE, league_code="nba"), {})
        with patch("syndicate.features.shared.basketball_props_smart_sim._espn_scoreboard_local", return_value={}):
            self.assertEqual(espn_event_ids_by_matchup(processed_root=Path("."), date_str=_DATE, league_code="nba"), {})


class GameCardsGameIdTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.processed = self.root / "data" / "processed"
        self.processed.mkdir(parents=True)
        self.date = _DATE

    def _write_game_odds(self, *matchups: tuple[str, str], with_ids: bool = False) -> None:
        header = ["date", "game_id", "home_team", "visitor_team", "commence_time", "home_ml", "away_ml", "total"]
        with (self.processed / f"game_odds_{self.date}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            for index, (home, away) in enumerate(matchups):
                writer.writerow({
                    "date": self.date, "game_id": f"00424{index:05d}" if with_ids else "", "home_team": home,
                    "visitor_team": away, "commence_time": f"{self.date}T23:30:00Z", "home_ml": -150, "away_ml": 130, "total": 215.5,
                })

    def _ids(self, module, espn_ids: dict) -> dict[tuple[str, str], str]:
        with patch(
            "syndicate.features.shared.basketball_boxscores_history.espn_event_ids_by_matchup", return_value=espn_ids
        ) as lookup:
            if module is nba:
                count, path = module._build_local_game_cards_artifact(
                    source_root=self.root, processed_root=self.processed, date_str=self.date, log_file=self.root / "log.txt"
                )
            else:
                count, path = module._build_local_game_cards_artifact(
                    source_root=self.root, processed_root=self.processed, date_str=self.date, log_file=self.root / "log.txt"
                )
        self.lookup_calls = lookup.call_count
        self.assertGreater(count, 0, "builder took a branch that wrote nothing -- fixture did not reach the game_odds path")
        with Path(path).open(encoding="utf-8", newline="") as handle:
            return {(row["home_tri"], row["away_tri"]): row["game_id"] for row in csv.DictReader(handle)}

    def test_nba_uses_the_espn_event_id_never_the_row_index(self) -> None:
        self._write_game_odds(("San Antonio Spurs", "New York Knicks"))
        ids = self._ids(nba, {("SAS", "NYK"): "401859967"})
        self.assertEqual(ids, {("SAS", "NYK"): "401859967"})

    def test_nba_without_an_espn_match_falls_back_to_away_at_home(self) -> None:
        self._write_game_odds(("San Antonio Spurs", "New York Knicks"), ("Boston Celtics", "Miami Heat"))
        ids = self._ids(nba, {})
        self.assertEqual(ids, {("SAS", "NYK"): "NYK@SAS", ("BOS", "MIA"): "MIA@BOS"})
        self.assertEqual(len(set(ids.values())), 2)  # still unique within the day
        self.assertNotIn("1", ids.values())

    # 2026-09-30: no WNBA schedule in the checkout for that date, so the builder
    # reaches the game_odds fallback (06-13 has one and takes the schedule path,
    # which already carries real ESPN ids).
    def test_wnba_uses_the_espn_event_id_never_the_row_index(self) -> None:
        self.date = "2026-09-30"
        self._write_game_odds(("Las Vegas Aces", "New York Liberty"))
        ids = self._ids(wnba, {("LVA", "NYL"): "401999999"})
        self.assertEqual(ids, {("LVA", "NYL"): "401999999"})

    def test_wnba_without_an_espn_match_falls_back_to_away_at_home(self) -> None:
        self.date = "2026-09-30"
        self._write_game_odds(("Las Vegas Aces", "New York Liberty"))
        self.assertEqual(self._ids(wnba, {}), {("LVA", "NYL"): "NYL@LVA"})

    def test_nba_keeps_a_real_row_id_and_never_calls_espn(self) -> None:
        self._write_game_odds(("San Antonio Spurs", "New York Knicks"), with_ids=True)
        ids = self._ids(nba, {("SAS", "NYK"): "401859967"})
        self.assertEqual(ids, {("SAS", "NYK"): "0042400000"})
        self.assertEqual(self.lookup_calls, 0)


if __name__ == "__main__":
    unittest.main()
