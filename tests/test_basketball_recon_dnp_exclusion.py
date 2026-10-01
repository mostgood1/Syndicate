"""NBA and WNBA recon_props carry no row for a player who did not play.

ESPN box scores (`basketball_boxscores_history._event_rows_from_summary`, the
path both sports' refresh scripts use) write a DNP as MIN 0 with every counting
stat 0. Kept in recon, that is a real-looking 0-point line: the live-prop audit
grades it, the props calibration trains on it, and `betting_recap` settles a
prop against it -- it coerces even a blank stat to 0.0, so the row must go.
Measured 2026-10-01: the 2026 NBA Finals box scores hold 9-11 such rows of 30.
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.refresh_nba_oddsapi_props import _build_local_recon_props_artifact as build_nba
from scripts.refresh_wnba_oddsapi_props import _build_local_recon_props_artifact as build_wnba
from syndicate.features.shared.basketball_boxscores_history import did_not_play

_DATE = "2026-06-13"
_HEADER = "game_id,TEAM_ABBREVIATION,PLAYER_ID,PLAYER_NAME,MIN,PTS,REB,AST,STL,BLK,TOV,FG3M,PLUS_MINUS"
_PLAYED = "401859967,SAS,1,Victor Wembanyama,38.0,31,12,4,1,5,3,2,9"
_PLAYED_SHORT = "401859967,NYK,2,Tyler Kolek,0:45,0,0,0,0,0,0,0,0"
_DNP_ESPN = "401859967,SAS,3,Mason Plumlee,0.0,0,0,0,0,0,0,0,0"
_DNP_CLOCK = "401859967,NYK,4,Jeremy Sochan,0:00,0,0,0,0,0,0,0,0"
_UNKNOWN_MIN = "401859967,NYK,5,Mohamed Diawara,,,,,,,,,"
# Seconds on the floor: ESPN rounds to MIN 0, but plus-minus proves she played.
_SUB_MINUTE = "401859967,NYK,6,Rayah Marshall,0,0,0,0,0,0,0,0,-2"


class DidNotPlayTests(unittest.TestCase):
    def test_only_minutes_that_parse_to_zero_are_a_dnp(self) -> None:
        for value in ("0", "0.0", "0:00", "PT00M00.00S"):
            self.assertTrue(did_not_play({"MIN": value}), value)
        for value in ("", None, "nan", "12.5", "34:12", "0:45", "PT34M12.00S", "DNP"):
            self.assertFalse(did_not_play({"MIN": value}), value)

    def test_min_zero_with_any_activity_is_not_a_dnp(self) -> None:
        """Measured 2026-10-01: Rayah Marshall, WNBA 2026-09-24, MIN 0 and
        PLUS_MINUS -2 -- on the floor for seconds, correctly kept by
        build_wnba_recon (which reads ESPN's didNotPlay flag)."""
        self.assertFalse(did_not_play({"MIN": "0", "PLUS_MINUS": "-2"}))
        self.assertFalse(did_not_play({"MIN": "0", "PTS": "2"}))
        self.assertTrue(did_not_play({"MIN": "0", "PLUS_MINUS": "0", "PTS": "0"}))

    def test_espns_flag_decides_when_present(self) -> None:
        self.assertTrue(did_not_play({"MIN": "12", "DID_NOT_PLAY": "True"}))
        self.assertFalse(did_not_play({"MIN": "0", "PLUS_MINUS": "0", "DID_NOT_PLAY": "False"}))

    def test_the_espn_fetcher_writes_the_flag(self) -> None:
        from syndicate.features.shared.basketball_boxscores_history import _event_rows_from_summary

        def athlete(name: str, *, dnp: bool, stats: list[str]) -> dict:
            return {"athlete": {"displayName": name, "id": "1"}, "didNotPlay": dnp, "stats": stats}

        summary = {"boxscore": {"players": [{
            "team": {"abbreviation": "NY"},
            "statistics": [{
                "labels": ["MIN", "PTS"],
                "athletes": [athlete("Jalen Brunson", dnp=False, stats=["40", "31"]), athlete("Ariel Hukporti", dnp=True, stats=[])],
            }],
        }]}}
        rows = _event_rows_from_summary(summary=summary, event_id="1", date_str="2026-06-13", league_code="nba")
        self.assertEqual({row["PLAYER_NAME"]: row["DID_NOT_PLAY"] for row in rows}, {"Jalen Brunson": False, "Ariel Hukporti": True})
        self.assertEqual([did_not_play(row) for row in rows], [False, True])

    def test_the_minutes_key_is_matched_case_insensitively(self) -> None:
        self.assertTrue(did_not_play({"min": "0"}))
        self.assertTrue(did_not_play({"minutes": "0:00"}))
        self.assertFalse(did_not_play({"PTS": "0"}))  # no minutes column -> unknown, kept


class ReconBuildersExcludeDnpTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.processed = Path(tmp.name)
        lines = [_HEADER, _PLAYED, _PLAYED_SHORT, _DNP_ESPN, _DNP_CLOCK, _UNKNOWN_MIN, _SUB_MINUTE]
        (self.processed / f"boxscores_{_DATE}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _names(self, build) -> list[str]:
        count, path = build(processed_root=self.processed, date_str=_DATE)
        with Path(path).open(encoding="utf-8", newline="") as handle:
            names = [row["player_name"] for row in csv.DictReader(handle)]
        self.assertEqual(count, len(names))
        return names

    def test_nba_builder_drops_dnps_and_keeps_played_and_unknown_rows(self) -> None:
        self.assertEqual(self._names(build_nba), ["Victor Wembanyama", "Tyler Kolek", "Mohamed Diawara", "Rayah Marshall"])

    def test_wnba_builder_drops_dnps_and_keeps_played_and_unknown_rows(self) -> None:
        self.assertEqual(self._names(build_wnba), ["Victor Wembanyama", "Tyler Kolek", "Mohamed Diawara", "Rayah Marshall"])

    def test_a_day_of_only_dnps_writes_no_file_at_all(self) -> None:
        (self.processed / f"boxscores_{_DATE}.csv").write_text("\n".join([_HEADER, _DNP_ESPN, _DNP_CLOCK]) + "\n", encoding="utf-8")
        self.assertEqual(build_nba(processed_root=self.processed, date_str=_DATE), (0, None))
        self.assertEqual(build_wnba(processed_root=self.processed, date_str=_DATE), (0, None))


if __name__ == "__main__":
    unittest.main()
