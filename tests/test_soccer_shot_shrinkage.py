"""The shot-shrinkage divisor: does it REACH the engine, and does it fail safe.

THE FIRST TEST IS A REACHABILITY TEST, and it drives the real shipped function
rather than the calibration module, because that is the failure this repo keeps
paying for: a correctly-loaded constant that nothing multiplies by is
indistinguishable from a build where the feature does not exist. A correctness
test over `shot_shrinkage_divisor()` alone would pass in exactly that case.

The rest pin the SAFE side. `1.0` on every failure path is deliberate: the
permissive direction here is APPLYING an unvalidated correction to a live money
path, so absent, unreadable, malformed and out-of-range must all resolve to the
identity -- the pre-2026-08-31 behaviour.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from syndicate.features.soccer.sim_engine.soccersim import shot_calibration
from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.player_props import (
    PlayerUsageProfile,
    project_player_props,
)


class _Isolated(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        patcher = mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, payload):
        # Writes a DATED file, because that is the only name the worker's
        # date-scoped pull can ever deliver. `shot_shrinkage_path()` resolves
        # the newest one.
        p = shot_calibration._calibration_dir() / "shot_shrinkage_2026-08-31.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload) if not isinstance(payload, str) else payload,
                     encoding="utf-8")


def _profile():
    return PlayerUsageProfile(
        player_id="p1", player_name="Test Striker", side="home", position="F",
        team="Test FC", expected_minutes_share=0.9, shot_share=0.25,
        goal_share=0.2, assist_share=0.1, on_target_rate=0.35,
    )


def _distribution():
    """A minimal real MatchDistributionSummary -- the engine's own input type,
    not a stand-in, so the test cannot pass against a signature that changed."""
    return MatchDistributionSummary(
        simulations=1, home_win_probability=0.4, draw_probability=0.3,
        away_win_probability=0.3, mean_home_goals=1.4, mean_away_goals=1.1,
        mean_total=2.5, mean_margin=0.3, over_2_5_probability=0.5,
        both_teams_scored_probability=0.5, scoreline_probabilities={},
        mean_home_shots=12.0, mean_away_shots=10.0,
        mean_home_shots_on_target=4.0, mean_away_shots_on_target=3.0,
    )


def _project():
    """Drive the REAL shipped projection function, not the calibration module."""
    return project_player_props(_distribution(), _profile())


class ItActuallyReachesTheEngine(_Isolated):
    def test_off_versus_on_changes_the_published_probability(self):
        """The reachability test. Without this, every other test here passes on
        a build where the divisor is loaded and never used."""
        self.write({"divisor": 1.0})
        before = _project()
        self.write({"divisor": 1.4})
        after = _project()
        self.assertGreater(before.expected_shots, after.expected_shots,
                           "the divisor is not reaching expected_shots")
        self.assertNotEqual(before.shots_over_probabilities,
                            after.shots_over_probabilities,
                            "expected_shots moved but the published ladder did not")

    def test_shots_on_target_inherits_the_same_correction(self):
        """Measured, not assumed: shots 1.398x and SOT 1.408x over-predict, so
        the on-target RATE is already right and must NOT be corrected twice."""
        self.write({"divisor": 1.0})
        before = _project()
        self.write({"divisor": 1.4})
        after = _project()
        rate_before = before.expected_shots_on_target / before.expected_shots
        rate_after = after.expected_shots_on_target / after.expected_shots
        # places=4, not 6: `expected_shots` and `expected_shots_on_target` are
        # each rounded to 4dp independently by the dataclass, so their RATIO
        # drifts ~7e-06 purely from that. Asserting tighter than the stored
        # precision tests the rounding, not the behaviour.
        self.assertAlmostEqual(rate_before, rate_after, places=4,
                               msg="the divisor changed the on-target RATE; it must only scale the level")
        self.assertAlmostEqual(after.expected_shots_on_target,
                               before.expected_shots_on_target / 1.4, places=3)

    def test_the_divisor_scales_the_mean_by_exactly_itself(self):
        self.write({"divisor": 1.0})
        before = _project().expected_shots
        self.write({"divisor": 1.4})
        after = _project().expected_shots
        self.assertAlmostEqual(after, before / 1.4, places=3)


class EveryFailurePathIsTheIdentity(_Isolated):
    def test_absent_artifact(self):
        self.assertEqual(shot_calibration.shot_shrinkage_divisor(), 1.0)

    def test_absent_artifact_leaves_the_projection_untouched(self):
        """`absent` must mean 'behaves as it did before this module existed'."""
        no_file = _project().expected_shots
        self.write({"divisor": 1.0})
        self.assertAlmostEqual(no_file, _project().expected_shots, places=6)

    def test_malformed_json(self):
        self.write("{ not json at all")
        self.assertEqual(shot_calibration.shot_shrinkage_divisor(), 1.0)

    def test_missing_key(self):
        self.write({"fitted_at": "2026-08-31"})
        self.assertEqual(shot_calibration.shot_shrinkage_divisor(), 1.0)

    def test_non_numeric(self):
        self.write({"divisor": "1.4x"})
        self.assertEqual(shot_calibration.shot_shrinkage_divisor(), 1.0)

    def test_out_of_range_is_refused_rather_than_clamped_into_effect(self):
        """A garbage fit must not silently become a 2.0 correction."""
        for bad in (0.0, 0.5, 2.5, 100.0, -1.4):
            with self.subTest(divisor=bad):
                self.write({"divisor": bad})
                self.assertEqual(shot_calibration.shot_shrinkage_divisor(), 1.0)

    def test_the_measured_range_is_accepted(self):
        """1.24-1.44 is what every split produced; the clamp must be inert there."""
        for good in (1.2441, 1.3135, 1.3331, 1.4376):
            with self.subTest(divisor=good):
                self.write({"divisor": good})
                self.assertAlmostEqual(shot_calibration.shot_shrinkage_divisor(), good)


if __name__ == "__main__":
    unittest.main()
