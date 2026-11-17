"""`/portfolio/paper` does no heavy work in the web request [2026-11-17, lane paper-endpoint-request-path].

Measured on the fleet that day: the builder read every order of every date (51,075 rows, 120 MB of archive)
and settled all of it per request, 24 s and 772 MB; one GET ran ~177 s until gunicorn killed its web worker.
These pin the two halves of the fix:
  * the date view reads one date's rows from its month shard, the SAME rows the full-history filter gave,
    and leaves no whole shard in the process's parse cache;
  * the all-dates record is written by the worker's settle pass (reachable from `settle_orders`) and only
    read by web, which degrades to None before the first write.
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
from syndicate.features.shared.execution_ledger import LIVE, PAPER, STATUS_FILLED  # noqa: E402

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


def _row(key, *, date=DATE, mode=PAPER, outcome=None, pnl=0.0, **extra):
    row = {"idempotency_key": key, "mode": mode, "status": STATUS_FILLED, "selected_date": date, "venue": "paper",
           "sport": "nba", "market": "h2h", "fill_stake_dollars": 10.0, "fill_price": -110,
           "submitted_at": f"{date}T15:00:00Z", **extra}
    if outcome is not None:
        row.update(outcome=outcome, pnl_dollars=pnl)
    return row


def _plant():
    # Archive: two dates in the November shard, one re-archived copy, and a row of ANOTHER date whose
    # text carries this date (a commence_time) -- the substring prefilter must not admit it.
    ledger._archive_rows([
        _row("a"), _row("b", outcome="lost", pnl=-10.0), _row("c", mode=LIVE),
        _row("x", date="2026-11-16", commence_time=f"{DATE}T00:10:00Z"),
        _row("y", date="2026-10-30"),
    ])
    ledger._archive_rows([_row("b", outcome="won", pnl=9.0)])  # archived twice: the last copy wins
    with open(ledger._archive_dir() / "orders_2026-11.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"idempotency_key": "torn", "selected_date": "' + DATE + '"')  # torn final line
    # Document: a newer copy of an archived row (the document wins) and a row only the document has.
    ledger._persist({"orders": [_row("a", outcome="won", pnl=9.0), _row("d"), _row("z", date="2026-11-16")]})


def _by_key(rows):
    return {r["idempotency_key"]: r for r in rows}


def test_ledger_for_date_gives_the_full_history_filters_rows_and_summary():
    _plant()
    old = [o for o in ledger.full_history_orders() if o.get("selected_date") == DATE]
    ledger._ARCHIVE_PARSE_CACHE.clear()
    new = ledger.ledger_for_date(DATE)
    assert _by_key(new["orders"]) == _by_key(old)
    assert sorted(_by_key(new["orders"])) == ["a", "b", "c", "d"]
    assert _by_key(new["orders"])["a"]["outcome"] == "won"  # the document's copy
    assert _by_key(new["orders"])["b"]["outcome"] == "won"  # the newest archived copy
    assert new["summary"] == ledger.ledger_summary(DATE)


def test_ledger_for_date_parses_no_whole_shard():
    _plant()
    ledger._ARCHIVE_PARSE_CACHE.clear()
    ledger.ledger_for_date(DATE)
    assert ledger._ARCHIVE_PARSE_CACHE == {}
    ledger.ledger_summary(DATE)  # the old path does fill it: the check above can fail
    assert ledger._ARCHIVE_PARSE_CACHE != {}


def test_ledger_for_date_with_no_shard_reads_the_document_only():
    ledger._persist({"orders": [_row("d"), _row("e", date="2026-11-16")]})
    assert sorted(_by_key(ledger.ledger_for_date(DATE)["orders"])) == ["d"]


def test_the_worker_writes_the_paper_only_all_time_record_and_web_reads_it():
    history = [_row("p1", outcome="won", pnl=9.0), _row("p2", outcome="lost", pnl=-10.0, date="2026-10-02"),
               _row("l1", mode=LIVE, outcome="won", pnl=50.0)]
    assert settle.read_paper_all_time() is None
    doc = settle.write_paper_all_time(history, now=T0)
    paper = [r for r in history if r["mode"] != LIVE]
    assert doc["rows"] == 2 and doc["summary"] == settle.settlement_summary(None, orders=paper)
    assert doc["population"] == "paper_mode_order_rows_portfolio_book_all_dates"
    stored = settle.read_paper_all_time()
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


def test_the_settle_pass_writes_the_record(capsys):
    ledger._persist({"orders": [_row("p1", outcome="won", pnl=9.0), _row("l1", mode=LIVE, outcome="lost", pnl=-5.0)]})
    assert settle.read_paper_all_time() is None
    settle.settle_orders(DATE, resolver=_resolve, closer=_no_close)
    stored = settle.read_paper_all_time()
    assert stored is not None and stored["rows"] == 1
    assert "[paper_settlement] PAPER_ALL_TIME_WRITTEN rows=1" in capsys.readouterr().out


def _payload(monkeypatch):
    from syndicate.blueprints import intelligence as bp

    def _no_full_history():
        raise AssertionError("the web request read the full order history")

    monkeypatch.setattr(ledger, "full_history_orders", _no_full_history)
    return bp._paper_portfolio_payload(DATE)


def test_the_payload_reads_the_worker_record_and_never_the_full_history(monkeypatch):
    _plant()
    settle.write_paper_all_time([_row("p1", outcome="won", pnl=9.0)], now=T0)
    payload = _payload(monkeypatch)
    assert payload["ledger_error"] is None and payload["settlement_error"] is None
    assert payload["settlement_all_time"]["total"]["settled"] == 1
    assert payload["settlement_all_time_as_of"] == "2026-11-17T18:00:00Z"
    # The date's paper orders only: `c` is live and stays off the paper page.
    assert sorted(o["idempotency_key"] for o in payload["orphan_orders"]) == ["a", "b", "d"]
    assert payload["ledger"]["orders"] == 4  # the summary counts every mode, as `ledger_summary` did
    assert ledger._ARCHIVE_PARSE_CACHE == {}


def test_before_the_first_worker_write_the_all_dates_record_is_absent_not_zero(monkeypatch):
    _plant()
    payload = _payload(monkeypatch)
    assert payload["settlement_all_time"] is None and payload["settlement_all_time_as_of"] is None
    assert payload["settlement_error"] is None
    assert payload["settlement"]["total"]["settled"] == 2  # the date's own record is still computed
