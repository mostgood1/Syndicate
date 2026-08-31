"""NCAAF: a fixture with no model, and WHICH kind of absence it is.

WHY THIS EXISTS. `games_indexed: 1` against `scheduled_games: 39` reads as a
broken join, and it is not one — the schedule has exactly one NCAAF game on
2026-08-30 (Memphis @ UNLV) and the projection matched it. The two numbers have
different denominators: one is the anchor date, the other the whole 7-day
window. I drew the wrong conclusion from that pair before probing it.

THE REAL BOUNDARY, measured over the whole of 2026 week 1:

    scheduled  99
    projected  51
    missing    48 of 48 are (fbs, fcs)
    projected  51 of 51 are (fbs, fbs)

`rating_source` is `cfbd_sp_plus_2026[...]`, and CFBD's SP+ covers FBS. An
FBS-vs-FCS fixture has no rating for one side and can never be projected, no
matter how healthy the pipeline is. Coverage of the RATEABLE population is
51/51 = 100%.

Without a stated reason those rows are indistinguishable from a failed
generation — and that failure is real and concurrent: a peer session found the
CFBD monthly quota exhausted the same week. So the string is not decoration; it
separates a permanent boundary from a live outage.
"""

from __future__ import annotations

import unittest

from syndicate.features.ncaaf.game_projections import (
    NcaafGameProjectionIndex,
    _unratable_reason,
    attach_ncaaf_game_projections,
)

DATE = "2026-09-05"


def _game(home_cls="fbs", away_cls="fcs", home="Kansas", away="Long Island University"):
    return {
        "homeTeam": home, "awayTeam": away,
        "homeClassification": home_cls, "awayClassification": away_cls,
        "startDate": f"{DATE}T18:00:00.000Z", "week": 1,
    }


def _row(home="Kansas", away="Long Island University", market="h2h"):
    return {
        "kind": "game", "market": market, "segment": "full",
        "commence_time": f"{DATE}T18:00:00Z",
        "home_team": home, "away_team": away,
        "sides": ["away", "home"], "consensus": {"home": -200, "away": 170},
    }


class TheReasonItself(unittest.TestCase):
    def test_fbs_versus_fcs_is_unratable_and_names_the_side(self):
        reason = _unratable_reason(_game(home_cls="fbs", away_cls="fcs"))
        self.assertIsNotNone(reason)
        self.assertIn("away team is FCS", reason)
        self.assertIn("FBS only", reason)
        self.assertIn("not by failure", reason,
                      "the string must separate a boundary from an outage")

    def test_the_side_is_read_from_the_data_not_assumed(self):
        reason = _unratable_reason(_game(home_cls="fcs", away_cls="fbs"))
        self.assertIn("home team is FCS", reason)

    def test_fbs_versus_fbs_is_rateable(self):
        self.assertIsNone(_unratable_reason(_game(home_cls="fbs", away_cls="fbs")))

    def test_an_absent_classification_is_NOT_called_unratable(self):
        """Conservative on purpose. An unknown reported as a stated boundary
        turns a data gap into a confident explanation — the exact failure this
        string exists to prevent."""
        for home_cls, away_cls in (("", "fcs"), ("fbs", ""), ("", "")):
            with self.subTest(home=home_cls, away=away_cls):
                self.assertIsNone(_unratable_reason(_game(home_cls=home_cls, away_cls=away_cls)))

    def test_a_classification_we_do_not_recognise_still_reports(self):
        """FCS is not the only non-FBS tier — division ii/iii and independents
        appear on openers too, and they are equally unrateable."""
        reason = _unratable_reason(_game(home_cls="fbs", away_cls="ii"))
        self.assertIsNotNone(reason)
        self.assertIn("away team is II", reason)


class TheAttachSeparatesTheTwoAbsences(unittest.TestCase):
    def _index(self, *games):
        index = NcaafGameProjectionIndex()
        for game in games:
            reason = _unratable_reason(game)
            if reason:
                key = (DATE, game["homeTeam"].lower(), game["awayTeam"].lower())
                index.unratable[key] = reason
        index.unratable_games = len(index.unratable)
        return index

    def test_an_unratable_row_is_counted_apart_from_a_real_miss(self):
        index = self._index(_game())
        grid = [_row()]
        coverage = attach_ncaaf_game_projections(grid, index)
        self.assertEqual(coverage["rows_unratable_opponent"], 1)
        self.assertEqual(coverage["rows_unmatched"], 0,
                         "an explicable absence is not an unexplained one")
        self.assertIn("FBS only", grid[0]["projection_absent_reason"])

    def test_an_fbs_row_with_no_projection_is_still_a_real_miss(self):
        """The counter must not become a catch-all that hides genuine gaps."""
        grid = [_row(home="Oklahoma", away="UTEP")]
        coverage = attach_ncaaf_game_projections(grid, self._index(_game()))
        self.assertEqual(coverage["rows_unmatched"], 1)
        self.assertEqual(coverage["rows_unratable_opponent"], 0)
        self.assertNotIn("projection_absent_reason", grid[0])

    def test_the_reason_is_NOT_inside_a_projection_dict(self):
        """`layer1_board` counts ANY `projection` dict as `rows_with_projection`,
        so putting the reason there would inflate coverage with rows that carry
        no model at all — improving the number that made this look broken while
        making the board less true."""
        grid = [_row()]
        attach_ncaaf_game_projections(grid, self._index(_game()))
        self.assertNotIn("projection", grid[0])
        self.assertIn("projection_absent_reason", grid[0])

    def test_coverage_reports_the_unratable_population_as_a_rate(self):
        index = self._index(_game(), _game(home="Minnesota", away="Eastern Illinois"))
        coverage = attach_ncaaf_game_projections([_row()], index)
        self.assertEqual(coverage["games_unratable_opponent"], 2)
        self.assertIn("games_indexed", coverage,
                      "the pair is what makes it readable as a rate")


if __name__ == "__main__":
    unittest.main()
