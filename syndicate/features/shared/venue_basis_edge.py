"""A VENUE-basis edge: an in-play EXCHANGE price against the book consensus.

WHY THIS EXISTS, AND WHY IT IS ALLOWED LIVE WHEN `market_basis_edge` IS NOT
--------------------------------------------------------------------------

`market_basis_edge` refuses every live market, and it is right to. Its claim is
*this book is quoting a better number than the other books at the same moment*,
and once a game starts that simultaneity is gone: books suspend, re-open and lag
each other by seconds to minutes, so the cross-book spread is mostly STALENESS.
Its own header records the measurement -- NC State @ Virginia totals 42.5 at
+1200 against +175, ten quotes, all on the same line, all within 115s, none
stale by the lag rule. Books do not disagree 7x on a live number; some of them
stopped updating.

**This is a different comparison and the difference is the whole justification.**
The anchor here is not another book. It is an EXCHANGE that demonstrably trades
in-play against live order flow:

    Measured 2026-08-29 22:02Z, `KXMLBGAME`, games already in progress:
      SEA@TOR   0.74/0.75   vol24 904,281 contracts   OI 558,549
      MIA@WSH   0.94/0.95   vol24 804,405             OI 524,743
      AZ@SF     0.63/0.68   vol24 418,031             OI 414,921
    Every in-play spread observed was ONE CENT, and prices moved between two
    reads four minutes apart (TOR 0.73/0.74 -> 0.74/0.75).

A venue with a two-sided book, a one-cent spread and ~$1M of daily turnover on a
single moneyline is not a book that forgot to update. So "the exchange and the
sportsbooks disagree during a game" is a real disagreement in a way that "two
sportsbooks disagree during a game" is not.

**THAT ARGUMENT IS AN ARGUMENT, NOT A MEASUREMENT.** Nothing here has been
scored against realised results. See DISPLAY VS SERVE below: this ships
display-only, deliberately, and `servable` is False for every row until someone
measures it.

NET OF THE VENUE'S OWN FEE, WHICH IS NOT OPTIONAL HERE
------------------------------------------------------

`market_basis_edge` compares two book prices and neither carries an explicit
fee. This compares a book price against an EXCHANGE price, and the exchange
charges a commission that the sportsbook's number does not contain. Ignoring it
would systematically overstate every venue-side edge.

Both fees are measured, not assumed (`venue_fees.py`):

    Kalshi      `rate * C * P * (1-P)`, rate = 0.07 * the SERIES' OWN
                `fee_multiplier` -- every MLB game/total/spread series is HALF
                rate. Verified against 18/18 real fills, rounding ceil-to-4dp.
                Nothing writes that multiplier into `kalshi_markets.json` yet,
                so when it is absent the FULL rate is assumed and the row is
                stamped `fee_is_upper_bound`. That can only shrink an edge,
                never invent one -- see the block at the fee call.
    Polymarket  150 bps of NOTIONAL, FLAT, price-independent. Verified against
                five real `commissionNotionalTotalCollected` values.

The shapes differ and that matters at the tails, which is where in-play prices
live: at P=0.94 Kalshi's MLB fee is 0.0020/contract and Polymarket's 0.0150.

THE GUARDS, AND WHY EACH ONE IS HERE
-------------------------------------

1. **THE VENUE MUST BE ONE THAT TRADES IN-PLAY.** The whole argument above rests
   on it. An unknown venue is refused by name rather than assumed live-capable.

2. **THE VENUE QUOTE MUST NAME THIS GAME.** `#603`: venue quote keys carried no
   game term, and one quote answered every fixture sharing a line -- measured
   26 of 28 live Polymarket totals quotes shared across games, `over 7.5 @ -400`
   on four games at once where one was worth ~2% and another had already won.
   A cross-game price would produce a spectacular and entirely fictional edge
   here, so this refuses unless the row and the quote agree on the fixture.

3. **VENUE FRESHNESS IS TIGHTER THAN PREGAME.** A 300-second-old exchange price
   on a pregame market is fine; on a live one it is a different game state. The
   default is deliberately short and is the one number here most likely to need
   tuning against real data.

4. **A ONE-BOOK CONSENSUS IS NOT A CONSENSUS.** Straight from
   `market_basis_edge` guard 1: with one quoting book the "consensus" IS that
   book, the arithmetic returns exactly 0.0, and a zero that means "nothing to
   compare against" is worse than a refusal.

5. **THE BOOK SIDE MUST BE LIVE-VINTAGE TOO.** The one guard this module was
   first written WITHOUT, and the one most likely to have made it dangerous. A
   live venue price against a PREGAME book consensus is not an edge, it is two
   clocks: `_reprice_live_benchmark` measured ~0.90 against ~0.55 on a team
   three runs up in the 7th, a 35-POINT number that is entirely vintage and is
   shaped exactly like the finding this module exists to surface. The staleness
   flags do not catch it -- when every book stopped updating at first pitch,
   none of them is stale RELATIVE TO ITS PEERS.

6. **DISPLAY AND SERVE ARE DIFFERENT BARS, AND SERVE IS CLOSED.** See below.

DISPLAY VS SERVE: THIS SHIPS UNSERVABLE ON PURPOSE
---------------------------------------------------

`servable` is **always False**. Not because the guards are weak but because the
claim is unmeasured: nobody has scored venue-vs-book disagreement against
realised results, and the platform's own history is emphatic about what happens
when an unmeasured live edge reaches a picks surface. A live-edge attempt was
SHIPPED AND BACKED OUT after it priced `modelProbOver` bit-identical to the
pregame probability on 24 of 28 rows -- three props whose over had ALREADY WON
still read 0.659/0.655/0.745, producing +36.5%/+32.3%/+15.8% and sorting
straight to the top of an edge-ranked board.

So this computes and displays a number with its reasoning attached, and refuses
to call it a pick. Lifting that needs the same thing NCAAF's model gate needs:
a measurement against the close or against results. `pick_gate` is the right
home for that verdict when it exists; this module deliberately does not grant
itself one.

PURE BY CONSTRUCTION
--------------------
No clock, no network, no env. `now` is injected. Everything it needs arrives as
arguments, so it is unit-testable as arithmetic and cannot disagree with
production about what time it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

__all__ = [
    "BASIS",
    "IN_PLAY_VENUES",
    "MAX_ANCHOR_AGE_SECONDS",
    "MAX_VENUE_QUOTE_AGE_SECONDS",
    "MIN_BOOKS_FOR_CONSENSUS",
    "MIN_EDGE_PCT_TO_DISPLAY",
    "VenueBasisEdge",
    "venue_basis_edge",
]

BASIS = "venue"

# The venues whose in-play book is real enough to anchor against. Kalshi is
# measured (see the header). Polymarket US is included because its slate carries
# live game markets and its fee is measured -- but its in-play DEPTH has not been
# read the way Kalshi's has, which is recorded here rather than assumed away.
#
# AN UNKNOWN VENUE IS REFUSED, never treated as live-capable. A sportsbook that
# appears in `book_prices` (draftkings, fanduel, ...) is exactly what this
# comparison must not anchor on, and defaulting to "allow" would silently
# reintroduce the cross-book staleness trap this module exists to avoid.
IN_PLAY_VENUES = frozenset({"kalshi", "polymarket"})

# How old an exchange quote may be and still describe THIS game state.
#
# Deliberately far tighter than the pregame path's tolerance: a 300s-old price
# on a pregame market is the same market, while on a live one a three-minute-old
# baseball price can be two innings stale. 45s is a starting position chosen to
# be conservative, NOT a measurement -- it is the number here most likely to be
# wrong, and it should be set from observed venue update cadence once someone
# has read one.
MAX_VENUE_QUOTE_AGE_SECONDS = 45.0

# Guard 4. Same reasoning and same number as `market_basis_edge`'s display bar:
# one book is not a consensus, and a two-book "consensus" is a coin flip
# between two numbers.
MIN_BOOKS_FOR_CONSENSUS = 3

# GUARD 5. HOW OLD THE **BOOK** SIDE MAY BE -- the guard this module most
# needed and did not originally have.
#
# The venue price being live is only half of the comparison. If the book
# consensus is a PREGAME capture, the difference between them is not an edge,
# it is the gap between two clocks -- and `_reprice_live_benchmark` has the
# measurement on file: a team three runs up in the 7th is ~0.90 to a live price
# and ~0.55 to the pregame consensus, and subtracting them reports a 35-POINT
# EDGE that is entirely vintage. That artifact is exactly the shape of the
# finding this module is supposed to surface, which is what makes it dangerous
# here rather than merely wrong.
#
# The staleness FLAGS do not catch it. `market_basis_edge`'s own header records
# ten quotes on one line, spread 7x, "none stale by the lag rule" -- a book that
# stopped updating at first pitch looks perfectly healthy to a flag that asks
# whether a price is older than its peers. All the peers are pregame too.
#
# Read from `opportunity_gate` rather than chosen here, so the staleness the
# board ENFORCES on a live row and the staleness it ANCHORS AGAINST cannot
# drift apart. 900s is loose for baseball -- it is long enough to hold a real
# vintage gap -- but it does reliably exclude the pregame capture, which is the
# defect that produces the 35-point number. TIGHTEN THIS FROM DATA, not from
# taste; it is the second number here (with the venue ceiling) that should be
# set by a measurement nobody has taken yet.
try:  # pragma: no cover - import-order guard, not a behaviour branch
    from syndicate.features.shared.opportunity_gate import (
        LIVE_MARKET_MAX_AGE_SECONDS as MAX_ANCHOR_AGE_SECONDS,
    )
except ImportError:  # pragma: no cover
    MAX_ANCHOR_AGE_SECONDS = 900.0

# Below this, the number is noise dressed as a finding. A venue and a book
# agreeing to within a quarter of a point during a live game is agreement.
MIN_EDGE_PCT_TO_DISPLAY = 0.25


@dataclass(frozen=True)
class VenueBasisEdge:
    """One side's venue-basis verdict.

    `edge_pct is None` and `servable is False` are DIFFERENT refusals, and this
    module returns the second on EVERY row -- see the module header. A caller
    that reads `servable` as "maybe someday true" is reading it correctly; one
    that reads a non-None `edge_pct` as a pick is not.
    """

    edge_pct: float | None
    displayable: bool
    servable: bool
    reason: str
    basis: str = BASIS
    venue: str | None = None
    venue_price_probability: float | None = None
    consensus_probability: float | None = None
    venue_fee_per_contract: float | None = None
    #: True when the Kalshi series' own `fee_multiplier` was unavailable and the
    #: FULL 0.07 rate was assumed. The true fee is then at most this -- so the
    #: edge is a LOWER bound, never an inflated one. Never true for Polymarket,
    #: whose flat 150bps is measured and price-independent.
    fee_is_upper_bound: bool = False
    anchor_books: int = 0

    def as_payload(self) -> dict[str, Any]:
        """The shape that rides on a board row.

        Carries the FEE and the BOOK COUNT beside the number, because a venue
        edge with neither is not auditable: a reader cannot tell a real gap from
        one that the exchange's own commission eats, nor a three-book consensus
        from a one-book echo.
        """
        return {
            "basis": self.basis,
            "edge_pct": self.edge_pct,
            "displayable": self.displayable,
            "servable": self.servable,
            "reason": self.reason,
            "venue": self.venue,
            "venue_probability": self.venue_price_probability,
            "consensus_probability": self.consensus_probability,
            "venue_fee_per_contract": self.venue_fee_per_contract,
            "fee_is_upper_bound": self.fee_is_upper_bound,
            "anchor_books": self.anchor_books,
        }


def _refuse(reason: str, **extra: Any) -> VenueBasisEdge:
    return VenueBasisEdge(
        edge_pct=None, displayable=False, servable=False, reason=reason, **extra
    )


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _american_to_probability(price: Any) -> float | None:
    try:
        value = float(price)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return None
    return 100.0 / (value + 100.0) if value > 0 else (-value) / ((-value) + 100.0)


def venue_basis_edge(
    best_side: Mapping[str, Any] | None,
    *,
    venue: Any,
    venue_price: Any,
    venue_quote_age_seconds: Any,
    venue_game_token: Any = None,
    row_game_token: Any = None,
    book_quote_age_seconds: Any = None,
    kalshi_fee_multiplier: Any = None,
    is_live: bool = False,
    now: datetime | None = None,
) -> VenueBasisEdge:
    """An in-play exchange price against the book consensus, net of venue fee.

    Returns a refusal rather than a number wherever the comparison would not
    mean what it appears to mean. Every branch names its reason.

    `is_live` is REQUIRED to be true. This is the live-market path; a pregame
    row belongs to `market_basis_edge`, whose anchor is other books and whose
    guards are the right ones there. Two modules answering the same pregame
    question with different arithmetic is how a board comes to disagree with
    itself.
    """
    venue_name = str(venue or "").strip().lower()

    if not is_live:
        return _refuse(
            "pregame row: the book-consensus comparison belongs to market_basis_edge, "
            "which is measured; this path exists only for live markets",
            venue=venue_name or None,
        )

    # GUARD 1: the venue must actually trade in-play.
    if venue_name not in IN_PLAY_VENUES:
        return _refuse(
            f"{venue_name or 'unnamed venue'} is not a known in-play exchange "
            f"(known: {', '.join(sorted(IN_PLAY_VENUES))}); anchoring a live comparison "
            "on a sportsbook is the cross-book staleness trap, not a price",
            venue=venue_name or None,
        )

    # GUARD 2: the venue quote must be for THIS fixture. `#603`.
    if venue_game_token and row_game_token and venue_game_token != row_game_token:
        return _refuse(
            "the venue quote names a different fixture, so this comparison would "
            "price one game against another (#603)",
            venue=venue_name,
        )

    # GUARD 3: freshness, tighter than pregame.
    try:
        age = float(venue_quote_age_seconds)
    except (TypeError, ValueError):
        return _refuse(
            "the venue quote carries no age, so it cannot be shown to describe the "
            "current game state",
            venue=venue_name,
        )
    if age > MAX_VENUE_QUOTE_AGE_SECONDS:
        return _refuse(
            f"venue quote is {age:.0f}s old against a {MAX_VENUE_QUOTE_AGE_SECONDS:.0f}s "
            "ceiling: on a live market that is a different game state, not a stale price",
            venue=venue_name,
        )

    # GUARD 4: a consensus needs books.
    if not isinstance(best_side, Mapping):
        return _refuse("no best-price block on this side", venue=venue_name)
    try:
        books = int(best_side.get("books_quoting") or 0)
    except (TypeError, ValueError):
        books = 0
    if books < MIN_BOOKS_FOR_CONSENSUS:
        return _refuse(
            f"{books} book{'' if books == 1 else 's'} quoting: a consensus needs at least "
            f"{MIN_BOOKS_FOR_CONSENSUS}, and with fewer the 'consensus' is one book's number",
            venue=venue_name,
            anchor_books=books,
        )
    if best_side.get("all_quotes_stale") or best_side.get("suspect_stale"):
        return _refuse(
            "the book side is flagged stale, so the anchor is not a current market",
            venue=venue_name,
            anchor_books=books,
        )

    # GUARD 5: the BOOK side must be live-vintage too. See MAX_ANCHOR_AGE_SECONDS.
    try:
        anchor_age = float(book_quote_age_seconds)
    except (TypeError, ValueError):
        return _refuse(
            "the book consensus carries no age, so it cannot be shown to postdate "
            "first pitch; an unaged anchor is assumed PREGAME rather than assumed fine",
            venue=venue_name,
            anchor_books=books,
        )
    if anchor_age > MAX_ANCHOR_AGE_SECONDS:
        return _refuse(
            f"the book consensus is {anchor_age:.0f}s old against a "
            f"{MAX_ANCHOR_AGE_SECONDS:.0f}s ceiling: comparing a live venue price to a "
            "pregame capture measures the gap between two clocks, not an edge",
            venue=venue_name,
            anchor_books=books,
        )

    consensus = _american_to_probability(best_side.get("consensus_vigged_price"))
    if consensus is None:
        consensus = _american_to_probability(best_side.get("price"))
    if consensus is None:
        return _refuse(
            "no consensus price could be read for this side", venue=venue_name, anchor_books=books
        )

    venue_probability = _american_to_probability(venue_price)
    if venue_probability is None:
        return _refuse(
            "the venue price is unreadable as a probability", venue=venue_name, anchor_books=books
        )

    # THE FEE IS PART OF THE PRICE HERE. A venue quote of 0.60 that costs
    # 0.0150/contract to take is effectively 0.615 to us, and comparing the raw
    # 0.60 against a book would claim an edge the commission has already eaten.
    from syndicate.features.shared.venue_fees import (
        VenueFeeError,
        kalshi_taker_fee_dollars,
        polymarket_fee_dollars,
    )

    fee_is_upper_bound = False
    try:
        if venue_name == "kalshi":
            if kalshi_fee_multiplier is None:
                # THE FULL RATE, ASSUMED, NOT A REFUSAL -- and the direction is
                # the whole justification.
                #
                # Nothing writes `fee_multiplier` into `kalshi_markets.json`
                # today, so refusing here would make this module INERT on the
                # one venue whose in-play depth is actually measured (1c
                # spreads, ~900k contracts of 24h volume on a single live
                # moneyline). Inert-but-principled is the worse failure: the
                # feature would silently do nothing and read as "Kalshi has no
                # live edges", which is precisely the confusion that cost an
                # evening when `markets_key_absent` made Kalshi offer zero
                # quotes platform-wide.
                #
                # Assuming FULL rate is safe in the only direction that matters.
                # Every MLB game/total/spread series is HALF rate, so the true
                # fee is at most this and usually half of it: the assumption can
                # only make an edge look SMALLER, never invent one. Assuming
                # half would have the opposite sign and is not available.
                #
                # `kalshi_polymarket_arb` already made this exact call
                # (`float(m.get("kalshi_fee_multiplier") or 1.0)`), so this is
                # consistency with a live decision, not a new one.
                #
                # The assumption RIDES ON THE PAYLOAD (`fee_is_upper_bound`) so
                # a reader is never told a bound is a measurement.
                fee_is_upper_bound = True
            fee = kalshi_taker_fee_dollars(
                1.0,
                venue_probability,
                fee_multiplier=float(1.0 if kalshi_fee_multiplier is None
                                     else kalshi_fee_multiplier),
            )
        else:
            fee = polymarket_fee_dollars(1.0, venue_probability)
    except VenueFeeError as exc:
        return _refuse(
            f"venue fee could not be priced: {exc}", venue=venue_name, anchor_books=books
        )

    # Effective cost of taking the venue's side, as a probability.
    effective = venue_probability + fee
    # POSITIVE means the VENUE is cheaper than the books think the side is worth
    # -- i.e. buying at the exchange beats the book consensus, after commission.
    edge_pct = (consensus - effective) * 100.0

    if abs(edge_pct) < MIN_EDGE_PCT_TO_DISPLAY:
        # THE FEE AND BOTH PRICES RIDE ON THE REFUSAL TOO. They are known by
        # this point, and a refusal that drops them cannot be audited: a reader
        # cannot tell "the venue and the books agree" from "the commission ate
        # a real gap", and those call for opposite conclusions.
        return _refuse(
            f"{edge_pct:+.2f} pts against the book consensus is inside the "
            f"{MIN_EDGE_PCT_TO_DISPLAY:.2f}-point noise floor: a venue and a book agreeing "
            "this closely during a live game is agreement",
            venue=venue_name,
            anchor_books=books,
            venue_price_probability=round(venue_probability, 6),
            consensus_probability=round(consensus, 6),
            venue_fee_per_contract=fee,
            fee_is_upper_bound=fee_is_upper_bound,
        )

    return VenueBasisEdge(
        edge_pct=round(edge_pct, 4),
        displayable=True,
        # ALWAYS FALSE. See the module header: the claim is unmeasured, and the
        # platform has already shipped and backed out one unmeasured live edge.
        servable=False,
        reason=(
            f"{venue_name} at {venue_probability:.3f} plus {fee:.4f} commission against a "
            f"{books}-book consensus of {consensus:.3f}: "
            + ("the VENUE is cheaper after commission" if edge_pct > 0
               else "the BOOKS are cheaper; taking the venue side costs more")
            + ". DISPLAY ONLY -- venue-vs-book disagreement has never been scored "
            "against results"
        ),
        venue=venue_name,
        venue_price_probability=round(venue_probability, 6),
        consensus_probability=round(consensus, 6),
        venue_fee_per_contract=fee,
        fee_is_upper_bound=fee_is_upper_bound,
        anchor_books=books,
    )
