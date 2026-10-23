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
    POLYMARKET_ASSUMED_WORST_CASE_RATE,
    POLYMARKET_MEASURED_NOTIONAL_RATE,
    POLYMARKET_TAKER_THETA,
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
    polymarket_fill_fee_dollars,
    polymarket_worst_case_fee_dollars,
    taker_fee_per_contract,
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


# (order_id, contracts, fill_price, commissionNotionalTotalCollected) -- every
# live Polymarket fill with a recorded commission since go-live, 2026-10-20..23,
# read off the fleet execution ledger and the `COMMISSION` log lines (they agree).
REAL_POLYMARKET_FILLS = [
    ("D7HMYF0G10JQ", 1.02, 0.48, 0.02),
    ("D7JJFKT010JF", 1.04, 0.47, 0.02),
    ("D7M3K12050JE", 11.29, 0.48, 0.20),
    ("D7M3G08030JV", 1.04, 0.47, 0.02),
    ("D7PR8F4G10JE", 1.04, 0.47, 0.02),
    ("D7W7YCSG10JN", 0.50, 0.48, 0.01),
    ("D7X0DKEG10JE", 10.02, 0.755, 0.13),
    ("D7XPJT2G10JR", 1.08, 0.35, 0.02),
    ("D7Y3D2WG10JN", 0.55, 0.49, 0.01),
    ("D7ZHM82010JR", 1.08, 0.48, 0.02),
    ("D816C6F010JF", 11.51, 0.47, 0.19),  # a cent UNDER: multi-fill rounding
    ("D816DSB010JF", 1.05, 0.53, 0.02),
    ("D81C2CEG10JH", 0.44, 0.49, 0.01),
    ("D89HER7090JK", 11.29, 0.48, 0.20),
    ("D8K1DNA011MV", 11.29, 0.48, 0.20),
    ("D8K1E8FG11MQ", 1.08, 0.48, 0.02),
    ("D8NDJJDG11MC", 11.48, 0.49, 0.20),
    ("D8ZE2ABG11MQ", 11.24, 0.49, 0.20),
]

# The 08-30 fills that fitted "150 bps flat", charged under theta 0.06 (in force
# 2026-07-01 per QCX's filing). They sit at 0.43-0.47, where 0.06*p(1-p) ~ 1.5c.
AUGUST_POLYMARKET_FILLS = [
    ("C60RZVXYJKDG", 4.93, 0.43, 0.07),
    ("C60JWBG0WKDK", 3.91, 0.47, 0.06),
    ("C5Y0GHE4MKDE", 2.38, 0.44, 0.04),
    ("C5Y08RVP8KDK", 18.70, 0.47, 0.28),
    ("C5SM8P8S4KDC", 3.40, 0.47, 0.05),
    ("C65VD0R72KDG", 13.13, 0.235, 0.14),  # the 0.235 fill that broke "flat"
]


def test_polymarket_fee_reproduces_the_REAL_commissions():
    """The filed parabola against what the venue actually booked.

    17 of 18 to the cent. The 18th is one cent UNDER: an order that sweeps
    several resting orders is never charged more than the rounded cumulative
    fee, so the venue can come in under the single-fill rounding and never over.
    """
    exact, over, misses = 0, [], []
    for order, contracts, price, actual in REAL_POLYMARKET_FILLS:
        modelled = polymarket_fill_fee_dollars(contracts, price)
        if modelled == pytest.approx(actual, abs=1e-9):
            exact += 1
        elif actual > modelled:
            over.append(order)
        elif modelled - actual > 0.010001:
            misses.append(f"{order}: modelled {modelled:.2f} vs actual {actual:.2f}")
    assert not over, f"venue charged MORE than the filed fee on {over}"
    assert not misses, "; ".join(misses)
    assert exact >= 17


def test_the_off_mid_fill_DISCRIMINATES_the_shapes():
    """10.02 contracts at 0.755, charged $0.13: the one fill that separates them.

    Flat 1.5c predicts $0.15, the parabola at 0.06 predicts $0.11, at 0.0695 $0.13.
    """
    contracts, price, actual = 10.02, 0.755, 0.13
    assert polymarket_fill_fee_dollars(contracts, price) == pytest.approx(actual)
    assert polymarket_fill_fee_dollars(contracts, price, theta=0.06) == pytest.approx(0.11)
    assert round(POLYMARKET_MEASURED_NOTIONAL_RATE * contracts, 2) == pytest.approx(0.15)


def test_the_august_fills_fit_the_theta_then_in_force():
    for order, contracts, price, actual in AUGUST_POLYMARKET_FILLS:
        assert polymarket_fill_fee_dollars(contracts, price, theta=0.06) == pytest.approx(actual), order


def test_the_polymarket_fee_is_NOT_zero_and_IS_quadratic():
    """Zero came from a fee-blind method; FLAT came from five fills at the mid.

    The filed shape vanishes toward the tails like Kalshi's, so a 0.94 contract
    costs ~0.39c, not the 1.5c the flat model charged.
    """
    assert POLYMARKET_TAKER_THETA == 0.0695
    mid = polymarket_fee_dollars(100, 0.50)
    tail = polymarket_fee_dollars(100, 0.94)
    assert mid == pytest.approx(1.7375)
    assert tail == pytest.approx(0.0695 * 100 * 0.94 * 0.06, abs=1e-4)
    assert 0 < tail < mid / 4


def test_the_board_rate_is_the_unrounded_parabola():
    fee, basis, bound = taker_fee_per_contract("polymarket", 0.48)
    assert fee == pytest.approx(0.0695 * 0.48 * 0.52)
    assert basis == "polymarket_filed_quadratic"
    assert bound is False


def test_polymarket_is_dearer_than_kalshi_mlb_at_every_price():
    """Same parabola, larger coefficient: 0.0695 against MLB's 0.07 x 0.5."""
    for price in (0.05, 0.50, 0.94):
        poly = polymarket_fee_dollars(1, price)
        kalshi = kalshi_taker_fee_dollars(1, price, fee_multiplier=0.5)
        assert poly > kalshi, f"at p={price}: poly {poly} !> kalshi {kalshi}"


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


def test_the_bound_is_ABOVE_the_measurement_at_every_price():
    """The relationship nothing asserted, which is how a trap survived.

    The bound was a QUADRATIC while the fee was thought quadratic. After the
    shape correction it sat BELOW the measured fee at every price -- 0.50
    against 1.50 per hundred contracts at even money. A "worst case" cheaper
    than the real cost is the exact direction this module exists to prevent.
    """
    for price in (0.01, 0.05, 0.30, 0.50, 0.80, 0.95, 0.99):
        bound = polymarket_worst_case_fee_dollars(100, price)
        measured = polymarket_fee_dollars(100, price)
        assert bound > measured, f"at p={price}: bound {bound} !> measured {measured}"
    assert POLYMARKET_ASSUMED_WORST_CASE_RATE >= POLYMARKET_TAKER_THETA


def test_the_arb_worst_case_leg_is_ABOVE_the_filed_fee():
    """The arb path applied the 0.02 bound as a theta: 0.5c at even money, under
    a real 1.74c. A bound below the fee makes fake arbs."""
    from syndicate.features.shared.kalshi_polymarket_arb import net_edge_per_contract

    for price in (0.05, 0.30, 0.50, 0.80, 0.95):
        bounded = net_edge_per_contract(1.0 - price - 0.01, price, kalshi_fee_multiplier=1.0)
        filed = net_edge_per_contract(
            1.0 - price - 0.01, price, kalshi_fee_multiplier=1.0, polymarket_fee_bound=False)
        assert bounded["polymarket_fee_per_contract"] > filed["polymarket_fee_per_contract"]
        assert filed["polymarket_fee_per_contract"] == pytest.approx(0.0695 * price * (1 - price))


# --------------------------------------------------------------------------
# THE SERIES -> MULTIPLIER TABLE. `#S6a`.
#
# The table is a SNAPSHOT of venue configuration, so these tests deliberately
# do not re-type every rate: pinning all 24 rows here would just be a second
# copy of the same thing that diverges when the venue changes. They pin the
# two facts a caller relies on -- the resolver's SHAPE, and the direction it
# fails in.
# --------------------------------------------------------------------------


def test_a_mapped_series_resolves_from_a_FULL_TICKER_not_just_a_bare_series():
    """Callers hold contract tickers, not series. If only the bare form
    resolved, every real board row would fall through to the assumed rate and
    the fix would be inert on the only input it ever sees."""
    from syndicate.features.shared.venue_fees import kalshi_fee_multiplier_for_series

    assert kalshi_fee_multiplier_for_series("KXMLBTB") == 0.5
    assert kalshi_fee_multiplier_for_series(
        "KXMLBTB-26SEP091840NYYBOS-BOSDEVERS12-2"
    ) == 0.5


def test_an_UNKNOWN_series_returns_None_and_NEVER_a_cheap_guess():
    """None is the caller's signal to assume the FULL rate and stamp the row.

    The asymmetry is the design: overstating a fee only shrinks an edge, while
    understating one invents edge that is not there and loses on every fill.
    So nothing unmapped may resolve, and no prefix rule may rescue it.
    """
    from syndicate.features.shared.venue_fees import kalshi_fee_multiplier_for_series

    for unknown in ("", None, "KXMLBNOTREAL", "KXMLBNOTREAL-26SEP06-X",
                    "mlb-cin-chc-2026-09-06", "-", 17):
        assert kalshi_fee_multiplier_for_series(unknown) is None, unknown


def test_the_table_is_NOT_uniform_which_is_why_a_per_sport_rule_is_wrong():
    """`venue_fees` names three broader rules its own table falsifies. This
    pins the sharpest one: two MLB totals series at two different rates.

    A future edit that "simplifies" this to `MLB -> 0.5` would be wrong in
    both directions at once, and this is the test that says so.
    """
    from syndicate.features.shared.venue_fees import (
        KALSHI_SERIES_FEE_MULTIPLIERS,
        kalshi_fee_multiplier_for_series,
    )

    assert kalshi_fee_multiplier_for_series("KXMLBTOTAL") == 0.5
    assert kalshi_fee_multiplier_for_series("KXMLBINNINGTOTAL") == 1.0
    assert set(KALSHI_SERIES_FEE_MULTIPLIERS.values()) == {0.5, 1.0}


def test_the_assumed_multiplier_is_the_DEAREST_rate_in_the_table():
    """A "conservative" default cheaper than some real rate would not be
    conservative at all -- the same trap `POLYMARKET_ASSUMED_WORST_CASE_RATE`
    fell into when it sat below the measured fee."""
    from syndicate.features.shared.venue_fees import (
        KALSHI_ASSUMED_FEE_MULTIPLIER,
        KALSHI_SERIES_FEE_MULTIPLIERS,
    )

    assert KALSHI_ASSUMED_FEE_MULTIPLIER >= max(KALSHI_SERIES_FEE_MULTIPLIERS.values())


def test_the_FORMULA_is_untouched_for_a_given_multiplier():
    """`#S6a` changed WHICH multiplier is chosen, never the arithmetic.

    Pinned against the real fill the module docstring quotes: 19 contracts at
    0.53 on a x1.0 series charged $0.3314.
    """
    assert kalshi_taker_fee_dollars(19, 0.53, fee_multiplier=1.0) == pytest.approx(
        0.3314, abs=1e-9
    )
    # And the half-rate series is exactly half of it, pre-rounding aside.
    half = kalshi_taker_fee_dollars(19, 0.53, fee_multiplier=0.5)
    assert half == pytest.approx(0.1657, abs=1e-9)
