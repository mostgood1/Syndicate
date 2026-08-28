"""A segment bet must not be placed on a full-game Polymarket contract.

MEASURED 2026-08-28, real money, FOUR orders -- the same defect Kalshi had the
same day (`#601`), in the sibling join, found only because the Kalshi audit was
repeated against the other venue:

    first3  h2h home  aec-mlb-lad-det-2026-08-28   +199,  $2.35
    first3  h2h away  aec-mlb-tex-mil-2026-08-28   +160,  $2.52
    first5  h2h home  aec-mlb-lad-det-2026-08-28   +208,  $2.11
    first3  h2h away  aec-mlb-pit-stl-2026-08-28   +106,  $2.40

WHAT MAKES THIS ONE SHARPER THAN KALSHI'S. The venue side of this join ALREADY
refuses segment markets (`segment_market_not_full_game`), so every indexed
Polymarket market is guaranteed full-game. A `first3` row therefore could not
match a CORRECT contract -- only a wrong one. The guarantee that made the index
safe is what made the missing board-side check unsafe.

`layer2_board.py:623` keys a board row on `(event_id, market, segment, line,
player_name)`. The board has always treated segment as part of a row's
identity; both venue resolvers dropped it.
"""

from __future__ import annotations

from syndicate.features.shared.polymarket_board_join import _resolver_key


def _rec(**kw):
    r = {"event_id": "evt-1", "market": "h2h", "player_name": None,
         "line": None, "side": "home"}
    r.update(kw)
    return r


def test_a_first3_row_no_longer_resolves_to_the_full_game_market():
    """The lad-det and pit-stl orders. A match record carries no `segment` and
    is always full-game; before the fix both sides hashed to the same 5-tuple."""
    assert _resolver_key(_rec(segment="first3")) != _resolver_key(_rec())


def test_a_first5_row_no_longer_resolves_to_the_full_game_market():
    assert _resolver_key(_rec(segment="first5")) != _resolver_key(_rec())


def test_a_full_game_row_STILL_resolves_and_this_is_the_control():
    """68 of the 72 orders on the board that day were full-game. A fix that
    stopped them would trade four wrong bets for no bets."""
    assert _resolver_key(_rec()) == _resolver_key(_rec(segment="full"))
    assert _resolver_key(_rec()) == _resolver_key(_rec(segment=None))
    assert _resolver_key(_rec()) is not None


def test_the_match_record_shape_still_keys_absent_segment_as_full_game():
    """The MATCH record has no `segment` key at all -- it is built from
    event_id/market/side/line/player_name plus the venue slug. Absent must mean
    full game or every Polymarket order stops resolving."""
    match = {"event_id": "evt-1", "market": "h2h", "side": "home",
             "line": None, "player_name": None, "polymarket_slug": "aec-mlb-lad-det"}
    assert "segment" not in match
    assert _resolver_key(match) == _resolver_key(_rec(segment="full"))


def test_segment_is_compared_case_and_whitespace_insensitively():
    assert _resolver_key(_rec(segment="  FULL ")) == _resolver_key(_rec())
    assert _resolver_key(_rec(segment="First3")) == _resolver_key(_rec(segment="first3"))


def test_a_row_with_no_event_id_is_still_refused():
    """The pre-existing fail-safe must survive the change."""
    assert _resolver_key(_rec(event_id="", segment="full")) is None


def test_the_key_is_a_SIX_tuple_on_both_record_shapes():
    """One shared function serves the price resolver and the ticker resolver,
    so an arity drift between callers is impossible by construction -- but the
    arity must actually have grown, or the segment is not in the key at all."""
    a = _resolver_key(_rec())
    b = _resolver_key(_rec(segment="first5"))
    assert len(a) == len(b) == 6
    assert a[5] == "full" and b[5] == "first5"
