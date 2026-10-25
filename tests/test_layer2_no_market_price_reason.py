"""Rows refused for having no market price are counted by WHY they have no fair (lane fair-price-v2, 2026-10-23).

The served board can never show `quote.fair_unresolved_reason`: the rows that carry it are exactly the rows
`select_shortlist` drops as `rows_no_market_price`. Measured 10-23: 0 of 4,757 served rows lacked a fair while the
counter read 1 (`ncaaf|spreads`). So the reason is counted where the row is refused.
"""
from __future__ import annotations

from syndicate.features.shared.layer2_board import select_shortlist


def _cand(i, reason=None, fair=None, sport="ncaaf", market="spreads"):
    quote = {"fair_probability": fair}
    if reason:
        quote["fair_unresolved_reason"] = reason
    return {"sport": sport, "kind": "game", "market": market, "event_id": f"e{i}", "score": {"score": 10 - i},
            "model_edge_pct": 12.0, "ev_pct": None if fair is None else 3.0, "quote": quote}


def test_refused_rows_are_counted_by_their_unresolved_reason():
    rows = [_cand(0, "two_sided_devig_refused"), _cand(1, "two_sided_devig_refused"), _cand(2, "no_two_sided_book"),
            _cand(3), _cand(4, fair=0.52)]                        # no reason stamped; and one row WITH a fair (kept)
    result = select_shortlist(rows)
    assert result["rows_no_market_price"] == 4
    assert result["rows_no_market_price_by_reason"] == {"no_two_sided_book": 1, "none": 1, "two_sided_devig_refused": 2}
    assert result["rows_no_market_price_by_family"] == {"ncaaf|spreads": 4}
    assert sum(result["rows_no_market_price_by_reason"].values()) == result["rows_no_market_price"]


def test_nothing_refused_reports_an_empty_reason_map():
    assert select_shortlist([_cand(0, fair=0.5)])["rows_no_market_price_by_reason"] == {}
