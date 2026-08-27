"""Does `DIRECT_FEED_BOOKS` catch every spelling the aggregator uses? `#546`.

`is_direct_feed_book` compares `str(book).strip().lower()` against the frozenset
EXACTLY -- no prefix match, no separator folding. So `polymarket_us`,
`kalshi_us` or `Polymarket US` would pass straight through the filter that
exists to stop them, and a second price for one venue would re-enter the de-vig.

Whether the aggregator ever uses such a spelling COULD NOT BE ANSWERED from this
repo: the git-tracked OddsAPI shards are a May/June MLB mirror carrying five
books (draftkings, fanduel, betmgm, fanatics, williamhill_us) and neither venue
at all, and no log line anywhere prints a book key. Production HTTP is
unreachable from a cloud session. So the answer is measured on the next build
instead of guessed at.
"""

from __future__ import annotations

from syndicate.features.shared.book_shortlist import DIRECT_FEED_BOOKS, is_direct_feed_book


def test_the_matcher_is_exact_which_is_why_the_counter_exists():
    """Pin the behaviour the counter is watching for.

    If someone later makes this substring-based, these assertions fail and force
    them to read `#546` -- because a substring match would silently swallow any
    future book whose name merely CONTAINS these strings, dropping real prices
    with no way to notice. That is a worse failure than the one it fixes.
    """
    assert is_direct_feed_book("kalshi")
    assert is_direct_feed_book("  Kalshi  ")
    assert is_direct_feed_book("POLYMARKET")

    # The spellings that would slip through TODAY. Asserted as MISSES so the
    # test states the exposure rather than hiding it.
    assert not is_direct_feed_book("polymarket_us")
    assert not is_direct_feed_book("kalshi_us")
    assert not is_direct_feed_book("polymarket-us")
    assert not is_direct_feed_book("Polymarket US")


def test_unknown_and_blank_keep_the_row():
    """Permissive here KEEPS a row, matching `freshest_rows_for_grid`'s own rule."""
    assert not is_direct_feed_book(None)
    assert not is_direct_feed_book("")
    assert not is_direct_feed_book("draftkings")


def test_the_near_miss_counter_names_the_spelling_it_refused():
    from syndicate.features.shared.book_grid import freshest_rows_for_grid

    rows = [
        {"bookmaker": "draftkings", "price": -110, "selection": "home", "market": "h2h"},
        {"bookmaker": "kalshi", "price": -105, "selection": "home", "market": "h2h"},
        {"bookmaker": "polymarket_us", "price": -104, "selection": "home", "market": "h2h"},
        {"bookmaker": "Kalshi US", "price": -103, "selection": "home", "market": "h2h"},
    ]
    kept = freshest_rows_for_grid(rows)
    kept_books = {str(r.get("bookmaker") or "").lower() for r in kept}

    # The exact spelling is dropped; the near misses are NOT dropped -- they are
    # still in the grid, which is precisely the exposure being measured.
    assert "kalshi" not in kept_books
    assert "polymarket_us" in kept_books
    assert "kalshi us" in kept_books


def test_a_book_that_merely_contains_the_name_is_not_silently_dropped():
    """The counter must not become a filter by accident."""
    from syndicate.features.shared.book_grid import freshest_rows_for_grid

    rows = [{"bookmaker": "polymarket_clone_sportsbook", "price": -110,
             "selection": "home", "market": "h2h"}]
    kept = freshest_rows_for_grid(rows)
    assert len(kept) == 1, "a near miss is counted, never removed"


def test_the_frozenset_is_still_the_two_venues_we_read_directly():
    assert DIRECT_FEED_BOOKS == frozenset({"kalshi", "polymarket"})
