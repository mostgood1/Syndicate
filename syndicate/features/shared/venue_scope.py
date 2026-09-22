"""Restrict a board to ONE venue's prices -- what we could actually have bet there.

WHY THIS EXISTS. Stage D's plan names its own catch: the only legally automatable
venues (Kalshi, Sporttrade, ProphetX, Novig) trade mostly moneyline / spread /
total on major games, while `layer2_board.py`'s header says props are where the
sim differentiates and where **95.5% of the OddsAPI spend** goes. **So the
markets that can be automated are largely not the markets this board is best
at**, and that is a question about whether Stage D is worth building at all.

The plan says to answer it with numbers rather than in advance. This is how: run
a SECOND paper portfolio restricted to one venue, alongside the unrestricted one,
and compare. If the venue-scoped book has no edge, no placer is worth writing.

**REPRICING IS THE WHOLE POINT, AND INHERITING EV WOULD FAKE IT.** The board
publishes the BEST book's price and `ev_pct` computed against it. Kalshi is
routinely not the best book. Sizing Kalshi's price against the best book's EV
would claim an edge at a price we did not get -- the exact best-of-N fiction the
CLV path refuses -- and would size positions that are, at Kalshi's real price,
negative EV.

So EV is RECOMPUTED, using the repo's own algebra rather than a second one.
`sizing_inputs_from_row` defines

    fair = (ev_pct/100 + 1) / (profit + 1)

`fair` is the market's no-vig probability: a property of the MARKET, not of the
book quoting it. So it is recovered from the best-book row and re-applied at the
venue's price:

    ev_pct_venue = (fair * (profit_venue + 1) - 1) * 100

`model_edge_pct` is the model's deviation from `fair` and is likewise
book-independent, so it carries over untouched. Everything downstream -- the
minimum-EV gate, Kelly, the exposure budget, the refusal names -- then runs
UNMODIFIED on the rewritten row. A venue-scoped plan is not a different pipeline;
it is the same pipeline fed the price we could actually get.

**A ROW THE VENUE DOES NOT QUOTE IS REFUSED BY NAME, NEVER REPRICED.** There is
no fallback to a neighbouring book: the entire question is what THIS venue
offers, and a substituted price would answer a different one while looking like
an answer to this.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["scope_rows_to_venue", "venue_scope_report_line"]

REASON_SCOPED = "scoped"
REASON_NO_BOOK_PRICES = "no_book_prices"
REASON_VENUE_NOT_QUOTING = "venue_not_quoting"
REASON_UNUSABLE_VENUE_PRICE = "unusable_venue_price"
REASON_NO_BEST_PRICE = "no_best_price"
REASON_NO_EV_PCT = "no_ev_pct"
REASON_FAIR_OUT_OF_RANGE = "derived_fair_probability_out_of_range"
# THE SHORTLIST'S IMPLAUSIBLE-BOOK GATE, applied to the VENUE's price (user decision
# 2026-09-21, "apply the 5.26 ceiling and fee to venue-repriced orders"). The board drops
# any row whose EV implies a book total under `_MIN_IMPLIED_BOOK_TOTAL_PCT` (95% -> EV >
# 5.26%) because no real book prices a market that way; this function then re-derives EV
# at the venue's own price and could land far past it. Measured on the paper book
# 09-08..09-20: orders above 5.27% stated EV -- 133, ALL Kalshi or Polymarket
# venue-repriced -- returned -26.7% ROI [-46.3, -5.9].
REASON_VENUE_EV_IMPLAUSIBLE = "venue_ev_implausible"


def _min_implied_book_total_pct() -> float:
    """The shortlist's own threshold (env-overridable there), never a copy of it."""
    try:
        from syndicate.features.shared.layer2_board import _MIN_IMPLIED_BOOK_TOTAL_PCT

        return float(_MIN_IMPLIED_BOOK_TOTAL_PCT)
    except Exception:
        return 95.0


def _as_float(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.strip().replace("+", "")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _venue_price(book_prices: Mapping[str, Any] | None, venue: str) -> float | None:
    """Case-insensitive lookup. The board does not promise a casing."""
    if not isinstance(book_prices, Mapping):
        return None
    target = str(venue).strip().lower()
    for name, price in book_prices.items():
        if str(name).strip().lower() == target:
            return _as_float(price)
    return None


def scope_rows_to_venue(
    rows: Sequence[Mapping[str, Any]],
    venue: str,
    *,
    price_resolver: Any = None,
    ticker_resolver: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rewrite each row at `venue`'s price, or refuse it by name.

    Returns `(scoped_rows, refusals)`. `refusals` accounts for every row that did
    not make it, so `len(scoped_rows) + sum(refusals.values()) == len(rows)` --
    a scoping pass that cannot account for every row it was given is not a
    measurement.

    **`price_resolver` IS WHERE THE VENUE'S OWN PRICE COMES IN.** Without it the
    price is read from `quote.book_prices[venue]`, which is the AGGREGATOR's
    view -- and for these exchanges OddsAPI carries game lines only, which is
    why every coverage number in this system was about OddsAPI rather than the
    venue. Passing a resolver built from the venue's own feed makes the scoped
    book real. The rest of the pipeline is unchanged either way: same gates,
    same refusal names, same sizing.
    """
    from syndicate.features.shared.portfolio_commit import _net_profit_per_unit

    scoped: list[dict[str, Any]] = []
    refusals: dict[str, int] = {}

    def _refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    for row in rows:
        if not isinstance(row, Mapping):
            _refuse("row_not_a_mapping")
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else None
        if quote is None:
            _refuse(REASON_NO_BOOK_PRICES)
            continue

        # The venue's own quote first, the aggregator's only as a fallback --
        # and `price_source` records WHICH, because a coverage number built on
        # the aggregator means something different from one built on the venue
        # and the two must never be silently blended.
        venue_price = None
        price_source = "venue_feed"
        if price_resolver is not None:
            venue_price = _as_float(price_resolver(row))
        if venue_price is None:
            venue_price = _venue_price(quote.get("book_prices"), venue)
            price_source = "aggregator"
        if venue_price is None:
            # THE HEADLINE NUMBER OF THIS WHOLE EXERCISE. How much of the board
            # the venue simply does not offer is the answer to "is Stage D worth
            # building", so it is a counted refusal and never a silent skip.
            _refuse(REASON_VENUE_NOT_QUOTING)
            continue
        venue_profit = _net_profit_per_unit(venue_price)
        if venue_profit is None:
            _refuse(REASON_UNUSABLE_VENUE_PRICE)
            continue

        best_price = _as_float(quote.get("price"))
        if best_price is None:
            _refuse(REASON_NO_BEST_PRICE)
            continue
        best_profit = _net_profit_per_unit(best_price)
        if best_profit is None:
            _refuse(REASON_NO_BEST_PRICE)
            continue

        ev_pct = _as_float(row.get("ev_pct"))
        if ev_pct is None:
            # Same refusal name the sizer uses, deliberately: without EV there
            # is no `fair` to recover, so the row is unscopable for exactly the
            # reason it would be unsizable.
            _refuse(REASON_NO_EV_PCT)
            continue

        fair = (ev_pct / 100.0 + 1.0) / (best_profit + 1.0)
        if not (0.0 < fair < 1.0):
            _refuse(REASON_FAIR_OUT_OF_RANGE)
            continue

        venue_ev_pct = (fair * (venue_profit + 1.0) - 1.0) * 100.0
        if 100.0 / (1.0 + venue_ev_pct / 100.0) < _min_implied_book_total_pct():
            _refuse(REASON_VENUE_EV_IMPLAUSIBLE)
            continue

        # THE CONTRACT ID FIRST, because the fee depends on it: Kalshi's multiplier is
        # a property of the SERIES (MLB game/total/batter series x0.5, others x1.0).
        venue_ticker = None
        ticker_failed = False
        if ticker_resolver is not None:
            try:
                venue_ticker = ticker_resolver(row)
            except Exception:
                ticker_failed = True

        # THE VENUE'S FEE, DEDUCTED HERE -- BEFORE ANY ORDER EXISTS (user decision
        # 2026-09-21: "we should have the fee deduction prior to submit not at submit").
        # `ev_pct` stays GROSS on purpose: `portfolio_commit` rebuilds the fair from it
        # and the price, and the Polymarket submit check re-derives the model
        # probability from it; a fee-net value there would deflate the fair and let the
        # fee be counted twice. The plan's gate and sizer read the two fields below.
        from syndicate.features.shared.venue_fees import taker_fee_per_contract

        venue_prob = 1.0 / (venue_profit + 1.0)
        fee, fee_basis, fee_bound = taker_fee_per_contract(
            venue, venue_prob, venue_ref=venue_ticker, sport=row.get("sport"),
            market=row.get("market"), segment=row.get("segment"))
        ev_net_pct = (fair / (venue_prob + fee) - 1.0) * 100.0

        scoped_quote = dict(quote)
        scoped_quote["price"] = venue_price
        scoped_quote["bookmaker"] = str(venue).strip().lower()
        # `book_prices` is KEPT. The marks and the CLV join both read it, and
        # trimming it here would make a venue-scoped order un-markable for a
        # reason that has nothing to do with the venue.
        scoped_row = dict(row)
        scoped_row["quote"] = scoped_quote
        scoped_row["ev_pct"] = round(venue_ev_pct, 6)
        # The best book's numbers, kept alongside rather than overwritten: the
        # gap between them is the PRICE COST of being restricted to this venue,
        # which is half of what the comparison is for.
        scoped_row["unrestricted_price"] = best_price
        scoped_row["unrestricted_ev_pct"] = ev_pct
        scoped_row["unrestricted_bookmaker"] = quote.get("bookmaker")
        scoped_row["venue"] = str(venue).strip().lower()
        scoped_row["price_source"] = price_source
        scoped_row["venue_fee_per_contract"] = round(fee, 6)
        scoped_row["venue_fee_basis"] = fee_basis
        scoped_row["venue_fee_is_upper_bound"] = bool(fee_bound)
        scoped_row["ev_pct_net_of_fee"] = round(ev_net_pct, 6)
        if ticker_resolver is not None:
            # THE VENUE'S CONTRACT ID, stamped beside the venue's price and from
            # the same match. An order needs both, and deriving the ticker later
            # would derive it from a catalogue that may have moved since we
            # priced -- so the thing we priced and the thing we buy could differ
            # with nothing recording that they did.
            #
            # A ticker we cannot resolve leaves the row PRICED and UNPLACEABLE,
            # which the order builder refuses by name. Better than dropping the
            # row: the paper book still records what the strategy would have done.
            scoped_row["venue_ticker"] = None if ticker_failed else venue_ticker
        scoped.append(scoped_row)
        _refuse(REASON_SCOPED)

    scoped_count = refusals.pop(REASON_SCOPED, 0)
    assert scoped_count == len(scoped)
    return scoped, dict(sorted(refusals.items()))


def venue_scope_report_line(
    venue: str, rows_in: int, scoped: int, refusals: Mapping[str, int]
) -> str:
    """One log line. `logger.info` never reaches Render's collector -- print this."""
    coverage = round(scoped / rows_in, 4) if rows_in else None
    return (
        "[venue_scope] VENUE_SCOPE"
        f" venue={venue}"
        f" rows_in={rows_in}"
        f" scoped={scoped}"
        # The number Stage D's go/no-go rests on: what share of the board this
        # venue quotes at all.
        f" coverage={coverage}"
        f" refusals={dict(sorted(refusals.items()))}"
    )
