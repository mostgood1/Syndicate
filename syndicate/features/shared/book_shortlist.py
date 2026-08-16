"""THE ONE OWNER of "which books can this operator actually bet".

WHY THIS FILE EXISTS. The list lived as a client-side JS array inside a Jinja
template (`templates/shared/layer1_board.html:267`, `DEFAULT_BOOKS`), which made
it Layer 1's private preference. Layer 2 had no equivalent and no allowlist of
any kind, so it shopped 36 books and recommended prices at books the user cannot
place a bet at.

Measured on the served Layer 2 shortlist 2026-08-16T16:20:21Z, 108 rows:

    best book OUTSIDE Layer 1's list    27 of 108   25.0%
      betopenly      16
      betfair_ex_eu   9
      betsson         2

Copying the array into Layer 2 would have produced a second owner that can
drift, which is the shape this repo has paid for before (`#245`'s dead-market
rule written twice, `board_cross_book`'s pairing guard duplicated). So: ONE
list, in Python, read by both surfaces. Layer 1 renders its "My books / All
books" toggle from it; Layer 2 restricts best-price selection to it.

**A FILTER ON SELECTION, NEVER ON FETCH.** Every book still arrives in the
payload and every price is still recorded in `book_prices` for the CLV join --
which needs the widest possible book overlap, and is the reason
`book_prices` keeps all 36. This bounds only WHICH PRICE WE RECOMMEND. A price
that exists is never invisible; it is one "All books" click away on Layer 1.

ORDER IS MEANINGFUL AND IS NOT ALPHABETICAL. Majors first, then the sharp and
exchange prices, then the prediction markets -- the order they are actually read
in. Alphabetical put `betanysports` ahead of `draftkings`. Carried over verbatim
from the Layer 1 array so that moving the owner changes no rendering.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Verbatim from `layer1_board.html`'s DEFAULT_BOOKS, order preserved.
DEFAULT_BOOKS: tuple[str, ...] = (
    "draftkings",
    "fanduel",
    "betmgm",
    "williamhill_us",
    "betrivers",
    "fanatics",
    "pinnacle",
    "novig",
    "prophetx",
    "kalshi",
    "polymarket",
)

_DEFAULT_BOOK_SET = frozenset(DEFAULT_BOOKS)


def is_bettable(book: Any) -> bool:
    """Is this a book the operator holds an account with?

    Unknown/blank is NOT bettable. `learnings.md`'s standing rule --
    "unknown must not default permissive" -- applies directly: an absent
    bookmaker resolving to the permissive branch would readmit exactly the rows
    this filter exists to remove, and would do it silently.
    """
    if book is None:
        return False
    return str(book).strip().lower() in _DEFAULT_BOOK_SET


def bettable_prices(book_prices: Mapping[str, Any] | None) -> dict[str, int]:
    """The subset of a `{book: price}` map the operator can actually bet."""
    out: dict[str, int] = {}
    for book, price in (book_prices or {}).items():
        if not is_bettable(book):
            continue
        try:
            out[str(book).strip().lower()] = int(price)
        except (TypeError, ValueError):
            continue
    return out


def best_bettable(book_prices: Mapping[str, Any] | None) -> tuple[str, int] | None:
    """Best price among books we can bet, or None when none of them quote it.

    None is a REAL and load-bearing answer, not an error. 9 of the 27 offending
    rows in the measurement above were `h2h_lay` quoted only by `betfair_ex_eu`
    and `matchbook` -- exchange lay markets. Those do not degrade to a worse
    price under this list; they have no price at all, and the caller must drop
    the row rather than fall back to an unbettable book.

    Ties keep the FIRST book in `DEFAULT_BOOKS` order rather than an arbitrary
    dict-iteration winner, so the same input always names the same book -- a
    recommendation that changes book between two identical builds is
    indistinguishable from a real line move to anyone reading the artifact.
    """
    priced = bettable_prices(book_prices)
    if not priced:
        return None
    best_book: str | None = None
    best_price: int | None = None
    for book in DEFAULT_BOOKS:  # iterate the ORDER, so ties are deterministic
        price = priced.get(book)
        if price is None:
            continue
        # `_better`'s comparison, restated here rather than imported: raw
        # American ints order correctly in both signs (larger positive pays
        # more; negative closer to zero pays more), so one `>` is the whole
        # rule and importing `book_grid` for it would couple this module to the
        # grid builder it is meant to be independent of.
        if best_price is None or price > best_price:
            best_book, best_price = book, price
    if best_book is None or best_price is None:
        return None
    return best_book, best_price


def books_seen(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    """Every book quoted anywhere in a row set -- the "All books" denominator."""
    seen: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        quote = row.get("quote")
        prices = quote.get("book_prices") if isinstance(quote, Mapping) else None
        for book in (prices or {}):
            token = str(book).strip().lower()
            if token:
                seen.add(token)
    return seen
