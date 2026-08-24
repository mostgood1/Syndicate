"""Novig's market data -- three tiers, one of them deliberately unimplemented.

Covers the pure conversion arithmetic, the normalization/refusal behaviour,
and `load_credentials`'s named-refusal contract. Network calls (tiers 1 and 2)
are not exercised here -- see `novig_client.py`'s header for why every host in
this lane is unreachable from this sandbox.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.novig_client import (
    load_credentials,
    normalize_market,
    probability_to_american,
)


@pytest.mark.parametrize("probability,expected", [(0.62, -163), (0.38, 163), (0.5, -100)])
def test_probability_converts_to_american_correctly(probability, expected):
    assert probability_to_american(probability) == expected


@pytest.mark.parametrize("probability", [0, 1, 1.5, -0.2, None])
def test_untradeable_probabilities_are_refused(probability):
    assert probability_to_american(probability) is None


def test_load_credentials_refuses_by_name_without_a_client_id(monkeypatch):
    monkeypatch.delenv("NOVIG_CLIENT_ID", raising=False)
    monkeypatch.delenv("NOVIG_CLIENT_SECRET", raising=False)
    result = load_credentials()
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_client_id"


def test_load_credentials_refuses_by_name_without_a_client_secret(monkeypatch):
    monkeypatch.setenv("NOVIG_CLIENT_ID", "abc")
    monkeypatch.delenv("NOVIG_CLIENT_SECRET", raising=False)
    result = load_credentials()
    assert result["status"] == "unavailable"
    assert result["reason"] == "no_client_secret"


def test_load_credentials_ok_with_both(monkeypatch):
    monkeypatch.setenv("NOVIG_CLIENT_ID", "abc")
    monkeypatch.setenv("NOVIG_CLIENT_SECRET", "def")
    result = load_credentials()
    assert result["status"] == "ok"
    assert result["client_id"] == "abc"


def test_normalize_market_reports_missing_fields_and_normalizes_outcomes():
    row = normalize_market(
        {
            "id": "evt-1",
            "league": "MLB",
            "type": "Game",
            "status": "OPEN_PREGAME",
            "outcomes": [
                {"type": "moneyline_home", "last": "0.62"},
                {"type": "moneyline_away", "last": "0.38"},
            ],
        }
    )
    assert row["league"] == "MLB"
    # Fields never supplied above must still be present and counted.
    assert "scheduled_start" in row["missing_fields"]
    assert len(row["outcomes"]) == 2
    assert row["outcomes"][0]["probability"] == pytest.approx(0.62)
    assert row["outcomes"][0]["american"] == -163


def test_normalize_market_reports_absent_outcomes_by_name():
    row = normalize_market({"id": "evt-1"})
    assert row["outcomes"] == []
    assert "outcomes" in row["missing_fields"]


def test_normalize_market_falls_back_to_available_when_last_is_absent():
    row = normalize_market({"outcomes": [{"type": "moneyline_home", "available": "0.55"}]})
    assert row["outcomes"][0]["probability"] == pytest.approx(0.55)
