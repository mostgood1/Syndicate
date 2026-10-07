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
        # "off" is explicit: since 2026-10-07 the GameConfig defaults ARE the measured rates.
        off = [(r.away_score, r.home_score) for r in _games(bip_dp_r2_to_3b_rate=0.0, bip_dp_r3_scores_rate=0.0)]
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


def _fc_count(fc_rate):
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    cfg = replace(GameConfig(rng_seed=7, manager_pitching="v2", pbp="pa"), bip_fc_rate=fc_rate)
    return sum(1 for i in range(30) for ev in (simulate_game(away, home, replace(cfg, rng_seed=7 + i)).pbp or [])
               if ev.get("type") == "PA" and ev.get("result") == "FC")


class FieldersChoiceCeilingTests(unittest.TestCase):
    def test_fc_rate_above_the_old_0_2_ceiling_is_not_clamped(self) -> None:
        # The measured real rate is ~0.48; a 0.2 ceiling made 0.2 and 0.6 identical in expectation.
        lo, hi = _fc_count(0.2), _fc_count(0.6)
        self.assertGreater(lo, 0, "the fixture must produce fielder's choices")
        self.assertGreater(hi, 2 * lo)


def _sf(bb, flypop, pop):
    from vendor.mlb_bettingv2.sim_engine.simulate import _tuple_to_bases

    class _Draw(random.Random):
        def random(self):  # 0.5: fires only for a rate above 0.5
            return 0.5

    out = _resolve_in_play_out_with_runners(_Draw(0), _tuple_to_bases(False, False, True), 0, 0, 0, 3, 9, bb,
                                            0.0, flypop, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, sf_rate_pop=pop)
    return out[-1]


class PopupSacFlyTests(unittest.TestCase):
    def test_popups_use_their_own_rate_when_set(self) -> None:
        self.assertEqual(_sf(BattedBallType.POP, 0.9, 0.0), "OUT")
        self.assertEqual(_sf(BattedBallType.FLY, 0.9, 0.0), "SF")

    def test_unset_popup_rate_falls_back_to_the_pooled_rate(self) -> None:
        self.assertEqual(_sf(BattedBallType.POP, 0.9, None), "SF")


def _roe(bb, roe_rates):
    from vendor.mlb_bettingv2.sim_engine.simulate import _tuple_to_bases

    class _Draw(random.Random):
        def random(self):  # 0.02: fires only for a rate above 0.02
            return 0.02

    out = _resolve_in_play_out_with_runners(_Draw(0), _tuple_to_bases(False, False, False), 0, 0, 0, 0, 9, bb,
                                            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.012, 0.0, 0.0, 0.0, roe_rates=roe_rates)
    return out[-1]


class ReachedOnErrorTests(unittest.TestCase):
    def test_per_trajectory_rates_replace_base_times_multiplier(self) -> None:
        rates = {"ground": 0.028, "line": 0.006, "air": 0.003}
        self.assertEqual(_roe(BattedBallType.GROUND, rates), "ROE")   # 0.028 > 0.02
        self.assertEqual(_roe(BattedBallType.LINE, rates), "OUT")     # 0.006
        self.assertEqual(_roe(BattedBallType.FLY, rates), "OUT")      # 0.003

    def test_unset_rates_keep_base_times_multiplier(self) -> None:
        # 0.012 x 1.40 = 0.0168 < 0.02 -> no error; None everywhere is today's behaviour.
        self.assertEqual(_roe(BattedBallType.GROUND, {"ground": None, "line": None, "air": None}), "OUT")
        self.assertEqual(_roe(BattedBallType.GROUND, None), "OUT")


def _steal_totals(**cfg_fields):
    from tests.test_mlb_non_pa_outs import _stealing_roster
    away, home = _stealing_roster(1, "AWY", 100000), _stealing_roster(2, "HOM", 200000)
    cfg = replace(GameConfig(rng_seed=3, manager_pitching="v2"), **cfg_fields)
    sb = cs = 0
    for i in range(40):
        for row in (simulate_game(away, home, replace(cfg, rng_seed=3 + i)).batter_stats or {}).values():
            sb += int(row.get("SB") or 0)
            cs += int(row.get("CS") or 0)
    return sb, cs


class StolenBaseMultiplierTests(unittest.TestCase):
    def test_attempt_multiplier_cuts_attempts(self) -> None:
        sb0, cs0 = _steal_totals()
        sb1, cs1 = _steal_totals(sb_attempt_mult=0.3)
        self.assertLess(sb1 + cs1, 0.6 * (sb0 + cs0))

    def test_success_multiplier_shifts_the_success_share(self) -> None:
        sb0, cs0 = _steal_totals()
        sb1, cs1 = _steal_totals(sb_success_mult=2.0)  # 0.40 x 2 = 0.80, inside the 0.95 clamp
        self.assertGreater(sb1 / (sb1 + cs1), sb0 / (sb0 + cs0) + 0.2)


def _steal3_games(mult):
    from tests.test_mlb_non_pa_outs import _stealing_roster
    away, home = _stealing_roster(1, "AWY", 100000), _stealing_roster(2, "HOM", 200000)
    cfg = replace(GameConfig(rng_seed=21, manager_pitching="v2", pbp="pa"), sb3_attempt_mult=mult)
    return [simulate_game(away, home, replace(cfg, rng_seed=21 + i)) for i in range(40)]


class StealOfThirdTests(unittest.TestCase):
    def test_off_by_default_and_on_when_set(self) -> None:
        to3 = lambda games: [ev for r in games for ev in (r.pbp or []) if ev.get("to") == "3B" or  # noqa: E731
                             (ev.get("type") == "CS" and ev.get("to") == "3B")]
        self.assertEqual(to3(_steal3_games(0.0)), [])
        on = [ev for r in _steal3_games(1.0) for ev in (r.pbp or []) if ev.get("to") == "3B"]
        self.assertGreater(sum(1 for ev in on if ev["type"] == "SB"), 0)
        self.assertGreater(sum(1 for ev in on if ev["type"] == "CS"), 0, "the fixture must produce a CS of 3rd")

    def test_caught_stealing_third_is_the_pitchers_out(self) -> None:
        for r in _steal3_games(1.0):
            if r.home_score > r.away_score and len(r.home_inning_runs) == len(r.away_inning_runs):
                continue  # walk-off: the last half may end before 3 outs
            halves = len(r.away_inning_runs) + len(r.home_inning_runs)
            outs = sum(float(row.get("OUTS") or 0.0) for row in (r.pitcher_stats or {}).values())
            self.assertEqual(outs, 3.0 * halves)


def _double_steal_games(trail):
    from tests.test_mlb_non_pa_outs import _stealing_roster
    away, home = _stealing_roster(1, "AWY", 100000), _stealing_roster(2, "HOM", 200000)
    cfg = replace(GameConfig(rng_seed=31, manager_pitching="v2", pbp="pa"),
                  sb3_attempt_mult=1.0, sb_attempt_mult=0.0, sb_double_steal_trail_prob=trail)
    return [simulate_game(away, home, replace(cfg, rng_seed=31 + i)) for i in range(40)]


class DoubleStealTests(unittest.TestCase):
    def test_trailer_reaches_second_only_when_set(self) -> None:
        # sb_attempt_mult 0 disables the separate 2B steal, so any SB credited beyond the
        # steals of third can only come from a trailer on a double steal.
        def sb_vs_to3(games):
            sb = sum(int(row.get("SB") or 0) for r in games for row in (r.batter_stats or {}).values())
            to3 = sum(1 for r in games for ev in (r.pbp or []) if ev.get("type") == "SB" and ev.get("to") == "3B")
            return sb, to3
        sb_off, to3_off = sb_vs_to3(_double_steal_games(0.0))
        self.assertEqual(sb_off, to3_off)
        sb_on, to3_on = sb_vs_to3(_double_steal_games(1.0))
        self.assertGreater(sb_on, to3_on)

    def test_pitcher_outs_still_three_per_half_inning(self) -> None:
        for r in _double_steal_games(1.0):
            if r.home_score > r.away_score and len(r.home_inning_runs) == len(r.away_inning_runs):
                continue
            halves = len(r.away_inning_runs) + len(r.home_inning_runs)
            outs = sum(float(row.get("OUTS") or 0.0) for row in (r.pitcher_stats or {}).values())
            self.assertEqual(outs, 3.0 * halves)


if __name__ == "__main__":
    unittest.main()
