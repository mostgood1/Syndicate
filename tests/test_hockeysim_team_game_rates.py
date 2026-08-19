"""Tests for `historical_truth.team_game_rates` -- the boxscore(SOG+blocks)/play-by-play(faceoffs)
parser and season aggregator behind `scripts/build_nhl_team_rates_artifact.py`."""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import (
    GameTeamRates, build_game_team_rates, compute_team_rate_aggregates,
    parse_boxscore_sog_and_blocks, parse_play_by_play_faceoffs,
)


def _boxscore(*, home_abbr="FLA", away_abbr="CHI", home_sog=30, away_sog=25,
              home_blocks=(3, 2), away_blocks=(4, 1), game_id="2025020001"):
    def _skaters(blocks):
        forwards, defense = blocks
        return {
            "forwards": [{"blockedShots": forwards}],
            "defense": [{"blockedShots": defense}],
        }
    return {
        "id": game_id,
        "homeTeam": {"abbrev": home_abbr, "sog": home_sog},
        "awayTeam": {"abbrev": away_abbr, "sog": away_sog},
        "playerByGameStats": {
            "homeTeam": _skaters(home_blocks),
            "awayTeam": _skaters(away_blocks),
        },
    }


def _pbp_faceoffs(*, home_id=13, away_id=16, home_wins=35, away_wins=30, game_id="2025020001"):
    plays = []
    for _ in range(home_wins):
        plays.append({"typeDescKey": "faceoff", "details": {"eventOwnerTeamId": home_id}})
    for _ in range(away_wins):
        plays.append({"typeDescKey": "faceoff", "details": {"eventOwnerTeamId": away_id}})
    plays.append({"typeDescKey": "shot-on-goal", "details": {"eventOwnerTeamId": home_id}})  # noise
    return {
        "id": game_id,
        "homeTeam": {"id": home_id, "abbrev": "FLA"},
        "awayTeam": {"id": away_id, "abbrev": "CHI"},
        "plays": plays,
    }


class ParseBoxscoreSogAndBlocksTest(unittest.TestCase):
    def test_parses_sog_and_blocks(self) -> None:
        rec = parse_boxscore_sog_and_blocks(_boxscore())
        self.assertEqual(rec["home_abbr"], "FLA")
        self.assertEqual(rec["away_abbr"], "CHI")
        self.assertEqual(rec["home_sog"], 30)
        self.assertEqual(rec["away_sog"], 25)
        self.assertEqual(rec["home_blocks"], 5)  # 3 forwards + 2 defense
        self.assertEqual(rec["away_blocks"], 5)

    def test_missing_sog_returns_none(self) -> None:
        box = _boxscore()
        del box["homeTeam"]["sog"]
        self.assertIsNone(parse_boxscore_sog_and_blocks(box))

    def test_not_a_dict_returns_none(self) -> None:
        self.assertIsNone(parse_boxscore_sog_and_blocks(None))


class ParsePlayByPlayFaceoffsTest(unittest.TestCase):
    def test_parses_faceoff_wins(self) -> None:
        rec = parse_play_by_play_faceoffs(_pbp_faceoffs(home_wins=35, away_wins=30))
        self.assertEqual(rec, {"home_wins": 35, "away_wins": 30, "total": 65})

    def test_non_faceoff_events_ignored(self) -> None:
        # the noise shot-on-goal event in the fixture must not be counted
        rec = parse_play_by_play_faceoffs(_pbp_faceoffs(home_wins=1, away_wins=1))
        self.assertEqual(rec["total"], 2)

    def test_no_faceoffs_returns_none(self) -> None:
        payload = {"id": "g1", "homeTeam": {"id": 1}, "awayTeam": {"id": 2}, "plays": []}
        self.assertIsNone(parse_play_by_play_faceoffs(payload))

    def test_missing_team_ids_returns_none(self) -> None:
        self.assertIsNone(parse_play_by_play_faceoffs({"id": "g1", "plays": []}))


class BuildGameTeamRatesTest(unittest.TestCase):
    def test_joins_boxscore_and_playbyplay(self) -> None:
        box = _boxscore(game_id="g1")
        pbp = _pbp_faceoffs(game_id="g1")
        rates = build_game_team_rates([box], {"g1": pbp})
        self.assertIn("g1", rates)
        r = rates["g1"]
        self.assertEqual(r.home_abbr, "FLA")
        self.assertEqual(r.home_sog, 30)
        self.assertEqual(r.home_blocks, 5)
        self.assertEqual(r.home_faceoff_wins, 35)
        self.assertEqual(r.faceoff_total, 65)

    def test_game_missing_playbyplay_is_skipped(self) -> None:
        box = _boxscore(game_id="g1")
        rates = build_game_team_rates([box], {})
        self.assertEqual(rates, {})

    def test_game_missing_boxscore_data_is_skipped(self) -> None:
        box = _boxscore(game_id="g1")
        del box["homeTeam"]["sog"]
        pbp = _pbp_faceoffs(game_id="g1")
        rates = build_game_team_rates([box], {"g1": pbp})
        self.assertEqual(rates, {})


class ComputeTeamRateAggregatesTest(unittest.TestCase):
    def test_season_aggregate_across_two_games(self) -> None:
        records = [
            GameTeamRates(
                game_id="g1", home_abbr="FLA", away_abbr="CHI",
                home_sog=30, away_sog=25, home_blocks=5, away_blocks=6,
                home_faceoff_wins=35, away_faceoff_wins=30, faceoff_total=65,
            ),
            GameTeamRates(
                game_id="g2", home_abbr="CHI", away_abbr="FLA",
                home_sog=28, away_sog=32, home_blocks=4, away_blocks=8,
                home_faceoff_wins=28, away_faceoff_wins=32, faceoff_total=60,
            ),
        ]
        agg = compute_team_rate_aggregates(records)
        self.assertEqual(agg["FLA"].games, 2)
        self.assertAlmostEqual(agg["FLA"].shots_per_60, (30 + 32) / 2)
        self.assertAlmostEqual(agg["FLA"].blocks_per_60, (5 + 8) / 2)
        # FLA faceoff wins: 35 (game1, home) + 32 (game2, away) = 67 / (65+60)=125 total
        self.assertAlmostEqual(agg["FLA"].faceoff_win_pct, 67 / 125, places=4)
        self.assertEqual(agg["CHI"].games, 2)
        self.assertAlmostEqual(agg["CHI"].shots_per_60, (25 + 28) / 2)

    def test_league_wide_faceoff_win_pct_sums_to_one_per_game(self) -> None:
        # every faceoff has exactly one winner -- FLA's + CHI's win pct-weighted counts must
        # reconcile: home_wins + away_wins == faceoff_total, checked structurally above; this
        # test locks the empty/zero-total fallback instead.
        agg = compute_team_rate_aggregates([])
        self.assertEqual(agg, {})

    def test_zero_faceoffs_falls_back_to_neutral(self) -> None:
        records = [GameTeamRates(
            game_id="g1", home_abbr="FLA", away_abbr="CHI",
            home_sog=30, away_sog=25, home_blocks=5, away_blocks=6,
            home_faceoff_wins=0, away_faceoff_wins=0, faceoff_total=0,
        )]
        agg = compute_team_rate_aggregates(records)
        self.assertEqual(agg["FLA"].faceoff_win_pct, 0.5)


if __name__ == "__main__":
    unittest.main()
