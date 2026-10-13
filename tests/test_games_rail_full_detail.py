"""Games-rail card footer and live detail (mockup 4, lane games-rail-full-detail)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from syndicate.features.shared import game_chip_detail as detail


def _footer(sport, game, start="2026-10-09T23:00:00+00:00", **names):
    return detail.pregame_footer(
        sport,
        game,
        away=names.get("away", "AWY"),
        home=names.get("home", "HME"),
        away_name=names.get("away_name", "Away Team"),
        home_name=names.get("home_name", "Home Team"),
        start_utc=datetime.fromisoformat(start),
    )


class PregameFooter(unittest.TestCase):
    def test_mlb_probables_and_favourite(self) -> None:
        game = {"probable": {"away": {"fullName": "Parker Messick"}, "home": {"fullName": "Shane Burke"}},
                "trackedGameLines": {"h2h": {"home_odds": "+105", "away_odds": "-120"}}}
        self.assertEqual(_footer("mlb", game, away="CLE", home="CWS"), "Messick vs Burke · CLE −120")

    def test_nba_spread_and_total(self) -> None:
        game = {"markets": {"spread": {"home": -3.5}, "total": {"line": 237.5}}}
        self.assertEqual(_footer("nba", game, away="MEM", home="CHI"), "CHI −3.5 · o/u 237.5")

    def test_nfl_thursday_is_tnf(self) -> None:
        game = {"betting": {"home_spread": -3, "total": 48.5}}
        # Thursday 2026-10-08 7:15 PM CT
        self.assertEqual(_footer("nfl", game, start="2026-10-09T00:15:00+00:00", away="TB", home="DAL"),
                         "TNF · DAL −3 · o/u 48.5")

    def test_underdog_home_spread_names_the_away_favourite(self) -> None:
        game = {"betting": {"home_spread": 6.5, "total": 42.5}}
        self.assertEqual(_footer("nfl", game, start="2026-10-11T17:00:00+00:00", away="CIN", home="MIA"),
                         "CIN −6.5 · o/u 42.5")

    def test_soccer_plus_money_favourite_is_not_named(self) -> None:
        game = {"markets": {"moneyline": {"home": 143, "away": 180}, "total": {"line": 2.5}}}
        self.assertEqual(_footer("soccer", game, away="CIN", home="ATL"), "o/u 2.5")

    def test_nothing_known_is_none_not_a_placeholder(self) -> None:
        self.assertIsNone(_footer("mlb", {"probable": {}, "trackedGameLines": {}}))


class LiveDetail(unittest.TestCase):
    def test_football_down_and_distance(self) -> None:
        game = {"live_state": {"game_shape": {"down": 3, "distance": 4, "possession_team": "DAL", "yard_line": "TB 38"}}}
        self.assertEqual(detail.live_detail("nfl", game), "DAL ball · 3rd & 4 · at TB 38")

    def test_mlb_runners_and_pitcher(self) -> None:
        game = {"live_state": {"linescore": {"outs": 1, "offense": {"first": {"id": 1}, "third": {"id": 2}},
                                             "defense": {"pitcher": {"fullName": "Parker Messick"}}},
                               "game_shape": {"pitcher_pitch_count": 94}}}
        self.assertEqual(detail.live_detail("mlb", game), "1 out · On 1st & 3rd · Messick 94p")

    def test_no_live_fields_is_none(self) -> None:
        self.assertIsNone(detail.live_detail("nba", {"live_state": {"status": "Q3 4:10"}}))

    def test_basketball_run_from_scoring_events(self) -> None:
        ev = lambda team, pts, i: {"type": "points", "team": team, "weight": pts, "possession_index": i}
        narrator = [ev("SAC", 3, 1), ev("LAL", 2, 2), ev("SAC", 2, 3), ev("LAL", 3, 4), ev("LAL", 2, 5), ev("LAL", 2, 6)]
        self.assertEqual(detail.basketball_run(narrator), ("LAL", 9, 2))
        self.assertIsNone(detail.basketball_run([ev("LAL", 2, 1), ev("SAC", 2, 2)]))

    def test_espn_situation_gives_possession_and_down_distance(self) -> None:
        game = {"live_state": {"espn_situation": {"downDistanceText": "1st & 10 at FSU 45", "possession": "52"},
                               "possession_side": "away"}}
        self.assertEqual(detail.live_detail("ncaaf", game, None, {"away": "FS", "home": "LOU"}),
                         "FS ball · 1st & 10 at FSU 45")

    def test_espn_clock_period_text_is_not_repeated_as_situation(self) -> None:
        from syndicate.features.shared.game_chip_scoreboard import _live_situation

        game = {"live_state": {"status": "8:34 - 1st"}}
        self.assertIsNone(_live_situation(game, "Q1 8:34"))


class BoardPlays(unittest.TestCase):
    """User 2026-10-09: "Lines now, props overnight"."""

    def _env(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        tmp = tempfile.mkdtemp()
        patch = mock.patch("syndicate.features.shared.game_chip_plays._reports_root", lambda: Path(tmp))
        patch.start()
        self.addCleanup(patch.stop)
        return Path(tmp)

    def test_lines_graded_at_final_props_from_overnight_results(self) -> None:
        from syndicate.features.shared import game_chip_plays as plays

        root = self._env()
        base = {"sport": "nfl", "away_key": "tampa bay buccaneers", "home_key": "dallas cowboys",
                "home_team": "Dallas Cowboys", "away_team": "Tampa Bay Buccaneers", "segment": "full"}
        cards = [
            dict(base, pick_id="a", kind="game", market="spreads", side="home", line=-3.0, ev_vs_fair_pct=2.0),   # DAL -3, lost 16-24
            dict(base, pick_id="b", kind="game", market="totals", side="over", line=38.5, ev_vs_fair_pct=1.5),   # 40 > 38.5 win
            dict(base, pick_id="c", kind="game", market="h2h", side="away", line=None, ev_vs_fair_pct=0.5),      # TB won
            dict(base, pick_id="d", kind="game", market="h2h", side="home", line=None, ev_vs_fair_pct=-1.0),     # not a play
            dict(base, pick_id="p1", kind="prop", market="Receiving Yards", side="over", line=60.5, ev_vs_fair_pct=3.0),
            dict(base, pick_id="p2", kind="prop", market="Receptions", side="under", line=4.5, ev_vs_fair_pct=1.0),
        ]
        chips = [{"sport": "nfl", "state": "final",
                  "away": {"key": "tampa bay buccaneers", "name": "Tampa Bay Buccaneers", "score": "24"},
                  "home": {"key": "dallas cowboys", "name": "Dallas Cowboys", "score": "16"}}]
        plays.write_pick_results("2026-10-08", [{"pick_id": "p1", "result": "win"}], reports_dir=root)
        plays.attach_plays(chips, "2026-10-08", cards=cards)
        got = chips[0]["plays"]
        self.assertEqual((got["total"], got["lines"], got["props"]), (5, 3, 2))
        self.assertEqual(got["line_results"], {"win": 2, "loss": 1, "push": 0, "pending": 0})
        self.assertEqual(got["prop_results"], {"win": 1, "loss": 0, "push": 0, "pending": 1})

    def test_record_survives_the_game_leaving_the_board(self) -> None:
        from syndicate.features.shared import game_chip_plays as plays

        self._env()
        card = {"sport": "nhl", "away_key": "a", "home_key": "b", "pick_id": "x", "kind": "game",
                "market": "totals", "side": "under", "line": 6.5, "segment": "full", "ev_vs_fair_pct": 1.0}
        plays.attach_plays([], "2026-10-08", cards=[card])           # seen while pregame
        chips = [{"sport": "nhl", "state": "final", "away": {"key": "a", "score": "2"}, "home": {"key": "b", "score": "3"}}]
        plays.attach_plays(chips, "2026-10-08", cards=[])              # board no longer has it
        self.assertEqual(chips[0]["plays"]["line_results"]["win"], 1)


    def test_a_game_is_filed_under_its_own_day(self) -> None:
        from syndicate.features.shared import game_chip_plays as plays

        self._env()
        card = {"sport": "ncaaf", "away_key": "ucf", "home_key": "ohio state", "pick_id": "y", "kind": "game",
                "market": "spreads", "side": "home", "line": -10.5, "segment": "full", "ev_vs_fair_pct": 1.0,
                "commence_time": "2026-10-10T16:00:00Z"}
        plays.attach_plays([], "2026-10-09", cards=[card])          # recorded by the 10-09 board
        chips = [{"sport": "ncaaf", "state": "pregame", "start_time_utc": "2026-10-10T16:00:00+00:00",
                  "away": {"key": "ucf"}, "home": {"key": "ohio state"}}]
        plays.attach_plays(chips, "2026-10-10")                     # found by the 10-10 card
        self.assertEqual(chips[0]["plays"]["total"], 1)

    def test_soccer_draw_loses_a_side_bet_and_corners_are_not_graded(self) -> None:
        from syndicate.features.shared import game_chip_plays as plays

        self._env()
        base = {"sport": "soccer", "away_key": "a", "home_key": "b", "kind": "game", "segment": "full", "ev_vs_fair_pct": 1.0}
        cards = [dict(base, pick_id="h", market="h2h", side="home", line=None),
                 dict(base, pick_id="d", market="h2h", side="draw", line=None),
                 dict(base, pick_id="y", market="btts", side="yes", line=None),
                 dict(base, pick_id="c", market="alternate_totals_corners", side="over", line=9.5)]
        chips = [{"sport": "soccer", "state": "final", "away": {"key": "a", "score": "1"}, "home": {"key": "b", "score": "1"}}]
        plays.attach_plays(chips, "2026-10-09", cards=cards)
        got = chips[0]["plays"]
        self.assertEqual(got["line_results"], {"win": 2, "loss": 1, "push": 0, "pending": 0})  # draw + BTTS win, home loses
        self.assertEqual((got["lines"], got["other"]), (3, 1))

    def test_pick_results_read_the_pick_id_inside_recommendation(self) -> None:
        from syndicate.features.shared import game_chip_plays as plays

        root = self._env()
        n = plays.write_pick_results("2026-10-10", [{"result": "win", "recommendation": {"pick_id": "l2_x"}},
                                                    {"result": "pending", "recommendation": {"pick_id": "l2_y"}}], reports_dir=root)
        self.assertEqual(n, 1)


class BookGridNextDay(unittest.TestCase):
    """An evening CT kickoff is priced in the NEXT date's soccer grid (2026-10-13)."""

    def _grid(self, root, day, rows):
        import json
        from pathlib import Path

        path = Path(root) / "soccer_source" / "data" / "book_grid"
        path.mkdir(parents=True, exist_ok=True)
        (path / f"book_grid_{day}.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")

    def _total(self, sport, line=3.5):
        return {"kind": "game", "segment": "full", "market": "totals", "line": line, "home_team": "Chicago Fire",
                "away_team": "Philadelphia Union", "consensus": {"over": -110, "under": -110}}

    def test_soccer_reads_the_next_utc_day(self) -> None:
        import tempfile
        from unittest import mock

        from syndicate.features.shared import game_chip_detail as gd

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
            self._grid(tmp, "2026-10-14", [])
            self._grid(tmp, "2026-10-15", [self._total("soccer")])
            got = gd._book_grid_main("soccer", "2026-10-14", "Chicago Fire", "Philadelphia Union")
            self.assertEqual(got["total"], 3.5)

    def test_other_sports_never_borrow_tomorrows_line(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from syndicate.features.shared import game_chip_detail as gd

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
            path = Path(tmp) / "mlb_source" / "data" / "book_grid"
            path.mkdir(parents=True)
            (path / "book_grid_2026-10-15.json").write_text(json.dumps({"rows": [self._total("mlb", 8.5)]}), encoding="utf-8")
            got = gd._book_grid_main("mlb", "2026-10-14", "Chicago Fire", "Philadelphia Union")
            self.assertIsNone(got["total"])


if __name__ == "__main__":
    unittest.main()


class SoccerUnplayedChip(unittest.TestCase):
    def test_void_match_reads_postponed_not_pregame(self) -> None:
        from syndicate.features.shared.game_chip_scoreboard import build_game_chip
        from syndicate.features.soccer.cards import _live_state_block
        from syndicate.features.soccer.ingestion.espn_lineups import UNPLAYED_STATE

        game = {"gamePk": "401882849", "league": "la_liga",
                "away": {"abbr": "ATH", "name": "Athletic Club"}, "home": {"abbr": "RAY", "name": "Rayo Vallecano"},
                "status": "Sat, Oct 10 - 7:00 AM CT", "scheduled_start_utc": "2026-10-10T12:00Z",
                "live_state": _live_state_block(UNPLAYED_STATE, "2026-10-10T12:00Z")}
        chip = build_game_chip("soccer", game)
        self.assertEqual(chip["status_token"], "PPD")
        self.assertNotEqual(chip["state"], "pregame")

    def test_played_states_carry_no_code(self) -> None:
        from syndicate.features.soccer.cards import _live_state_block

        self.assertNotIn("codedGameState", _live_state_block("pre", "2030-01-01T12:00Z"))


class FooterRoundsConsensusLines(unittest.TestCase):
    def _footer(self, sport, spread, total):
        from syndicate.features.shared import game_chip_detail as gd

        with __import__("unittest.mock").mock.patch.object(gd, "_market_lines", return_value={"home_ml": None, "away_ml": None, "home_spread": spread, "total": total}), \
                __import__("unittest.mock").mock.patch.object(gd, "_book_grid_main", return_value={}):
            return gd.pregame_footer(sport, {}, away="IND", home="OKC", away_name="Indiana Pacers", home_name="Oklahoma City Thunder", start_utc=None)

    def test_basketball_rounds_to_half_points(self) -> None:
        self.assertEqual(self._footer("nba", -9.6875, 228.062), "OKC −9.5 · o/u 228")

    def test_soccer_keeps_quarter_lines(self) -> None:
        self.assertIn("o/u 3.25", self._footer("soccer", None, 3.25))
