"""ProphetX's Affiliate API -- partner-gated, so the credential-refusal path
is as important to test as the arithmetic.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.prophetx_client import (
    api_token,
    american_to_probability,
    fetch_markets,
    normalize_market,
    normalize_selection,
    probe,
)


@pytest.mark.parametrize("odds,expected", [(119, pytest.approx(0.4566, abs=1e-3)), (-122, pytest.approx(0.5495, abs=1e-3))])
def test_american_odds_convert_to_probability(odds, expected):
    assert american_to_probability(odds) == expected


@pytest.mark.parametrize("odds", [0, None, "abc"])
def test_invalid_odds_are_refused(odds):
    assert american_to_probability(odds) is None


def test_api_token_is_absent_by_default(monkeypatch):
    monkeypatch.delenv("PROPHETX_API_TOKEN", raising=False)
    assert api_token() is None


def test_api_token_reads_the_env_var(monkeypatch):
    monkeypatch.setenv("PROPHETX_API_TOKEN", "shhh")
    assert api_token() == "shhh"


def test_fetch_markets_refuses_by_name_without_a_token(monkeypatch):
    monkeypatch.delenv("PROPHETX_API_TOKEN", raising=False)
    result = fetch_markets()
    assert result == {"status": "unavailable", "reason": "no_api_token"}


def test_probe_refuses_by_name_without_a_token(monkeypatch):
    monkeypatch.delenv("PROPHETX_API_TOKEN", raising=False)
    result = probe()
    assert result == {"status": "credential_unavailable", "reason": "no_api_token"}


def test_normalize_selection_reports_missing_fields_and_probability():
    row = normalize_selection({"outcome_id": 1, "name": "Yankees", "odds": 119})
    assert row["name"] == "Yankees"
    assert row["probability"] == pytest.approx(0.4566, abs=1e-3)
    assert "line_id" in row["missing_fields"]


def test_normalize_market_decodes_nested_selections():
    row = normalize_market(
        {
            "event_id": "evt-1",
            "selections": [
                {"outcome_id": 1, "name": "Yankees", "odds": 119},
                {"outcome_id": 2, "name": "Red Sox", "odds": -140},
            ],
        }
    )
    assert row["selections_present"] is True
    assert len(row["selections"]) == 2
    assert row["selections"][0]["probability"] == pytest.approx(0.4566, abs=1e-3)


def test_normalize_market_reports_absent_selections_honestly():
    row = normalize_market({"event_id": "evt-1"})
    assert row["selections"] == []
    assert row["selections_present"] is False
