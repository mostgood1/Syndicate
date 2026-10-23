"""In-game LIVE entries: off by default, the paper rule's hook, budget, IOC body, executor seams."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from syndicate.features.shared import inplay_entries_live as live
from syndicate.features.shared import inplay_entries_paper as ip
from syndicate.features.shared import kalshi_orders as ko

DAY = "2026-10-22"
ENTRY = {"key": f"{DAY}:KXNHLSPREAD-26OCT22TORCBJ-TOR2:yes", "ticker": "KXNHLSPREAD-26OCT22TORCBJ-TOR2",
         "leg": "yes", "ask": 0.30, "edge": 0.05, "line": 1.5}


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for k in ("SYNDICATE_INPLAY_ENTRIES", "SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "SYNDICATE_EXECUTION_MODE",
              "SYNDICATE_EXECUTION_LIVE_ARMED", "SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF"):
        monkeypatch.delenv(k, raising=False)


def _placer(orders=(), enabled=True):
    calls: list = []

    def place(**kw):
        calls.append(kw)
        return {"placed": True, "status": "submitted"}

    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: list(orders), place_fn=place,
                             enabled_fn=(lambda: enabled))
    return p, calls


def test_off_by_default_and_needs_a_live_armed_executor(monkeypatch):
    assert live.live_entries_enabled() is False  # switch absent
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRIES", "on")
    assert live.live_entries_enabled() is False  # executor not live/armed
    for raw in ("true", "1", "paper", "yes"):
        monkeypatch.setenv("SYNDICATE_INPLAY_ENTRIES", raw)
        assert live.entries_switch_on() is False
    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [],
                             place_fn=lambda **kw: pytest.fail("placed while off"))
    assert p(ENTRY) == {"placed": False, "reason": "live_entries_off"}


def test_reachability_on_places_exactly_one_contract():
    p, calls = _placer()
    assert p(ENTRY)["placed"] is True
    (kw,) = calls
    assert kw["ticker"] == ENTRY["ticker"] and kw["leg"] == "yes" and kw["stake"] == 0.31  # ask + 1c
    assert int(kw["stake"] // 0.31) == 1 and int(kw["stake"] // 0.30) == 1  # floors to ONE contract


def test_once_per_ticker_leg_per_day_from_the_ledger():
    row = {"position_key": f"ingame:{ENTRY['ticker']}:yes", "selected_date": DAY, "status": "rejected"}
    p, calls = _placer(orders=[row])
    assert p(ENTRY) == {"placed": False, "reason": "already_in_ledger_today"} and not calls


def test_day_budget_and_its_ceiling(monkeypatch):
    rows = [{"position_key": f"ingame:T{i}:yes", "selected_date": DAY, "status": "filled",
             "fill_stake_dollars": 4.97} for i in range(10)]  # $49.70 spent
    p, calls = _placer(orders=rows)
    out = p(ENTRY)
    assert out["placed"] is False and out["reason"] == "in_game_day_budget" and not calls
    assert live.day_budget_dollars() == 50.0
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "500")
    assert live.day_budget_dollars() == 50.0  # the user's cap is a ceiling
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "20")
    assert live.day_budget_dollars() == 20.0
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "junk")
    assert live.day_budget_dollars() == 50.0


def _req(**kw):
    base = dict(venue_ticker="KXNHLSPREAD-26OCT22TORCBJ-TOR2", side="yes", market="spreads", line=1.5,
                requested_stake_dollars=0.31, position_key="ingame:x:yes", selected_date=DAY, venue="kalshi",
                sport="nhl", event_id="e", player_name=None,
                commence_time=(datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    base.update(kw)
    return SimpleNamespace(**base)


def test_ioc_body_and_every_other_body_unchanged(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "on")
    plain = ko.order_body_v2(_req(), price_dollars=0.31)
    assert plain["time_in_force"] != "immediate_or_cancel" and "expiration_time" in plain
    ioc = ko.order_body_v2(live._IOC(_req()), price_dollars=0.31)
    assert ioc["time_in_force"] == "immediate_or_cancel" and "expiration_time" not in ioc
    assert {k: v for k, v in ioc.items() if k != "time_in_force"} == {
        k: v for k, v in plain.items() if k not in ("time_in_force", "expiration_time")}
    odd = ko.order_body_v2(_req(time_in_force="good_till_canceled_forever"), price_dollars=0.31)
    assert odd == plain  # only the allowlisted value changes anything


def test_ioc_submitter_builds_and_sends_the_ioc_request():
    seen: list = []

    def base_build(req):
        seen.append(getattr(req, "time_in_force", None))
        return lambda: {"ok": True}

    base = SimpleNamespace(build=base_build)
    sub = live.ioc_submitter(base)
    assert sub(_req()) == {"ok": True} and seen == ["immediate_or_cancel"]
    sub.build(_req())
    assert seen == ["immediate_or_cancel"] * 2


def test_place_live_refusal_sends_nothing(monkeypatch):
    from syndicate.features.shared import execution_guard, execution_ledger

    monkeypatch.setattr(execution_guard, "check_order", lambda r, **kw: {"allowed": False, "reason": "kill_switch"})
    monkeypatch.setattr(execution_ledger, "place_order", lambda *a, **k: pytest.fail("sent after a refusal"))
    out = live._place_live(ticker=ENTRY["ticker"], leg="yes", ask=0.30, stake=0.31, line=1.5, day=DAY,
                           spend={"dollars": 0.0, "orders": 0})
    assert out == {"placed": False, "reason": "kill_switch"}


def test_place_live_feeds_the_in_game_spend_to_the_guard(monkeypatch):
    from syndicate.features.shared import execution_guard, execution_ledger

    seen = {}

    def check(r, **kw):
        seen.update(kw)
        seen["stake"] = r.requested_stake_dollars
        return {"allowed": True}

    monkeypatch.setattr(execution_guard, "check_order", check)
    monkeypatch.setattr(execution_ledger, "place_order",
                        lambda req, **k: {"status": "submitted", "idempotency_key": "k1"})
    out = live._place_live(ticker=ENTRY["ticker"], leg="yes", ask=0.30, stake=0.31, line=1.5, day=DAY,
                           spend={"dollars": 3.0, "orders": 2})
    assert out == {"placed": True, "status": "submitted", "key": "k1"}
    assert seen["already"] == {"dollars": 3.0, "orders": 2} and seen["stake"] == 0.31


def test_the_paper_rule_hands_its_booked_entry_to_the_hook(monkeypatch):
    """Reachability: a real paper booking through step() calls on_book once, and stores its answer."""
    from tests import test_inplay_entries_paper as tp

    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    got: list = []
    persisted: list = []
    ts = [tp.T0, tp.T0 + 200, tp.T0 + 220]
    m = [tp._market(), tp._other()]
    loop, advance = tp._loop([m, m, m], [("in", ("1", "0"))], ts, persisted)
    loop.on_book = lambda e: (got.append(e) or {"placed": True, "status": "submitted"})
    advance(0)
    advance(1)
    assert advance(2)["booked"] == 1
    (e,) = loop.doc["entries"].values()
    assert len(got) == 1 and got[0]["ticker"] == e["ticker"] and got[0]["leg"] == e["leg"]
    assert e["live"] == {"placed": True, "status": "submitted"}

    def boom(_e):
        raise RuntimeError("venue down")

    loop2, advance2 = tp._loop([m, m, m], [("in", ("1", "0"))], ts, [])
    loop2.on_book = boom
    advance2(0)
    advance2(1)
    assert advance2(2)["booked"] == 1  # the paper record survives a raising hook
    (e2,) = loop2.doc["entries"].values()
    assert e2["live"]["placed"] is False and "venue down" in e2["live"]["reason"]
