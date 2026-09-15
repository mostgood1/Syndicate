"""Soccer shot props: the divisor stays retired, and the ladder is conditional on appearing.

THE RETIRED DIVISOR. The 1.393 shot-shrinkage divisor (shipped 2026-08-31) was
read from a dated `soccer_source/calibration/shot_shrinkage_*.json` artifact. That
artifact is still on production's disk, and the calibration glob that delivered it
is still allowlisted, because `probability_calibration` shares it. So the only
thing keeping the old correction out of the engine is that nothing reads the file.
The first class pins exactly that, with the artifact PRESENT: an `off == on` test,
the inverse of the reachability test that shipped with the divisor.

THE CONDITIONAL LADDER. Books void a shot prop on a DNP, so `shots_over_probabilities`
is P(over | appears): a start/sub mixture at the player's on-pitch rate. Measured
held out (lane soccer-player-role-allocation, dates >= 2026-08-26, production-shaped
inputs), log loss at P(>=1) / P(>=2) was shots 0.611 / 0.469 against the
unconditional ladder's 0.641 / 0.517, and SOT 0.493 / 0.199 against 0.512 / 0.215,
better in 9/10 leagues.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from syndicate.features.soccer.features.loaders import build_soccer_player_features
from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import PlayerUsageProfile
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles
from syndicate.features.soccer.sim_engine.soccersim.player_props import poisson_at_least
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_player_props


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=1, home_win_probability=0.4, draw_probability=0.3,
        away_win_probability=0.3, mean_home_goals=1.4, mean_away_goals=1.1,
        mean_total=2.5, mean_margin=0.3, over_2_5_probability=0.5,
        both_teams_scored_probability=0.5, scoreline_probabilities={},
        mean_home_shots=12.0, mean_away_shots=10.0,
        mean_home_shots_on_target=4.0, mean_away_shots_on_target=3.0,
    )


def _striker() -> PlayerUsageProfile:
    return PlayerUsageProfile(
        player_id="p1", player_name="Test Striker", side="home", position="F",
        team="Test FC", expected_minutes_share=0.9, shot_share=0.25,
        goal_share=0.2, assist_share=0.1, on_target_rate=0.35,
    )


class TheRetiredDivisorStaysRetired(unittest.TestCase):
    def _with_divisor_artifact(self, divisor: float):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        calibration = Path(tmp.name) / "soccer_source" / "calibration"
        calibration.mkdir(parents=True)
        (calibration / "shot_shrinkage_2026-08-31.json").write_text(
            json.dumps({"divisor": divisor}), encoding="utf-8")
        patcher = mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_divisor_artifact_on_disk_no_longer_moves_the_shot_mean(self):
        """off == on: the artifact production still holds must be inert."""
        without = project_player_props(_distribution(), _striker())
        self._with_divisor_artifact(1.393)
        with_file = project_player_props(_distribution(), _striker())
        self.assertEqual(without.expected_shots, with_file.expected_shots)
        self.assertEqual(without.shots_over_probabilities, with_file.shots_over_probabilities)
        self.assertEqual(without.shots_on_target_over_probabilities,
                         with_file.shots_on_target_over_probabilities)

    def test_the_shot_mean_is_exactly_the_share_of_team_volume(self):
        self._with_divisor_artifact(1.393)
        projection = project_player_props(_distribution(), _striker())
        self.assertAlmostEqual(projection.expected_shots, 12.0 * 0.25, places=4)
        self.assertEqual(projection.shots_over_probabilities["0.5"],
                         round(poisson_at_least(12.0 * 0.25, 1), 4))

    def test_shots_on_target_is_the_shot_mean_times_the_rate(self):
        projection = project_player_props(_distribution(), _striker())
        self.assertAlmostEqual(projection.expected_shots_on_target, 12.0 * 0.25 * 0.35, places=4)

    def test_the_calibration_module_is_gone(self):
        """Nothing can re-import the loader and quietly re-apply it."""
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("syndicate.features.soccer.sim_engine.soccersim.shot_calibration")


def _mixture_p(components, k):
    return sum(weight * poisson_at_least(mean, k) for weight, mean in components)


class TheShotLadderIsConditionalOnAppearing(unittest.TestCase):
    def test_role_inputs_change_the_published_ladders_and_nothing_else(self):
        """Reachability, off != on. It is also the guard that the mixture touches
        only the two shot markets it was measured on."""
        bare = _striker()
        with_roles = dataclasses.replace(bare, start_probability=0.8, on_pitch_shot_share=0.25 / 0.9)
        off = project_player_props(_distribution(), bare)
        on = project_player_props(_distribution(), with_roles)
        self.assertNotEqual(off.shots_over_probabilities, on.shots_over_probabilities)
        self.assertNotEqual(off.shots_on_target_over_probabilities, on.shots_on_target_over_probabilities)
        self.assertNotEqual(off.expected_shots_if_playing, on.expected_shots_if_playing)
        for unchanged in ("expected_shots", "expected_shots_on_target", "expected_goals", "expected_assists",
                          "anytime_scorer_probability", "anytime_scorer_probability_if_playing",
                          "assists_over_probabilities", "goal_or_assist_probability"):
            self.assertEqual(getattr(off, unchanged), getattr(on, unchanged), unchanged)

    def test_the_ladder_is_the_start_sub_mixture(self):
        profile = dataclasses.replace(_striker(), start_probability=0.8, on_pitch_shot_share=0.3)
        projection = project_player_props(_distribution(), profile)
        full_match = 12.0 * 0.3
        shots = ((0.8, full_match * 83.1 / 90.0), (0.2, 1.8 * full_match * 15.6 / 90.0))
        sot = tuple((w, m * 0.35) for w, m in shots)
        self.assertEqual(projection.shots_over_probabilities["0.5"], round(_mixture_p(shots, 1), 4))
        self.assertEqual(projection.shots_over_probabilities["1.5"], round(_mixture_p(shots, 2), 4))
        self.assertEqual(projection.shots_on_target_over_probabilities["0.5"], round(_mixture_p(sot, 1), 4))
        self.assertAlmostEqual(projection.expected_shots_if_playing, sum(w * m for w, m in shots), places=4)
        # The first component is 1 - exp(-mean): check the helper against the closed form.
        self.assertAlmostEqual(_mixture_p(((1.0, 2.0),), 1), 1.0 - math.exp(-2.0), places=9)

    def test_a_goalkeeper_is_untouched(self):
        keeper = PlayerUsageProfile(player_id="gk", player_name="Keeper", side="home", position="GK",
                                    is_goalkeeper=True, start_probability=1.0, on_pitch_shot_share=0.5)
        projection = project_player_props(_distribution(), keeper)
        self.assertEqual(projection.shots_over_probabilities, {})


def _row(pid, **fields):
    base = {"player_id": pid, "player_name": pid.upper(), "position": "F", "team": "Test FC", "shots_per90": 2.0}
    base.update(fields)
    return base


class BuildUsageProfilesSetsTheRoleInputs(unittest.TestCase):
    def test_a_confirmed_lineup_decides_the_role(self):
        rows = [_row("s1", season=2026, games=4, minutes=300), _row("b1", season=2026, games=4, minutes=40)]
        starter, bench = build_usage_profiles(rows, side="home", starters={"s1"})
        self.assertEqual(starter.start_probability, 1.0)
        self.assertEqual(bench.start_probability, 0.0)

    def test_espn_counts_set_the_start_probability(self):
        rows = [_row("e1", appearances=5, starts=4, expected_minutes_share=0.7), _row("e2", expected_minutes_share=0.9)]
        profile = build_usage_profiles(rows, side="home")[0]
        prior = min(0.95, max(0.05, 0.7 / (83.1 / 90.0)))
        self.assertAlmostEqual(profile.start_probability, (4 + 2.0 * prior) / (5 + 2.0), places=9)

    def test_understat_minutes_per_appearance_set_the_start_probability(self):
        rows = [_row("u1", season=2026, games=4, minutes=300), _row("u2", season=2026, games=4, minutes=360)]
        profile = build_usage_profiles(rows, side="home")[0]
        self.assertAlmostEqual(profile.start_probability, (75.0 - 15.6) / (83.1 - 15.6), places=9)

    def test_no_role_evidence_falls_back_to_the_minutes_prior(self):
        rows = [_row("a1", expected_minutes_share=0.45), _row("a2", expected_minutes_share=0.9)]
        profile = build_usage_profiles(rows, side="home")[0]
        self.assertAlmostEqual(profile.start_probability, 0.45 / (83.1 / 90.0), places=9)

    def test_a_prior_season_row_does_not_set_the_current_match_count(self):
        """The defect run 5 measured: one match count across seasons inflated the big five 1.15-1.67x."""
        rows = [
            _row("cur1", season=2026, games=4, minutes=360, shots_per90=3.0),
            _row("cur2", season=2026, games=4, minutes=180, shots_per90=2.0),
            _row("old", season=2025, games=38, minutes=3000, shots_per90=1.0),
        ]
        cur1 = build_usage_profiles(rows, side="home")[0]
        total = 3.0 * (360 / 360) + 2.0 * (180 / 360) + 1.0 * (3000 / (38 * 90))
        self.assertAlmostEqual(cur1.on_pitch_shot_share, 3.0 / total, places=9)
        self.assertLess(cur1.on_pitch_shot_share, 1.0)

    def test_the_shares_that_allocate_goals_and_assists_are_unchanged(self):
        plain = [_row("x1", expected_minutes_share=0.8, xg_per90=0.4, xa_per90=0.1),
                 _row("x2", expected_minutes_share=0.3, xg_per90=0.2, xa_per90=0.3)]
        roled = [dict(plain[0], season=2026, games=4, minutes=100, appearances=3, starts=1),
                 dict(plain[1], season=2025, games=30, minutes=2000)]
        for a, b in zip(build_usage_profiles(plain, side="home"), build_usage_profiles(roled, side="home")):
            for field in ("expected_minutes_share", "shot_share", "goal_share", "assist_share"):
                self.assertEqual(getattr(a, field), getattr(b, field), field)


class LoadersCarryTheRoleInputs(unittest.TestCase):
    def test_usage_metrics_carry_season_appearances_and_starts(self):
        rows = [{"player_id": "e1", "player_name": "Alpha", "team": "Test FC", "position": "F",
                 "shots_per90": 2.0, "season": 2026, "games": 4, "minutes": 300,
                 "appearances": 5, "starts": 4, "expected_minutes_share": 0.7}]
        features = build_soccer_player_features(rows, league="epl", date="2026-09-15",
                                                fixture_teams=["Test FC", "Other FC"])
        self.assertEqual(len(features), 1)
        metrics = features[0].usage_metrics
        for key in ("season", "games", "minutes", "appearances", "starts"):
            self.assertIn(key, metrics, key)


if __name__ == "__main__":
    unittest.main()
