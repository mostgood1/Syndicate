"""Robinhood event contracts -- there is no Robinhood-specific API. Same
discipline as `test_coinbase_client.py`: the finding must say so, and the
Kalshi pass-through must be labelled as partial and never mistaken for
Robinhood's own confirmed catalogue.
"""

from __future__ import annotations

from syndicate.features.shared import robinhood_client


def test_finding_states_no_public_api_and_names_the_underlying_venues():
    assert robinhood_client.FINDING["status"] == "no_public_api"
    summary = robinhood_client.FINDING["summary"].lower()
    assert "kalshi" in summary
    assert "forecastex" in summary or "rothera" in summary


def test_finding_carries_an_explicit_coverage_caveat():
    """Unlike Coinbase Predict (100% Kalshi at launch), Robinhood's catalogue
    is only PARTLY Kalshi-sourced -- the caveat must say that plainly."""
    caveat = robinhood_client.FINDING["coverage_caveat"].lower()
    assert "kalshi" in caveat
    assert "forecastex" in caveat or "rothera" in caveat


def test_discover_via_kalshi_labels_the_result_as_partial(monkeypatch):
    def fake_discover(*, limit, max_pages):
        return {"markets": [], "series_count": 0, "by_series": {}}

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover", fake_discover, raising=False
    )
    result = robinhood_client.discover_via_kalshi()
    assert result["status"] == "ok"
    assert result["venue"] == "robinhood_event_contracts_via_kalshi_partial"
    assert result["venue"] != "robinhood"
    assert result["finding"] is robinhood_client.FINDING


def test_discover_via_kalshi_reports_a_kalshi_error_by_name(monkeypatch):
    from syndicate.features.shared.kalshi_client import KalshiError

    def fake_discover(*, limit, max_pages):
        raise KalshiError("all_hosts_failed: denied")

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover", fake_discover, raising=False
    )
    result = robinhood_client.discover_via_kalshi()
    assert result["status"] == "error"
    assert "all_hosts_failed" in result["reason"]
