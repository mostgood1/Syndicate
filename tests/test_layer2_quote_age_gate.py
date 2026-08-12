"""`#370` -- the shortlist aged rows out on the wrong clock.

`select_shortlist`'s `max_quote_age_seconds` ceiling asks "is our data too old to
act on". It read `book_age_seconds`, which answers a different question: how long
since the PRICE MOVED. `book_quotes` is a change log -- an unchanged price writes
no row -- so a motionless market ages without limit while we watch it every tick.

Measured on the served shortlist 2026-08-11, both clocks present on 200/200 rows:

    sport   book_age median   seen_age median
    mlb              8.9m              2.2m
    nfl            331.6m            270.4m
    wnba           376.2m             68.5m

WNBA prices had not moved in six hours; we had looked 68 minutes ago. At a
1-hour ceiling the moved-clock excludes 123/200 rows and the seen-clock excludes
104 -- and the 19 rows in between are markets we are actively observing that the
old gate would have dropped as stale.

DELIBERATELY NOT CHANGED: `opportunity_gate`'s live/pregame lane checks also read
`book_age_seconds`. They ask whether the MARKET is still moving -- a book that
has not touched its own timestamp during a live game is plausibly suspended --
which is exactly what the moved-clock is for. Same field, different question.
"""

from __future__ import annotations

from syndicate.features.shared.layer2_board import _row_quote_age_seconds


def _row(*, book=None, seen=None) -> dict:
    quote = {}
    if book is not None:
        quote["book_age_seconds"] = book
    if seen is not None:
        quote["quote_seen_age_seconds"] = seen
    return {"quote": quote}


def test_the_seen_clock_wins_when_both_are_present():
    # The measured WNBA case: price motionless six hours, observed 68m ago.
    assert _row_quote_age_seconds(_row(book=22572.0, seen=4110.0)) == 4110.0


def test_a_motionless_but_watched_market_is_not_aged_out():
    # 7h since the price moved, 60s since we looked, 1h ceiling. The old gate
    # dropped this row; it is one of the freshest things on the board.
    age = _row_quote_age_seconds(_row(book=25200.0, seen=60.0))
    assert age is not None and age < 3600, "a market observed a minute ago read as seven hours stale"


def test_it_falls_back_to_the_book_clock_when_no_sidecar():
    # A source with no seen-age must be gated exactly as before, never passed
    # through unmeasured.
    assert _row_quote_age_seconds(_row(book=900.0)) == 900.0


def test_an_absent_quote_or_clock_stays_unknown():
    # Unknown is not fresh. The caller treats None as "do not exclude, but the
    # score already discounts it" -- that contract must not change here.
    assert _row_quote_age_seconds({}) is None
    assert _row_quote_age_seconds({"quote": None}) is None
    assert _row_quote_age_seconds(_row()) is None


def test_a_zero_seen_age_is_honoured_not_treated_as_missing():
    # 0.0 is falsy; a truthiness check here would silently fall through to the
    # book clock for the freshest possible observation.
    assert _row_quote_age_seconds(_row(book=9999.0, seen=0.0)) == 0.0


def test_unparseable_values_do_not_crash_the_gate():
    assert _row_quote_age_seconds({"quote": {"quote_seen_age_seconds": "nope", "book_age_seconds": 120.0}}) == 120.0
    assert _row_quote_age_seconds({"quote": {"quote_seen_age_seconds": None, "book_age_seconds": None}}) is None


def test_the_ceiling_is_one_hour_and_actually_fires():
    """`#371` -- the gate was 24h and excluded nothing.

    Measured on the served shortlist immediately before the change: seen-age
    median 68.5m, p90 375.8m, 104 of 200 rows older than an hour, and 0 of 200
    excluded by the 24h ceiling on either clock. Half the board rested on
    observations over an hour old.

    Pinned as a test because the value is the whole behaviour: a ceiling that
    does not fire is indistinguishable from no gate, and that is exactly the
    state this replaced.
    """
    from syndicate.features.shared.layer2_board import SHORTLIST_MAX_QUOTE_AGE_SECONDS

    assert SHORTLIST_MAX_QUOTE_AGE_SECONDS == 3600
    # A row observed 68 minutes ago -- the measured median -- must now be excluded.
    assert _row_quote_age_seconds(_row(book=22572.0, seen=4110.0)) > SHORTLIST_MAX_QUOTE_AGE_SECONDS
    # And one observed a minute ago must survive, however long since it moved.
    assert _row_quote_age_seconds(_row(book=25200.0, seen=60.0)) < SHORTLIST_MAX_QUOTE_AGE_SECONDS
