"""NHL props backtest: an unquotable book price is dropped and COUNTED, not priced.

2026-10-03, lane nhl-props-converter-guard: `_implied` priced 0 as 0.0 and
`_american_to_dec` raised ZeroDivisionError at 0. Both now refuse 0 and |price| < 100,
and `score_book` drops such a line under `invalid_price_excluded` before matching.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backtest_nhl_props as bt  # noqa: E402


@pytest.mark.parametrize("price", [0, "0", 50, -99.9, None, "", "abc"])
def test_converters_refuse_unquotable_prices(price):
    assert bt._implied(price) is None
    assert bt._american_to_dec(price) is None


def test_converters_accept_wire_format_and_floats():
    assert bt._implied("+150") == pytest.approx(0.4)
    assert bt._american_to_dec(-110.5) == pytest.approx(1.9049773756)


@pytest.mark.parametrize("over, under", [("0", "-110"), ("-110", "50")])
def test_score_book_counts_an_invalid_price_instead_of_matching_it(over, under):
    line = {"over_price": over, "under_price": under, "line": "1.5", "market": "SOG",
            "player_name": "Andrew Copp", "home_team": "Detroit Red Wings", "away_team": "New York Rangers"}
    out = bt.score_book("arm", [{"date": "2026-10-01", "games": []}], {}, {"2026-10-01": [line]},
                        {}, lambda s: str(s or "").lower(), lambda s: str(s or "").lower(), 1)
    counts = out["filter_counts"]
    assert counts.get("invalid_price_excluded") == 1, counts
    assert "no_unique_player_match" not in counts, counts
