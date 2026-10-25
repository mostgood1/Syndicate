"""Kalshi maker pilot (lane kalshi-maker-pilot): off is the old executor, on posts, caps hold."""
from __future__ import annotations

import dataclasses
import datetime as dt

import pytest

from syndicate.features.shared import kalshi_maker_pilot as mp
from syndicate.features.shared.execution_ledger import OrderRequest, idempotency_key

NOW = dt.datetime(2026, 10, 24, 18, 0, tzinfo=dt.timezone.utc)
KICK = "2026-10-24T23:00:00Z"
TICKER = "KXNBATOTAL-26OCT24AAABBB-216"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in ("SYNDICATE_KALSHI_MAKER_PILOT", "SYNDICATE_KALSHI_MAKER_PILOT_DAY_DOLLARS",
                "SYNDICATE_KALSHI_MAKER_PILOT_ORDER_DOLLARS", "SYNDICATE_EXECUTION_ENABLED",
                "SYNDICATE_EXECUTION_MODE", "SYNDICATE_EXECUTION_LIVE_ARMED", "SYNDICATE_EXECUTION_VENUE",
                "SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "SYNDICATE_REFRESH_STATE_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "1")
    mp._routed_here.clear()
    mp._cache.update(at=None, orders=[])
    yield
    mp._routed_here.clear()


def _req(**kw) -> OrderRequest:
    base = dict(position_key="pk-1", selected_date="2026-10-24", venue="kalshi", sport="nba", event_id="e1",
                market="totals", side="over", line=215.5, requested_price=-110.0, requested_stake_dollars=8.0,
                commence_time=KICK, venue_ticker=TICKER)
    base.update(kw)
    return OrderRequest(**base)


def _on():
    return True


def _route(req, orders=(), now=NOW):
    return mp.route(req, now=now, orders=list(orders), enabled_fn=_on, wrap=lambda s: s)


def _pilot_row(req, status="submitted", submitted_at="2026-10-24T17:00:00Z", stake=5.0):
    return {"idempotency_key": idempotency_key(req), "execution_style": "maker_pilot", "mode": "live",
            "status": status, "submitted_at": submitted_at, "requested_stake_dollars": stake}


# --------------------------------------------------------------------- reachability: off != on

def test_off_by_default_routes_nothing_and_reads_nothing(monkeypatch):
    monkeypatch.setattr(mp, "_ledger_orders", lambda: pytest.fail("off must not read the ledger"))
    assert mp.pilot_enabled() is False
    assert mp.route(_req(), now=NOW) is None


def test_switch_on_without_live_arming_is_still_off(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT", "on")
    assert mp.pilot_enabled() is False          # paper mode, unarmed
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    assert mp.pilot_enabled() is True


def test_on_routes_an_eligible_pregame_request_with_the_pilot_stake_and_tag():
    off = mp.route(_req(), now=NOW, orders=[], enabled_fn=lambda: False)
    on = _route(_req())
    assert off is None and on is not None and on.skip is None
    assert on.request.requested_stake_dollars == 5.0
    assert on.request.execution_style == "maker_pilot"
    # same bet: the pilot never changes the position identity
    assert idempotency_key(on.request) == idempotency_key(_req())


def test_order_and_day_caps_cannot_be_raised_by_env(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_ORDER_DOLLARS", "50")
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_DAY_DOLLARS", "1000")
    assert mp.order_dollars() == 5.0 and mp.day_budget_dollars() == 10.0
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_DAY_DOLLARS", "5")
    assert mp.day_budget_dollars() == 5.0


# --------------------------------------------------------------------- gates

@pytest.mark.parametrize("kw,reason", [
    (dict(venue="polymarket"), "not_kalshi"),
    (dict(commence_time="2026-10-24T17:00:00Z"), "not_pregame"),      # started
    (dict(commence_time="2026-10-24T18:05:00Z"), "not_pregame"),      # < 10 min lead
    (dict(commence_time=None), "no_commence_time"),
])
def test_ineligible_requests_stay_taker(kw, reason):
    assert mp.refusal(_req(**kw), now=NOW, orders=[], enabled_fn=_on) == reason
    assert _route(_req(**kw)) is None


def test_needs_the_venue_kickoff_expiry(monkeypatch):
    monkeypatch.delenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF")
    assert mp.refusal(_req(), now=NOW, orders=[], enabled_fn=_on) == "no_kickoff_expiry:disabled"


def test_day_cap_counts_resting_and_filled_today_only():
    a, b = _req(position_key="a"), _req(position_key="b")
    today = [_pilot_row(a, "submitted"), _pilot_row(b, "filled")]
    assert mp.refusal(_req(), now=NOW, orders=today, enabled_fn=_on).startswith("pilot_day_cap:10.00")
    released = [_pilot_row(a, "rejected"), _pilot_row(b, "filled")]
    assert mp.refusal(_req(), now=NOW, orders=released, enabled_fn=_on) is None
    yesterday = [_pilot_row(a, "filled", "2026-10-23T15:00:00Z"), _pilot_row(b, "filled", "2026-10-23T16:00:00Z")]
    assert mp.refusal(_req(), now=NOW, orders=yesterday, enabled_fn=_on) is None
    taker = [{**_pilot_row(a), "execution_style": None}, {**_pilot_row(b), "execution_style": None}]
    assert mp.refusal(_req(), now=NOW, orders=taker, enabled_fn=_on) is None


def test_one_post_per_position_no_repost_no_taker_fallback():
    req = _req()
    for status in ("submitted", "filled", "rejected"):
        routed = _route(req, orders=[_pilot_row(req, status)])
        assert routed is not None and routed.skip == "maker_pilot_held" and routed.submitter is None


def test_a_send_in_this_process_counts_before_the_ledger_shows_it(monkeypatch):
    monkeypatch.setattr(mp, "_key", lambda r: idempotency_key(r))
    mp._routed_here.extend([("k1", "2026-10-24", 5.0), ("k2", "2026-10-24", 5.0)])
    assert mp.refusal(_req(), now=NOW, orders=[], enabled_fn=_on).startswith("pilot_day_cap")


# --------------------------------------------------------------------- price and body

def _market(**m):
    return lambda ticker: {"status": "ok", "market": m}


@pytest.mark.parametrize("bid,ask,post", [("0.4400", "0.4700", 0.45), ("0.4400", "0.4500", 0.44),
                                          ("0.4400", "0.4600", 0.45)])
def test_maker_price_is_one_tick_inside_never_at_the_ask(bid, ask, post):
    fetch = _market(yes_bid_dollars=bid, yes_ask_dollars=ask, no_bid_dollars="0.5300", no_ask_dollars="0.5600")
    assert mp.maker_price(_req(side="over"), fetch=fetch) == post


def test_maker_price_reads_the_no_leg_and_refuses_an_empty_book():
    fetch = _market(yes_bid_dollars="0.4400", yes_ask_dollars="0.4700", no_bid_dollars="0.5300", no_ask_dollars="0.5600")
    assert mp.maker_price(_req(side="under"), fetch=fetch) == 0.54
    assert mp.maker_price(_req(), fetch=_market(yes_bid_dollars=None, yes_ask_dollars="0.4700")) is None
    assert mp.maker_price(_req(), fetch=lambda t: {"status": "error", "reason": "x"}) is None


def test_body_is_post_only_and_expires_at_kickoff_only_for_the_pilot(monkeypatch):
    from syndicate.features.shared import kalshi_orders as ko

    plain = ko.order_body_v2(_req(requested_stake_dollars=5.0), price_dollars=0.45, now=NOW)
    pilot = ko.order_body_v2(mp._Maker(_req(requested_stake_dollars=5.0)), price_dollars=0.45, now=NOW)
    assert plain["post_only"] is False and pilot["post_only"] is True
    assert pilot["expiration_time"] == int(dt.datetime(2026, 10, 24, 23, tzinfo=dt.timezone.utc).timestamp())
    assert pilot["time_in_force"] == plain["time_in_force"] == "good_till_canceled"
    assert {k: v for k, v in pilot.items() if k != "post_only"} == {k: v for k, v in plain.items() if k != "post_only"}


def test_the_ledger_row_carries_the_tag():
    from syndicate.features.shared.execution_ledger import _record_into_state

    state: dict = {"orders": []}
    row, created = _record_into_state(state, dataclasses.replace(_req(), execution_style="maker_pilot"), mode="live")
    assert created and row["execution_style"] == "maker_pilot"
    row2, _ = _record_into_state({"orders": []}, _req(), mode="live")
    assert row2["execution_style"] is None


def test_reconcile_lines():
    base = {"execution_style": "maker_pilot", "idempotency_key": "k", "ticker": TICKER, "from": "submitted"}
    assert "MAKER_PILOT FILL" in mp.reconcile_line({**base, "to": "filled"})
    assert "MAKER_PILOT EXPIRE" in mp.reconcile_line({**base, "to": "rejected"})
    assert mp.reconcile_line({**base, "execution_style": None, "to": "filled"}) is None


# --------------------------------------------------------------------- the executor seam, off != on

def _plan_row():
    from tests.test_execute_portfolio import _row

    kick = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=6)
    eastern = (kick - dt.timedelta(hours=5)).strftime("%y%b%d").upper()   # the ticker carries the ET date
    return _row(venue_ticker=f"KXMLBGAME-{eastern}AWAYHOME-HOME", commence_time=kick.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _run_live(monkeypatch, pilot: bool):
    from pipeline import execute_portfolio as runner
    from tests.test_execute_portfolio import _write_live_plan

    monkeypatch.setenv("SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY", "off")
    _write_live_plan(monkeypatch, [_plan_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    if pilot:
        monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT", "on")
    taker, maker = [], []

    def taker_submit(request):
        taker.append(request)
        return {"status": "filled", "fill_price": 0.46, "fill_stake_dollars": 0.92}

    def maker_submit(request):
        maker.append(request)
        return {"status": "submitted", "venue_status": "resting"}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: taker_submit)
    monkeypatch.setattr(mp, "maker_submitter", lambda price_for=None: maker_submit)
    result = runner.run_execution("2026-08-22", venue_scope="kalshi")
    return result, taker, maker


def test_executor_off_takes_as_before(monkeypatch):
    result, taker, maker = _run_live(monkeypatch, pilot=False)
    assert len(taker) == 1 and not maker
    assert getattr(taker[0], "execution_style", None) is None


def test_executor_on_posts_instead_of_taking_then_holds(monkeypatch):
    from syndicate.features.shared.execution_ledger import _load

    result, taker, maker = _run_live(monkeypatch, pilot=True)
    assert not taker and len(maker) == 1
    assert maker[0].execution_style == "maker_pilot" and maker[0].requested_stake_dollars == 5.0
    rows = [o for o in _load().get("orders") or [] if o.get("venue") == "kalshi"]
    assert len(rows) == 1 and rows[0]["execution_style"] == "maker_pilot"
    # the next pass neither re-posts nor takes it
    from pipeline import execute_portfolio as runner

    mp._cache.update(at=None, orders=[])
    again = runner.run_execution("2026-08-22", venue_scope="kalshi")
    assert len(maker) == 1 and not taker
