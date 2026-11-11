"""`exec:ungraded_fills` -- a live fill nothing is grading is an alarm, not a quiet refusal (lane `kalshi-aged-out-grade`).

Key `970ec063` (Kalshi, 1 NO, filled 2026-10-25 17:14Z, WON) sat ungraded for 16 days: the venue grader refused
it every pass and nothing said so until the order aged out of Kalshi's routes and the reconciler started a 404
loop. The age is the alarm: the later of the fill and the slate date, so a fill placed ahead of its game is not
aged from the placement.
"""

from __future__ import annotations

import datetime as dt

from scripts import execution_watchdog as xw
from tests.test_execution_watchdog import _healthy, _keys

NOW = dt.datetime(2026, 11, 10, 23, 49, tzinfo=dt.timezone.utc)
LIMITS = dict(xw.DEFAULTS)


def _fill(key="k", *, filled_days_ago=4.0, slate=None, **extra):
    at = (NOW - dt.timedelta(days=filled_days_ago)).isoformat().replace("+00:00", "Z")
    row = {"idempotency_key": key, "mode": "live", "venue": "kalshi", "status": "filled", "outcome": None,
           "submitted_at": at, "venue_resolved_at": at, "venue_ticker": "KX-T", "fill_stake_dollars": 0.43,
           "reconciled_at": at}
    if slate:
        row["selected_date"] = slate
    row.update(extra)
    return row


def _eval(orders, limits=LIMITS):
    readings = _healthy(orders=orders)
    return xw.evaluate(readings, NOW, limits, {})


def test_the_measured_case_is_flagged():
    row = _fill("970ec063e70e43b1ac7e1cbd", submitted_at="2026-10-25T17:14:02Z",
                venue_resolved_at="2026-10-25T17:14:05Z", slate="2026-10-25", sport="nfl", market="h2h", side="no")
    findings, _ = _eval([row])
    assert _keys(findings).get("exec:ungraded_fills") == xw.WARN
    message = next(f.message for f in findings if f.key == "exec:ungraded_fills")
    assert "970ec063e70e43b1ac7e1cbd" in message and "16.3 d" in message
    assert xw.emailable("exec:ungraded_fills", xw.WARN), "every exec: finding is emailed"


def test_a_young_fill_is_not_flagged():
    findings, _ = _eval([_fill(filled_days_ago=2.0)])
    assert "exec:ungraded_fills" not in _keys(findings)


def test_graded_paper_and_non_position_rows_are_not_flagged():
    rows = [_fill("graded", outcome="won"), _fill("paper", mode="paper"), _fill("rejected", status="rejected"),
            _fill("submitted", status="submitted", reconciled_at=None)]
    ungraded = xw.ungraded_fills(rows, NOW, 3.0)
    assert ungraded == []


def test_the_clock_starts_at_the_slate_date_when_that_is_later():
    """A fill placed four days before its game is one day past the slate, not four."""
    slate = (NOW - dt.timedelta(days=1)).date().isoformat()
    assert xw.ungraded_fills([_fill(filled_days_ago=4.0, slate=slate)], NOW, 3.0) == []
    assert len(xw.ungraded_fills([_fill(filled_days_ago=4.0, slate="2026-11-05")], NOW, 3.0)) == 1


def test_a_fill_ahead_of_its_game_is_aged_from_the_game():
    """MEASURED 2026-11-11: NCAAF bets bought on slate 11-08 for games on 11-14 read 3.1 d from the slate."""
    ahead = _fill(filled_days_ago=3.1, slate="2026-11-07", commence_time="2026-11-14T17:00:00Z")
    assert xw.ungraded_fills([ahead], NOW, 3.0) == []
    started = _fill(filled_days_ago=5.0, slate="2026-11-05", commence_time="2026-11-06T00:00:00Z")
    assert len(xw.ungraded_fills([started], NOW, 3.0)) == 1


def test_the_lean_order_keeps_the_game_start():
    assert xw._lean({"commence_time": "2026-11-14T17:00:00Z", "mode": "live"})["commence_time"] == "2026-11-14T17:00:00Z"


def test_an_unknown_age_is_reported_not_skipped():
    row = _fill(submitted_at=None, venue_resolved_at=None)
    flagged = xw.ungraded_fills([row], NOW, 3.0)
    assert len(flagged) == 1 and flagged[0]["_age_days"] is None


def test_the_threshold_is_overridable_and_absent_means_the_default(tmp_path):
    (tmp_path / "alerts.env").write_text("SYNDICATE_ALERT_UNGRADED_FILL_DAYS=10\n", encoding="utf-8")
    limits = xw.thresholds(tmp_path)
    assert limits["ungraded_fill_days"] == 10.0
    findings, _ = _eval([_fill(filled_days_ago=4.0)], limits)
    assert "exec:ungraded_fills" not in _keys(findings)
    no_key = {k: v for k, v in LIMITS.items() if k != "ungraded_fill_days"}
    findings, _ = _eval([_fill(filled_days_ago=4.0)], no_key)
    assert "exec:ungraded_fills" in _keys(findings), "a limits dict without the key uses the default, not off"
