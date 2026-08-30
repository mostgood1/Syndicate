"""`cancel_order`: the capability that did not exist when it was needed.

Measured 2026-08-30: a restated `commence_time` minted a second `position_key`
for a bet already placed, and ~$9.12 rested at Polymarket as two legs where one
was intended. **There was no cancel path at all**, so retiring the surplus leg
required a human on the venue's own Orders screen. A second duplicate pair had
already FILLED before anyone looked.

Every test here monkeypatches the venue. Nothing in this file contacts
Polymarket, and the module must not either unless `execute=True`.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import polymarket_us_orders as mod

RESTING = {
    "id": "C6HN0XD92KDE",
    "status": "ORDER_STATUS_OPEN",
    "clientOrderId": "0f0e2a675e86ed5589a9d913",
    "marketSlug": "tsc-mlb-lad-det-2026-08-30-7pt5",
    "cumQuantity": 0,
    "quantity": 5.44,
}


def _venue(monkeypatch, order=RESTING, *, sends: list | None = None, fail_read=False):
    """Stand in for the signed venue client, recording any WRITE it is asked
    to make so a test can assert the module stayed read-only."""
    import syndicate.features.shared.polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: True)

    def signed_request(method, url, **kw):
        if method == "GET":
            if fail_read:
                raise RuntimeError("http_503")
            return dict(order)
        if sends is not None:
            sends.append((method, url))
        return {"ok": True}

    monkeypatch.setattr(auth, "signed_request", signed_request)
    return sends


def test_the_DEFAULT_is_a_dry_run_and_sends_NOTHING(monkeypatch):
    """Safe by default. A cancel adapter whose default action is to cancel is
    one keystroke from retiring the wrong leg."""
    sends: list = []
    _venue(monkeypatch, sends=sends)

    out = mod.cancel_order("C6HN0XD92KDE")

    assert out["status"] == "dry_run"
    assert sends == [], "a dry run contacted the venue with a write"
    # And it still reports what it WOULD do, or the dry run is useless.
    assert out["method"] == "DELETE"
    assert out["url"].endswith("/v1/order/C6HN0XD92KDE")
    assert out["client_order_id"] == "0f0e2a675e86ed5589a9d913"


def test_execute_TRUE_actually_sends_the_cancel(monkeypatch):
    """off != on. A guard that never fires and an adapter that never sends are
    the same defect, and this repo shipped three inert guards today."""
    sends: list = []
    _venue(monkeypatch, sends=sends)

    out = mod.cancel_order("C6HN0XD92KDE", execute=True)

    assert out["status"] == "sent"
    assert len(sends) == 1
    method, url = sends[0]
    assert method == "DELETE"
    assert url.endswith("/v1/order/C6HN0XD92KDE")


def test_a_FILLED_order_is_REFUSED(monkeypatch):
    """The money already moved. Cancelling is meaningless and the request would
    be a write against a settled position -- refuse rather than find out."""
    sends: list = []
    _venue(monkeypatch, dict(RESTING, status="ORDER_STATUS_FILLED", cumQuantity=5.44), sends=sends)

    out = mod.cancel_order("C6HN0XD92KDE", execute=True)

    assert out["status"] == "refused"
    assert "not_cancellable" in out["reason"]
    assert sends == [], "a filled order was sent a cancel"


@pytest.mark.parametrize("status", ["ORDER_STATUS_CANCELED", "ORDER_STATUS_EXPIRED",
                                    "ORDER_STATUS_REJECTED"])
def test_other_terminal_states_are_refused_too(monkeypatch, status):
    """Prefixed enums, matched as substrings -- this venue returns
    `ORDER_STATUS_CANCELED`, never `canceled`."""
    sends: list = []
    _venue(monkeypatch, dict(RESTING, status=status), sends=sends)
    assert mod.cancel_order("C6HN0XD92KDE", execute=True)["status"] == "refused"
    assert sends == []


def test_a_CLIENT_ORDER_ID_MISMATCH_refuses_the_write(monkeypatch):
    """THE WRONG-LEG GUARD, and the reason this function reads before it writes.

    A duplicate pair is two orders on the same market, side and line, differing
    only in id and stake. Cancelling the wrong one keeps the unintended bet AND
    destroys the intended one -- strictly worse than doing nothing. An id copied
    from a log or a screenshot is exactly the input that lands on the wrong row.
    """
    sends: list = []
    _venue(monkeypatch, sends=sends)

    out = mod.cancel_order(
        "C6HN0XD92KDE", execute=True, expect_client_order_id="THE-OTHER-LEG"
    )

    assert out["status"] == "refused"
    assert "client_order_id_mismatch" in out["reason"]
    assert sends == [], "a mismatched expectation still sent the cancel"


def test_a_MARKET_SLUG_MISMATCH_refuses_the_write(monkeypatch):
    sends: list = []
    _venue(monkeypatch, sends=sends)

    out = mod.cancel_order(
        "C6HN0XD92KDE", execute=True, expect_market_slug="tsc-mlb-hou-nyy-2026-08-26"
    )

    assert out["status"] == "refused"
    assert "market_slug_mismatch" in out["reason"]
    assert sends == []


def test_MATCHING_expectations_do_not_block_a_real_cancel(monkeypatch):
    """The guards must not refuse the correct call, or an operator learns to
    stop passing them -- which removes the protection entirely."""
    sends: list = []
    _venue(monkeypatch, sends=sends)

    out = mod.cancel_order(
        "C6HN0XD92KDE",
        execute=True,
        expect_client_order_id="0f0e2a675e86ed5589a9d913",
        expect_market_slug="tsc-mlb-lad-det-2026-08-30-7pt5",
    )

    assert out["status"] == "sent"
    assert len(sends) == 1


def test_a_FAILED_READ_is_NOT_permission_to_write(monkeypatch):
    """Absence in a failed read is not absence at the venue -- the same rule
    `reconcile_live_orders` applies before modifying any record. If we cannot
    see what the order is, we must not cancel it."""
    sends: list = []
    _venue(monkeypatch, sends=sends, fail_read=True)

    out = mod.cancel_order("C6HN0XD92KDE", execute=True)

    assert out["status"] == "error"
    assert "read_failed" in out["reason"]
    assert sends == [], "a cancel was sent after the read failed"


def test_absent_credentials_skip_rather_than_raise(monkeypatch):
    import syndicate.features.shared.polymarket_us_auth as auth

    monkeypatch.setattr(auth, "credentials_present", lambda: False)
    out = mod.cancel_order("C6HN0XD92KDE", execute=True)
    assert out["status"] == "skipped"
    assert out["reason"] == "credentials_absent"


def test_an_empty_order_id_is_refused_before_any_call(monkeypatch):
    sends: list = []
    _venue(monkeypatch, sends=sends)
    assert mod.cancel_order("  ", execute=True)["status"] == "refused"
    assert sends == []


def test_the_cancel_route_is_overridable_without_a_deploy(monkeypatch):
    """The route is a GUESS until a real call confirms it -- `DELETE
    /v1/order/{id}` by gRPC-gateway convention. It must be correctable by env,
    because discovering the true path should not need a code change on a day
    when a duplicate is resting."""
    monkeypatch.setenv("POLYMARKET_US_ORDER_CANCEL_PATH", "/v1/orders/cancel")
    assert mod._order_cancel_url("ABC").endswith("/v1/orders/cancel/ABC")


def test_the_POLYMARKET_cancel_is_not_yet_wired_into_any_automatic_path():
    """Operator capability only, FOR NOW -- and the distinction is deliberate.

    Kalshi already HAS an automatic cancel: `execution_ledger._cancel_stale_resting`
    pulls resting orders past an age and price-band rule, bounded by
    `SYNDICATE_EXECUTION_MAX_CANCELS` and logged by name. That is a sound design
    and this adapter is its missing Polymarket sibling.

    But wiring it there has a PRECONDITION that is verified for one venue and
    unknown for the other. That function's own reasoning is: *"Cancelling costs
    nothing at Kalshi -- an unfilled order carries no fee -- so the asymmetry
    runs the right way: a cancel we should not have made costs a re-place, a
    fill we should not have taken costs the stake."* **Nobody has established
    that Polymarket charges nothing to cancel.** Its fee model was falsified at
    low prices only today, so importing the asymmetry argument on faith is
    exactly the move this lane keeps catching.

    Until that is measured, choosing WHICH leg of a duplicate pair to retire
    stays a human judgement about sizing intent. This test fails the day someone
    wires it up, which is when that argument needs making explicitly.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    callers = []
    for path in list((root / "pipeline").rglob("*.py")) + list((root / "syndicate").rglob("*.py")):
        if path.name == "polymarket_us_orders.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "polymarket_us_orders import" in text and "cancel_order" in text:
            callers.append(str(path.relative_to(root)))
        elif "polymarket_us_orders.cancel_order(" in text:
            callers.append(str(path.relative_to(root)))
    assert callers == [], (
        "the Polymarket cancel is now called automatically by "
        f"{callers} -- establish the cancellation FEE first (see docstring)"
    )
