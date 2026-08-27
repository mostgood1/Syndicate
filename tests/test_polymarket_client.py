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

from unittest.mock import patch

from syndicate.features.shared import polymarket_client
from syndicate.features.shared.polymarket_client import (
    PolymarketError,
    decode_outcomes,
    fetch_markets,
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


# ---------------------------------------------------------------------------
# fetch_markets pagination.
#
# THE SERVER CAPS PAGE SIZE AND IGNORES A LARGER `limit`. Measured against the
# live API 2026-08-27: asked 100 -> 100 rows, asked 200 -> 100, asked 500 -> 100.
# The loop used to break on `len(page_rows) < limit` with a default limit of
# 200, so it stopped after ONE page every time and reported `truncated=False`
# -- a 100-row slice presented as the whole catalogue, on all ten
# live-odds-worker boots in 17h.
# ---------------------------------------------------------------------------


_SERVER_PAGE_CAP = 100


def _capped_server(total: int, cap: int = _SERVER_PAGE_CAP):
    """A Gamma stand-in that ignores `limit` and never returns more than `cap`.

    Records the offsets it was asked for, because the stride is half the bug.
    """
    seen_offsets: list[int] = []

    def _get(url: str):
        query = url.split("?", 1)[1]
        params = dict(part.split("=", 1) for part in query.split("&"))
        offset = int(params["offset"])
        seen_offsets.append(offset)
        rows = [{"id": str(i), "question": f"q{i}"} for i in range(offset, min(offset + cap, total))]
        return {"data": rows}

    return _get, seen_offsets


def test_a_short_page_is_not_the_end_of_the_catalogue():
    # The regression. Default limit is 200 and the server caps at 100, so every
    # page is "short" and the old code returned exactly one page.
    _get, _ = _capped_server(total=250)
    with patch.object(polymarket_client, "_get", _get):
        result = fetch_markets(active=True, closed=False)
    assert len(result["markets"]) == 250
    assert result["truncated"] is False


def test_offset_advances_by_rows_received_not_by_limit():
    """Fixing only the break condition would SKIP rows.

    `offset += limit` with limit=200 against a 100-row cap steps 0, 200, 400 and
    never reads rows 100-199 of each stride. The stride must be what came back.
    """
    _get, seen_offsets = _capped_server(total=250)
    with patch.object(polymarket_client, "_get", _get):
        result = fetch_markets(active=True, closed=False)
    assert seen_offsets == [0, 100, 200, 250]
    ids = [m.get("id") for m in result["markets"]]
    assert ids == [str(i) for i in range(250)]
    assert len(set(ids)) == 250


def test_max_pages_still_reports_truncated():
    # The hard stop must remain visible rather than looking like a full read.
    _get, _ = _capped_server(total=10_000)
    with patch.object(polymarket_client, "_get", _get):
        result = fetch_markets(active=True, closed=False, max_pages=3)
    assert result["truncated"] is True
    assert len(result["markets"]) == 300


def test_a_gamma_validation_error_is_named_not_flattened():
    """Gamma refuses with HTTP 200 and an `error` key.

    Measured 2026-08-27: offset 3000+ returns
    `{"type": "validation error", "error": "offset too large, use
    /markets/keyset for deeper pagination"}`. Without this branch it surfaced as
    `unexpected_shape: got dict`, which hides the one thing worth knowing --
    that deeper paging is a different ENDPOINT, not a bigger number.
    """
    def _get(url: str):
        return {"type": "validation error", "error": "offset too large, use /markets/keyset"}

    with patch.object(polymarket_client, "_get", _get):
        with pytest.raises(PolymarketError) as excinfo:
            fetch_markets(active=True, closed=False)
    assert "gamma_refused" in str(excinfo.value)
    assert "offset too large" in str(excinfo.value)
