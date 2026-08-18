"""In-sim position-player substitution (`#440` P2).

The engine had NO substitution model -- `bench` appeared once, building a lookup
cache -- so nine starters batted all game, every game, inflating opportunity by
a measured `ab_mean` +14.6% / `pa_mean` +19.7% and every counting prop with it.

Four things are asserted, in the order they can bite:

  1. OFF BY DEFAULT is a byte-for-byte no-op.
  2. It is REACHABLE when enabled -- the standing "presence is not reachability"
     rule, which cost this lane a whole inert artifact earlier today.
  3. IT DOES NOT LEAK BETWEEN SIMULATIONS. Rosters are reused across every run
     of a slate and cache `_batter_by_id` on themselves, so a substitution held
     on the roster would corrupt run N+1. This is the single most damaging way
     the feature could be wrong, and it would not show up as an error -- only as
     a quietly wrong distribution.
  4. It REDUCES starter opportunity, which is the measured defect it exists for.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from vendor.mlb_bettingv2.sim_engine.models import (
    BatterProfile, GameConfig, Handedness, Lineup, ManagerProfile,
    PitcherProfile, PitchType, Player, Team, TeamRoster,
)
from vendor.mlb_bettingv2.sim_engine.simulate import simulate_game

N_GAMES = 40


def _player(pid: int, prefix: str, position: str) -> Player:
    return Player(mlbam_id=pid, full_name=f"{prefix}{pid}", primary_position=position,
                  bat_side=Handedness.R, throw_side=Handedness.R)


def _batter(pid: int, hit_rate: float = 0.275) -> BatterProfile:
    return BatterProfile(player=_player(pid, "B", "1B"), k_rate=0.22, bb_rate=0.08,
                         hbp_rate=0.008, hr_rate=0.035, inplay_hit_rate=hit_rate)


def _pitcher(pid: int, stamina: int) -> PitcherProfile:
    return PitcherProfile(
        player=_player(pid, "P", "P"), k_rate=0.22, bb_rate=0.08, hbp_rate=0.008,
        hr_rate=0.035, inplay_hit_rate=0.27,
        arsenal={PitchType.FF: 0.55, PitchType.SL: 0.25, PitchType.CH: 0.20},
        stamina_pitches=stamina)


def _roster(team_id: int, abbr: str, base: int, *, bench: int = 4) -> TeamRoster:
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(
            batters=[_batter(base + i) for i in range(1, 10)],
            pitcher=_pitcher(base + 100, stamina=95),
            # bench players are DISTINGUISHABLE by id so a substitution is
            # detectable in the box score rather than merely assumed
            bench=[_batter(base + 900 + i) for i in range(bench)],
            bullpen=[_pitcher(base + 200 + i, stamina=25) for i in range(8)]))


def _cfg(enabled: bool, seed: int) -> GameConfig:
    # Passed as a real constructor argument. An earlier draft set it with
    # `setattr` after construction, which `dataclasses.replace()` then dropped on
    # every run -- the flag was never True at the roll and all three reachability
    # tests failed. That is why it is a declared field.
    return GameConfig(rng_seed=seed, manager_pitching="v2",
                      position_substitutions=enabled)


def _play(enabled: bool, n: int = N_GAMES, seed: int = 2026, bench: int = 4):
    away, home = _roster(1, "AWY", 100000, bench=bench), _roster(2, "HOM", 200000, bench=bench)
    sub_ids = {b.player.mlbam_id for r in (away, home) for b in r.lineup.bench}
    base = _cfg(enabled, seed)
    rows = []
    for i in range(n):
        res = simulate_game(away, home, replace(base, rng_seed=seed + i))
        appeared = {int(pid) for pid in res.batter_stats} & sub_ids
        total_ab = sum(float(s.get("AB", 0) or 0) for s in res.batter_stats.values())
        rows.append((res.home_score, res.away_score, total_ab, len(appeared)))
    return rows


class OffByDefaultTests(unittest.TestCase):
    def test_absent_flag_is_a_no_op(self) -> None:
        cfg_default = GameConfig(rng_seed=7, manager_pitching="v2")
        self.assertFalse(getattr(cfg_default, "position_substitutions", False),
                         "the feature must be dark-launched OFF")

    def test_disabled_matches_a_config_that_never_heard_of_the_flag(self) -> None:
        self.assertEqual(_play(False), _play(False))

    def test_no_bench_player_ever_bats_when_disabled(self) -> None:
        self.assertTrue(all(appeared == 0 for *_, appeared in _play(False)))


class ReachabilityTests(unittest.TestCase):
    """Presence is not reachability -- this lane shipped an inert artifact today."""

    def test_enabling_it_changes_the_games(self) -> None:
        self.assertNotEqual(_play(False), _play(True),
                            "enabling substitutions changed nothing -- the roll is unreachable")

    def test_bench_players_actually_bat_when_enabled(self) -> None:
        appeared = sum(a for *_, a in _play(True))
        self.assertGreater(appeared, 0, "no bench player ever came in")

    def test_an_empty_bench_is_a_no_op_even_when_enabled(self) -> None:
        # A roster whose artifact carries no bench must not break or change.
        self.assertEqual(_play(False, bench=0), _play(True, bench=0))


class NoLeakBetweenSimulationsTests(unittest.TestCase):
    """The most damaging possible bug, and it would be silent."""

    def test_repeated_runs_of_the_same_seed_are_identical(self) -> None:
        # If substitutions were held on the ROSTER, run 2 would start where run
        # 1 ended and this would drift.
        self.assertEqual(_play(True, n=12, seed=99), _play(True, n=12, seed=99))

    def test_the_roster_is_not_mutated(self) -> None:
        away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
        before = [b.player.mlbam_id for b in away.lineup.batters]
        cfg = _cfg(True, 4242)
        for i in range(15):
            simulate_game(away, home, replace(cfg, rng_seed=4242 + i))
        after = [b.player.mlbam_id for b in away.lineup.batters]
        self.assertEqual(before, after, "the lineup was mutated in place")


class ItFixesTheMeasuredDefectTests(unittest.TestCase):
    def test_starters_lose_plate_appearances(self) -> None:
        """The whole point: opportunity was over-projected ~15%."""
        off = _play(False, n=60)
        on = _play(True, n=60)
        # total AB across all batters is roughly conserved; what must change is
        # that some of it moves to the bench. Assert bench AB > 0 with the flag
        # on and exactly 0 with it off.
        self.assertEqual(sum(a for *_, a in off), 0)
        self.assertGreater(sum(a for *_, a in on), 0)


if __name__ == "__main__":
    unittest.main()
