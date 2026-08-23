"""Kalshi's own market data.

The endpoint and field names in this module are UNVERIFIED -- the agent proxy
denies the host, so they were written without ever calling the API. These tests
therefore cover the parts that do not depend on the endpoint being right: the
price conversion (pure arithmetic, and the piece the rest of the system reads),
and the refusal behaviour that keeps a wrong schema from looking like an empty
venue.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_client import (
    KalshiError,
    cents_to_american,
    cents_to_probability,
    normalize_market,
)


# --- the conversion the whole board depends on ----------------------------


@pytest.mark.parametrize("cents,expected", [(62, 0.62), (50, 0.5), (1, 0.01), (99, 0.99)])
def test_cents_are_probability_directly(cents, expected):
    """A Kalshi contract settles at $1, so its price in cents IS the implied
    probability. 62c means the market says 62%."""
    assert cents_to_probability(cents) == pytest.approx(expected)


def test_a_favourite_converts_to_negative_american():
    """THE CONVERSION THAT MATTERS. Passing 62 through unconverted would read as
    +62 to every downstream consumer -- 61.7% implied rendered as 38%."""
    assert cents_to_american(62) == -163


def test_an_underdog_converts_to_positive_american():
    assert cents_to_american(38) == 163


def test_the_conversion_is_symmetric_about_even_money():
    """p and 1-p must produce mirrored prices, or one side of every market is
    systematically mispriced."""
    assert cents_to_american(50) == -100
    assert cents_to_american(5) == -cents_to_american(95)


def test_a_round_trip_preserves_the_probability():
    for cents in (5, 25, 49, 51, 75, 95):
        american = cents_to_american(cents)
        implied = (
            abs(american) / (abs(american) + 100)
            if american < 0
            else 100 / (american + 100)
        )
        assert implied == pytest.approx(cents / 100.0, abs=0.001)


@pytest.mark.parametrize("cents", [0, 100, -5, 150, None, "", "abc"])
def test_untradeable_prices_are_refused_not_converted(cents):
    """0 and 100 are a settled or absent market, not a price. Treating either as
    a probability produces an infinite or zero-payout bet downstream."""
    assert cents_to_probability(cents) is None
    assert cents_to_american(cents) is None


# --- a wrong schema must be loud ------------------------------------------


def test_missing_fields_are_named_on_every_row():
    """The schema is unverified. If it is wrong, the first production run has to
    say WHICH field rather than leaving a silently-None column."""
    row = normalize_market({"ticker": "KXMLB-25AUG22-NYY", "yes_ask": 62})
    assert row["ticker"] == "KXMLB-25AUG22-NYY"
    assert "event_ticker" in row["missing_fields"]
    assert row["yes_american"] == -163


def test_a_complete_market_reports_no_missing_fields():
    complete = {
        "ticker": "T", "event_ticker": "E", "series_ticker": "S", "title": "t",
        "subtitle": "s", "status": "open", "yes_bid": 60, "yes_ask": 62,
        "no_bid": 36, "no_ask": 38, "last_price": 61, "volume": 10,
        "open_time": "x", "close_time": "y", "strike_type": "greater",
        "floor_strike": 1.5, "cap_strike": None,
    }
    row = normalize_market(complete)
    assert row["missing_fields"] == []
    assert row["yes_american"] == -163
    assert row["no_american"] == 163


def test_both_sides_are_converted_independently():
    """yes and no are separately quoted and their asks do not sum to 100 (that
    gap is the spread). Deriving one from the other would erase it."""
    row = normalize_market({"yes_ask": 62, "no_ask": 40})
    assert row["yes_probability"] == pytest.approx(0.62)
    assert row["no_probability"] == pytest.approx(0.40)


def test_fetch_refuses_rather_than_returning_an_empty_list(monkeypatch):
    """An empty list would read as 'Kalshi lists nothing', which is the precise
    wrong conclusion this module exists to prevent."""
    import syndicate.features.shared.kalshi_client as mod

    def boom(url, **kw):
        raise KalshiError("connect_rejected")

    monkeypatch.setattr(mod, "_get", boom)
    with pytest.raises(KalshiError) as excinfo:
        mod.fetch_markets(series_ticker="KXMLBGAME")
    assert "all_hosts_failed" in str(excinfo.value)


def test_a_non_list_markets_payload_is_refused(monkeypatch):
    import syndicate.features.shared.kalshi_client as mod

    monkeypatch.setattr(mod, "_get", lambda url, **kw: {"markets": {"not": "a list"}})
    with pytest.raises(KalshiError):
        mod.fetch_markets()


def test_paging_stops_and_reports_truncation(monkeypatch):
    """A cursor that never terminates would page forever; the stop is reported
    so a partial listing is never mistaken for the whole one."""
    import syndicate.features.shared.kalshi_client as mod

    monkeypatch.setattr(
        mod, "_get", lambda url, **kw: {"markets": [{"ticker": "T"}], "cursor": "always"}
    )
    report = mod.fetch_markets(max_pages=3)
    assert report["pages"] == 3
    assert report["truncated"] is True
    assert report["count"] == 3


# --- discovery -------------------------------------------------------------


def test_discover_groups_by_series_from_kalshis_own_tickers(monkeypatch):
    """UNFILTERED on purpose. Fetching by series_ticker needs the ticker, and a
    guessed one that does not exist returns an empty page indistinguishable from
    a venue listing nothing -- the exact false negative this module exists to
    avoid. Grouping an unfiltered pull takes the tickers from Kalshi instead."""
    import syndicate.features.shared.kalshi_client as mod

    monkeypatch.setattr(mod, "_get", lambda url, **kw: {"markets": [
        {"ticker": "A", "series_ticker": "KXMLBGAME", "title": "Yankees win?", "yes_ask": 62},
        {"ticker": "B", "series_ticker": "KXMLBGAME", "title": "Sox win?", "yes_ask": 45},
        {"ticker": "C", "series_ticker": "KXNBAPTS", "title": "Over 20.5 pts?", "yes_ask": 51},
    ], "cursor": None})
    report = mod.discover()
    assert report["series_count"] == 2
    assert report["by_series"]["KXMLBGAME"] == 2
    assert report["series_examples"]["KXNBAPTS"] == "Over 20.5 pts?"


def test_discover_orders_series_by_volume():
    """The biggest series first, because the question is what Kalshi mostly
    lists, not what it lists alphabetically."""
    import syndicate.features.shared.kalshi_client as mod

    original = mod._get
    mod._get = lambda url, **kw: {"markets": [
        {"series_ticker": "SMALL", "yes_ask": 50},
        {"series_ticker": "BIG", "yes_ask": 50},
        {"series_ticker": "BIG", "yes_ask": 50},
    ], "cursor": None}
    try:
        assert list(mod.discover()["by_series"]) == ["BIG", "SMALL"]
    finally:
        mod._get = original


def test_a_market_with_no_series_is_labelled_not_dropped(monkeypatch):
    import syndicate.features.shared.kalshi_client as mod

    monkeypatch.setattr(mod, "_get", lambda url, **kw: {
        "markets": [{"ticker": "A", "yes_ask": 50}], "cursor": None})
    assert mod.discover()["by_series"]["<absent>"] == 1
