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
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))  # decision records land under the data root
    for k in ("SYNDICATE_INPLAY_ENTRIES", "SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "SYNDICATE_EXECUTION_MODE",
              "SYNDICATE_EXECUTION_LIVE_ARMED", "SYNDICATE_KALSHI_EXPIRE_AT_KICKOFF", "SYNDICATE_LIVE_PRICE_BAND", "SYNDICATE_LIVE_CELL_GATE",
              "SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "SYNDICATE_KALSHI_ROUND_UP_MIN_DOLLARS"):
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
    assert live.day_budget_dollars() == 50.0  # absent = the original cap, never the ceiling
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "500")
    assert live.day_budget_dollars() == 100.0  # the user's $100/day (2026-10-28) is a ceiling
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "20")
    assert live.day_budget_dollars() == 20.0
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "junk")
    assert live.day_budget_dollars() == 50.0
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_DAY_DOLLARS", "100")
    p, calls = _placer(orders=rows)
    assert p(ENTRY)["placed"] is True and len(calls) == 1  # $49.70 spent: room under $100


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
    assert out["placed"] is False and out["reason"] == "kill_switch"
    assert out["check_order"] == {"verdict": "fail", "reason": "kill_switch"} and len(out["idempotency_key"]) == 24


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
    assert {k: out[k] for k in ("placed", "status", "key", "idempotency_key")} == {
        "placed": True, "status": "submitted", "key": "k1", "idempotency_key": "k1"}
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


def test_one_entry_per_game_axis_per_day():
    """Two DAL@IND unders on adjacent total lines must not both go out (live 2026-10-23 23:38-23:39Z)."""
    held = {"position_key": "ingame:KXNBATOTAL-26OCT23DALIND-249:no", "venue_ticker": "KXNBATOTAL-26OCT23DALIND-249",
            "selected_date": DAY, "status": "filled", "fill_stake_dollars": 0.42, "fees_dollars": 0.0171}
    p, calls = _placer(orders=[held])
    same_axis = {**ENTRY, "ticker": "KXNBATOTAL-26OCT23DALIND-251", "leg": "no", "ask": 0.44}
    out = p(same_axis)
    assert out["placed"] is False and out["reason"] == "same_game_axis_held" and not calls
    other_axis = {**ENTRY, "ticker": "KXNBASPREAD-26OCT23DALIND-IND5", "leg": "yes", "ask": 0.40}
    assert p(other_axis)["placed"] is True  # margin axis of the same game is a different axis
    other_game = {**ENTRY, "ticker": "KXNBATOTAL-26OCT23ATLCHA-226", "leg": "yes", "ask": 0.45}
    assert p(other_game)["placed"] is True


def test_an_unfilled_ioc_does_not_hold_its_axis_and_fees_count():
    dead = {"position_key": "ingame:KXNBATOTAL-26OCT23ATLCHA-226:yes", "venue_ticker": "KXNBATOTAL-26OCT23ATLCHA-226",
            "selected_date": DAY, "status": "rejected", "requested_stake_dollars": 0.46}
    filled = {"position_key": "ingame:KXNBATOTAL-26OCT23DALIND-249:no", "venue_ticker": "KXNBATOTAL-26OCT23DALIND-249",
              "selected_date": DAY, "status": "filled", "fill_stake_dollars": 0.42, "fees_dollars": 0.0171}
    s = live.in_game_spend([dead, filled], DAY)
    assert s["dollars"] == round(0.42 + 0.0171, 4) and s["orders"] == 1
    assert ("26OCT23ATLCHA", "total") not in s["held_axes"] and ("26OCT23DALIND", "total") in s["held_axes"]


EVENT = {"id": "oddsapi-ev-1", "home_team": "Boston Celtics", "away_team": "New York Knicks",
         "commence_time": "2026-10-23T23:30:00Z"}


def test_human_selection_maps_back_to_the_same_kalshi_contract():
    """The portfolio label must never change the bet: every kind x leg round-trips through _side_to_kalshi."""
    cases = [("spreads", "New York", 5.5), ("spreads", "Boston", 3.5), ("totals", "Over", 214.5),
             ("h2h", "Boston", None), ("h2h", "New York", None)]
    for kind, team, line in cases:
        for leg in ("yes", "no"):
            side, ln = ip.human_selection(kind, team, line, leg, EVENT)
            assert ko._side_to_kalshi(side, kind, ln) == leg, (kind, team, leg, side, ln)
    assert ip.human_selection("spreads", "New York", 5.5, "yes", EVENT) == ("away", -5.5)  # NYK -5.5
    assert ip.human_selection("spreads", "New York", 5.5, "no", EVENT) == ("home", 5.5)   # BOS +5.5
    assert ip.human_selection("totals", "Over", 214.5, "no", EVENT) == ("under", 214.5)
    assert ip.human_selection("h2h", "Boston", None, "yes", EVENT) == ("home", None)


def test_place_live_stamps_the_game_and_the_human_side(monkeypatch):
    from syndicate.features.shared import execution_guard, execution_ledger

    seen = {}
    monkeypatch.setattr(execution_guard, "check_order", lambda r, **kw: seen.update(req=r) or {"allowed": True})
    monkeypatch.setattr(execution_ledger, "place_order", lambda req, **k: {"status": "submitted", "idempotency_key": "k"})
    game = {"event_id": "oddsapi-ev-1", "home_team": "Boston Celtics", "away_team": "New York Knicks",
            "commence_time": "2026-10-23T23:30:00Z", "order_side": "away", "order_line": -5.5}
    out = live._place_live(ticker="KXNBASPREAD-26OCT23NYKBOS-NYK6", leg="yes", ask=0.44, stake=0.45, line=5.5,
                           day=DAY, sport="nba", market="spreads", spend={"dollars": 0.0, "orders": 0}, game=game)
    assert out["placed"] is True
    r = seen["req"]
    assert (r.event_id, r.home_team, r.away_team, r.commence_time) == (
        "oddsapi-ev-1", "Boston Celtics", "New York Knicks", "2026-10-23T23:30:00Z")
    assert (r.side, r.line, r.market, r.sport) == ("away", -5.5, "spreads", "nba")


def test_a_label_that_would_change_the_leg_is_refused(monkeypatch):
    from syndicate.features.shared import execution_guard, execution_ledger

    monkeypatch.setattr(execution_guard, "check_order", lambda r, **kw: pytest.fail("checked a mislabelled order"))
    monkeypatch.setattr(execution_ledger, "place_order", lambda *a, **k: pytest.fail("sent a mislabelled order"))
    bad = {"event_id": "e", "order_side": "home", "order_line": 5.5}  # +5.5 -> NO, but the decision was YES
    out = live._place_live(ticker="KXNBASPREAD-26OCT23NYKBOS-NYK6", leg="yes", ask=0.44, stake=0.45, line=5.5,
                           day=DAY, sport="nba", market="spreads", spend={"dollars": 0.0, "orders": 0}, game=bad)
    assert out["placed"] is False and out["reason"].startswith("side_relabel_mismatch")


def test_the_live_price_band_refuses_outside_and_writes_nothing(monkeypatch):
    # Same env and parser as the pregame executor; [low, high) on the ask as a probability.
    monkeypatch.setenv("SYNDICATE_LIVE_PRICE_BAND", "0.40,0.75")
    for ask, placed in ((0.12, False), (0.399, False), (0.40, True), (0.749, True), (0.75, False), (0.90, False)):
        p, calls = _placer()
        result = p({**ENTRY, "ask": ask})
        assert result["placed"] is placed, ask
        assert len(calls) == (1 if placed else 0)
        if not placed:
            assert result["reason"] == "outside_price_band"
    # absent or unusable = off, exactly as pregame: the 0.30 entry is placed
    for raw in (None, "junk", "0.8,0.4"):
        if raw is None:
            monkeypatch.delenv("SYNDICATE_LIVE_PRICE_BAND", raising=False)
        else:
            monkeypatch.setenv("SYNDICATE_LIVE_PRICE_BAND", raw)
        p, calls = _placer()
        assert p(ENTRY)["placed"] is True and len(calls) == 1


def test_live_price_reads_the_leg_not_the_human_side(monkeypatch):
    # 2026-10-24: a NO leg labelled "under" read the YES ask and was refused no_live_price.
    from syndicate.features.shared import kalshi_client

    market = {"yes_ask_dollars": "0.6000", "no_ask_dollars": "0.4100"}
    monkeypatch.setattr(kalshi_client, "fetch_market", lambda t: {"status": "ok", "market": market})
    req = SimpleNamespace(venue_ticker="KXNBATOTAL-26OCT23DALIND-249", side="under")
    assert live.LivePrice(0.41, "no")(req) == 0.41
    assert live.LivePrice(0.60, "yes")(SimpleNamespace(venue_ticker="T", side="over")) == 0.60
    assert live.LivePrice(0.41, "yes")(req) is None  # the other leg's ask is a price move, refused


def _gated_placer(gate, clock=None):
    calls, reads = [], []

    def gate_fn():
        reads.append(1)
        return gate() if callable(gate) else gate

    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [], enabled_fn=lambda: True,
                             place_fn=lambda **kw: calls.append(kw) or {"placed": True, "status": "submitted"},
                             gate_fn=gate_fn, clock=clock or (lambda: 0.0))
    return p, calls, reads


def test_live_cell_gate_off_reads_nothing_and_places():
    p, calls, reads = _gated_placer({"cells": {"kalshi|nhl|spread|in_game": {"status": "tripped"}}, "unknown": None})
    assert p({**ENTRY, "sport": "nhl", "kind": "spreads"})["placed"] is True and len(calls) == 1 and not reads


def test_live_cell_gate_refuses_its_tripped_cell_only(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_CELL_GATE", "on")
    gate = {"cells": {"kalshi|nba|spread|in_game": {"status": "tripped"},
                      "kalshi|nba|total|in_game": {"status": "armed"}}, "unknown": None}
    p, calls, _ = _gated_placer(gate)
    tk = "KXNBASPREAD-26OCT24AAABBB-AAA3"
    out = p({**ENTRY, "ticker": tk, "sport": "nba", "kind": "spreads"})
    assert out == {"placed": False, "reason": "live_cell_tripped"} and not calls
    assert p({**ENTRY, "ticker": "KXNBATOTAL-26OCT24CCCDDD-220", "sport": "nba", "kind": "totals"})["placed"] is True
    assert p({**ENTRY, "ticker": "KXNHLSPREAD-26OCT24EEEFFF-EEE2", "sport": "nhl", "kind": "spreads"})["placed"] is True


def test_live_cell_gate_unknown_fails_closed_and_the_read_is_cached(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_CELL_GATE", "on")
    t = {"now": 0.0}
    p, calls, reads = _gated_placer({"cells": {}, "unknown": "state read not ok"}, clock=lambda: t["now"])
    for i in range(3):
        out = p({**ENTRY, "ticker": f"KXNHLSPREAD-26OCT24G{i}H{i}I{i}-X2"})
        assert out == {"placed": False, "reason": "live_cell_gate_unknown"}
    assert not calls and len(reads) == 1  # one store read per CELL_GATE_CACHE_S
    t["now"] = live.CELL_GATE_CACHE_S
    p({**ENTRY, "ticker": "KXNHLSPREAD-26OCT24JJJKKK-J2"})
    assert len(reads) == 2


def test_order_dollars_off_is_one_contract_on_is_whole_contracts(monkeypatch):
    for raw in ("", "abc", "0", "-3"):
        monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", raw)
        assert live.order_dollars() is None and live.entry_stake(0.30) == 0.31
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "3")
    off_stake = 0.31
    on_stake = live.entry_stake(0.30)
    assert on_stake != off_stake and on_stake == 2.7901  # 9 contracts at 31c, under $3
    for ask in (0.40, 0.55, 0.74):
        stake = live.entry_stake(ask)
        n = round(stake / (ask + 0.01))
        assert stake <= 3.0 + 1e-3 and n >= 1
        for price in (ask - 0.01, ask, ask + 0.01):  # the submitter floors at any live ask within 1c
            assert ko.contracts_for_stake(stake, price) == n


def test_order_dollars_ceiling_and_the_placer_reads_it(monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "500")
    assert live.order_dollars() == live.ORDER_DOLLARS_CEILING == 5.0
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "3")
    p, calls = _placer()
    assert p(ENTRY)["placed"] is True
    assert calls[0]["stake"] == 2.7901


def test_order_dollars_still_bounded_by_the_day_budget(monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "3")
    spent = [{"position_key": f"ingame:T{i}-X:yes", "venue_ticker": f"KXNHLSPREAD-G{i}-X", "selected_date": DAY,
              "status": "filled", "fill_stake_dollars": 4.8} for i in range(10)]  # $48.00 spent
    p, calls = _placer(orders=spent)
    out = p(ENTRY)
    assert out["placed"] is False and out["reason"] == "in_game_day_budget" and calls == []



# --------------------------------------------------------------------------- the decision record (item (e))

BOOKED = {**ENTRY, "key": ENTRY["key"], "sport": "nhl", "kind": "spreads", "fair": 0.38, "fair_version": ip.FAIR_VERSION,
          "n_books": 4, "fee": 0.0147, "team": "TOR", "at": "2026-10-22T23:50:00Z", "since_score_s": 400,
          "mid_move_60s": 0.01, "event_id": "oddsapi-ev-9", "home_team": "Columbus Blue Jackets",
          "away_team": "Toronto Maple Leafs", "commence_time": "2026-10-22T23:00:00Z", "order_side": "away",
          "order_line": -1.5}


def test_a_placed_entry_joins_the_ledger_row_by_its_idempotency_key(monkeypatch):
    """Through the REAL _place_live: the record's key is the ledger's key for the very request sent."""
    from syndicate.features.shared import execution_guard, execution_ledger

    monkeypatch.setenv("SYNDICATE_LIVE_PRICE_BAND", "0.20,0.75")
    monkeypatch.setenv("SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS", "3")
    sent = {}
    monkeypatch.setattr(execution_guard, "check_order", lambda r, **kw: {"allowed": True})
    monkeypatch.setattr(execution_ledger, "place_order", lambda req, **k: sent.update(req=req) or {
        "status": "submitted", "idempotency_key": execution_ledger.idempotency_key(req)})
    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [], enabled_fn=lambda: True)
    out = p(BOOKED)
    assert out["placed"] is True and "check_order" not in out and "idempotency_key" not in out  # paper doc shape kept
    (rec,) = live.read_decision_records(DAY)
    req = sent["req"]
    assert rec["idempotency_key"] == execution_ledger.idempotency_key(req) == out["key"]
    assert req.staked_probability_version == f"inplay:{ip.FAIR_VERSION}" == rec["staked_probability_version"]
    assert req.sizing_basis == "inplay_order_dollars" == rec["sizing"]["basis"]
    assert rec["fair"]["p"] == 0.38 and rec["fair"]["version"] == ip.FAIR_VERSION and rec["fair"]["n_books"] == 4
    assert rec["fair"]["rule"]["min_edge"] == ip.MIN_EDGE and rec["fair"]["rule"]["score_quiet_s"] == 180.0
    assert (rec["ask"], rec["leg"], rec["position_key"]) == (0.30, "yes", f"ingame:{ENTRY['ticker']}:yes")
    assert rec["sizing"]["version"] == live.SIZING_VERSION and rec["sizing"]["stake"] == 2.7901
    assert rec["sizing"]["contracts"] == 9 and rec["sizing"]["order_dollars"] == 3.0 and rec["sizing"]["day_cap"] == 50.0
    assert set(rec["guards"]) == {"band", "cell_gate", "ledger", "axis", "day_budget", "check_order"}
    assert rec["guards"]["band"] == {"verdict": "pass", "band": [0.20, 0.75]}
    assert rec["guards"]["cell_gate"] == {"verdict": "off"}
    assert rec["guards"]["check_order"] == {"verdict": "pass", "reason": None}
    assert rec["game"]["event_id"] == "oddsapi-ev-9" and rec["result"]["placed"] is True
    assert live.records_by_idempotency_key([DAY])[out["key"]]["decision_id"] == ENTRY["key"]


def test_a_refusal_records_every_guard_not_only_the_first(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_PRICE_BAND", "0.40,0.75")
    held = {"position_key": f"ingame:{ENTRY['ticker']}:yes", "venue_ticker": ENTRY["ticker"], "selected_date": DAY,
            "status": "filled", "fill_stake_dollars": 49.9}
    recs: list = []
    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [held], enabled_fn=lambda: True,
                             place_fn=lambda **kw: pytest.fail("placed a refusal"), record_fn=lambda d, r: recs.append(r))
    out = p(BOOKED)
    assert out["reason"] == "outside_price_band"  # the first refusal is still THE reason
    (rec,) = recs
    g = rec["guards"]
    assert [g[k]["verdict"] for k in ("band", "ledger", "axis", "day_budget")] == ["fail"] * 4
    assert g["check_order"] == {"verdict": "not_reached"} and rec["idempotency_key"] is None
    assert rec["sizing"]["basis"] == "inplay_one_contract" and rec["sizing"]["day_spend_before"] == 49.9


def test_off_writes_no_record_and_a_failed_write_never_raises(monkeypatch, tmp_path):
    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [], enabled_fn=lambda: False)
    p(BOOKED)
    assert live.read_decision_records(DAY) == []
    blocker = tmp_path / "file"
    blocker.write_text("x")
    live.append_decision_record(DAY, {"idempotency_key": "k"}, root=blocker)  # mkdir under a file fails: logged only
    assert live.read_decision_records(DAY, root=blocker) == []


def test_records_live_beside_the_pregame_records_and_web_may_read_them(tmp_path):
    from syndicate.features.shared import artifact_publisher as ap
    from syndicate.features.shared import decision_record as dr

    path = live.records_path(DAY)
    assert path.parent == dr.records_dir() and path.name == f"{DAY}.inplay.jsonl"
    rel = path.relative_to(tmp_path).as_posix()
    assert ap.is_exportable_artifact_relative_path(rel) and not ap.is_hot_artifact_relative_path(rel)
    path.parent.mkdir(parents=True)
    path.write_text('{"idempotency_key":"a","n":1}\n{torn\n{"idempotency_key":"a","n":2}\n', encoding="utf-8")
    assert live.records_by_idempotency_key([DAY])["a"]["n"] == 2  # last line wins; a torn line is skipped


def test_the_paper_booking_carries_the_fair_version(monkeypatch):
    from tests import test_inplay_entries_paper as tp

    monkeypatch.setenv("ODDS_API_KEY", "test-key-not-real")
    ts = [tp.T0, tp.T0 + 200, tp.T0 + 220]
    m = [tp._market(), tp._other()]
    loop, advance = tp._loop([m, m, m], [("in", ("1", "0"))], ts, [])
    for i in range(3):
        advance(i)
    (e,) = loop.doc["entries"].values()
    assert e["fair_version"] == ip.FAIR_VERSION
    assert live.order_provenance(e)["staked_probability_version"] == f"inplay:{ip.FAIR_VERSION}"


def test_the_gate_reading_script_reads_what_the_placer_writes():
    """scripts/inplay_decision_record_join.py is self-contained (it runs on older fleet checkouts): its reader must
    agree with the writer's path and format."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "inplay_join", Path(__file__).resolve().parents[1] / "scripts" / "inplay_decision_record_join.py")
    join = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(join)
    recs: list = []
    p = live.LiveEntryPlacer(today_fn=lambda: DAY, orders_fn=lambda: [], enabled_fn=lambda: True,
                             place_fn=lambda **kw: {"placed": True, "status": "submitted", "key": "ledger-key-1"})
    p(BOOKED)
    got = join.read_inplay_records(live.records_path(DAY).parent, DAY)
    assert set(got) == {"ledger-key-1"} and got["ledger-key-1"]["fair"]["version"] == ip.FAIR_VERSION
    assert join.phase({"submitted_at": "2026-10-22T23:50:00Z", "commence_time": "2026-10-22T23:00:00Z"}) == "in_play"
    assert join.phase({"submitted_at": "2026-10-22T22:50:00Z", "commence_time": "2026-10-22T23:00:00Z"}) == "pregame"
    assert join.phase({"submitted_at": "2026-10-22T22:50:00Z"}) == "in_play_no_commence"


def test_backfill_writes_a_joinable_record_once_and_only_for_placed_entries():
    """scripts/inplay_decision_record_backfill.py (user 2026-11-01 "Backfill them"): a placed paper entry becomes a
    record the gate reading joins on the ledger key; guards are marked inferred; a refusal and a re-run write nothing."""
    import importlib.util
    from pathlib import Path

    def load(name):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    bf, join = load("inplay_decision_record_backfill"), load("inplay_decision_record_join")
    placed = dict(BOOKED, day=DAY, live={"placed": True, "status": "submitted", "key": "ledger-key-9"})
    refused = dict(BOOKED, day=DAY, ticker="KXOTHER", live={"placed": False, "reason": "band"})
    orphan = dict(BOOKED, day=DAY, ticker="KXGONE", live={"placed": True, "key": "not-in-ledger"})
    entries = {"a": placed, "b": refused, "c": orphan}
    orders = {"ledger-key-9": {"idempotency_key": "ledger-key-9", "selected_date": DAY, "requested_stake_dollars": 2.5,
                               "position_key": "ingame:x:yes"}}
    todo, why = bf.plan(entries, orders, {}, record_version=live.RECORD_VERSION, backfilled_at="2026-11-01T00:00:00Z")
    assert why == {"write": 1, "no_ledger_row": 1, "day_mismatch": 0}
    (rec,) = todo[DAY]
    assert rec["guards"]["check_order"] == {"verdict": "pass_inferred"} and set(rec["guards"]) == set(bf.GUARDS)
    assert rec["backfill"]["ledger_row_edited"] is False and rec["sizing"]["stake"] == 2.5
    live.append_decision_record(DAY, rec)
    assert set(join.read_inplay_records(live.records_path(DAY).parent, DAY)) == {"ledger-key-9"}
    again, why2 = bf.plan(entries, orders, {DAY: {"ledger-key-9"}}, record_version=live.RECORD_VERSION,
                          backfilled_at="x")
    assert again == {} and why2["already_recorded"] == 1
