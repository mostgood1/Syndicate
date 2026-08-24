"""Polymarket's own market data.

Field names were RESEARCHED, not called (see `polymarket_client.py`'s header),
so these tests cover the parts that do not depend on the endpoint being right:
price conversion (pure arithmetic) and the decode/refusal behaviour that keeps
a malformed or absent JSON-string field from looking like a market with no
outcomes.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared.polymarket_client import (
    decode_outcomes,
    normalize_market,
    outcome_price_to_american,
    probability_to_american,
)


@pytest.mark.parametrize("probability,expected", [(0.62, -163), (0.38, 163), (0.5, -100)])
def test_probability_converts_to_american_correctly(probability, expected):
    assert probability_to_american(probability) == expected


@pytest.mark.parametrize("probability", [0, 1, 1.5, -0.2, None])
def test_untradeable_probabilities_are_refused(probability):
    """0 and 1 are a resolved-or-impossible outcome, not a tradeable price."""
    assert probability_to_american(probability) is None


def test_outcome_price_to_american_reads_a_raw_string_field():
    """`outcomePrices[i]` arrives as a JSON-decoded string, e.g. '0.62'."""
    assert outcome_price_to_american("0.62") == -163
    assert outcome_price_to_american("not_a_number") is None


def test_decode_outcomes_zips_the_three_json_string_fields():
    raw = {
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "clobTokenIds": json.dumps(["111", "222"]),
    }
    result = decode_outcomes(raw)
    assert result["decode_error"] is None
    assert len(result["outcomes"]) == 2
    yes_row = result["outcomes"][0]
    assert yes_row["name"] == "Yes"
    assert yes_row["token_id"] == "111"
    assert yes_row["probability"] == pytest.approx(0.62)
    assert yes_row["american"] == -163


def test_decode_outcomes_reports_a_malformed_field_by_name_not_as_empty():
    """A malformed `outcomePrices` string must not read as 'no outcomes' --
    that is a different, much rarer fact than 'the string did not parse'."""
    raw = {
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": "{not valid json",
        "clobTokenIds": json.dumps(["111", "222"]),
    }
    result = decode_outcomes(raw)
    assert result["outcomes"] == []
    assert result["decode_error"] is not None
    assert "outcomePrices" in result["decode_error"]


def test_decode_outcomes_reports_absent_fields_by_name():
    result = decode_outcomes({})
    assert result["outcomes"] == []
    assert "outcomes: absent" in result["decode_error"]


def test_decode_outcomes_reports_a_length_mismatch():
    raw = {
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62"]),
        "clobTokenIds": json.dumps(["111", "222"]),
    }
    result = decode_outcomes(raw)
    assert result["outcomes"] == []
    assert "length_mismatch" in result["decode_error"]


def test_decode_outcomes_accepts_already_decoded_native_lists():
    """Not every caller necessarily hands this a raw Gamma row -- a value that
    is already a native list must not be treated as a decode failure."""
    raw = {"outcomes": ["Yes", "No"], "outcomePrices": ["0.62", "0.38"], "clobTokenIds": ["111", "222"]}
    result = decode_outcomes(raw)
    assert result["decode_error"] is None
    assert len(result["outcomes"]) == 2


def test_normalize_market_reports_missing_fields_and_decodes_outcomes():
    row = normalize_market(
        {
            "id": "123",
            "conditionId": "0xabc",
            "question": "Will it happen?",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["0.7", "0.3"]),
            "clobTokenIds": json.dumps(["1", "2"]),
            "active": True,
        }
    )
    assert row["question"] == "Will it happen?"
    assert row["decode_error"] is None
    assert row["outcomes"][0]["probability"] == pytest.approx(0.7)
    # Fields never supplied above must still be present and counted.
    assert "volume" in row["missing_fields"]
    assert row["closed"] is None
