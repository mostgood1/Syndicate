"""OG.com ("Crypto.com OG") -- no public API confirmed to exist yet. Covers
the finding contents and that `probe()` degrades honestly when the candidate
host is unreachable (as it is from this sandbox -- see the module header).
"""

from __future__ import annotations

import urllib.error

from syndicate.features.shared import cryptocom_client


def test_finding_states_no_public_api_yet_and_names_og_dot_com():
    assert cryptocom_client.FINDING["status"] == "no_public_api_yet"
    assert cryptocom_client.FINDING["product"] == "og_dot_com_prediction_markets"
    assert "cdna" in cryptocom_client.FINDING["summary"].lower()


def test_finding_explicitly_rejects_the_uncorroborated_third_party_endpoint():
    """The one concrete endpoint research found (`/api/v1/predictions/events`)
    must be documented as REJECTED, not silently absent -- silence here would
    look like it was never considered rather than deliberately excluded."""
    assert "rejected_source" in cryptocom_client.FINDING
    assert "predictions/events" in cryptocom_client.FINDING["rejected_source"]


def test_probe_reports_a_named_error_when_the_host_is_unreachable(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.URLError("connect_rejected")

    monkeypatch.setattr(
        "syndicate.features.shared.cryptocom_client.urllib.request.urlopen", fail
    )
    result = cryptocom_client.probe()
    assert result["status"] == "error"
    assert "connect_rejected" in result["error"]
    assert result["finding"] is cryptocom_client.FINDING


def test_probe_never_silently_returns_ok_on_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("url", 403, "forbidden", {}, None)

    monkeypatch.setattr(
        "syndicate.features.shared.cryptocom_client.urllib.request.urlopen", fail
    )
    result = cryptocom_client.probe()
    assert result["status"] == "error"
    assert result["error"] == "http_403"
