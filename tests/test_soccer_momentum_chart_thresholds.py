"""`_momentum_chart`'s strength bands must stay pinned to FotMob's 0-100 scale.

WHY THIS TEST EXISTS. The bands (40/60/80) were retuned 2026-08-22 from an
informal ESPN-proxy scale (1.0/2.5/5.0) to FotMob's measured scale, in the same
session that found a control silently computing `+0.0000` because a threshold
built for one feature's scale was applied to another's. A future edit that
swaps the momentum source again, or "simplifies" these constants, would
reintroduce that exact class of bug -- these tests pin the boundaries so it
would be caught here, not read off a live card by a human.
"""

from __future__ import annotations

from syndicate.features.soccer.cards import _momentum_chart


def _momentum(current: float) -> dict:
    return {"supported": True, "current": current, "events": 5,
            "series": [{"t": 0, "v": 0.0}, {"t": 600, "v": current}]}


def _label_for(current: float) -> tuple[str, bool, bool]:
    out = _momentum_chart(_momentum(current), away_abbr="AWY", home_abbr="HME")
    return out["label"], out["side_is_home"], out["side_is_away"]


def test_below_40_reads_balanced_regardless_of_sign():
    for value in (0.0, 5.0, -5.0, 39.9, -39.9):
        label, is_home, is_away = _label_for(value)
        assert label == "Balanced", f"value={value} should not claim a side"


def test_39_9_is_balanced_but_40_0_is_not_a_boundary_regression_guard():
    below, *_ = _label_for(39.9)
    at, *_ = _label_for(40.0)
    assert below == "Balanced"
    assert at != "Balanced"


def test_40_to_60_is_shading_it():
    label, is_home, is_away = _label_for(45.0)
    assert label == "HME shading it"
    assert is_home and not is_away


def test_60_to_80_is_on_top():
    label, *_ = _label_for(-65.0)
    assert label == "AWY on top"


def test_80_plus_is_pressing_hard():
    label, is_home, is_away = _label_for(92.0)
    assert label == "HME pressing hard"
    assert is_home and not is_away


def test_unsupported_momentum_hides_the_panel():
    assert _momentum_chart({"supported": False, "reason": "x"},
                           away_abbr="AWY", home_abbr="HME") is None
    assert _momentum_chart(None, away_abbr="AWY", home_abbr="HME") is None


def test_no_side_when_current_is_exactly_zero():
    label, is_home, is_away = _label_for(0.0)
    assert label == "Balanced"
    assert not is_home and not is_away
