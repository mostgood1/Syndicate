"""A segment bet must not be placed on a full-game contract.

MEASURED 2026-08-28, real money. `_match_key`/`_row_key` were five-tuples with
no `segment`, so a board row for "under 2.5, first 3 innings" matched Kalshi's
FULL-GAME `KXMLBTOTAL` on game + market + line + side, and nothing checked that
the contract settles on a different portion of the game. Five orders, $7.08:

    first3  under 2.5   KXMLBTOTAL-26AUG281940TEXMIL-3   +1900,  5c
    first3  under 2.5   KXMLBTOTAL-26AUG282138PHILAA-3   +1900,  5c
    first3  under 2.5   KXMLBTOTAL-26AUG281845MIAWSH-3   +1900,  5c
    first3  under 2.5   KXMLBTOTAL-26AUG281840LADDET-3   +1567,  6c
    first5  under 3.5   KXMLBTOTAL-26AUG281840LADDET-4   +567,  15c

The prices are the tell. The model priced "under 2.5 runs through three
innings" -- an ordinary proposition -- against the venue's price for "under 2.5
in nine", which is correctly ~5c because it almost never happens. The entire
apparent edge was the two numbers describing different events.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import _match_key, _row_key
from syndicate.features.shared.kalshi_catalogue import segment_for_series


def _row(**kw):
    row = {"event_id": "evt-1", "sport": "mlb", "market": "totals",
           "line": 2.5, "side": "under"}
    row.update(kw)
    return row


def _match(**kw):
    m = {"board_event_id": "evt-1", "market": "totals", "line": 2.5,
         "board_side": "under", "series": "KXMLBTOTAL"}
    m.update(kw)
    return m


# ---------------------------------------------------------------------------
# THE MEASURED FAILURE
# ---------------------------------------------------------------------------


def test_a_first3_row_no_longer_matches_the_FULL_GAME_contract():
    """The four TEXMIL/PHILAA/MIAWSH/LADDET orders. Before the fix these keys
    were equal and the join handed back a `KXMLBTOTAL` ticker."""
    assert _row_key(_row(segment="first3")) != _match_key(_match(series="KXMLBTOTAL"))


def test_a_first5_row_no_longer_matches_the_FULL_GAME_contract():
    """The LADDET-4 order -- the one that should have been F5."""
    assert _row_key(_row(segment="first5", line=3.5)) != _match_key(
        _match(series="KXMLBTOTAL", line=3.5)
    )


def test_a_first5_row_DOES_match_the_F5_contract():
    """The fix must not be "refuse everything". Kalshi HAS the right contract
    (`KXMLBF5TOTAL`, 'First 5 innings: Over 6.5 runs') and we already fetch it,
    so the F5 order was a mis-SELECTION, not an impossibility."""
    assert _row_key(_row(segment="first5")) == _match_key(_match(series="KXMLBF5TOTAL"))


def test_a_full_game_row_still_matches_the_full_game_contract():
    """The control. 18 of the 23 Kalshi totals orders that day were full-game
    and correct; a fix that broke them would trade one defect for a bigger one.
    """
    assert _row_key(_row()) == _match_key(_match())


def test_an_ABSENT_segment_means_full_game():
    """Every board row without an explicit segment has always meant the whole
    game. Stated rather than implied, because the defect WAS an implied value."""
    assert _row_key(_row()) == _row_key(_row(segment="full"))
    assert _row_key(_row()) == _row_key(_row(segment=None))


# ---------------------------------------------------------------------------
# Unknown must not land on the permissive branch
# ---------------------------------------------------------------------------


def test_a_series_that_LOOKS_like_a_segment_but_is_unmapped_refuses():
    """`KXMLBINNINGTOTAL` is a single inning, not a cumulative segment. An
    unknown that carries a segment marker is the one case where defaulting to
    `full` reopens the defect from the other direction."""
    assert _match_key(_match(series="KXMLBINNINGTOTAL")) is None
    assert segment_for_series("KXMLBF5RUNS") is None


def test_the_PROP_BOOK_still_indexes_and_this_is_the_load_bearing_control():
    """The first version of this fix refused every unmapped series, which would
    have unindexed the entire player-prop book -- `KXMLBKS`, `KXWNBAREB`,
    `KXMLBHIT` are all absent from the table and all inherently whole-game.
    That would have traded a $7.08 defect for no Kalshi orders at all.

    Caught by `test_the_price_resolver_is_keyed_as_tightly_as_the_join`, whose
    failure was itself the discovery that NEITHER match record carried `series`.
    """
    for series in ("KXMLBKS", "KXWNBAREB", "KXMLBHIT", "KXMLBOUTS"):
        assert segment_for_series(series) == "full", series
        assert _match_key(_match(series=series)) is not None, series


def test_a_match_record_with_no_series_still_indexes_as_full_game():
    """Absence is not a segment claim. Refusing here would make the fix depend
    on a field propagating through every construction site, which is exactly
    what was NOT true when this was written."""
    assert segment_for_series("") == "full"
    assert segment_for_series(None) == "full"
    assert _match_key(_match(series=None)) is not None


def test_F5_variants_are_a_TABLE_not_a_prefix_rule():
    """`KXMLBF5`, `KXMLBF5TOTAL` and `KXMLBF5SPREAD` are three markets. A
    `startswith("KXMLBF5")` test would fold the moneyline into the total."""
    assert segment_for_series("KXMLBF5") == "first5"
    assert segment_for_series("KXMLBF5TOTAL") == "first5"
    assert segment_for_series("KXMLBF5SPREAD") == "first5"
    # And a plausible-looking sibling that is NOT in the table stays unknown.
    assert segment_for_series("KXMLBF5RUNS") is None


def test_the_two_key_shapes_stay_one_shape():
    """`_match_key` and `_row_key` must produce the same arity or they can never
    compare equal -- the module's own docstring says two resolvers keyed by two
    slightly different tuples is how a bet gets placed at a price that was never
    quoted for it."""
    a = _row_key(_row(segment="first5"))
    b = _match_key(_match(series="KXMLBF5TOTAL"))
    assert a is not None and b is not None
    assert len(a) == len(b) == 6
