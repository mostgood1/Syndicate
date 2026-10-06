"""Caught-stealing outs belong to the pitcher on the mound (lane mlb-non-pa-outs).

The pre-PA steal block in `simulate.py` adds a caught-stealing out to the
inning (`half.outs += 1`) but never to the pitcher's `OUTS`. Real box scores
count it in the pitcher's innings pitched, and outs props settle on that.

The invariant: in a game that does not end on a walk-off, every half-inning ends
on its third out, so the outs credited to the pitchers equal 3 x the half-innings
played. The harness forces many steal attempts with a low success rate, so the
invariant is exercised -- `test_the_fixture_actually_produces_caught_stealing`
proves it, or a passing invariant would be vacuous.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from tests.test_mlb_starter_leash_tunable import _roster
from vendor.mlb_bettingv2.sim_engine.models import GameConfig
from vendor.mlb_bettingv2.sim_engine.simulate import simulate_game

N = 60


def _stealing_roster(team_id, abbr, base):
    r = _roster(team_id, abbr, base)
    bats = [replace(b, sb_attempt_rate=0.40, sb_success_rate=0.40) for b in r.lineup.batters]
    return replace(r, lineup=replace(r.lineup, batters=bats))


def _games(overrides=None):
    away, home = _stealing_roster(1, "AWY", 100000), _stealing_roster(2, "HOM", 200000)
    cfg = GameConfig(rng_seed=11, manager_pitching="v2", manager_pitching_overrides=dict(overrides or {}))
    for i in range(N):
        yield simulate_game(away, home, replace(cfg, rng_seed=11 + i))


def _summary(overrides=None):
    return [(r.away_score, r.home_score, sorted((k, sorted(v.items())) for k, v in r.pitcher_stats.items()))
            for r in _games(overrides)]


def _no_walkoff(r):
    # Home batted in the final inning AND won -> that half may have ended before 3 outs.
    return not (r.home_score > r.away_score and len(r.home_inning_runs) == len(r.away_inning_runs))


class CaughtStealingOutsTests(unittest.TestCase):
    def test_the_fixture_actually_produces_caught_stealing(self) -> None:
        cs = sum(int(row.get("CS") or 0) for r in _games() for row in (r.batter_stats or {}).values())
        self.assertGreater(cs, 20, "the harness must exercise caught stealing or the invariant is vacuous")

    def test_pitcher_outs_equal_three_per_half_inning(self) -> None:
        checked = 0
        for r in _games():
            if not _no_walkoff(r):
                continue
            halves = len(r.away_inning_runs) + len(r.home_inning_runs)
            outs = sum(float(row.get("OUTS") or 0.0) for row in (r.pitcher_stats or {}).values())
            self.assertEqual(outs, 3.0 * halves, f"pitcher OUTS {outs} != 3 x {halves} half-innings")
            checked += 1
        self.assertGreater(checked, 20)


class PickoffTests(unittest.TestCase):
    def test_default_and_explicit_zero_are_byte_identical(self) -> None:
        self.assertEqual(_summary(None), _summary({"pickoff_rate": 0.0}))

    def test_junk_values_fall_back_to_off(self) -> None:
        for junk in ("x", None, -1, float("nan")):
            self.assertEqual(_summary(None), _summary({"pickoff_rate": junk}), f"junk {junk!r}")

    def test_pickoffs_happen_and_are_the_pitchers_outs(self) -> None:
        po = 0
        checked = 0
        for r in _games({"pickoff_rate": 0.10}):
            po += int(sum(float(v.get("PO", 0.0)) for v in r.pitcher_stats.values()))
            if not _no_walkoff(r):
                continue
            halves = len(r.away_inning_runs) + len(r.home_inning_runs)
            outs = sum(float(v.get("OUTS") or 0.0) for v in r.pitcher_stats.values())
            self.assertEqual(outs, 3.0 * halves)
            checked += 1
        self.assertGreater(po, 10, "the knob was not read, or the opportunity never arose")
        self.assertGreater(checked, 20)


if __name__ == "__main__":
    unittest.main()
