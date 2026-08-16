"""A row whose EV is the book's own hold restated must not seat a shortlist slot.

Lane `recommendation-lane-correctness`, A3, from the 2026-08-14 model audit.

`book_margin_model` prices a ONE-SIDED market as `fair = implied x (1 - hold)`.
`expected_value_pct` is `fair/implied - 1`, so the price cancels and `ev_pct` is
identically `-hold` -- a fact about which book quoted, not about the bet.

Measured on the served shortlist 2026-08-14: all 100 soccer rows were exactly
this, every one with `books_quoting: 1`, all with a negative score. Predicting
`ev_pct` from `round(implied x (1-h), 4) / implied - 1` reproduced the served
value on 100 of 100 rows, 0 mismatches. Three distinct holds presented as
nineteen distinct `ev_pct` values purely through 4-dp rounding of `fair`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from syndicate.features.shared.layer2_board import (
    _row_ev_is_hold_restatement,
    select_shortlist,
)
from syndicate.features.shared.opportunity_signals import expected_value_pct


_NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


def _modelled_row(*, price: int, hold: float, market: str = "player_shots", **extra: object) -> dict:
    """A one-sided row priced exactly the way `book_margin_model` prices one."""
    implied = 100.0 / (price + 100.0) if price > 0 else abs(price) / (abs(price) + 100.0)
    fair = round(implied * (1.0 - hold / 100.0), 4)
    row = {
        "sport": "soccer",
        "market": market,
        "side": "yes",
        "event_id": f"evt-{price}-{market}",
        "commence_time": "2026-08-14T23:00:00Z",
        "ev_pct": expected_value_pct(price, fair),
        "model_edge_pct": None,
        "quote": {
            "price": price,
            "fair_probability": fair,
            "fair_method": "book_margin_model",
            "assumed_hold_pct": hold,
            "books_quoting": 1,
        },
        "score": {"score": -0.06, "value_pct": -hold},
    }
    row.update(extra)
    return row


def test_the_ev_really_is_the_hold_restated():
    """The premise, checked rather than asserted in prose."""
    for price in (150, 1700, 2200, 10000, -110):
        for hold in (6.514, 6.634, 7.501):
            row = _modelled_row(price=price, hold=hold)
            # Within the 4-dp rounding of `fair`, which is the whole residual.
            assert abs(row["ev_pct"] - (-hold)) < 0.6, (price, hold, row["ev_pct"])


def test_a_modelled_one_sided_row_with_no_model_is_uninformative():
    assert _row_ev_is_hold_restatement(_modelled_row(price=10000, hold=7.501)) is True


def test_a_modelled_row_that_carries_a_model_view_is_kept():
    # The distinction that makes the rule narrow: with a projection the row
    # ranks on the sim's disagreement, not on the book's margin.
    row = _modelled_row(price=10000, hold=7.501, model_edge_pct=3.2)
    assert _row_ev_is_hold_restatement(row) is False


def test_a_two_sided_consensus_row_is_never_touched():
    row = _modelled_row(price=150, hold=6.5)
    row["quote"]["fair_method"] = "consensus"
    assert _row_ev_is_hold_restatement(row) is False


def test_a_row_with_no_fair_method_is_never_touched():
    row = _modelled_row(price=150, hold=6.5)
    row["quote"].pop("fair_method")
    assert _row_ev_is_hold_restatement(row) is False


def test_select_shortlist_drops_them_and_counts_them():
    rows = [_modelled_row(price=2200, hold=6.514, market=f"player_shots_{i}") for i in range(5)]
    keeper = _modelled_row(price=2200, hold=6.514, market="player_assists", model_edge_pct=4.1)
    keeper["ev_pct"] = 2.5
    keeper["score"] = {"score": 2.5, "value_pct": 2.5}

    result = select_shortlist([*rows, keeper], now=_NOW)

    assert result["rows_uninformative_ev"] == 5
    kept_markets = {str(row.get("market")) for row in result["rows"]}
    assert kept_markets == {"player_assists"}


def test_the_counter_is_zero_when_nothing_is_dropped():
    # A counter that only ever appears when it fires is unreadable as "the rule
    # ran and rejected nothing" -- this module's own recurring lesson.
    keeper = _modelled_row(price=2200, hold=6.514, model_edge_pct=4.1)
    keeper["ev_pct"] = 2.5
    keeper["score"] = {"score": 2.5, "value_pct": 2.5}
    result = select_shortlist([keeper], now=_NOW)
    assert result["rows_uninformative_ev"] == 0
