"""Prop matches feed the QUOTE CAPTURE, not the ORDER PATH -- until armed.

The join admits MLB player props (2026-09-01, lane
`polymarket-prop-quote-capture`) so the venue's own prop prices reach
`book_quotes`. The resolvers in `portfolio_commit._polymarket_price_resolver`
are a different consumer: whatever they index becomes priceable and
ticker-stamped for the paper AND live books. Widening the money path was not
that change's decision, so prop matches are withheld from the resolvers behind
`SYNDICATE_POLYMARKET_PROP_RESOLVERS`, OFF by default.

Both directions are asserted (off != on), because a gate tested only in its
default state is indistinguishable from a gate that ignores its switch -- the
inert-feature failure the model-engine standard exists for.
"""

from __future__ import annotations

import json
import time

import pipeline.portfolio_commit as pc


def _prop_market():
    return {
        "slug": "astatc-mlb-pit-sd-2026-08-24-hits-jacmer-gte2",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.40"]),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 1,
    }


def _game_market():
    return {
        "slug": "aec-mlb-pit-sd-2026-08-24",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
        "outcomes": json.dumps(["Pirates", "Padres"]),
        "outcomePrices": json.dumps(["0.45", "0.55"]),
        "orderPriceMinTickSize": 0.01,
        "minimumTradeQty": 1,
    }


def _prop_row():
    return {
        "market": "batter_hits", "side": "over", "line": 1.5,
        "player_name": "Jackson Merrill",
        "home": "San Diego Padres", "away": "Pittsburgh Pirates",
        "selected_date": "2026-08-24", "sport": "mlb",
        "event_id": "evt-pit-sd",
    }


def _game_row():
    return {
        "market": "h2h", "side": "Padres", "line": None,
        "home": "San Diego Padres", "away": "Pittsburgh Pirates",
        "selected_date": "2026-08-24", "sport": "mlb",
        "event_id": "evt-pit-sd",
    }


def _wire(monkeypatch, captured):
    from syndicate.features.shared import polymarket_board_join as join_mod

    monkeypatch.setattr(
        join_mod, "load_polymarket_markets",
        lambda: ([_prop_market(), _game_market()], time.time()),
    )
    monkeypatch.setattr(
        pc, "_board_rows_for_join", lambda selected_date: [_prop_row(), _game_row()]
    )
    # The capture is its own covered surface; here it only has to be OBSERVED,
    # because capture-before-gate is the ordering this file exists to pin.
    monkeypatch.setattr(
        pc, "_capture_polymarket_quotes",
        lambda report, board_rows, selected_date: captured.append(report),
    )


def test_prop_matches_are_withheld_from_the_resolvers_by_default(monkeypatch):
    monkeypatch.delenv("SYNDICATE_POLYMARKET_PROP_RESOLVERS", raising=False)
    captured: list = []
    _wire(monkeypatch, captured)

    price, ticker = pc._polymarket_price_resolver("2026-08-24")

    # The CAPTURE saw the prop match -- the gate sits downstream of it.
    assert captured and any(
        (m.get("player_name") or "") for m in captured[0]["matches"]
    )
    # The RESOLVERS did not: the game line prices, the prop does not.
    assert price is not None and ticker is not None
    assert price(_game_row()) == -122
    assert price(_prop_row()) is None
    assert ticker(_prop_row()) is None


def test_arming_the_switch_lets_props_resolve(monkeypatch):
    monkeypatch.setenv("SYNDICATE_POLYMARKET_PROP_RESOLVERS", "1")
    captured: list = []
    _wire(monkeypatch, captured)

    price, ticker = pc._polymarket_price_resolver("2026-08-24")

    assert price is not None and ticker is not None
    # P(Yes)=0.62 -> American on the over leg.
    assert price(_prop_row()) is not None
    stamped = ticker(_prop_row())
    assert stamped is not None
    assert stamped["slug"] == "astatc-mlb-pit-sd-2026-08-24-hits-jacmer-gte2"


def test_an_all_prop_slate_returns_no_resolvers_rather_than_empty_ones(monkeypatch):
    """Withholding EVERY match must land in the documented `(None, None)`
    no-direct-feed contract, not a resolver that answers None to everything
    while claiming market_count coverage."""
    from syndicate.features.shared import polymarket_board_join as join_mod

    monkeypatch.delenv("SYNDICATE_POLYMARKET_PROP_RESOLVERS", raising=False)
    captured: list = []
    monkeypatch.setattr(
        join_mod, "load_polymarket_markets", lambda: ([_prop_market()], time.time())
    )
    monkeypatch.setattr(pc, "_board_rows_for_join", lambda selected_date: [_prop_row()])
    monkeypatch.setattr(
        pc, "_capture_polymarket_quotes",
        lambda report, board_rows, selected_date: captured.append(report),
    )

    assert pc._polymarket_price_resolver("2026-08-24") == (None, None)
    assert captured and captured[0]["matched"] == 1
