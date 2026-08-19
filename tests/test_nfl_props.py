from __future__ import annotations

import csv
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.nfl import player_stats
from syndicate.features.nfl import props


class NflPropsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.nfl_root = os.path.join(self._tmp.name, "nfl_source")
        os.makedirs(self.nfl_root, exist_ok=True)
        self._root_patch = patch.object(props, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        # player_stats.resolve_player_id also resolves its own source root
        # (for the pbp file, a separate lookup from the props CSV above) --
        # must be patched too, or these tests would fall through to the
        # real repo's production pbp_2025.csv (slow, non-hermetic).
        self._player_stats_root_patch = patch.object(player_stats, "default_nfl_source_root", return_value=Path(self.nfl_root))
        self._player_stats_root_patch.start()
        self.addCleanup(self._player_stats_root_patch.stop)
        props._nfl_raw_player_props.cache_clear()
        player_stats.load_player_plays.cache_clear()
        player_stats.player_name_index.cache_clear()
        player_stats._anytime_td_league_week_totals.cache_clear()

    def _write_pbp(self, season: int, rows: list[dict]) -> None:
        pbp_dir = os.path.join(self.nfl_root, "tracking", "nflverse", "pbp")
        os.makedirs(pbp_dir, exist_ok=True)
        fieldnames = [
            "game_id", "week", "season_type",
            "passer_player_id", "passer_player_name", "passing_yards", "pass_attempt", "pass_touchdown",
            "rusher_player_id", "rusher_player_name", "rushing_yards", "rush_attempt", "rush_touchdown",
            "receiver_player_id", "receiver_player_name", "receiving_yards", "complete_pass", "touchdown", "interception",
        ]
        with open(os.path.join(pbp_dir, f"pbp_{season}.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def _write_props(self, season: int, week: int, rows: list[dict]) -> None:
        fieldnames = ["player", "team", "market", "line", "over_price", "under_price", "book", "event", "game_time", "home_team", "away_team", "is_ladder"]
        path = os.path.join(self.nfl_root, f"oddsapi_player_props_{season}_wk{week}.csv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                full = {key: "" for key in fieldnames}
                full.update(row)
                writer.writerow(full)

    def test_missing_file_returns_empty(self) -> None:
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_header_only_stub_returns_empty(self) -> None:
        self._write_props(2025, 5, [])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_real_line_kept_even_without_resolvable_player_rate(self) -> None:
        # Unknown player -> resolve_player_id returns None -> no sim row,
        # but the real quoted line must still appear as an odds row.
        self._write_props(2025, 5, [
            {"player": "Totally Unknown Guy", "market": "Passing Yards", "line": "230.5", "over_price": "-110", "under_price": "-110", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(len(odds_rows), 2)
        self.assertEqual(sim_rows, [])

    def test_anytime_td_is_one_sided(self) -> None:
        self._write_props(2025, 5, [
            {"player": "Some Guy", "market": "Anytime TD", "line": "", "over_price": "250", "under_price": "", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, _sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(len(odds_rows), 1)
        self.assertEqual(odds_rows[0]["side"], "over")
        self.assertNotIn("line", odds_rows[0])

    def test_anytime_td_sim_row_uses_the_shrunk_rate_not_the_raw_zero(self) -> None:
        # `#471`: a player with a raw rolling mean of exactly 0.0 (2 games,
        # no TDs) used to project a literal 0% chance to score, in a
        # league that clearly does produce scores elsewhere. This is the
        # end-to-end wiring test -- nfl_props_rows_for_week must reach
        # anytime_td_rate, not player_rate, for this specific market.
        pbp_rows = []
        for week in ("1", "2"):
            game = f"2025_0{week}_KC_DEN"
            pbp_rows.append({"game_id": game, "week": week, "season_type": "REG", "rusher_player_id": "RB1", "rusher_player_name": "R.One", "rushing_yards": "3", "rush_attempt": "1"})
            pbp_rows.append({"game_id": game, "week": week, "season_type": "REG", "rusher_player_id": "RB2", "rusher_player_name": "R.Two", "rushing_yards": "4", "rush_attempt": "1", "rush_touchdown": "1", "touchdown": "1"})
        self._write_pbp(2025, pbp_rows)
        self._write_props(2025, 3, [
            {"player": "R. One", "market": "Anytime TD", "line": "", "over_price": "250", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        with patch.object(player_stats, "resolve_player_id", return_value="RB1"):
            _odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 3)
        self.assertEqual(len(sim_rows), 1)
        # Raw rate would be exactly 0.0 (2 scoreless games) -- the shrunk
        # rate must be strictly positive, pulled toward the league's own
        # observed rate (RB2 scored every week).
        self.assertGreater(sim_rows[0]["sim_projection"], 0.0)
        self.assertEqual(sim_rows[0]["projected_value"], sim_rows[0]["sim_projection"])

    def test_receiving_yards_and_interceptions_are_mapped(self) -> None:
        # Regression: both markets are fetched by
        # scripts/fetch_nfl_oddsapi_props_local.py (player_rec_yds /
        # player_interceptions) but had no entry in
        # _NFL_PROP_MARKET_TO_STAT until 2026-08-03 -- real rows for these
        # two markets were silently dropped exactly like an unmapped/unknown
        # market, never reaching the board.
        self._write_props(2025, 5, [
            {"player": "Some Receiver", "market": "Receiving Yards", "line": "55.5", "over_price": "-110", "under_price": "-110", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
            {"player": "Some Passer", "market": "Interceptions", "line": "0.5", "over_price": "+150", "under_price": "-180", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, _sim_rows = props.nfl_props_rows_for_week(2025, 5)
        stats = {props.nfl_prop_display_stat(row["market"]) for row in odds_rows}
        self.assertIn("receiving_yards", stats)
        self.assertIn("interceptions", stats)

    def test_unmapped_market_is_skipped(self) -> None:
        self._write_props(2025, 5, [
            {"player": "Some Guy", "market": "Some Unknown Market", "line": "1.5", "over_price": "-110", "under_price": "-110", "home_team": "New England Patriots", "away_team": "Seattle Seahawks"},
        ])
        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 5)
        self.assertEqual(odds_rows, [])
        self.assertEqual(sim_rows, [])

    def test_props_key_matches_away_home_pair(self) -> None:
        self.assertEqual(props.nfl_props_key("Seattle Seahawks", "New England Patriots"), "Seattle Seahawks|New England Patriots")

    def test_available_weeks_excludes_header_only_stubs(self) -> None:
        self._write_props(2025, 5, [])
        self._write_props(2025, 6, [
            {"player": "Some Guy", "market": "Anytime TD", "over_price": "250", "home_team": "A", "away_team": "B"},
        ])
        self.assertEqual(props.nfl_props_available_weeks(2025), [6])

    def test_model_probability_uses_hit_rate_for_anytime_td(self) -> None:
        prob = props._nfl_prop_model_probability(stat="anytime_td", mean=0.4, stdev=None, n=5, line=None)
        self.assertEqual(prob, 0.4)

    def test_model_probability_none_below_two_samples(self) -> None:
        prob = props._nfl_prop_model_probability(stat="passing_yards", mean=250.0, stdev=20.0, n=1, line=230.0)
        self.assertIsNone(prob)

    # ---- `#471` defect 1: Normal/log-normal blend ------------------------

    def test_lognormal_params_match_hand_computation(self) -> None:
        # variance=25, mean=10 -> sigma^2 = ln(1 + 25/100) = ln(1.25)
        import math
        mu, sigma = props._lognormal_params_from_moments(10.0, 5.0)
        expected_sigma_sq = math.log(1.25)
        self.assertAlmostEqual(sigma * sigma, expected_sigma_sq)
        self.assertAlmostEqual(mu, math.log(10.0) - expected_sigma_sq / 2.0)

    def test_lognormal_params_none_for_nonpositive_mean(self) -> None:
        self.assertIsNone(props._lognormal_params_from_moments(0.0, 5.0))
        self.assertIsNone(props._lognormal_params_from_moments(-1.0, 5.0))

    def test_lognormal_cover_probability_none_for_nonpositive_line(self) -> None:
        self.assertIsNone(props._lognormal_cover_probability(10.0, 5.0, 0.0))
        self.assertIsNone(props._lognormal_cover_probability(10.0, 5.0, -1.0))

    def test_model_probability_weight_zero_market_is_pure_normal(self) -> None:
        # interceptions and passing_tds are shipped at weight 0.0 -- the
        # OOS tune found no real benefit there. Must match the plain
        # Normal-CDF probability exactly, not just approximately (a
        # weight of 0.0 should short-circuit before any log-normal call).
        import statistics as stdlib_statistics
        mean, stdev, line = 1.2, 0.8, 1.5
        normal_only = 1.0 - stdlib_statistics.NormalDist(mean, stdev).cdf(line)
        self.assertEqual(props._COVER_PROBABILITY_BLEND_WEIGHT["interceptions"], 0.0)
        blended = props._nfl_prop_model_probability(stat="interceptions", mean=mean, stdev=stdev, n=5, line=line)
        self.assertEqual(blended, normal_only)

    def test_model_probability_weighted_market_differs_from_pure_normal(self) -> None:
        # rushing_yards ships at weight 0.573 (a real, non-trivial
        # correction) -- the blended probability must actually differ from
        # the pure-Normal one for a realistic right-skewed input, or the
        # wiring did nothing.
        self.assertGreater(props._COVER_PROBABILITY_BLEND_WEIGHT["rushing_yards"], 0.0)
        mean, stdev, line = 60.0, 30.0, 60.0  # line AT the mean -- exactly where the defect was measured
        import statistics as stdlib_statistics
        normal_only = 1.0 - stdlib_statistics.NormalDist(mean, stdev).cdf(line)
        blended = props._nfl_prop_model_probability(stat="rushing_yards", mean=mean, stdev=stdev, n=10, line=line)
        self.assertNotEqual(blended, normal_only)
        # A right-skewed distribution has P(X > mean) < 0.5 (mean sits
        # above the median) -- the blend should move the probability DOWN
        # from the Normal's exact 0.5 at line==mean, not up.
        self.assertAlmostEqual(normal_only, 0.5)
        self.assertLess(blended, 0.5)

    def test_model_probability_falls_back_to_normal_when_lognormal_undefined(self) -> None:
        # A market with a nonzero blend weight but a degenerate mean<=0
        # input (e.g. a mostly-non-rushing player's rushing_yards rate)
        # must still return the Normal-only probability, not None and not
        # crash -- mean<=0 is exactly the case _lognormal_params_from_
        # moments returns None for.
        blended = props._nfl_prop_model_probability(stat="rushing_yards", mean=0.0, stdev=3.0, n=5, line=5.0)
        import statistics as stdlib_statistics
        normal_only = 1.0 - stdlib_statistics.NormalDist(0.0, 3.0).cdf(5.0)
        self.assertEqual(blended, normal_only)

    def test_join_market_key_disambiguates_by_player(self) -> None:
        # Same bug class as MLB's hitter-RBI props (_mlb_prop_join_market_key):
        # every player sharing a market label must not collide in the join.
        key_a = props._nfl_prop_join_market_key("anytime_td", "Player One")
        key_b = props._nfl_prop_join_market_key("anytime_td", "Player Two")
        self.assertNotEqual(key_a, key_b)
        self.assertEqual(props.nfl_prop_display_stat(key_a), "anytime_td")
        self.assertEqual(props.nfl_prop_display_stat(key_b), "anytime_td")

    def test_two_players_same_market_never_flag_needs_resim(self) -> None:
        # Regression: before disambiguating the join market key, a player
        # with no resolvable rate would be misclassified as
        # unmatched_needs_resim (not unmatched_no_sim_coverage) purely
        # because a DIFFERENT player at the same game had sim coverage for
        # the same shared market label -- confirmed live on real 2025 wk22
        # data (Brady Russell / Efton Chism III) before this fix.
        from syndicate.features.shared.market_inventory import JOIN_STATUS_NEEDS_RESIM
        from syndicate.features.shared.market_inventory import join_odds_to_sim

        self._write_props(2025, 22, [
            {"player": "Has Rate Guy", "market": "Anytime TD", "over_price": "250", "home_team": "NE", "away_team": "SEA"},
            {"player": "No Rate Guy", "market": "Anytime TD", "over_price": "700", "home_team": "NE", "away_team": "SEA"},
        ])
        pbp_dir = os.path.join(self.nfl_root, "tracking", "nflverse", "pbp")
        os.makedirs(pbp_dir, exist_ok=True)
        fieldnames = ["game_id", "week", "season_type", "passer_player_id", "passer_player_name", "passing_yards", "pass_attempt", "pass_touchdown", "rusher_player_id", "rusher_player_name", "rushing_yards", "rush_attempt", "rush_touchdown", "receiver_player_id", "receiver_player_name", "receiving_yards", "complete_pass", "touchdown"]
        with open(os.path.join(pbp_dir, "pbp_2025.csv"), "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for week in (1, 2):
                writer.writerow({"game_id": f"2025_0{week}_X_Y", "week": str(week), "season_type": "REG", "rusher_player_id": "RATE1", "rusher_player_name": "H.Guy", "rushing_yards": "10", "rush_attempt": "1", "rush_touchdown": "1", "touchdown": "1"})

        odds_rows, sim_rows = props.nfl_props_rows_for_week(2025, 22)
        inventory = join_odds_to_sim(odds_rows, sim_rows)
        no_rate_rows = [row for row in inventory if row["entity"] == "No Rate Guy"]
        self.assertTrue(no_rate_rows)
        for row in no_rate_rows:
            self.assertNotEqual(row["join_status"], JOIN_STATUS_NEEDS_RESIM)


if __name__ == "__main__":
    unittest.main()
