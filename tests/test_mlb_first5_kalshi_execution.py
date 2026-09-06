"""MLB first-five execution on `KXMLBF5TOTAL`.

WHY THIS FILE EXISTS AND WHAT IT IS GUARDING. Until 2026-09-05 a `first5` board
row could not acquire a Kalshi ticker at all: `KXMLBF5TOTAL` was absent from
`SERIES_SPORT`, so `classify_market` refused it as `unmapped_series` at the
first gate, and even with the series registered the join keyed the contract as
`totals_1st_5_innings` while the board row said `totals` + `segment='first5'`.
Two gaps in series, one behind the other -- fixing either alone ships inert.

THE FIRST TEST IS A REACHABILITY TEST (`off != on`), deliberately, and it is
first because this repo has shipped four inert fixes caught by nothing else.
A correctness test that passes in BOTH states measures nothing.

WHAT MUST NOT REGRESS. The 2026-08-28 defect put five real orders ($7.08) on
full-game contracts priced as three- and five-inning bets. The guard that
stopped it (`_segments_agree`) has to keep firing with these changes in place,
so the mismatch cases are asserted here too rather than left to the other file.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as kc
from syndicate.features.shared.kalshi_board_join import (
    REASON_SEGMENT_MISMATCH,
    _classify,
    _event_key,
    _match_key,
    _row_key,
    _segments_agree,
    join_kalshi_to_board,
)
from syndicate.features.shared.market_segments import split_segment_market_key

F5_TITLE = "First 5 innings: Over 6.5 runs"
F5_TICKER = "KXMLBF5TOTAL-26SEP061340SFNYM-7"


def _f5_market(**over):
    market = {
        "series": "KXMLBF5TOTAL",
        "title": F5_TITLE,
        "ticker": F5_TICKER,
        "yes_american": -110,
        "no_american": -110,
    }
    market.update(over)
    return market


def _f5_board_row(**over):
    """What production actually stores: base market, segment in its own field.

    Not `totals_1st_5_innings`. `segment_market_keys('mlb')` maps the request
    key onto exactly this pair, and `segment_for_board_row`'s docstring names
    it: "that is what production order rows carry (`segment='first5'`,
    `market='totals'`)".
    """
    row = {
        "event_id": "evt-sfnym",
        "sport": "mlb",
        "market": "totals",
        "segment": "first5",
        "line": 6.5,
        "side": "over",
        "player_name": None,
        # A GAME LINE NAMES NO CLUB, so the join resolves the event from the
        # ticker's code pair (`SFNYM`) against the board's own teams. Without
        # these the join refuses `event_not_on_our_board` BEFORE any segment
        # check -- which is a refusal the segment guard must never be credited
        # with, and is how the first draft of the end-to-end test below passed
        # for the wrong reason.
        "away_team": "SF",
        "home_team": "NYM",
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------
# REACHABILITY. `off != on`, before any correctness claim.
# ---------------------------------------------------------------------------


def test_the_series_registration_is_what_makes_the_market_readable_at_all():
    """With the registry line removed the market refuses; with it, it classifies.

    This is the `off != on` reading. `classify_market` gates on
    `sport_for_series` BEFORE it ever looks at a title, so an unregistered
    series can never reach the grammar that would have read it correctly.
    """
    assert kc.SERIES_SPORT.get("KXMLBF5TOTAL") == "mlb"

    on = kc.classify_market(_f5_market())
    assert on["status"] == "ok", on
    assert on["sport"] == "mlb"

    saved = kc.SERIES_SPORT.pop("KXMLBF5TOTAL")
    # `_DISCOVERED` is a module global nothing resets between tests -- a known
    # pollution source in this suite -- so it is cleared for the OFF read and
    # restored, or a discovery from another test would mask the refusal.
    discovered = kc._DISCOVERED.pop("KXMLBF5TOTAL", None)
    try:
        off = kc.classify_market(_f5_market())
    finally:
        kc.SERIES_SPORT["KXMLBF5TOTAL"] = saved
        if discovered is not None:
            kc._DISCOVERED["KXMLBF5TOTAL"] = discovered

    assert off["status"] == "refused"
    assert off["reason"] == kc.REASON_UNMAPPED_SERIES, off


def test_the_vocabulary_bridge_is_what_makes_the_index_lookup_hit():
    """Registering alone is NOT enough, and this is the test that proves it.

    `classify_market` returns the suffixed OddsAPI key; the board row keys on
    the base market. `_event_key` is the index the join looks the contract up
    in, so if the two spellings disagree the pairing never exists and no
    segment check is ever reached.
    """
    raw = kc.classify_market(_f5_market())
    assert raw["market"] == "totals_1st_5_innings", raw

    row_index_key = _event_key(_f5_board_row())
    assert row_index_key == ("evt-sfnym", "totals", 6.5)

    # OFF: the un-bridged spelling misses the index the board built.
    assert (
        "evt-sfnym",
        raw["market"],
        6.5,
    ) != row_index_key

    # ON: `_classify` restates it in the board's vocabulary and it hits.
    bridged = _classify(_f5_market())
    assert bridged["market"] == "totals"
    assert ("evt-sfnym", bridged["market"], 6.5) == row_index_key


def test_the_bridge_keeps_the_oddsapi_key_under_its_own_name():
    """A silent rename would make a segment market unreadable in diagnostics."""
    bridged = _classify(_f5_market())
    assert bridged["oddsapi_market_key"] == "totals_1st_5_innings"


def test_the_bridge_does_not_mutate_what_classify_market_returned():
    """Other readers in the same build call `classify_market` themselves."""
    market = _f5_market()
    direct = kc.classify_market(market)
    _classify(market)
    assert direct["market"] == "totals_1st_5_innings"


# ---------------------------------------------------------------------------
# THE KEYS MEET -- which is the whole point, and the segment survives.
# ---------------------------------------------------------------------------


def test_the_full_join_key_agrees_between_contract_and_board_row():
    verdict = _classify(_f5_market())
    match = {
        "board_event_id": "evt-sfnym",
        "series": "KXMLBF5TOTAL",
        "market": verdict["market"],
        "player_name": None,
        "line": 6.5,
        "board_side": "over",
    }
    assert _match_key(match) == _row_key(_f5_board_row())
    # ...and the segment is carried, not stripped away with the suffix.
    assert _match_key(match)[-1] == "first5"


def test_split_segment_market_key_is_the_inverse_of_the_forward_map():
    assert split_segment_market_key("mlb", "totals_1st_5_innings") == ("first5", "totals")
    # A non-segment key is returned as None -- NOT as `("full", key)`. The
    # caller must be able to leave what it does not recognise untouched.
    assert split_segment_market_key("mlb", "totals") is None
    assert split_segment_market_key("mlb", "") is None
    # Wrong sport: MLB innings are not an NBA vocabulary.
    assert split_segment_market_key("nba", "totals_1st_5_innings") is None


# ---------------------------------------------------------------------------
# WHAT MUST NOT REGRESS -- the 2026-08-28 defect, both directions.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row_segment, series, agree",
    [
        ("first5", "KXMLBF5TOTAL", True),
        ("first5", "KXMLBTOTAL", False),   # the $7.08 defect
        ("first3", "KXMLBF5TOTAL", False),  # a five-inning contract is not three
        ("full", "KXMLBF5TOTAL", False),   # the mirror failure
        ("full", "KXMLBTOTAL", True),
    ],
)
def test_segments_still_have_to_agree(row_segment, series, agree):
    row = _f5_board_row(segment=row_segment)
    assert _segments_agree(row, {"series": series}) is agree


def test_a_first5_row_does_not_match_a_full_game_contract_through_the_whole_join(
    monkeypatch,
):
    """End to end, not just at the predicate -- the bridge must not reopen it.

    `KXMLBTOTAL` classifies to `totals` with no suffix to strip, so it reaches
    the same index slot a `first5` row occupies. Only the segment separates
    them, which is exactly the 2026-08-28 shape.
    """
    full_game = {
        "series": "KXMLBTOTAL",
        "title": "Over 6.5 runs",
        "ticker": "KXMLBTOTAL-26SEP061340SFNYM-7",
        "yes_american": -110,
        "no_american": -110,
    }
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    report = join_kalshi_to_board(
        [full_game], [_f5_board_row()], selected_date="2026-09-06"
    )
    assert not report.get("matches")
    # THE NAMED REASON, not merely "some refusal happened". A market that
    # refused for an unrelated reason would satisfy a truthiness check on
    # `reasons` while proving nothing about the segment guard -- and a guard
    # credited with a refusal it did not cause is how an inert fix reads green.
    assert report["reasons"].get(REASON_SEGMENT_MISMATCH) == 1, report["reasons"]


def test_a_first5_row_DOES_match_a_first5_contract_end_to_end(monkeypatch):
    """The goal of the change, asserted through the whole join.

    Everything above tests one hop. This one runs the real path -- classify,
    resolve the event from the ticker, index, segment-check, price -- and is
    the test that would have caught either half of the fix shipping alone.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    report = join_kalshi_to_board(
        [_f5_market()], [_f5_board_row()], selected_date="2026-09-06"
    )
    assert report["reasons"].get(REASON_SEGMENT_MISMATCH) is None, report["reasons"]
    matches = report.get("matches") or []
    assert len(matches) == 1, report["reasons"]
    got = matches[0]
    assert got["ticker"] == F5_TICKER
    assert got["series"] == "KXMLBF5TOTAL"
    assert got["market"] == "totals"
    assert got["board_side"] == "over"
    # OVER takes the YES leg of a total. Asserted because a side inversion here
    # is the failure that does not look like one -- it prices, it fills, and it
    # is the opposite bet.
    assert got["kalshi_side"] == "yes"


def test_without_the_series_registration_the_same_join_matches_nothing(monkeypatch):
    """`off != on` at the JOIN level, not just at `classify_market`.

    The reachability test at the top of this file proves the registry line
    changes what the catalogue returns. This proves it changes what the join
    PRODUCES -- which is the thing that decides whether an order can carry a
    ticker, and the reading that separates a working fix from an inert one.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    saved = kc.SERIES_SPORT.pop("KXMLBF5TOTAL")
    discovered = kc._DISCOVERED.pop("KXMLBF5TOTAL", None)
    try:
        report = join_kalshi_to_board(
            [_f5_market()], [_f5_board_row()], selected_date="2026-09-06"
        )
    finally:
        kc.SERIES_SPORT["KXMLBF5TOTAL"] = saved
        if discovered is not None:
            kc._DISCOVERED["KXMLBF5TOTAL"] = discovered
    assert not (report.get("matches") or [])
    assert report["reasons"].get(kc.REASON_UNMAPPED_SERIES) == 1, report["reasons"]


def test_the_fused_board_spelling_reaches_the_same_contract(monkeypatch):
    """`market='totals_1st_5_innings'` and `market='totals'`+`segment` are one bet.

    Both spellings are live on the board, and before `_row_market` they keyed
    differently -- so which one a row happened to carry decided whether it could
    be executed at all. Asserted for the FUSED form here; the split form is the
    test above.
    """
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    fused = _f5_board_row(market="totals_1st_5_innings")
    fused.pop("segment")
    report = join_kalshi_to_board(
        [_f5_market()], [fused], selected_date="2026-09-06"
    )
    assert len(report.get("matches") or []) == 1, report["reasons"]
    # And the two spellings produce the SAME join key, which is the property
    # that makes them one bet rather than two that happen both to work.
    assert _row_key(fused) == _row_key(_f5_board_row())
