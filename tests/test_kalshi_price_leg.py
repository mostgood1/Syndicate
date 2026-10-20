"""The Kalshi price and the Kalshi order body must agree on the leg.

Measured 2026-10-20 21:35:55Z: OKC +20.5 (`side=away`, spreads_alt, line +20.5) is the
NO leg of KXNBASPREAD-26OCT20OKCSAS-SAS21, but `_kalshi_price_for` read the YES ask
($0.08). `order_body_v2` then quoted its complement and sized off it:
`side=ask count=125 price=0.92` (buy NO at $0.08) instead of NO at ~$0.93 x 10.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

YES_ASK = 0.08
NO_ASK = 0.93
TICKER = "KXNBASPREAD-26OCT20OKCSAS-SAS21"


@dataclass
class _Req:
    side: str
    market: str | None
    line: float | None
    venue_ticker: str = TICKER
    requested_stake_dollars: float = 10.0
    position_key: str = "pk"
    selected_date: str = "2026-10-20"
    venue: str = "kalshi"
    sport: str = "nba"
    event_id: str = "evt"
    player_name: str | None = None


@pytest.fixture
def quotes(monkeypatch):
    from syndicate.features.shared import kalshi_client
    import pipeline.execute_portfolio as runner

    monkeypatch.setattr(
        kalshi_client,
        "fetch_market",
        lambda ticker: {"status": "ok", "market": {"ticker": ticker, "yes_ask_dollars": YES_ASK, "no_ask_dollars": NO_ASK}},
    )
    # No artifact price: no slippage comparison, the live ask is returned as read.
    monkeypatch.setattr(runner, "_artifact_price", lambda t, k: None)
    return runner


@pytest.mark.parametrize(
    "side,market,line,expected",
    [
        ("away", "spreads_alt", 20.5, NO_ASK),   # the measured case: taking points = NO
        ("home", "spreads", 7.5, NO_ASK),
        ("home", "spreads_alt", -20.5, YES_ASK),  # laying points = YES
        ("away", "spreads", -3.5, YES_ASK),
        ("home", "h2h", None, YES_ASK),           # per-team ticker: always YES
        ("away", "h2h", None, YES_ASK),
        ("draw", "h2h", None, YES_ASK),
        ("over", "totals", 44.5, YES_ASK),
        ("under", "totals", 44.5, NO_ASK),
        ("under", "player_points", 9.5, NO_ASK),
        ("over", "player_threes", 1.5, YES_ASK),
        ("no", None, None, NO_ASK),
        ("yes", None, None, YES_ASK),
    ],
)
def test_the_price_is_read_from_the_leg_the_body_buys(quotes, side, market, line, expected):
    from syndicate.features.shared.kalshi_orders import _side_to_kalshi

    req = _Req(side=side, market=market, line=line)
    assert quotes._kalshi_price_for(req) == expected
    # And it is the leg the body will buy.
    assert (expected == NO_ASK) == (_side_to_kalshi(side, market, line) == "no")


def test_an_unmappable_side_keeps_the_old_literal_rule(quotes):
    """The body refuses these by name (`unmappable_side`); the price read must not raise first."""
    assert quotes._kalshi_price_for(_Req(side="home", market="totals", line=44.5)) == YES_ASK
    assert quotes._kalshi_price_for(_Req(side="under", market="weird_market", line=None)) == NO_ASK


def test_the_measured_order_now_builds_as_NO_at_the_no_ask_for_the_stake(quotes):
    """End to end through `order_body_v2`: $10 on OKC +20.5 at the NO ask $0.93 is 10 contracts,
    sent as an ask on YES at the complement $0.07 -- not 125 contracts at $0.92."""
    from syndicate.features.shared.kalshi_orders import order_body_v2

    req = _Req(side="away", market="spreads_alt", line=20.5)
    body = order_body_v2(req, price_dollars=quotes._kalshi_price_for(req))
    assert body["side"] == "ask"
    assert body["price"] == "0.0700"
    assert body["count"] == "10.00"
