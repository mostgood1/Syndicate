"""The live-lens snapshot is a PROJECTION set, not a pick list.

`_select_bounded_live_side` is a bet selector -- two-way price, non-favourite
(`max_favorite_odds=-200`), projection clear of the line by 0.08/0.18, market
edge over 0.05/0.03. Every row it rejected was dropped from the live-lens
snapshot, and the betting board consumes that snapshot as its source of live
projections. Measured on the served board 2026-08-15 20:12:48Z: 57 of 638 live
rows (8.9%) carried one; `batter_home_runs` 0 of 116; `batter_hits_runs_rbis`
0 of 79.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.features.mlb import cards
from syndicate.features.mlb.cards import (
    _LIVE_HITTER_MARKET_KEYS,
    _MLB_HITTER_PROP_DIST_CONFIG,
    _actual_hitter_stat_value,
    _current_live_pitcher_prop_rows,
    _synth_live_hitter_prop_rows,
)


class MarketTableAgreementTests(unittest.TestCase):
    def test_every_emitted_hitter_market_can_be_priced(self):
        # The two tables are the same fact. `batter_hits_runs_rbis` was in the
        # dist config and not in the emitter's key table, so the sim could price
        # a market the live rail never emitted a row for -- 0 of 79 on the board.
        for _prop_key, (market_key, _label) in _LIVE_HITTER_MARKET_KEYS.items():
            with self.subTest(market=market_key):
                self.assertIn(market_key, _MLB_HITTER_PROP_DIST_CONFIG)

    def test_hits_runs_rbis_is_emitted(self):
        self.assertEqual(
            _LIVE_HITTER_MARKET_KEYS.get("hits_runs_rbis"),
            ("batter_hits_runs_rbis", "Hits+Runs+RBIs"),
        )

    def test_every_emitted_hitter_market_has_a_live_actual_reader(self):
        # A market with no box-score reader projects but can never bank an
        # actual, which is the shape that produced a projection below a recorded
        # value on the pitcher side.
        stats = {"hits": 1, "runs": 1, "rbi": 2, "totalBases": 3, "homeRuns": 0}
        for prop_key in _LIVE_HITTER_MARKET_KEYS:
            with self.subTest(prop=prop_key):
                self.assertIsNotNone(_actual_hitter_stat_value(stats, prop_key))


class CompositeActualTests(unittest.TestCase):
    def test_hits_runs_rbis_sums_its_three_legs(self):
        self.assertEqual(
            _actual_hitter_stat_value({"hits": 1, "runs": 1, "rbi": 2}, "hits_runs_rbis"),
            4.0,
        )

    def test_a_partial_box_score_sums_what_is_present(self):
        # Returning None because one leg is absent would report "nothing banked"
        # for a hitter who already has a hit -- wrong direction on a market whose
        # whole point is that it clears easily.
        self.assertEqual(_actual_hitter_stat_value({"hits": 2}, "hits_runs_rbis"), 2.0)

    def test_no_legs_at_all_is_none_not_zero(self):
        self.assertIsNone(_actual_hitter_stat_value({"atBats": 3}, "hits_runs_rbis"))


def _hitter_sim():
    return {
        "hitter_props": {
            "1": {
                "name": "Kyle Tucker",
                "team_side": "home",
                "lineup_order": 3,
                "pa_mean": 4.2,
                "ab_mean": 3.8,
                "hr_mean": 0.15,
                "home_runs_dist": {"0": 85, "1": 14, "2": 1},
            }
        }
    }


def _hitter_actual():
    return {
        "gameData": {"teams": {"away": {"abbreviation": "STL"}, "home": {"abbreviation": "CHC"}}},
        "liveData": {
            "linescore": {"currentInning": 4, "inningHalf": "top", "outs": 1},
            "boxscore": {
                "teams": {
                    "away": {"players": {}},
                    "home": {
                        "players": {
                            "ID1": {
                                "person": {"id": 1, "fullName": "Kyle Tucker"},
                                "battingOrder": "300",
                                "stats": {"batting": {"atBats": 2, "hits": 1, "runs": 0, "rbi": 0, "homeRuns": 0}},
                            }
                        }
                    },
                }
            },
        },
    }


# A home-run market priced the way books actually price it: the over is a
# longshot the projection sits well under, and the under is past the -200
# favourite cap. The bet selector rejects BOTH sides, every time.
_HR_LINES = {"kyle tucker": {"batter_home_runs": {"line": 0.5, "over_odds": 320, "under_odds": -420}}}


class ProjectionOnlyHitterRowsTests(unittest.TestCase):
    def _rows(self, *, include_projection_only):
        with patch.object(cards, "_hitter_snapshot_market_lines", return_value=_HR_LINES):
            return _synth_live_hitter_prop_rows(
                "2026-08-15", 824644, _hitter_sim(), _hitter_actual(), [],
                include_projection_only=include_projection_only,
            )

    def test_the_pick_selector_rejects_the_home_run_row(self):
        # The baseline. 0 of 116 on the board, reproduced.
        self.assertEqual(self._rows(include_projection_only=False), [])

    def test_the_projection_survives_when_asked_for(self):
        rows = self._rows(include_projection_only=True)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["prop"], "home_runs")
        self.assertTrue(row["projection_only"])
        self.assertIsNotNone(row["live_projection"])
        self.assertIsNotNone(row["model_prob_over"])

    def test_a_projection_only_row_carries_no_bet(self):
        # Null, not zero: a consumer must not read "no pick here" as "a pick
        # with no edge". Zeroed pricing fields would rank as a live 0.0% edge.
        row = self._rows(include_projection_only=True)[0]
        self.assertIsNone(row["selection"])
        self.assertIsNone(row["edge"])
        self.assertIsNone(row["live_edge"])
        self.assertTrue(row["projection_only_reason"])

    def test_a_projection_only_row_is_not_given_a_ranking_score(self):
        scored = cards._apply_source_live_prop_ranking_scores(self._rows(include_projection_only=True))
        self.assertIsNone(scored[0].get("ranking_score"))


def _pitcher_sim():
    return {
        "pitcher_props": {
            "571510": {
                "so_mean": 5.4, "so_dist": {"2": 20, "5": 50, "8": 30},
                "outs_mean": 17.0, "outs_dist": {"12": 30, "18": 70},
                "er_mean": 3.2, "earned_runs_dist": {"2": 50, "4": 50},
                "hits_mean": 5.1, "hits_dist": {"4": 50, "6": 50},
                "walks_mean": 2.0, "walks_dist": {"1": 50, "3": 50},
            }
        }
    }


def _pitcher_actual(*, earned_runs, removed):
    home_players = {
        "ID571510": {
            "person": {"id": 571510, "fullName": "Matthew Boyd"},
            "stats": {"pitching": {"outs": 16, "inningsPitched": "5.1", "strikeOuts": 2, "earnedRuns": earned_runs, "hits": 5, "baseOnBalls": 3}},
        }
    }
    if removed:
        home_players["ID663423"] = {
            "person": {"id": 663423, "fullName": "Trent Thornton"},
            "stats": {"pitching": {"outs": 2, "inningsPitched": "0.2", "strikeOuts": 1, "earnedRuns": 0, "hits": 0, "baseOnBalls": 0}},
        }
    return {
        "gameData": {
            "probablePitchers": {"home": {"id": 571510, "fullName": "Matthew Boyd"}},
            "teams": {"away": {"abbreviation": "STL"}, "home": {"abbreviation": "CHC"}},
        },
        "liveData": {
            "linescore": {"currentInning": 7, "inningHalf": "top", "outs": 0},
            "boxscore": {"teams": {"away": {"players": {}}, "home": {"players": home_players}}},
        },
    }


_ER_LINES = {"matthew boyd": {"earned_runs": {"line": 2.5, "over_odds": 110, "under_odds": -130}}}


class SettledPitcherRowTests(unittest.TestCase):
    """Boyd sat on 7 earned runs against a 2.5 line and the board went on
    showing his pregame 3.242, because the row was skipped outright."""

    def _rows(self, *, include_projection_only, earned_runs=7, removed=True):
        with patch.object(cards, "_pitcher_snapshot_market_lines", return_value=_ER_LINES):
            return _current_live_pitcher_prop_rows(
                "2026-08-15", _pitcher_sim(), _pitcher_actual(earned_runs=earned_runs, removed=removed),
                include_projection_only=include_projection_only,
            )

    def test_a_decided_market_is_skipped_by_the_pick_path(self):
        self.assertEqual(self._rows(include_projection_only=False), [])

    def test_a_decided_market_still_yields_a_projection(self):
        rows = self._rows(include_projection_only=True)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["projection_only"])
        self.assertIn("already decided", rows[0]["projection_only_reason"])

    def test_the_projection_settles_to_the_actual_for_a_pulled_starter(self):
        # The whole point: 7 earned runs banked, pitcher gone, so the projection
        # is 7 -- not the pregame 3.2 and not something between them.
        rows = self._rows(include_projection_only=True)
        self.assertEqual(rows[0]["live_projection"], 7.0)
        self.assertEqual(rows[0]["actual_so_far"], 7.0)


if __name__ == "__main__":
    unittest.main()


class PulledStarterSurvivesTheRailFilterTests(unittest.TestCase):
    """`_live_pitcher_prop_row_actionable` drops every row for a starter who has
    left the game. Correct for a pick rail, and exactly why Boyd had no live row
    while the board kept showing his pregame 4.057 strikeouts against an actual 2.
    Without the bypass the settle-to-actual fix is INERT in the snapshot path."""

    def _computed(self, *, removed):
        actual = _pitcher_actual(earned_runs=1, removed=removed)
        actual["gameData"]["status"] = {"abstractGameState": "Live", "detailedState": "In Progress"}
        with patch.object(cards, "_pitcher_snapshot_market_lines", return_value=_ER_LINES), \
             patch.object(cards, "_registry_live_prop_rows", return_value=[]), \
             patch.object(cards, "_synth_live_hitter_prop_rows", return_value=[]), \
             patch.object(cards, "central_today_iso", return_value="2026-08-15"):
            return cards._live_prop_rows_computed(
                "2026-08-15", 824644, _pitcher_sim(), actual, None,
                include_projection_only=True,
            )

    def test_the_row_survives_when_the_starter_has_been_pulled(self):
        rows = self._computed(removed=True)
        self.assertEqual([r["prop"] for r in rows], ["earned_runs"])
        self.assertTrue(rows[0]["projection_only"])

    def test_a_starter_still_pitching_is_unaffected(self):
        rows = self._computed(removed=False)
        self.assertEqual([r["prop"] for r in rows], ["earned_runs"])
