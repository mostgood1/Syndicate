"""Batted-ball blend: shifts rate ESTIMATES, and never becomes a mechanism.

`#440`. The blend exists because batted-ball data out-predicts the sim's own
outcome rates leak-free (barrel 0.387 vs hr_rate 0.312 on future HR; hard-hit
0.235 vs 0.126 on future TB, n=218).

The tests that matter here are the ones that keep it HONEST rather than the ones
that prove it runs:

  * weight 0 / absent artifact / unknown player must be exact no-ops;
  * a LEAGUE-AVERAGE batter must be UNCHANGED -- if the blend moved everyone it
    would be a league-wide rate shift masquerading as a player signal, and the
    refit would then absorb it and hide the effect;
  * the multiplier must be CLAMPED, so a leaderboard outlier cannot triple a
    home-run rate;
  * barrels must drive HR and hard-hit must drive in-play, not the reverse.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from vendor.mlb_bettingv2.sim_engine.data import batted_ball as bbmod

SEASON = 2026


@dataclass
class _P:
    mlbam_id: int


@dataclass
class _Prof:
    player: _P
    hr_rate: float = 0.030
    inplay_hit_rate: float = 0.280


def _write(tmp: Path, players: dict) -> None:
    out = tmp / "mlb_source/source_artifacts/data/batted_ball"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"batted_ball_{SEASON}.json").write_text(
        json.dumps({"schema_version": 1, "season": SEASON, "players": players}),
        encoding="utf-8")


def _league(n: int = 40) -> dict:
    # a flat league at barrel 8.0 / hard-hit 40.0
    return {str(1000 + i): {"bbe": 200, "barrel_pct": 8.0, "hard_hit_pct": 40.0}
            for i in range(n)}


class NoOpTests(unittest.TestCase):
    def setUp(self):
        bbmod._ARTIFACT_CACHE.clear()

    def tearDown(self):
        bbmod._ARTIFACT_CACHE.clear()

    def test_weight_zero_is_a_no_op(self):
        with TemporaryDirectory() as t:
            root = Path(t); _write(root, _league() | {"7": {"bbe": 300, "barrel_pct": 20.0, "hard_hit_pct": 60.0}})
            p = _Prof(_P(7))
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                bbmod._ARTIFACT_CACHE.clear()
                self.assertFalse(bbmod.apply_batted_ball_to_batter(p, season=SEASON, weight=0.0))
        self.assertEqual((p.hr_rate, p.inplay_hit_rate), (0.030, 0.280))

    def test_absent_artifact_is_a_no_op(self):
        with TemporaryDirectory() as t:
            p = _Prof(_P(7))
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": t}):
                bbmod._ARTIFACT_CACHE.clear()
                self.assertFalse(bbmod.apply_batted_ball_to_batter(p, season=SEASON))
        self.assertEqual(p.hr_rate, 0.030)

    def test_unknown_player_is_a_no_op(self):
        with TemporaryDirectory() as t:
            root = Path(t); _write(root, _league())
            p = _Prof(_P(999999))
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                bbmod._ARTIFACT_CACHE.clear()
                self.assertFalse(bbmod.apply_batted_ball_to_batter(p, season=SEASON))
        self.assertEqual(p.hr_rate, 0.030)


class BlendBehaviourTests(unittest.TestCase):
    def setUp(self):
        bbmod._ARTIFACT_CACHE.clear()

    def tearDown(self):
        bbmod._ARTIFACT_CACHE.clear()

    def _run(self, entry: dict, weight: float = 0.35) -> _Prof:
        with TemporaryDirectory() as t:
            root = Path(t); _write(root, _league() | {"7": entry})
            p = _Prof(_P(7))
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": str(root)}):
                bbmod._ARTIFACT_CACHE.clear()
                bbmod.apply_batted_ball_to_batter(p, season=SEASON, weight=weight)
            return p

    def test_a_league_average_batter_is_unchanged(self):
        """If everyone moved, this would be a league rate shift, not a signal."""
        p = self._run({"bbe": 200, "barrel_pct": 8.0, "hard_hit_pct": 40.0})
        self.assertAlmostEqual(p.hr_rate, 0.030, places=9)
        self.assertAlmostEqual(p.inplay_hit_rate, 0.280, places=9)

    def test_a_high_barrel_batter_gets_a_higher_hr_rate(self):
        p = self._run({"bbe": 300, "barrel_pct": 16.0, "hard_hit_pct": 40.0})
        self.assertGreater(p.hr_rate, 0.030)
        self.assertAlmostEqual(p.inplay_hit_rate, 0.280, places=9,
                               msg="barrels must not move the in-play rate")

    def test_a_high_hard_hit_batter_gets_a_higher_inplay_rate(self):
        p = self._run({"bbe": 300, "barrel_pct": 8.0, "hard_hit_pct": 60.0})
        self.assertGreater(p.inplay_hit_rate, 0.280)
        self.assertAlmostEqual(p.hr_rate, 0.030, places=9,
                               msg="hard-hit must not move the HR rate")

    def test_a_weak_contact_batter_gets_a_lower_hr_rate(self):
        p = self._run({"bbe": 300, "barrel_pct": 2.0, "hard_hit_pct": 40.0})
        self.assertLess(p.hr_rate, 0.030)

    def test_an_outlier_is_CLAMPED(self):
        """A 10x barrel rate must not produce a 10x home-run rate."""
        p = self._run({"bbe": 300, "barrel_pct": 80.0, "hard_hit_pct": 40.0}, weight=1.0)
        self.assertLessEqual(p.hr_rate, 0.030 * bbmod._MULT_MAX + 1e-12)

    def test_larger_weight_moves_further(self):
        lo = self._run({"bbe": 300, "barrel_pct": 16.0, "hard_hit_pct": 40.0}, weight=0.20)
        hi = self._run({"bbe": 300, "barrel_pct": 16.0, "hard_hit_pct": 40.0}, weight=0.60)
        self.assertGreater(hi.hr_rate, lo.hr_rate)


if __name__ == "__main__":
    unittest.main()


class ProductionCallSiteTests(unittest.TestCase):
    """The blend must be REACHED by the roster build, not merely importable.

    This class exists because the first version of this module had ZERO
    production callers: it was fully implemented, had nine passing tests, and
    was wired to nothing. Every test above would have passed forever while the
    feature did nothing in production.

    `learnings.md` 2026-08-17 already carried the rule ("write the reachability
    assertion FIRST") and I broke it anyway on the very next feature, so the
    check is encoded here rather than left to discipline.
    """

    def test_build_roster_imports_and_calls_the_blend(self) -> None:
        from pathlib import Path
        src = Path("vendor/mlb_bettingv2/sim_engine/data/build_roster.py").read_text(
            encoding="utf-8")
        self.assertIn("from .batted_ball import apply_batted_ball_to_batter", src,
                      "build_roster does not import the blend")
        self.assertIn("apply_batted_ball_to_batter(", src,
                      "build_roster imports the blend but never calls it")

    def test_the_weight_gate_defaults_to_off(self) -> None:
        import os
        from unittest import mock
        from vendor.mlb_bettingv2.sim_engine.data.build_roster import _batted_ball_weight
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SYNDICATE_MLB_BATTED_BALL_WEIGHT", None)
            self.assertEqual(_batted_ball_weight(), 0.0)

    def test_a_malformed_weight_reads_as_off_not_on(self) -> None:
        import os
        from unittest import mock
        from vendor.mlb_bettingv2.sim_engine.data.build_roster import _batted_ball_weight
        for junk in ("banana", "", "  "):
            with mock.patch.dict(os.environ, {"SYNDICATE_MLB_BATTED_BALL_WEIGHT": junk}):
                self.assertEqual(_batted_ball_weight(), 0.0, f"junk {junk!r} enabled it")

    def test_a_set_weight_is_honoured_and_clamped(self) -> None:
        import os
        from unittest import mock
        from vendor.mlb_bettingv2.sim_engine.data.build_roster import _batted_ball_weight
        with mock.patch.dict(os.environ, {"SYNDICATE_MLB_BATTED_BALL_WEIGHT": "0.35"}):
            self.assertAlmostEqual(_batted_ball_weight(), 0.35)
        with mock.patch.dict(os.environ, {"SYNDICATE_MLB_BATTED_BALL_WEIGHT": "9.0"}):
            self.assertEqual(_batted_ball_weight(), 1.0)
