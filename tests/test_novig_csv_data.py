"""Novig's public CSV mirror -- REAL structure (data.novig.com/reporting/
trade-data/...), supplied directly by the user 2026-08-24, replacing an
earlier flat-path guess (`{base}/markets.csv`) that 403'd because it was
never going to exist. See `novig_client.py`'s module header for the full
story and for why this is END-OF-DAY data, never a live price.

Sample rows below are taken VERBATIM from the real documentation supplied,
not invented -- the point of this file is to pin this module's parsing
against known-real examples, the same way `test_novig_orders.py` pins
`order_body` against a real worked `curl` example.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from syndicate.features.shared.novig_client import (
    cents_to_american,
    cents_to_probability,
    fetch_daily_csv,
    fetch_latest_markets_snapshot,
    fetch_trade_data_index,
    latest_market_date,
    normalize_market_row,
    normalize_trade_row,
)


class _FakeHTTPResponse:
    def __init__(self, *, body: bytes):
        self._body = body
        self.status = 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# --- cents_to_probability / cents_to_american --------------------------------


def test_cents_to_probability_matches_the_documented_example():
    """The docs' own worked example: "a close of 47.5 is a probability of
    0.475"."""
    assert cents_to_probability(47.5) == pytest.approx(0.475)
    assert cents_to_probability("47.5") == pytest.approx(0.475)


@pytest.mark.parametrize("cents", [0, 100, 100.0, -1, None, "", "not_a_number"])
def test_cents_to_probability_refuses_untradeable_values(cents):
    assert cents_to_probability(cents) is None


def test_cents_to_american_composes_with_probability_to_american():
    assert cents_to_american(62.0) == -163


def test_cents_and_decimal_probability_conventions_are_NOT_interchangeable():
    """THE WHOLE REASON THIS IS A SEPARATE FUNCTION. Handing a REST-tier
    0-1 probability to the cents converter (or vice versa) must not silently
    produce a number -- 0.62 as cents is 0.62% probability, not 62%."""
    from syndicate.features.shared.novig_client import probability_to_american

    # 0.62 read as a decimal probability (REST tier) is a big favourite.
    assert probability_to_american(0.62) == -163
    # The SAME 0.62 read as a cents price (CSV tier) is a near-impossible
    # underdog -- a 100x-shaped error if the two are ever confused.
    assert cents_to_american(0.62) != probability_to_american(0.62)


# --- normalize_trade_row ------------------------------------------------------


def test_normalize_trade_row_matches_the_documented_straight_taker_example():
    """Verbatim first row of the real trades.csv example."""
    row = normalize_trade_row(
        {
            "timestamp": "2026-08-04T17:03:11Z",
            "outcomeId": "0b1c...",
            "marketId": "7f2e...",
            "contractSeries": "Basketball Moneyline",
            "league": "NBA",
            "marketType": "MONEY",
            "tradeType": "STRAIGHT",
            "legs": "1",
            "cost": "45.5",
            "qty": "100",
            "side": "TAKER",
        }
    )
    assert row["league"] == "NBA"
    assert row["market_type"] == "MONEY"
    assert row["trade_type"] == "STRAIGHT"
    assert row["legs"] == 1
    assert row["cost"] == Decimal("45.5")
    assert row["qty"] == Decimal("100")
    # "Price one side paid -- cost / qty, a probability between 0 and 1."
    assert row["price_probability"] == pytest.approx(0.455)
    assert row["side"] == "TAKER"


def test_normalize_trade_row_reports_combo_rows_with_empty_league_and_market_type():
    """Verbatim COMBO row: "Empty for a COMBO" for both league and
    marketType -- must read as None, not the literal empty string."""
    row = normalize_trade_row(
        {
            "timestamp": "2026-08-04T18:41:52Z",
            "outcomeId": "9d8c...",
            "marketId": "9d8c...",
            "contractSeries": "Parlay",
            "league": "",
            "marketType": "",
            "tradeType": "COMBO",
            "legs": "3",
            "cost": "50",
            "qty": "200",
            "side": "TAKER",
        }
    )
    assert row["league"] is None
    assert row["market_type"] is None
    assert row["trade_type"] == "COMBO"
    assert row["legs"] == 3
    assert row["price_probability"] == pytest.approx(0.25)


def test_normalize_trade_row_uses_decimal_not_float_for_cost_and_qty():
    """The docs' own words: "cost and qty are strings carrying full numeric
    precision." A raw float parse is the exact class of bug already fixed
    once in this lane (novig_orders.cash_units_for_stake)."""
    row = normalize_trade_row({"cost": "12.345", "qty": "100"})
    assert row["cost"] == Decimal("12.345")
    assert isinstance(row["cost"], Decimal)


def test_normalize_trade_row_handles_a_missing_or_zero_qty_without_dividing_by_zero():
    row = normalize_trade_row({"cost": "10", "qty": "0"})
    assert row["price_probability"] is None
    row_missing = normalize_trade_row({"cost": "10"})
    assert row_missing["price_probability"] is None


# --- normalize_market_row -----------------------------------------------------


def test_normalize_market_row_matches_the_documented_order_book_example():
    """Verbatim first row of the real markets.csv example."""
    row = normalize_market_row(
        {
            "date": "2026-08-09",
            "marketId": "019fddfe...",
            "reportTicker": "ATP-FIRST_SET_MONEYLINE",
            "openInterest": "0.00",
            "dailyVolume": "420.73",
            "open": "50.5",
            "high": "54.5",
            "low": "50.5",
            "close": "51.0",
            "status": "finalized",
        }
    )
    assert row["report_ticker"] == "ATP-FIRST_SET_MONEYLINE"
    assert row["open_interest"] == Decimal("0.00")
    assert row["daily_volume"] == Decimal("420.73")
    assert row["close_probability"] == pytest.approx(0.51)
    assert row["close_american"] == probability_american_of(0.51)
    assert row["status"] == "finalized"
    assert row["traded_today"] is True


def test_normalize_market_row_matches_the_documented_combo_example():
    """A combination's open/high/low/close are all its one trade's price."""
    row = normalize_market_row(
        {
            "date": "2026-08-09",
            "marketId": "019fe4ad...",
            "reportTicker": "COMBO",
            "openInterest": "0.00",
            "dailyVolume": "85.91",
            "open": "20.0",
            "high": "20.0",
            "low": "20.0",
            "close": "20.0",
            "status": "finalized",
        }
    )
    assert row["report_ticker"] == "COMBO"
    assert row["open_probability"] == row["close_probability"] == pytest.approx(0.20)


def test_normalize_market_row_reports_no_trades_today_as_none_not_zero():
    """Verbatim third row: an active market with zero volume and EMPTY OHLC
    -- "Empty if the market did not trade that day, which is NOT the same as
    having traded at zero.\""""
    row = normalize_market_row(
        {
            "date": "2026-08-09",
            "marketId": "019fcbf2...",
            "reportTicker": "MLB-AL_CENTRAL_DIVISION_WINNER",
            "openInterest": "9.25",
            "dailyVolume": "0.00",
            "open": "",
            "high": "",
            "low": "",
            "close": "",
            "status": "active",
        }
    )
    assert row["open_probability"] is None
    assert row["close_probability"] is None
    assert row["close_american"] is None
    assert row["traded_today"] is False
    # open interest is real and nonzero even with no volume today.
    assert row["open_interest"] == Decimal("9.25")
    assert row["daily_volume"] == Decimal("0.00")


def probability_american_of(p):
    from syndicate.features.shared.novig_client import probability_to_american

    return probability_to_american(p)


# --- fetch_trade_data_index ---------------------------------------------------


def test_fetch_trade_data_index_parses_the_documented_manifest_shape(monkeypatch):
    body = json.dumps({"dates": ["2026-08-07", "2026-08-06"], "marketDates": ["2026-08-06", "2026-08-07"]}).encode()
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: _FakeHTTPResponse(body=body),
    )
    result = fetch_trade_data_index()
    assert result["status"] == "ok"
    assert result["dates"] == ["2026-08-06", "2026-08-07"]  # sorted
    assert result["market_dates"] == ["2026-08-06", "2026-08-07"]


def test_fetch_trade_data_index_treats_absent_market_dates_as_empty_list(monkeypatch):
    """"marketDates ... is absent on manifests published before that file
    existed -- read it as an empty list.\""""
    body = json.dumps({"dates": ["2026-08-06"]}).encode()
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: _FakeHTTPResponse(body=body),
    )
    result = fetch_trade_data_index()
    assert result["status"] == "ok"
    assert result["market_dates"] == []


def test_fetch_trade_data_index_refuses_a_malformed_manifest(monkeypatch):
    body = json.dumps({"notDates": []}).encode()
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: _FakeHTTPResponse(body=body),
    )
    result = fetch_trade_data_index()
    assert result["status"] == "error"
    assert result["reason"] == "no_dates_array"


# --- latest_market_date --------------------------------------------------------


def test_latest_market_date_returns_the_last_published_date():
    index = {"status": "ok", "dates": [], "market_dates": ["2026-08-06", "2026-08-07"]}
    result = latest_market_date(index)
    assert result == {"status": "ok", "date": "2026-08-07"}


def test_latest_market_date_refuses_when_none_are_published():
    index = {"status": "ok", "dates": [], "market_dates": []}
    result = latest_market_date(index)
    assert result["status"] == "error"
    assert result["reason"] == "no_market_dates_published"


def test_latest_market_date_propagates_an_index_fetch_failure():
    index = {"status": "error", "reason": "http_403"}
    result = latest_market_date(index)
    assert result["status"] == "error"
    assert result["reason"] == "http_403"


# --- fetch_daily_csv (dated) ---------------------------------------------------


def test_fetch_daily_csv_requires_a_date():
    result = fetch_daily_csv("markets", "")
    assert result == {"status": "error", "reason": "no_date"}


def test_fetch_daily_csv_refuses_an_invalid_name():
    result = fetch_daily_csv("wagers", "2026-08-09")
    assert result["status"] == "error"
    assert result["reason"] == "invalid_name"


def test_fetch_daily_csv_builds_the_documented_dated_url(monkeypatch):
    csv_text = "date,marketId,status\n2026-08-09,abc,active\n"
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: _FakeHTTPResponse(body=csv_text.encode()),
    )
    result = fetch_daily_csv("markets", "2026-08-09")
    assert result["status"] == "ok"
    assert result["url"] == "https://data.novig.com/reporting/trade-data/2026-08-09/markets.csv"
    assert result["count"] == 1
    assert result["rows"][0]["marketId"] == "abc"


# --- fetch_latest_markets_snapshot ---------------------------------------------


def test_fetch_latest_markets_snapshot_orchestrates_index_then_dated_csv(monkeypatch):
    index_body = json.dumps({"dates": ["2026-08-09"], "marketDates": ["2026-08-09"]}).encode()
    markets_csv = (
        "date,marketId,reportTicker,openInterest,dailyVolume,open,high,low,close,status\n"
        "2026-08-09,m1,ATP-FIRST_SET_MONEYLINE,0.00,420.73,50.5,54.5,50.5,51.0,active\n"
        "2026-08-09,m2,MLB-SPREAD,0.00,0.00,,,,,closed\n"
    )
    responses = [
        _FakeHTTPResponse(body=index_body),
        _FakeHTTPResponse(body=markets_csv.encode()),
    ]
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: responses.pop(0),
    )
    result = fetch_latest_markets_snapshot()
    assert result["status"] == "ok"
    assert result["date"] == "2026-08-09"
    # default status_filter keeps only "active" -- the closed row is dropped.
    assert result["count"] == 1
    assert result["markets"][0]["report_ticker"] == "ATP-FIRST_SET_MONEYLINE"
    assert isinstance(result["is_stale_by_days"], int)
    assert result["is_stale_by_days"] >= 0


def test_fetch_latest_markets_snapshot_with_no_status_filter_keeps_everything(monkeypatch):
    index_body = json.dumps({"dates": [], "marketDates": ["2026-08-09"]}).encode()
    markets_csv = (
        "date,marketId,reportTicker,openInterest,dailyVolume,open,high,low,close,status\n"
        "2026-08-09,m1,X,0.00,1.00,50.0,50.0,50.0,50.0,active\n"
        "2026-08-09,m2,Y,0.00,0.00,,,,,closed\n"
    )
    responses = [
        _FakeHTTPResponse(body=index_body),
        _FakeHTTPResponse(body=markets_csv.encode()),
    ]
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: responses.pop(0),
    )
    result = fetch_latest_markets_snapshot(status_filter=None)
    assert result["count"] == 2


def test_fetch_latest_markets_snapshot_refuses_by_name_with_no_market_dates(monkeypatch):
    index_body = json.dumps({"dates": ["2026-08-09"], "marketDates": []}).encode()
    monkeypatch.setattr(
        "syndicate.features.shared.novig_client.urllib.request.urlopen",
        lambda *a, **kw: _FakeHTTPResponse(body=index_body),
    )
    result = fetch_latest_markets_snapshot()
    assert result["status"] == "error"
    assert result["reason"] == "no_market_dates_published"
