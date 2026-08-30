"""Fee model tests, anchored on REAL FILLS rather than on the formula.

The important test in this file is `test_reproduces_real_kalshi_fills`. A test
that asserts `0.07 * C * P * (1-P)` against a hand-computed `0.07 * C * P *
(1-P)` proves only that the author can multiply. These rows are what Kalshi
actually charged us, read from `/api/portfolio/live?show=all` on 2026-08-29,
and they DISCRIMINATE: they span both `fee_multiplier` values, so a model that
ignored the multiplier passes on half of them and fails on the other half.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_fees import (
    FEE_TYPE_QUADRATIC,
    POLYMARKET_MEASURED_SAMPLE,
    POLYMARKET_MEASURED_TAKER_RATE,
    ceil_to_cent,
    FEE_TYPE_QUADRATIC_WITH_MAKER,
    KALSHI_BASE_TAKER_RATE,
    VenueFeeError,
    VenueFeeUnknown,
    ceil_to_fee_precision,
    kalshi_fee_params,
    kalshi_maker_fee_dollars,
    kalshi_taker_fee_dollars,
    polymarket_fee_dollars,
    polymarket_worst_case_fee_dollars,
)

# (ticker, contracts, fill_price, fee_multiplier, observed_fees_dollars)
# Contracts recovered as round(fill_stake_dollars / fill_price); multiplier read
# from GET /trade-api/v2/series/<series> the same day.
REAL_KALSHI_FILLS = [
    ("KXWNBAREB-26AUG29CHINY-NYBSTEWART30-8", 20, 0.53, 1.0, 0.3488),
    ("KXWNBAREB-26AUG29TORPHX-PHXNMACK4-8", 19, 0.53, 1.0, 0.3314),
    ("KXWNBA3PT-26AUG29TORPHX-PHXKCOPPER2-3", 4, 0.35, 1.0, 0.0637),
    ("KXMLBKS-26AUG291310LADDET-DETKMONTERO54-4", 19, 0.50, 0.5, 0.1663),
    ("KXMLBKS-26AUG291420CINCHC-CINAABBOTT41-4", 18, 0.57, 0.5, 0.1545),
    ("KXMLBHIT-26AUG291610SDTB-SDMMACHADO13-1", 15, 0.37, 0.5, 0.1224),
    ("KXMLBHIT-26AUG291610KCCLE-CLEJRAMREZ11-1", 14, 0.32, 0.5, 0.1067),
    ("KXMLBHRR-26AUG291610SDTB-SDMMACHADO13-2", 13, 0.52, 0.5, 0.1136),
    ("KXMLBKS-26AUG291605MIAWSH-WSHCCAVALLI24-7", 13, 0.45, 0.5, 0.1127),
    ("KXMLBKS-26AUG291610SDTB-SDWBUEHLER10-4", 12, 0.45, 0.5, 0.1040),
    ("KXMLBHIT-26AUG291507SEATOR-SEACYOUNG2-1", 12, 0.39, 0.5, 0.1000),
    ("KXMLBKS-26AUG291610COLATL-ATLMPREZ33-5", 11, 0.43, 0.5, 0.0944),
    ("KXMLBHRR-26AUG291610COLATL-COLCCARRIGG16-2", 10, 0.52, 0.5, 0.0874),
    ("KXMLBSPREAD-26AUG292207PHILAA-PHI3", 9, 0.44, 0.5, 0.0777),
    ("KXMLBTB-26AUG291605MIAWSH-WSHDLILE4-2", 8, 0.58, 0.5, 0.0683),
    ("KXMLBSPREAD-26AUG291415PITSTL-PIT2", 7, 0.34, 0.5, 0.0550),
    ("KXMLBHRR-26AUG291610COLATL-ATLOALBIES1-2", 6, 0.44, 0.5, 0.0518),
    ("KXMLBHIT-26AUG291610COLATL-ATLRACUNA13-1", 4, 0.32, 0.5, 0.0305),
]


def test_reproduces_real_kalshi_fills():
    """Every observed fee EXACTLY, from the venue's own fee params.

    Tolerance is a tenth of the rounding grain, not "close enough". These 18
    rows reconcile to the hundredth of a cent, and holding them to that is the
    only way the rounding rule stays pinned -- a half-cent tolerance passes
    with round-to-4dp, with ceil-to-cent, and with no rounding at all.
    """
    failures = []
    for ticker, contracts, price, multiplier, observed in REAL_KALSHI_FILLS:
        modelled = kalshi_taker_fee_dollars(contracts, price, fee_multiplier=multiplier)
        if abs(modelled - observed) > 1e-9:
            failures.append(f"{ticker}: modelled {modelled:.4f} vs observed {observed:.4f}")
    assert not failures, "fee model disagrees with real fills:\n  " + "\n  ".join(failures)


def test_multiplier_actually_discriminates():
    """off != on for `fee_multiplier`.

    Without this, a model that ignored the multiplier entirely would still pass
    `test_reproduces_real_kalshi_fills` on whichever half happened to match the
    hardcoded rate. Same contracts and price, two multipliers, 2:1 apart.
    """
    full = kalshi_taker_fee_dollars(100, 0.50, fee_multiplier=1.0)
    half = kalshi_taker_fee_dollars(100, 0.50, fee_multiplier=0.5)
    assert full == pytest.approx(1.75, abs=1e-9)    # 0.07 * 100 * 0.25 exactly
    assert half == pytest.approx(0.875, abs=1e-9)   # exactly half, and on-grain
    assert full > half


def test_fee_is_maximal_at_even_money_and_vanishes_at_the_tails():
    """The quadratic shape, which is what makes tail arbs cheap to cross."""
    mid = kalshi_taker_fee_dollars(1000, 0.50, fee_multiplier=1.0)
    tail = kalshi_taker_fee_dollars(1000, 0.05, fee_multiplier=1.0)
    assert mid > tail
    assert kalshi_taker_fee_dollars(1000, 0.0, fee_multiplier=1.0) == 0.0
    assert kalshi_taker_fee_dollars(1000, 1.0, fee_multiplier=1.0) == 0.0


def test_rounding_is_up_to_a_hundredth_of_a_cent():
    """The measured grain. Never down, and never up to a whole cent either.

    Rounding to the whole cent is what every third-party source describes and
    it is wrong on 9 of our 18 fills -- safe in direction but coarse enough to
    hide a real 1-2c arb margin.
    """
    assert ceil_to_fee_precision(0.00001) == 0.0001
    assert ceil_to_fee_precision(0.331303) == 0.3314   # the discriminating row
    assert ceil_to_fee_precision(0.0637) == 0.0637     # already on-grain, unchanged
    assert ceil_to_fee_precision(0.0) == 0.0
    # Explicitly NOT the whole-cent rule.
    assert ceil_to_fee_precision(0.331303) != 0.34


def test_the_retired_cent_rounder_refuses_rather_than_returning_a_number():
    """It encoded a rule the venue does not follow, so a caller must not get a
    quietly-different answer from it."""
    with pytest.raises(VenueFeeError) as exc:
        ceil_to_cent(0.5)
    assert "ceil_to_cent_is_not_the_venue_rule" in str(exc.value)


def test_fee_params_read_both_payload_shapes():
    enveloped = {"series": {"fee_type": FEE_TYPE_QUADRATIC, "fee_multiplier": 0.5}}
    inner = {"fee_type": FEE_TYPE_QUADRATIC, "fee_multiplier": 0.5}
    assert kalshi_fee_params(enveloped) == (FEE_TYPE_QUADRATIC, 0.5)
    assert kalshi_fee_params(inner) == (FEE_TYPE_QUADRATIC, 0.5)


@pytest.mark.parametrize(
    "payload, fragment",
    [
        ({"fee_multiplier": 1.0}, "fee_type_absent"),
        ({"fee_type": "linear", "fee_multiplier": 1.0}, "fee_type_unrecognised"),
        ({"fee_type": FEE_TYPE_QUADRATIC}, "fee_multiplier_absent"),
        ({"fee_type": FEE_TYPE_QUADRATIC, "fee_multiplier": 0}, "fee_multiplier_not_positive"),
        ({"fee_type": FEE_TYPE_QUADRATIC, "fee_multiplier": "n/a"}, "fee_multiplier_unreadable"),
    ],
)
def test_unreadable_fee_params_refuse_by_name(payload, fragment):
    """No defaults. An unreadable fee is a refusal, and the reason says which."""
    with pytest.raises(VenueFeeError) as exc:
        kalshi_fee_params(payload)
    assert fragment in str(exc.value)


def test_a_new_fee_type_refuses_rather_than_falling_back():
    """The case this guard exists for: Kalshi ships a third fee_type.

    Falling back to the quadratic formula would price it plausibly and wrongly,
    with nothing in any log to say so.
    """
    with pytest.raises(VenueFeeError) as exc:
        kalshi_fee_params({"fee_type": "quadratic_with_something_new", "fee_multiplier": 1.0})
    assert "fee_type_unrecognised" in str(exc.value)


def test_price_outside_unit_interval_refuses_rather_than_rebating():
    """`P*(1-P)` past the bounds is negative -- a fee that PAYS us."""
    with pytest.raises(VenueFeeError) as exc:
        kalshi_taker_fee_dollars(10, 1.4, fee_multiplier=1.0)
    assert "price_outside_unit_interval" in str(exc.value)
    with pytest.raises(VenueFeeError):
        kalshi_taker_fee_dollars(10, -0.2, fee_multiplier=1.0)


def test_maker_is_free_on_quadratic_series():
    """The one maker case with evidence: both zero-fee fills are `quadratic`."""
    assert (
        kalshi_maker_fee_dollars(11, 0.45, fee_multiplier=0.5, fee_type=FEE_TYPE_QUADRATIC) == 0.0
    )


def test_maker_refuses_on_maker_fee_series_without_the_flag():
    """MAKER_FRACTION has no fill behind it, so it is opt-in and named."""
    with pytest.raises(VenueFeeUnknown) as exc:
        kalshi_maker_fee_dollars(10, 0.5, fee_multiplier=1.0, fee_type=FEE_TYPE_QUADRATIC_WITH_MAKER)
    assert "maker_fee_unverified" in str(exc.value)

    allowed = kalshi_maker_fee_dollars(
        10, 0.5, fee_multiplier=1.0, fee_type=FEE_TYPE_QUADRATIC_WITH_MAKER,
        allow_unverified_maker=True,
    )
    # A quarter of the taker fee on the same row -- and strictly cheaper, which
    # is the property that would make it dangerous if it were wrong.
    taker = kalshi_taker_fee_dollars(10, 0.5, fee_multiplier=1.0)
    assert 0 < allowed < taker


def test_polymarket_fee_is_the_MEASURED_zero_and_no_longer_refuses():
    """It raised while the fee was genuinely unobserved. It is observed now.

    Measured 2026-08-30 off the venue's own realized P&L on ten settled orders,
    $75.98 notional, effective rate -2.37 bps -- i.e. zero, with the negative
    sign being contract-reconstruction rounding. A real commission is strictly
    positive.

    Refusing to price a leg we HAVE measured is as wrong as guessing one we
    have not, so the refusal is gone rather than kept for safety's sake.
    """
    assert polymarket_fee_dollars(10, 0.5) == 0.0
    assert POLYMARKET_MEASURED_TAKER_RATE == 0.0
    # The population is carried in code so a caller can see how far it goes.
    assert POLYMARKET_MEASURED_SAMPLE["orders"] == 10
    assert POLYMARKET_MEASURED_SAMPLE["markets"] == "totals only"


def test_the_bound_is_still_available_and_still_conservative():
    """A bound remains for callers that want one -- but it is no longer the
    absurd 0.10 that predated any observation."""
    bound = polymarket_worst_case_fee_dollars(100, 0.5)
    measured = polymarket_fee_dollars(100, 0.5)
    assert bound > measured, "a bound that is not above the measurement is not a bound"
    # An order of magnitude over everything observed, and no longer larger than
    # the venue we HAVE measured a real schedule for.
    kalshi_full = kalshi_taker_fee_dollars(100, 0.5, fee_multiplier=1.0)
    assert bound < kalshi_full


def test_base_rate_matches_the_measurement_it_claims():
    """Guards the constant itself against a well-meaning edit.

    If someone 'corrects' KALSHI_BASE_TAKER_RATE to a number from a fee
    explainer, the 25 real fills stop reconciling. This states the link
    explicitly so the reason is visible at the point of change.
    """
    assert KALSHI_BASE_TAKER_RATE == 0.07
    contracts, price = 20, 0.53
    implied = 0.3488 / (contracts * price * (1 - price))
    assert implied == pytest.approx(KALSHI_BASE_TAKER_RATE * 1.0, abs=0.0005)
