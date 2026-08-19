"""Phase-2b tests for the hockeysim player-prop projections.

Small sim counts (network-free, synthetic rosters). Lock: skaters get skater markets, the
starting goalie gets SAVES, projections are non-negative, POINTS ~ GOALS + ASSISTS on average,
book lines produce complementary over/under, and the path is deterministic under a fixed seed.
"""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim import (
    HockeyGameFeatures,
    HockeyPlayerFeatures,
    HockeyTeamFeatures,
    build_prop_projections,
)


def _players(team: str, base: int) -> tuple[HockeyPlayerFeatures, ...]:
    out: list[HockeyPlayerFeatures] = []
    pid = base
    for i in range(12):
        out.append(HockeyPlayerFeatures(
            player_id=pid, full_name=f"{team} F{i+1}", position="F",
            proj_toi=20.0 - i * 0.9, line_slot=f"L{i // 3 + 1}"))
        pid += 1
    for i in range(6):
        out.append(HockeyPlayerFeatures(
            player_id=pid, full_name=f"{team} D{i+1}", position="D",
            proj_toi=22.0 - i * 2.0, line_slot=f"D{i // 2 + 1}"))
        pid += 1
    out.append(HockeyPlayerFeatures(
        player_id=pid, full_name=f"{team} G1", position="G",
        proj_toi=60.0, is_starting_goalie=True))
    return tuple(out)


def _game() -> HockeyGameFeatures:
    return HockeyGameFeatures(
        game_pk="2026020042", date="2026-03-15",
        home=HockeyTeamFeatures(name="HOME", shots_per_60=31.0, goals_per_60=3.1),
        away=HockeyTeamFeatures(name="AWAY", shots_per_60=29.5, goals_per_60=2.8),
        home_players=_players("HOME", 1000), away_players=_players("AWAY", 2000),
    )


class HockeySimPropsTest(unittest.TestCase):
    def test_projections_structure(self) -> None:
        projs = build_prop_projections(_game(), n_sims=40)
        self.assertTrue(projs)
        markets_by_pos = {}
        for p in projs:
            self.assertGreaterEqual(p.proj_lambda, 0.0)
            self.assertGreaterEqual(p.proj, 0.0)
            self.assertIn(p.team, ("HOME", "AWAY"))
            self.assertEqual(p.opp, "AWAY" if p.team == "HOME" else "HOME")
            markets_by_pos.setdefault(p.market, 0)
            markets_by_pos[p.market] += 1
        # Skater markets present; SAVES present (goalies).
        for m in ("SOG", "GOALS", "ASSISTS", "POINTS", "BLOCKS", "SAVES"):
            self.assertIn(m, markets_by_pos, m)

    def test_saves_only_for_goalies(self) -> None:
        projs = build_prop_projections(_game(), n_sims=40)
        game = _game()
        goalie_ids = {p.player_id for p in game.home_players + game.away_players
                      if p.position == "G"}
        for p in projs:
            if p.market == "SAVES":
                self.assertIn(p.player_id, goalie_ids)
            if p.player_id in goalie_ids:
                self.assertEqual(p.market, "SAVES")

    def test_points_consistency(self) -> None:
        # For each skater, mean POINTS ~= mean GOALS + mean ASSISTS.
        projs = build_prop_projections(_game(), n_sims=60)
        by_player: dict[int, dict[str, float]] = {}
        for p in projs:
            by_player.setdefault(p.player_id, {})[p.market] = p.proj
        for pid, m in by_player.items():
            if {"GOALS", "ASSISTS", "POINTS"} <= set(m):
                # Exact pre-rounding; allow for independent 4-dp rounding of each market mean.
                self.assertAlmostEqual(m["POINTS"], m["GOALS"] + m["ASSISTS"], delta=2e-4)

    def test_lines_produce_over_under(self) -> None:
        game = _game()
        star = game.home_players[0].player_id  # top line forward
        projs = build_prop_projections(game, n_sims=60, lines={(star, "SOG"): 2.5})
        hit = [p for p in projs if p.player_id == star and p.market == "SOG"]
        self.assertEqual(len(hit), 1)
        p = hit[0]
        self.assertIsNotNone(p.p_over)
        self.assertIsNotNone(p.p_under)
        self.assertAlmostEqual(p.p_over + p.p_under, 1.0, places=6)  # 2.5 line -> no push

    def test_deterministic(self) -> None:
        a = build_prop_projections(_game(), n_sims=30)
        b = build_prop_projections(_game(), n_sims=30)
        self.assertEqual(len(a), len(b))
        am = {(p.player_id, p.market): p.proj for p in a}
        bm = {(p.player_id, p.market): p.proj for p in b}
        self.assertEqual(am, bm)

    def test_special_teams_cal_bare_sim_config_is_the_old_neutral_fallback(self) -> None:
        """The WIRING itself (`hockeysim_engine_reference.md` §2b/§2c) must not invent behavior: a
        bare, uncalibrated `SimConfig()` must reproduce the exact values the old
        `.get(key, DEFAULT)` inline fallbacks used -- the wiring is mechanically a no-op, only the
        separate calibration pass below changes a value."""
        from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig
        from syndicate.features.nhl.sim_engine.hockeysim.player_props import _special_teams_cal

        cal = _special_teams_cal(SimConfig())
        self.assertEqual(cal, {
            "pp_shot_multiplier": 1.0, "pk_shot_multiplier": 1.0,
            "pp_goal_multiplier": 1.0, "pk_goal_multiplier": 1.0,
            "blocks_ev_rate": 0.45, "blocks_pk_rate": 0.55, "blocks_pp_def_rate": 0.35,
        })

    def test_special_teams_cal_production_default_carries_the_calibration(self) -> None:
        """`build_nhl_sim_config()` (what production actually resolves) reflects all calibration
        passes (§2d/§2e/§2h): `pk_goal_cal_mult`/`pp_shot_cal_mult`/`pk_shot_cal_mult` and the
        block-rate constants measurably corrected against real truth, `pp_goal_cal_mult` left at
        neutral (measured statistically indistinguishable from 1.0). Locks the calibrated values
        in place so a future edit to the profile constant fails a test, not silently drifts."""
        from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config
        from syndicate.features.nhl.sim_engine.hockeysim.player_props import _special_teams_cal

        cal = _special_teams_cal(build_nhl_sim_config())
        self.assertEqual(cal["pp_goal_multiplier"], 1.0)
        self.assertEqual(cal["pk_goal_multiplier"], 0.4645)
        self.assertEqual(cal["pp_shot_multiplier"], 0.9108)
        self.assertEqual(cal["pk_shot_multiplier"], 0.3369)
        # Block rates ARE now calibrated (§2h, `scripts/calibrate_nhl_block_rate.py`): a single
        # shared scale (1.0631) applied uniformly to the vendor's original 0.45/0.55/0.35,
        # preserving their structural ratio -- the only degree of freedom the truth source (one
        # league-wide blocks/game target, no strength-state breakdown) actually supports.
        self.assertEqual(cal["blocks_ev_rate"], 0.4784)
        self.assertEqual(cal["blocks_pk_rate"], 0.5847)
        self.assertEqual(cal["blocks_pp_def_rate"], 0.3721)

    def test_special_teams_cal_reflects_a_custom_profile(self) -> None:
        """A non-default `SimConfig` must actually change what `build_prop_projections` sends to
        the engine -- not just the default-profile no-op case above."""
        from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config
        from syndicate.features.nhl.sim_engine.hockeysim.player_props import _special_teams_cal

        cfg = build_nhl_sim_config(overrides={"pp_goal_cal_mult": 1.8, "block_rate_pk": 0.62})
        cal = _special_teams_cal(cfg)
        self.assertEqual(cal["pp_goal_multiplier"], 1.8)
        self.assertEqual(cal["blocks_pk_rate"], 0.62)
        # Untouched field still matches the CALIBRATED default (0.4645, not the bare-dataclass 1.0
        # -- see test_special_teams_cal_production_default_carries_the_calibration) -- confirms
        # this is an OVERRIDE on top of the real production baseline, not a reset to neutral.
        self.assertEqual(cal["pk_goal_multiplier"], 0.4645)


if __name__ == "__main__":
    unittest.main()
