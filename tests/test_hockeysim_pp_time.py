"""Team power-play TIME (`SimConfig.pp_time_model`, lane nhl-pp-time).

Reachability first (model_engine_standard.md): "per_minor" must change the simulated PP time, the
default must be the legacy path, and the env off switch must restore the legacy path exactly.
Network-free / fully synthetic.
"""
from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest import mock

from syndicate.features.nhl.sim_engine.hockeysim import (
    NHL_CALIBRATION_PROFILE,
    RateModels,
    TeamRates,
    run_hockeysim_game,
)
from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig

ST = {"pp_pct": 0.2, "pk_pct": 0.8, "drawn_per_game": 3.2, "committed_per_game": 3.2}


def _roster(team: str, base_pid: int) -> list[dict]:
    rows = [{"player_id": base_pid + i, "full_name": f"{team} F{i}", "position": "F", "proj_toi": 20.0 - i * 0.9}
            for i in range(12)]
    rows += [{"player_id": base_pid + 20 + i, "full_name": f"{team} D{i}", "position": "D", "proj_toi": 22.0 - i * 2.0}
             for i in range(6)]
    rows.append({"player_id": base_pid + 30, "full_name": f"{team} G", "position": "G", "proj_toi": 60.0})
    return rows


def _lineup(base_pid: int) -> list[dict]:
    rows = [{"player_id": base_pid + line * 3 + k, "line_slot": f"L{line + 1}"} for line in range(4) for k in range(3)]
    rows += [{"player_id": base_pid + 20 + pair * 2 + k, "line_slot": f"D{pair + 1}"} for pair in range(3) for k in range(2)]
    return rows


def _rates() -> RateModels:
    return RateModels(home=TeamRates(shots_per_60=31.0, goals_per_60=3.1, faceoff_win_pct=0.51),
                      away=TeamRates(shots_per_60=29.5, goals_per_60=2.8, faceoff_win_pct=0.49), player_rates={})


def _pp_seconds(profile: SimConfig, seeds: range) -> tuple[float, list]:
    """Mean PP seconds per team-game (the goalie is on ice every segment) and the raw event digest."""
    rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
    goalies = {1030, 2030}
    total = 0.0
    digest = []
    for s in seeds:
        _gs, ev = run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), st_home=dict(ST), st_away=dict(ST),
                                     lineup_home=_lineup(1000), lineup_away=_lineup(2000),
                                     profile=profile, seed=s)
        for e in ev:
            if e.kind == "shift" and e.player_id in goalies and (e.meta or {}).get("strength") == "PP":
                total += float(e.meta.get("dur", 0.0))
        digest.append([(e.kind, e.team, e.player_id, round(e.t, 6)) for e in ev])
    return total / (2 * len(seeds)), digest


class PPTimeModelTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, {"SYNDICATE_NHL_PP_TIME_MODEL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_legacy(self) -> None:
        self.assertEqual(SimConfig().pp_time_model, "minors_2min")
        self.assertEqual(SimConfig().pp_seconds_per_minor, 120.0)

    def test_per_minor_is_reachable_and_scales_pp_time(self) -> None:
        seeds = range(40)
        legacy, d_legacy = _pp_seconds(NHL_CALIBRATION_PROFILE, seeds)
        per_minor, d_new = _pp_seconds(replace(NHL_CALIBRATION_PROFILE, pp_time_model="per_minor",
                                               pp_seconds_per_minor=88.0), seeds)
        self.assertNotEqual(d_legacy, d_new)  # off != on
        # legacy: 3.2 minors x 120 s = 384 s of PP per team in regulation (plus a capped OT window)
        self.assertGreater(legacy, 330.0)
        # per_minor: 3.2 x 88 = 281.6 s; the ratio tracks 88/120 within Monte Carlo noise
        self.assertLess(per_minor, legacy)
        self.assertAlmostEqual(per_minor / legacy, 88.0 / 120.0, delta=0.08)

    def test_per_minor_at_120_matches_legacy_in_regulation_scale(self) -> None:
        # 120 s per minor reproduces the legacy regulation rate; only OT differs (regulation rate vs
        # the legacy OT-window denominator), so the two stay close but OT can make them differ.
        seeds = range(40)
        legacy, _ = _pp_seconds(NHL_CALIBRATION_PROFILE, seeds)
        same_rate, _ = _pp_seconds(replace(NHL_CALIBRATION_PROFILE, pp_time_model="per_minor",
                                           pp_seconds_per_minor=120.0), seeds)
        self.assertLessEqual(same_rate, legacy + 1e-9)
        self.assertGreater(same_rate / legacy, 0.9)

    def test_env_off_switch_restores_legacy_exactly(self) -> None:
        seeds = range(10)
        _, d_legacy = _pp_seconds(NHL_CALIBRATION_PROFILE, seeds)
        with mock.patch.dict(os.environ, {"SYNDICATE_NHL_PP_TIME_MODEL": "minors_2min"}):
            _, d_off = _pp_seconds(replace(NHL_CALIBRATION_PROFILE, pp_time_model="per_minor",
                                           pp_seconds_per_minor=88.0), seeds)
        self.assertEqual(d_legacy, d_off)


if __name__ == "__main__":
    unittest.main()
