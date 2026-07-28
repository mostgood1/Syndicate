from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vendor.mlb_bettingv2.tools.oddsapi import fetch_daily_oddsapi_markets as odds_module


def _game_row(event_id: str, away: str, home: str) -> dict:
    return {
        "event_id": event_id,
        "commence_time": "2026-07-28T23:10:00Z",
        "home_team": home,
        "away_team": away,
        "bookmaker": "fanduel",
        "markets": {"h2h": {"home_odds": -150, "away_odds": 130}},
    }


class FetchAndWriteLiveOddsForDateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out_dir = Path(self._tmp.name)
        self.game_lines_path = self.out_dir / "oddsapi_game_lines_2026_07_28.json"
        self.env_patch = patch.dict(os.environ, {"ODDS_API_KEY": "test-key"}, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _seed_existing_full_slate(self, n: int = 16) -> None:
        rows = [_game_row(f"event-{i}", f"Away{i}", f"Home{i}") for i in range(n)]
        self.game_lines_path.write_text(
            json.dumps({"date": "2026-07-28", "games": rows, "meta": {"counts": {"games": n}}}),
            encoding="utf-8",
        )

    def test_a_partial_new_fetch_no_longer_drops_the_other_games_lines(self) -> None:
        # #111: production observed a 16-game slate collapse to 1 game with
        # any market data after a live-events fetch returned only 1 event,
        # because the write replaced games wholesale instead of merging.
        self._seed_existing_full_slate(16)
        single_new_game = [_game_row("event-3", "Away3", "Home3")]

        with patch.object(odds_module, "_fetch_live_events_for_date", return_value=[{"id": "event-3"}]):
            with patch.object(
                odds_module,
                "fetch_live_game_lines_for_date",
                return_value={
                    "date": "2026-07-28",
                    "games": single_new_game,
                    "meta": {"counts": {"games": 1}},
                },
            ):
                with patch.object(
                    odds_module,
                    "fetch_live_pitcher_props_for_date",
                    return_value={"pitcher_props": {}, "meta": {"counts": {"players": 0}}},
                ):
                    with patch.object(
                        odds_module,
                        "fetch_live_hitter_props_for_date",
                        return_value={"hitter_props": {}, "meta": {"counts": {"players": 0}}},
                    ):
                        result = odds_module.fetch_and_write_live_odds_for_date(
                            "2026-07-28",
                            out_dir=self.out_dir,
                        )

        written = json.loads(self.game_lines_path.read_text(encoding="utf-8"))
        event_ids = {row.get("event_id") for row in written.get("games") or []}
        self.assertEqual(len(event_ids), 16, "the other 15 games' lines must survive a partial refetch")
        self.assertIn("event-3", event_ids)
        self.assertEqual(result["status"], "warning")

    def test_a_full_new_fetch_still_replaces_stale_entries_for_games_it_covers(self) -> None:
        self._seed_existing_full_slate(2)
        updated_rows = [
            _game_row("event-0", "Away0", "Home0"),
            {**_game_row("event-1", "Away1", "Home1"), "markets": {"h2h": {"home_odds": -999, "away_odds": 888}}},
        ]

        with patch.object(odds_module, "_fetch_live_events_for_date", return_value=[{"id": "event-0"}, {"id": "event-1"}]):
            with patch.object(
                odds_module,
                "fetch_live_game_lines_for_date",
                return_value={"date": "2026-07-28", "games": updated_rows, "meta": {"counts": {"games": 2}}},
            ):
                with patch.object(
                    odds_module,
                    "fetch_live_pitcher_props_for_date",
                    return_value={"pitcher_props": {}, "meta": {"counts": {"players": 0}}},
                ):
                    with patch.object(
                        odds_module,
                        "fetch_live_hitter_props_for_date",
                        return_value={"hitter_props": {}, "meta": {"counts": {"players": 0}}},
                    ):
                        odds_module.fetch_and_write_live_odds_for_date("2026-07-28", out_dir=self.out_dir)

        written = json.loads(self.game_lines_path.read_text(encoding="utf-8"))
        by_id = {row.get("event_id"): row for row in written.get("games") or []}
        self.assertEqual(len(by_id), 2)
        self.assertEqual(by_id["event-1"]["markets"]["h2h"]["home_odds"], -999)


if __name__ == "__main__":
    unittest.main()
