"""OddsAPI's market, side and line live in the shard KEY, not the entry value.

MEASURED 2026-08-25 against a real shard entry:

  KEY   event_id=..|home_team=Cincinnati Reds|away_team=Chicago Cubs
        |market=h2h|bookmaker=fanduel
  VALUE delta, delta_line, history, last_line, last_odds, last_snapshot_ts,
        last_source_path, last_updated, movement, percent_change, previous_line

`entry.get("market")`, `("side")`, `("line")`, `("american")`, `("price")` and
`("probability")` are ALL None. So every quote was built as
`quote_key(sport, None, None, None)` -- one identical useless key for the whole
shard, carrying no price -- and oddsapi reported `quotes: 298` while winning
ZERO selections and stamping ZERO rows.

That is why `beyond_quote_age` was killing the board: stamping is the only
thing that resets a row's age, and a source emitting priceless quotes on a
single collided key can never stamp anything.

It survived review because `quotes` was non-empty, so `status` read `ok`.
"""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared import venue_quote_adapters as adapters
from syndicate.features.shared.venue_quote_adapters import _parse_odds_history_key


# ---------------------------------------------------------------------------
# The key parser
# ---------------------------------------------------------------------------


def test_a_soccer_key_yields_market_and_side():
    key = ("event_id=a979|home_team=Real Madrid|away_team=Real Sociedad"
           "|market=h2h|side=Draw|book=draftkings")

    parsed = _parse_odds_history_key(key)

    assert parsed["market"] == "h2h"
    assert parsed["side"] == "Draw"
    assert parsed["event_id"] == "a979"


def test_an_mlb_key_yields_market_but_NO_side():
    """The shapes genuinely differ by sport -- mlb keys carry `bookmaker=` and
    no side at all. A parser assuming one shape would drop the other."""
    key = ("event_id=2716|home_team=Cincinnati Reds|away_team=Chicago Cubs"
           "|market=h2h|bookmaker=fanduel")

    parsed = _parse_odds_history_key(key)

    assert parsed["market"] == "h2h"
    assert parsed.get("side") is None
    assert parsed["bookmaker"] == "fanduel"


def test_a_line_in_the_key_parses_as_a_number():
    parsed = _parse_odds_history_key("market=totals|side=Over|line=8.5|book=fanduel")
    assert parsed["line"] == 8.5


def test_a_key_with_no_pairs_yields_nothing_rather_than_raising():
    assert _parse_odds_history_key("").get("market") is None
    assert _parse_odds_history_key(None).get("market") is None


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


def _shard(markets):
    return {"updated_at": "2026-08-25T02:00:00Z", "markets": markets}


@pytest.fixture
def _shard_of(monkeypatch):
    def install(markets):
        monkeypatch.setattr(
            "syndicate.features.shared.odds_control_plane."
            "load_odds_history_payload_for_sport",
            lambda sport, date: _shard(markets),
        )
    return install


def test_a_sided_entry_becomes_a_REAL_key_and_a_REAL_price(_shard_of):
    _shard_of({
        "event_id=a979|home_team=Real Madrid|away_team=Real Sociedad"
        "|market=h2h|side=Draw|book=draftkings": {"last_odds": 260.0},
    })

    outcome = adapters.oddsapi_outcome("soccer", "2026-08-24")

    assert len(outcome.quotes) == 1
    quote = outcome.quotes[0]
    assert quote.key == "soccer|h2h|draw"
    assert quote.american == 260


def test_an_entry_with_no_side_is_REFUSED_and_counted(_shard_of):
    """`last_odds` with no side says nothing about WHICH team. Emitting it
    against a guessed side is a price for the wrong team."""
    _shard_of({
        "event_id=2716|home_team=Cincinnati Reds|away_team=Chicago Cubs"
        "|market=h2h|bookmaker=fanduel": {"last_odds": 750.0},
    })

    outcome = adapters.oddsapi_outcome("mlb", "2026-08-24")

    assert outcome.quotes == []
    assert "no_side_in_key:1" in (outcome.reason or "")


def test_the_drop_counts_ride_on_a_SUCCESSFUL_read(_shard_of):
    """12 usable out of 300 is not the same as 12 out of 12, and only the
    reason string says which."""
    _shard_of({
        "market=h2h|side=Draw|book=dk": {"last_odds": 260.0},
        "market=h2h|bookmaker=fanduel": {"last_odds": 750.0},
        "market=h2h|side=Home|book=dk": {},
    })

    outcome = adapters.oddsapi_outcome("soccer", "2026-08-24")

    assert outcome.status == "ok"
    assert len(outcome.quotes) == 1
    assert "no_side_in_key:1" in outcome.reason
    assert "no_last_odds:1" in outcome.reason


def test_the_old_behaviour_would_have_collided_every_key():
    """Pins WHY this mattered: the pre-fix key for every entry was identical.

    A dict keyed on that collapses an entire shard to one entry, which is how
    298 quotes stamped zero rows.
    """
    from syndicate.features.shared.venue_quote_adapters import quote_key

    collided = {quote_key("soccer", None, None, None) for _ in range(3)}

    assert collided == {"soccer||"}
    assert len(collided) == 1
