"""NHL / soccer pressure line on live games-rail cards (2026-10-14)."""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import game_chip_trend as gt

_HEADER = {"header": {"competitions": [{"competitors": [
    {"homeAway": "away", "team": {"id": "22", "displayName": "Vancouver Canucks"}},
    {"homeAway": "home", "team": {"id": "12", "displayName": "New York Islanders"}}]}]}}


def _nhl_play(kind, team, period, clock):
    return {"type": {"text": kind}, "team": {"id": team}, "period": {"number": period}, "clock": {"displayValue": clock}}


class NhlPressure(unittest.TestCase):
    def test_home_outshooting_in_the_last_ten(self) -> None:
        plays = [_nhl_play("Shot", "22", 2, "05:00")]  # outside the window
        plays += [_nhl_play("Shot", "12", 3, f"{m:02d}:00") for m in (8, 9, 10, 11, 12, 13)]
        plays += [_nhl_play("Missed", "12", 3, "14:00"), _nhl_play("Shot", "22", 3, "15:00"), _nhl_play("Blocked", "22", 3, "16:00")]
        got = gt.nhl_pressure({**_HEADER, "plays": plays}, "VAN", "NYI")
        self.assertEqual(got, "NYI pressing · 7–1 shots, last 10'")

    def test_even_game_says_nothing(self) -> None:
        plays = [_nhl_play("Shot", t, 3, f"{m:02d}:00") for m, t in ((10, "12"), (11, "22"), (12, "12"), (13, "22"))]
        self.assertIsNone(gt.nhl_pressure({**_HEADER, "plays": plays}, "VAN", "NYI"))


def _soc(kind, team, minute):
    return {"time": {"displayValue": minute}, "play": {"type": {"text": kind}, "team": {"displayName": team}}}


class SoccerPressure(unittest.TestCase):
    def test_shots_and_corners_in_the_last_fifteen(self) -> None:
        home, away = "New York Islanders", "Vancouver Canucks"  # any two names in the header
        com = [_soc("Shot On Target", away, "20'")]  # outside the window
        com += [_soc("Shot Off Target", home, "62'"), _soc("Shot Blocked", home, "65'"), _soc("Goal - Header", home, "70'"),
                _soc("Shot On Target", home, "74'"), _soc("Shot On Target", away, "71'"),
                _soc("Corner Awarded", home, "66'"), _soc("Corner Awarded", home, "73'"), _soc("Corner Awarded", home, "75'+2'")]
        got = gt.soccer_pressure({**_HEADER, "commentary": com}, "VAN", "NYI")
        self.assertEqual(got, "NYI pressing · 4–1 shots, 3–0 corners, last 15'")

    def test_quiet_window_says_nothing(self) -> None:
        com = [_soc("Shot On Target", "New York Islanders", "80'"), _soc("Foul", "Vancouver Canucks", "81'")]
        self.assertIsNone(gt.soccer_pressure({**_HEADER, "commentary": com}, "VAN", "NYI"))


class ChipLine(unittest.TestCase):
    def test_replaces_rather_than_stacks_and_drops_raw_game_state(self) -> None:
        from syndicate.features.shared import game_chip_scoreboard as gs

        chip = {"sport": "nhl", "state": "live", "situation": "CRIT", "game_key": "1", "away": {"abbr": "VAN"}, "home": {"abbr": "NYI"}}
        with mock.patch("syndicate.features.shared.game_chip_linescore.espn_event_id", return_value="401"), \
                mock.patch.object(gt, "live_trend", side_effect=["NYI pressing · 7–1 shots, last 10'", "VAN pressing · 6–2 shots, last 10'"]):
            gs._attach_trend("nhl", {}, chip, "2026-10-13")
            self.assertEqual(chip["situation"], "NYI pressing · 7–1 shots, last 10'")
            gs._attach_trend("nhl", {}, chip, "2026-10-13")
        self.assertEqual(chip["situation"], "VAN pressing · 6–2 shots, last 10'")


if __name__ == "__main__":
    unittest.main()
