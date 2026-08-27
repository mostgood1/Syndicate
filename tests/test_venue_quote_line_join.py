"""The OddsAPI venue adapter must publish quotes AT THEIR LINE.

Every lined OddsAPI quote was structurally unmatchable: the adapter read
`american` from the entry VALUE (`last_odds`) but the line from the KEY, and
these shards carry no `line=` in the key. So `quote_key` built `soccer|totals|
over` -- not a bet, and unable to meet the board's `soccer|totals|over|2.5`.

The property that matters here is not "more matches". It is that a match can
only ever happen at the SAME number, which is `quote_key`'s own rule: "a spread
at -1.5 and the same spread at -2.5 are different bets, and collapsing them
prices one at the other's number."
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_quote_adapters import (
    _oddsapi_quote_line,
    _parse_odds_history_key,
    quote_key,
)


SOCCER_KEY = "event_id=e1|home_team=Real Madrid|away_team=Celta Vigo|market=totals|side=Over|book=draftkings"


def _entry(**over):
    base = {
        "last_odds": -110,
        "last_line": 2.5,
        "previous_line": 2.5,
        "delta": 0,
        "history": [],
    }
    base.update(over)
    return base


def test_the_line_comes_from_the_value_when_the_key_has_none():
    """THE FIX. The real shard shape: no `line=` in the key, `last_line` in the
    value. Returns None before the fix, 2.5 after."""
    parsed = _parse_odds_history_key(SOCCER_KEY)

    assert parsed.get("line") is None, "fixture must reproduce the real shard: no line in the key"
    assert _oddsapi_quote_line("totals", parsed, _entry()) == 2.5


def test_the_resulting_key_can_meet_the_board():
    """The join, end to end on both halves. The board asks for a lined key; the
    venue must produce the identical string."""
    parsed = _parse_odds_history_key(SOCCER_KEY)
    line = _oddsapi_quote_line("totals", parsed, _entry())

    venue = quote_key("soccer", "totals", "over", line)
    board = quote_key("soccer", "totals", "over", 2.5)

    assert venue == board == "soccer|totals|over|2.5"


def test_a_different_line_still_does_not_match():
    """The safety property, stated as a test rather than as a comment. Adding
    the line must ENFORCE `quote_key`'s rule, never relax it."""
    parsed = _parse_odds_history_key(SOCCER_KEY)
    venue = quote_key("soccer", "totals", "over", _oddsapi_quote_line("totals", parsed, _entry(last_line=3.5)))

    assert venue != quote_key("soccer", "totals", "over", 2.5)


def test_the_key_wins_when_it_carries_a_line():
    """A sport whose shard IS line-bearing must be completely unchanged."""
    keyed = _parse_odds_history_key(SOCCER_KEY + "|line=1.5")

    assert _oddsapi_quote_line("totals", keyed, _entry(last_line=9.5)) == 1.5


@pytest.mark.parametrize("market", ["h2h", "h2h_h1", "h2h_h2"])
def test_h2h_never_takes_a_line_even_when_the_value_has_one(market):
    """THE REGRESSION GUARD, and the reason this is not a one-line change.
    `last_line` is a MOVEMENT field and appears on h2h entries too. Reading it
    there would turn `soccer|h2h|draw` into `soccer|h2h|draw|0` and break the
    one market family that already matches -- a regression bought with a fix."""
    parsed = _parse_odds_history_key(
        "event_id=e1|home_team=Real Madrid|away_team=Celta Vigo|market=h2h|side=Draw|book=draftkings"
    )

    assert _oddsapi_quote_line(market, parsed, _entry(last_line=0)) is None
    assert quote_key("soccer", market, "draw", None) == f"soccer|{market}|draw"


def test_spreads_take_the_line_too():
    parsed = _parse_odds_history_key(
        "event_id=e1|home_team=Real Madrid|away_team=Celta Vigo|market=spreads|side=Real Madrid|book=draftkings"
    )

    assert _oddsapi_quote_line("spreads", parsed, _entry(last_line=-1.5)) == -1.5


def test_a_lined_market_with_no_line_anywhere_stays_none():
    """Refused rather than invented. This is the residual the adapter now
    REPORTS as `lined_market_without_line` instead of publishing silently."""
    parsed = _parse_odds_history_key(SOCCER_KEY)

    assert _oddsapi_quote_line("totals", parsed, _entry(last_line=None)) is None
