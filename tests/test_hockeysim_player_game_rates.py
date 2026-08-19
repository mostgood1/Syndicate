"""Tests for `historical_truth.player_game_rates` -- the boxscore per-skater parser and season
aggregator behind `scripts/build_nhl_player_rates_artifact.py`."""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.player_game_rates import (
    MIN_GAMES_FOR_PLAYER_WEIGHT, build_player_game_dataset, compute_player_rate_aggregates,
    parse_boxscore_player_rates,
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


if __name__ == "__main__":
    unittest.main()
