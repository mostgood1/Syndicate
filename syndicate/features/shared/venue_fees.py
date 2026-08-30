"""What a fill actually costs at each venue. Read from the venue, not encoded.

An arb is a claim about ARITHMETIC: buy both complementary sides for less than
$1.00 and the pair pays $1.00 whatever happens. Fees are the whole margin. A
fee model that is 2x too high hides real opportunities; one that is 2x too low
manufactures fake ones and loses money on every single fill. The second
direction is the expensive one, so every unknown here refuses or rounds
AGAINST us -- never toward "cheap".

--------------------------------------------------------------------------
KALSHI PUBLISHES ITS OWN FEE PARAMETERS PER SERIES. DO NOT HARDCODE A RATE.
--------------------------------------------------------------------------

`GET /trade-api/v2/series/<ticker>` carries two fields that decide the fee:

    fee_type        "quadratic" | "quadratic_with_maker_fees"
    fee_multiplier  a float scaling the base rate

Read live 2026-08-29 across the thirteen series this platform trades, and they
are NOT uniform -- four distinct combinations:

    KXMLBGAME     quadratic_with_maker_fees   0.5     KXNFLGAME    ..._maker_fees  1
    KXMLBTOTAL    quadratic                   0.5     KXWNBAGAME   ..._maker_fees  1
    KXMLBSPREAD   quadratic                   0.5     KXWNBATOTAL  quadratic       1
    KXMLBKS       quadratic                   0.5     KXNBAGAME    ..._maker_fees  1
    KXMLBERA      quadratic                   1       KXNCAAFGAME  ..._maker_fees  1

**Every MLB game/total/spread/K series is HALF RATE.** A flat 0.07 -- the
number every third-party fee explainer quotes -- would have doubled the
modelled cost on exactly the sport with the most volume, and killed real arbs
on paper before anything ever looked at them.

--------------------------------------------------------------------------
THE BASE RATE IS MEASURED OFF OUR OWN FILLS, NOT TAKEN FROM A WEB SOURCE
--------------------------------------------------------------------------

`fees_dollars` on 27 real Kalshi fills (`/api/portfolio/live?show=all`,
2026-08-29), against contracts recovered as `fill_stake_dollars / fill_price`.
Implied rate `fees / (C * P * (1-P))`:

    21 fills on fee_multiplier 0.5 series  ->  0.0350   (= 0.07 * 0.5)
     4 fills on fee_multiplier 1.0 series  ->  0.0700   (= 0.07 * 1.0)
     2 fills                               ->  0.0000   (see maker note below)

Both the base rate AND the meaning of `fee_multiplier` are confirmed by the
same reading, and it DISCRIMINATES: two different multipliers produced two
different implied rates in the expected 2:1 ratio. That is why this is stated
as measured rather than cited.

**The reading is not circular, and that was checked before it was trusted.**
`fees_dollars` is populated in `kalshi_orders._FEE_FIELDS` from the venue's own
`taker_fees_dollars` / `maker_fees_dollars` on the order read. Nothing in this
repo computes a fee from a rate, so these are Kalshi's numbers and not ours
handed back.

--------------------------------------------------------------------------
THE ROUNDING IS TO A HUNDREDTH OF A CENT, NOT TO A CENT. MEASURED 18/18.
--------------------------------------------------------------------------

Every third-party fee explainer says Kalshi "rounds up to the next cent". Against
the 18 fills above that is WRONG, and wrong in the expensive direction --
it overstates the cost of an order by up to 0.9c, which on a 1-2c arb margin is
the whole decision.

Tested as a discriminating comparison rather than assumed:

    ceil to 4 decimal places   18 / 18 exact
    round to 4 decimal places   9 / 18 exact

e.g. 19 contracts at 0.53, multiplier 1.0: raw 0.331303, observed **0.3314**.
Round-to-4dp gives 0.3313 and is wrong; ceil-to-4dp gives 0.3314 and is right.
Nine rows cannot tell the two apart (the raw value already sits on a 4dp
boundary), which is exactly why the count matters more than a spot check.

Rounding is still UP -- just at a finer grain. Understating a fee is what makes
a fake arb look real, so the direction is preserved.

--------------------------------------------------------------------------
THE MAKER FRACTION IS **NOT** MEASURED, AND IT IS THE UNSAFE DIRECTION
--------------------------------------------------------------------------

The two zero-fee fills are `KXMLBSPREAD-...-ATL2` and
`KXMLBOUTS-...-TEXCQUANTRILL44-16`. Both series are `fee_type: quadratic`,
whose name says it carries no maker fee, so "these were resting orders that got
hit, and a maker fill on a `quadratic` series is free" explains both. It is the
LEADING explanation and not a proven one -- the ledger does not record whether
a fill was maker or taker, so the two cannot be distinguished from a fee that
simply was not captured.

So `MAKER_FRACTION` below is a third-party number with no fill of ours behind
it. `maker_fee_dollars` therefore REFUSES on a `quadratic_with_maker_fees`
series unless the caller passes `allow_unverified_maker=True` and says why.
Nothing in the arb path should be resting orders anyway -- see the two-leg note
in `kalshi_polymarket_arb` -- so the refusal costs nothing today.

--------------------------------------------------------------------------
POLYMARKET CHARGED NOTHING. MEASURED 2026-08-30 OFF THE VENUE'S OWN REALIZED P&L
--------------------------------------------------------------------------

`fees_dollars` is still null on every filled Polymarket order -- `venue_order_
view` hardcodes it and the venue's `commissionNotionalTotalCollected` never
reaches the ledger. So the fee was measured a different way: from the VENUE'S
OWN realized P&L on settled positions.

`venue_settlement` grades a Polymarket order from
`delta = after_realized - before_realized`, read off the venue's position row,
and stores it as `pnl_dollars` with `settled_by="venue"`. That is the venue's
number, not ours -- checked before it was trusted, the same circularity check
Kalshi's rate got. If a commission had been taken, realized P&L would fall
short of the no-fee expectation by exactly that amount.

Ten venue-settled orders, `$75.98` of notional:

    implied fee (expected_no_fee - venue_pnl)   -0.0037 .. +0.0000 dollars
    total                                       -$0.0180
    effective rate                              -2.37 bps of notional

**Every value is NEGATIVE OR ZERO.** A real commission is strictly positive; a
negative implied fee is contract-count reconstruction rounding, nothing else.
So the measurement is that Polymarket took **no commission** on these fills.

ONE ROW EXCLUDED, and not for being inconvenient:
`tsc-mlb-tex-mil-2026-08-29-8pt5` implied `+$0.42`, and it carries
`held_side: POSITION_RESOLUTION_SIDE_SHORT` on an order placed as `under` --
the `#595` wrong-side signature. Its P&L does not correspond to the position we
think we held, so it cannot price a fee.

**THE POPULATION IS NARROW AND THAT BOUNDS THE CLAIM.** Ten orders, all
`totals`, all $1-$9. The venue's own payload carries `commissionsBasisPoints`
and `makerCommissionsBasisPoints`, so it CAN charge -- and those fields are
authoritative where this inference is not. `polymarket_fee_dollars` returns the
measured 0.0 and names the population; a caller pricing a different market type
or a much larger order should read the venue field rather than lean on this.

`POLYMARKET_ASSUMED_WORST_CASE_RATE` is kept for callers that want a bound
rather than a measurement, and TIGHTENED from 0.10 to 0.01 -- still an order of
magnitude above everything observed, no longer a number that made Polymarket
two thirds of a modelled pair cost on the strength of nothing.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = [
    "FEE_TYPE_QUADRATIC",
    "FEE_TYPE_QUADRATIC_WITH_MAKER",
    "KNOWN_FEE_TYPES",
    "KALSHI_BASE_TAKER_RATE",
    "MAKER_FRACTION",
    "POLYMARKET_ASSUMED_WORST_CASE_RATE",
    "POLYMARKET_MEASURED_NOTIONAL_RATE",
    "POLYMARKET_REJECTED_COST_RATE",
    "POLYMARKET_MEASURED_SAMPLE",
    "VenueFeeError",
    "VenueFeeUnknown",
    "ceil_to_fee_precision",
    "FEE_DECIMAL_PLACES",
    "kalshi_fee_params",
    "kalshi_taker_fee_dollars",
    "kalshi_maker_fee_dollars",
    "polymarket_fee_dollars",
    "polymarket_worst_case_fee_dollars",
]


class VenueFeeError(Exception):
    """A fee could not be computed from what the venue actually said."""


class VenueFeeUnknown(VenueFeeError):
    """The venue has never told us this fee and we refuse to invent it."""


# Kalshi's `fee_type` vocabulary, as returned by the series endpoint. An
# UNRECOGNISED value is a refusal, never a fallback -- a new fee type is
# exactly the case where assuming the old formula is wrong, and it would be
# wrong silently.
FEE_TYPE_QUADRATIC = "quadratic"
FEE_TYPE_QUADRATIC_WITH_MAKER = "quadratic_with_maker_fees"
KNOWN_FEE_TYPES = frozenset({FEE_TYPE_QUADRATIC, FEE_TYPE_QUADRATIC_WITH_MAKER})

# MEASURED on 25 of our own fills across two multipliers -- see the docstring.
KALSHI_BASE_TAKER_RATE = 0.07

# UNVERIFIED. Third-party sources put the maker fee at a quarter of the taker
# fee (0.0175 / 0.07). No fill of ours confirms it, and `maker_fee_dollars`
# refuses rather than apply it silently.
MAKER_FRACTION = 0.25

# RETRACTED VALUE WAS 0.0. See the docstring: that came from a FEE-BLIND
# method and is disproven on the same orders it was measured from.
#
# MEASURED from `commissionNotionalTotalCollected` on five real fills:
# **150 bps of NOTIONAL** (contracts x $1), i.e. 0.015 per contract, flat.
POLYMARKET_MEASURED_NOTIONAL_RATE = 0.015

# A cost basis (3.247% of contracts x price) fits the same five fills almost as
# well, and I first modelled BOTH and charged the dearer -- but the data does
# separate them, and a test caught it:
#
#     contracts  actual  notional@1.5%   err   cost@3.247%   err
#         18.70    0.28      0.2805    0.0005     0.2854   0.0054
#          2.38    0.04      0.0357    0.0043     0.0340   0.0060
#     total abs error                   0.0111              0.0148
#
# **The largest fill is the discriminator** -- 18.70 contracts is where
# cent-rounding matters least, and notional fits it ten times better. Cost basis
# is REJECTED on the best-resolved point, not merely disfavoured on average.
# Kept as a constant only so the rejection is legible.
POLYMARKET_REJECTED_COST_RATE = 0.03247

# The population behind that zero, carried in code so a caller can see how far
# it generalises without reading the docstring.
POLYMARKET_MEASURED_SAMPLE = {
    "orders": 5,
    "source": "commissionNotionalTotalCollected, per fill",
    "total_fees_dollars": 0.50,
    "total_cost_dollars": 15.40,
    "total_notional_contracts": 33.32,
    "fill_price_range": (0.43, 0.47),
    "basis": "notional (cost basis rejected on the 18.70-contract fill)",
    "measured_at": "2026-08-30",
}

# A bound for callers that want one. RAISED BACK from 0.01 -- that value was set
# on the strength of the retracted zero and sat BELOW the true fee, which is the
# one direction this module exists to prevent.
POLYMARKET_ASSUMED_WORST_CASE_RATE = 0.02


# Decimal places Kalshi rounds a fee to. FOUR -- a hundredth of a cent -- not
# two. Measured 18/18 against real fills; see the module docstring for the
# discriminating comparison against round-to-4dp (9/18).
FEE_DECIMAL_PLACES = 4


def ceil_to_fee_precision(dollars: float) -> float:
    """Round UP to the next hundredth of a cent, the way the venue does.

    Rounding DOWN would make every modelled arb look one rounding-error more
    profitable than it is, which is the direction this module exists to avoid.
    Rounding up to the whole CENT -- what the third-party sources describe --
    errs the safe way but by enough (up to 0.9c/order) to hide real
    opportunities on a 1-2c margin.

    The `round(..., 6)` before the ceiling absorbs float representation slop, so
    a value that already sits exactly on a 4dp boundary is not pushed to the
    next one by 1e-17.
    """
    value = float(dollars)
    if value <= 0:
        return 0.0
    scale = 10 ** FEE_DECIMAL_PLACES
    return math.ceil(round(value * scale, 6)) / scale


# Retained under its old name: `ceil_to_cent` described a rule the venue does
# not follow, so it is not merely renamed but WRONG, and anything still calling
# it should fail loudly rather than get a quietly different number.
def ceil_to_cent(dollars: float) -> float:  # pragma: no cover - deliberate trap
    raise VenueFeeError(
        "ceil_to_cent_is_not_the_venue_rule: Kalshi rounds fees up to a"
        " HUNDREDTH of a cent (measured 18/18 on real fills), not to a cent."
        " Use ceil_to_fee_precision()."
    )


def kalshi_fee_params(series: Any) -> tuple[str, float]:
    """`(fee_type, fee_multiplier)` off a Kalshi series payload, or refuse.

    Accepts either the `{"series": {...}}` envelope the endpoint returns or the
    inner mapping, because both shapes are in circulation in this repo and
    picking the wrong one silently yields `None` for both fields.

    REFUSES on an absent or unrecognised `fee_type`, and on a non-positive or
    absent `fee_multiplier`. There is no default: a series whose fee we cannot
    read is a series we cannot price, and pricing it at the common case is how
    a half-rate MLB market and a full-rate NFL market become indistinguishable.
    """
    if not isinstance(series, dict):
        raise VenueFeeError(f"series_payload_not_a_mapping: {type(series).__name__}")
    inner = series.get("series")
    row = inner if isinstance(inner, dict) else series

    fee_type = str(row.get("fee_type") or "").strip()
    if not fee_type:
        raise VenueFeeError("fee_type_absent -- series payload names no fee type")
    if fee_type not in KNOWN_FEE_TYPES:
        raise VenueFeeError(
            f"fee_type_unrecognised: {fee_type!r} -- known: {sorted(KNOWN_FEE_TYPES)}."
            " A new fee type must be read before it is priced, not assumed to"
            " behave like the old one."
        )

    raw_multiplier = row.get("fee_multiplier")
    if raw_multiplier is None:
        raise VenueFeeError("fee_multiplier_absent")
    try:
        multiplier = float(raw_multiplier)
    except (TypeError, ValueError) as exc:
        raise VenueFeeError(f"fee_multiplier_unreadable: {raw_multiplier!r}") from exc
    if not (multiplier > 0):
        # Zero would mean "free", which is a claim strong enough that it must
        # come from a field we understand rather than from a parse failure.
        raise VenueFeeError(f"fee_multiplier_not_positive: {multiplier!r}")

    return fee_type, multiplier


def _quadratic_base(contracts: float, price: float) -> float:
    """`C * P * (1-P)`, with the bounds checked rather than assumed.

    A price at or outside [0, 1] is not a probability, and `P*(1-P)` would go
    negative there -- yielding a NEGATIVE fee, i.e. a rebate, which would make
    a losing arb look profitable. That is the single worst arithmetic error
    this module could make, so it is a refusal.
    """
    try:
        c = float(contracts)
        p = float(price)
    except (TypeError, ValueError) as exc:
        raise VenueFeeError(f"fee_inputs_unreadable: contracts={contracts!r} price={price!r}") from exc
    if c < 0:
        raise VenueFeeError(f"contracts_negative: {c!r}")
    if not (0.0 <= p <= 1.0):
        raise VenueFeeError(
            f"price_outside_unit_interval: {p!r} -- a quadratic fee on a price"
            " outside [0,1] is negative, which reads as a rebate"
        )
    return c * p * (1.0 - p)


def kalshi_taker_fee_dollars(contracts: float, price: float, *, fee_multiplier: float) -> float:
    """The fee for crossing the spread on `contracts` at `price`, in dollars.

    `ceil_to_cent(0.07 * fee_multiplier * C * P * (1-P))`. Both the rate and
    the multiplier's meaning are measured -- see the module docstring.

    `fee_multiplier` is REQUIRED and keyword-only. It has no default on
    purpose: a default would be a hardcoded rate wearing a different hat, and
    the half-rate MLB series are the ones that matter most here.
    """
    try:
        multiplier = float(fee_multiplier)
    except (TypeError, ValueError) as exc:
        raise VenueFeeError(f"fee_multiplier_unreadable: {fee_multiplier!r}") from exc
    if not (multiplier > 0):
        raise VenueFeeError(f"fee_multiplier_not_positive: {multiplier!r}")
    return ceil_to_fee_precision(KALSHI_BASE_TAKER_RATE * multiplier * _quadratic_base(contracts, price))


def kalshi_maker_fee_dollars(
    contracts: float,
    price: float,
    *,
    fee_multiplier: float,
    fee_type: str,
    allow_unverified_maker: bool = False,
) -> float:
    """The fee for a RESTING order that gets hit. Zero on `quadratic` series.

    On `quadratic` this returns 0.0, which is the one maker case with evidence
    behind it: both zero-fee fills in our book are on `quadratic` series.

    On `quadratic_with_maker_fees` it REFUSES unless `allow_unverified_maker`,
    because `MAKER_FRACTION` is a third-party number and understating a fee is
    the direction that costs money. A caller that genuinely needs the estimate
    passes the flag and owns the assumption at its own call site, where a
    reader can see it.
    """
    fee_type_text = str(fee_type or "").strip()
    if fee_type_text not in KNOWN_FEE_TYPES:
        raise VenueFeeError(f"fee_type_unrecognised: {fee_type!r}")
    if fee_type_text == FEE_TYPE_QUADRATIC:
        # Validate the inputs anyway -- a free fee on an impossible price is
        # still a sign the caller is holding the wrong row.
        _quadratic_base(contracts, price)
        return 0.0
    if not allow_unverified_maker:
        raise VenueFeeUnknown(
            "maker_fee_unverified: this series charges maker fees and no fill of"
            f" ours has ever measured one. MAKER_FRACTION={MAKER_FRACTION} is a"
            " third-party figure. Pass allow_unverified_maker=True to price it"
            " anyway, and say why at the call site."
        )
    try:
        multiplier = float(fee_multiplier)
    except (TypeError, ValueError) as exc:
        raise VenueFeeError(f"fee_multiplier_unreadable: {fee_multiplier!r}") from exc
    if not (multiplier > 0):
        raise VenueFeeError(f"fee_multiplier_not_positive: {multiplier!r}")
    rate = KALSHI_BASE_TAKER_RATE * MAKER_FRACTION * multiplier
    return ceil_to_fee_precision(rate * _quadratic_base(contracts, price))


def polymarket_fee_dollars(contracts: float, price: float) -> float:
    """The MEASURED Polymarket fee. **NOT zero, and NOT quadratic.**

    **150 bps of NOTIONAL** (contracts x $1), flat -- independent of price.
    Reproduces all five real commissions within a cent. A cost basis was
    considered and REJECTED: see `POLYMARKET_REJECTED_COST_RATE` for the
    discriminating comparison on the largest fill.

    THE SHAPE IS DIFFERENT FROM KALSHI'S AND THAT MATTERS. Kalshi charges
    `rate * C * P * (1-P)` -- a parabola that vanishes at the tails. Polymarket
    charges a flat proportion, so it does NOT vanish: at P=0.94 Kalshi's MLB fee
    is 0.0020/contract and Polymarket's is 0.0150, seven times larger. Modelling
    this as a quadratic (as the first version of `net_edge_per_contract` did)
    understates the tails by an order of magnitude -- and the tails are exactly
    where in-play pairs live.
    """
    _quadratic_base(contracts, price)  # an impossible input is still a refusal
    return ceil_to_fee_precision(POLYMARKET_MEASURED_NOTIONAL_RATE * float(contracts))


def polymarket_worst_case_fee_dollars(contracts: float, price: float) -> float:
    """A deliberately pessimistic bound on the Polymarket leg, in dollars.

    FLAT PER CONTRACT, matching the measured shape at a higher rate.

    IT WAS A QUADRATIC, copied from Kalshi's form while Polymarket's fee was
    unobserved. Once the real shape turned out to be flat, that quadratic sat
    BELOW the measured fee at EVERY price -- 0.50 against 1.50 per hundred
    contracts at even money. **A bound cheaper than the thing it bounds is not
    conservative, it is a trap**, and it survived the shape correction because
    nothing asserted the relationship between the two.

    Report it as a bound wherever it is used, so no reader mistakes it for the
    measurement.
    """
    _quadratic_base(contracts, price)  # an impossible input is still a refusal
    return ceil_to_fee_precision(POLYMARKET_ASSUMED_WORST_CASE_RATE * float(contracts))
