"""The venue grades a live order first; our inference is the fallback.

WHAT THIS FIXES, measured in production 2026-08-26T21:36Z.
`paper_settlement.settle_orders` runs from `intelligence_state.py` on
**refresh-worker**. `venue_settlement.settle_from_venue` runs on
**live-odds-worker**. Both skip an order that already carries an `outcome`, so
whichever service ticked first after a game ended owned that row permanently --
which grader won was decided by TIMING rather than by policy. On the first
reading the two disagreed sharply (venue 3 bets ROI -11.88%, inferred 12 bets
+51.07%), and while the race stood that comparison could never become
controlled.

The rule under test: a LIVE order is not graded by inference until the venue has
had a stated window. Paper is untouched, and an order the venue never settles
still reaches the ledger eventually rather than sitting open forever -- that is
why this is a delay and not a refusal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import paper_settlement as ps


def _stamp(hours_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    ).isoformat().replace("+00:00", "Z")


def _order(**over):
    order = {
        "idempotency_key": "k1",
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": "KX-TEST",
        "status": "filled",
        "selected_date": "2026-08-26",
        "submitted_at": _stamp(1),
        "fill_price": -110,
        "fill_stake_dollars": 5.0,
        "market": "player_points",
        "side": "Over",
        "line": 17.5,
    }
    order.update(over)
    return order


@pytest.fixture
def ledger(monkeypatch):
    state = {"orders": []}
    import syndicate.features.shared.execution_ledger as led

    monkeypatch.setattr(led, "_load", lambda: state)
    monkeypatch.setattr(led, "_persist", lambda s: None)
    monkeypatch.delenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", raising=False)
    return state


def _decided(order):
    """A resolver that always has an answer, so the ONLY thing that can stop a
    grade in these tests is the deferral under test."""
    return {"current_value": 25.0, "is_final": True, "started": True}


# ---------------------------------------------------------------------------
# off != on
# ---------------------------------------------------------------------------


def test_a_fresh_live_order_is_deferred_to_the_venue(ledger):
    ledger["orders"] = [_order(submitted_at=_stamp(1))]
    result = ps.settle_orders("2026-08-26", resolver=_decided)
    assert result["graded"] == 0
    assert result["ungraded"].get(ps.REASON_AWAITING_VENUE) == 1
    assert "outcome" not in ledger["orders"][0]


def test_the_same_order_past_the_window_is_graded_as_the_fallback(ledger):
    """A market the venue never settles must still reach the ledger. This is a
    delay, not a refusal -- otherwise a ticker we got wrong means a position
    that is never scored at all."""
    ledger["orders"] = [_order(submitted_at=_stamp(30))]
    result = ps.settle_orders("2026-08-26", resolver=_decided)
    assert result["graded"] == 1
    assert ledger["orders"][0]["outcome"] == "won"
    # And it is NOT marked authoritative -- only venue_settlement stamps that.
    assert ledger["orders"][0].get("settled_by") != "venue"


def test_a_paper_order_is_never_deferred(ledger):
    """Paper has no venue record to wait for, so delaying it buys nothing."""
    ledger["orders"] = [_order(mode="paper", submitted_at=_stamp(1))]
    result = ps.settle_orders("2026-08-26", resolver=_decided)
    assert result["graded"] == 1
    assert ledger["orders"][0]["outcome"] == "won"


def test_an_order_the_venue_already_settled_is_untouched(ledger):
    """The idempotency both graders share. A venue-settled row must never be
    re-graded by inference, whatever the window says."""
    ledger["orders"] = [
        _order(submitted_at=_stamp(99), outcome="lost", settled_by="venue", pnl_dollars=-5.0)
    ]
    result = ps.settle_orders("2026-08-26", resolver=_decided)
    assert result["graded"] == 0
    assert result["already_graded"] == 1
    assert ledger["orders"][0]["outcome"] == "lost"
    assert ledger["orders"][0]["pnl_dollars"] == -5.0


# ---------------------------------------------------------------------------
# The window itself
# ---------------------------------------------------------------------------


def test_the_window_is_configurable_without_a_deploy(ledger, monkeypatch):
    monkeypatch.setenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", "0.5")
    ledger["orders"] = [_order(submitted_at=_stamp(1))]
    assert ps.settle_orders("2026-08-26", resolver=_decided)["graded"] == 1


def test_zero_disables_the_deferral_deliberately(ledger, monkeypatch):
    """Zero is a real instruction -- "grade immediately, I accept the race" --
    and must not be read as an unset value."""
    monkeypatch.setenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", "0")
    ledger["orders"] = [_order(submitted_at=_stamp(0.1))]
    assert ps.settle_orders("2026-08-26", resolver=_decided)["graded"] == 1


def test_a_negative_window_falls_back_to_the_default(monkeypatch):
    """A negative would mean "never defer" -- a policy change dressed as a typo."""
    monkeypatch.setenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", "-5")
    assert ps._venue_grace_hours() == ps._DEFAULT_VENUE_GRACE_HOURS
    monkeypatch.setenv("SYNDICATE_VENUE_SETTLEMENT_GRACE_HOURS", "not-a-number")
    assert ps._venue_grace_hours() == ps._DEFAULT_VENUE_GRACE_HOURS


# ---------------------------------------------------------------------------
# Age, and the case where we cannot tell
# ---------------------------------------------------------------------------


def test_age_falls_back_to_the_slate_date_when_the_stamp_is_malformed(ledger):
    """Without this fallback one bad stamp means an order deferred forever,
    which is worse than grading it late."""
    order = _order(submitted_at="not-a-timestamp", selected_date="2026-01-01")
    age = ps._order_age_hours(order)
    assert age is not None and age > 24


def test_the_slate_date_ages_from_the_END_of_the_day(ledger):
    """A night game on that date has not finished at 00:00. Ageing from
    midnight would hand the fallback a head start it has not earned."""
    today = datetime.now(timezone.utc).date().isoformat()
    age = ps._order_age_hours({"selected_date": today})
    assert age is not None and age < 0


def test_an_order_with_no_readable_age_is_deferred_under_its_OWN_reason(ledger):
    """"The venue has not settled it" and "we cannot tell how old it is" both
    end in an ungraded row and only one is a bug. A shared reason string would
    make them the same line in the counter."""
    ledger["orders"] = [_order(submitted_at="", selected_date="2026-08-26")]
    # `selected_date` still carries the date `settle_orders` filters on, so the
    # only way to lose the age entirely is to lose both.
    ledger["orders"][0]["selected_date"] = "2026-08-26"
    ledger["orders"][0]["submitted_at"] = "garbage"
    result = ps.settle_orders("2026-08-26", resolver=_decided)
    # This one IS gradeable via the slate-date fallback, so it must not be
    # counted as unknown-age.
    assert result["ungraded"].get(ps.REASON_AWAITING_VENUE_NO_AGE) is None


def test_both_stamps_unreadable_defers_and_names_it(monkeypatch):
    order = {"mode": "live", "status": "filled", "selected_date": "nope", "submitted_at": "nope"}
    assert ps._order_age_hours(order) is None
