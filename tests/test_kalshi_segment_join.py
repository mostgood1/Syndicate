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


# ---------------------------------------------------------------------------
# `#604` -- THE GUARD MUST BE VISIBLE, NOT MERELY EFFECTIVE
# ---------------------------------------------------------------------------


def test_the_refusal_reason_is_actually_REFERENCED_not_just_defined():
    """`REASON_SEGMENT_MISMATCH` was defined and used NOWHERE.

    The key fix works silently -- two tuples fail to compare equal -- which is
    indistinguishable from a venue that stopped quoting. `#601`'s own VERIFY
    line asked for a refusal count that did not exist. This test fails if the
    constant is ever orphaned again.
    """
    import inspect

    from syndicate.features.shared import kalshi_board_join as mod

    src = inspect.getsource(mod)
    assert src.count("REASON_SEGMENT_MISMATCH") >= 2, "constant is defined but never used"


def test_a_segment_row_and_a_full_game_contract_DISAGREE():
    from syndicate.features.shared.kalshi_board_join import _segments_agree

    assert not _segments_agree({"segment": "first3"}, {"series": "KXMLBTOTAL"})
    assert not _segments_agree({"segment": "first5"}, {"series": "KXMLBTOTAL"})


def test_matching_segments_AGREE_including_the_absent_case():
    from syndicate.features.shared.kalshi_board_join import _segments_agree

    assert _segments_agree({"segment": "first5"}, {"series": "KXMLBF5TOTAL"})
    assert _segments_agree({}, {"series": "KXMLBTOTAL"})
    assert _segments_agree({"segment": None}, {"series": "KXMLBTOTAL"})
    assert _segments_agree({"segment": " FULL "}, {"series": "KXMLBTOTAL"})


def test_an_unmappable_SEGMENT_MARKER_series_refuses_rather_than_agreeing():
    """The mirror failure: a whole-game row must not land on a segment contract
    we could not identify."""
    from syndicate.features.shared.kalshi_board_join import _segments_agree

    assert not _segments_agree({}, {"series": "KXMLBINNINGTOTAL"})


def test_the_PROP_BOOK_still_agrees_and_this_is_the_control_again():
    """Props are whole-game and unmapped; `#601`'s first version would have
    refused them all. This guard must not resurrect that."""
    from syndicate.features.shared.kalshi_board_join import _segments_agree

    for series in ("KXMLBKS", "KXWNBAREB", "KXMLBHIT"):
        assert _segments_agree({}, {"series": series}), series


def test_the_match_record_does_not_carry_TWO_series_keys():
    """The earlier fix stamped `market.get("series")` into records that already
    carried the NORMALISED `verdict.get("series")`. It won by being last in the
    dict literal -- harmless here, and exactly the kind of thing that is not
    harmless the next time the order changes."""
    import inspect

    from syndicate.features.shared import kalshi_board_join as mod

    src = inspect.getsource(mod)
    assert '"series": market.get("series")' not in src


# ---------------------------------------------------------------------------
# THE SECOND VOCABULARY -- the near-miss inside the fix
# ---------------------------------------------------------------------------


def test_a_SUFFIX_vocabulary_row_is_not_mistaken_for_a_full_game_row():
    """The board spells a segment TWO ways and only one is a `segment` field.

    `totals_1st_5_innings` carries NO `segment` field -- the market NAME is the
    segment. `#601` keyed absent as `full`, so such a row keyed `full` while its
    CORRECT `KXMLBF5TOTAL` contract keyed `first5`, and a legitimate first-five
    pairing would have stopped resolving. That is the original defect inverted:
    not a wrong bet, a silently missing one.

    Caught by `test_a_total_takes_its_side_from_the_title`, whose fixture rows
    have no `segment` field at all -- which is why it was written that way and
    why it must stay that way.
    """
    from syndicate.features.shared.kalshi_catalogue import segment_for_board_row

    assert segment_for_board_row({"market": "totals_1st_5_innings"}) == "first5"
    assert segment_for_board_row({"market": "spreads_1st_3_innings"}) == "first3"
    assert segment_for_board_row({"market": "spreads_q1"}) == "q1"
    assert segment_for_board_row({"market": "totals"}) == "full"


def test_the_EXPLICIT_field_wins_over_the_market_name():
    """Production order rows carry `segment='first5'` WITH `market='totals'`.
    The field is the authority when both could speak."""
    from syndicate.features.shared.kalshi_catalogue import segment_for_board_row

    assert segment_for_board_row({"segment": "first3", "market": "totals"}) == "first3"
    assert segment_for_board_row(
        {"segment": "first5", "market": "totals_1st_5_innings"}
    ) == "first5"


def test_the_two_vocabularies_agree_on_the_SAME_key():
    """A suffix row and a field row for the same bet must key identically, or
    the join silently splits one market into two."""
    from syndicate.features.shared.kalshi_board_join import _row_key

    suffix = _row_key({"event_id": "e", "sport": "mlb",
                       "market": "totals_1st_5_innings", "line": 3.5, "side": "under"})
    assert suffix is not None and suffix[5] == "first5"
