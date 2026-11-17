"""The paper page and API are retired; the paper BOOK's all-dates record is the worker's.

[2026-11-17, lanes paper-endpoint-request-path then paper-page-retirement] Measured on the fleet that day:
`/api/portfolio/paper` read every order of every date (51,075 rows, 120 MB of archive) and settled all of it
per request, 24 s and 772 MB; one GET ran ~177 s until gunicorn killed its web worker. No person had opened
the page since 2026-10-19 and nothing scheduled called it, so the user retired it ("Retire it").

These pin what remains:
  * the refresh-worker's settle pass writes the paper-only all-dates record (reachable from `settle_orders`),
    throttled to one per 10 min, and prints it on `PAPER_ALL_TIME_WRITTEN` for the portfolio monitor;
  * `/portfolio/paper` redirects to `/portfolio`, `/api/portfolio/paper` answers 410 with a pointer, and the
    book switcher no longer lists Paper.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import execution_ledger as ledger  # noqa: E402
from syndicate.features.shared import paper_settlement as settle  # noqa: E402
from syndicate.features.shared import portfolio_books  # noqa: E402
from syndicate.features.shared.execution_ledger import LIVE, PAPER, STATUS_FILLED  # noqa: E402
from syndicate.features.shared.refresh_state_store import read_json_file  # noqa: E402

DATE = "2026-11-17"
T0 = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    ledger._ARCHIVE_PARSE_CACHE.clear()
    yield
    ledger._ARCHIVE_PARSE_CACHE.clear()


def _row(key, *, date=DATE, mode=PAPER, outcome=None, pnl=0.0):
    row = {"idempotency_key": key, "mode": mode, "status": STATUS_FILLED, "selected_date": date, "venue": "paper",
           "sport": "nba", "market": "h2h", "fill_stake_dollars": 10.0, "fill_price": -110,
           "submitted_at": f"{date}T15:00:00Z"}
    if outcome is not None:
        row.update(outcome=outcome, pnl_dollars=pnl)
    return row


def test_the_worker_writes_the_paper_only_all_time_record():
    history = [_row("p1", outcome="won", pnl=9.0), _row("p2", outcome="lost", pnl=-10.0, date="2026-10-02"),
               _row("l1", mode=LIVE, outcome="won", pnl=50.0)]
    doc = settle.write_paper_all_time(history, now=T0)
    paper = [r for r in history if r["mode"] != LIVE]
    assert doc["rows"] == 2 and doc["summary"] == settle.settlement_summary(None, orders=paper)
    assert doc["population"] == "paper_mode_order_rows_portfolio_book_all_dates"
    stored = read_json_file(settle.paper_all_time_path())
    assert stored["summary"]["total"]["settled"] == 2 and stored["written_at"] == "2026-11-17T18:00:00Z"


def test_the_write_is_throttled_to_one_per_interval():
    history = [_row("p1", outcome="won", pnl=9.0)]
    assert settle.write_paper_all_time(history, now=T0) is not None
    assert settle.write_paper_all_time(history, now=T0 + timedelta(seconds=599)) is None
    assert settle.write_paper_all_time(history, now=T0 + timedelta(seconds=601)) is not None


def _resolve(_order):
    return {"current_value": 1.0, "is_final": True, "started": True}


def _no_close(rows, _date):
    return {"rows": [{"idempotency_key": r.get("idempotency_key"), "reason": "no_close_for_market",
                      "clv_pct": None, "close_price": None} for r in rows]}


def test_the_settle_pass_writes_the_record_and_prints_it(capsys):
    ledger._persist({"orders": [_row("p1", outcome="won", pnl=9.0), _row("p2", outcome="lost", pnl=-10.0),
                                _row("l1", mode=LIVE, outcome="lost", pnl=-5.0)]})
    assert read_json_file(settle.paper_all_time_path()) is None
    settle.settle_orders(DATE, resolver=_resolve, closer=_no_close)
    assert read_json_file(settle.paper_all_time_path())["rows"] == 2
    line = next(l for l in capsys.readouterr().out.splitlines() if "PAPER_ALL_TIME_WRITTEN" in l)
    # The record is on the line (the monitor reads it there), and no dollar figure is.
    for field in ("rows=2", "settled=2", "won=1", "lost=1", "push=0", "roi_pct=", "win_pct=50.0"):
        assert field in line, field
    assert "$" not in line and "pnl" not in line


def test_the_retired_routes_answer_with_a_redirect_and_a_410(monkeypatch):
    from syndicate.app import app

    monkeypatch.setitem(app.config, "TESTING", True)
    monkeypatch.setitem(app.config, "ADMIN_TOKEN", "test-token")
    client = app.test_client()
    headers = {"X-Admin-Token": "test-token"}
    page = client.get(f"/portfolio/paper?date={DATE}", headers=headers)
    assert page.status_code == 302 and page.headers["Location"].endswith("/portfolio")
    api = client.get(f"/api/portfolio/paper?date={DATE}", headers=headers)
    assert api.status_code == 410 and api.get_json()["retired"] == "2026-11-17"


def test_the_book_switcher_no_longer_lists_paper_and_paper_stays_reserved():
    assert [b["id"] for b in portfolio_books.BUILTIN_PORTFOLIOS] == ["live"]
    assert "paper" in portfolio_books._RESERVED_IDS
