"""The venue balance gate.

MEASURED 2026-08-27: 7 live Kalshi orders died `http_400 insufficient_balance`
-- $1.09 to $3.39, 3 to 7 contracts. Not a sizing bug and not an empty account:
$32.46 sat in open positions against $53.89 free, so venue cash runs to the
floor and refills only as markets settle. The day caps are larger than the cash
behind them, so no cap could express it.

MOST OF THIS FILE IS ABOUT THE PERMISSIVE HALF. The gate deliberately ALLOWS
when the balance is unknown, which inverts the house rule about unknowns, and
the argument for that inversion is only sound while the refusal stays narrow.
So the tests that matter are the ones proving an absent, broken, stale or
unusable reading never becomes a refusal -- failing closed on a credential bug
would silently stop all live trading, which looks exactly like a quiet day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_guard as G


def _stamp(offset_seconds: float = 0.0) -> str:
    at = datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)
    return at.isoformat().replace("+00:00", "Z")


def _balances(dollars, *, status="ok", venue="kalshi", age=30.0):
    return {
        "recorded_at": _stamp(age),
        "recorded_by": "test",
        "venues": {venue: {"venue": venue, "status": status, "dollars": dollars}},
    }


@pytest.fixture
def stamped(monkeypatch):
    """Install a balance stamp and neutralise the ledger lookup."""

    def install(payload, *, committed=0.0):
        monkeypatch.setattr(
            "syndicate.features.shared.venue_balances.read_venue_balances",
            lambda: payload,
            raising=False,
        )
        monkeypatch.setattr(G, "_live_stake_since", lambda *a, **k: committed)

    return install


# ---------------------------------------------------------------------------
# The refusal itself
# ---------------------------------------------------------------------------


def test_a_stake_over_the_venue_balance_is_refused(stamped):
    stamped(_balances(2.00))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is True
    assert result["available"] == pytest.approx(2.00)


def test_a_stake_within_the_balance_is_known_and_allowed(stamped):
    stamped(_balances(53.89))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is True
    assert result["available"] == pytest.approx(53.89)


def test_orders_placed_since_the_reading_are_subtracted(stamped):
    """The in-tick overspend the gate exists to stop.

    The stamp is written once per tick, so without this every order in a tick
    measures itself against the same pre-tick cash and they all pass.
    """
    stamped(_balances(10.00), committed=8.50)
    result = G._venue_available_dollars("kalshi")
    assert result["available"] == pytest.approx(1.50)
    assert result["committed_since_reading"] == pytest.approx(8.50)


def test_available_never_goes_negative(stamped):
    stamped(_balances(5.00), committed=9.00)
    assert G._venue_available_dollars("kalshi")["available"] == 0.0


# ---------------------------------------------------------------------------
# The permissive half -- every absence must stay UNKNOWN, never a refusal
# ---------------------------------------------------------------------------


def test_no_stamp_at_all_is_unknown_not_broke(stamped):
    stamped(None)
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"] == "never_recorded"


def test_a_credential_failure_is_unknown_not_broke(stamped):
    stamped(_balances(None, status="auth_error"))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"] == "balance_auth_error"


def test_a_venue_missing_from_the_stamp_is_unknown(stamped):
    stamped(_balances(50.0, venue="polymarket"))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"] == "venue_absent_from_stamp"


def test_an_unusable_number_is_unknown(stamped):
    stamped(_balances("not-a-number"))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"] == "unusable_balance_value"


def test_a_stale_reading_is_unknown(stamped):
    stamped(_balances(50.0, age=G._BALANCE_MAX_AGE_SECONDS + 60))
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"] == "stale_reading"


def test_a_fresh_reading_at_the_boundary_is_still_known(stamped):
    stamped(_balances(50.0, age=G._BALANCE_MAX_AGE_SECONDS - 60))
    assert G._venue_available_dollars("kalshi")["known"] is True


def test_a_read_that_raises_is_unknown_not_a_crash(monkeypatch):
    """A balance gate that throws stops the tick that places orders."""

    def boom():
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(
        "syndicate.features.shared.venue_balances.read_venue_balances", boom, raising=False
    )
    result = G._venue_available_dollars("kalshi")
    assert result["known"] is False
    assert result["reason"].startswith("read_error:")


def test_every_absence_reason_is_distinct():
    """Distinct names, or two different problems share one silent branch."""
    reasons = {
        "no_venue_on_request",
        "never_recorded",
        "venue_absent_from_stamp",
        "balance_auth_error",
        "unusable_balance_value",
        "stale_reading",
        "unstamped_reading",
    }
    assert len(reasons) == 7


# ---------------------------------------------------------------------------
# The gate as `check_order` actually applies it
# ---------------------------------------------------------------------------
#
# The tests above cover the reading. These cover the DECISION, which is the
# part with money on it -- a correct reading wired to nothing refuses nothing.

from syndicate.features.shared.execution_ledger import OrderRequest  # noqa: E402


def _order(stake=3.00, venue="kalshi"):
    return OrderRequest(
        position_key="p1",
        selected_date="2026-08-27",
        venue=venue,
        sport="mlb",
        event_id="e1",
        market="totals",
        side="under",
        requested_price=-110.0,
        requested_stake_dollars=stake,
    )


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "SYNDICATE_EXECUTION_KILL_SWITCH",
        "SYNDICATE_EXECUTION_MODE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_check_order_refuses_a_live_order_it_cannot_fund(stamped):
    stamped(_balances(2.00))
    result = G.check_order(_order(stake=3.39), mode="live", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is False
    assert result["reason"] == "insufficient_venue_balance"
    # The refusal carries the numbers, so the board can say WHY rather than
    # just that something was blocked.
    assert result["balance"]["available"] == pytest.approx(2.00)
    assert result["stake"] == pytest.approx(3.39)


def test_check_order_allows_a_live_order_the_venue_can_fund(stamped):
    stamped(_balances(53.89))
    result = G.check_order(_order(stake=3.39), mode="live", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True


def test_a_stake_exactly_equal_to_the_balance_is_allowed(stamped):
    """`>` not `>=`. Spending the last dollar is legal."""
    stamped(_balances(3.39))
    result = G.check_order(_order(stake=3.39), mode="live", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True


def test_an_unknown_balance_ALLOWS_a_live_order(stamped):
    """The inverted-rule case, and the one most worth guarding.

    Failing closed on a broken credential would stop every live order with no
    error anywhere -- indistinguishable from a quiet slate. The venue's own 4xx
    is the authoritative check and costs one wasted request.
    """
    stamped(None)
    result = G.check_order(_order(stake=3.39), mode="live", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True
    assert result["reason"] is None


def test_a_broken_credential_ALLOWS_rather_than_halting_trading(stamped):
    stamped(_balances(None, status="auth_error"))
    result = G.check_order(_order(stake=3.39), mode="live", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True


def test_paper_orders_are_not_balance_gated(stamped):
    """Paper has no venue account, so there is no balance to be short of.

    Deliberately different from the CAPS, which do apply to paper -- a cap is a
    strategy statement worth rehearsing, while a balance is a fact about a real
    account that paper does not have.
    """
    stamped(_balances(0.01))
    result = G.check_order(_order(stake=3.39), mode="paper", already={"dollars": 0, "orders": 0})
    assert result["allowed"] is True


def test_the_balance_gate_does_not_fire_before_the_cap_checks(stamped):
    """An oversized order is still refused BY SIZE, not by balance.

    Reason strings drive the board copy, so the first true one has to win.
    """
    stamped(_balances(0.01))
    result = G.check_order(_order(stake=40.0), mode="live", already={"dollars": 0, "orders": 0})
    assert result["reason"] == "over_max_order_dollars"
