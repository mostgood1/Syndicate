"""Tests for `historical_truth.player_game_rates` -- the boxscore per-skater parser and season
aggregator behind `scripts/build_nhl_player_rates_artifact.py`."""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (
    MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT, MIN_GAMES_FOR_PLAYER_WEIGHT, GamePlayerFaceoffRecord,
    build_player_game_dataset, compute_player_faceoff_aggregates, compute_player_rate_aggregates,
    parse_boxscore_player_rates, parse_playbyplay_player_faceoffs, parse_playbyplay_roster_names,
)


def _skater(player_id, name, sog=3, goals=1, blocks=0):
    return {"playerId": player_id, "name": {"default": name}, "sog": sog, "goals": goals,
            "blockedShots": blocks}


def _boxscore(*, forwards_home=None, defense_home=None, forwards_away=None, defense_away=None):
    return {
        "playerByGameStats": {
            "homeTeam": {"forwards": forwards_home or [], "defense": defense_home or []},
            "awayTeam": {"forwards": forwards_away or [], "defense": defense_away or []},
        },
    }


class ParseBoxscorePlayerRatesTest(unittest.TestCase):
    def test_parses_forwards_and_defense_both_sides(self) -> None:
        box = _boxscore(
            forwards_home=[_skater(1, "Home F1")], defense_home=[_skater(2, "Home D1")],
            forwards_away=[_skater(3, "Away F1")], defense_away=[_skater(4, "Away D1")],
        )
        recs = parse_boxscore_player_rates(box)
        self.assertEqual({r.player_id for r in recs}, {1, 2, 3, 4})
        by_id = {r.player_id: r for r in recs}
        self.assertEqual(by_id[1].position, "F")
        self.assertEqual(by_id[2].position, "D")

    def test_stat_values_carried_through(self) -> None:
        box = _boxscore(forwards_home=[_skater(1, "Star", sog=5, goals=2, blocks=1)])
        recs = parse_boxscore_player_rates(box)
        r = recs[0]
        self.assertEqual((r.shots, r.goals, r.blocks), (5, 2, 1))

    def test_missing_stats_default_to_zero(self) -> None:
        box = _boxscore(forwards_home=[{"playerId": 1, "name": {"default": "X"}}])
        recs = parse_boxscore_player_rates(box)
        self.assertEqual((recs[0].shots, recs[0].goals, recs[0].blocks), (0, 0, 0))

    def test_missing_player_id_skipped(self) -> None:
        box = _boxscore(forwards_home=[{"name": {"default": "NoId"}, "sog": 3}])
        self.assertEqual(parse_boxscore_player_rates(box), [])

    def test_not_a_dict_returns_empty(self) -> None:
        self.assertEqual(parse_boxscore_player_rates(None), [])

    def test_missing_player_by_game_stats_returns_empty(self) -> None:
        self.assertEqual(parse_boxscore_player_rates({}), [])

    def test_goalies_never_appear(self) -> None:
        # goalies live under a separate "goalies" key this parser never reads
        box = {"playerByGameStats": {"homeTeam": {"forwards": [], "defense": [],
                                                    "goalies": [_skater(9, "Netminder")]},
                                      "awayTeam": {"forwards": [], "defense": []}}}
        recs = parse_boxscore_player_rates(box)
        self.assertEqual(recs, [])


class BuildPlayerGameDatasetTest(unittest.TestCase):
    def test_flattens_across_payloads(self) -> None:
        p1 = _boxscore(forwards_home=[_skater(1, "A")])
        p2 = _boxscore(forwards_home=[_skater(2, "B")])
        recs = build_player_game_dataset([p1, p2])
        self.assertEqual({r.player_id for r in recs}, {1, 2})


class ComputePlayerRateAggregatesTest(unittest.TestCase):
    def _n_games(self, n, player_id=1, name="Star", sog=3, goals=1, blocks=0, position_home=True):
        recs = []
        for _ in range(n):
            box = _boxscore(forwards_home=[_skater(player_id, name, sog, goals, blocks)])
            recs.extend(parse_boxscore_player_rates(box))
        return recs

    def test_below_floor_is_omitted(self) -> None:
        recs = self._n_games(MIN_GAMES_FOR_PLAYER_WEIGHT - 1)
        agg = compute_player_rate_aggregates(recs)
        self.assertEqual(agg, {})

    def test_at_floor_is_included(self) -> None:
        recs = self._n_games(MIN_GAMES_FOR_PLAYER_WEIGHT)
        agg = compute_player_rate_aggregates(recs)
        self.assertIn(1, agg)

    def test_rate_is_per_game_average(self) -> None:
        recs = self._n_games(10, sog=4, goals=2, blocks=1)
        agg = compute_player_rate_aggregates(recs)[1]
        self.assertAlmostEqual(agg.shot_weight, 4.0)
        self.assertAlmostEqual(agg.goal_weight, 2.0)
        self.assertAlmostEqual(agg.block_weight, 1.0)
        self.assertEqual(agg.games, 10)

    def test_mixed_stat_games_average_correctly(self) -> None:
        recs = []
        recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X", sog=2, goals=0, blocks=0)])))
        recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X", sog=6, goals=2, blocks=0)])))
        recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X", sog=4, goals=1, blocks=0)])))
        recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X", sog=0, goals=0, blocks=0)])))
        recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X", sog=8, goals=1, blocks=0)])))
        agg = compute_player_rate_aggregates(recs)[1]
        self.assertAlmostEqual(agg.shot_weight, (2 + 6 + 4 + 0 + 8) / 5)

    def test_position_is_the_most_common_one(self) -> None:
        recs = []
        for _ in range(4):
            recs.extend(parse_boxscore_player_rates(_boxscore(forwards_home=[_skater(1, "X")])))
        recs.extend(parse_boxscore_player_rates(_boxscore(defense_home=[_skater(1, "X")])))
        agg = compute_player_rate_aggregates(recs)[1]
        self.assertEqual(agg.position, "F")

    def test_full_name_carried_through(self) -> None:
        recs = self._n_games(MIN_GAMES_FOR_PLAYER_WEIGHT, name="Connor Skater")
        agg = compute_player_rate_aggregates(recs)[1]
        self.assertEqual(agg.full_name, "Connor Skater")

    def test_empty_input(self) -> None:
        self.assertEqual(compute_player_rate_aggregates([]), {})


# ---------------------------------------------------------------------------
# Per-player faceoff win rate (§2zz) -- sourced from `playbyplay`, NOT the boxscore (see the
# module docstring for why: a naive per-game average of the boxscore's own `faceoffWinningPctg`
# is heavily biased by low-draw games).
# ---------------------------------------------------------------------------

def _faceoff_play(*, winner, loser):
    return {"typeDescKey": "faceoff", "details": {"winningPlayerId": winner, "losingPlayerId": loser}}


def _playbyplay(plays):
    return {"plays": plays}


class ParsePlaybyplayPlayerFaceoffsTest(unittest.TestCase):
    def test_winner_gets_a_win_and_a_draw_loser_gets_a_draw_only(self) -> None:
        payload = _playbyplay([_faceoff_play(winner=1, loser=2)])
        recs = {r.player_id: r for r in parse_playbyplay_player_faceoffs(payload)}
        self.assertEqual((recs[1].wins, recs[1].total), (1, 1))
        self.assertEqual((recs[2].wins, recs[2].total), (0, 1))

    def test_counts_accumulate_across_multiple_draws_same_game(self) -> None:
        payload = _playbyplay([
            _faceoff_play(winner=1, loser=2),
            _faceoff_play(winner=1, loser=3),
            _faceoff_play(winner=2, loser=1),
        ])
        recs = {r.player_id: r for r in parse_playbyplay_player_faceoffs(payload)}
        self.assertEqual((recs[1].wins, recs[1].total), (2, 3))  # 2 wins, 1 loss = 3 draws
        self.assertEqual((recs[2].wins, recs[2].total), (1, 2))
        self.assertEqual((recs[3].wins, recs[3].total), (0, 1))

    def test_non_faceoff_plays_ignored(self) -> None:
        payload = _playbyplay([{"typeDescKey": "shot-on-goal", "details": {"winningPlayerId": 1}}])
        self.assertEqual(parse_playbyplay_player_faceoffs(payload), [])

    def test_missing_winner_or_loser_skipped(self) -> None:
        payload = _playbyplay([{"typeDescKey": "faceoff", "details": {"winningPlayerId": 1}}])
        self.assertEqual(parse_playbyplay_player_faceoffs(payload), [])

    def test_missing_plays_returns_empty(self) -> None:
        self.assertEqual(parse_playbyplay_player_faceoffs({}), [])

    def test_not_a_dict_returns_empty(self) -> None:
        self.assertEqual(parse_playbyplay_player_faceoffs(None), [])


class ParsePlaybyplayRosterNamesTest(unittest.TestCase):
    def test_parses_name_and_position_from_roster_spots(self) -> None:
        payload = {"rosterSpots": [
            {"playerId": 1, "firstName": {"default": "Connor"}, "lastName": {"default": "Star"},
             "positionCode": "C"},
        ]}
        out = parse_playbyplay_roster_names(payload)
        self.assertEqual(out[1], ("Connor Star", "C"))

    def test_missing_roster_spots_returns_empty(self) -> None:
        self.assertEqual(parse_playbyplay_roster_names({}), {})

    def test_not_a_dict_returns_empty(self) -> None:
        self.assertEqual(parse_playbyplay_roster_names(None), {})


class ComputePlayerFaceoffAggregatesTest(unittest.TestCase):
    def _games(self, n, *, player_id=1, wins_per_game=6, total_per_game=10, name="Center X", pos="C"):
        recs = []
        names = []
        for _ in range(n):
            recs.append([GamePlayerFaceoffRecord(player_id=player_id, wins=wins_per_game, total=total_per_game)])
            names.append({player_id: (name, pos)})
        return recs, names

    def test_below_draw_floor_is_omitted(self) -> None:
        recs, names = self._games(1, total_per_game=MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT - 1)
        agg = compute_player_faceoff_aggregates(recs, names)
        self.assertEqual(agg, {})

    def test_at_draw_floor_is_included(self) -> None:
        recs, names = self._games(1, total_per_game=MIN_DRAWS_FOR_PLAYER_FACEOFF_WEIGHT)
        agg = compute_player_faceoff_aggregates(recs, names)
        self.assertIn(1, agg)

    def test_rate_is_true_win_total_ratio_not_average_of_per_game_rates(self) -> None:
        """The real bug this module's own design avoids: a player who goes 100/100 one game and
        0/100 the next has a TRUE rate of 0.5 (100 wins / 200 total) -- an average-of-per-game-
        rates approach would ALSO give 0.5 here (a case too symmetric to distinguish the two
        methods), so a second, asymmetric-volume case follows immediately below to actually
        discriminate. Both games are individually above the draw floor so this isolates the
        averaging behavior, not the floor."""
        recs = [
            [GamePlayerFaceoffRecord(player_id=1, wins=100, total=100)],
            [GamePlayerFaceoffRecord(player_id=1, wins=0, total=100)],
        ]
        names = [{1: ("X", "C")}, {1: ("X", "C")}]
        agg = compute_player_faceoff_aggregates(recs, names)[1]
        self.assertAlmostEqual(agg.faceoff_weight, 0.5)
        self.assertEqual(agg.draws, 200)

    def test_true_count_differs_from_average_of_rates_under_asymmetric_volume(self) -> None:
        """A player who takes 90 draws at a 60% rate (54 wins) in one game and 10 draws at a 0%
        rate (0 wins) in another: TRUE rate = 54/100 = 0.54. A naive average-of-per-game-RATES
        would instead give (0.6 + 0.0)/2 = 0.30 -- a real, large discrepancy, proving this
        function uses true counts, not an average of ratios."""
        recs = [
            [GamePlayerFaceoffRecord(player_id=1, wins=54, total=90)],
            [GamePlayerFaceoffRecord(player_id=1, wins=0, total=10)],
        ]
        names = [{1: ("X", "C")}, {1: ("X", "C")}]
        agg = compute_player_faceoff_aggregates(recs, names)[1]
        self.assertAlmostEqual(agg.faceoff_weight, 0.54)
        self.assertNotAlmostEqual(agg.faceoff_weight, 0.30, places=1)

    def test_zero_draw_games_do_not_crash_or_count_as_a_game(self) -> None:
        recs = [
            [GamePlayerFaceoffRecord(player_id=1, wins=0, total=0)],
            [GamePlayerFaceoffRecord(player_id=1, wins=60, total=100)],
        ]
        names = [{1: ("X", "C")}, {1: ("X", "C")}]
        agg = compute_player_faceoff_aggregates(recs, names)[1]
        self.assertEqual(agg.games, 1)  # the zero-draw game does not count

    def test_name_and_position_carried_through(self) -> None:
        recs, names = self._games(1, total_per_game=150, name="Connor Center", pos="C")
        agg = compute_player_faceoff_aggregates(recs, names)[1]
        self.assertEqual(agg.full_name, "Connor Center")
        self.assertEqual(agg.position, "C")

    def test_empty_input(self) -> None:
        self.assertEqual(compute_player_faceoff_aggregates([], []), {})


if __name__ == "__main__":
    unittest.main()
