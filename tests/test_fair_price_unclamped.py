"""The board never publishes a fair price the market never implied.

Companion to `tests/test_wnba_fair_price_unclamped.py`, which covers the WNBA
site. This one covers the other two, both of which produce the `fair_price`
column the intelligence board renders:

  - `layer2_board._american_from_probability`
  - the copy that lived INLINE inside
    `pipeline.intelligence_state._backfill_layer2_board_columns`

Both carried `max(0.02, min(0.98, p))`. Measured on production 2026-08-15,
`/api/intelligence/query` served 1346 `fair_price` values with **24 sitting
exactly on +/-4900 and not one beyond it**; joined row-wise, mlb totals under at
`fair_probability` 0.992056 was published as **-4900** against a correct
**-12488**. A clamp is not a guard.

These tests exercise the CALL SITES, not just the converters -- the harness
(`scripts/probability_differential.py`) already pins the converters. What could
still regress here is the call site deciding to write a wrong number rather than
omit the column, so that is what is asserted.
"""
from __future__ import annotations

import pytest

from pipeline.intelligence_state import _backfill_layer2_board_columns
from syndicate.features.shared.layer2_board import (
    _american_from_probability,
    _layer2_board_columns,
)


# (probability, expected published price). The first two are the exact values
# measured on the live board; the rest bracket the old clamp.
BEYOND_THE_OLD_CLAMP = [
    (0.992056, -12488.0),
    (0.007944, 12488.0),
    (0.99, -9900.0),
    (0.01, 9900.0),
]

INSIDE_THE_OLD_CLAMP = [
    (0.5238, -110.0),
    (0.40, 150.0),
    (0.98, -4900.0),
    (0.02, 4900.0),
]

# A price cannot be derived from any of these. The old code answered every one
# of them with a confident number.
NOT_PRICEABLE = [0.0, 1.0, 50.0, None, "", -0.5, 1.5]


@pytest.mark.parametrize("probability,expected", BEYOND_THE_OLD_CLAMP)
def test_layer2_prices_beyond_the_old_clamp(probability, expected):
    assert _american_from_probability(probability) == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize("probability,expected", INSIDE_THE_OLD_CLAMP)
def test_layer2_unchanged_inside_the_old_clamp(probability, expected):
    """The lane's falsification test: only OUT-OF-RANGE input may change.

    If a probability the clamp never touched now prices differently, the
    delegation altered valid behaviour and must be reverted.
    """
    assert _american_from_probability(probability) == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize("probability", NOT_PRICEABLE)
def test_layer2_refuses_what_it_cannot_price(probability):
    assert _american_from_probability(probability) is None


def test_board_column_is_omitted_rather_than_faked():
    """Absent renders as absent (board contract, web `932a1f71`).

    The column must be MISSING, not present-and-wrong and not present-and-null:
    a null still occupies the cell the UI reads first.
    """
    columns = _layer2_board_columns({}, {"fair_probability": 50.0}, {})
    assert "fair_price" not in columns

    priced = _layer2_board_columns({}, {"fair_probability": 0.992056}, {})
    assert priced["fair_price"] == pytest.approx(-12488.0, abs=1.0)


@pytest.mark.parametrize("probability,expected", BEYOND_THE_OLD_CLAMP)
def test_backfill_prices_beyond_the_old_clamp(probability, expected):
    card = {"quote": {"fair_probability": probability}}
    _backfill_layer2_board_columns(card)
    assert card["fair_price"] == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize("probability", [0.0, 1.0, 50.0])
def test_backfill_leaves_the_key_absent_when_it_cannot_price(probability):
    """The backfill's own stated rule, applied to this field.

    Its docstring already says deriving a number it cannot recover honestly "is
    inventing a number, which is worse than an empty cell". Before this fix
    `fair_price` was the one field that did not follow it.
    """
    card = {"quote": {"fair_probability": probability}}
    _backfill_layer2_board_columns(card)
    assert "fair_price" not in card


def test_backfill_still_defers_to_a_card_that_already_has_a_price():
    """`setdefault` semantics: the producer is the authority, this is a backfill.

    Pinned because the fix touched the one branch that guards it.
    """
    card = {"quote": {"fair_probability": 0.75}, "fair_price": -250.0}
    _backfill_layer2_board_columns(card)
    assert card["fair_price"] == -250.0


def test_the_two_producers_agree():
    """Four producers of one column was the root defect. They must now agree."""
    for probability, _ in BEYOND_THE_OLD_CLAMP + INSIDE_THE_OLD_CLAMP:
        card = {"quote": {"fair_probability": probability}}
        _backfill_layer2_board_columns(card)
        assert card["fair_price"] == _american_from_probability(probability), probability
