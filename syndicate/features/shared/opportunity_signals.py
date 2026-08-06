"""No-vig fair probability, hold, and expected value (#238).

WHY THIS EXISTS
---------------
Every EV number this platform has ever shown was computed against a VIGGED
price. `quote_enrichment` did `ev_pct = model_probability - implied(best_price)`
where `implied()` is the raw American-odds conversion, which includes the
book's margin. That is not expected value against anything -- it is the model's
probability minus a number that is deliberately inflated in the book's favour.

Measured on the production MLB shard for 2026-08-06 (122,023 rows, 11 books),
the median two-sided hold is **6.25%** (p10 3.27, p90 7.36). A hold of 6.25%
inflates one side's implied probability by roughly 3.1 percentage points, so
every EV on the board was biased low by about that much: a row displaying
`+1.0%` was really `~+4.1%`, and rows sitting just under an edge threshold were
being discarded while genuinely +EV.

This module produces the fair probability that fixes it. It is the same thing an
OddsJam-class tool means by "no-vig fair odds" -- the difference being that they
anchor on sharp books (Pinnacle, Circa, the exchange) and we capture none of
those, so consensus across the books we DO have has to do that work. See
`docs/ai_context/plan_oddsjam_class_board.md`.

PURE BY CONSTRUCTION
--------------------
No I/O, no artifact reads, no imports from the feature tree. Everything here is
arithmetic over prices, so it is cheap enough for the request path and testable
without fixtures. The messy part -- finding which rows are two sides of one
market -- lives in `odds_book_quotes`, next to the data.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# Below this, a de-vig is numerically meaningless and usually means one leg is
# stale rather than that the book is generous.
_MIN_OVERROUND = 0.80
# Above this, the two "sides" are almost certainly not the same market (a
# mispaired spread, a 3-way missing its draw). Refusing is better than
# publishing a fair price derived from unrelated bets.
_MAX_OVERROUND = 1.60


def implied_probability(price: Any) -> float | None:
    """American odds -> implied probability, vig included."""
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return (100.0 / (value + 100.0)) if value > 0 else (abs(value) / (abs(value) + 100.0))


def american_price(probability: Any) -> int | None:
    """Probability -> the American price that would be fair at it.

    The inverse of `implied_probability`, so a fair probability can be shown as
    a price next to the book's -- which is the comparison a bettor actually
    makes ("fair is -105, this book has +110").
    """
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0):
        return None
    # `>` not `>=`: at exactly even money the convention is +100, and returning
    # -100 there fails a round trip through implied_probability for no reason.
    return round(-100.0 * p / (1.0 - p)) if p > 0.5 else round(100.0 * (1.0 - p) / p)


def overround(prices: Iterable[Any]) -> float | None:
    """Sum of implied probabilities across every side of one market.

    1.0 is a perfectly fair market; 1.0625 is our measured median. Returns None
    if any side is unusable, because a partial sum is not a hold -- it is a
    smaller number that looks like a better market.
    """
    total = 0.0
    seen = 0
    for price in prices:
        implied = implied_probability(price)
        if implied is None:
            return None
        total += implied
        seen += 1
    return total if seen >= 2 else None


def hold_pct(prices: Iterable[Any]) -> float | None:
    """The book's margin as a share of handle, in percentage points.

    `(total - 1) / total`, NOT `total - 1`. The two differ and the industry --
    and every published figure worth comparing against -- means the former: the
    canonical -110/-110 market is quoted as a **4.55%** hold, which is
    0.0476/1.0476, not 4.76%. Getting this wrong would have made every hold we
    publish read slightly rich, and would have put our numbers permanently a few
    basis points off anything a user could check them against.

    Negative means the sides sum to under 100% -- an arbitrage. Under this
    definition hold and `arbitrage_profit_pct` are exact negatives of each
    other, which is the property that makes them safe to show side by side.
    """
    total = overround(prices)
    if total is None or total <= 0:
        return None
    return round((total - 1.0) / total * 100.0, 4)


def devig(prices: Sequence[Any], *, method: str = "multiplicative") -> list[float] | None:
    """Strip the margin from one market's prices. Returns fair probabilities.

    Works for any number of sides, which is not incidental: a 3-way market
    (`h2h_3_way`) de-vigged as home/away alone produces a fair price for a bet
    that cannot be placed, and treating it as two-way manufactured 7 of the 10
    "arbitrages" the first measurement pass reported. Pass every side.

    `multiplicative` (default) scales all sides by the same factor. It is the
    industry-standard method and what most public no-vig calculators use.

    `power` solves for the exponent k where sum(p_i ** k) == 1. It removes more
    margin from longshots than from favourites, which matches how books actually
    price them -- worth using on player props, where a +390 side and a -450 side
    are routinely two halves of one market and multiplicative de-vig leaves the
    longshot overstated.
    """
    implied = [implied_probability(price) for price in prices]
    if not implied or any(value is None for value in implied):
        return None
    values: list[float] = [float(value) for value in implied]  # narrowed above
    total = sum(values)
    if not (_MIN_OVERROUND <= total <= _MAX_OVERROUND):
        # Refused rather than clamped. A total outside this band is evidence the
        # legs are not one market (or one is stale), and a fair probability
        # derived from them would be confidently wrong -- which is worse than
        # absent, because everything downstream treats it as truth.
        return None
    if method == "power":
        solved = _solve_power(values)
        if solved is not None:
            return solved
    return [value / total for value in values]


def _solve_power(values: Sequence[float], *, iterations: int = 60) -> list[float] | None:
    """Find k such that sum(p ** k) == 1, by bisection.

    Bisection rather than Newton: sum(p**k) is monotonically decreasing in k for
    probabilities in (0,1), so bisection cannot diverge, and 60 halvings is far
    past float precision. No derivative, no failure mode worth handling.
    """
    if any(not (0.0 < value < 1.0) for value in values):
        return None
    low, high = 0.5, 4.0
    for _ in range(iterations):
        mid = (low + high) / 2.0
        total = sum(value ** mid for value in values)
        if total > 1.0:
            low = mid
        else:
            high = mid
    k = (low + high) / 2.0
    fair = [value ** k for value in values]
    total = sum(fair)
    if total <= 0:
        return None
    # Renormalise: bisection lands within tolerance, not exactly on 1.0.
    return [value / total for value in fair]


def fair_probability_by_book(
    prices_by_selection_by_book: Mapping[Any, Mapping[Any, Any]],
    *,
    method: str = "multiplicative",
) -> dict[Any, dict[Any, float]]:
    """De-vig EACH BOOK's own market, keyed {book: {selection: fair_prob}}.

    De-vigging must happen within a single book, not across the best prices of
    several. A book's two sides are a coherent pair that sums to its own margin;
    the best over at one book and the best under at another sum to something
    smaller, and normalising THAT to 1.0 silently launders a line-shopping edge
    into the "fair" price -- which then makes the edge disappear from the EV it
    was supposed to measure.

    Input is {book: {selection: price}}; books that do not quote every side are
    skipped, because a partial market cannot be de-vigged at all.
    """
    fair: dict[Any, dict[Any, float]] = {}
    selections = {selection for prices in prices_by_selection_by_book.values() for selection in prices}
    for book, prices in prices_by_selection_by_book.items():
        if set(prices) != selections or len(prices) < 2:
            continue
        ordered = sorted(prices)
        devigged = devig([prices[selection] for selection in ordered], method=method)
        if devigged is None:
            continue
        fair[book] = dict(zip(ordered, devigged))
    return fair


def consensus_fair_probability(
    prices_by_selection_by_book: Mapping[Any, Mapping[Any, Any]],
    *,
    method: str = "multiplicative",
) -> dict[Any, float] | None:
    """The market's fair probability per selection, across books.

    MEDIAN, not mean. We capture 11 books of wildly different quality and one
    stale or fat-fingered line should not drag the consensus -- the median is
    unmoved by a single outlier and the mean is not. With no sharp anchor
    available (no Pinnacle, Circa or exchange in our feed) this consensus IS our
    fair-value benchmark, so its robustness is load-bearing.
    """
    by_book = fair_probability_by_book(prices_by_selection_by_book, method=method)
    if not by_book:
        return None
    per_selection: dict[Any, list[float]] = {}
    for probabilities in by_book.values():
        for selection, probability in probabilities.items():
            per_selection.setdefault(selection, []).append(probability)
    consensus = {selection: _median(values) for selection, values in per_selection.items() if values}
    total = sum(consensus.values())
    if total <= 0:
        return None
    # Per-selection medians need not sum to 1; renormalise so the result is a
    # probability distribution rather than a set of unrelated medians.
    return {selection: value / total for selection, value in consensus.items()}


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    return ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def expected_value_pct(price: Any, fair_prob: Any) -> float | None:
    """EV per unit staked, in percent, for taking `price` at `fair_prob`.

    The real thing, not a probability difference: profit is asymmetric in
    American odds, so `fair_prob - implied(price)` understates a longshot's EV
    and overstates a favourite's. +5% here means five cents expected return per
    dollar risked.
    """
    try:
        p = float(fair_prob)
        american = float(price)
    except (TypeError, ValueError):
        return None
    if not (0.0 < p < 1.0) or american == 0:
        return None
    profit = (american / 100.0) if american > 0 else (100.0 / abs(american))
    return round((p * profit - (1.0 - p)) * 100.0, 4)


def edge_pct(price: Any, fair_prob: Any) -> float | None:
    """Fair probability minus the price's implied probability, in points.

    Kept alongside `expected_value_pct` because they answer different questions:
    this is "how mispriced is this number", EV is "what does betting it return".
    Ranking should use EV; a human reading the card usually wants this.
    """
    implied = implied_probability(price)
    try:
        p = float(fair_prob)
    except (TypeError, ValueError):
        return None
    if implied is None or not (0.0 < p < 1.0):
        return None
    return round((p - implied) * 100.0, 4)


def arbitrage_profit_pct(prices: Iterable[Any]) -> float | None:
    """Guaranteed return from backing every side at these prices, in percent.

    Positive means an arb. This is just the inverse of the overround, but stated
    as the number a bettor acts on rather than as a margin.

    NOTE for callers: the arithmetic is the easy part and is not where arb
    detection goes wrong. Ours went wrong on PAIRING and STALENESS -- spreads
    are signed per side (home -1.5 pairs with away +1.5), 3-way markets need
    their draw leg, and prices from an all-day log must be simultaneous. Those
    guards belong at the call site, on real rows; see the module docstring's
    reference doc for the measurements.
    """
    total = overround(prices)
    if total is None or total <= 0:
        return None
    return round((1.0 / total - 1.0) * 100.0, 4)


def is_low_hold(prices: Iterable[Any], *, threshold_pct: float = 2.0) -> bool:
    hold = hold_pct(prices)
    return hold is not None and 0.0 <= hold < threshold_pct


def model_edge_pct(model_prob: Any, fair_prob: Any) -> float | None:
    """The simulation's disagreement with the market, in probability points.

    THE differentiator, and the one signal a market-only tool cannot produce:
    it finds value when every book agrees, because it compares against reality
    rather than against the other books' consensus. Positive means the sim
    thinks the outcome is likelier than the de-vigged market does.

    Both inputs must already be vig-free for this to mean anything, which is the
    other reason de-vigging matters: comparing a model probability against a
    vigged implied probability made the sim look systematically pessimistic by
    roughly half the hold.
    """
    try:
        model = float(model_prob)
        fair = float(fair_prob)
    except (TypeError, ValueError):
        return None
    if model > 1.0:
        model = model / 100.0  # sports modules are inconsistent about percent vs fraction
    if not (0.0 < model < 1.0) or not (0.0 < fair < 1.0):
        return None
    return round((model - fair) * 100.0, 4)
