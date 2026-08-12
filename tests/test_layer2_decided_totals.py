"""`#392` -- a total whose line is already passed kept a +EV badge and a slot.

Reported from a screenshot 2026-08-12: BAL @ MIN, bottom of the 5th, 9 runs
scored, and the board quoted `Over 14.5` (needs six more in four innings) and
`Under 10.5` (needs at most one) as live +EV opportunities.

The `ACTUAL` column rendered 9 in the served payload -- the number was joined
and displayed. Nothing compared it to `line`.
"""

from __future__ import annotations

from pipeline.intelligence_state import _mark_layer2_decided, _prune_decided_layer2_cards


def _card(*, market="totals", line=None, actual=None, kind="game"):
    return {"kind": kind, "market": market, "line": line, "actual": actual}


def test_a_total_already_reached_is_marked_decided():
    card = _card(line=10.5, actual=11.0)
    _mark_layer2_decided(card)
    assert card.get("decided") is True
    assert "10.5" in card["decided_reason"] and "11" in card["decided_reason"]


def test_the_boundary_counts_as_reached():
    # actual == line settles the over on most books' whole-number totals.
    card = _card(line=9.0, actual=9.0)
    _mark_layer2_decided(card)
    assert card.get("decided") is True


def test_a_total_not_yet_reached_is_left_alone():
    # THE ASYMMETRY: actual < line decides NOTHING. The game can still go either
    # way, and marking it would be the same confident-wrong signal being removed.
    card = _card(line=14.5, actual=9.0)
    _mark_layer2_decided(card)
    assert "decided" not in card


def test_spreads_are_not_decided_by_this_rule():
    # A margin can still swing in either direction while the game is live.
    card = _card(market="spreads", line=1.5, actual=4.0)
    _mark_layer2_decided(card)
    assert "decided" not in card


def test_a_missing_actual_or_line_decides_nothing():
    for card in (_card(line=10.5), _card(actual=11.0), _card()):
        _mark_layer2_decided(card)
        assert "decided" not in card


def test_unparseable_values_do_not_crash_or_decide():
    card = _card(line="nope", actual=11.0)
    _mark_layer2_decided(card)
    assert "decided" not in card


def test_pruning_removes_only_decided_rows_and_reports_the_count():
    live = _card(line=14.5, actual=9.0)
    done = _card(line=8.5, actual=9.0)
    for c in (live, done):
        _mark_layer2_decided(c)
    cards = [live, done]
    removed = _prune_decided_layer2_cards(cards)
    assert removed == 1
    assert cards == [live], "a still-live total was pruned"


def test_pruning_an_all_live_board_is_a_no_op():
    cards = [_card(line=14.5, actual=9.0)]
    for c in cards:
        _mark_layer2_decided(c)
    assert _prune_decided_layer2_cards(cards) == 0
    assert len(cards) == 1
