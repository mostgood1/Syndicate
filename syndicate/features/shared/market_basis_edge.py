"""A MARKET-basis edge: the best price against the market's own consensus.

WHY THIS EXISTS, AND WHAT IT IS NOT
-----------------------------------
`football/pick_gate.py` measures ONE claim -- *the model prices this market
better than the book does* -- and for NCAAF that claim is false at 17 sigma
(margin MAE 15.775 vs 12.212, n=2233). It then denies on `(sport, market)`,
which also blacks out a claim it never measured and which uses no model at all:

    *this book's price is better than the market's own consensus.*

That is a different assertion with a different failure mode. It is arithmetic
over prices that are on the board right now, not a forecast about a game. A
model that loses to the close says nothing about whether DraftKings is a point
worse than William Hill on the same number, and the two must not share a gate.

**IT IS NOT EXPECTED VALUE, AND MUST NEVER BE LABELLED AS SUCH.** The anchor is
`consensus_vigged_price` -- `book_grid`'s own comment says "nothing here
de-vigs". So this is a PRICE-SHOPPING delta: how much better than the average
quoted price the best quoted price is. Price shopping is measured at **+2.79
ROI pts** platform-wide (`state.md [sharp-reference-price]`) and **+2.95 pts**
on the NFL prop grade, both on controlled identical bets. That is the entire
claim. Turning it into +EV needs a de-vigged SHARP anchor, and whether one is
present is a property of the captured book set, not of this arithmetic.

THE FOUR GUARDS, AND THE MEASUREMENT BEHIND EACH
-------------------------------------------------
Measured on the production NCAAF board, 2026-08-29/30, four dates:

1. **A ONE-BOOK CONSENSUS IS NOT A CONSENSUS.** 414 of 552 fresh pregame sides
   on 2026-09-05 had exactly one quoting book. Best price then IS the
   consensus, so the arithmetic returns exactly `0.0` -- and `0.0` renders as a
   real number meaning "no edge here", when the truth is "nothing to compare
   against". This returns **None with a reason**, never a zero. `book_grid`
   already makes this distinction for the consensus itself, in those words.

2. **NOT ON A LIVE OR SETTLED MARKET.** On the 08-29 slate every double-digit
   "edge" was on a game already in progress or finished: NC State @ Virginia
   totals 42.5 carried over at +1200 (DraftKings) against +175 (William Hill),
   ten quotes, all on the SAME line, all within 115s of each other, none stale
   by the lag rule. Books do not disagree 7x on a live number -- they stop
   updating at different moments, and the spread between the ones that quit and
   the ones that did not looks exactly like a huge edge. The model edge is
   already suppressed on these rows for the same reason, in `board_enrichment`'s
   own words: "the market is settled, so there is no price to beat".

3. **STALE QUOTES ARE EXCLUDED BY THE PRODUCER**, and re-checked here rather
   than assumed. `book_grid` selects the best over fresh quotes only and flags
   `suspect_stale`/`all_quotes_stale` when it could not. Zero of 90 sides on the
   08-29 slate tripped it, so this guard is currently silent -- which is a
   reason to keep it, not to drop it: a guard that has never fired on real data
   is untested, not unnecessary.

4. **DISPLAY AND SERVE ARE DIFFERENT BARS.** A small honest number beats a dash,
   so anything clearing guards 1-3 is DISPLAYED. Calling it a PICK asserts it is
   worth acting on, which needs a wider anchor and a real gap -- see the two
   constants below and `pick_gate.market_verdict(..., basis="market")`.

PURE BY CONSTRUCTION
--------------------
No I/O, no artifact reads, no imports from the feature tree. Arithmetic and
policy over values the caller already holds, so it is cheap enough for the
request path and testable without fixtures -- the same contract
`opportunity_signals` states for itself, and for the same reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

#: The basis token that travels on every row this module verdicts. Callers key
#: on THIS, never on a string of their own -- `pick_gate` and the board template
#: both compare against it, and a second spelling is a silent no-op in whichever
#: one is not updated.
BASIS = "market_consensus"

#: The MODEL basis, named here so the two are declared in one place and a reader
#: can see that they are alternatives rather than a flag and its absence.
MODEL_BASIS = "model"

#: Fewest fresh books that can stand as a consensus for DISPLAY. Two is the
#: minimum at which "best vs average" says anything at all -- with one book the
#: two are the same number by construction (guard 1).
MIN_BOOKS_TO_DISPLAY = 2

#: Fewest fresh books before the number may be called a PICK. Three, because a
#: two-book "consensus" is just the midpoint of one pair and half the reported
#: gap is whichever book is worse, not a market the bettor is beating.
#: Measured cost of this bar on the 2026-09-05 pregame slate: it excludes 74 of
#: 552 sides that guard 1 lets through for display.
MIN_BOOKS_TO_SERVE = 3

#: How much better than consensus, in POINTS OF IMPLIED PROBABILITY, before it
#: is worth acting on. Deliberately NOT tuned to make a slate look full: the
#: measured value of price shopping comes from taking the best price across the
#: whole distribution, not from a threshold, so this exists only to keep noise
#: off a page headed PICKS. On the 2026-09-05 pregame slate it leaves 3 sides;
#: on 2026-09-06 it leaves zero, and zero is the correct answer there.
MIN_EDGE_PCT_TO_SERVE = 1.0


@dataclass(frozen=True)
class MarketBasisEdge:
    """One side's market-basis verdict: the number, and whether it may be served.

    `edge_pct is None` and `servable is False` are DIFFERENT refusals and both
    carry `reason`. The first means there is no number to show; the second means
    there is a number, it is shown, and it does not clear the bar for a pick.
    """

    edge_pct: float | None
    displayable: bool
    servable: bool
    reason: str
    basis: str = BASIS
    anchor: str = "vigged_consensus"
    anchor_books: int = 0

    def as_payload(self) -> dict[str, Any]:
        """The shape that rides on a board row.

        Every field the template needs to render AND to explain itself. A number
        with no anchor count is not auditable on the page, and the page is the
        only place a human ever reads this.
        """
        return {
            "basis": self.basis,
            "edge_pct": self.edge_pct,
            "anchor": self.anchor,
            "anchor_books": self.anchor_books,
            "displayable": self.displayable,
            "servable": self.servable,
            "reason": self.reason,
            # Spelled out on the row rather than left to each surface, because
            # this is the sentence that stops it being read as +EV and there
            # must be exactly one copy of it.
            "label": (
                f"{self.edge_pct:+.2f} pts better than the {self.anchor_books}-book "
                "consensus price (price shopping, not model, not EV)"
                if self.edge_pct is not None
                else self.reason
            ),
        }


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


def _refuse(reason: str, *, books: int = 0) -> MarketBasisEdge:
    return MarketBasisEdge(
        edge_pct=None, displayable=False, servable=False, reason=reason, anchor_books=books
    )


def market_basis_edge(
    best_side: Mapping[str, Any] | None,
    *,
    commence_time: Any = None,
    now: datetime | None = None,
) -> MarketBasisEdge:
    """Verdict one side of one market row, from the `best[side]` block.

    `best_side` is `book_grid`'s own output -- this reads the fields that
    producer already computed rather than recomputing a second copy of the same
    statistic, which is precisely how `book_grid` and `odds_book_quotes` came to
    disagree at the even-money boundary before `consensus_vigged_price` was made
    the single owner.

    `commence_time` absent is treated as **NOT SAFE TO SERVE**, not as pregame.
    An unknown that lands on the permissive branch is a guard that fires only
    when the data is healthy enough not to need it.
    """
    if not isinstance(best_side, Mapping):
        return _refuse("no best-price block on this side")

    books = best_side.get("books_quoting")
    try:
        books = int(books)
    except (TypeError, ValueError):
        books = 0

    edge = best_side.get("edge_vs_consensus_pct")
    if edge is None:
        return _refuse("no consensus price could be computed for this side", books=books)
    try:
        edge = float(edge)
    except (TypeError, ValueError):
        return _refuse("consensus edge is not a number", books=books)

    # GUARD 3 first: a stale side's number is wrong in an unknown direction, so
    # nothing downstream should see it at all.
    if best_side.get("all_quotes_stale") or best_side.get("suspect_stale"):
        return _refuse(
            "every fresh quote on this side is stale, so the best price is not a current one",
            books=books,
        )

    # GUARD 1: one book is not a market. Refuse rather than report the 0.0 the
    # arithmetic produces -- see the module docstring.
    if books < MIN_BOOKS_TO_DISPLAY:
        return _refuse(
            f"{books} book{'' if books == 1 else 's'} quoting: a consensus needs at least "
            f"{MIN_BOOKS_TO_DISPLAY}, so there is nothing to price this against",
            books=books,
        )

    # GUARD 2: live and settled markets. Unknown start time refuses.
    kickoff = _as_datetime(commence_time)
    if kickoff is None:
        return _refuse(
            "no start time on this row, so it cannot be shown to be a pregame market",
            books=books,
        )
    moment = now or datetime.now(timezone.utc)
    if moment >= kickoff:
        return _refuse(
            "the game has started: cross-book spread on a live or settled market is books "
            "closing at different moments, not a price to shop",
            books=books,
        )

    # GUARD 4: displayable now; servable only above both bars.
    if books < MIN_BOOKS_TO_SERVE:
        return MarketBasisEdge(
            edge_pct=round(edge, 2),
            displayable=True,
            servable=False,
            reason=(
                f"{books} books is enough to show a number, not enough to call it a pick "
                f"(a pick needs {MIN_BOOKS_TO_SERVE})"
            ),
            anchor_books=books,
        )
    if edge < MIN_EDGE_PCT_TO_SERVE:
        return MarketBasisEdge(
            edge_pct=round(edge, 2),
            displayable=True,
            servable=False,
            reason=(
                f"{edge:+.2f} pts against consensus is below the {MIN_EDGE_PCT_TO_SERVE:.2f} "
                "pt bar for a pick"
            ),
            anchor_books=books,
        )
    return MarketBasisEdge(
        edge_pct=round(edge, 2),
        displayable=True,
        servable=True,
        reason="",
        anchor_books=books,
    )


def summarise(verdicts: "list[MarketBasisEdge] | tuple[MarketBasisEdge, ...]") -> dict[str, Any]:
    """Counts a caller can print. A suppression nobody can see is one somebody deletes.

    Keyed on the REASON, not just a total, because "no consensus" and "the game
    started" are different problems and a single `suppressed: 84` cannot tell an
    operator which one to go and fix.
    """
    reasons: dict[str, int] = {}
    displayed = served = 0
    for verdict in verdicts:
        if verdict.servable:
            served += 1
        if verdict.displayable:
            displayed += 1
        else:
            key = verdict.reason.split(":")[0].split(",")[0].strip()
            reasons[key] = reasons.get(key, 0) + 1
    return {
        "basis": BASIS,
        "sides": len(verdicts),
        "displayed": displayed,
        "servable": served,
        "not_displayed_by_reason": reasons,
    }
