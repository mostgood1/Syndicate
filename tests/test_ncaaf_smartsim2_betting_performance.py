from __future__ import annotations

import unittest

from syndicate.features.ncaaf.smartsim2_betting_performance import NET_PROFIT_PER_WIN
from syndicate.features.ncaaf.smartsim2_betting_performance import compute_ats_stats
from syndicate.features.ncaaf.smartsim2_betting_performance import compute_totals_stats
from syndicate.features.ncaaf.smartsim2_betting_performance import grade_ats_pick
from syndicate.features.ncaaf.smartsim2_betting_performance import grade_totals_pick
from syndicate.features.ncaaf.smartsim2_betting_performance import summarize_betting_performance


def _record(**overrides):
    base = dict(
        game_id="1",
        season=2025,
        week=1,
        home_team="Sam Houston",
        away_team="UNLV",
        conference_game=False,
        market_margin=3.0,
        market_total=55.0,
        engine_margin=3.0,
        engine_total=55.0,
        smartsim_margin=3.0,
        smartsim_total=55.0,
        consensus_margin=3.0,
        consensus_total=55.0,
        consensus_used_smartsim_margin=True,
        actual_margin=3.0,
        actual_total=55.0,
        side_disagreement=False,
        total_disagreement=False,
        large_mismatch=False,
    )
    base.update(overrides)
    return base


class GradeAtsPickTests(unittest.TestCase):
    def test_home_pick_wins_when_home_covers(self) -> None:
        # Source likes home more than market (market home margin 3, source projects 7) -> bets home.
        self.assertEqual(grade_ats_pick(7.0, 3.0, 10.0), "win")

    def test_home_pick_loses_when_home_fails_to_cover(self) -> None:
        self.assertEqual(grade_ats_pick(7.0, 3.0, 2.0), "loss")

    def test_away_pick_wins_when_away_covers(self) -> None:
        # Source likes home less than market -> bets away; away covers if actual margin < market margin.
        self.assertEqual(grade_ats_pick(-2.0, 3.0, -5.0), "win")

    def test_away_pick_loses_when_home_covers(self) -> None:
        self.assertEqual(grade_ats_pick(-2.0, 3.0, 10.0), "loss")

    def test_push_when_actual_equals_market(self) -> None:
        self.assertEqual(grade_ats_pick(7.0, 3.0, 3.0), "push")

    def test_no_pick_when_source_equals_market(self) -> None:
        self.assertEqual(grade_ats_pick(3.0, 3.0, 10.0), "no_pick")


class GradeTotalsPickTests(unittest.TestCase):
    def test_over_pick_wins(self) -> None:
        self.assertEqual(grade_totals_pick(60.0, 55.0, 58.0), "win")

    def test_over_pick_loses(self) -> None:
        self.assertEqual(grade_totals_pick(60.0, 55.0, 50.0), "loss")

    def test_under_pick_wins(self) -> None:
        self.assertEqual(grade_totals_pick(50.0, 55.0, 48.0), "win")

    def test_push(self) -> None:
        self.assertEqual(grade_totals_pick(60.0, 55.0, 55.0), "push")

    def test_no_pick(self) -> None:
        self.assertEqual(grade_totals_pick(55.0, 55.0, 60.0), "no_pick")


class ComputeAtsStatsTests(unittest.TestCase):
    def test_all_wins_perfect_record(self) -> None:
        rows = [
            _record(game_id="1", engine_margin=7.0, market_margin=3.0, actual_margin=10.0),
            _record(game_id="2", engine_margin=7.0, market_margin=3.0, actual_margin=10.0),
        ]
        stats = compute_ats_stats(rows, "engine")
        self.assertEqual(stats.wins, 2)
        self.assertEqual(stats.losses, 0)
        self.assertEqual(stats.win_pct, 100.0)
        self.assertAlmostEqual(stats.units_net, 2 * NET_PROFIT_PER_WIN, places=3)
        self.assertAlmostEqual(stats.roi_pct, 100.0 * NET_PROFIT_PER_WIN, places=1)

    def test_mixed_record_roi_and_win_pct(self) -> None:
        rows = [
            _record(game_id="1", engine_margin=7.0, market_margin=3.0, actual_margin=10.0),  # win
            _record(game_id="2", engine_margin=7.0, market_margin=3.0, actual_margin=-5.0),  # loss
        ]
        stats = compute_ats_stats(rows, "engine")
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.losses, 1)
        self.assertEqual(stats.win_pct, 50.0)
        self.assertAlmostEqual(stats.units_net, NET_PROFIT_PER_WIN - 1.0, places=3)
        self.assertLess(stats.roi_pct, 0)  # standard vig means breakeven at >50% required

    def test_pushes_excluded_from_win_pct_denominator(self) -> None:
        rows = [
            _record(game_id="1", engine_margin=7.0, market_margin=3.0, actual_margin=3.0),  # push
            _record(game_id="2", engine_margin=7.0, market_margin=3.0, actual_margin=10.0),  # win
        ]
        stats = compute_ats_stats(rows, "engine")
        self.assertEqual(stats.pushes, 1)
        self.assertEqual(stats.win_pct, 100.0)

    def test_none_when_no_market_margin(self) -> None:
        rows = [_record(market_margin=None)]
        self.assertIsNone(compute_ats_stats(rows, "engine"))

    def test_none_when_empty(self) -> None:
        self.assertIsNone(compute_ats_stats([], "engine"))


class ComputeTotalsStatsTests(unittest.TestCase):
    def test_basic_totals_grading(self) -> None:
        rows = [
            _record(game_id="1", engine_total=60.0, market_total=55.0, actual_total=58.0),  # over win
            _record(game_id="2", engine_total=50.0, market_total=55.0, actual_total=58.0),  # under loss
        ]
        stats = compute_totals_stats(rows, "engine")
        self.assertEqual(stats.wins, 1)
        self.assertEqual(stats.losses, 1)


class SummarizeBettingPerformanceTests(unittest.TestCase):
    def test_summarize_partitions_by_category(self) -> None:
        agree = _record(
            game_id="a", conference_game=True, side_disagreement=False, total_disagreement=False, large_mismatch=False,
            engine_margin=2.0, market_margin=2.0 - 0.01, actual_margin=5.0,
        )
        mismatch = _record(
            game_id="b", conference_game=False, side_disagreement=True, total_disagreement=True, large_mismatch=True,
            engine_margin=15.0, market_margin=12.0, actual_margin=20.0,
        )
        summary = summarize_betting_performance([agree, mismatch])
        self.assertEqual(summary["n_games"], 2)
        self.assertEqual(summary["large_mismatch"]["n"], 1)
        self.assertEqual(summary["conference_games"]["n"], 1)
        self.assertEqual(summary["non_conference_games"]["n"], 1)
        self.assertEqual(summary["side_disagreement"]["n"], 1)
        self.assertEqual(summary["total_disagreement"]["n"], 1)

    def test_summarize_handles_empty_input(self) -> None:
        summary = summarize_betting_performance([])
        self.assertEqual(summary["n_games"], 0)
        self.assertEqual(summary["overall"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
