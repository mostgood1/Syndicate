"""H38 own-rate blend for soccer shot / SOT props (lane soccer-shots-allocation-blend).

REACHABILITY FIRST (model_engine_standard 4.3): with the flag on and the inputs present the ladder must move;
with the flag off it must be exactly the pre-change mixture. Then the arithmetic, the >= 3-appearance gate, and
that only the CURRENT season's row feeds the own rate.
"""

from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from syndicate.features.soccer.sim_engine.soccersim import player_props as pp
from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary


def _distribution() -> MatchDistributionSummary:
    return MatchDistributionSummary(
        simulations=1, home_win_probability=0.4, draw_probability=0.3,
        away_win_probability=0.3, mean_home_goals=1.4, mean_away_goals=1.1,
        mean_total=2.5, mean_margin=0.3, over_2_5_probability=0.5,
        both_teams_scored_probability=0.5, scoreline_probabilities={},
        mean_home_shots=12.0, mean_away_shots=10.0,
        mean_home_shots_on_target=4.0, mean_away_shots_on_target=3.0,
    )


def _rows(season: str = "2026") -> list[dict]:
    # ESPN-shaped current-season rows: appearances, starts, minutes_played, shots_per90, shot_on_target_rate.
    return [
        {"player_id": "s1", "player_name": "Striker", "position": "F", "season": season, "appearances": 6, "starts": 6,
         "minutes_played": 520.0, "shots_per90": 3.6, "xg_per90": 0.5, "xa_per90": 0.1, "shot_on_target_rate": 0.4,
         "expected_minutes_share": 0.95},
        {"player_id": "m1", "player_name": "Mid", "position": "M", "season": season, "appearances": 6, "starts": 4,
         "minutes_played": 400.0, "shots_per90": 1.2, "xg_per90": 0.1, "xa_per90": 0.2, "shot_on_target_rate": 0.3,
         "expected_minutes_share": 0.7},
        {"player_id": "d1", "player_name": "Def", "position": "D", "season": season, "appearances": 2, "starts": 2,
         "minutes_played": 180.0, "shots_per90": 0.4, "xg_per90": 0.02, "xa_per90": 0.05, "shot_on_target_rate": 0.2,
         "expected_minutes_share": 0.4},
    ]


def _profiles(flag: bool, rows=None):
    env = {pp._OWN_RATE_BLEND_ENV: "1"} if flag else {}
    with mock.patch.dict("os.environ", env, clear=False):
        if not flag:
            import os
            os.environ.pop(pp._OWN_RATE_BLEND_ENV, None)
        return pp.build_usage_profiles(rows or _rows(), side="home", team="Test FC")


class Reachability(unittest.TestCase):
    def test_flag_on_moves_the_striker_ladder_and_flag_off_does_not(self):
        off = pp.project_player_props(_distribution(), _profiles(False)[0])
        on = pp.project_player_props(_distribution(), _profiles(True)[0])
        self.assertNotEqual(off.shots_over_probabilities, on.shots_over_probabilities)
        self.assertNotEqual(off.expected_shots_if_playing, on.expected_shots_if_playing)
        self.assertIsNone(off.own_rate_blend)
        self.assertIsNotNone(on.own_rate_blend)

    def test_flag_off_is_the_pre_change_mixture_exactly(self):
        prof = _profiles(False)[0]
        stripped = dataclasses.replace(prof, own_shots_per_appearance=None, own_sot_per_appearance=None, own_appearances=None)
        a, b = pp.project_player_props(_distribution(), prof), pp.project_player_props(_distribution(), stripped)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_the_flag_is_a_declared_field_and_survives_replace(self):
        prof = _profiles(True)[0]
        self.assertTrue(dataclasses.replace(prof, team="X").own_rate_blend)


class Arithmetic(unittest.TestCase):
    def test_blended_means_follow_the_registered_weights(self):
        on = pp.project_player_props(_distribution(), _profiles(True)[0])
        note = on.own_rate_blend
        self.assertAlmostEqual(note["blend_shots"], pp._OWN_RATE_L_SHOTS * note["model_shots"] + (1 - pp._OWN_RATE_L_SHOTS) * note["own_shots"], places=3)
        self.assertAlmostEqual(on.expected_shots_if_playing, note["blend_shots"], places=3)
        self.assertAlmostEqual(on.expected_shots_on_target_if_playing, note["blend_sot"], places=3)

    def test_own_rate_is_shrunk_toward_the_team_mean(self):
        prof = _profiles(True)[0]
        team_apps = 6 + 6 + 2
        team_shots = 3.6 * 520 / 90 + 1.2 * 400 / 90 + 0.4 * 180 / 90
        expected = (3.6 * 520 / 90 + 3.0 * team_shots / team_apps) / (6 + 3.0)
        self.assertAlmostEqual(prof.own_shots_per_appearance, expected, places=6)

    def test_fewer_than_three_appearances_leaves_the_model_alone(self):
        prof = _profiles(True)[2]   # the defender has 2 appearances
        self.assertEqual(prof.own_appearances, 2)
        self.assertIsNone(pp.project_player_props(_distribution(), prof).own_rate_blend)

    def test_a_prior_season_row_does_not_feed_the_own_rate(self):
        rows = _rows("2026") + [dict(_rows("2025")[0], player_id="old", player_name="Old Season")]
        profs = _profiles(True, rows)
        self.assertIsNone(profs[-1].own_shots_per_appearance)


class AZeroModelMeanIsBlendedToo(unittest.TestCase):
    """Defect 1 (deploys.md 2026-10-04 17:55Z): a player with no shot share had a 0 model mean, the note recorded a
    positive blend, and the served ladder stayed 0. The served mean must equal the note."""

    def test_zero_model_mean_serves_the_blend(self):
        prof = dataclasses.replace(_profiles(True)[1], on_pitch_shot_share=0.0)
        proj = pp.project_player_props(_distribution(), prof)
        note = proj.own_rate_blend
        self.assertEqual(note["model_shots"], 0.0)
        self.assertGreater(note["blend_shots"], 0.0)
        self.assertAlmostEqual(proj.expected_shots_if_playing, note["blend_shots"], places=3)
        self.assertAlmostEqual(proj.expected_shots_on_target_if_playing, note["blend_sot"], places=3)
        self.assertGreater(proj.shots_over_probabilities["0.5"], 0.0)

    def test_zero_model_mean_with_flag_off_stays_zero(self):
        prof = dataclasses.replace(_profiles(False)[1], on_pitch_shot_share=0.0)
        proj = pp.project_player_props(_distribution(), prof)
        self.assertEqual(proj.expected_shots_if_playing, 0.0)
        self.assertIsNone(proj.own_rate_blend)


class EspnRowsReachTheBlend(unittest.TestCase):
    """The loader's usage_metrics whitelist is the gate production rows pass through. ESPN rows carry
    `minutes_played`, not `minutes`; without it the blend is inert for championship/eredivisie/primeira/belgian."""

    def test_an_espn_row_through_the_real_loader_feeds_the_own_rate(self):
        from syndicate.features.soccer.features.loaders import build_soccer_player_features

        rows = [dict(r, team="Test FC") for r in _rows()]
        feats = build_soccer_player_features(rows, league="championship", date="2026-10-03", fixture_teams=["Test FC"])
        usage = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, **dict(f.usage_metrics)} for f in feats]
        self.assertTrue(all("minutes_played" in u for u in usage))
        with mock.patch.dict("os.environ", {pp._OWN_RATE_BLEND_ENV: "1"}):
            profs = pp.build_usage_profiles(usage, side="home", team="Test FC")
        striker = next(p for p in profs if p.player_id == "s1")
        self.assertIsNotNone(striker.own_shots_per_appearance)
        self.assertIsNotNone(pp.project_player_props(_distribution(), striker).own_rate_blend)


if __name__ == "__main__":
    unittest.main()
