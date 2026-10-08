"""Penalty-kill on-ice selection by SH minutes (`SimConfig.pk_usage`, lane nhl-pk-units).

Reachability first (model_engine_standard.md): "minutes" must change who kills penalties, the default must
be the fixed-unit path, and a player with no SH minutes must never be drawn. Network-free / synthetic.
"""
from __future__ import annotations

import collections
import unittest
from dataclasses import replace

from syndicate.features.nhl.sim_engine.hockeysim import NHL_CALIBRATION_PROFILE, RateModels, TeamRates, run_hockeysim_game
from syndicate.features.nhl.sim_engine.hockeysim.engine import SimConfig
from syndicate.features.nhl.sim_engine.hockeysim.features.loaders import _proj_sh_toi

ST = {"pp_pct": 0.2, "pk_pct": 0.8, "drawn_per_game": 3.4, "committed_per_game": 3.4}
# PK minutes per game: a real-looking spread (two heavy killers per position, a tail, and zeros)
SH_F = [2.4, 2.2, 1.6, 1.4, 0.6, 0.4, 0.2, 0.1, 0.0, 0.0, 0.0, 0.0]
SH_D = [2.6, 2.3, 1.5, 1.2, 0.3, 0.0]


def _roster(team: str, base: int) -> list[dict]:
    rows = [{"player_id": base + i, "full_name": f"{team} F{i}", "position": "F", "proj_toi": 20.0 - i * 0.9,
             "proj_sh_toi": SH_F[i]} for i in range(12)]
    rows += [{"player_id": base + 20 + i, "full_name": f"{team} D{i}", "position": "D", "proj_toi": 22.0 - i * 2.0,
              "proj_sh_toi": SH_D[i]} for i in range(6)]
    rows.append({"player_id": base + 30, "full_name": f"{team} G", "position": "G", "proj_toi": 60.0})
    return rows


def _lineup(base: int) -> list[dict]:
    rows = [{"player_id": base + line * 3 + k, "line_slot": f"L{line + 1}"} for line in range(4) for k in range(3)]
    rows += [{"player_id": base + 20 + pair * 2 + k, "line_slot": f"D{pair + 1}"} for pair in range(3) for k in range(2)]
    pk = {base + 0: 1, base + 1: 1, base + 20: 1, base + 21: 1, base + 2: 2, base + 3: 2, base + 22: 2, base + 23: 2}
    # PP units too: the engine's away-PP branch requires them (`elif seg_is_away_pp and pp_away`)
    pp = {base + 0: 1, base + 1: 1, base + 2: 1, base + 3: 1, base + 20: 1,
          base + 4: 2, base + 5: 2, base + 6: 2, base + 7: 2, base + 22: 2}
    for r in rows:
        r["pk_unit"] = pk.get(r["player_id"])
        r["pp_unit"] = pp.get(r["player_id"])
    return rows


def _rates() -> RateModels:
    return RateModels(home=TeamRates(shots_per_60=31.0, goals_per_60=3.1, faceoff_win_pct=0.51),
                      away=TeamRates(shots_per_60=29.5, goals_per_60=2.8, faceoff_win_pct=0.49), player_rates={})


def _pk_seconds(profile: SimConfig, seeds: range):
    rh, ra = _roster("HOME", 1000), _roster("AWAY", 2000)
    sec = collections.Counter()
    digest = []
    for s in seeds:
        _gs, ev = run_hockeysim_game("HOME", "AWAY", rh, ra, _rates(), st_home=dict(ST), st_away=dict(ST),
                                     lineup_home=_lineup(1000), lineup_away=_lineup(2000), profile=profile, seed=s)
        for e in ev:
            if e.kind == "shift" and e.team == "HOME" and (e.meta or {}).get("strength") == "PK" and e.player_id not in (1030,):
                sec[int(e.player_id)] += float(e.meta.get("dur", 0.0))
        digest.append([(e.kind, e.team, e.player_id, round(e.t, 6)) for e in ev])
    return sec, digest


class PKUsageTest(unittest.TestCase):
    def test_default_is_units(self) -> None:
        self.assertEqual(SimConfig().pk_usage, "units")

    def test_production_profile_ships_minutes(self) -> None:
        self.assertEqual(NHL_CALIBRATION_PROFILE.pk_usage, "minutes")

    def test_minutes_is_reachable_and_spreads_pk_time(self) -> None:
        seeds = range(25)
        units, d_units = _pk_seconds(replace(NHL_CALIBRATION_PROFILE, pk_usage="units"), seeds)
        mins, d_mins = _pk_seconds(replace(NHL_CALIBRATION_PROFILE, pk_usage="minutes"), seeds)
        self.assertNotEqual(d_units, d_mins)  # off != on
        pk1 = {1000, 1001, 1020, 1021}
        share = lambda c, ids: sum(c[i] for i in ids) / max(1e-9, sum(c.values()))
        # fixed units concentrate PK time on PK1; minutes follow the SH-minute distribution (~0.53 here)
        self.assertGreater(share(units, pk1), share(mins, pk1) + 0.10)
        # a skater outside both units but with SH minutes now kills penalties
        self.assertEqual(units[1004], 0.0)
        self.assertGreater(mins[1004], 0.0)
        # a skater with no SH minutes is never drawn
        self.assertEqual(mins[1008], 0.0)

    def test_proj_sh_toi_derived_from_existing_columns(self) -> None:
        self.assertEqual(_proj_sh_toi({"proj_sh_toi": "1.75"}), 1.75)
        self.assertAlmostEqual(_proj_sh_toi({"proj_toi": "20.0", "proj_ev_toi": "16.5", "proj_pp_toi": "2.0"}), 1.5)
        self.assertIsNone(_proj_sh_toi({"proj_toi": "20.0", "proj_ev_toi": ""}))


if __name__ == "__main__":
    unittest.main()
