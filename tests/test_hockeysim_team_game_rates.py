"""Tests for `historical_truth.team_game_rates` -- the boxscore(SOG)/play-by-play(faceoffs)
parser and season aggregator behind `scripts/build_nhl_team_rates_artifact.py`.

`blocks_per_60` was REMOVED from this module's scope (`docs/ai_context/hockeysim_engine_reference.md`
§2l) after being proven a confirmed dead gate -- `engine.py` never read it once populated. Block
volume is fully governed by the truth-calibrated per-shot `block_rate_*` mechanism instead
(`historical_truth/boxscore_block_rate.py`, still alive and tested separately)."""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.team_game_rates import (
    GameTeamRates, build_game_team_rates, compute_team_rate_aggregates,
    parse_boxscore_sog, parse_play_by_play_faceoffs,
)


def _boxscore(*, home_abbr="FLA", away_abbr="CHI", home_sog=30, away_sog=25, game_id="2025020001"):
    return {
        "id": game_id,
        "homeTeam": {"abbrev": home_abbr, "sog": home_sog},
        "awayTeam": {"abbrev": away_abbr, "sog": away_sog},
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


class ParseBoxscoreSogTest(unittest.TestCase):
    def test_parses_sog(self) -> None:
        rec = parse_boxscore_sog(_boxscore())
        self.assertEqual(rec["home_abbr"], "FLA")
        self.assertEqual(rec["away_abbr"], "CHI")
        self.assertEqual(rec["home_sog"], 30)
        self.assertEqual(rec["away_sog"], 25)

    def test_missing_sog_returns_none(self) -> None:
        box = _boxscore()
        del box["homeTeam"]["sog"]
        self.assertIsNone(parse_boxscore_sog(box))

    def test_not_a_dict_returns_none(self) -> None:
        self.assertIsNone(parse_boxscore_sog(None))


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
                home_sog=30, away_sog=25,
                home_faceoff_wins=35, away_faceoff_wins=30, faceoff_total=65,
            ),
            GameTeamRates(
                game_id="g2", home_abbr="CHI", away_abbr="FLA",
                home_sog=28, away_sog=32,
                home_faceoff_wins=28, away_faceoff_wins=32, faceoff_total=60,
            ),
        ]
        agg = compute_team_rate_aggregates(records)
        self.assertEqual(agg["FLA"].games, 2)
        self.assertAlmostEqual(agg["FLA"].shots_per_60, (30 + 32) / 2)
        # FLA faceoff wins: 35 (game1, home) + 32 (game2, away) = 67 / (65+60)=125 total
        self.assertAlmostEqual(agg["FLA"].faceoff_win_pct, 67 / 125, places=4)
        self.assertEqual(agg["CHI"].games, 2)
        self.assertAlmostEqual(agg["CHI"].shots_per_60, (25 + 28) / 2)

    def test_empty_input(self) -> None:
        agg = compute_team_rate_aggregates([])
        self.assertEqual(agg, {})

    def test_zero_faceoffs_falls_back_to_neutral(self) -> None:
        records = [GameTeamRates(
            game_id="g1", home_abbr="FLA", away_abbr="CHI",
            home_sog=30, away_sog=25,
            home_faceoff_wins=0, away_faceoff_wins=0, faceoff_total=0,
        )]
        agg = compute_team_rate_aggregates(records)
        self.assertEqual(agg["FLA"].faceoff_win_pct, 0.5)

    def test_aggregate_has_no_blocks_per_60_field(self) -> None:
        """Regression guard: `blocks_per_60` was removed from `TeamRateAggregate` (§2l) along with
        the `HockeyTeamFeatures`/`TeamRates` fields it used to feed."""
        records = [GameTeamRates(
            game_id="g1", home_abbr="FLA", away_abbr="CHI",
            home_sog=30, away_sog=25,
            home_faceoff_wins=1, away_faceoff_wins=1, faceoff_total=2,
        )]
        agg = compute_team_rate_aggregates(records)["FLA"]
        self.assertFalse(hasattr(agg, "blocks_per_60"))


if __name__ == "__main__":
    unittest.main()
