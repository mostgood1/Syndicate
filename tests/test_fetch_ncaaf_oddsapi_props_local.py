from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts import fetch_ncaaf_oddsapi_props_local as fetch_module


def _event_fixture() -> dict:
    return {
        "id": "evt123",
        "home_team": "Ohio State",
        "away_team": "Michigan",
        "commence_time": "2026-08-29T23:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_pass_yds",
                        "outcomes": [
                            {"name": "Over", "description": "Will Howard", "point": 245.5, "price": -110},
                            {"name": "Under", "description": "Will Howard", "point": 245.5, "price": -120},
                        ],
                    },
                    {
                        "key": "player_anytime_td",
                        "outcomes": [
                            {"name": "Yes", "description": "Quinshon Judkins", "price": 130},
                        ],
                    },
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Ohio State", "price": -150},
                        ],
                    },
                ],
            }
        ],
    }


class FetchNcaafOddsApiPropsLocalTests(unittest.TestCase):
    def test_default_sport_key(self) -> None:
        self.assertEqual(fetch_module._get_sport_key(), "americanfootball_ncaaf")

    @patch.dict("os.environ", {"ODDS_API_SPORT": "americanfootball_ncaaf_custom"}, clear=False)
    def test_sport_key_env_override(self) -> None:
        self.assertEqual(fetch_module._get_sport_key(), "americanfootball_ncaaf_custom")

    def test_parse_events_to_rows_extracts_player_props_and_ignores_non_player_markets(self) -> None:
        rows = fetch_module.parse_events_to_rows([_event_fixture()])

        by_market: dict[str, list[dict]] = {}
        for row in rows:
            by_market.setdefault(row["market"], []).append(row)

        self.assertIn("Passing Yards", by_market)
        passing_row = by_market["Passing Yards"][0]
        self.assertEqual(passing_row["player"], "Will Howard")
        self.assertEqual(passing_row["line"], 245.5)
        self.assertEqual(passing_row["over_price"], -110)
        self.assertEqual(passing_row["under_price"], -120)
        self.assertEqual(passing_row["event"], "Michigan @ Ohio State")
        self.assertEqual(passing_row["book"], "draftkings")

        self.assertIn("Anytime TD", by_market)
        self.assertEqual(by_market["Anytime TD"][0]["player"], "Quinshon Judkins")

        # h2h is a game-line market, not a player prop -- must be ignored.
        self.assertNotIn("h2h", by_market)

    def test_main_writes_header_only_csv_on_confirmed_empty_markets(self) -> None:
        # Confirmed live 2026-08-05: OddsAPI currently returns zero real
        # NCAAF player-prop markets weeks before kickoff (same timing
        # pattern confirmed for NFL's own Hall of Fame Game). This must
        # degrade gracefully to an empty/header-only CSV, never raise.
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "oddsapi_player_props_2026_wk1.csv"

            with patch.object(fetch_module, "fetch_player_props_chunked", return_value=[]), patch.dict(
                "os.environ", {"ODDS_API_KEY": "test-key"}, clear=False
            ):
                exit_code = fetch_module.main(
                    ["--season", "2026", "--week", "1", "--out", str(out_path), "--no-save-raw", "--no-keep-existing-on-empty"]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(out_path.exists())
            result_df = pd.read_csv(out_path)
            self.assertTrue(result_df.empty)

    def test_main_preserves_existing_snapshot_on_ambiguous_empty_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "oddsapi_player_props_2026_wk1.csv"
            out_path.write_text(
                "player,team,market,line,over_price,under_price,book,event,game_time,home_team,away_team,is_ladder\n"
                "Will Howard,,Passing Yards,245.5,-110,-120,draftkings,Michigan @ Ohio State,2026-08-29T23:00:00Z,Ohio State,Michigan,False\n",
                encoding="utf-8",
            )

            with patch.object(fetch_module, "fetch_player_props_chunked", return_value=[]), patch.dict(
                "os.environ", {"ODDS_API_KEY": "test-key"}, clear=False
            ):
                exit_code = fetch_module.main(["--season", "2026", "--week", "1", "--out", str(out_path), "--no-save-raw"])

            self.assertEqual(exit_code, 0)
            result_df = pd.read_csv(out_path)
            self.assertEqual(len(result_df), 1)
            self.assertEqual(result_df.iloc[0]["player"], "Will Howard")

    def test_main_requires_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_path = Path(tmp_dir) / "oddsapi_player_props_2026_wk1.csv"
            # ODDS_API_KEY is confirmed absent from this repo's real .env
            # (unlike CFBD_API_KEY), so clearing the environment here can't
            # accidentally reload a real key via _load_env()'s load_dotenv().
            with patch.dict("os.environ", {}, clear=True):
                exit_code = fetch_module.main(["--season", "2026", "--week", "1", "--out", str(out_path)])
            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
