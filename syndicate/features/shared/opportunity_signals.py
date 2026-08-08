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


# Blended-score weights (#243). PROVISIONAL, and labelled as such on purpose:
# nothing here is measured yet. #213 records the quote struck at bet time and
# #214 derives closes, so the honest way to set these is to compare each
# component's CLV once enough settled bets exist -- until then they are a
# stated prior, not a finding. Kept as module constants so tuning is one edit
# and the components ship alongside the score so a reader can disagree with the
# weighting without having to trust it.
_SCORE_SIM_WEIGHT = 0.5          # sim edge counts half as much as measured EV
_SCORE_BOOK_CONFIDENCE = ((1, 0.5), (2, 0.7), (4, 0.85))   # books quoting -> factor
_SCORE_FRESHNESS = ((300, 1.0), (1800, 0.9), (3600, 0.75), (10800, 0.5))  # seconds -> factor

# EV% IS NOT COMPARABLE ACROSS PRICE LEVELS, and ranking on it alone put a
# 60-to-1 longshot at the top of the board.
#
# MEASURED on the first production L2-A shortlist (2026-08-08): the #1 row was a
# soccer h2h at +6000, fair_probability 0.0178, EV 8.64%, from 5 books. The same
# 8.64% EV requires a wildly different absolute probability edge depending on
# where the price sits:
#
#     price   implied   absolute edge needed for 8.64% EV
#     -110    0.5238    +0.0453
#     +150    0.4000    +0.0346
#     +500    0.1667    +0.0144
#     +6000   0.0164    +0.0014      <- 32x smaller than at -110
#
# `expected_value_pct` is right that EV answers "what does betting this return".
# The error was ranking on it without accounting for how reliable the estimate
# is AT THAT PRICE. Our fair probability comes from a two-sided devig over a
# handful of books, and its ABSOLUTE error does not shrink as p shrinks -- so at
# long odds the EV is dominated by estimation noise rather than by edge.
#
# The floor is the plausible absolute error in a devigged fair probability. It
# is a STATED PRIOR, not a measurement -- same status as the weights above, and
# the honest way to set it is the same: compare CLV by price bucket once enough
# bets settle. Named for the job it serves so it is not reused for another
# (rule 9): this is "how wrong can the DEVIG be", not "how wrong is the sim".
_SCORE_DEVIG_ABS_ERROR_FLOOR = 0.01   # 1 probability point

# Deliberately NOT a hard longshot ban. A +6000 row with a genuinely large
# absolute edge still ranks; this only stops a sub-noise edge being amplified
# into a headline EV by the price alone.


def _book_confidence(books_quoting: Any) -> float:
    """How much a consensus of N books is worth trusting.

    One book is not a market -- its "fair" price is just its own opinion
    de-vigged. Five is a field. This is the difference between an edge and a
    typo, and it is why `books_quoting` was put on the quote in the first place.
    """
    try:
        count = int(books_quoting)
    except (TypeError, ValueError):
        return 0.5
    for threshold, factor in _SCORE_BOOK_CONFIDENCE:
        if count <= threshold:
            return factor
    return 1.0


def _freshness_factor(book_age_seconds: Any) -> float:
    """How much a price that moved N seconds ago is still worth.

    Judged on the BOOK clock, never our capture clock. Decays hard: production
    served a board where every price was ~7 hours old and it looked identical to
    a live one, which is exactly the failure this factor exists to make visible
    in the ranking rather than only in a column.
    """
    try:
        age = float(book_age_seconds)
    except (TypeError, ValueError):
        # Unknown age is not fresh. Several sources publish no book clock at
        # all, and treating that as "brand new" would float them to the top.
        return 0.6
    if age < 0:
        return 0.6
    for threshold, factor in _SCORE_FRESHNESS:
        if age <= threshold:
            return factor
    return 0.25


def _price_reliability(price: Any, fair_prob: Any) -> float:
    """How much of this row's EV survives plausible devig error at its price.

    See `_SCORE_DEVIG_ABS_ERROR_FLOOR`. Returns 1.0 when the absolute
    probability edge is at or above the error floor -- i.e. for any normally
    priced row -- so this changes nothing except at the extremes it exists for.

    Returns 1.0 rather than 0.0 when price or fair probability is missing:
    unknown must not be scored as bad, and a row with no fair probability has
    no EV either, so it has already been excluded upstream.
    """
    edge_points = edge_pct(price, fair_prob)
    if edge_points is None:
        return 1.0
    absolute_edge = abs(float(edge_points)) / 100.0
    if _SCORE_DEVIG_ABS_ERROR_FLOOR <= 0:
        return 1.0
    return round(min(1.0, absolute_edge / _SCORE_DEVIG_ABS_ERROR_FLOOR), 4)


def blended_score(
    *,
    ev_pct: Any = None,
    model_edge: Any = None,
    books_quoting: Any = None,
    book_age_seconds: Any = None,
    price: Any = None,
    fair_prob: Any = None,
) -> dict[str, Any] | None:
    """Rank a board row by value discounted for how much we trust it (#243).

    VALUE is additive and in one unit (percentage points): expected value
    against the no-vig fair price, plus the simulation's disagreement with that
    same fair price at half weight. Both are vig-free, which is the only reason
    they can be added at all -- #238's whole point.

    RELIABILITY is multiplicative: a wide field of books and a price that moved
    recently. Multiplicative because these are not additional value, they are
    confidence in the value already computed -- a +15% EV from one book on a
    seven-hour-old line should not outrank a +4% EV from seven books quoted a
    minute ago, and additively it would.

    Returns the score AND its components, because a single opaque number is not
    something a bettor should be asked to trust. Returns None when there is no
    value term at all -- a row with neither EV nor a sim edge has nothing to
    rank, and scoring it zero would sort it above genuinely negative rows.
    """
    value_ev = _as_float(ev_pct)
    value_sim = _as_float(model_edge)
    if value_ev is None and value_sim is None:
        return None
    value = (value_ev or 0.0) + _SCORE_SIM_WEIGHT * (value_sim or 0.0)
    confidence = _book_confidence(books_quoting)
    freshness = _freshness_factor(book_age_seconds)
    # Third multiplicative reliability term, alongside book breadth and
    # freshness, for the same reason they are multiplicative: it is not
    # additional value, it is confidence in the value already computed.
    price_reliability = _price_reliability(price, fair_prob)
    return {
        "score": round(value * confidence * freshness * price_reliability, 4),
        "value_pct": round(value, 4),
        "ev_component": None if value_ev is None else round(value_ev, 4),
        "sim_component": None if value_sim is None else round(_SCORE_SIM_WEIGHT * value_sim, 4),
        "book_confidence": confidence,
        "freshness_factor": freshness,
        "price_reliability": price_reliability,
    }


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed  # NaN


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
