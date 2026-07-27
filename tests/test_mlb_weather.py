"""#84. NWS park weather: fetch-and-store only; the sim join is the open half."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.fetch_mlb_weather import (
    STADIUM_COORDS,
    _home_teams_from_statsapi_schedule,
    _todays_home_teams,
    fetch_weather_for_date,
    parse_wind_mph,
    trim_hourly_periods,
)


class MlbWeatherTests(unittest.TestCase):
    def test_every_stadium_has_plausible_coordinates(self) -> None:
        self.assertGreaterEqual(len(STADIUM_COORDS), 30)
        for team, coords in STADIUM_COORDS.items():
            self.assertTrue(24.0 < coords["lat"] < 49.0, team)   # continental US + Toronto
            self.assertTrue(-125.0 < coords["lon"] < -66.0, team)
            self.assertIn("roof", coords, team)

    def test_wind_speed_text_parses_including_ranges(self) -> None:
        self.assertEqual(parse_wind_mph("10 mph"), 10.0)
        # "5 to 10 mph": keep the max -- gusts move baseballs.
        self.assertEqual(parse_wind_mph("5 to 10 mph"), 10.0)
        self.assertIsNone(parse_wind_mph(""))
        self.assertIsNone(parse_wind_mph("calm"))

    def test_hourly_trim_keeps_the_forecast_window_and_normalizes(self) -> None:
        now_epoch = 1_800_000_000.0  # 2027-01-15T08:00:00Z
        periods = [
            {"startTime": "2027-01-15T07:00:00+00:00", "temperature": 60, "windSpeed": "5 mph", "windDirection": "N"},
            {"startTime": "2027-01-15T12:00:00+00:00", "temperature": 72, "windSpeed": "10 to 15 mph", "windDirection": "SW"},
            {"startTime": "2027-01-16T12:00:00+00:00", "temperature": 70, "windSpeed": "5 mph", "windDirection": "S"},
            {"startTime": "not a time"},
        ]
        rows = trim_hourly_periods(periods, now_epoch=now_epoch, hours=14)
        self.assertEqual(len(rows), 2)  # 07:00 kept (within 1h grace), 12:00 kept, next-day and junk dropped
        self.assertEqual(rows[1]["temp_f"], 72)
        self.assertEqual(rows[1]["wind_mph"], 15.0)
        self.assertEqual(rows[1]["wind_dir"], "SW")

    def test_todays_home_teams_reads_the_date_suffixed_snapshot_filename(self) -> None:
        # Regression for 2026-07-27: this used to look for a bare
        # "oddsapi_game_lines.json" under daily/snapshots/<date>/, but the
        # writer and its daily-snapshot mirror both use the date-suffixed
        # oddsapi_game_lines_<date_slug>.json in either directory -- the old
        # filename never matched anything, so home teams (and therefore
        # every park's weather) came back empty on every run regardless of
        # whether the odds pipeline had actually produced game data.
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            snapshot_dir = root / "data" / "daily" / "snapshots" / "2026-07-27"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "oddsapi_game_lines_2026_07_27.json").write_text(
                json.dumps({"games": [{"home_team": "New York Yankees"}, {"home_team": "Boston Red Sox"}]}),
                encoding="utf-8",
            )
            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[root]):
                teams = _todays_home_teams("2026-07-27")
        self.assertEqual(teams, ["Boston Red Sox", "New York Yankees"])

    def test_todays_home_teams_falls_back_to_statsapi_schedule_when_no_local_snapshot(self) -> None:
        # Regression for 2026-07-27: on the service that actually runs this
        # script, neither local snapshot candidate ever resolved (confirmed
        # in production -- separate Render disks, no filesystem sharing), so
        # parks/errors stayed {} on every run even on a live 12-game slate.
        # Weather only needs "which parks have a game today", so this falls
        # back to MLB's own free/keyless schedule endpoint instead of
        # depending on the odds pipeline having synced a local file.
        schedule_payload = {
            "dates": [
                {
                    "games": [
                        {"teams": {"home": {"team": {"name": "Boston Red Sox"}}}},
                        {"teams": {"home": {"team": {"name": "New York Yankees"}}}},
                    ]
                }
            ]
        }
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[root]):
                with patch("scripts.fetch_mlb_weather.data_root", return_value=root):
                    with patch("scripts.fetch_mlb_weather._get_json", return_value=schedule_payload) as mock_get:
                        teams = _todays_home_teams("2026-07-27")
        self.assertEqual(teams, ["Boston Red Sox", "New York Yankees"])
        mock_get.assert_called_once()
        self.assertIn("statsapi.mlb.com", mock_get.call_args[0][0])

    def test_todays_home_teams_raises_when_everything_is_unavailable(self) -> None:
        # _todays_home_teams itself does NOT swallow the schedule-fallback
        # failure -- a prior version did (bare `except Exception: return []`
        # around the fallback call), and that shipped 2026-07-27 still
        # producing empty parks/errors in production with zero visibility
        # into why. The caller (fetch_weather_for_date) is what fails open
        # now, and it records the reason -- see the test below.
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[root]):
                with patch("scripts.fetch_mlb_weather.data_root", return_value=root):
                    with patch("scripts.fetch_mlb_weather._get_json", side_effect=OSError("network down")):
                        with self.assertRaises(OSError):
                            _todays_home_teams("2026-07-27")

    def test_fetch_weather_for_date_fails_open_and_records_the_reason(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch("syndicate.features.mlb.sources._artifact_roots", return_value=[root]):
                with patch("scripts.fetch_mlb_weather.data_root", return_value=root):
                    with patch("scripts.fetch_mlb_weather._get_json", side_effect=OSError("network down")):
                        doc = fetch_weather_for_date("2026-07-27")
        self.assertEqual(doc["parks"], {})
        self.assertIn("_home_teams_lookup", doc["errors"])
        self.assertIn("network down", doc["errors"]["_home_teams_lookup"])

    def test_statsapi_schedule_fallback_parses_home_teams_and_dedupes(self) -> None:
        schedule_payload = {
            "dates": [
                {
                    "games": [
                        {"teams": {"home": {"team": {"name": "Athletics"}}}},
                        {"teams": {"home": {"team": {"name": "Athletics"}}}},
                        {"teams": {}},
                        {},
                    ]
                }
            ]
        }
        with patch("scripts.fetch_mlb_weather._get_json", return_value=schedule_payload):
            teams = _home_teams_from_statsapi_schedule("2026-07-27")
        self.assertEqual(teams, ["Athletics"])


if __name__ == "__main__":
    unittest.main()
