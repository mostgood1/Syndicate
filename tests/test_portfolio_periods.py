"""The day/month/year pivots over the live book."""

from __future__ import annotations

from syndicate.features.shared.portfolio_periods import (
    is_position,
    period_key,
    period_rollup,
)


def _order(**kw):
    row = {
        "mode": "live",
        "venue": "kalshi",
        "selected_date": "2026-08-25",
        "status": "filled",
        "fill_stake_dollars": 1.0,
    }
    row.update(kw)
    return row


def test_day_month_and_year_all_roll_the_same_orders():
    rows = [
        _order(selected_date="2026-08-25"),
        _order(selected_date="2026-08-26"),
        _order(selected_date="2026-07-04"),
        _order(selected_date="2025-12-31"),
    ]
    out = period_rollup(rows)
    assert [b["key"] for b in out["by_day"]] == ["2026-08-26", "2026-08-25", "2026-07-04", "2025-12-31"]
    assert [b["key"] for b in out["by_month"]] == ["2026-08", "2026-07", "2025-12"]
    assert [b["key"] for b in out["by_year"]] == ["2026", "2025"]
    # Every period covers the SAME orders -- a month that omits a day its own
    # day-view shows is two views disagreeing about one book.
    assert sum(b["orders"] for b in out["by_day"]) == 4
    assert sum(b["orders"] for b in out["by_month"]) == 4
    assert sum(b["orders"] for b in out["by_year"]) == 4


def test_the_pivot_is_the_slate_date_not_the_submit_stamp():
    """A 9pm Central order carries a NEXT-DAY UTC stamp. Keying on the stamp
    would split one evening's slate across two rows."""
    rows = [
        _order(selected_date="2026-08-25", submitted_at="2026-08-26T02:15:00Z"),
        _order(selected_date="2026-08-25", submitted_at="2026-08-25T18:00:00Z"),
    ]
    out = period_rollup(rows)
    assert len(out["by_day"]) == 1
    assert out["by_day"][0]["key"] == "2026-08-25"
    assert out["by_day"][0]["orders"] == 2


def test_refused_orders_are_not_counted():
    """[USER DECISION] they "also should not count against the number of
    orders" -- and the page hides exactly these."""
    rows = [
        _order(),
        _order(status="rejected", error="zero_kelly_stake"),
        _order(status="failed", error="KalshiAuthError: http_404: market_not_found"),
    ]
    out = period_rollup(rows)
    assert out["by_day"][0]["orders"] == 1
    assert out["counted_orders"] == 1


def test_a_timed_out_submit_still_counts():
    """THE IMPORTANT HALF. A submit that timed out may well have landed --
    counting a possible fill as nothing is the error that matters."""
    row = _order(status="failed", error="ReadTimeout: no response")
    assert is_position(row)
    assert period_rollup([row])["by_day"][0]["orders"] == 1


def test_open_positions_are_pending_not_settled_at_zero():
    """A filled bet with no graded outcome is money at risk right now. Folding
    it into settled-with-0-P&L makes an unresolved book look break-even."""
    out = period_rollup([_order(fill_stake_dollars=5.0)])
    day = out["by_day"][0]
    assert day["pending"] == 1
    assert day["settled"] == 0
    assert day["roi_pct"] is None
    assert day["staked_dollars"] == 5.0
    assert day["settled_stake_dollars"] == 0.0


def test_roi_is_none_on_nothing_graded_not_zero_percent():
    """0.0% on zero settled and 0.0% on fifty are the same string and opposite
    facts."""
    graded = period_rollup([_order(outcome="won", pnl_dollars=0.0, fill_stake_dollars=2.0)])
    assert graded["by_day"][0]["roi_pct"] == 0.0
    ungraded = period_rollup([_order()])
    assert ungraded["by_day"][0]["roi_pct"] is None


def test_settled_totals_and_rates():
    rows = [
        _order(outcome="won", pnl_dollars=1.5, fill_stake_dollars=2.0),
        _order(outcome="lost", pnl_dollars=-2.0, fill_stake_dollars=2.0),
        _order(outcome="won", pnl_dollars=1.0, fill_stake_dollars=2.0),
        _order(outcome="push", pnl_dollars=0.0, fill_stake_dollars=2.0),
    ]
    day = period_rollup(rows)["by_day"][0]
    assert (day["won"], day["lost"], day["push"]) == (2, 1, 1)
    assert day["settled"] == 4
    assert day["pnl_dollars"] == 0.5
    assert day["settled_stake_dollars"] == 8.0
    assert day["roi_pct"] == 6.25
    # Win% over DECIDED bets -- a push is not a loss.
    assert day["win_pct"] == round(100.0 * 2 / 3, 2)


def test_venue_split_within_a_period():
    rows = [
        _order(venue="kalshi", outcome="won", pnl_dollars=1.0, fill_stake_dollars=1.0),
        _order(venue="polymarket", outcome="lost", pnl_dollars=-2.0, fill_stake_dollars=2.0),
    ]
    day = period_rollup(rows)["by_day"][0]
    assert day["venues"]["kalshi"] == {"orders": 1, "staked_dollars": 1.0, "pnl_dollars": 1.0}
    assert day["venues"]["polymarket"] == {"orders": 1, "staked_dollars": 2.0, "pnl_dollars": -2.0}


def test_an_undated_order_is_reported_not_filed_under_a_guess():
    """A row in the wrong month is worse than a row visibly missing."""
    out = period_rollup([_order(), _order(selected_date=""), _order(selected_date="not-a-date")])
    assert out["undated"] == 2
    assert out["counted_orders"] == 1
    assert sum(b["orders"] for b in out["by_day"]) == 1
    # Dropped from EVERY period, so the views cannot disagree.
    assert sum(b["orders"] for b in out["by_month"]) == 1
    assert sum(b["orders"] for b in out["by_year"]) == 1


def test_period_key_shapes():
    row = _order(selected_date="2026-08-25")
    assert period_key(row, "day") == "2026-08-25"
    assert period_key(row, "month") == "2026-08"
    assert period_key(row, "year") == "2026"
    assert period_key(_order(selected_date="26-8"), "day") == ""


def test_empty_book_is_empty_not_an_error():
    out = period_rollup([])
    assert out == {
        "by_day": [], "by_month": [], "by_year": [],
        "counted_orders": 0, "undated": 0,
    }
