"""`unjoinable` split by WHEN the venue settled it.

The fleet started with none of Render's live orders, so every venue row is
unjoinable; the bare count cannot tell graded history from outcomes that landed
after Render stopped. These pin the split that answers it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import venue_settlement as vs

CUT = "2026-09-30T06:37:00Z"


def _k(ticker="KXNFLGAME-26SEP28-NE", when="2026-09-29T03:10:00Z", **over):
    row = {
        "ticker": ticker, "market_result": "yes", "yes_count_fp": "10.00", "no_count_fp": "0.00",
        "yes_total_cost_dollars": "5.4000", "no_total_cost_dollars": "0.0000", "revenue": 1000,
        "fee_cost": "0.3400", "settled_time": when,
    }
    row.update(over)
    return row


def _p(slug="asc-nfl-ne-cle-2026-10-01", when="2026-10-01T03:10:00.123456789Z", before=3.0, after=-6.6):
    return {
        "marketSlug": slug, "side": "POSITION_RESOLUTION_SIDE_LONG", "updateTime": when,
        "beforePosition": {"realized": {"value": str(before)}},
        "afterPosition": {"realized": {"value": str(after)}},
    }


def test_split_counts_sides_grades_only_after_and_keeps_undated_apart():
    split = vs.split_unjoinable(
        {
            "kalshi": [_k(), _k(when="2026-10-01T02:00:00Z"), _k(when="", ticker="X")],
            "polymarket": [_p(), _p(when="2026-09-01T00:00:00Z")],
        },
        split_at=CUT,
    )
    assert (split["before"], split["after"], split["undated"]) == (2, 2, 1)
    assert split["after_by_venue"] == {"kalshi": 1, "polymarket": 1}
    assert split["after_outcomes"] == {"won": 1, "lost": 1}
    assert split["after_pnl_dollars"] == pytest.approx(4.26 - 9.6, abs=0.01)
    # Polymarket's nanosecond stamp parses (fromisoformat alone refuses it).
    assert split["newest"] == "2026-10-01T03:10:00Z"


def test_env_override_moves_the_cutoff(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SETTLEMENT_SPLIT_AT", "2026-10-01T00:00:00Z")
    split = vs.split_unjoinable({"kalshi": [_k(when="2026-09-30T12:00:00Z")]})
    assert (split["at"], split["before"], split["after"]) == ("2026-10-01T00:00:00Z", 1, 0)


def test_settle_from_venue_reports_the_split_for_exactly_its_unjoinable_rows(monkeypatch):
    """Reachability: the counter is on the result the worker prints, and it
    covers the unjoinable rows only -- a row that JOINS is not in it."""
    import syndicate.features.shared.execution_ledger as led

    state = {"orders": [{
        "idempotency_key": "k1", "mode": "live", "venue": "kalshi", "venue_ticker": "KXJOINED",
        "status": "filled", "fill_stake_dollars": 5.40, "selected_date": "2026-10-01",
    }]}
    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.setattr(vs, "fetch_kalshi_settlements", lambda **kw: (
        [_k(ticker="KXJOINED", when="2026-10-01T05:00:00Z"), _k(), _k(when="2026-10-01T06:00:00Z", ticker="KXB")], None))
    monkeypatch.setattr(vs, "fetch_polymarket_resolutions", lambda **kw: ([_p()], None))
    monkeypatch.delenv("SYNDICATE_SETTLEMENT_SPLIT_AT", raising=False)

    result = vs.settle_from_venue(dry_run=True)
    split = result["unjoinable_split"]
    assert result["unjoinable"] == 3 and result["settled"] == 1
    assert split["at"] == vs.UNJOINABLE_SPLIT_DEFAULT
    assert split["before"] + split["after"] + split["undated"] == result["unjoinable"]
    assert (split["before"], split["after"]) == (1, 2)
