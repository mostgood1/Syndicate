"""Games-rail line scores: per-period scores, or R/H/E for MLB (2026-10-13)."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from syndicate.features.shared import game_chip_linescore as gl


class LineScores(unittest.TestCase):
    def setUp(self) -> None:
        gl._CACHE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_football_quarters_and_overtime(self) -> None:
        game = {"live_state": {"away_linescores": [0, 14, 0, 3, 6], "home_linescores": [7, 0, 3, 7, 0]}}
        got = gl.linescore("nfl", game, "2026-10-11")
        self.assertEqual(got["labels"], ["1", "2", "3", "4", "OT"])
        self.assertEqual(got["away"], [0, 14, 0, 3, 6])

    def test_basketball_quarters_from_pbp_cumulative_scores(self) -> None:
        path = self.root / "nba_source" / "data" / "processed"
        path.mkdir(parents=True)
        rows = ["game_id,event_id,period,home_score,away_score",
                "401,401,1,10,8", "401,401,1,33,26", "401,401,2,68,61", "401,401,3,99,78", "401,401,4,119,109"]
        (path / "pbp_espn_2026-10-12.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        got = gl.linescore("nba", {"game_id": "401"}, "2026-10-12")
        self.assertEqual(got["away"], [26, 35, 17, 31])
        self.assertEqual(got["home"], [33, 35, 31, 20])
        self.assertEqual(sum(got["home"]), 119)

    def test_nhl_goals_by_period_joined_through_the_boxscore_id(self) -> None:
        cache = self.root / "nhl_source" / "data" / "ingestion_cache"
        cache.mkdir(parents=True)
        (cache / "boxscore_2026020087.json").write_text(json.dumps(
            {"id": 2026020087, "gameDate": "2026-10-12", "awayTeam": {"abbrev": "FLA"}, "homeTeam": {"abbrev": "BUF"}}), encoding="utf-8")
        goal = lambda team: {"teamAbbrev": {"default": team}}  # noqa: E731
        (cache / "landing_2026020087.json").write_text(json.dumps({"summary": {"scoring": [
            {"periodDescriptor": {"number": 1, "periodType": "REG"}, "goals": [goal("FLA"), goal("BUF"), goal("BUF")]},
            {"periodDescriptor": {"number": 2, "periodType": "REG"}, "goals": [goal("FLA")]},
            {"periodDescriptor": {"number": 3, "periodType": "REG"}, "goals": []},
            {"periodDescriptor": {"number": 5, "periodType": "SO"}, "goals": [goal("FLA")]},
        ]}}), encoding="utf-8")
        got = gl.linescore("nhl", {"gamePk": "1"}, "2026-10-12", away_abbr="FLA", home_abbr="BUF")
        self.assertEqual((got["labels"], got["away"], got["home"]), (["1", "2", "3"], [1, 1, 0], [2, 0, 0]))

    def test_mlb_runs_hits_errors(self) -> None:
        feed = self.root / "mlb_source" / "source_artifacts" / "data" / "raw" / "statsapi" / "feed_live" / "2026" / "2026-10-12"
        feed.mkdir(parents=True)
        with gzip.open(feed / "849820.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"liveData": {"linescore": {"teams": {"home": {"runs": 3, "hits": 7, "errors": 0},
                                                            "away": {"runs": 7, "hits": 14, "errors": 1}}}}}, fh)
        with mock.patch.object(gl, "_mlb_live_board", return_value={}):  # older-date path: the feed file
            got = gl.linescore("mlb", {"gamePk": 849820}, "2026-10-12")
        self.assertEqual((got["kind"], got["labels"], got["away"], got["home"]), ("rhe", ["R", "H", "E"], [7, 14, 1], [3, 7, 0]))

    def test_soccer_halves_from_the_match_box(self) -> None:
        box = {"match_box": {"999": {"away_linescores": [1, 3], "home_linescores": [0, 1]}}}
        with mock.patch("syndicate.features.soccer.sources.board_live_state_payload", return_value=box):
            got = gl.linescore("soccer", {"event_id": "999", "league": "mls"}, "2026-10-11")
        self.assertEqual((got["labels"], got["away"], got["home"]), (["1H", "2H"], [1, 3], [0, 1]))

    def test_no_source_means_no_line_score(self) -> None:
        self.assertIsNone(gl.linescore("wnba", {"game_id": "401"}, "2026-10-09"))
        self.assertIsNone(gl.linescore("nfl", {"live_state": {}}, "2026-10-11"))


class FinalWithoutScore(unittest.TestCase):
    def test_final_with_null_scores_takes_the_period_sums(self) -> None:
        from syndicate.features.shared import game_chip_scoreboard as gs

        chip = {"state": "final", "away": {"abbr": "OKC", "score": None}, "home": {"abbr": "ATL", "score": None}}
        box = {"kind": "periods", "labels": ["1", "2", "3", "4"], "away": [28, 21, 30, 31], "home": [29, 27, 23, 34]}
        with mock.patch.object(gl, "linescore", return_value=box):
            gs._attach_linescore("nba", {}, chip, "2026-10-12")
        self.assertEqual((chip["away"]["score"], chip["home"]["score"], chip["leader"]), ("110", "113", "home"))

    def test_live_game_scores_are_never_filled(self) -> None:
        from syndicate.features.shared import game_chip_scoreboard as gs

        chip = {"state": "live", "away": {"score": None}, "home": {"score": None}}
        with mock.patch.object(gl, "linescore", return_value={"kind": "periods", "labels": ["1"], "away": [20], "home": [18]}):
            gs._attach_linescore("nba", {}, chip, "2026-10-12")
        self.assertIsNone(chip["away"]["score"])


class DailyLineScores(unittest.TestCase):
    def test_scoreboard_parse_keeps_completed_games_only(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("fbl", Path(__file__).resolve().parents[1] / "scripts" / "fetch_basketball_linescores.py")
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        team = lambda abbr, side, per: {"homeAway": side, "team": {"abbreviation": abbr}, "linescores": [{"value": v} for v in per]}  # noqa: E731
        payload = {"events": [
            {"id": "401", "status": {"type": {"completed": True}}, "competitions": [{"competitors": [team("NY", "away", [26, 28, 20, 14, 10]), team("ATL", "home", [26, 30, 19, 13, 13])]}]},
            {"id": "402", "status": {"type": {"completed": False}}, "competitions": [{"competitors": [team("A", "away", [1]), team("B", "home", [2])]}]},
        ]}
        got = mod.parse_scoreboard(payload)
        self.assertEqual(list(got), ["401"])
        self.assertEqual(got["401"]["home_periods"], [26, 30, 19, 13, 13])

    def test_daily_file_wins_and_joins_by_team_pair(self) -> None:
        gl._CACHE.clear()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
            path = Path(tmp) / "wnba_source" / "data" / "processed"
            path.mkdir(parents=True)
            (path / "linescores_2026-10-07.json").write_text(json.dumps({"games": {"401918297": {
                "away": "NY", "home": "ATL", "away_periods": [26, 28, 20, 14, 10], "home_periods": [26, 30, 19, 13, 13]}}}), encoding="utf-8")
            got = gl.linescore("wnba", {"away_tri": "NYL", "home_tri": "ATL", "game_id": "oddsapi-x"}, "2026-10-07")
        self.assertEqual(got["labels"], ["1", "2", "3", "4", "OT"])
        self.assertEqual(sum(got["home"]), 101)


class LiveFromEspn(unittest.TestCase):
    BOARD = {"401898403": {"away": "CLE", "home": "ORL", "away_periods": [28, 24, 17], "home_periods": [35, 37, 23]},
             "401892489": {"away": "FLA", "home": "CBJ", "away_periods": [0, 4, 2], "home_periods": [1, 0, 1]},
             "401892500": {"away": "UTAH", "home": "NJ", "away_periods": [1, 0, 0, 1], "home_periods": [0, 1, 0, 0]},
             "401892501": {"away": "BUF", "home": "MTL", "away_periods": [1, 0, 2, 0, 0], "home_periods": [1, 2, 0, 0, 1]}}

    def _live(self, sport, game, **kw):
        gl._CACHE.clear()
        with mock.patch.object(gl, "_espn_board", return_value=self.BOARD):
            return gl.linescore(sport, game, "2026-10-13", live=True, **kw)

    def test_live_nba_by_espn_id(self) -> None:
        got = self._live("nba", {"game_id": "401898403"})
        self.assertEqual((got["labels"], got["away"], got["home"]), (["1", "2", "3"], [28, 24, 17], [35, 37, 23]))

    def test_live_nhl_by_team_pair_with_espn_abbreviations(self) -> None:
        got = self._live("nhl", {"gamePk": "1"}, away_abbr="FLA", home_abbr="CBJ")
        self.assertEqual(got["away"], [0, 4, 2])
        got = self._live("nhl", {"gamePk": "2"}, away_abbr="UTA", home_abbr="NJD")
        self.assertEqual(got["labels"], ["1", "2", "3", "OT"])

    def test_nhl_shootout_is_labelled_so(self) -> None:
        got = self._live("nhl", {"gamePk": "4"}, away_abbr="BUF", home_abbr="MTL")
        self.assertEqual(got["labels"], ["1", "2", "3", "OT", "SO"])

    def test_live_unknown_game_has_no_line_score(self) -> None:
        self.assertIsNone(self._live("nhl", {"gamePk": "3"}, away_abbr="BOS", home_abbr="SJS"))


class ServedChipLineScores(unittest.TestCase):
    def test_worker_chips_get_live_line_scores_at_serve_time(self) -> None:
        from syndicate.features.shared import game_chip_scoreboard as gs

        chips = [{"sport": "nhl", "state": "live", "game_key": "1", "start_time_utc": "2026-10-14T00:00:00Z",
                  "away": {"abbr": "FLA", "score": "6"}, "home": {"abbr": "CBJ", "score": "2"}},
                 {"sport": "mlb", "state": "live", "game_key": "2", "away": {"abbr": "A"}, "home": {"abbr": "B"}},
                 {"sport": "nba", "state": "pregame", "game_key": "3", "away": {"abbr": "GSW"}, "home": {"abbr": "LAL"}}]
        board = {"401892489": {"away": "FLA", "home": "CBJ", "away_periods": [0, 4, 2], "home_periods": [1, 0, 1]}}
        gl._CACHE.clear()
        with mock.patch.object(gl, "_espn_board", return_value=board):
            gs.attach_served_linescores(chips, "2026-10-13")
        self.assertEqual(chips[0]["linescore"]["away"], [0, 4, 2])
        self.assertNotIn("linescore", chips[1])  # MLB waits for the worker's own build
        self.assertNotIn("linescore", chips[2])  # pregame


class NhlLiveClock(unittest.TestCase):
    BOARD = {"401": {"away": "COL", "home": "DAL", "away_periods": [1, 1], "home_periods": [1, 0], "period": 2, "clock": "11:26", "status_name": "STATUS_IN_PROGRESS"},
             "402": {"away": "MIN", "home": "WPG", "away_periods": [2, 0], "home_periods": [2, 1], "period": 2, "clock": "0:00", "status_name": "STATUS_END_PERIOD"}}

    def _serve(self, chip):
        from syndicate.features.shared import game_chip_scoreboard as gs

        gl._CACHE.clear()
        with mock.patch.object(gl, "_espn_board", return_value=self.BOARD):
            gs.attach_served_linescores([chip], "2026-10-13")
        return chip

    def test_live_nhl_gets_period_and_clock(self) -> None:
        chip = self._serve({"sport": "nhl", "state": "live", "game_key": "1", "status_token": "P2", "away": {"abbr": "COL"}, "home": {"abbr": "DAL"}})
        self.assertEqual(chip["status_token"], "P2 11:26")
        self.assertEqual(chip["linescore"]["away"], [1, 1])

    def test_intermission_reads_end_of_period(self) -> None:
        chip = self._serve({"sport": "nhl", "state": "live", "game_key": "1", "status_token": "P2", "away": {"abbr": "MIN"}, "home": {"abbr": "WPG"}})
        self.assertEqual(chip["status_token"], "END P2")

    def test_worker_built_clock_is_refreshed_not_kept(self) -> None:
        chip = self._serve({"sport": "nhl", "state": "live", "game_key": "1", "status_token": "P2 15:00",
                            "linescore": {"kind": "periods", "labels": ["1"], "away": [0], "home": [0]},
                            "away": {"abbr": "COL"}, "home": {"abbr": "DAL"}})
        self.assertEqual(chip["status_token"], "P2 11:26")
        self.assertEqual(chip["linescore"]["away"], [1, 1])


class BasketballBonus(unittest.TestCase):
    BOARD = {"401908621": {"id": "401908621", "away": "IND", "home": "OKC", "away_periods": [33, 28], "home_periods": [25, 34],
                           "period": 4, "clock": "7:57", "status_name": "STATUS_IN_PROGRESS"}}

    def _serve(self, fouls, situation="OKC on a 9–4 run"):
        from syndicate.features.shared import game_chip_scoreboard as gs

        chip = {"sport": "nba", "state": "live", "game_key": "401908621", "status_token": "Q4 7:57", "situation": situation,
                "away": {"abbr": "IND"}, "home": {"abbr": "OKC"}}
        gl._CACHE.clear()
        with mock.patch.object(gl, "_espn_board", return_value=self.BOARD), mock.patch.object(gl, "_espn_fouls", return_value=fouls):
            gs.attach_served_linescores([chip], "2026-10-13")
            gs.attach_served_linescores([chip], "2026-10-13")  # a second serve must not stack it
        return chip["situation"]

    def test_team_with_no_fouls_to_give_puts_the_opponent_in_bonus(self) -> None:
        got = self._serve({"away": {"foulsToGive": 0}, "home": {"foulsToGive": 2}})
        self.assertEqual(got, "OKC on a 9–4 run · OKC in bonus")

    def test_both_and_neither(self) -> None:
        self.assertEqual(self._serve({"away": {"foulsToGive": 0}, "home": {"foulsToGive": 0}}, situation=None), "both in bonus")
        self.assertEqual(self._serve({"away": {"foulsToGive": 3}, "home": {"foulsToGive": 1}}), "OKC on a 9–4 run")


class BasketballLiveClock(unittest.TestCase):
    def _serve(self, status_name, clock, token="Q4 7:57"):
        from syndicate.features.shared import game_chip_scoreboard as gs

        board = {"401908621": {"id": "401908621", "away": "IND", "home": "OKC", "away_periods": [33, 28, 23, 10], "home_periods": [25, 34, 26, 12],
                               "period": 4 if status_name != "STATUS_HALFTIME" else 2, "clock": clock, "status_name": status_name}}
        chip = {"sport": "nba", "state": "live", "game_key": "401908621", "status_token": token, "away": {"abbr": "IND"}, "home": {"abbr": "OKC"}}
        gl._CACHE.clear()
        with mock.patch.object(gl, "_espn_board", return_value=board), mock.patch.object(gl, "_espn_fouls", return_value={}):
            gs.attach_served_linescores([chip], "2026-10-13")
        return chip["status_token"]

    def test_stale_worker_clock_is_replaced(self) -> None:
        self.assertEqual(self._serve("STATUS_IN_PROGRESS", "5:40"), "Q4 5:40")

    def test_sub_minute_clock(self) -> None:
        self.assertEqual(self._serve("STATUS_IN_PROGRESS", "45.3", token="Q4 1:02"), "Q4 45.3")

    def test_halftime(self) -> None:
        self.assertEqual(self._serve("STATUS_HALFTIME", "0.0", token="Q2 0:00"), "HALF")


class MlbLive(unittest.TestCase):
    BOARD = {"849813": {"away": [1, 6, 1], "home": [3, 7, 0], "inning": 7, "state": "Bottom"}}

    def test_live_mlb_takes_statsapi_rhe_and_inning(self) -> None:
        from syndicate.features.shared import game_chip_scoreboard as gs

        chip = {"sport": "mlb", "state": "live", "game_key": "849813", "status_token": "TOP 7",
                "linescore": {"kind": "rhe", "labels": ["R", "H", "E"], "away": [0, 0, 0], "home": [0, 0, 0]},
                "away": {"abbr": "CLE", "score": "1"}, "home": {"abbr": "TB", "score": "3"}}
        gl._CACHE.clear()
        with mock.patch.object(gl, "_mlb_live_board", return_value=self.BOARD):
            gs.attach_served_linescores([chip], "2026-10-13")
        self.assertEqual(chip["status_token"], "BOT 7")
        self.assertEqual((chip["linescore"]["away"], chip["linescore"]["home"]), ([1, 6, 1], [3, 7, 0]))


if __name__ == "__main__":
    unittest.main()
