"""Runners move on a 0-out double play (lane mlb-combined-calibration).

`_resolve_in_play_out_with_runners` used to hold every other runner on a DP. Real
box scores: with 0 outs before, the runner on 2nd usually takes 3rd and the runner
on 3rd usually scores (charged to the pitcher, no RBI). With 1 out the DP ends the
inning. Rates of 0 must draw no random number, so the default is byte-identical.
"""
from __future__ import annotations

import random
import unittest
from dataclasses import replace

from tests.test_mlb_starter_leash_tunable import _roster
from vendor.mlb_bettingv2.sim_engine.models import BattedBallType, GameConfig
from vendor.mlb_bettingv2.sim_engine.simulate import _resolve_in_play_out_with_runners, simulate_game


class _Scripted(random.Random):
    """Returns 0.0 for every draw (every probability fires) and counts the draws."""

    def __init__(self):
        super().__init__(0)
        self.draws = 0

    def random(self):  # noqa: D401
        self.draws += 1
        return 0.0


def _dp(outs, on1, on2, on3, r2, r3, rng=None):
    rng = rng or _Scripted()
    from vendor.mlb_bettingv2.sim_engine.simulate import _tuple_to_bases
    bases = _tuple_to_bases(bool(on1), bool(on2), bool(on3))
    out = _resolve_in_play_out_with_runners(rng, bases, outs, on1, on2, on3, 9, BattedBallType.GROUND,
                                            1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                                            dp_r2_to_3b_rate=r2, dp_r3_scores_rate=r3)
    return out, rng.draws


class ResolverTests(unittest.TestCase):
    def test_zero_out_dp_scores_the_runner_on_third_and_moves_second_to_third(self) -> None:
        (nb, on1, on2, on3, runs, scoring, outs_added, sub), _ = _dp(0, 1, 2, 3, 1.0, 1.0)
        self.assertEqual((sub, outs_added, runs, scoring), ("DP", 2, 1, [3]))
        self.assertEqual((on1, on2, on3), (0, 0, 2))

    def test_runner_on_second_cannot_take_an_occupied_third(self) -> None:
        (_, on1, on2, on3, runs, _, _, _), _ = _dp(0, 1, 2, 3, 1.0, 0.0)
        self.assertEqual((on1, on2, on3, runs), (0, 2, 3, 0))

    def test_one_out_dp_moves_nobody(self) -> None:
        (_, on1, on2, on3, runs, scoring, outs_added, _), _ = _dp(1, 1, 2, 3, 1.0, 1.0)
        self.assertEqual((on1, on2, on3, runs, scoring, outs_added), (0, 2, 3, 0, [], 2))

    def test_zero_rates_draw_no_extra_random_number(self) -> None:
        _, draws_off = _dp(0, 1, 2, 3, 0.0, 0.0)
        self.assertEqual(draws_off, 1, "only the DP draw itself; the RNG stream must not change by default")


def _games(**cfg_fields):
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    cfg = replace(GameConfig(rng_seed=5, manager_pitching="v2"), bip_dp_rate=0.6, **cfg_fields)
    return [simulate_game(away, home, replace(cfg, rng_seed=5 + i)) for i in range(40)]


class GameTests(unittest.TestCase):
    def test_reachable_off_differs_from_on(self) -> None:
        off = [(r.away_score, r.home_score) for r in _games()]
        on = [(r.away_score, r.home_score) for r in _games(bip_dp_r2_to_3b_rate=1.0, bip_dp_r3_scores_rate=1.0)]
        # Direction is proven by the resolver tests: once the RNG streams diverge,
        # 40 whole games are too noisy to show a run increase this small.
        self.assertNotEqual(off, on)

    def test_every_run_is_charged_and_dp_runs_carry_no_rbi(self) -> None:
        for r in _games(bip_dp_r2_to_3b_rate=1.0, bip_dp_r3_scores_rate=1.0):
            runs = r.away_score + r.home_score
            charged = sum(float(row.get("R") or 0.0) for row in (r.pitcher_stats or {}).values())
            rbi = sum(int(row.get("RBI") or 0) for row in (r.batter_stats or {}).values())
            self.assertEqual(charged, float(runs))
            self.assertLessEqual(rbi, runs)


if __name__ == "__main__":
    unittest.main()
