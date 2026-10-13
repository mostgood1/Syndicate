"""Past-date WNBA chips take their finals from the settlement rows (2026-10-13)."""

from __future__ import annotations

import unittest
from unittest import mock

from syndicate.features.shared import game_chip_finals as gf
from syndicate.features.shared import settlement_sport_rows as rows


def _row(away, away_pts, home, home_pts, game_id="401918300"):
    return rows._score_row("wnba", game_id, home, away, float(home_pts), float(away_pts), "test", game_date="2026-10-09")


def _pregame(away_tri, home_tri):
    return {"away_tri": away_tri, "home_tri": home_tri,
            "status": {"status": "Scheduled", "detail": "8:37 PM CT", "final": False, "in_progress": False},
            "live_state": {}}


class RecordedFinals(unittest.TestCase):
    def _apply(self, games, score_rows, today="2026-10-13"):
        with mock.patch.object(gf, "central_today_iso", return_value=today), \
                mock.patch.object(rows, "wnba_rows_for_date", return_value=score_rows):
            return gf.apply_wnba_recorded_finals(games, "2026-10-09")

    def test_pregame_game_becomes_final_with_the_score(self) -> None:
        out = self._apply([_pregame("GSV", "LVA")], [_row("GS", 87, "LV", 77)])
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["status"]["final"])
        self.assertEqual((out[0]["live_state"]["away_pts"], out[0]["live_state"]["home_pts"]), (87.0, 77.0))

    def test_missing_game_is_added_as_a_final(self) -> None:
        out = self._apply([_pregame("GSV", "LVA")], [_row("GS", 87, "LV", 77), _row("ATL", 85, "NY", 83, "401918299")])
        self.assertEqual(len(out), 2)
        added = out[1]
        self.assertEqual((added["away_tri"], added["home_tri"]), ("ATL", "NYL"))
        self.assertTrue(added["status"]["final"])
        self.assertEqual(added["live_state"]["away_pts"], 85.0)
        from syndicate.features.shared.game_chip_scoreboard import build_game_chip

        chip = build_game_chip("wnba", added)
        self.assertEqual((chip["away"]["name"], chip["home"]["name"]), ("Atlanta Dream", "New York Liberty"))

    def test_today_is_left_to_the_live_merge(self) -> None:
        games = [_pregame("GSV", "LVA")]
        out = self._apply(games, [_row("GS", 87, "LV", 77)], today="2026-10-09")
        self.assertFalse(out[0]["status"]["final"])

    def test_chip_reads_final_and_score(self) -> None:
        from syndicate.features.shared.game_chip_scoreboard import build_game_chip

        out = self._apply([_pregame("GSV", "LVA")], [_row("GS", 87, "LV", 77)])
        chip = build_game_chip("wnba", out[0])
        self.assertEqual(chip["state"], "final")
        self.assertEqual((chip["away"]["score"], chip["home"]["score"]), ("87", "77"))


if __name__ == "__main__":
    unittest.main()
