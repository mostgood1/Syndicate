"""Pieces of scripts/mlb_starter_length_replay.py that decide what counts as a start.

The engine run itself is validated against production's stored sims
(`--validate-only`; 10-03: mean diff +0.09 outs over 8 starters), not here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "mlb_starter_length_replay", Path(__file__).resolve().parents[1] / "scripts" / "mlb_starter_length_replay.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)


def _box(away_first, home_first, away_ip="5.1", home_ip="2.0"):
    def team(pid, ip, extra):
        return {"pitchers": [pid, extra],
                "players": {f"ID{pid}": {"stats": {"pitching": {"inningsPitched": ip, "numberOfPitches": 88,
                                                                 "strikeOuts": 6, "hits": 4, "earnedRuns": 2,
                                                                 "baseOnBalls": 1}}}}}
    return {"teams": {"away": team(away_first, away_ip, 9), "home": team(home_first, home_ip, 8)}}


def test_the_first_pitcher_listed_is_the_starter_and_outs_come_from_ip():
    a = rp.actual_starters(_box(11, 22))
    assert a["away"]["pid"] == 11 and a["away"]["OUTS"] == 16 and a["away"]["P"] == 88
    assert a["home"]["pid"] == 22 and a["home"]["OUTS"] == 6


def test_crps_is_zero_for_a_point_mass_on_the_truth_and_grows_with_error():
    assert rp.crps_discrete([15.0] * 10, 15.0) == pytest.approx(0.0)
    assert rp.crps_discrete([15.0] * 10, 18.0) == pytest.approx(3.0)
    wide = rp.crps_discrete([10.0, 20.0] * 5, 15.0)
    assert 0 < wide < 5.0


def test_context_from_sim_rebuilds_or_degrades_to_neutral():
    rp_vendor = Path(rp.VENDOR)
    assert rp_vendor.exists()
    w, p, u = rp.context_from_sim(None)
    assert (w, p, u) == (None, None, None)
    w, p, u = rp.context_from_sim({
        "weather": {"condition": "Clear", "temperature_f": 80.0, "wind_speed_mph": 5.0, "wind_direction": "out"},
        "park": {"venue_name": "X", "multipliers": {"hr_mult": 1.05, "inplay_hit_mult": 0.99, "xb_share_mult": 1.0}},
        "umpire": {"called_strike_mult": 1.02},
    })
    assert p.multipliers().hr_mult == pytest.approx(1.05)
    assert u.multipliers().called_strike_mult == pytest.approx(1.02)


def test_boot_ci_resamples_games():
    rows = [{"game_pk": g, "v": float(g % 2)} for g in range(40) for _ in range(2)]
    est, lo, hi = rp.boot_ci(rows, lambda rs: sum(r["v"] for r in rs) / len(rs), draws=200)
    assert est == pytest.approx(0.5) and lo <= est <= hi
