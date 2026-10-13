"""Shin de-vig on the board's consensus chain (lane `fair-price-v2`)."""
from __future__ import annotations

import math

from syndicate.features.shared import layer2_board
from syndicate.features.shared.opportunity_signals import devig


def test_shin_sums_to_one_and_sits_between_multiplicative_and_power_on_the_longshot() -> None:
    mult, power, shin = (devig([-400, 300], method=m) for m in ("multiplicative", "power", "shin"))
    assert math.isclose(sum(shin), 1.0, abs_tol=1e-9)
    assert power[1] < shin[1] < mult[1]


def test_shin_leaves_a_balanced_market_alone_and_handles_three_ways() -> None:
    assert devig([-110, -110], method="shin") == [0.5, 0.5]
    three = devig([150, 230, 210], method="shin")
    assert three is not None and math.isclose(sum(three), 1.0, abs_tol=1e-9)


def test_shin_falls_back_to_multiplicative_without_an_overround() -> None:
    # 2.0 / 2.0 decimal = no margin: nothing to remove, so Shin defers.
    assert devig([100, 100], method="shin") == devig([100, 100], method="multiplicative")


def test_the_board_accepts_shin_and_still_defaults_to_multiplicative(monkeypatch) -> None:
    monkeypatch.delenv(layer2_board.FAIR_DEVIG_METHOD_ENV, raising=False)
    assert layer2_board._fair_devig_method() == "multiplicative"
    monkeypatch.setenv(layer2_board.FAIR_DEVIG_METHOD_ENV, "shin")
    assert layer2_board._fair_devig_method() == "shin"
    monkeypatch.setenv(layer2_board.FAIR_DEVIG_METHOD_ENV, "nonsense")
    assert layer2_board._fair_devig_method() == "multiplicative"
