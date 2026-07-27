"""#84. NWS park weather: fetch-and-store only; the sim join is the open half."""

from __future__ import annotations

import unittest

from scripts.fetch_mlb_weather import STADIUM_COORDS, parse_wind_mph, trim_hourly_periods


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


if __name__ == "__main__":
    unittest.main()
