"""`starter_min_innings` as a manager_pitching override (`#440` Phase 7 follow-up).

Context. The F5 leash was readable only from `ManagerProfile.starter_min_innings`,
hardcoded at 5 for all 30 teams because `data/manager/manager_tendencies.json`
does not exist and its loader silently returns `{}`. It is upstream of every
knob in `manager_pitching_overrides` -- inside the leash window the pitch-count
hook is bypassed -- so it was the one starter-depth parameter that could not be
swept while everything below it had been fitted. Measured 2026-08-17 on 726
production starts: sim P(outs<15) = 0.104 against an actual 0.296, with 26.78%
of all simulated mass at exactly 15 outs.

The two tests that matter are the Phase 5 pair, and in the same order:

  1. NO BEHAVIOUR CHANGE when the override is absent -- byte-identical results.
  2. REACHABILITY -- the engine actually READS it. `calibration_profile_store`
     is the standing lesson here: a seam that exists and is called by nothing
     looks exactly like a working one from the outside.

Toy rosters, so this needs no artifact, no network and no mirror.
"""

from __future__ import annotations

import random
import unittest
from dataclasses import replace

from vendor.mlb_bettingv2.sim_engine.models import (
    BatterProfile,
    GameConfig,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    PitchType,
    Player,
    Team,
    TeamRoster,
)
from vendor.mlb_bettingv2.sim_engine.simulate import simulate_game

N_GAMES = 60


def _player(pid: int, prefix: str, position: str) -> Player:
    return Player(
        mlbam_id=pid,
        full_name=f"{prefix}{pid}",
        primary_position=position,
        bat_side=Handedness.R,
        throw_side=Handedness.R,
    )


def _batter(pid: int) -> BatterProfile:
    return BatterProfile(
        player=_player(pid, "B", "1B"),
        k_rate=0.22, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035, inplay_hit_rate=0.275,
    )


def _pitcher(pid: int, stamina: int) -> PitcherProfile:
    return PitcherProfile(
        player=_player(pid, "P", "P"),
        k_rate=0.22, bb_rate=0.08, hbp_rate=0.008, hr_rate=0.035, inplay_hit_rate=0.27,
        arsenal={PitchType.FF: 0.55, PitchType.SL: 0.25, PitchType.CH: 0.20},
        stamina_pitches=stamina,
    )


def _roster(team_id: int, abbr: str, base: int) -> TeamRoster:
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(
            batters=[_batter(base + i) for i in range(1, 10)],
            pitcher=_pitcher(base + 100, stamina=95),
            bench=[],
            bullpen=[_pitcher(base + 200 + i, stamina=25) for i in range(8)],
        ),
    )


def starter_outs(overrides: dict | None, *, n: int = N_GAMES, seed: int = 2026) -> list[float]:
    """Outs recorded by each team's STARTER across n seeded games."""
    away, home = _roster(1, "AWY", 100000), _roster(2, "HOM", 200000)
    starters = {away.lineup.pitcher.player.mlbam_id, home.lineup.pitcher.player.mlbam_id}
    cfg = GameConfig(
        rng_seed=seed,
        manager_pitching="v2",
        manager_pitching_overrides=dict(overrides or {}),
    )
    out: list[float] = []
    for i in range(n):
        result = simulate_game(away, home, replace(cfg, rng_seed=seed + i))
        for pid, stats in result.pitcher_stats.items():
            if int(pid) in starters:
                # "OUTS", not "outs" -- the first draft of this file used the
                # lowercase key, every reading came back 0.0, and the two
                # no-behaviour-change tests PASSED on 0.0 == 0.0. A vacuous
                # pass is the failure mode this helper now refuses to have.
                out.append(float(stats["OUTS"]))
    if not out or not any(out):
        raise AssertionError(
            "no starter recorded a single out -- the harness is measuring nothing, "
            "so every comparison built on it would pass vacuously"
        )
    return out


class NoBehaviourChangeTests(unittest.TestCase):
    """Half one: an absent override must be a no-op."""

    def test_absent_override_is_byte_identical_to_the_profile_default(self) -> None:
        self.assertEqual(starter_outs(None), starter_outs({}))

    def test_setting_it_to_the_profile_value_is_also_a_no_op(self) -> None:
        # ManagerProfile.starter_min_innings is 5; naming it explicitly must not
        # change a single game.
        self.assertEqual(
            starter_outs(None),
            starter_outs({"starter_min_innings": ManagerProfile().starter_min_innings}),
        )

    def test_unrelated_overrides_do_not_disturb_the_leash(self) -> None:
        self.assertEqual(
            starter_outs({"starter_leash_pc_buffer": 20}),
            starter_outs({"starter_leash_pc_buffer": 20, "starter_min_innings": 5}),
        )


class ReachabilityTests(unittest.TestCase):
    """Half two, and the one that actually proves the seam is wired. A knob the
    engine never reads passes every no-op test above."""

    def test_shortening_the_leash_changes_the_simulated_outs(self) -> None:
        baseline = starter_outs({"starter_min_innings": 5})
        shortened = starter_outs({"starter_min_innings": 3})
        self.assertNotEqual(baseline, shortened, "engine did not read starter_min_innings")

    def test_shortening_the_leash_reduces_mean_starter_outs(self) -> None:
        # Direction, not just difference: a shorter leash must not make starters
        # go LONGER. This is what makes the knob usable for a sweep.
        long_leash = starter_outs({"starter_min_innings": 6})
        short_leash = starter_outs({"starter_min_innings": 2})
        self.assertLess(
            sum(short_leash) / len(short_leash),
            sum(long_leash) / len(long_leash),
        )

    def test_zero_disables_the_leash_rather_than_being_promoted_to_one(self) -> None:
        # The old code read max(1, ...), which silently turned 0 into a
        # one-inning leash. 0 must now mean "no leash window at all".
        self.assertNotEqual(
            starter_outs({"starter_min_innings": 0}),
            starter_outs({"starter_min_innings": 1}),
        )

    def test_the_leash_compresses_mass_onto_its_own_boundary(self) -> None:
        # The production defect in miniature: with a 5-inning leash, 15 outs
        # should be a visible spike; with the leash off it should not dominate.
        with_leash = starter_outs({"starter_min_innings": 5})
        without = starter_outs({"starter_min_innings": 0})
        share_at_15 = sum(1 for o in with_leash if o == 15) / len(with_leash)
        share_at_15_off = sum(1 for o in without if o == 15) / len(without)
        self.assertGreater(share_at_15, share_at_15_off)


class MalformedInputTests(unittest.TestCase):
    def test_a_junk_override_falls_back_to_the_profile_instead_of_raising(self) -> None:
        for junk in ("banana", None, [1, 2]):
            self.assertEqual(
                starter_outs(None),
                starter_outs({"starter_min_innings": junk}),
                f"junk value {junk!r} did not fall back cleanly",
            )

    def test_a_negative_value_is_clamped_to_no_leash_not_to_one(self) -> None:
        self.assertEqual(
            starter_outs({"starter_min_innings": -3}),
            starter_outs({"starter_min_innings": 0}),
        )


if __name__ == "__main__":
    unittest.main()
