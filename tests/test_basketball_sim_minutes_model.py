"""WNBA smart-sim minutes without rotation history (lane wnba-sim-minutes-model).

The vendored `_derive_sim_minutes` shrank every candidate's rolling minutes by
total/sum -- 11 LVA candidates summing to 232 on 2026-10-01 -> x0.862, A'ja
Wilson 30.5 -> 26.3. Backtest vs actual box minutes (36 games, 869 rows):
bench-first water-fill MAE 5.785 vs 6.019, 95% CI [-0.336, -0.130].
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from syndicate.features.shared import basketball_props_smart_sim as sim

LVA = np.array([30.5, 31.1, 29.6, 19.7, 21.3, 24.2, 20.7, 16.6, 13.3, 12.8, 12.25])  # sums to ~232


def test_water_fill_takes_the_same_minutes_off_everyone_and_keeps_the_total():
    out = sim._water_fill_minutes_local(LVA, total=200.0, caps=None)
    assert out.sum() == pytest.approx(200.0)
    cut = LVA - out
    assert np.allclose(cut[out > 0], cut[out > 0][0])  # equal reduction for everyone still playing
    # The star keeps far more than the proportional x0.862 would leave her.
    proportional = 30.5 * (200.0 / LVA.sum())  # 26.3, what the vendor gave her
    assert out[0] == pytest.approx(30.5 - (LVA.sum() - 200.0) / len(LVA), abs=1e-6)  # 27.6
    assert out[0] > proportional + 1.0


def test_water_fill_floors_at_zero_and_respects_caps():
    base = np.array([38.0, 36.0, 34.0, 30.0, 28.0, 22.0, 18.0, 12.0, 8.0])  # 226; 220 under the caps
    out = sim._water_fill_minutes_local(base, total=200.0, caps=np.array([34.0] * 9))
    assert out.sum() == pytest.approx(200.0)
    assert out.max() <= 34.0 + 1e-6 and out.min() >= 0.0
    assert out[-1] < 8.0 and out[0] == pytest.approx(34.0)  # bench absorbs it; the capped star stays capped


def test_water_fill_refuses_when_caps_bind():
    assert sim._water_fill_minutes_local(np.array([30.0] * 8), total=200.0, caps=np.array([20.0] * 8)) is None


def _fake_module(base):
    calls = {"scale": 0}

    def scale(mins, total_target):
        calls["scale"] += 1
        return mins * (total_target / mins.sum())

    m = SimpleNamespace(
        LEAGUE=SimpleNamespace(regulation_team_minutes=200.0),
        _roll_minutes_unscaled=lambda df, date_str=None, team_tri=None: pd.Series(base, index=df.index, dtype=float),
        _first_minutes_signal=lambda df: pd.Series(base, index=df.index, dtype=float),
        _minutes_priors_from_player_logs=lambda **k: {},
        _frame_series=lambda df, col, default: df.get(col, pd.Series([default] * len(df))),
        _norm_player_key=lambda v: str(v).upper(),
        _minutes_caps_from_team_df=lambda df, base_minutes: pd.Series([40.0] * len(df), index=df.index),
        _scale_minutes_to_target=scale,
        _cap_and_redistribute_minutes=lambda mins, total_target, cap, iters: mins,
    )
    return m, calls


def test_shrink_case_uses_water_fill():
    m, calls = _fake_module(LVA)
    df = pd.DataFrame({"player_name": [f"p{i}" for i in range(len(LVA))]})
    out = sim._derive_sim_minutes_local(smart_sim_module=m, team_df=df, date_str="2026-10-01", team_tri="LVA")
    assert out.sum() == pytest.approx(200.0)
    assert out.iloc[0] > 30.5 * (200.0 / LVA.sum()) + 1.0 and calls["scale"] == 0


def test_short_rotation_keeps_the_vendor_path():
    short = np.array([30.0, 28.0, 25.0, 20.0, 15.0, 10.0])  # sums to 128 < 200
    m, calls = _fake_module(short)
    df = pd.DataFrame({"player_name": [f"p{i}" for i in range(len(short))]})
    sim._derive_sim_minutes_local(smart_sim_module=m, team_df=df, date_str="2026-10-01", team_tri="LVA")
    assert calls["scale"] == 1


def test_the_sim_routes_derive_sim_minutes_to_the_local_port():
    source = Path(sim.__file__).read_text(encoding="utf-8")
    assert '"_derive_sim_minutes": lambda team_df, date_str=None, team_tri=None: _derive_sim_minutes_local(' in source
