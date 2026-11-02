"""Kalshi maker pilot fair-move cancel (lane maker-pilot-fair-cancel): a resting post lives only while the
plan still wants it at the price it rests at. Evidence: findings_2026-10-31_maker_pilot_review.md."""
from __future__ import annotations

import datetime as dt

import pytest

from syndicate.features.shared import kalshi_maker_pilot as mp
from syndicate.features.shared.execution_ledger import OrderRequest, idempotency_key

T0 = dt.datetime(2026, 10, 30, 9, 30, tzinfo=dt.timezone.utc)
DATE = "2026-10-30"
TICKER = "KXNBATOTAL-26OCT30CHAWAS-218"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in ("SYNDICATE_KALSHI_MAKER_PILOT", "SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL",
                "SYNDICATE_KALSHI_MAKER_PILOT_EDGE_FLOOR", "SYNDICATE_REFRESH_STATE_BACKEND"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "1")
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL", "on")
    for store in (mp._seen, mp._pass_at, mp._routed_here):
        store.clear()
    mp._cache.update(at=None, orders=[])
    yield
    for store in (mp._seen, mp._pass_at, mp._routed_here):
        store.clear()


def _req(**kw) -> OrderRequest:
    # CHA@WAS o217.5 as posted: plan price -138 (0.5798) at EV 4.596% -> fair 0.6065.
    base = dict(position_key="pk-chawas", selected_date=DATE, venue="kalshi", sport="nba", event_id="e1",
                market="totals_alt", side="over", line=217.5, requested_price=-138.0,
                requested_stake_dollars=5.0, commence_time="2026-10-30T23:10:00Z", venue_ticker=TICKER,
                ev_pct=4.596)
    base.update(kw)
    return OrderRequest(**base)


def _row(req, *, yes=0.56, no=0.44, order_id="ord-1", **kw):
    row = {"idempotency_key": idempotency_key(req), "order_id": order_id, "ticker": req.venue_ticker,
           "side": req.side, "market": req.market, "line": req.line, "yes_price": yes, "no_price": no,
           "submitted_at": "2026-10-30T05:01:56Z", "execution_style": "maker_pilot"}
    row.update(kw)
    return row


class _Cancels:
    def __init__(self, status="ok"):
        self.ids, self.status = [], status

    def __call__(self, order_id):
        self.ids.append(order_id)
        return {"status": self.status, "reason": None if self.status == "ok" else "venue_down"}


def _review(rows, at=T0, cancel=None):
    cancel = cancel or _Cancels()
    return mp.review_resting(rows, now=at, cancel=cancel), cancel


# --------------------------------------------------------------------- the fair

def test_plan_fair_is_the_plans_price_times_one_plus_ev():
    # Pollard u1.5 as posted 10-25: +122 at EV 5.0921 -> 0.4734 (book consensus read 0.477).
    assert mp.plan_fair(_req(requested_price=122.0, ev_pct=5.0921)) == pytest.approx(0.4734, abs=1e-4)
    assert mp.plan_fair(_req(ev_pct=None)) is None


# --------------------------------------------------------------------- reachability: off != on

def test_fair_cancel_is_off_when_absent_and_on_when_set(monkeypatch):
    """Reachability, off != on. The switch is OFF WHEN ABSENT (user decision via 332cb014)."""
    mp.note_plan_sighting(_req(ev_pct=-4.0), now=T0)  # fair 0.5566 < resting 0.56: edge -0.3pp
    row = _row(_req())
    monkeypatch.delenv("SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL")
    absent, absent_cancels = _review([row])
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL", "off")
    off, off_cancels = _review([row])
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_FAIR_CANCEL", "on")
    on, on_cancels = _review([row])
    assert absent["status"] == "off" and absent_cancels.ids == []
    assert off["status"] == "off" and off_cancels.ids == []
    assert on["cancelled"] == 1 and on_cancels.ids == ["ord-1"]
    assert on["orders"][0]["reason"] == "edge_below_floor"


# --------------------------------------------------------------------- the two rules

def test_unseen_post_is_left_resting():
    result, cancels = _review([_row(_req())])
    assert result["unseen"] == 1 and cancels.ids == []


def test_post_with_edge_at_or_above_floor_is_kept():
    mp.note_plan_sighting(_req(), now=T0)  # fair 0.6065 vs resting 0.56: +4.6pp
    result, cancels = _review([_row(_req())])
    assert result["kept"] == 1 and cancels.ids == []


def test_post_below_floor_is_cancelled_and_floor_is_configurable(monkeypatch):
    # fair 0.5798 x 0.978 = 0.5671 vs resting 0.56: +0.71pp, under the default +1pp.
    mp.note_plan_sighting(_req(ev_pct=-2.2), now=T0)
    result, cancels = _review([_row(_req())])
    assert result["cancelled"] == 1 and result["orders"][0]["edge"] == pytest.approx(0.0071, abs=1e-4)
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT_EDGE_FLOOR", "0.005")
    result, cancels = _review([_row(_req())])
    assert result["kept"] == 1 and cancels.ids == []


def test_a_later_pass_without_the_position_cancels_as_plan_dropped():
    mp.note_plan_sighting(_req(), now=T0)
    other = _req(position_key="pk-other", event_id="e2", venue_ticker="KXNBATOTAL-26OCT30OTHER-220")
    mp.note_plan_sighting(other, now=T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 60))
    result, cancels = _review([_row(_req())], at=T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 90))
    assert cancels.ids == ["ord-1"] and result["orders"][0]["reason"] == "plan_dropped"


def test_the_same_pass_or_an_earlier_date_does_not_count_as_dropped():
    mp.note_plan_sighting(_req(), now=T0)
    mp.note_plan_sighting(_req(position_key="pk-same-pass", event_id="e2"), now=T0 + dt.timedelta(seconds=20))
    mp.note_plan_sighting(_req(position_key="pk-old", event_id="e3", selected_date="2026-10-29"),
                          now=T0 + dt.timedelta(hours=2))
    result, cancels = _review([_row(_req())], at=T0 + dt.timedelta(hours=2))
    assert result["kept"] == 1 and cancels.ids == []


# --------------------------------------------------------------------- after a restart

def _other_pass(at, date=DATE):
    """A plan pass that sends some OTHER Kalshi position of `date` at `at`."""
    mp.note_plan_sighting(_req(position_key="pk-other", event_id="e2", selected_date=date,
                               venue_ticker="KXNBATOTAL-26OCT30OTHER-220"), now=at)


def test_a_post_made_before_the_restart_and_missing_from_a_later_pass_is_dropped(monkeypatch):
    """2026-11-01: the two MLS posts left the plan after the 16:53Z restart and rested on to kickoff."""
    monkeypatch.setattr(mp, "_BOOT_AT", T0.timestamp())
    _other_pass(T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 60))
    result, cancels = _review([_row(_req(), selected_date=DATE)],
                              at=T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 90))
    assert cancels.ids == ["ord-1"] and result["orders"][0]["reason"] == "plan_dropped"
    assert result["unseen"] == 0


def test_after_a_restart_only_a_pass_past_the_margin_counts(monkeypatch):
    monkeypatch.setattr(mp, "_BOOT_AT", T0.timestamp())
    _other_pass(T0 + dt.timedelta(seconds=60))
    result, cancels = _review([_row(_req(), selected_date=DATE)], at=T0 + dt.timedelta(seconds=90))
    assert result["unseen"] == 1 and cancels.ids == []


def test_after_a_restart_an_undated_post_or_an_earlier_dated_pass_cancels_nothing(monkeypatch):
    monkeypatch.setattr(mp, "_BOOT_AT", T0.timestamp())
    _other_pass(T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 60), date="2026-10-29")
    late = T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 90)
    result, cancels = _review([_row(_req()), _row(_req(), selected_date=DATE, order_id="ord-2")], at=late)
    assert result["unseen"] == 2 and cancels.ids == []


def test_a_post_resent_after_the_restart_is_judged_on_its_sighting(monkeypatch):
    monkeypatch.setattr(mp, "_BOOT_AT", T0.timestamp())
    at = T0 + dt.timedelta(seconds=mp.PLAN_DROP_MARGIN_S + 60)
    mp.note_plan_sighting(_req(), now=at)
    result, cancels = _review([_row(_req(), selected_date=DATE)], at=at + dt.timedelta(seconds=30))
    assert result["kept"] == 1 and cancels.ids == []


def test_a_failed_cancel_leaves_the_post_and_says_so():
    mp.note_plan_sighting(_req(ev_pct=-4.0), now=T0)
    result, cancels = _review([_row(_req())], cancel=_Cancels(status="error"))
    assert result["failed"] == 1 and result["cancelled"] == 0 and cancels.ids == ["ord-1"]


def test_a_spread_reads_our_leg_with_market_and_line():
    """DET@BKN 10-30: side=home on spreads_alt 13.5 is the NO leg of -DET14 (posted 0.68)."""
    req = _req(position_key="pk-det", market="spreads_alt", side="home", line=13.5, requested_price=-233.0,
               ev_pct=3.399, venue_ticker="KXNBASPREAD-26OCT30DETBKN-DET14")
    assert mp._resting_leg_price(_row(req, yes=0.32, no=0.68)) == pytest.approx(0.68)
    mp.note_plan_sighting(req, now=T0)  # P(-233) 0.6996 x 1.034 = 0.7234 vs 0.68: +4.3pp -> kept
    result, _ = _review([_row(req, yes=0.32, no=0.68)])
    assert result["kept"] == 1


# --------------------------------------------------------------------- wired end to end

def test_a_post_from_an_earlier_slate_is_matched_by_contract():
    """FLA@UGA was posted 10-29 for 10-31: the 10-30 plan re-sends it under a NEW idempotency key
    (and refuses it `held_other_slate`). Keyed by contract, it is still the same post."""
    posted = _req(selected_date="2026-10-29", position_key="pk-posted")
    mp.note_plan_sighting(_req(selected_date="2026-10-30", position_key="pk-replanned"), now=T0)
    assert idempotency_key(posted) != idempotency_key(_req(selected_date="2026-10-30", position_key="pk-replanned"))
    result, cancels = _review([_row(posted)])
    assert result["kept"] == 1 and result["unseen"] == 0 and cancels.ids == []


def test_observe_records_only_when_the_pilot_is_on(monkeypatch):
    mp.observe_plan_position(_req())
    assert mp._seen == {} and mp._pass_at == {}
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT", "on")
    mp.observe_plan_position(_req())
    assert list(mp._seen) == [f"{TICKER}|yes"] and mp._pass_at == {DATE: pytest.approx(mp._seen[f"{TICKER}|yes"]["at"])}


def test_observe_never_raises(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_MAKER_PILOT", "on")
    monkeypatch.setattr(mp, "note_plan_sighting", lambda r: (_ for _ in ()).throw(RuntimeError("boom")))
    mp.observe_plan_position(_req())  # no exception


def _live_kalshi(monkeypatch):
    for key, value in (("SYNDICATE_EXECUTION_ENABLED", "1"), ("SYNDICATE_EXECUTION_MODE", "live"),
                       ("SYNDICATE_EXECUTION_LIVE_ARMED", "1"), ("SYNDICATE_EXECUTION_VENUE", "kalshi")):
        monkeypatch.setenv(key, value)


def test_the_executor_tick_hands_resting_pilot_rows_to_the_review(monkeypatch):
    """Reachability at the CADENCE the rule needs: every Kalshi executor tick, not the boot dump.
    Measured 2026-11-01: hooked in `cancel_stale_resting_orders` it ran 0 times over 13 reconciles."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger as L

    _live_kalshi(monkeypatch)
    pilot, kicked = _row(_req()), _row(_req(position_key="pk-k"), order_id="ord-k")
    taker = _row(_req(position_key="pk-t"), order_id="ord-t", execution_style=None)
    resting = [pilot, kicked, taker]
    monkeypatch.setattr(L, "reconcile_live_orders",
                        lambda venue="kalshi", **_: {"status": "ok", "resting": resting if venue == "kalshi" else []})
    monkeypatch.setattr(L, "cancel_pregame_resting_at_kickoff",
                        lambda rows, **_: {"status": "ok", "orders": [{"idempotency_key": kicked["idempotency_key"]}]})
    handed: list = []
    monkeypatch.setattr(mp, "review_resting", lambda rows, **_: handed.append(list(rows)) or {})
    runner.run_execution(DATE, venue_scope="kalshi")
    assert handed == [[pilot]]  # the taker row and the row the kickoff cancel pulled are not reviewed

    handed.clear()
    runner.run_execution(DATE, venue_scope="polymarket")
    assert handed == []


def test_a_review_failure_never_costs_the_executor_its_pass(monkeypatch):
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger as L

    _live_kalshi(monkeypatch)
    asked: list = []
    monkeypatch.setattr(L, "reconcile_live_orders",
                        lambda venue="kalshi", **_: asked.append(venue) or {"status": "ok", "resting": [_row(_req())]})
    monkeypatch.setattr(L, "cancel_pregame_resting_at_kickoff", lambda rows, **_: {"orders": []})
    monkeypatch.setattr(mp, "review_resting", lambda rows, **_: (_ for _ in ()).throw(RuntimeError("boom")))
    runner.run_execution(DATE, venue_scope="kalshi")
    assert asked == ["kalshi", "polymarket"]  # the Polymarket reconcile after it still ran


def test_the_executor_records_each_position_before_any_gate():
    """A sighting recorded after a refusal would read a refused position as dropped."""
    import inspect
    from pipeline import execute_portfolio as runner

    src = inspect.getsource(runner._run_execution)
    loop = src[src.index("for position in positions:"):]
    at = loop.index("observe_plan_position(request)")
    for gate in ("held_by_venue_book", "no_venue_ticker", "REFUSAL_HELD_OTHER_SLATE",
                 "REFUSAL_HELD_VENUE_CONTRACT", "REFUSAL_PRICE_BAND", "_maker_route(request)"):
        assert at < loop.index(gate), gate


def test_the_boot_stale_pass_no_longer_reviews_pilot_rows(monkeypatch):
    from syndicate.features.shared import execution_ledger as mod

    mp.note_plan_sighting(_req(ev_pct=-4.0), now=T0)  # would be below floor
    called: list = []
    monkeypatch.setattr(mp, "review_resting", lambda rows, **_: called.append(rows))
    cancels = _Cancels()
    monkeypatch.setattr("syndicate.features.shared.kalshi_orders.cancel_order", cancels)
    monkeypatch.setattr(mod, "_market_price_for_side", lambda ticker, side: 0.60)
    result = mod.cancel_stale_resting_orders([_row(_req(), submitted_at="2020-01-01T00:00:00Z")])
    assert result["maker_pilot"] == 1 and cancels.ids == [] and called == []


def test_the_resting_row_carries_market_and_line():
    import inspect
    from syndicate.features.shared import execution_ledger as mod

    src = inspect.getsource(mod.reconcile_live_orders)
    block = src[src.index("resting.append("):src.index("after = STATUS_SUBMITTED", src.index("resting.append("))]
    assert '"market": order.get("market")' in block and '"line": order.get("line")' in block
