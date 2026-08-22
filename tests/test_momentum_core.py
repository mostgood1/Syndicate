"""`shared/momentum_core.py` -- the causal decay, and the pin that guards it.

**WHY A PIN AND NOT A REFACTOR.** `soccer/features/momentum.py` still owns its
own copy of this math. The lane holding that file (`soccer-board-mlb-parity`)
owes a production reading of soccer momentum on a live card, and changing the
implementation under an outstanding measurement is how a measurement stops
meaning anything. So the core is written fresh and pinned against soccer's
instead -- the same guard `game_shape.py:483` uses for
`basketball_elapsed_minutes` against `wnba/cards.py`'s copy, for the reason
that file states in prose.

Test names are NOT `test_soccer_*`: that glob is claimed by the lane above.
"""

from __future__ import annotations

import math

import pytest

from syndicate.features.shared.momentum_core import momentum_at
from syndicate.features.shared.momentum_core import momentum_series
from syndicate.features.shared.momentum_core import peak_magnitude
from syndicate.features.soccer.features.momentum import momentum_at as _soccer_momentum_at


def _rows() -> list[dict[str, float]]:
    """Rows in the shape both implementations read: clock_seconds/sign/weight."""
    return [
        {"clock_seconds": 120.0, "sign": 1.0, "weight": 3.0},
        {"clock_seconds": 300.0, "sign": -1.0, "weight": 1.5},
        {"clock_seconds": 540.0, "sign": 1.0, "weight": 1.0},
        {"clock_seconds": 900.0, "sign": -1.0, "weight": 3.0},
        {"clock_seconds": 1500.0, "sign": 1.0, "weight": 1.5},
    ]


# --------------------------------------------------------------------------
# THE PIN
# --------------------------------------------------------------------------

@pytest.mark.parametrize("half_life", [60.0, 120.0, 300.0, 600.0])
@pytest.mark.parametrize("probe", [0.0, 119.0, 120.0, 301.0, 900.0, 1500.0, 2700.0])
def test_core_agrees_with_the_soccer_implementation(half_life: float, probe: float) -> None:
    """Byte-for-byte agreement with `soccer.features.momentum.momentum_at`.

    Swept over both arguments rather than spot-checked: a decay bug that
    happens to agree at one half-life or one instant is the failure this
    guards against.
    """
    rows = _rows()
    assert momentum_at(rows, probe, half_life_seconds=half_life) == _soccer_momentum_at(
        rows, probe, half_life_seconds=half_life
    )


def test_the_pin_can_actually_fail() -> None:
    """A comparison that cannot fail is not a guard.

    The lane's falsification test: perturb the half-life and the two must
    DISAGREE. Without this, `test_core_agrees_with_the_soccer_implementation`
    would still pass if both functions returned a constant.
    """
    rows = _rows()
    probe = 900.0
    baseline = momentum_at(rows, probe, half_life_seconds=300.0)
    perturbed = _soccer_momentum_at(rows, probe, half_life_seconds=450.0)
    assert baseline != perturbed, (
        "a 1.5x half-life perturbation produced an identical value -- the pin has no power"
    )


def test_core_rejects_the_half_life_soccer_silently_floors() -> None:
    """The one DELIBERATE divergence, asserted so it cannot be mistaken for drift.

    Soccer computes `max(1.0, half_life_seconds)`, so a half-life of 0 silently
    becomes 1.0. A shared module used by sports that have not chosen a
    half-life yet must refuse instead: a floored constant is an unfed input
    wearing a plausible value, which is the failure `model_engine_standard.md`
    exists to stop. Agreement above holds for every half-life >= 1.0, which is
    every value any caller uses.
    """
    with pytest.raises(ValueError):
        momentum_at(_rows(), 900.0, half_life_seconds=0.0)
    with pytest.raises(ValueError):
        momentum_at(_rows(), 900.0, half_life_seconds=-300.0)
    assert _soccer_momentum_at(_rows(), 900.0, half_life_seconds=0.0) == _soccer_momentum_at(
        _rows(), 900.0, half_life_seconds=1.0
    )


# --------------------------------------------------------------------------
# STRICT CAUSALITY -- the property the whole exercise rests on
# --------------------------------------------------------------------------

def test_an_event_one_second_in_the_future_does_not_move_the_present() -> None:
    """The lane's verification (b). If this fails, every lead/lag test is void."""
    past = [{"clock_seconds": 600.0, "sign": 1.0, "weight": 2.0}]
    future = past + [{"clock_seconds": 601.0, "sign": -1.0, "weight": 99.0}]
    assert momentum_at(past, 600.0, half_life_seconds=120.0) == momentum_at(
        future, 600.0, half_life_seconds=120.0
    )


def test_an_event_exactly_at_the_probe_instant_counts() -> None:
    """`t <= probe`, not `t < probe`. Stated because either is defensible and
    the two disagree on every goal/basket sampled at its own timestamp."""
    rows = [{"clock_seconds": 600.0, "sign": 1.0, "weight": 2.0}]
    assert momentum_at(rows, 600.0, half_life_seconds=120.0) == 2.0


def test_unsorted_input_is_not_silently_truncated() -> None:
    """The module accepts any iterable, so it must skip future rows rather than
    break on the first one -- an unsorted caller gets a correct answer."""
    ordered = _rows()
    shuffled = [ordered[3], ordered[0], ordered[4], ordered[1], ordered[2]]
    assert momentum_at(shuffled, 900.0, half_life_seconds=120.0) == momentum_at(
        ordered, 900.0, half_life_seconds=120.0
    )


def test_a_row_with_no_usable_clock_is_skipped_not_placed_at_zero() -> None:
    """Dropping an unplaceable row to 0.0 would put it at tip-off, where it
    decays to nothing and reads as 'no event' rather than 'an event we could
    not place'. Skipping is the honest option and this asserts we do it."""
    good = [{"clock_seconds": 600.0, "sign": 1.0, "weight": 2.0}]
    with_junk = good + [
        {"sign": 1.0, "weight": 50.0},
        {"clock_seconds": None, "sign": 1.0, "weight": 50.0},
        {"clock_seconds": "not a number", "sign": 1.0, "weight": 50.0},
    ]
    assert momentum_at(with_junk, 600.0, half_life_seconds=120.0) == momentum_at(
        good, 600.0, half_life_seconds=120.0
    )


def test_decay_halves_over_exactly_one_half_life() -> None:
    rows = [{"clock_seconds": 0.0, "sign": 1.0, "weight": 4.0}]
    assert momentum_at(rows, 120.0, half_life_seconds=120.0) == pytest.approx(2.0)
    assert momentum_at(rows, 240.0, half_life_seconds=120.0) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# SERIES + NORMALISATION
# --------------------------------------------------------------------------

def test_series_is_sampled_to_the_instant_asked_for_and_no_further() -> None:
    """`until_seconds` is the LIVE clock. Reading the whole feed would let a
    card show pressure from after the moment it claims to describe."""
    series = momentum_series(_rows(), until_seconds=600.0, half_life_seconds=120.0, step_seconds=60.0)
    assert series[0][0] == 0.0
    assert series[-1][0] == 600.0
    assert all(t <= 600.0 for t, _ in series)


def test_series_required_arguments_have_no_sport_specific_defaults() -> None:
    """Soccer defaults `until_seconds=5400.0` (90 minutes), which is a soccer
    fact. A shared module must not carry it."""
    with pytest.raises(TypeError):
        momentum_series(_rows(), half_life_seconds=120.0)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        momentum_series(_rows(), until_seconds=600.0)  # type: ignore[call-arg]


def test_peak_magnitude_never_returns_zero() -> None:
    """Callers divide by it to normalise a chart to [-1, 1]."""
    assert peak_magnitude([]) > 0.0
    assert peak_magnitude([(0.0, 0.0), (60.0, 0.0)]) > 0.0
    assert peak_magnitude([(0.0, -4.0), (60.0, 2.0)]) == 4.0


def test_every_value_is_finite() -> None:
    """A non-finite value reaching a snapshot fails `validate_live_lens_snapshot`
    for the WHOLE sport, not just this game."""
    for t, v in momentum_series(_rows(), until_seconds=2700.0, half_life_seconds=120.0):
        assert math.isfinite(v), f"non-finite momentum at t={t}"
