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


# ---------------------------------------------------------------------------
# Team rates (`shots_per_60`/`blocks_per_60`/`penalties_per_60`/`faceoff_win_pct`) --
# `docs/ai_context/hockeysim_engine_reference.md` §2j. `shots_per_60`/`faceoff_win_pct` are
# CONSUMED all the way through `engine.py`'s shot-volume lambda; `blocks_per_60`/`penalties_per_60`
# are CONSUMED only as far as `TeamRates` construction (`player_props._team_rates`) and then never
# read by `engine.py` at all -- a genuine dead gate, the same shape as basketball's `#467`. These
# tests prove BOTH the reachable and the unreachable cases with real assertions, not code-reading.
# ---------------------------------------------------------------------------


def _game_with(home_overrides: dict, away_overrides: dict) -> HockeyGameFeatures:
    home_kwargs = {"shots_per_60": 30.0, "goals_per_60": 3.0, **home_overrides}
    away_kwargs = {"shots_per_60": 30.0, "goals_per_60": 3.0, **away_overrides}
    home = HockeyTeamFeatures(name="HOME", **home_kwargs)
    away = HockeyTeamFeatures(name="AWAY", **away_kwargs)
    return HockeyGameFeatures(
        game_pk="2026020099", date="2026-03-15", home=home, away=away,
        home_players=_players("HOME", 1000), away_players=_players("AWAY", 2000),
    )


class TeamRatesReachabilityTest(unittest.TestCase):
    def _mean_team_sog(self, game: HockeyGameFeatures, team: str, n_sims: int) -> float:
        projs = build_prop_projections(game, n_sims=n_sims, base_seed=777)
        totals = [p.proj for p in projs if p.market == "SOG" and p.team == team]
        return sum(totals) / len(totals) if totals else 0.0

    def test_shots_per_60_actually_changes_sog_projection(self) -> None:
        heavy = _game_with({"shots_per_60": 40.0}, {"shots_per_60": 20.0})
        heavy_sog = self._mean_team_sog(heavy, "HOME", n_sims=60)
        light = _game_with({"shots_per_60": 20.0}, {"shots_per_60": 40.0})
        light_sog = self._mean_team_sog(light, "HOME", n_sims=60)
        self.assertGreater(heavy_sog, light_sog,
                            "HOME shots_per_60=40 should out-shoot HOME shots_per_60=20")

    def test_faceoff_win_pct_actually_changes_sog_projection(self) -> None:
        strong = _game_with({"faceoff_win_pct": 0.65}, {"faceoff_win_pct": 0.35})
        strong_sog = self._mean_team_sog(strong, "HOME", n_sims=60)
        weak = _game_with({"faceoff_win_pct": 0.35}, {"faceoff_win_pct": 0.65})
        weak_sog = self._mean_team_sog(weak, "HOME", n_sims=60)
        self.assertGreater(strong_sog, weak_sog,
                            "HOME winning more faceoffs should raise its own shot volume")

    def test_blocks_per_60_is_a_dead_gate_not_reachable(self) -> None:
        """`blocks_per_60` reaches `TeamRates` (`player_props._team_rates`) but `engine.py` never
        reads `rates.home.blocks_per_60`/`rates.away.blocks_per_60` -- confirmed by grep AND, here,
        by a deterministic same-seed run: an extreme swing (3.0 -> 60.0) produces a BYTE-IDENTICAL
        projection set. Real block generation is governed entirely by `special_teams_cal`'s
        `block_rate_ev`/`pk`/`pp_def` (§2g/§2h), a genuinely different mechanism -- this is NOT a
        missing wiring step, it is confirmed dead code on `TeamRates.blocks_per_60`."""
        low = _game_with({"blocks_per_60": 3.0}, {"blocks_per_60": 3.0})
        high = _game_with({"blocks_per_60": 60.0}, {"blocks_per_60": 60.0})
        low_projs = build_prop_projections(low, n_sims=40, base_seed=555)
        high_projs = build_prop_projections(high, n_sims=40, base_seed=555)
        low_by_key = {(p.player_id, p.market): p.proj for p in low_projs}
        high_by_key = {(p.player_id, p.market): p.proj for p in high_projs}
        self.assertEqual(low_by_key, high_by_key)

    def test_penalties_per_60_is_a_dead_gate_not_reachable(self) -> None:
        """Same finding as `blocks_per_60` above, for `penalties_per_60` -- no PIM/penalty market
        or mechanism reads it anywhere in `engine.py`."""
        low = _game_with({"penalties_per_60": 1.0}, {"penalties_per_60": 1.0})
        high = _game_with({"penalties_per_60": 12.0}, {"penalties_per_60": 12.0})
        low_projs = build_prop_projections(low, n_sims=40, base_seed=555)
        high_projs = build_prop_projections(high, n_sims=40, base_seed=555)
        low_by_key = {(p.player_id, p.market): p.proj for p in low_projs}
        high_by_key = {(p.player_id, p.market): p.proj for p in high_projs}
        self.assertEqual(low_by_key, high_by_key)


if __name__ == "__main__":
    unittest.main()
