"""Phase-1 smoke/regression tests for the Syndicate-owned ``hockeysim`` engine.

These lock the absorbed engine's public contract: determinism under a fixed seed, sane score
ranges, event-stream integrity (goals are a subset of shots in the default ``from_shots``
model), and that the calibration-profile seam is non-mutating. Network-free / fully synthetic.
"""
from __future__ import annotations

import statistics
import unittest

from syndicate.features.nhl.sim_engine.hockeysim import (
    NHL_CALIBRATION_PROFILE,
    RateModels,
    TeamRates,
    build_nhl_sim_config,
    run_hockeysim_game,
)


def _roster(team: str, base_pid: int) -> list[dict]:
    """A plausible 12F / 6D / 1G roster with descending TOI."""
    rows: list[dict] = []
    pid = base_pid
    for i in range(12):  # forwards
        rows.append({"player_id": pid, "full_name": f"{team} F{i+1}", "position": "F",
                     "proj_toi": 20.0 - i * 0.9})
        pid += 1
    for i in range(6):  # defense
        rows.append({"player_id": pid, "full_name": f"{team} D{i+1}", "position": "D",
                     "proj_toi": 22.0 - i * 2.0})
        pid += 1
    rows.append({"player_id": pid, "full_name": f"{team} G1", "position": "G", "proj_toi": 60.0})
    return rows


def _rates() -> RateModels:
    return RateModels(
        home=TeamRates(shots_per_60=31.0, goals_per_60=3.1, blocks_per_60=13.0,
                       penalties_per_60=3.0, faceoff_win_pct=0.51),
        away=TeamRates(shots_per_60=29.5, goals_per_60=2.8, blocks_per_60=12.0,
                       penalties_per_60=3.0, faceoff_win_pct=0.49),
        player_rates={},
    )


class HockeySimEngineTest(unittest.TestCase):
    def test_determinism_same_seed(self) -> None:
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        gs1, ev1 = run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), seed=42)
        gs2, ev2 = run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), seed=42)
        self.assertEqual((gs1.home.score, gs1.away.score), (gs2.home.score, gs2.away.score))
        self.assertEqual(len(ev1), len(ev2))

    def test_different_seeds_can_differ(self) -> None:
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        scores = {
            run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), seed=s)[0].home.score
            for s in range(12)
        }
        self.assertGreater(len(scores), 1, "seed should drive stochastic variation")

    def test_score_ranges_are_sane(self) -> None:
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        totals = []
        for s in range(60):
            gs, _ = run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), seed=s)
            self.assertLessEqual(0, gs.home.score)
            self.assertLessEqual(0, gs.away.score)
            self.assertLess(gs.home.score, 15)
            self.assertLess(gs.away.score, 15)
            totals.append(gs.home.score + gs.away.score)
        # NHL combined regulation+OT total sits roughly in the 5-8 goal band on average.
        self.assertTrue(4.0 < statistics.mean(totals) < 9.0, statistics.mean(totals))

    def test_goals_subset_of_shots_default_model(self) -> None:
        # Default goal_model == "from_shots": lineup path emits every goal as a shot too.
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        gs, events = run_hockeysim_game(
            "HOME", "AWAY", rh, ra, _rates(),
            lineup_home=lineup_h, lineup_away=lineup_a, seed=7,
        )
        shots = sum(1 for e in events if e.kind == "shot" and e.team == "HOME")
        goals = sum(1 for e in events if e.kind == "goal" and e.team == "HOME")
        self.assertLessEqual(goals, shots)

    def test_special_teams_pp_pct_actually_changes_output(self) -> None:
        """Reachability test (`model_engine_standard.md` §4.3), not just presence: `st_home`'s
        `pp_pct` must MEASURABLY change simulated output, not just sit on the dataclass unread.

        Requires the lineup path (`lineup_home`/`lineup_away` not None) -- `st_home`/`st_away`
        are ignored on the roster-only path (`runtime.run_hockeysim_game`).
        """
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        elite_pp = {"pp_pct": 0.35, "pk_pct": 0.80, "committed_per_game": 3.0}
        poor_pp = {"pp_pct": 0.08, "pk_pct": 0.80, "committed_per_game": 3.0}

        def _mean_home_goals(st_home: dict) -> float:
            totals = []
            for s in range(80):
                gs, _ = run_hockeysim_game(
                    "HOME", "AWAY", rh, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a,
                    st_home=st_home, st_away={"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.0},
                    seed=s,
                )
                totals.append(gs.home.score)
            return statistics.mean(totals)

        elite_mean = _mean_home_goals(elite_pp)
        poor_mean = _mean_home_goals(poor_pp)
        self.assertGreater(
            elite_mean, poor_mean,
            f"an elite power play (pp_pct=0.35) must outscore a poor one (pp_pct=0.08) on average "
            f"when nothing else differs -- got elite={elite_mean:.3f} poor={poor_mean:.3f}. If this "
            f"fails, st_home is present but not reachable, the exact defect this test exists to catch.",
        )

    def test_profile_seam_is_non_mutating(self) -> None:
        before = NHL_CALIBRATION_PROFILE.pp_shots_mult
        cfg = build_nhl_sim_config(seed=5, overrides={"pp_shots_mult": 9.9, "bogus": 1})
        self.assertEqual(cfg.pp_shots_mult, 9.9)
        self.assertEqual(cfg.seed, 5)
        self.assertFalse(hasattr(cfg, "bogus"))
        # Shared baseline untouched.
        self.assertEqual(NHL_CALIBRATION_PROFILE.pp_shots_mult, before)
        self.assertIsNone(NHL_CALIBRATION_PROFILE.seed)


if __name__ == "__main__":
    unittest.main()
