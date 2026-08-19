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
        home=TeamRates(shots_per_60=31.0, goals_per_60=3.1, faceoff_win_pct=0.51),
        away=TeamRates(shots_per_60=29.5, goals_per_60=2.8, faceoff_win_pct=0.49),
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

    def test_special_teams_pp_shot_index_actually_changes_shot_volume(self) -> None:
        """Reachability test for the NEW per-team mechanism (`docs/ai_context/hockeysim_engine_reference.md`
        §2f): `pp_shot_index`/`pk_shot_index_allowed` on `st_home`/`st_away` -- distinct from
        `pp_pct` above (goal CONVERSION) and from `special_teams_cal`'s league-wide multipliers
        (calibration constants) -- must measurably change simulated SHOT volume, not goal count.
        """
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        base = {"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.0}
        high_index = dict(base, pp_shot_index=1.8)
        low_index = dict(base, pp_shot_index=0.4)
        away_neutral = dict(base, pk_shot_index_allowed=1.0)

        def _mean_home_shots(st_home: dict) -> float:
            totals = []
            for s in range(80):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", rh, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a,
                    st_home=st_home, st_away=away_neutral, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "shot" and e.team == "HOME"))
            return statistics.mean(totals)

        high_mean = _mean_home_shots(high_index)
        low_mean = _mean_home_shots(low_index)
        self.assertGreater(
            high_mean, low_mean,
            f"pp_shot_index=1.8 must produce more HOME shots on average than pp_shot_index=0.4 "
            f"when nothing else differs -- got high={high_mean:.3f} low={low_mean:.3f}. If this "
            f"fails, pp_shot_index is present on HockeyTeamFeatures.special_teams but not "
            f"reachable in engine.py.",
        )

    def test_special_teams_block_rate_index_actually_changes_block_volume(self) -> None:
        """Reachability test for the LAST per-team special-teams mechanism
        (`docs/ai_context/hockeysim_engine_reference.md` §2g): `block_rate_index` on
        `st_home`/`st_away` must measurably change simulated BLOCK volume for the team doing the
        blocking -- distinct from `pp_shot_index` (shots taken) and `pp_pct` (goals scored).
        """
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        base = {"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.0}
        heavy_blocker = dict(base, block_rate_index=1.8)
        light_blocker = dict(base, block_rate_index=0.3)

        def _mean_home_blocks(st_home: dict) -> float:
            totals = []
            for s in range(80):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", rh, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a,
                    st_home=st_home, st_away=base, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "block" and e.team == "HOME"))
            return statistics.mean(totals)

        heavy_mean = _mean_home_blocks(heavy_blocker)
        light_mean = _mean_home_blocks(light_blocker)
        self.assertGreater(
            heavy_mean, light_mean,
            f"block_rate_index=1.8 must produce more HOME blocks on average than "
            f"block_rate_index=0.3 when nothing else differs -- got heavy={heavy_mean:.3f} "
            f"light={light_mean:.3f}. If this fails, block_rate_index is present on "
            f"HockeyTeamFeatures.special_teams but not reachable in engine.py.",
        )

    def test_player_shot_weight_actually_differentiates_shot_share(self) -> None:
        """Reachability test for `HockeyPlayerFeatures.shot_weight` (`docs/ai_context/
        hockeysim_engine_reference.md` §2k, the last genuinely-absent input this document tracked).
        UNLIKE the team-rates dead gate (§2j), this one is ALREADY consumed by `_weighted_choice`
        -- this proves it, at the roster-row level `run_hockeysim_game` actually reads, not just
        by grepping the source. Two forwards at IDENTICAL `proj_toi` (so the position/TOI fallback
        heuristic alone would treat them identically) differ ONLY in `shot_weight`."""
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        rh[0]["proj_toi"] = rh[1]["proj_toi"] = 18.0  # remove TOI as a confound
        star_id = rh[0]["player_id"]
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]

        def _mean_star_shots(shot_weight: float) -> float:
            roster = [dict(r) for r in rh]
            roster[0]["shot_weight"] = shot_weight
            totals = []
            for s in range(80):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", roster, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "shot" and e.player_id == star_id))
            return statistics.mean(totals)

        high_mean = _mean_star_shots(8.0)
        low_mean = _mean_star_shots(0.2)
        self.assertGreater(
            high_mean, low_mean,
            f"shot_weight=8.0 must produce more shots credited to that player on average than "
            f"shot_weight=0.2 when TOI/position are held identical -- got high={high_mean:.3f} "
            f"low={low_mean:.3f}. If this fails, shot_weight is present on HockeyPlayerFeatures "
            f"but not reachable in engine.py's _weighted_choice.",
        )

    def test_player_block_weight_actually_differentiates_block_share(self) -> None:
        """Same proof as `shot_weight` above, for `block_weight` -- a defenseman's own block
        credit share, distinct from the per-TEAM `block_rate_index` mechanism (§2g), which governs
        how many total blocks a team records, not WHICH skater gets credited for each one."""
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        # defensemen are indices 12/13 in `_roster`'s layout (12 forwards, then 6 defense)
        rh[12]["proj_toi"] = rh[13]["proj_toi"] = 20.0
        blocker_id = rh[12]["player_id"]
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]

        def _mean_blocker_blocks(block_weight: float) -> float:
            roster = [dict(r) for r in rh]
            roster[12]["block_weight"] = block_weight
            totals = []
            for s in range(80):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", roster, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "block" and e.player_id == blocker_id))
            return statistics.mean(totals)

        high_mean = _mean_blocker_blocks(6.0)
        low_mean = _mean_blocker_blocks(0.1)
        self.assertGreater(
            high_mean, low_mean,
            f"block_weight=6.0 must produce more blocks credited to that defenseman on average "
            f"than block_weight=0.1 when TOI/position are held identical -- got high={high_mean:.3f} "
            f"low={low_mean:.3f}.",
        )

    def test_player_goal_weight_actually_differentiates_finishing_rate(self) -> None:
        """Same proof as `shot_weight`/`block_weight` above, for `goal_weight` -- this one drives
        `engine.py`'s per-shot FINISHING multiplier (`goal_weight`/`shot_weight` ratio), not
        attribution volume, so `shot_weight` is held FIXED across both variants and only the
        GOALS credited to that shooter (not shots taken) should differ."""
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        rh[0]["proj_toi"] = 18.0
        rh[0]["shot_weight"] = 4.0  # held fixed -- only goal_weight varies below
        sniper_id = rh[0]["player_id"]
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]

        def _mean_sniper_goals(goal_weight: float) -> float:
            roster = [dict(r) for r in rh]
            roster[0]["goal_weight"] = goal_weight
            totals = []
            for s in range(120):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", roster, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "goal" and e.player_id == sniper_id))
            return statistics.mean(totals)

        high_mean = _mean_sniper_goals(3.6)   # gw/sw ratio 0.9 -- elite finisher
        low_mean = _mean_sniper_goals(0.2)    # gw/sw ratio 0.05 -- poor finisher
        self.assertGreater(
            high_mean, low_mean,
            f"goal_weight=3.6 (high gw/sw ratio) must produce more goals for that shooter on "
            f"average than goal_weight=0.2 (low ratio), with shot_weight held fixed -- got "
            f"high={high_mean:.3f} low={low_mean:.3f}.",
        )

    def test_special_teams_cal_pp_goal_mult_actually_changes_output(self) -> None:
        """Reachability test for the OTHER special-teams parameter: `special_teams_cal`
        (`pp_goal_cal_mult` etc, sourced from `SimConfig` via `player_props._special_teams_cal`).

        This was CONSUMED with no caller anywhere supplying it a value -- UNREACHABLE, a stricter
        defect than unpopulated (`hockeysim_engine_reference.md` §2b). Proves the NEW wiring
        (SimConfig fields -> `player_props.build_prop_projections` -> `special_teams_cal=`) actually
        changes simulated output, not just that the plumbing runs without raising.
        """
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        st = {"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.0}
        low_cal = {"pp_shot_multiplier": 1.0, "pk_shot_multiplier": 1.0,
                   "pp_goal_multiplier": 0.5, "pk_goal_multiplier": 1.0,
                   "blocks_ev_rate": 0.45, "blocks_pk_rate": 0.55, "blocks_pp_def_rate": 0.35}
        high_cal = dict(low_cal, pp_goal_multiplier=2.5)

        def _mean_home_goals(cal: dict) -> float:
            totals = []
            for s in range(80):
                gs, _ = run_hockeysim_game(
                    "HOME", "AWAY", rh, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a,
                    st_home=st, st_away=st, special_teams_cal=cal, seed=s,
                )
                totals.append(gs.home.score)
            return statistics.mean(totals)

        low_mean = _mean_home_goals(low_cal)
        high_mean = _mean_home_goals(high_cal)
        self.assertGreater(
            high_mean, low_mean,
            f"pp_goal_multiplier=2.5 must outscore pp_goal_multiplier=0.5 on average when nothing "
            f"else differs -- got high={high_mean:.3f} low={low_mean:.3f}. If this fails, "
            f"special_teams_cal is present but not reachable, the exact defect this test exists to "
            f"catch.",
        )

    def test_special_teams_cal_pp_shot_mult_actually_changes_shot_volume(self) -> None:
        """Reachability test for `pp_shot_cal_mult`/`pk_shot_cal_mult` specifically -- distinct
        from the goal-multiplier test above, since shot VOLUME (this test) and goal CONVERSION
        (the sibling test) are separate mechanisms in `engine.py` (`pp_mult_shots` vs
        `p_goal_home`), calibrated separately (`scripts/calibrate_nhl_special_teams_shot_mult.py`,
        `hockeysim_engine_reference.md` §2e) against a real per-team `pp_pct`/`pk_pct` -- the
        SHOT-count events, not goal events.
        """
        rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
        lineup_h = [{"player_id": r["player_id"], "line_slot": None} for r in rh]
        lineup_a = [{"player_id": r["player_id"], "line_slot": None} for r in ra]
        st = {"pp_pct": 0.2, "pk_pct": 0.8, "committed_per_game": 3.0}
        low_cal = {"pp_shot_multiplier": 0.4, "pk_shot_multiplier": 1.0,
                   "pp_goal_multiplier": 1.0, "pk_goal_multiplier": 1.0,
                   "blocks_ev_rate": 0.45, "blocks_pk_rate": 0.55, "blocks_pp_def_rate": 0.35}
        high_cal = dict(low_cal, pp_shot_multiplier=2.0)

        def _mean_home_shots(cal: dict) -> float:
            totals = []
            for s in range(80):
                gs, events = run_hockeysim_game(
                    "HOME", "AWAY", rh, ra, _rates(),
                    lineup_home=lineup_h, lineup_away=lineup_a,
                    st_home=st, st_away=st, special_teams_cal=cal, seed=s,
                )
                totals.append(sum(1 for e in events if e.kind == "shot" and e.team == "HOME"))
            return statistics.mean(totals)

        low_mean = _mean_home_shots(low_cal)
        high_mean = _mean_home_shots(high_cal)
        self.assertGreater(
            high_mean, low_mean,
            f"pp_shot_multiplier=2.0 must produce more HOME shots on average than "
            f"pp_shot_multiplier=0.4 when nothing else differs -- got high={high_mean:.3f} "
            f"low={low_mean:.3f}. If this fails, pp_shot_cal_mult is present but not reachable.",
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
