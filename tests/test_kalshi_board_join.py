"""Matching a Kalshi market to the board row for the same bet.

#505 is the cautionary case: the settlement join matched on an id that changed
whenever the price moved and reported 4,560 no_key_match of 8,276. So these
tests are weighted toward the ways a join produces a CONFIDENT WRONG MATCH
rather than an obvious failure.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import (
    REASON_NO_BOARD_ROW,
    REASON_UNMAPPED_SERIES,
    REASON_UNPARSEABLE_TITLE,
    join_kalshi_to_board,
    normalize_person,
    parse_prop_title,
    series_to_market,
    threshold_to_line,
)


# --- the half-point convention --------------------------------------------


def test_seven_plus_is_over_six_point_five():
    """THE CONVENTION THAT WOULD MISMATCH EVERY LINE. Kalshi says "at least N";
    the board says "over N-0.5". Both pay at 7 or more."""
    assert threshold_to_line(7) == 6.5


def test_matching_a_threshold_against_its_own_integer_finds_nothing():
    """7+ against a line of 7.0 is not the same bet, and must not match."""
    assert threshold_to_line(7) != 7.0


def test_off_by_a_half_would_be_a_different_bet():
    """7+ is Over 6.5, NOT Over 7.5. Matching the latter would price a
    different bet confidently -- worse than no match."""
    assert threshold_to_line(7) != 7.5
    assert threshold_to_line(8) == 7.5


# --- title parsing ---------------------------------------------------------


def test_a_strikeout_title_parses():
    parsed = parse_prop_title("Andrew Abbott: 7+ strikeouts?")
    assert parsed["player_name"] == "Andrew Abbott"
    assert parsed["threshold"] == 7


def test_an_outs_title_parses():
    parsed = parse_prop_title("Andrew Abbott: 17+ Outs Recorded?")
    assert parsed["threshold"] == 17
    assert parsed["stat_text"] == "Outs Recorded"


@pytest.mark.parametrize("title", ["", None, "yes Cruz Azul", "Will over 8.5 goals be scored?",
                                   "Andrew Abbott strikeouts", "Abbott: many+ strikeouts?"])
def test_an_unreadable_title_returns_None_not_a_partial_parse(title):
    """A half-parsed player name would match the WRONG HUMAN — learnings.md's
    'worse at any stake than no bet'."""
    assert parse_prop_title(title) is None


def test_names_normalise_across_accents_and_punctuation():
    """Feeds disagree on accents and suffixes; a period must not decide whether
    a bet matches."""
    assert normalize_person("José Ramírez") == normalize_person("Jose Ramirez")
    assert normalize_person("Ronald Acuña Jr.") == normalize_person("Ronald Acuna Jr")


def test_series_mapping_is_explicit_and_refuses_the_unknown():
    assert series_to_market("KXMLBKS") == "pitcher_strikeouts"
    assert series_to_market("KXMLBOUTS") == "pitcher_outs"
    # Parlay series and anything unrecognised must never be guessed into a market.
    assert series_to_market("KXMVECROSSCATEGORY") is None
    assert series_to_market("KXNEWTHING") is None


# --- the join --------------------------------------------------------------


def _kalshi(title="Andrew Abbott: 7+ strikeouts?", series="KXMLBKS", **kw):
    market = {
        "ticker": "KXMLBKS-25AUG22ABBOTT-7",
        "series": series,
        "title": title,
        "yes_american": -120,
        "no_american": 105,
        "yes_probability": 0.545,
        "no_probability": 0.488,
    }
    market.update(kw)
    return market


def _row(side="Over", line=6.5, market="pitcher_strikeouts", player="Andrew Abbott", **kw):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": market,
        "player_name": player,
        "line": line,
        "side": side,
        "model_edge_pct": 2.0,
        "quote": {"bookmaker": "draftkings", "price": -110},
    }
    row.update(kw)
    return row


def test_a_matching_bet_pairs_over_with_YES():
    report = join_kalshi_to_board([_kalshi()], [_row(side="Over")])
    assert report["matched"] == 1
    match = report["matches"][0]
    assert match["kalshi_side"] == "yes"
    assert match["kalshi_american"] == -120
    assert match["line"] == 6.5


def test_under_pairs_with_NO_and_takes_NOs_own_price():
    """yes and no are separately quoted and do not sum to 1 — the gap is the
    spread. Deriving one from the other would invent edge."""
    report = join_kalshi_to_board([_kalshi()], [_row(side="Under")])
    match = report["matches"][0]
    assert match["kalshi_side"] == "no"
    assert match["kalshi_american"] == 105


def test_both_sides_of_one_market_match_independently():
    report = join_kalshi_to_board([_kalshi()], [_row(side="Over"), _row(side="Under")])
    assert report["matched"] == 2
    assert {m["kalshi_american"] for m in report["matches"]} == {-120, 105}


def test_a_line_that_does_not_correspond_does_not_match():
    """The half-point test again, through the join: 7+ must not pair with 7.5."""
    report = join_kalshi_to_board([_kalshi()], [_row(line=7.5)])
    assert report["matched"] == 0
    assert report["reasons"][REASON_NO_BOARD_ROW] == 1


def test_a_different_player_does_not_match():
    report = join_kalshi_to_board([_kalshi()], [_row(player="Shane Baz")])
    assert report["matched"] == 0


def test_a_different_market_family_does_not_match():
    """A strikeouts market must never pair with an outs row at the same number."""
    report = join_kalshi_to_board([_kalshi()], [_row(market="pitcher_outs")])
    assert report["matched"] == 0


def test_parlay_markets_are_refused_by_name():
    report = join_kalshi_to_board(
        [_kalshi(series="KXMVECROSSCATEGORY", title="yes Tampa Bay,yes Shane Baz: 2+")],
        [_row()],
    )
    assert report["reasons"][REASON_UNMAPPED_SERIES] == 1


def test_an_unparseable_title_is_named_separately_from_a_missing_row():
    """'We could not read this market' and 'Kalshi has nothing we bet' are
    different facts and must not share a counter."""
    report = join_kalshi_to_board([_kalshi(title="Will over 8.5 goals be scored?")], [_row()])
    assert report["reasons"][REASON_UNPARSEABLE_TITLE] == 1
    assert REASON_NO_BOARD_ROW not in report["reasons"]


def test_accented_names_still_join():
    report = join_kalshi_to_board(
        [_kalshi(title="José Ramírez: 3+ strikeouts?")],
        [_row(player="Jose Ramirez", line=2.5)],
    )
    assert report["matched"] == 1


def test_every_market_is_accounted_for():
    """matched + refusals == markets in, or the join is not a measurement."""
    markets = [_kalshi(), _kalshi(series="KXMVECROSSCATEGORY"), _kalshi(title="junk")]
    report = join_kalshi_to_board(markets, [_row()])
    assert report["matched"] + sum(report["reasons"].values()) == len(markets)


def test_the_price_resolver_is_keyed_as_tightly_as_the_join():
    """A resolver looser than the join would silently reintroduce exactly the
    mismatches the join refuses."""
    from syndicate.features.shared.kalshi_board_join import kalshi_price_resolver

    resolve = kalshi_price_resolver([{
        "market": "pitcher_strikeouts", "player_name": "Andrew Abbott",
        "line": 6.5, "board_side": "over", "kalshi_american": -120,
    }])
    assert resolve(_row(side="Over", line=6.5)) == -120
    # Every one of these is a different bet and must not resolve.
    assert resolve(_row(side="Under", line=6.5)) is None
    assert resolve(_row(side="Over", line=7.5)) is None
    assert resolve(_row(side="Over", line=6.5, player="Shane Baz")) is None
    assert resolve(_row(side="Over", line=6.5, market="pitcher_outs")) is None


# --- the join must stay inside one slate -----------------------------------


def test_a_market_closing_on_another_date_is_refused():
    """MEASURED 2026-08-23T04:22Z: Kalshi was quoting tomorrow's MLB while the
    board had rolled to European soccer. Nothing matched — correct, but only by
    luck that the vocabularies did not overlap. A pitcher with the same line on
    two different days WOULD have matched the wrong game."""
    from syndicate.features.shared.kalshi_board_join import REASON_WRONG_DATE

    market = _kalshi(title="Lake Bachar: 6+ strikeouts?", close_time="2026-08-24T02:10:00Z")
    row = _row(player="Lake Bachar", line=5.5)
    assert join_kalshi_to_board([market], [row], selected_date="2026-08-24")["matched"] == 1
    stale = join_kalshi_to_board([market], [row], selected_date="2026-08-22")
    assert stale["matched"] == 0
    assert stale["reasons"][REASON_WRONG_DATE] == 1


def test_the_date_is_compared_on_the_DAY_not_the_timestamp():
    """A night game closes after midnight UTC. An exact timestamp comparison
    would drop precisely the games this board is mostly about (#370)."""
    market = _kalshi(title="Lake Bachar: 6+ strikeouts?", close_time="2026-08-24T02:10:00Z")
    row = _row(player="Lake Bachar", line=5.5)
    assert join_kalshi_to_board([market], [row], selected_date="2026-08-24")["matched"] == 1


def test_no_selected_date_skips_the_check_rather_than_guessing():
    """A caller that does not know the slate date gets the old behaviour, not a
    silent filter."""
    market = _kalshi(title="Lake Bachar: 6+ strikeouts?", close_time="2026-08-24T02:10:00Z")
    assert join_kalshi_to_board([market], [_row(player="Lake Bachar", line=5.5)])["matched"] == 1


def test_a_market_with_no_close_time_is_not_dropped_by_the_date_check():
    """Absent is not wrong-date. Refusing it would hide markets for a reason
    that has nothing to do with the slate."""
    market = _kalshi(title="Lake Bachar: 6+ strikeouts?")
    assert join_kalshi_to_board(
        [market], [_row(player="Lake Bachar", line=5.5)], selected_date="2026-08-24"
    )["matched"] == 1
