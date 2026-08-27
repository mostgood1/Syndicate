"""Coinbase Predict -- there is no Coinbase-specific API, so what needs
testing is that the module says so honestly and that its pass-through to
Kalshi's client is correctly labelled, never mistaken for Coinbase's own data.
"""

from __future__ import annotations

from syndicate.features.shared import coinbase_client


def test_finding_states_the_no_distinct_api_conclusion():
    assert coinbase_client.FINDING["status"] == "no_distinct_api"
    assert "kalshi" in coinbase_client.FINDING["summary"].lower()


def test_discover_via_kalshi_labels_the_result_distinctly_from_coinbase(monkeypatch):
    """The venue tag must never read as plain 'coinbase' -- that would claim
    this is Coinbase's own confirmed catalogue, which research could not
    establish."""

    def fake_discover(*, limit, max_pages):
        return {"markets": [], "series_count": 0, "by_series": {}}

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover", fake_discover, raising=False
    )
    result = coinbase_client.discover_via_kalshi()
    assert result["status"] == "ok"
    assert result["venue"] == "coinbase_predict_via_kalshi"
    assert result["venue"] != "coinbase"
    assert result["finding"] is coinbase_client.FINDING


def test_discover_via_kalshi_reports_a_kalshi_error_by_name(monkeypatch):
    from syndicate.features.shared.kalshi_client import KalshiError

    def fake_discover(*, limit, max_pages):
        raise KalshiError("all_hosts_failed: denied")

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.discover", fake_discover, raising=False
    )
    result = coinbase_client.discover_via_kalshi()
    assert result["status"] == "error"
    assert "all_hosts_failed" in result["reason"]


def test_probe_never_raises_even_if_kalshi_client_is_unreachable(monkeypatch):
    def broken_probe():
        raise RuntimeError("network denied")

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_client.probe", broken_probe, raising=False
    )
    result = coinbase_client.probe()
    assert "finding" in result
    assert "error" in result["kalshi_probe"]
