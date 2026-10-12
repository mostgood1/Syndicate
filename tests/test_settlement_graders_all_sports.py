"""Non-MLB settlement graders (lane settlement-graders-all-sports, 2026-10-12)."""

from __future__ import annotations

import unittest

from syndicate.features.shared import settlement_identity as si
from syndicate.features.shared import settlement_sport_rows as rows


def _markets_ok(*_args) -> bool:
    return True


def _pick(market, side, line, *, kind="prop", player=None, home="Dallas Cowboys", away="Tampa Bay Buccaneers",
          commence="2026-10-09T00:15:00Z", segment="full", event_id="oddsapi-hash"):
    rec = {"sport": "nfl", "market": market, "side": side, "line": line, "kind": kind, "segment": segment,
           "home_team": home, "away_team": away, "commence_time": commence, "event_id": event_id,
           "pick_id": "l2_test"}
    if player:
        rec.update({"player_name": player, "selection": player})
    return {"recommendation": rec, "result": "pending"}


def _nfl_rows(game_date="2026-10-08"):
    score = rows._score_row("nfl", "2026_05_TB_DAL", "DAL", "TB", 16.0, 24.0, "test", game_date=game_date)
    q1 = rows._score_row("nfl", "2026_05_TB_DAL", "DAL", "TB", 3.0, 7.0, "test", segment="q1", game_date=game_date)
    box = rows._box_row("nfl", "2026_05_TB_DAL", "DAL", "TB", [
        {"id": "00-1", "name": "Bucky Irving", "name_key": "bucky irving", "team": "TB",
         "player": {"rec": 3.0, "rec_yds": 21.0, "rush_yds": 54.0, "anytime_td": 1.0}},
    ], "test", game_date=game_date)
    return [score, q1, box]


class NflGrading(unittest.TestCase):
    def _grade(self, record, grows=None):
        out = si.find_graded_row(record, si.GradedRowIndex(grows or _nfl_rows()), sport="nfl", markets_compatible=_markets_ok)
        return (out.row or {}).get("result"), out.reason

    def test_prop_joins_by_fixture_across_id_namespaces(self) -> None:
        self.assertEqual(self._grade(_pick("Receptions", "over", 2.5, player="Bucky Irving")), ("win", None))
        self.assertEqual(self._grade(_pick("Rushing Yards", "under", 60.5, player="Bucky Irving")), ("win", None))

    def test_anytime_td_yes_no(self) -> None:
        self.assertEqual(self._grade(_pick("Anytime TD", "yes", None, player="Bucky Irving")), ("win", None))
        self.assertEqual(self._grade(_pick("Anytime TD", "no", None, player="Bucky Irving")), ("loss", None))

    def test_game_lines_and_quarters_grade_from_score_rows(self) -> None:
        self.assertEqual(self._grade(_pick("totals", "over", 38.5, kind="game")), ("win", None))
        self.assertEqual(self._grade(_pick("h2h", "away", None, kind="game")), ("win", None))
        self.assertEqual(self._grade(_pick("totals", "under", 9.5, kind="game", segment="q1")), ("loss", None))

    def test_same_clubs_on_another_day_do_not_join(self) -> None:
        later = _nfl_rows(game_date="2026-10-15")
        result, reason = self._grade(_pick("Receptions", "over", 2.5, player="Bucky Irving"), later)
        self.assertIsNone(result)

    def test_unmapped_market_refuses_by_name(self) -> None:
        mapped, refusal = si.prop_stat_for_record("nfl", _pick("Longest Reception", "over", 20.5, player="Bucky Irving"))
        self.assertIsNone(mapped)
        self.assertEqual(refusal, "prop_market_unmapped")


class NflSegments(unittest.TestCase):
    def test_quarters_and_halves_from_cumulative_ends(self) -> None:
        ends = {1: (3.0, 7.0), 2: (10.0, 14.0), 3: (13.0, 14.0), 4: (16.0, 24.0)}
        seg = rows._nfl_segment_scores(ends)
        self.assertEqual(seg["q1"], (3.0, 7.0))
        self.assertEqual(seg["q4"], (3.0, 10.0))
        self.assertEqual(seg["h1"], (10.0, 14.0))
        self.assertEqual(seg["h2"], (6.0, 10.0))

    def test_overtime_counts_in_the_second_half(self) -> None:
        ends = {1: (0.0, 0.0), 2: (7.0, 7.0), 3: (14.0, 14.0), 4: (21.0, 21.0), 5: (27.0, 21.0)}
        self.assertEqual(rows._nfl_segment_scores(ends)["h2"], (20.0, 14.0))

    def test_missing_quarter_gives_no_segments(self) -> None:
        self.assertEqual(rows._nfl_segment_scores({1: (0.0, 0.0), 2: (7.0, 7.0)}), {})


if __name__ == "__main__":
    unittest.main()
