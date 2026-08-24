"""Polymarket US's Sports API -- events by league or sport.

The endpoint shapes here are DOCUMENTED (the user pasted Polymarket's own
Sports API reference verbatim, 2026-08-24) so these tests pin the URL/query
construction against that documentation directly. The ROW SCHEMA is not
documented -- no test here asserts on event field names, matching
`probe_league`'s own job of reporting that shape rather than assuming it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import polymarket_us_sports_client as mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("POLYMARKET_US_API_KEY_ID", raising=False)
    monkeypatch.delenv("POLYMARKET_US_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_US_API_BASE", raising=False)
    yield


def _arm_credentials(monkeypatch):
    monkeypatch.setenv("POLYMARKET_US_API_KEY_ID", "11111111-2222-3333-4444-555555555555")
    import base64

    monkeypatch.setenv("POLYMARKET_US_PRIVATE_KEY", base64.b64encode(bytes(range(32))).decode())


def _stub_signed_request(monkeypatch, payload=None, *, error=None):
    calls = []

    def fake(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_auth.signed_request", fake
    )
    return calls


# --- sport-key mapping -----------------------------------------------------


def test_documented_example_slugs_map_to_themselves():
    """nfl/nba/mlb are the docs' own documented examples."""
    assert mod.syndicate_sport_to_polymarket_league("nfl") == "nfl"
    assert mod.syndicate_sport_to_polymarket_league("nba") == "nba"
    assert mod.syndicate_sport_to_polymarket_league("mlb") == "mlb"


def test_an_unmapped_sport_returns_none_not_a_guess_at_call_time():
    assert mod.syndicate_sport_to_polymarket_league("soccer") is None
    assert mod.syndicate_sport_to_polymarket_league("curling") is None


def test_the_mapping_is_case_insensitive():
    assert mod.syndicate_sport_to_polymarket_league("NFL") == "nfl"


# --- URL construction -------------------------------------------------------


def test_fetch_league_events_hits_the_documented_v2_path(monkeypatch):
    _arm_credentials(monkeypatch)
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_league_events("nfl")
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.polymarket.us/v2/leagues/nfl/events"
    assert calls[0]["method"] == "GET"


def test_fetch_sport_events_hits_the_documented_v2_path(monkeypatch):
    _arm_credentials(monkeypatch)
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_sport_events("football")
    assert calls[0]["url"] == "https://api.polymarket.us/v2/sports/football/events"


def test_query_parameters_are_documented_names_only_when_given(monkeypatch):
    _arm_credentials(monkeypatch)
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_league_events("nfl", limit=10, offset=20, type_="futures", section="trending")
    url = calls[0]["url"]
    assert "limit=10" in url
    assert "offset=20" in url
    assert "type=futures" in url
    assert "section=trending" in url


def test_no_query_parameters_when_none_are_given(monkeypatch):
    _arm_credentials(monkeypatch)
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_league_events("nfl")
    assert "?" not in calls[0]["url"]


def test_the_api_base_override_is_honored(monkeypatch):
    _arm_credentials(monkeypatch)
    monkeypatch.setenv("POLYMARKET_US_API_BASE", "https://staging.polymarket.us")
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_league_events("nfl")
    assert calls[0]["url"].startswith("https://staging.polymarket.us/v2/leagues/nfl/events")


def test_a_slug_is_url_quoted(monkeypatch):
    _arm_credentials(monkeypatch)
    calls = _stub_signed_request(monkeypatch, {"events": []})
    mod.fetch_league_events("some slug")
    assert "some%20slug" in calls[0]["url"]


# --- credential / error handling --------------------------------------------


def test_no_credential_refuses_by_name_without_calling_signed_request(monkeypatch):
    calls = _stub_signed_request(monkeypatch, {"events": []})
    result = mod.fetch_league_events("nfl")
    assert result == {
        "status": "error",
        "reason": "credentials_absent",
        "url": "https://api.polymarket.us/v2/leagues/nfl/events",
    }
    assert calls == []


def test_an_auth_error_is_reported_by_name_not_raised(monkeypatch):
    from syndicate.features.shared.polymarket_us_auth import PolymarketUSAuthError

    _arm_credentials(monkeypatch)
    _stub_signed_request(monkeypatch, error=PolymarketUSAuthError("http_401: boom"))
    result = mod.fetch_league_events("nfl")
    assert result["status"] == "error"
    assert "http_401" in result["reason"]


def test_an_unexpected_exception_is_named_not_raised(monkeypatch):
    _arm_credentials(monkeypatch)
    _stub_signed_request(monkeypatch, error=ValueError("boom"))
    result = mod.fetch_league_events("nfl")
    assert result["status"] == "error"
    assert "ValueError" in result["reason"]


# --- probe / shape reporting -------------------------------------------------


def test_probe_league_reports_shape_from_an_events_list(monkeypatch):
    _arm_credentials(monkeypatch)
    _stub_signed_request(
        monkeypatch,
        {"events": [{"id": "e1", "title": "Team A @ Team B"}, {"id": "e2", "title": "Team C @ Team D"}]},
    )
    result = mod.probe_league("nfl", limit=3)
    assert result["status"] == "ok"
    assert result["payload_keys"] == ["events"]
    assert result["event_count"] == 2
    assert result["event_keys"] == ["id", "title"]
    assert result["sample"] == [{"id": "e1", "title": "Team A @ Team B"}]


def test_probe_league_reports_a_plain_list_payload_shape_too(monkeypatch):
    _arm_credentials(monkeypatch)
    _stub_signed_request(monkeypatch, [{"id": "e1"}])
    result = mod.probe_league("nfl")
    assert result["event_count"] == 1
    assert result["event_keys"] == ["id"]


def test_probe_league_passes_through_an_error_unshaped(monkeypatch):
    result = mod.probe_league("nfl")
    assert result["status"] == "error"
    assert result["reason"] == "credentials_absent"


def test_probe_all_leagues_covers_every_mapped_sport(monkeypatch):
    _arm_credentials(monkeypatch)
    _stub_signed_request(monkeypatch, {"events": []})
    result = mod.probe_all_leagues()
    assert set(result.keys()) == {"nfl", "nba", "mlb", "wnba", "nhl", "ncaaf", "ncaab"}
    assert all(v["status"] == "ok" for v in result.values())
