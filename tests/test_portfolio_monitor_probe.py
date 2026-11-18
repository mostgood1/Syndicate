"""The portfolio monitor's readings are pure functions over the payloads and log lines it reads."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import portfolio_monitor_probe as pm  # noqa: E402

NOW = dt.datetime(2026, 11, 17, 16, 0, tzinfo=dt.timezone.utc)


def _order(**kw):
    base = {"mode": "live", "status": "filled", "selected_date": "2026-11-17", "venue": "kalshi", "sport": "nba",
            "outcome": None, "commence_time": "2026-11-18T00:00:00Z", "submitted_at": "2026-11-17T15:00:00Z",
            "fill_stake_dollars": 5.0, "requested_stake_dollars": 5.0}
    base.update(kw)
    return base


def test_parse_ts_takes_nanoseconds_and_offsets():
    assert pm.parse_ts("2026-11-17T06:12:20.279449123Z") == dt.datetime(2026, 11, 17, 6, 12, 20, 279449,
                                                                          tzinfo=dt.timezone.utc)
    assert pm.parse_ts("2026-11-17T10:13:23-06:00").utcoffset() == dt.timedelta(hours=-6)
    assert pm.parse_ts("") is None and pm.parse_ts("garbage") is None


def test_banner_names_the_bad_field_and_stale_state():
    live = {"health": {"ok": False, "armed": True, "job": False, "mode": True}, "state_age_seconds": 901,
            "stale_after_seconds": 900, "kill_switch": {"engaged": False}}
    b = pm.banner(live)
    assert b["ok"] is False and b["bad_fields"] == ["job"] and b["state_stale"] is True
    assert any("BANNER not ok: job" in a for a in pm.anomalies({"banner": b}))


def test_order_flow_counts_today_only_and_resting_age():
    orders = [_order(), _order(status="rejected"), _order(status="submitted", submitted_at="2026-11-17T12:00:00Z"),
              _order(selected_date="2026-11-16", status="failed")]
    f = pm.order_flow(orders, "2026-11-17", NOW)
    assert f["orders"] == 3 and f["failed_or_rejected"] == 1 and f["resting"] == 1
    assert f["resting_age_min"] == [240.0]
    found = pm.anomalies({"orders_today": f})
    assert "ORDERS failed or rejected today: 1/3 (33.3%)" in found
    assert any(a.startswith("ORDERS resting order") and "resting 240 min (> 120)" in a for a in found)


def test_settlement_lag_only_counts_started_filled_unsettled():
    orders = [
        _order(commence_time="2026-11-17T02:00:00Z"),                 # 14 h, late
        _order(commence_time="2026-11-17T12:00:00Z"),                 # 4 h, started, not late
        _order(commence_time="2026-11-17T02:00:00Z", outcome="won"),  # settled
        _order(commence_time="2026-11-18T02:00:00Z"),                 # future
        _order(commence_time="2026-11-17T02:00:00Z", status="rejected"),
    ]
    s = pm.settlement_lag(orders, NOW)
    assert (s["started_unsettled"], s["late"]) == (2, 1)
    assert s["late_rows"][0]["hours"] == 14.0


def test_cap_use_is_against_the_venue_day_caps_and_skips_refusals():
    orders = [_order(fill_stake_dollars=10.0), _order(status="rejected", fill_stake_dollars=50.0),
              _order(status="submitted", fill_stake_dollars=None, requested_stake_dollars=3.0),
              _order(venue="polymarket", fill_stake_dollars=7.0)]
    limits = {"max_day_dollars_by_venue": {"kalshi": 100.0, "polymarket": 7.5},
              "max_day_orders_by_venue": {"kalshi": 250, "polymarket": 250}}
    c = pm.cap_use(orders, limits, "2026-11-17")
    assert c["kalshi"]["dollars"] == 13.0 and c["kalshi"]["dollars_pct"] == 13.0 and c["kalshi"]["orders"] == 2
    assert c["polymarket"]["dollars_pct"] == 93.3
    assert "CAP polymarket dollars at 93.3% of the day cap" in pm.anomalies({"cap_use": c})


ACCESS = ('2026-11-17T16:10:26.141Z 127.0.0.1 - - [17/Nov/2026:10:10:26 -0600] "GET /api/portfolio/plan HTTP/1.1" '
          '200 479858 "-" "Python-urllib/3.11" 1520ms')


def test_web_access_groups_paths_counts_browsers_and_worker_timeouts():
    lines = [
        ACCESS,
        ACCESS.replace("1520ms", "20ms").replace("Python-urllib/3.11", "Mozilla/5.0 (Windows)"),
        '2026-11-17T16:10:30.000Z 127.0.0.1 - - [x] "GET /api/portfolio/live?on=all&show=all HTTP/1.1" 502 10 "-" "c" 9ms',
        "2026-11-17T16:13:23.492Z [2026-11-17 10:13:23 -0600] [438] [CRITICAL] WORKER TIMEOUT (pid:3996790)",
        ACCESS.replace("2026-11-17T16:10:26", "2026-11-17T15:00:00"),  # before the window
    ]
    w = pm.web_access(lines, "2026-11-17T16:00:00")
    assert w["worker_timeouts"] == 1
    assert w["paths"]["/api/portfolio/plan"]["n"] == 2 and w["paths"]["/api/portfolio/plan"]["browser"] == 1
    assert w["paths"]["/api/portfolio/live?on=all"]["status"] == {"502": 1}
    found = pm.anomalies({"web": w})
    assert "WEB 1 gunicorn WORKER TIMEOUT kill(s) in the window" in found
    assert "WEB /api/portfolio/live?on=all: 1/1 (100.0%) answered 5xx" in found


EXECUTED = ("2026-11-17T16:17:22.114Z [execute_portfolio] EXECUTED date=2026-11-17 mode=live venue=polymarket "
            "plan_source=live armed=True positions=5 placed=1 filled=1 failed=0 duplicates=2 retried=0 trimmed=0 "
            "skipped=3 refused={'outside_price_band': 3} spent={'dollars': 7.94, 'orders': 14} summary={'a': 1}")
PLAN = ("2026-11-17T16:14:41.018Z [portfolio_commit] LIVE_PLAN_WRITTEN date=2026-11-17 venue=polymarket rows_in=428 "
        "placeable_in=9 positions=5 staked=$7.08 scale=1.0 refusals={'aggregator_priced': 158, 'below_live_net_floor': 261}")


def test_execution_sums_live_ticks_only_and_keeps_the_newest_plan():
    paper = EXECUTED.replace("mode=live", "mode=paper").replace("failed=0", "failed=9")
    unrec = ("2026-11-17T16:17:13.868Z [execution_ledger] UNRECONCILABLE_ORDER key='f8b62e6ad863263bf537d607' "
             "venue='kalshi' mode='live' outcome='lost' reason=outcome_already_set")
    e = pm.execution([EXECUTED, EXECUTED.replace("failed=0", "failed=2"), paper, PLAN, unrec], "2026-11-17T16:00:00")
    v = e["live_ticks"]["polymarket"]
    assert (v["ticks"], v["placed"], v["filled"], v["failed"]) == (2, 2, 2, 2)
    assert v["refused"] == {"outside_price_band": 6}
    assert e["plans"]["polymarket"]["refusals"]["below_live_net_floor"] == 261
    assert e["unreconcilable_keys"] == ["f8b62e6a"]
    assert "EXECUTION polymarket: 2 failed order(s) over 2 live ticks" in pm.anomalies({"execution": e})


def test_the_two_endpoints_that_cost_a_worker_are_never_fetched():
    for path in pm.NEVER_READ:
        with pytest.raises(ValueError):
            pm.fetch("http://127.0.0.1:10000", path, None)
    assert not any(path.startswith(p) for _, path, _ in pm.ENDPOINTS for p in pm.NEVER_READ)


def test_main_refuses_a_non_fleet_base_url(capsys):
    assert pm.main(["--base-url", "https://example.onrender.com", "--no-logs"]) == 2
    assert "not the fleet" in capsys.readouterr().err


def test_a_clean_reading_has_no_anomalies():
    reading = {
        "endpoints": {"plan": {"status": 200, "seconds": 0.5, "budget_s": 6.0}},
        "web": {"paths": {}, "worker_timeouts": 0},
        "banner": {"ok": True, "state_age_s": 40, "stale_after_s": 900, "state_stale": False, "balances_age_s": 60},
        "plan": {"age_min": 5.0, "clv_join_match_rate": 1.0},
        "ledger": {"unknown_submits": 0, "unreconciled": 0, "grade_conflicts": 0},
        "orders_today": {"orders": 3, "failed_or_rejected": 0, "resting_age_min": [10.0]},
        "settlement": {"late": 0},
        "cap_use": {"kalshi": {"dollars_pct": 10.0, "orders_pct": 1.0}},
        "gate": {"clock": {"pending": False, "unclassified": 0}},
    }
    assert pm.anomalies(reading) == []


def test_the_paper_books_all_dates_record_is_read_from_the_worker_line():
    """The /portfolio/paper page was retired 2026-11-17; the record it showed is the refresh-worker's
    PAPER_ALL_TIME_WRITTEN line now, and the newest one in the window wins."""
    older = ("2026-11-17T18:00:00.000Z [paper_settlement] PAPER_ALL_TIME_WRITTEN rows=10 settled=8 pending=2 "
             "won=4 lost=4 push=0 roi_pct=-1.5 win_pct=50.0 at=2026-11-17T18:00:00Z")
    newer = ("2026-11-17T18:11:00.000Z [paper_settlement] PAPER_ALL_TIME_WRITTEN rows=51075 settled=14605 pending=7 "
             "won=7400 lost=7100 push=105 roi_pct=None win_pct=51.03 at=2026-11-17T18:11:00Z")
    e = pm.execution([older, newer], "2026-11-17T17:00:00")
    pr = e["paper_record"]
    assert pr["rows"] == 51075 and pr["settled"] == 14605 and pr["win_pct"] == 51.03 and pr["roi_pct"] is None
    assert pr["at"] == "2026-11-17T18:11:00Z"
    assert pm.execution([older], "2026-11-17T18:05:00")["paper_record"] is None  # outside the window


def test_a_maker_pilot_post_rests_until_kickoff_without_an_anomaly():
    """2026-11-17: an NCAAF maker-pilot post (00:12 CST for a 6 PM kickoff) was flagged at every reading by the
    generic 120-min rule. A pilot post rests on purpose until it fills, the fair moves, or kickoff."""
    kick = "2026-11-18T00:00:00Z"
    post = _order(status="submitted", execution_style="maker_pilot", idempotency_key="a1f809cad8ee",
                  submitted_at="2026-11-17T06:12:20Z", commence_time=kick, reconciled_at="2026-11-17T15:55:00Z")
    before = pm.order_flow([post], "2026-11-17", NOW)            # 16:00Z, 9 h 48 min resting, kickoff 8 h away
    assert before["resting"] == 1 and before["resting_overdue"] == []
    assert not any(a.startswith("ORDERS") for a in pm.anomalies({"orders_today": before}))
    after = dt.datetime(2026, 11, 18, 0, 15, tzinfo=dt.timezone.utc)
    late = pm.order_flow([dict(post, reconciled_at="2026-11-18T00:10:00Z")], "2026-11-17", after)
    assert late["resting_overdue"][0]["why"] == "maker-pilot post still resting 15 min after kickoff"
    assert "ORDERS resting order a1f809ca (maker_pilot): maker-pilot post still resting 15 min after kickoff" in         pm.anomalies({"orders_today": late})


def test_any_resting_order_the_reconciler_stopped_reading_is_flagged():
    post = _order(status="submitted", execution_style="maker_pilot", submitted_at="2026-11-17T15:00:00Z",
                  commence_time="2026-11-18T00:00:00Z", reconciled_at="2026-11-17T15:20:00Z")
    flow = pm.order_flow([post], "2026-11-17", NOW)
    assert flow["resting_overdue"][0]["why"] == "not reconciled for 40 min"


def test_a_taker_order_keeps_the_120_minute_rule():
    young = _order(status="submitted", submitted_at="2026-11-17T15:00:00Z", reconciled_at="2026-11-17T15:58:00Z")
    old = _order(status="submitted", submitted_at="2026-11-17T13:00:00Z", reconciled_at="2026-11-17T15:58:00Z")
    assert pm.order_flow([young], "2026-11-17", NOW)["resting_overdue"] == []
    assert pm.order_flow([old], "2026-11-17", NOW)["resting_overdue"][0]["why"] == "resting 180 min (> 120)"


def test_a_maker_post_that_expired_unfilled_at_kickoff_is_not_a_failure():
    """2026-11-18 00:00:07Z: the pilot post was cancelled unfilled at its kickoff expiry and recorded `rejected`
    (`error=venue_canceled`), which the probe counted as 'failed or rejected'. It is the post's designed ending."""
    expired = _order(status="rejected", execution_style="maker_pilot", error="venue_canceled", contracts=0)
    real = _order(status="rejected", error="venue_400")
    f = pm.order_flow([expired, _order()], "2026-11-17", NOW)
    assert f["maker_posts_expired_unfilled"] == 1 and f["failed_or_rejected"] == 0
    assert not any(a.startswith("ORDERS failed") for a in pm.anomalies({"orders_today": f}))
    g = pm.order_flow([expired, real], "2026-11-17", NOW)
    assert g["failed_or_rejected"] == 1
    assert "ORDERS failed or rejected today: 1/2 (50.0%)" in pm.anomalies({"orders_today": g})


def test_plan_commits_groups_venue_lines_per_date_and_ages_tonight():
    """Tonight's plan cadence: venue lines within 3 min are one commit, and tomorrow's writes do not refresh tonight."""
    def line(ts, date, venue="kalshi"):
        return f"{ts} [portfolio_commit] LIVE_PLAN_WRITTEN date={date} venue={venue} rows_in=10 placeable_in=2"

    lines = [line("2026-11-18T01:02:53.306Z", "2026-11-17"), line("2026-11-18T01:03:11.432Z", "2026-11-17", "polymarket"),
             line("2026-11-18T01:21:13.360Z", "2026-11-17"), line("2026-11-18T01:21:49.506Z", "2026-11-17", "polymarket"),
             line("2026-11-18T02:02:23.696Z", "2026-11-18"), line("2026-11-18T02:02:34.435Z", "2026-11-18", "polymarket")]
    now = dt.datetime(2026, 11, 18, 2, 11, 13, tzinfo=dt.timezone.utc)   # 8:11 PM CST on 11-17
    pc = pm.plan_commits(lines, now)
    assert pc["today"] == "2026-11-17"
    tonight = pc["by_date"]["2026-11-17"]
    assert tonight["commits"] == 2 and tonight["newest"] == "01:21:13Z" and tonight["max_gap_min"] == 18.3
    assert pc["by_date"]["2026-11-18"]["commits"] == 1
    assert pc["today_newest_age_min"] == 49.4   # the 02:02 write was tomorrow's: tonight's plan is still 01:21's
    assert pm.plan_commits([], now)["today_newest_age_min"] is None


def test_unreconciled_waits_out_the_reconcile_pass():
    now = dt.datetime(2026, 11, 18, 3, 7, 12, tzinfo=dt.timezone.utc)
    live = {"unreconciled": [{"idempotency_key": "6d56320bcab7", "submitted_at": "2026-11-18T03:05:02.986108Z"},
                             {"idempotency_key": "aaaaaaaa1111", "submitted_at": "2026-11-18T02:40:00Z"},
                             {"idempotency_key": "bbbbbbbb2222"}]}
    led = pm.ledger_flags(live, now)
    assert led["unreconciled"] == 3 and led["unreconciled_overdue_keys"] == ["aaaaaaaa", "bbbbbbbb"]
    alarms = [a for a in pm.anomalies({"ledger": led}) if a.startswith("LEDGER unreconciled")]
    assert alarms == ["LEDGER unreconciled > 10 min: 2 (aaaaaaaa, bbbbbbbb)"]
    fresh = pm.ledger_flags({"unreconciled": live["unreconciled"][:1]}, now)
    assert not [a for a in pm.anomalies({"ledger": fresh}) if a.startswith("LEDGER")]


def test_an_unfilled_inplay_ioc_is_not_a_failed_order():
    now = dt.datetime(2026, 11, 18, 3, 10, tzinfo=dt.timezone.utc)
    ioc = {"selected_date": "2026-11-17", "mode": "live", "status": "rejected", "error": "venue_canceled",
           "position_key": "ingame:KXNHLSPREAD-26NOV17TORCHI-CHI4:no", "contracts": None}
    real = {"selected_date": "2026-11-17", "mode": "live", "status": "rejected", "error": "insufficient_balance"}
    pregame_cancel = {"selected_date": "2026-11-17", "mode": "live", "status": "rejected", "error": "venue_canceled",
                      "position_key": "pregame:X", "contracts": None}
    flow = pm.order_flow([ioc, real, pregame_cancel], "2026-11-17", now)
    assert flow["inplay_ioc_unfilled"] == 1 and flow["failed_or_rejected"] == 2
