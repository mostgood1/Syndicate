"""Watch rows no tick has seen for 24 h move to the archive (lane exit-watch-unseen-prune, 2026-11-26).

MEASURED 11-25: the exits document crossed the 8,388,608 B keyvalue cap at 4:31 PM CST with 8,505 watch rows, 79-84%
of them last seen over a day ago. A refused save after a live sell lost that sell's venue answer, and its `submitted`
row blocked every new live exit for ~4.5 h (findings_2026-11-25_portfolio_monitor.md H-X1..H-X4).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import execution_exits as ex
from test_execution_exits import _market, _order, _quotes

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=timezone.utc)
NOW_TEXT = "2026-10-19T20:00:00Z"
TODAY = "2026-10-19"


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
    ):
        monkeypatch.delenv(name, raising=False)
    yield


def _row(key, last_seen=None, day=TODAY):
    row = {"entry_key": key, "selected_date": day, "commence_time": f"{day}T23:00:00Z", "mode": "paper"}
    if last_seen is not None:
        row["last_seen"] = last_seen
    return row


def test_a_row_unseen_for_over_24h_moves_to_the_archive_and_recent_rows_stay():
    state = ex._empty_state()
    state["watch"] = {
        "gone": _row("gone", "2026-10-18T19:59:59Z"),  # 24 h + 1 s
        "edge": _row("edge", "2026-10-18T20:00:00Z"),  # exactly 24 h: stays
        "fresh": _row("fresh", "2026-10-19T19:30:00Z"),
        "no_stamp": _row("no_stamp"),
        "bad_stamp": _row("bad_stamp", "not a time"),
    }
    assert ex._prune_watch(state, TODAY, now=NOW_TEXT) == 1
    assert sorted(state["watch"]) == ["bad_stamp", "edge", "fresh", "no_stamp"]
    assert [r["entry_key"] for r in ex.archived_watch_rows()] == ["gone"]


def test_without_now_the_prune_is_the_date_floor_alone():
    """off != on: the old call shape must not archive by age, and the new one must."""
    rows = {"old_seen": _row("old_seen", "2026-10-15T00:00:00Z")}
    without = ex._empty_state()
    without["watch"] = dict(rows)
    assert ex._prune_watch(without, TODAY) == 0 and list(without["watch"]) == ["old_seen"]
    with_now = ex._empty_state()
    with_now["watch"] = dict(rows)
    assert ex._prune_watch(with_now, TODAY, now=NOW_TEXT) == 1 and with_now["watch"] == {}


def test_the_date_floor_still_applies_to_a_row_seen_just_now():
    state = ex._empty_state()
    state["watch"] = {"past_floor": _row("past_floor", "2026-10-19T19:59:00Z", day="2026-10-13")}
    assert ex._prune_watch(state, TODAY, now=NOW_TEXT) == 1 and state["watch"] == {}


def test_the_tick_archives_unseen_rows_and_keeps_the_position_it_sees(monkeypatch):
    """Reachability through `run_exit_tick`: an open position's row is refreshed before the prune, so it stays
    even when its stored `last_seen` is old; a closed position's row, unseen for a day, leaves the document."""
    monkeypatch.setenv("SYNDICATE_EXIT_TAKE_PROFIT_MARGIN", "0.50")  # nothing triggers
    orders = [_order(mode="paper", venue="paper:kalshi")]
    positions, _ = ex.open_positions(orders, today=TODAY)
    open_key = positions[0].entry_key
    state = ex._empty_state()
    state["watch"] = {
        open_key: {**_row(open_key, "2026-10-17T00:00:00Z"), "first_seen": "2026-10-17T00:00:00Z", "samples": 3},
        "closed": _row("closed", "2026-10-18T12:00:00Z"),
    }
    ex._persist(state)
    summary = ex.run_exit_tick(today=TODAY, orders=orders, quotes=_quotes([_market()]),
                               venue_positions=lambda: {"status": "ok", "positions": {}}, now=NOW)
    assert summary["pruned"] == 1
    saved = ex.load_state()["watch"]
    assert list(saved) == [open_key]
    assert saved[open_key]["last_seen"] == NOW_TEXT and saved[open_key]["first_seen"] == "2026-10-17T00:00:00Z"
    assert [r["entry_key"] for r in ex.archived_watch_rows()] == ["closed"]
