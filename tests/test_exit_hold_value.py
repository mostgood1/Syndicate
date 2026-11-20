"""Hold-value exits (todo #856, lane hold-value-exits): the switch, the gate, the shadow, the grade."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from syndicate.features.shared import execution_exits as ex
from syndicate.features.shared import exit_hold_value as hv
from syndicate.features.shared import kalshi_maker_pilot as pilot

NOW = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
TODAY = "2026-11-20"
TICKER = "KXNBATOTAL-26NOV20MINCLE-220"
GAME = "2026-11-21T01:00:00Z"  # 7 hours after NOW: pregame


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    for name in (
        "SYNDICATE_EXIT_MODE",
        "SYNDICATE_EXIT_LIVE_ARMED",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_KILL_SWITCH",
        "SYNDICATE_EXIT_TAKE_PROFIT_MARGIN",
        "SYNDICATE_EXIT_FAIR_MARGIN",
        "SYNDICATE_EXIT_LIVE_PHASES",
        "SYNDICATE_EXIT_HOLD_AT_OR_ABOVE_BID",
        hv.MODE_ENV,
        hv.MAX_FAIR_AGE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    hv._PAPER_LOGGED.clear()
    pilot._seen.clear()
    yield
    pilot._seen.clear()
    hv._PAPER_LOGGED.clear()


def _order(**overrides):
    base = {
        "idempotency_key": "b" * 24,
        "mode": "live",
        "venue": "kalshi",
        "venue_ticker": TICKER,
        "status": "filled",
        "outcome": None,
        "selected_date": TODAY,
        "commence_time": GAME,
        "event_id": "evt-mincle",
        "sport": "nba",
        "market": "totals",
        "side": "over",
        "line": 220.5,
        "requested_price": 0.50,
        "requested_stake_dollars": 5.0,
        "fill_price": 0.50,
        "fill_stake_dollars": 5.0,  # 10 contracts
        "fees_dollars": 0.0875,
        "model_edge_pct": None,
        "ev_pct": None,
    }
    base.update(overrides)
    return base


def _market(**overrides):
    base = {
        "ticker": TICKER,
        "status": "active",
        "yes_bid_dollars": "0.7000",
        "yes_ask_dollars": "0.7200",
        "no_bid_dollars": "0.2800",
        "no_ask_dollars": "0.3000",
        "yes_bid_size_fp": "100.00",
        "yes_ask_size_fp": "80.00",
    }
    base.update(overrides)
    return base


def _position(**overrides):
    positions, _ = ex.open_positions([_order(**overrides)], today=TODAY)
    assert len(positions) == 1
    return positions[0]


def _decide(position=None, market=None, now=NOW):
    return ex.evaluate_exit(position or _position(), market or _market(), margin=0.08, fair_buffer=0.0, now=now)


def _sighting(fair, age_s=60.0, ticker=TICKER, leg="yes"):
    pilot._seen[f"{ticker}|{leg}"] = {"fair": fair, "at": NOW.timestamp() - age_s}


# The decision's keys before the switch existed, pinned: absent must not add one.
_TODAY_KEYS = {
    "entry_key", "ticker", "leg", "mode", "in_play", "rule", "reason", "bid", "bid_size", "exit_fee_dollars",
    "net_per_contract", "entry_cost_per_contract", "edge_per_contract", "fair", "fair_source", "margin",
}


# -- the switch --------------------------------------------------------------


@pytest.mark.parametrize("raw,mode", [
    (None, "off"), ("", "off"), ("off", "off"), ("1", "off"), ("true", "off"), ("shadw", "off"),
    ("shadow", "shadow"), (" Shadow ", "shadow"), ("on", "on"), ("ON", "on"),
])
def test_only_the_exact_words_reach_shadow_or_on(monkeypatch, raw, mode):
    if raw is not None:
        monkeypatch.setenv(hv.MODE_ENV, raw)
    assert hv.hold_value_mode() == mode


def test_the_rule_name_is_execution_exits_own():
    assert hv._RULE_TAKE_PROFIT == ex.RULE_TAKE_PROFIT


def test_max_fair_age_default_and_bad_values(monkeypatch):
    assert hv.max_fair_age_seconds() == 1800.0
    for bad in ("x", "-5", "nan", "inf"):
        monkeypatch.setenv(hv.MAX_FAIR_AGE_ENV, bad)
        assert hv.max_fair_age_seconds() == 1800.0
    monkeypatch.setenv(hv.MAX_FAIR_AGE_ENV, "600")
    assert hv.max_fair_age_seconds() == 600.0


# -- absent = today; shadow = today's decisions; on != off -------------------


def test_absent_is_todays_decision_exactly(monkeypatch):
    absent = _decide()
    assert set(absent) == _TODAY_KEYS
    assert absent["rule"] == "take_profit" and absent["reason"] == "triggered"
    for off_text in ("off", "garbage"):
        monkeypatch.setenv(hv.MODE_ENV, off_text)
        assert _decide() == absent


def test_shadow_keeps_todays_decision_and_only_adds_the_assessment(monkeypatch):
    absent = _decide()
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    shadow = _decide()
    assessment = shadow.pop("hold_value")
    assert shadow == absent
    assert assessment["today_rule"] == "take_profit"
    assert assessment["source"] == "venue_mid" and assessment["hold"] == 0.71
    assert assessment["would_exit"] is False and assessment["gated"] is False


def test_on_differs_from_off_where_holding_is_worth_more(monkeypatch):
    off = _decide()
    monkeypatch.setenv(hv.MODE_ENV, "on")
    on = _decide()
    assert off["rule"] == "take_profit"
    assert on["rule"] is None and on["reason"] == hv.REASON_HOLD
    assert on["hold_value"]["gated"] is True
    # Everything today's rules read is unchanged: only the rule and its reason move.
    for key in ("bid", "net_per_contract", "edge_per_contract", "exit_fee_dollars", "entry_cost_per_contract"):
        assert on[key] == off[key]


def test_on_keeps_take_profit_when_a_fresh_pregame_consensus_says_the_bid_is_rich(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "on")
    _sighting(0.60)
    on = _decide()
    a = on["hold_value"]
    assert a["source"] == "consensus" and a["hold"] == 0.60 and a["consensus_age_s"] == 60.0
    assert a["hv_edge"] > a["threshold"] and a["would_exit"] is True
    assert on["rule"] == "take_profit" and on["reason"] == "triggered"


def test_consensus_is_not_a_hold_value_in_play_or_when_stale(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "on")
    _sighting(0.60)
    in_play = _decide(_position(commence_time="2026-11-20T17:00:00Z"))
    assert in_play["in_play"] is True and in_play["hold_value"]["source"] == "venue_mid"
    assert in_play["rule"] is None
    _sighting(0.60, age_s=4000)
    stale = _decide()
    assert stale["hold_value"]["source"] == "venue_mid" and stale["rule"] is None
    monkeypatch.setenv(hv.MAX_FAIR_AGE_ENV, "5000")
    assert _decide()["hold_value"]["source"] == "consensus"


def test_model_fair_is_untouched_by_the_gate(monkeypatch):
    # ev_pct / model_edge_pct give a model view of 0.60: model_fair fires beside take_profit.
    position = _position(ev_pct=0.0, model_edge_pct=10.0)
    assert position.model_probability == 0.6
    off = _decide(position)
    assert off["rule"] == "take_profit+model_fair"
    monkeypatch.setenv(hv.MODE_ENV, "on")
    on = _decide(position)
    assert on["rule"] == "model_fair" and on["reason"] == "triggered"


def test_the_venue_mid_never_clears_the_bid():
    """The structural invariant the grade checks as I1: a mid hold value never sells."""
    position = _position()
    for bid_c in range(2, 97):
        for spread_c in (0, 1, 2, 5, 20):
            bid, ask = bid_c / 100, min(0.99, (bid_c + spread_c) / 100)
            market = _market(yes_bid_dollars=f"{bid:.4f}", yes_ask_dollars=f"{ask:.4f}")
            fee = ex.estimate_fee(position.family, position.ticker, position.contracts, bid)
            a = hv.assess(position, market, bid=bid, exit_fee=fee, net=bid - fee / position.contracts,
                          in_play=False, now=NOW, today_rules=["take_profit"], sighting_fn=lambda t, l: None)
            assert a["source"] == "venue_mid" and a["would_exit"] is False


def test_an_unknown_hold_value_never_sells(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "on")
    one_sided = _market(yes_ask_dollars=None, no_bid_dollars=None)
    on = _decide(market=one_sided)
    assert on["hold_value"]["source"] == "none" and on["hold_value"]["hold"] is None
    assert on["rule"] is None and on["reason"] == hv.REASON_HOLD


def test_the_ask_falls_back_to_one_minus_the_other_bid():
    assert hv.leg_ask(_market(), "yes") == 0.72
    assert hv.leg_ask(_market(yes_ask_dollars=None), "yes") == 0.72
    assert hv.leg_ask({"yes_bid_dollars": 0.4, "no_bid_dollars": 0.55}, "no") == 0.6
    assert hv.leg_ask({"yes_bid_dollars": 0.4}, "no") == 0.6
    assert hv.leg_ask({"no_bid_dollars": 0.55}, "no") is None  # no ask, no YES bid: unknown


def test_the_consensus_is_the_pilots_own_plan_sighting():
    """Reachability across the module boundary: the executor's writer feeds this reader."""
    request = SimpleNamespace(venue_ticker=TICKER, side="over", market="totals", line=220.5,
                              requested_price=0.55, ev_pct=100.0 * (0.60 / 0.55 - 1.0))
    pilot.note_plan_sighting(request, now=NOW - timedelta(seconds=30))
    seen = hv.consensus_sighting(TICKER, "yes")
    assert seen is not None and seen["fair"] == 0.6 and seen["at"] == (NOW - timedelta(seconds=30)).timestamp()
    assert hv.consensus_sighting(TICKER, "no") is None


# -- the tick: shadow rows, summary, the EXIT_TICK line; off writes nothing ---


def _quotes(markets):
    return lambda tickers: {"markets": {m["ticker"]: m for m in markets if m["ticker"] in tickers}, "errors": []}


def _venue():
    return {"status": "ok", "positions": {TICKER: 10.0}}


def _tick(orders=None, market=None, **kw):
    return ex.run_exit_tick(today=TODAY, orders=orders or [_order()], quotes=_quotes([market or _market()]),
                            venue_positions=_venue, now=NOW, **kw)


def _shadow_rows():
    return hv.read_shadow_rows()


def test_absent_tick_writes_no_shadow_and_adds_no_summary_key(monkeypatch):
    monkeypatch.setattr(ex, "_utc_now", lambda: "2026-11-20T18:00:00Z")
    summary = _tick()
    assert "hold_value" not in summary
    assert "hold_value=" not in ex.exit_tick_line(summary)
    assert not hv.shadow_dir().exists()
    assert summary["new_paper_exits"] == 1


def test_shadow_tick_changes_nothing_in_the_document(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "_utc_now", lambda: "2026-11-20T18:00:00Z")
    _tick()
    absent_doc = json.loads(ex.exits_path().read_text(encoding="utf-8"))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "shadow_root"))
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    _tick()
    shadow_doc = json.loads(ex.exits_path().read_text(encoding="utf-8"))
    assert shadow_doc["last_tick"].pop("hold_value")["rows"] == 1
    assert shadow_doc == absent_doc


def test_shadow_tick_logs_the_live_position_with_todays_rule(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    summary = _tick()
    assert summary["new_paper_exits"] == 1  # today's paper exit still books
    rows = _shadow_rows()
    assert len(rows) == 1
    row = rows[0]
    # Explicit `orders` is how the fast loop dispatches, so the row says so; the worker's own
    # tick (orders read from the ledger) is `slow` (test_the_worker_exit_tick_reaches_the_shadow).
    assert row["entry_key"] == "b" * 24 and row["entry_mode"] == "live" and row["tick"] == "dispatch"
    assert row["today_rule"] == "take_profit" and row["rule"] == "take_profit"
    assert row["hold_source"] == "venue_mid" and row["would_exit"] is False and row["gated"] is False
    assert row["bid"] == 0.70 and row["mid"] == 0.71 and row["hold"] == 0.71
    assert summary["hold_value"]["today_take_profit"] == 1 and summary["hold_value"]["held"] == 1
    assert summary["hold_value"]["by_source"] == {"venue_mid": 1}
    assert "hold_value=" in ex.exit_tick_line(summary)


def test_on_tick_books_no_take_profit_exit_where_off_books_one(monkeypatch):
    """off != on at the tick: today's first trigger books a paper exit; the gate holds it."""
    monkeypatch.setenv(hv.MODE_ENV, "on")
    summary = _tick()
    assert summary["new_paper_exits"] == 0
    assert summary["reasons"] == {hv.REASON_HOLD: 1}
    assert summary["hold_value"]["gated"] == 1
    row = _shadow_rows()[0]
    assert row["today_rule"] == "take_profit" and row["rule"] is None and row["gated"] is True


def test_a_dispatched_pass_is_marked_dispatch(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    ex.run_exit_tick(today=TODAY, orders=[_order()], quotes=_quotes([_market()]), venue_positions=_venue, now=NOW)
    assert _shadow_rows()[0]["tick"] == "dispatch"


def test_paper_positions_log_only_their_first_trigger_state(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    paper = _order(idempotency_key="c" * 24, mode="paper", venue="paper:kalshi")
    quiet = _order(idempotency_key="d" * 24, mode="paper", venue="paper:kalshi", fill_price=0.69,
                   requested_price=0.69, fill_stake_dollars=6.9)
    for _ in range(3):
        _tick(orders=[paper, quiet])
    keys = [r["entry_key"] for r in _shadow_rows()]
    assert keys == ["c" * 24]  # once, and the paper position below threshold never


def test_a_raising_assessment_keeps_todays_rule_in_shadow_and_holds_when_on(monkeypatch):
    monkeypatch.setattr(hv, "assess", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad book")))
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    shadow = _decide()
    assert shadow["rule"] == "take_profit" and shadow["hold_value"]["error"] == "ValueError: bad book"
    monkeypatch.setenv(hv.MODE_ENV, "on")
    on = _decide()
    assert on["rule"] is None and on["reason"] == hv.REASON_HOLD


def test_a_raising_observe_never_breaks_the_tick(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    monkeypatch.setattr(hv.ShadowTick, "_observe", lambda self, p, d: (_ for _ in ()).throw(KeyError("x")))
    summary = _tick()
    assert summary["status"] == "ok" and summary["new_paper_exits"] == 1
    assert summary["hold_value"]["observe_errors"] == 1


def test_a_shadow_write_failure_never_breaks_the_tick(monkeypatch):
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    monkeypatch.setattr(hv, "shadow_dir", lambda: (_ for _ in ()).throw(OSError("disk")))
    summary = _tick()
    assert summary["status"] == "ok" and summary["hold_value"]["rows"] == 0
    assert "OSError" in summary["hold_value"]["write_error"]


# -- the worker tick and the fast loop reach the gate ------------------------


def test_the_worker_exit_tick_reaches_the_shadow(monkeypatch, capsys):
    import importlib

    from syndicate.features.shared.timezone import central_today_iso

    worker = importlib.import_module("scripts.run_live_odds_refresh_worker")
    today = central_today_iso()
    game = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    orders = [_order(selected_date=today, commence_time=game)]
    monkeypatch.setattr("syndicate.features.shared.execution_ledger._load", lambda: {"orders": orders})
    monkeypatch.setattr(ex, "fetch_quotes", _quotes([_market()]))
    monkeypatch.setattr(ex, "fetch_venue_positions", _venue)
    worker._exit_tick(today)
    assert "hold_value=" not in capsys.readouterr().out
    assert not hv.shadow_dir().exists()
    monkeypatch.setenv(hv.MODE_ENV, "shadow")
    worker._exit_tick(today)
    out = capsys.readouterr().out
    assert "EXIT_TICK status=ok" in out and "hold_value={'mode': 'shadow', 'rows': 1" in out
    rows = _shadow_rows()
    assert len(rows) == 1 and rows[0]["tick"] == "slow" and rows[0]["today_rule"] == "take_profit"


def test_the_fast_loop_obeys_the_gate(monkeypatch):
    from syndicate.features.shared import execution_exits_fast as fast

    in_play = _position(commence_time="2026-11-20T17:00:00Z")
    quotes = {"markets": {TICKER: _market()}, "errors": []}
    off = fast.mark_pass(fast._empty(), [in_play], quotes, slow_watch={}, now=NOW)
    assert off["triggered"] == [("b" * 24, "take_profit", "live")]
    monkeypatch.setenv(hv.MODE_ENV, "on")
    on = fast.mark_pass(fast._empty(), [in_play], quotes, slow_watch={}, now=NOW)
    assert on["triggered"] == [] and on["reasons"] == {hv.REASON_HOLD: 1}


# -- the grade (pre-registered rule, findings s2.3) ---------------------------


def _row(key, at, *, today_rule="take_profit", would=False, net=0.70, source="venue_mid", mode="live",
         commence="2026-11-22T01:00:00Z", phase="pregame", family="kalshi", ticker="KXT-1-A"):
    return {"entry_key": key, "at": at, "tick": "slow", "entry_mode": mode, "family": family, "entry_phase": phase,
            "commence_time": commence, "contracts": 10.0, "ticker": ticker, "today_rule": today_rule,
            "would_exit": would, "net": net, "hold_source": source, "hv_edge": (0.05 if would else -0.01),
            "in_play": False}


def _grading_fixture(c_outcome="lost"):
    rows = [
        _row("A", "2026-11-25T00:00:00Z", today_rule=None),
        _row("A", "2026-11-25T00:05:00Z", net=0.70),
        _row("B", "2026-11-25T00:05:00Z", net=0.65),
        _row("B", "2026-11-25T00:10:00Z", net=0.72, would=True, source="consensus"),
        _row("C", "2026-11-26T00:05:00Z", net=0.60, commence="2026-11-27T01:00:00Z"),
        _row("D", "2026-11-25T00:05:00Z", net=0.80, would=True, source="consensus"),  # agrees: not in P
        _row("E", "2026-11-25T00:05:00Z", mode="paper"),  # paper: S3 only
    ]
    orders = [
        {"idempotency_key": "A", "outcome": "won", "event_id": "E1"},
        {"idempotency_key": "B", "outcome": "won", "event_id": "E1"},
        {"idempotency_key": "C", "outcome": c_outcome, "event_id": "E2"},
        {"idempotency_key": "D", "outcome": "won", "event_id": "E3"},
        {"idempotency_key": "E", "outcome": "won", "event_id": "E4"},
    ]
    return rows, orders


def test_grade_reproduces_the_hand_computed_exit_minus_hold():
    rows, orders = _grading_fixture()
    report = hv.grade_shadow(rows, orders, min_events=1, min_positions=1)
    by_key = {p["entry_key"]: p["emh_pp"] for p in report["positions"]}
    # A: sold 0.70, held to a win (1.0) -> -30. B: sold 0.65, the rule sells later at 0.72 -> -7.
    # C: sold 0.60, held to a loss (0.0) -> +60.
    assert by_key == {"A": -30.0, "B": -7.0, "C": 60.0}
    m = 23.0 / 3.0
    se = math.sqrt((((-30 - m) + (-7 - m)) ** 2 + (60 - m) ** 2)) / 3 * math.sqrt(2 / 1)
    p = report["primary"]
    assert p["n"] == 3 and p["events"] == 2
    assert p["mean"] == round(m, 4) and p["se"] == round(se, 4)
    assert p["lo"] == round(m - 1.96 * se, 4) and p["hi"] == round(m + 1.96 * se, 4)
    assert report["verdict"] == "AGAINST"
    s = report["secondary"]
    assert s["S1_first_take_profit_fires"] == 4 and s["S1_held_at_t1"] == 3
    assert s["S3_paper"]["n"] == 1 and s["S3_paper"]["mean"] == -30.0


def test_grade_support_strong_when_every_lodo_and_the_ci_are_below_zero():
    rows, orders = _grading_fixture(c_outcome="won")
    report = hv.grade_shadow(rows, orders, min_events=1, min_positions=1)
    assert report["primary"]["mean"] == round(-77.0 / 3.0, 4)
    assert report["primary"]["lodo"] == {"2026-11-21": -40.0, "2026-11-26": -18.5}
    assert report["verdict"] == "SUPPORT (STRONG)"


def test_grade_insufficient_below_the_registered_minimum():
    rows, orders = _grading_fixture(c_outcome="won")
    assert hv.grade_shadow(rows, orders)["verdict"] == "INSUFFICIENT"


def test_grade_invalid_when_a_mid_row_would_exit():
    rows, orders = _grading_fixture(c_outcome="won")
    rows.append(_row("Z", "2026-11-25T00:20:00Z", would=True, source="venue_mid"))
    report = hv.grade_shadow(rows, orders, min_events=1, min_positions=1)
    assert report["instrument"]["I1_mid_rows_that_would_exit"] == 1 and report["verdict"] == "INVALID"


def test_grade_invalid_when_a_live_sale_has_no_shadow_row():
    rows, orders = _grading_fixture(c_outcome="won")
    sales = [
        {"entry_key": "A", "mode": "live", "rule": "take_profit", "submitted_at": "2026-11-25T00:05:20Z"},
        {"entry_key": "Q", "mode": "live", "rule": "take_profit", "submitted_at": "2026-11-25T01:00:00Z"},
    ]
    report = hv.grade_shadow(rows, orders, sales, min_events=1, min_positions=1)
    assert report["instrument"]["I2_sales_with_a_shadow_row"] == 1 and report["instrument"]["I2_share"] == 0.5
    assert report["verdict"] == "INVALID"


def test_grade_excludes_ungraded_and_games_after_the_window():
    rows, orders = _grading_fixture(c_outcome="won")
    rows.append(_row("F", "2026-11-25T00:05:00Z"))  # no ledger row
    rows.append(_row("G", "2026-12-07T00:05:00Z", commence="2026-12-08T01:00:00Z"))  # game 12-07 CST
    report = hv.grade_shadow(rows, orders, min_events=1, min_positions=1)
    assert report["excluded"]["live"] == {"no_ledger_row": 1, "game_after_window_or_undated": 1}
    assert report["primary"]["n"] == 3


def test_the_grader_script_runs_on_files(tmp_path, capsys):
    import importlib

    rows, orders = _grading_fixture(c_outcome="won")
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "shadow_2026-11-25.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"orders": orders}), encoding="utf-8")
    exits = tmp_path / "exits.json"
    exits.write_text(json.dumps({"exits": {}}), encoding="utf-8")
    script = importlib.import_module("scripts.exit_hold_value_shadow_grade")
    rc = script.main(["--shadow-dir", str(shadow), "--ledger-json", str(ledger), "--exits-json", str(exits),
                      "--min-events", "1", "--min-positions", "1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["verdict"] == "SUPPORT (STRONG)" and out["primary"]["n"] == 3
