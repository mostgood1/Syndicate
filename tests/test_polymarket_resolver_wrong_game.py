"""A resolver must never hand back another game's contract.

MEASURED 2026-08-25 14:57:34Z -- three attempted purchases, two with a slug for
a DIFFERENT GAME than the row they were stamped on:

  board row                                        stamped slug
  totals under 8.5 · Cincinnati Reds @ SF Giants   tsc-mlb-bal-stl-2026-08-25-8pt5
  h2h home · Texas Rangers @ Chicago White Sox     aec-mlb-pit-sd-2026-08-25

Both resolvers keyed on `(market, player_name, line, side)`. A GAME LINE HAS NO
PLAYER, so every MLB h2h home row in the slate hashed to `("h2h", "", None,
"home")` and the index kept whichever game was written last.

The join was never wrong -- it matches each row through `_teams_match` and
refuses ambiguity outright. The defect was flattening that per-row result into a
key that no longer said which row produced it.

The order did not go through, and that was luck: the submit-time resolver had
been rebuilt from a slate holding fewer matches, so it returned nothing and
`polymarket_us_orders` raised `market_unresolved_for_position`. Had it held one
entry for that key, the order would have been submitted against another game's
contract at a price quoted for that other game.
"""

from __future__ import annotations

from syndicate.features.shared.polymarket_board_join import (
    polymarket_price_resolver,
    polymarket_ticker_resolver,
)


def _match(event_id, slug, price, *, market="h2h", side="home", line=None, **extra):
    base = {
        "event_id": event_id,
        "market": market,
        "side": side,
        "line": line,
        "player_name": None,
        "polymarket_slug": slug,
        "polymarket_american": price,
        "tick_size": 0.005,
        "minimum_trade_qty": 0.01,
    }
    base.update(extra)
    return base


def _row(event_id, *, market="h2h", side="home", line=None):
    return {"event_id": event_id, "market": market, "side": side,
            "line": line, "player_name": None, "sport": "mlb"}


TEX_CWS = _match("evt-tex-cws", "aec-mlb-tex-cws-2026-08-25", 115)
PIT_SD = _match("evt-pit-sd", "aec-mlb-pit-sd-2026-08-25", -130)


def test_two_games_sharing_a_market_do_not_collide():
    """THE BUG, as a property. Same market, same side, no player, no line --
    identical under the old key, and the second silently overwrote the first."""
    resolve = polymarket_ticker_resolver([TEX_CWS, PIT_SD])

    assert resolve(_row("evt-tex-cws"))["slug"] == "aec-mlb-tex-cws-2026-08-25"
    assert resolve(_row("evt-pit-sd"))["slug"] == "aec-mlb-pit-sd-2026-08-25"
    # Both survive: the index holds two entries, not one.
    assert resolve.market_count == 2


def test_the_price_resolver_cannot_quote_another_games_number():
    """The two resolvers share one key function on purpose. A row priced from
    one game and contracted on another is a bet placed at a price never quoted
    for it."""
    price = polymarket_price_resolver([TEX_CWS, PIT_SD])

    assert price(_row("evt-tex-cws")) == 115.0
    assert price(_row("evt-pit-sd")) == -130.0


def test_totals_at_the_SAME_line_in_different_games_stay_apart():
    """The other half of the production reading: `("totals", "", 8.5, "under")`
    was one key for every 8.5 total on the slate, and BAL@STL won it."""
    cin_sf = _match("evt-cin-sf", "tsc-mlb-cin-sf-2026-08-25-8pt5", -115,
                    market="totals", side="under", line=8.5)
    bal_stl = _match("evt-bal-stl", "tsc-mlb-bal-stl-2026-08-25-8pt5", -105,
                     market="totals", side="under", line=8.5)
    resolve = polymarket_ticker_resolver([cin_sf, bal_stl])

    got = resolve(_row("evt-cin-sf", market="totals", side="under", line=8.5))
    assert got["slug"] == "tsc-mlb-cin-sf-2026-08-25-8pt5"
    # The exact wrong answer production produced.
    assert got["slug"] != "tsc-mlb-bal-stl-2026-08-25-8pt5"


def test_a_row_for_a_game_with_no_market_resolves_to_NOTHING(monkeypatch):
    """Not to whatever shares its market shape. This is the case that used to
    return a confident wrong slug rather than None."""
    resolve = polymarket_ticker_resolver([PIT_SD])
    assert resolve(_row("evt-tex-cws")) is None
    assert polymarket_price_resolver([PIT_SD])(_row("evt-tex-cws")) is None


def test_a_match_with_no_event_id_is_NEVER_INDEXED():
    """An empty id would restore the collision under a different spelling --
    every id-less match sharing one `("", market, ...)` bucket. Not indexed
    means not resolved means no order, which is the direction that fails safe.
    """
    orphan = _match(None, "aec-mlb-bal-stl-2026-08-25", 100)
    resolve = polymarket_ticker_resolver([orphan, TEX_CWS])

    assert resolve.market_count == 1
    assert resolve(_row(None)) is None
    assert resolve(_row("")) is None
    # And the real one is unaffected by its presence.
    assert resolve(_row("evt-tex-cws"))["slug"] == "aec-mlb-tex-cws-2026-08-25"


def test_a_ROW_with_no_event_id_resolves_to_nothing_rather_than_the_first_match():
    resolve = polymarket_ticker_resolver([TEX_CWS, PIT_SD])
    assert resolve({"market": "h2h", "side": "home", "line": None}) is None


def test_the_two_resolvers_agree_on_identity():
    """Keyed by one shared function. Two nearly-identical tuples would pair a
    row with one market's price and another's contract."""
    matches = [TEX_CWS, PIT_SD]
    ticker = polymarket_ticker_resolver(matches)
    price = polymarket_price_resolver(matches)

    for event_id in ("evt-tex-cws", "evt-pit-sd", "evt-absent"):
        row = _row(event_id)
        assert (ticker(row) is None) == (price(row) is None), event_id


# --- the same defect in Kalshi, which Polymarket copied its shape from -------


def test_kalshi_resolvers_also_key_on_the_game():
    """`kalshi_board_join` had the identical key and had NOT yet produced the
    failure -- for two reasons, neither of which is a guard:

      * its board join currently supplies only PLAYER PROPS, and a player name
        happens to identify a game;
      * `_match_key` returns None when `float(line)` fails, so an h2h with no
        line is never indexed at all (this is the `no_live_price: None` seen on
        the third attempted purchase, 2026-08-25 14:57:34Z).

    The 171 Kalshi game series registered that day would have removed both
    accidents at once. Pinned here rather than waiting for the same incident on
    the venue that already holds real money.
    """
    from syndicate.features.shared.kalshi_board_join import (
        kalshi_price_resolver,
        kalshi_ticker_resolver,
    )

    def _m(event_id, ticker, price):
        return {"board_event_id": event_id, "ticker": ticker, "market": "totals",
                "player_name": None, "line": 8.5, "board_side": "over",
                "kalshi_american": price}

    def _r(event_id):
        return {"event_id": event_id, "market": "totals", "player_name": None,
                "line": 8.5, "side": "over", "sport": "mlb"}

    matches = [_m("evt-cin-sf", "KXMLBTOT-CINSF-O8.5", -115),
               _m("evt-bal-stl", "KXMLBTOT-BALSTL-O8.5", -105)]
    ticker = kalshi_ticker_resolver(matches)
    price = kalshi_price_resolver(matches)

    assert ticker(_r("evt-cin-sf")) == "KXMLBTOT-CINSF-O8.5"
    assert ticker(_r("evt-bal-stl")) == "KXMLBTOT-BALSTL-O8.5"
    assert price(_r("evt-cin-sf")) == -115.0
    assert ticker(_r("evt-absent")) is None


def test_a_kalshi_match_with_no_event_id_is_never_indexed():
    from syndicate.features.shared.kalshi_board_join import kalshi_ticker_resolver

    orphan = {"board_event_id": None, "ticker": "KX-ORPHAN", "market": "totals",
              "player_name": None, "line": 8.5, "board_side": "over"}
    resolve = kalshi_ticker_resolver([orphan])
    assert resolve({"event_id": "", "market": "totals", "player_name": None,
                    "line": 8.5, "side": "over", "sport": "mlb"}) is None
