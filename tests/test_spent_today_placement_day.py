"""A live order is charged to the day it was PLACED, not its slate (todo #707, D2).

Live bets games up to six days out. A day's cap has to mean money that left the
account that day. Today the executor places only today's slate, so this is a
no-op on the live ledger; T2 shows the switch is reachable (off != on) on the one
row shape where it matters, a row whose slate is not its placement day.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_guard as G
from syndicate.features.shared import execution_ledger as L


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv("SYNDICATE_EXECUTION_PLACEMENT_DAY_BUDGET", raising=False)
    yield


def _row(**overrides):
    row = {
        "mode": "live",
        "venue": "kalshi",
        "status": "filled",
        "selected_date": "2026-10-23",  # Friday's slate...
        "submitted_at": "2026-10-22T15:00:00Z",  # ...placed Thursday (10:00 AM CT)
        "requested_stake_dollars": 10.0,
        "fill_stake_dollars": 10.0,
        "fees_dollars": 0.5,
        "error": None,
    }
    row.update(overrides)
    return row


def _seed(monkeypatch, *rows):
    monkeypatch.setattr(L, "_load", lambda: {"orders": [dict(r) for r in rows]})


# --------------------------------------------------------------------------
# T2 -- reachability: off != on
# --------------------------------------------------------------------------


def test_T2_off_the_order_is_charged_to_its_slate(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_PLACEMENT_DAY_BUDGET", "off")
    _seed(monkeypatch, _row())
    assert G.spent_today("2026-10-22", venue="kalshi", mode="live") == {"dollars": 0.0, "orders": 0}
    assert G.spent_today("2026-10-23", venue="kalshi", mode="live") == {"dollars": 10.5, "orders": 1}


def test_T2_on_the_order_is_charged_to_the_day_it_was_placed(monkeypatch):
    _seed(monkeypatch, _row())
    assert G.spent_today("2026-10-22", venue="kalshi", mode="live") == {"dollars": 10.5, "orders": 1}
    assert G.spent_today("2026-10-23", venue="kalshi", mode="live") == {"dollars": 0.0, "orders": 0}


# --------------------------------------------------------------------------
# The no-op claim, and what stays as it was
# --------------------------------------------------------------------------


def test_a_row_placed_on_its_own_slate_reads_the_same_either_way(monkeypatch):
    # Every live row the executor writes today has this shape.
    row = _row(selected_date="2026-10-22", submitted_at="2026-10-22T15:00:00Z")
    _seed(monkeypatch, row)
    on = G.spent_today("2026-10-22", venue="kalshi", mode="live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_PLACEMENT_DAY_BUDGET", "off")
    off = G.spent_today("2026-10-22", venue="kalshi", mode="live")
    assert on == off == {"dollars": 10.5, "orders": 1}


def test_central_day_not_utc_day(monkeypatch):
    # 03:00Z on the 23rd is 10 PM CT on the 22nd: charged to the 22nd.
    _seed(monkeypatch, _row(submitted_at="2026-10-23T03:00:00Z"))
    assert G.spent_today("2026-10-22", venue="kalshi", mode="live")["orders"] == 1


@pytest.mark.parametrize("stamp", [None, "", "not-a-time"])
def test_an_unreadable_stamp_falls_back_to_the_slate(monkeypatch, stamp):
    _seed(monkeypatch, _row(submitted_at=stamp))
    assert G.spent_today("2026-10-23", venue="kalshi", mode="live")["orders"] == 1


def test_paper_keeps_its_slate_key(monkeypatch):
    # Paper places next-day slates today; its caps must not move.
    _seed(monkeypatch, _row(mode="paper", venue="paper:kalshi"))
    assert G.spent_today("2026-10-23", venue="paper:kalshi", mode="paper")["orders"] == 1
    assert G.spent_today("2026-10-22", venue="paper:kalshi", mode="paper")["orders"] == 0


def test_check_order_reaches_the_placement_day_budget(monkeypatch):
    """The guard, not just the counter. $95 placed Thursday on Friday's slate; a
    $10 order on Thursday's slate against a $100 day cap. On: refused, because
    Thursday already spent $95. Off: allowed, because Thursday's SLATE spent $0."""
    _seed(monkeypatch, _row(fill_stake_dollars=95.0, requested_stake_dollars=95.0, fees_dollars=0.0))
    monkeypatch.setattr(
        G, "limits",
        lambda mode=None, venue=None: {
            "max_order_dollars": 100.0, "max_day_dollars": 100.0, "max_day_orders": 50,
            "max_day_dollars_all_venues": 1000.0, "max_day_orders_all_venues": 50,
        },
    )
    monkeypatch.setattr(G, "balance_caps_refusal", lambda caps, venue: None)
    monkeypatch.setattr(G, "_venue_available_dollars", lambda venue: {"known": False})
    monkeypatch.setattr(G, "_shard_available_dollars", lambda request: {"known": False, "reason": "gate_off"})
    monkeypatch.setattr(G, "kill_switch_engaged", lambda: {"engaged": False})

    class _Req:
        venue = "kalshi"
        venue_ticker = "KX-TEST"
        requested_stake_dollars = 10.0
        selected_date = "2026-10-22"

    on = G.check_order(_Req(), mode="live")
    assert on["allowed"] is False and on["reason"] == "over_max_day_dollars"
    monkeypatch.setenv("SYNDICATE_EXECUTION_PLACEMENT_DAY_BUDGET", "off")
    off = G.check_order(_Req(), mode="live")
    assert off["allowed"] is True


def test_a_tick_that_straddles_midnight_charges_the_new_day(monkeypatch):
    # The executor reads `central_today_iso()` and stamps `submitted_at` seconds
    # later; a pass crossing midnight CT books slate D at 00:00:01 on D+1. On: the
    # money left the account on D+1, so D+1's budget pays. (Measured 2026-10-20 on
    # the fleet ledger: 33 of 554 live rows, all 08-06..09-27 under an older
    # executor, were placed 00:00-02:00 CT on the day after their slate.)
    _seed(monkeypatch, _row(selected_date="2026-10-22", submitted_at="2026-10-23T05:00:01Z"))
    assert G.spent_today("2026-10-23", venue="kalshi", mode="live")["orders"] == 1
    assert G.spent_today("2026-10-22", venue="kalshi", mode="live")["orders"] == 0
