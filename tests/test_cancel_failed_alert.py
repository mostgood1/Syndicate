"""A FAILED CANCEL IS AN ALERT ON ITS OWN -- no 3-line burst needed.

2026-10-20: KXNBASPREAD-26OCT20OKCSAS-SAS21 404'd on every cancel (unscoped DELETE ->
shard 0; fixed in d57476ec) and nothing alerted, because `CANCEL_FAILED` matched no
watchdog pattern and the burst threshold is 3 lines per check. A resting order we
tried and failed to pull can still fill at a stale price, so one line is an incident.
"""

from __future__ import annotations

import datetime as dt

from scripts import execution_watchdog as xw

NOW = dt.datetime(2026, 10, 21, 1, 30, tzinfo=dt.timezone.utc)


def _evaluate(lines, exec_state=None, now=NOW):
    readings = {"execution_state": None, "store_errors": [], "log_lines": lines}
    return xw.evaluate(readings, now, dict(xw.DEFAULTS), exec_state or {})


def test_both_cancel_failed_spellings_land_in_the_cancel_group():
    hits = xw.log_hits([
        "2026-10-21T01:30:00Z [execution_ledger] CANCEL_FAILED key=k1 reason=KalshiAuthError: http_404 -- order left resting",
        "2026-10-21T01:30:00Z [kalshi_orders] CANCEL_FAILED order_id=abc reason=shard_unresolved:x",
        "2026-10-21T01:30:00Z [execution_ledger] CANCEL_AT_KICKOFF key=k1 ticker=T",      # an attempt is not a failure
        "2026-10-21T01:30:00Z [execution_ledger] KICKOFF_CANCEL_PASS resting=1 due=1 cancelled=1 failed=0 deferred=0",
        "2026-10-21T01:30:00Z [kalshi_orders] CANCEL url=https://x/orders/abc?exchange_index=3",
    ])
    assert set(hits) == {"cancel"} and len(hits["cancel"]) == 2


def test_one_failed_cancel_is_an_alert_without_a_burst():
    readings = {"execution_state": None, "store_errors": [], "log_lines": [
        "2026-10-21T01:30:00Z [execution_ledger] CANCEL_FAILED key=k1 reason=http_404 -- order left resting"]}
    findings, updates = xw.evaluate(readings, NOW, dict(xw.DEFAULTS), {})
    assert "exec:log_errors:cancel" in {f.key for f in findings}
    assert updates["log_holds"]["cancel"]["count"] == 1


def test_other_groups_keep_the_burst_threshold():
    lines = ["[kalshi_orders] SUBMIT_FAILED_MARKET ticker=X"] * 2
    _, updates = xw.evaluate({"execution_state": None, "store_errors": [], "log_lines": lines},
                             NOW, dict(xw.DEFAULTS), {})
    assert "kalshi" not in updates["log_holds"]
