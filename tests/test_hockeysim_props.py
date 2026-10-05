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
    TeamRates,
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
# Team rates (`shots_per_60`/`faceoff_win_pct`) -- `docs/ai_context/hockeysim_engine_reference.md`
# §2j. Both are CONSUMED all the way through `engine.py`'s shot-volume lambda, proven below.
# `blocks_per_60`/`penalties_per_60` were CONSUMED only as far as `TeamRates` construction
# (`player_props._team_rates`) and never read by `engine.py` at all -- a genuine dead gate, the
# same shape as basketball's `#467`, proven the same way (a byte-identical-output test) before
# being REMOVED from both dataclasses entirely (§2l). The regression tests below guard against
# either field quietly coming back without a real consumer.
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

    def test_blocks_per_60_field_stays_removed(self) -> None:
        """`blocks_per_60` was a confirmed dead gate (populated into `TeamRates`, never read by
        `engine.py` -- proven via a byte-identical-output test before removal) and was deleted from
        both `HockeyTeamFeatures` and `TeamRates` (§2l) rather than force-wired into a mechanism
        that would double-count against the already-calibrated `block_rate_*` signal. This regression
        test fails loudly if the field quietly comes back without a real consumer alongside it."""
        self.assertNotIn("blocks_per_60", HockeyTeamFeatures.__dataclass_fields__)
        self.assertNotIn("blocks_per_60", TeamRates.__dataclass_fields__)

    def test_penalties_per_60_field_stays_removed(self) -> None:
        """Same finding and same fix as `blocks_per_60` above, for `penalties_per_60` -- no PIM
        market or mechanism ever read it, and the real penalty-rate signal already drives PP/PK
        segment generation via `special_teams`'s `committed_per_game`."""
        self.assertNotIn("penalties_per_60", HockeyTeamFeatures.__dataclass_fields__)
        self.assertNotIn("penalties_per_60", TeamRates.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()


def test_a_sim_without_the_player_counts_as_zero(monkeypatch):
    """Defect 4: the mean used to divide by the sims the player APPEARED in."""
    from syndicate.features.nhl.sim_engine.hockeysim import player_props as pp

    calls = {"i": 0}

    def fake_run(*args, **kwargs):
        calls["i"] += 1
        return object(), []

    def fake_box(gs, events, starters):
        # Player 1000 appears (with 2 shots) in every OTHER sim only.
        appears = calls["i"] % 2 == 1
        return {("HOME", 1000, 0): (2, 0, 0, 0, 0, 0)} if appears else {}

    monkeypatch.setattr(pp, "run_hockeysim_game", fake_run)
    monkeypatch.setattr(pp, "aggregate_events_to_boxscores_fast", fake_box)
    projs = pp.build_prop_projections(_game(), lines={(1000, "SOG"): 1.5}, n_sims=10, base_seed=1)
    sog = next(p for p in projs if p.player_id == 1000 and p.market == "SOG")
    assert sog.proj_lambda == 1.0          # 5 sims x 2 shots / 10 sims (was 2.0)
    assert sog.p_over == 0.5 and sog.p_under == 0.5


def test_attribution_unflattening_is_reachable_and_keeps_team_totals():
    """off != on: the production profile's unflattened attribution must give the top shooter a larger
    share than the old constants, while team totals stay where they were."""
    from dataclasses import replace

    from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config

    prod = build_nhl_sim_config()
    assert (prod.attribution_power, prod.attribution_uniform_mix, prod.attribution_share_cap) == (1.0, 0.0, 1.0)
    old = replace(prod, attribution_power=0.85, attribution_uniform_mix=0.12, attribution_share_cap=0.35)
    g = _game()
    players = [replace(p, shot_weight=(4.0 if i == 0 else 1.0)) if p.position != "G" else p
               for i, p in enumerate(g.home_players)]
    game = replace(g, home_players=tuple(players))

    def sog(profile):
        projs = build_prop_projections(game, n_sims=60, profile=profile, base_seed=9)
        home = [p for p in projs if p.market == "SOG" and p.player_id < 2000]
        return next(p.proj_lambda for p in home if p.player_id == 1000), sum(p.proj_lambda for p in home)

    star_old, team_old = sog(old)
    star_new, team_new = sog(prod)
    assert star_new > star_old * 1.15
    assert abs(team_new - team_old) / team_old < 0.05


def test_ev_minutes_rotation_is_reachable():
    """off != on: when L1's minutes are mostly PP time, EV rotation by EV minutes gives L1 less ice."""
    from dataclasses import replace

    g = _game()

    def l1_sog(with_ev: bool):
        players = []
        for i, p in enumerate(g.home_players):
            if p.position != "G" and with_ev:
                ev = (p.proj_toi - 6.0) if i < 3 else p.proj_toi    # L1 carries 6 PP minutes a game
                p = replace(p, proj_ev_toi=ev)
            players.append(p)
        projs = build_prop_projections(replace(g, home_players=tuple(players)), n_sims=60, base_seed=17)
        return sum(p.proj_lambda for p in projs if p.market == "SOG" and p.player_id in (1000, 1001, 1002))

    assert l1_sog(True) < l1_sog(False) * 0.95


def test_line_quality_is_reachable_and_keeps_team_totals():
    """off != on: with line quality on, the strong first line out-shoots the weak fourth line by more,
    while the team's shot total stays where it was (renormalised)."""
    from dataclasses import replace

    from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config

    assert build_nhl_sim_config().line_quality_strength == 0.5      # production value
    g = _game()

    def sw(i):
        return 3.0 if i < 3 else (0.5 if 9 <= i < 12 else 1.5)
    players = [replace(p, shot_weight=sw(i)) if p.position != "G" else p for i, p in enumerate(g.home_players)]
    game = replace(g, home_players=tuple(players))

    def run(alpha):
        prof = replace(build_nhl_sim_config(), line_quality_strength=alpha)
        projs = build_prop_projections(game, n_sims=150, profile=prof, base_seed=21)
        sog = {p.player_id: p.proj_lambda for p in projs if p.market == "SOG" and p.player_id < 2000}
        return (sum(sog[pid] for pid in (1000, 1001, 1002)), sum(sog[pid] for pid in (1009, 1010, 1011)),
                sum(sog.values()))

    l1_off, l4_off, team_off = run(0.0)
    l1_on, l4_on, team_on = run(1.0)
    assert l1_on > l1_off * 1.10
    assert l4_on < l4_off * 0.95
    assert abs(team_on - team_off) / team_off < 0.04


def test_assist_share_attribution_is_reachable():
    """off != on `[lane nhl-elite-assists]`: with every skater shooting alike, a high on-ice assist share
    must pull assists toward that player only when `assist_attribution == "onice_share"`, and the team's
    assist total must not move (the per-goal assist count does not depend on who gets them)."""
    from dataclasses import replace

    from syndicate.features.nhl.sim_engine.hockeysim.calibration_profile import build_nhl_sim_config

    prod = build_nhl_sim_config()
    assert (prod.assist_attribution, prod.assist_position_power, prod.assist_share_power) == ("onice_share", 2.0, 2.0)
    g = _game()
    players = [replace(p, shot_weight=1.5, assist_share=(0.75 if i == 0 else 0.40)) if p.position != "G" else p
               for i, p in enumerate(g.home_players)]
    game = replace(g, home_players=tuple(players))

    def run(mode):
        prof = replace(build_nhl_sim_config(), assist_attribution=mode, assist_position_power=2.0, assist_share_power=2.0)
        projs = build_prop_projections(game, n_sims=150, profile=prof, base_seed=9)
        ast = {p.player_id: p.proj_lambda for p in projs if p.market == "ASSISTS" and p.player_id < 2000}
        return ast[1000], sum(ast.values())

    star_off, team_off = run("shot_proxy")
    star_on, team_on = run("onice_share")
    assert star_on > star_off * 1.3
    assert abs(team_on - team_off) / team_off < 0.05


def test_assist_share_unknown_player_uses_the_position_prior():
    """A player with no measured share is weighted at his position prior, never at zero or at a forward's."""
    from syndicate.features.nhl.sim_engine.hockeysim.state import ASSIST_SHARE_PRIOR

    assert ASSIST_SHARE_PRIOR["F"] > ASSIST_SHARE_PRIOR["D"] > 0.2
