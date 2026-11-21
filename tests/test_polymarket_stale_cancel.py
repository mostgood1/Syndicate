"""The Polymarket stale cancel (lane polymarket-stale-cancel, 2026-11-21).

11-21: a Polymarket taker order rested untouched from 12:50Z to its 01:10Z tip-off expiry, holding its key, because
the only stale cancel is Kalshi-only and runs at worker boot. This pass runs off the executor's per-tick Polymarket
reconcile. Reachability first: absent is OFF, shadow never writes, on cancels once.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import polymarket_stale_cancel as S
from syndicate.features.shared import polymarket_us_orders as P

_NOW = datetime(2026, 11, 21, 15, 30, tzinfo=timezone.utc)
_SUBMITTED = "2026-11-21T12:50:14Z"  # 160 min before _NOW
_SLUG = "asc-nba-no-sa-2026-11-21-pos-15pt5"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for key in (S.ENV, S.MAX_AGE_ENV, S.BAND_ENV, S.MAX_CANCELS_ENV, "SYNDICATE_EXECUTION_ENABLED",
                "SYNDICATE_EXECUTION_MODE", "SYNDICATE_EXECUTION_LIVE_ARMED", "SYNDICATE_EXECUTION_VENUE",
                "SYNDICATE_REFRESH_STATE_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(S, "_CANCELLED", set())
    yield


def _resting(**overrides):
    row = {"idempotency_key": "ac07e83ec3661c9904436047", "order_id": "DVVZCPGG144P", "ticker": _SLUG,
           "side": "home", "submitted_at": _SUBMITTED, "execution_style": None}
    row.update(overrides)
    return row


def _venue_order(**overrides):
    # The real 11-21 order as the venue reads it: NO at a wire (YES) price of 0.44, i.e. a cost of 0.56.
    order = {"id": "DVVZCPGG144P", "marketSlug": _SLUG, "state": "ORDER_STATE_NEW", "outcomeSide": P._SIDE_NO,
             "price": {"value": "0.44", "currency": "USD"}, "cumQuantity": 0, "leavesQuantity": 1.05,
             "clientOrderId": "ac07e83ec3661c9904436047"}
    order.update(overrides)
    return order


def _book(best_bid=0.40, best_offer=0.45):
    return {"marketData": {"bids": [{"px": {"value": str(best_bid)}, "qty": "50"}] if best_bid is not None else [],
                           "offers": [{"px": {"value": str(best_offer)}, "qty": "50"}] if best_offer is not None else []}}


@pytest.fixture
def venue(monkeypatch):
    """The venue: an order read, a book read and a recording cancel. Reads count, so 'no read' is testable."""
    state = {"order": _venue_order(), "book": _book(), "reads": 0, "book_reads": 0, "cancels": [], "status": None}

    def read_order(order_id):
        state["reads"] += 1
        return state["order"]

    def read_book(slug):
        state["book_reads"] += 1
        if isinstance(state["book"], Exception):
            raise state["book"]
        return state["book"]

    def cancel(order_id, *, execute=False, expect_client_order_id=None, expect_market_slug=None):
        state["cancels"].append({"order_id": order_id, "execute": execute, "client": expect_client_order_id,
                                 "slug": expect_market_slug})
        return {"status": state["status"] or ("sent" if execute else "dry_run")}

    monkeypatch.setattr(S, "_read_order", read_order)
    monkeypatch.setattr(P, "_read_book", read_book)
    monkeypatch.setattr(P, "cancel_order", cancel)
    return state


# --------------------------------------------------------------------------- reachability: absent is OFF, off != on


@pytest.mark.parametrize("raw", [None, "", "off", "0", "false", "no", "maybe", "SHADOWS"])
def test_absent_blank_or_unknown_is_off_and_touches_nothing(monkeypatch, venue, raw):
    if raw is not None:
        monkeypatch.setenv(S.ENV, raw)
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["reason"] == "disabled" and result["mode"] == "off"
    assert venue["reads"] == venue["book_reads"] == 0 and venue["cancels"] == []


def test_on_cancels_the_11_21_order_once_naming_its_own_client_id_and_slug(monkeypatch, venue, capsys):
    monkeypatch.setenv(S.ENV, "on")
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["cancelled"] == 1 and result["would_cancel"] == 0
    assert venue["cancels"] == [{"order_id": "DVVZCPGG144P", "execute": True,
                                 "client": "ac07e83ec3661c9904436047", "slug": _SLUG}]
    out = capsys.readouterr().out
    assert "CANCEL_STALE key=ac07e83ec3661c9904436047" in out and "cost=0.56" in out and "ask=0.6" in out


def test_shadow_decides_the_same_but_never_writes(monkeypatch, venue, capsys):
    monkeypatch.setenv(S.ENV, "shadow")
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["would_cancel"] == 1 and result["cancelled"] == 0
    assert [c["execute"] for c in venue["cancels"]] == [False]
    assert "WOULD_CANCEL" in capsys.readouterr().out
    # Shadow remembers nothing: the next pass decides again from the venue.
    S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert len(venue["cancels"]) == 2


def test_the_executor_tick_reaches_the_pass_in_the_polymarket_scope_only(monkeypatch):
    """off != on through `run_execution` itself: the Polymarket reconcile's resting rows reach the pass, the
    Kalshi-scope run (which also reconciles Polymarket) does not repeat it."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger as L

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "polymarket")
    resting = [_resting()]
    monkeypatch.setattr(L, "reconcile_live_orders",
                        lambda venue="kalshi", **_: {"status": "ok", "resting": resting if venue == "polymarket" else []})
    handed: list = []
    monkeypatch.setattr(S, "cancel_stale_polymarket_resting", lambda rows, **_: handed.append(list(rows)) or {})
    runner.run_execution("2026-11-21", venue_scope="polymarket")
    assert handed == [resting]
    handed.clear()
    runner.run_execution("2026-11-21", venue_scope="kalshi")
    assert handed == []


def test_a_failing_pass_does_not_break_the_executor(monkeypatch, capsys):
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger as L

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setattr(L, "reconcile_live_orders", lambda venue="kalshi", **_: {"status": "ok", "resting": [_resting()]})

    def boom(rows, **_):
        raise RuntimeError("venue down")

    monkeypatch.setattr(S, "cancel_stale_polymarket_resting", boom)
    runner.run_execution("2026-11-21", venue_scope="polymarket")  # must not raise
    assert "POLYMARKET_STALE_CANCEL_FAILED RuntimeError: venue down" in capsys.readouterr().out


# --------------------------------------------------------------------------- the price, on OUR side's scale


def test_a_no_order_costs_one_minus_its_wire_price_and_its_ask_is_one_minus_the_best_bid():
    assert S.our_cost(_venue_order()) == pytest.approx(0.56)
    assert S.ask_for_side(_book(best_bid=0.40), P._SIDE_NO) == pytest.approx(0.60)
    assert S.our_cost(_venue_order(outcomeSide=P._SIDE_YES, price={"value": "0.55"})) == pytest.approx(0.55)
    assert S.ask_for_side(_book(best_offer=0.58), P._SIDE_YES) == pytest.approx(0.58)


@pytest.mark.parametrize("best_bid,cancelled", [(0.40, 1), (0.43, 1), (0.435, 0), (0.44, 0), (0.46, 0)])
def test_a_no_order_is_cancelled_only_when_the_book_has_left_it_by_the_band(monkeypatch, venue, best_bid, cancelled):
    # cost 0.56; NO ask = 1 - bid: 0.60 / 0.57 leave it (>= 0.01), 0.565 / 0.56 / 0.54 do not.
    monkeypatch.setenv(S.ENV, "on")
    venue["book"] = _book(best_bid=best_bid)
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["cancelled"] == cancelled
    assert result["at_market"] == 1 - cancelled


def test_a_yes_order_reads_the_offers(monkeypatch, venue):
    monkeypatch.setenv(S.ENV, "on")
    venue["order"] = _venue_order(outcomeSide=P._SIDE_YES, price={"value": "0.55"})
    venue["book"] = _book(best_bid=0.99, best_offer=0.555)  # a bid that would mislead a NO-style read
    assert S.cancel_stale_polymarket_resting([_resting()], now=_NOW)["cancelled"] == 0
    venue["book"] = _book(best_bid=0.99, best_offer=0.58)
    assert S.cancel_stale_polymarket_resting([_resting()], now=_NOW)["cancelled"] == 1


@pytest.mark.parametrize("book", [RuntimeError("no_polymarket_us_credentials"), {}, _book(best_bid=None)])
def test_no_price_no_cancel(monkeypatch, venue, book):
    monkeypatch.setenv(S.ENV, "on")
    venue["book"] = book
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["cancelled"] == 0 and result["unreadable"] == 1 and venue["cancels"] == []


# --------------------------------------------------------------------------- which orders are left alone


def test_an_order_younger_than_the_max_age_is_not_even_read(monkeypatch, venue):
    monkeypatch.setenv(S.ENV, "on")
    result = S.cancel_stale_polymarket_resting([_resting(submitted_at="2026-11-21T15:20:00Z")], now=_NOW)
    assert result["too_young"] == 1 and venue["reads"] == 0
    monkeypatch.setenv(S.MAX_AGE_ENV, "300")
    assert S.cancel_stale_polymarket_resting([_resting(submitted_at="2026-11-21T15:20:00Z")], now=_NOW)["cancelled"] == 1


@pytest.mark.parametrize("style", ["maker_pilot", "maker"])
def test_a_non_taker_order_rests_on_purpose_and_is_left_alone(monkeypatch, venue, style):
    monkeypatch.setenv(S.ENV, "on")
    result = S.cancel_stale_polymarket_resting([_resting(execution_style=style)], now=_NOW)
    assert result["not_taker"] == 1 and venue["reads"] == 0


@pytest.mark.parametrize("order", [
    _venue_order(cumQuantity=0.4, leavesQuantity=0.65),  # partly filled: a position as well as an order
    _venue_order(state="ORDER_STATE_FILLED", cumQuantity=1.05, leavesQuantity=0),
    _venue_order(state="ORDER_STATE_CANCELED"),
    _venue_order(state="ORDER_STATE_EXPIRED"),
    _venue_order(cumQuantity=None),  # unreadable fill quantity
])
def test_anything_but_an_untouched_working_order_is_left_alone(monkeypatch, venue, order):
    monkeypatch.setenv(S.ENV, "on")
    venue["order"] = order
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["touched"] == 1 and venue["cancels"] == []


@pytest.mark.parametrize("row", [_resting(order_id=None), _resting(ticker=None), _resting(idempotency_key=None),
                                 _resting(submitted_at=None), _resting(submitted_at="not-a-time")])
def test_a_row_missing_what_the_cancel_must_name_is_left_alone(monkeypatch, venue, row):
    monkeypatch.setenv(S.ENV, "on")
    assert S.cancel_stale_polymarket_resting([row], now=_NOW)["cancelled"] == 0
    assert venue["cancels"] == []


def test_an_unreadable_order_is_not_permission_to_write(monkeypatch, venue):
    monkeypatch.setenv(S.ENV, "on")
    venue["order"] = None
    result = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert result["unreadable"] == 1 and venue["cancels"] == []


# --------------------------------------------------------------------------- once, bounded, and failures change nothing


def test_one_cancel_per_order_while_the_reconcile_still_reads_it_resting(monkeypatch, venue):
    monkeypatch.setenv(S.ENV, "on")
    S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    second = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert len(venue["cancels"]) == 1 and second["already"] == 1


@pytest.mark.parametrize("status", ["refused", "error", "skipped"])
def test_a_cancel_the_venue_did_not_accept_is_counted_and_retried_next_pass(monkeypatch, venue, status, capsys):
    monkeypatch.setenv(S.ENV, "on")
    venue["status"] = status
    first = S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    S.cancel_stale_polymarket_resting([_resting()], now=_NOW)
    assert first["cancelled"] == 0 and first["failed"] == 1
    assert len(venue["cancels"]) == 2
    assert "CANCEL_NOT_DONE" in capsys.readouterr().out


def test_bounded_per_pass(monkeypatch, venue):
    monkeypatch.setenv(S.ENV, "on")
    monkeypatch.setenv(S.MAX_CANCELS_ENV, "2")
    rows = [_resting(idempotency_key=f"k-{i}", order_id=f"o-{i}") for i in range(5)]
    result = S.cancel_stale_polymarket_resting(rows, now=_NOW)
    assert [c["order_id"] for c in venue["cancels"]] == ["o-0", "o-1"] and result["cancelled"] == 2


def test_nothing_due_prints_nothing(monkeypatch, venue, capsys):
    monkeypatch.setenv(S.ENV, "on")
    S.cancel_stale_polymarket_resting([_resting(submitted_at="2026-11-21T15:25:00Z")], now=_NOW)
    assert capsys.readouterr().out == ""


def test_the_reconcile_resting_row_carries_what_this_pass_reads():
    import inspect

    from syndicate.features.shared import execution_ledger as L

    source = inspect.getsource(L.reconcile_live_orders)
    for field in ('"order_id": seen.get("order_id")', '"submitted_at": order.get("submitted_at")',
                  '"execution_style": order.get("execution_style")', '"idempotency_key": key'):
        assert field in source, field
