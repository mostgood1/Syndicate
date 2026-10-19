"""scripts/execution_watchdog.py -- every live-execution finding, the digest, and what gets emailed."""

from __future__ import annotations

import datetime as dt
import json

from scripts import execution_watchdog as xw
from scripts import local_watchdog as wd

NOW = dt.datetime(2026, 10, 19, 22, 0, tzinfo=dt.timezone.utc)
LIMITS = dict(xw.DEFAULTS)


def _iso(minutes_ago: float) -> str:
    return (NOW - dt.timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _healthy(**overrides):
    readings = {
        "execution_state": {"recorded_by": "live-odds-worker", "recorded_at": _iso(4), "execution_mode": "live",
                            "live_armed": True, "execution_enabled": True, "venue": "kalshi,polymarket",
                            "kill_switch": {"engaged": False, "source": "clear"}},
        "venue_balances": {"recorded_at": _iso(5), "venues": {
            "kalshi": {"status": "ok", "dollars": 485.48, "portfolio_value_dollars": 4.5},
            "polymarket": {"status": "ok", "dollars": 86.05, "buying_power_dollars": 86.05,
                           "detail": {"numbers": {"depositReservation": 0, "displayedAvailableSoon": 0}}}}},
        "kill_flag": None,
        "ledger_ok": True,
        "store_errors": [],
        "orders": [{"idempotency_key": "a1", "mode": "live", "venue": "kalshi", "status": "filled",
                    "submitted_at": _iso(60), "reconciled_at": _iso(3)}],
        "unknown_submits": [],
        "log_lines": [],
    }
    readings.update(overrides)
    return readings


def _keys(findings):
    return {f.key: f.severity for f in findings}


def _eval(readings, exec_state=None):
    return xw.evaluate(readings, NOW, LIMITS, exec_state or {})


def test_a_healthy_live_book_has_no_findings():
    findings, updates = _eval(_healthy())
    assert findings == [] and updates["log_holds"] == {}


def test_heartbeat_missing_or_old_is_a_fail():
    assert _keys(_eval(_healthy(execution_state=None))[0]) == {"exec:heartbeat": "fail", "exec:balance_stale": "fail"} \
        or "exec:heartbeat" in _keys(_eval(_healthy(execution_state=None))[0])
    state = dict(_healthy()["execution_state"], recorded_at=_iso(40))
    assert _keys(_eval(_healthy(execution_state=state))[0]) == {"exec:heartbeat": "fail"}
    state = dict(state, recorded_at=_iso(20))
    assert _eval(_healthy(execution_state=state))[0] == []


def test_kill_switch_engaged_alerts_with_its_source():
    state = dict(_healthy()["execution_state"], kill_switch={"engaged": True, "source": "flag", "detail": "drawdown"})
    findings, _ = _eval(_healthy(execution_state=state))
    assert _keys(findings) == {"exec:kill_switch": "fail"} and "source=flag" in findings[0].message
    # A flag the worker has not stamped yet is still caught.
    findings, _ = _eval(_healthy(kill_flag={"engaged": True, "reason": "manual", "set_at": _iso(1)}))
    assert _keys(findings) == {"exec:kill_switch": "fail"}


def test_unreconciled_only_after_n_minutes_and_only_live():
    young = {"idempotency_key": "s1", "mode": "live", "venue": "kalshi", "status": "submitted", "submitted_at": _iso(5)}
    old = dict(young, idempotency_key="s2", submitted_at=_iso(90), reconciled_at=_iso(25))
    paper = dict(old, idempotency_key="s3", mode="paper:kalshi")
    resting_fresh = dict(old, idempotency_key="s4", reconciled_at=_iso(2))
    findings, _ = _eval(_healthy(orders=[young, old, paper, resting_fresh]))
    assert _keys(findings) == {"exec:unreconciled": "fail"}
    assert "s2" in findings[0].message and "s1" not in findings[0].message and "s3" not in findings[0].message


def test_balance_stale_status_low_and_pending_deposit():
    bal = _healthy()["venue_balances"]
    findings, _ = _eval(_healthy(venue_balances=dict(bal, recorded_at=_iso(45))))
    assert _keys(findings) == {"exec:balance_stale": "fail"}

    venues = json.loads(json.dumps(bal["venues"]))
    venues["kalshi"] = {"status": "auth_error", "detail": "http_401"}
    venues["polymarket"]["buying_power_dollars"] = 12.0
    findings, _ = _eval(_healthy(venue_balances=dict(bal, venues=venues)))
    assert _keys(findings) == {"exec:balance_status:kalshi": "fail", "exec:balance_low:polymarket": "fail"}

    venues = json.loads(json.dumps(bal["venues"]))
    venues["polymarket"].update(buying_power_dollars=586.05, detail={"numbers": {"depositReservation": 500.0}})
    findings, _ = _eval(_healthy(venue_balances=dict(bal, venues=venues)))
    assert _keys(findings) == {"exec:pending_deposit": "warn"} and "$500.00" in findings[0].message


def test_balance_threshold_is_overridable(tmp_path):
    (tmp_path / "alerts.env").write_text("SYNDICATE_ALERT_MIN_BALANCE_KALSHI=500\n", encoding="utf-8")
    limits = xw.thresholds(tmp_path)
    assert limits["min_balance_kalshi"] == 500 and limits["min_balance_polymarket"] == xw.DEFAULTS["min_balance_polymarket"]
    findings, _ = xw.evaluate(_healthy(), NOW, limits, {})
    assert _keys(findings) == {"exec:balance_low:kalshi": "fail"}


def test_unknown_submit_definition_and_alert():
    base = {"mode": "live", "venue": "polymarket", "status": "failed", "submitted_at": _iso(30),
            "requested_stake_dollars": 1.84, "error": 'http_503 {"code":14}'}
    rows = [dict(base, idempotency_key="u1"),
            dict(base, idempotency_key="r4xx", error="http_400 bad"),           # venue refused: not a position
            dict(base, idempotency_key="has_id", venue_order_id="o-1"),
            dict(base, idempotency_key="resolved", operator_resolution={"finding": "placed"}),
            dict(base, idempotency_key="paper", mode="paper:polymarket")]
    unknown = xw.unknown_submits(rows)
    assert [o["idempotency_key"] for o in unknown] == ["u1"]
    findings, _ = _eval(_healthy(orders=rows, unknown_submits=unknown,
                                 balance_evidence={"u1": {"verdict": "not_placed", "reason": "balance_unchanged_across_submit"}}))
    assert _keys(findings) == {"exec:unknown_submits": "fail"}
    assert "$1.84" in findings[0].message and "not_placed" in findings[0].message


def test_log_bursts_alert_and_are_held_so_one_incident_is_one_alert():
    lines = [f"2026-10-19T21:5{i}:00.000Z [execution_ledger] RECONCILE_READ_FAILED venue=kalshi candidates=1 reason=http_503"
             for i in range(3)]
    findings, updates = _eval(_healthy(log_lines=lines))
    assert _keys(findings) == {"exec:log_errors:orders:kalshi": "fail"}
    # Next check: no new lines, but the hold keeps it active (no CLEARED/NEW flapping).
    later = NOW + dt.timedelta(minutes=10)
    findings, updates = xw.evaluate(_healthy(), later, LIMITS, updates)
    assert "exec:log_errors:orders:kalshi" in _keys(findings)
    findings, updates = xw.evaluate(_healthy(), NOW + dt.timedelta(minutes=31), LIMITS, updates)
    assert not any(k.startswith("exec:log_errors") for k in _keys(findings)) and updates["log_holds"] == {}
    # Two lines is below the threshold.
    assert _eval(_healthy(log_lines=lines[:2]))[0] == []


def test_adapter_prefixes_are_matched():
    hits = xw.log_hits([
        "[kalshi_orders] SUBMIT_FAILED_MARKET ticker=X",
        "[polymarket_us_orders] ORDERS_READ_ALL_FAILED n=2 errors=[...]",
        "[live_odds_worker] EXECUTION_ERROR KeyError: x",
        "[kalshi_orders] ORDERS_READ n=11",                                   # a healthy read is not a failure
        "[execute_portfolio] LIVE_ORDER status=failed venue=polymarket ticker=t",
    ])
    assert set(hits) == {"kalshi", "polymarket", "tick", "orders:polymarket"}


def test_store_failure_is_loud_not_quiet():
    findings, _ = _eval({"monitor_error": "ConnectionError: redis down", "log_lines": []})
    assert _keys(findings) == {"exec:monitor": "fail"}
    findings, _ = _eval(_healthy(store_errors=["execution_state.json"], execution_state=None))
    assert "exec:monitor" in _keys(findings) and "exec:heartbeat" not in _keys(findings)


def test_scan_log_follows_rotation_and_never_splits_a_line(tmp_path):
    log = tmp_path / "live-odds-worker.log"
    log.write_text("old line\n", encoding="utf-8")
    lines, cursor = xw.scan_log(log, None)
    assert lines == [] and cursor["offset"] == log.stat().st_size      # first run starts at EOF
    with log.open("a", encoding="utf-8") as h:
        h.write("a\nb\npartial")
    lines, cursor = xw.scan_log(log, cursor)
    assert lines == ["a", "b"]
    with log.open("a", encoding="utf-8") as h:
        h.write(" done\nc\n")
    log.rename(tmp_path / "live-odds-worker.log.1")
    log.write_text("d\n", encoding="utf-8")
    lines, cursor = xw.scan_log(log, cursor)
    assert lines == ["partial done", "c", "d"]


def test_digest_accumulates_refusals_per_tick_and_reports_pnl():
    tick = ("2026-10-19T{t}.000Z [live_odds_worker] EXECUTION status=ok reason=None mode=live venue=kalshi "
            "scope=kalshi placed=0 duplicates=0 refused={{'over_max_order_dollars': 1}} spent={{'dollars': 4.53}} limits={{}}")
    acc = xw.accumulate([tick.format(t="20:00:00"), tick.format(t="20:05:00")], {}, NOW)
    day = acc["2026-10-19"]
    assert day["ticks"] == {"live:kalshi": {"ok": 2}}
    assert day["refusals"] == {"kalshi:over_max_order_dollars": {"ticks": 2, "max": 1}}

    orders = [{"mode": "live", "venue": "kalshi", "status": "filled", "submitted_at": "2026-10-19T18:00:00Z",
               "fill_stake_dollars": 4.53, "fees_dollars": 0.03, "outcome": "won", "graded_at": "2026-10-19T23:30:00Z",
               "pnl_dollars": 0.47}]
    subject, body, snap = xw.build_digest(dt.date(2026, 10, 19), orders, _healthy(), day, {}, NOW, {"kalshi": 480.0})
    assert "+$0.47" in subject and "W1-L0-P0" in body and "over_max_order_dollars: 2 ticks" in body
    assert "+$5.48 since last digest" in body and snap["kalshi"] == 485.48


def test_digest_due_once_a_day_after_the_hour():
    morning = dt.datetime(2026, 10, 20, 12, 30, tzinfo=dt.timezone.utc)      # 7:30 AM CDT
    assert xw.digest_due(morning, {}, 8) is None
    after = dt.datetime(2026, 10, 20, 13, 5, tzinfo=dt.timezone.utc)         # 8:05 AM CDT
    assert xw.digest_due(after, {}, 8) == dt.date(2026, 10, 19)
    assert xw.digest_due(after, {"last_digest_day": "2026-10-19"}, 8) is None


def test_emailed_are_exec_findings_and_fleet_fails_not_fleet_warns():
    findings = [wd.Finding("exec:kill_switch", "fail", "engaged"), wd.Finding("role:live-odds-worker", "fail", "dead"),
                wd.Finding("job:ci-suite", "warn", "rc=1"), wd.Finding("exec:pending_deposit", "warn", "$500")]
    result, new_state = wd.decide(findings, {}, NOW)
    messages = xw.email_messages(findings, {}, new_state["active"], result, NOW)
    assert len(messages) == 1
    body = messages[0]["body"]
    assert "exec:kill_switch" in body and "role:live-odds-worker" in body and "exec:pending_deposit" in body
    assert "job:ci-suite" not in body and messages[0]["subject"].startswith("ALERT")
    # Next check, same findings: decide() dedupes, so nothing is emailed.
    result2, state2 = wd.decide(findings, new_state, NOW + dt.timedelta(minutes=5))
    assert xw.email_messages(findings, new_state["active"], state2["active"], result2, NOW) == []
    # Cleared: one email saying so.
    result3, state3 = wd.decide([], state2, NOW + dt.timedelta(minutes=10))
    cleared = xw.email_messages([], state2["active"], state3["active"], result3, NOW)
    assert cleared and cleared[0]["subject"].startswith("cleared") and "job:ci-suite" not in cleared[0]["body"]


def test_run_never_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(xw, "collect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    findings, exec_state, readings = xw.run(xw.lp.Settings(home=tmp_path), NOW, {})
    assert _keys(findings) == {"exec:monitor": "fail"} and readings == {}


def test_watchdog_main_wires_execution_and_email(monkeypatch, tmp_path):
    """Reachability: the hook in local_watchdog.main runs the execution checks and hands email to the mailer."""
    calls = {}

    def fake_run(settings, now, state):
        return [wd.Finding("exec:kill_switch", "fail", "engaged")], {"log_cursor": {"offset": 1}}, {}

    def fake_deliver(settings, messages, now, sender=None):
        calls["messages"] = messages
        return {"sent": [{"kind": "alert"}], "failed": [], "queued": 0, "held": 0, "enabled": True, "reason": ""}

    from scripts import alert_mailer

    monkeypatch.setattr(xw, "run", fake_run)
    monkeypatch.setattr(alert_mailer, "deliver", fake_deliver)
    monkeypatch.setattr(wd, "collect", lambda settings, now: {"pidfile_present": False})
    rc = wd.main(["--home", str(tmp_path), "--json"])
    assert rc == 1
    assert any("exec:kill_switch" in m["body"] for m in calls["messages"])
    state = json.loads((tmp_path / "run" / wd.STATE_NAME).read_text(encoding="utf-8"))
    assert "exec:kill_switch" in state["active"] and state["execution"]["log_cursor"] == {"offset": 1}
    # Off switch: no execution checks, no email.
    calls.clear()
    monkeypatch.setenv("SYNDICATE_WATCHDOG_EXECUTION", "0")
    wd.main(["--home", str(tmp_path / "b"), "--json"])
    assert calls == {}
