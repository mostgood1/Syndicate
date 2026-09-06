"""A main-line Kalshi contract may pair with an `_alt` board row — same bet.

WHAT THIS IS FOR. Kalshi lists F5 spreads at exactly two strikes, 1.5 and 2.5.
Measured on production 2026-09-06, the board's main-line `first5` spread rows sat
at 0.5/0.5/1.0 and every row at 1.5 or 2.5 was an `_alt` row, so `KXMLBF5SPREAD`
could not execute at all. The rows existed; the join refused them on a suffix.

WHY COLLAPSING `_alt` IS SAFE WHERE COLLAPSING SEGMENT OR SIGN IS NOT.
`alternate_totals` is OddsAPI's market for the SAME BET at non-main lines, so
`totals_alt / 4.5 / over` and `totals / 4.5 / over` on one event and segment are
one wager two feeds priced. A `first3` row against a full-game contract is a
different PORTION of the game ($7.08, 2026-08-28); a Kalshi spread states a
MARGIN where the board writes a HANDICAP, so magnitude-only pairing backs the
opposite CLUB (11 orders, 2026-08-26). Those two must keep refusing, and the
tests below assert that they still do.

THE HAZARD THIS CHANGE CREATES, and it is not the one the scope predicted.
Collapsing makes main and alt the same key, and the index holds LISTS that the
join iterates in full — so without `_collapse_duplicate_bets` one contract would
produce TWO match records, two stakeable rows, one ticker. Double exposure. The
scope called it an arbitrary pick, which would have been the harmless version;
reading the iteration before writing the code is what caught it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_catalogue as kc
from syndicate.features.shared.kalshi_board_join import (
    REASON_SEGMENT_MISMATCH,
    _collapse_duplicate_bets,
    _event_key,
    _row_key,
    _row_market,
    _segments_agree,
    join_kalshi_to_board,
)
from syndicate.features.shared.market_segments import base_market_for_alternate


def _row(**over):
    row = {
        "sport": "mlb",
        "event_id": "evt-texmil",
        "market": "spreads_alt",
        "segment": "first5",
        "line": -1.5,
        "side": "away",
        "player_name": None,
        "away_team": "TEX",
        "home_team": "MIL",
    }
    row.update(over)
    return row


def _priced(row, price):
    row = dict(row)
    row["quote"] = {"best_any_book": {"bookmaker": "fanduel", "price": price}}
    return row


# ---------------------------------------------------------------------------
# The inverse map, and what it must NOT claim.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "market, expected",
    [
        ("totals_alt", "totals"),
        ("spreads_alt", "spreads"),
        ("totals", None),      # not an alternate -- caller must leave it alone
        ("spreads", None),
        ("h2h", None),
        ("", None),
    ],
)
def test_base_market_for_alternate(market, expected):
    assert base_market_for_alternate(market) == expected


def test_row_market_collapses_alt_and_segment_together():
    """Both suffixes come off, and a fused segment spelling still works."""
    assert _row_market(_row(market="spreads_alt")) == "spreads"
    assert _row_market(_row(market="totals_alt")) == "totals"
    assert _row_market(_row(market="spreads")) == "spreads"
    # segment-fused spelling, no explicit segment field
    fused = _row(market="totals_1st_5_innings")
    fused.pop("segment")
    assert _row_market(fused) == "totals"


# ---------------------------------------------------------------------------
# REACHABILITY -- off != on, at the index the join actually looks bets up in.
# ---------------------------------------------------------------------------


def test_an_alt_row_now_lands_in_the_same_index_slot_as_the_main_line():
    """This is the whole change: one slot for one bet."""
    main = _row(market="spreads", line=-1.5)
    alt = _row(market="spreads_alt", line=-1.5)
    assert _event_key(main) == _event_key(alt)
    assert _row_key(main) == _row_key(alt)


# ---------------------------------------------------------------------------
# THE DOUBLE-EXPOSURE GUARD.
# ---------------------------------------------------------------------------


def test_two_rows_for_one_bet_collapse_to_one():
    rows = [_priced(_row(market="spreads"), -120), _priced(_row(market="spreads_alt"), -110)]
    out, collisions = _collapse_duplicate_bets(rows)
    assert collisions == 1
    assert len(out) == 1


def test_the_tiebreak_keeps_the_better_price_in_EITHER_insertion_order():
    """Order-independence is the property; a list-order winner is the bug."""
    good = _priced(_row(market="spreads_alt"), -110)   # better for the bettor
    bad = _priced(_row(market="spreads"), -550)
    for rows in ([good, bad], [bad, good]):
        out, collisions = _collapse_duplicate_bets(list(rows))
        assert collisions == 1
        assert _row_price_of(out[0]) == -110, [r.get("market") for r in out]


def _row_price_of(row):
    return row["quote"]["best_any_book"]["price"]


def test_an_unpriced_row_loses_to_a_priced_one():
    out, _ = _collapse_duplicate_bets([_row(market="spreads"), _priced(_row(market="spreads_alt"), -110)])
    assert _row_price_of(out[0]) == -110


def test_on_an_exact_price_tie_the_main_line_survives():
    for rows in ([_priced(_row(market="spreads_alt"), -110), _priced(_row(market="spreads"), -110)],
                 [_priced(_row(market="spreads"), -110), _priced(_row(market="spreads_alt"), -110)]):
        out, _ = _collapse_duplicate_bets(list(rows))
        assert out[0]["market"] == "spreads"


def test_opposite_sides_are_NOT_collapsed():
    """The index key omits side, so the dedupe must carry it or a bet vanishes."""
    rows = [_row(side="away", line=-1.5), _row(side="home", line=1.5)]
    out, collisions = _collapse_duplicate_bets(rows)
    assert collisions == 0 and len(out) == 2


def test_different_segments_are_NOT_collapsed():
    rows = [_row(segment="first5"), _row(segment="first3")]
    out, collisions = _collapse_duplicate_bets(rows)
    assert collisions == 0 and len(out) == 2


def test_a_row_with_no_identity_passes_through_untouched():
    """No event id -> `_row_key` is None -> never collapsed against anything."""
    anon = _row()
    anon.pop("event_id")
    out, collisions = _collapse_duplicate_bets([anon, dict(anon)])
    assert collisions == 0 and len(out) == 2


# ---------------------------------------------------------------------------
# WHAT MUST NOT REGRESS -- the two distinctions that are real.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row_segment, series, agree",
    [
        ("first5", "KXMLBF5TOTAL", True),
        ("first5", "KXMLBTOTAL", False),   # the $7.08 defect
        ("full", "KXMLBF5TOTAL", False),
    ],
)
def test_the_segment_guard_is_untouched_by_the_alt_collapse(row_segment, series, agree):
    assert _segments_agree(_row(market="totals_alt", segment=row_segment), {"series": series}) is agree


def test_a_full_game_contract_still_refuses_an_alt_segment_row_end_to_end(monkeypatch):
    """By NAMED reason -- `matched == 0` alone would pass for the wrong cause."""
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    market = {
        "series": "KXMLBTOTAL",
        "title": "Over 6.5 runs",
        "ticker": "KXMLBTOTAL-26SEP061340TEXMIL-7",
        "yes_american": -110,
        "no_american": -110,
    }
    row = _row(market="totals_alt", segment="first5", line=6.5, side="over")
    report = join_kalshi_to_board([market], [row], selected_date="2026-09-06")
    assert not report.get("matches")
    assert report["reasons"].get(REASON_SEGMENT_MISMATCH) == 1, report["reasons"]


def test_the_collision_counter_is_reported_even_when_zero(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    report = join_kalshi_to_board([], [_row()], selected_date="2026-09-06")
    assert report["alt_main_collisions"] == 0
