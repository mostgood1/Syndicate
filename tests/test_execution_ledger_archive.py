"""The record cap MOVES rows to a disk archive; it never drops them.

[2026-10-08, lane execution-ledger-keyvalue-growth] Measured on the fleet: 4,698
orders, ~600 paper a day, the 5,000 cap reached within hours -- and `_trim_to_cap`
dropped the oldest paper rows outright while the all-time ROI, the credibility
sample, the scorecard window and both fitters read the document as the whole
history. These pin the move, its write-ahead ordering, and that the full-history
readers actually see archived rows (reachability before correctness).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import execution_ledger as ledger  # noqa: E402
from syndicate.features.shared.execution_ledger import LIVE, PAPER, STATUS_FILLED  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REFRESH_STATE_BACKEND", raising=False)
    ledger._ARCHIVE_PARSE_CACHE.clear()
    yield
    ledger._ARCHIVE_PARSE_CACHE.clear()


def _row(key: str, *, mode: str = PAPER, outcome: str | None = None, date: str = "2026-10-02",
         pnl: float = 0.0) -> dict:
    row = {"idempotency_key": key, "mode": mode, "status": STATUS_FILLED, "selected_date": date,
           "venue": "paper", "sport": "nfl", "fill_stake_dollars": 10.0}
    if outcome is not None:
        row.update(outcome=outcome, pnl_dollars=pnl)
    return row


def _keys(rows) -> list[str]:
    return [o["idempotency_key"] for o in rows]


def test_trimmed_rows_land_in_the_archive_and_full_history_keeps_every_row(monkeypatch, capsys):
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 3)
    rows = [_row(f"p{i}", outcome="won") for i in range(5)]
    ledger._persist({"orders": rows})

    assert _keys(ledger._load()["orders"]) == ["p2", "p3", "p4"]
    assert _keys(ledger.archived_orders()) == ["p0", "p1"]
    assert _keys(ledger.full_history_orders()) == ["p0", "p1", "p2", "p3", "p4"]
    out = capsys.readouterr().out
    assert "TRIMMED dropped=2" in out and "archived_to=execution_ledger_archive/" in out
    shard = ledger._archive_dir() / "orders_2026-10.jsonl"
    assert shard.is_file() and len(shard.read_text(encoding="utf-8").splitlines()) == 2


def test_settled_paper_rows_leave_before_ungraded_ones(monkeypatch):
    """An ungraded row that leaves can never be graded: settlement writes the document."""
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 3)
    rows = [_row("open-old"), _row("settled-1", outcome="lost"), _row("open-2"),
            _row("settled-2", outcome="won"), _row("live", mode=LIVE)]
    ledger._persist({"orders": rows})
    assert _keys(ledger._load()["orders"]) == ["open-old", "open-2", "live"]
    assert _keys(ledger.archived_orders()) == ["settled-1", "settled-2"]


def test_a_failed_archive_keeps_the_rows_in_the_document(monkeypatch, capsys):
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 2)

    def _boom(rows):
        raise OSError("disk full")

    monkeypatch.setattr(ledger, "_archive_rows", _boom)
    state = ledger._persist({"orders": [_row(f"p{i}", outcome="won") for i in range(4)]})
    assert state["trimmed"] == 0
    assert _keys(ledger._load()["orders"]) == ["p0", "p1", "p2", "p3"]
    out = capsys.readouterr().out
    assert "LEDGER_ARCHIVE_FAILED" in out and "TRIMMED" not in out
    assert "LEDGER_OVER_CAP_PROTECTED over=2" in out


def test_the_document_copy_beats_the_archived_one_and_duplicates_collapse():
    ledger._archive_rows([_row("a", outcome="lost"), _row("b")])
    ledger._archive_rows([_row("b", outcome="won", pnl=9.0)])  # archived twice: last wins
    ledger._persist({"orders": [_row("a", outcome="won", pnl=5.0)]})  # still in the document

    history = {o["idempotency_key"]: o for o in ledger.full_history_orders()}
    assert len(ledger.full_history_orders()) == 2
    assert history["a"]["outcome"] == "won" and history["b"]["outcome"] == "won"


def test_a_torn_final_line_is_skipped():
    ledger._archive_rows([_row("a", outcome="won")])
    with open(ledger._archive_dir() / "orders_2026-10.jsonl", "a", encoding="utf-8") as handle:
        handle.write('{"idempotency_key": "torn"')
    assert _keys(ledger.archived_orders()) == ["a"]


def test_the_archive_is_plain_disk_even_on_the_keyvalue_backend(monkeypatch):
    """The archive exists to relieve the 8 MB keyvalue key; routing it through the
    store would put it straight back there."""
    monkeypatch.setattr(ledger, "write_json_file", lambda *a, **k: pytest.fail("archive used the store"))
    ledger._archive_rows([_row("a", outcome="won")])
    assert (ledger._archive_dir() / "orders_2026-10.jsonl").is_file()


def test_all_time_settlement_and_the_credibility_sample_read_the_archive(monkeypatch):
    """Reachability: off (document only) != on (archive included)."""
    from syndicate.features.shared import paper_settlement

    monkeypatch.setattr(ledger, "_MAX_RECORDS", 1)
    ledger._persist({"orders": [_row("old", outcome="won", pnl=10.0), _row("new", outcome="lost", pnl=-10.0)]})
    assert _keys(ledger._load()["orders"]) == ["new"]

    document_only = paper_settlement.settlement_summary(None, orders=ledger._load()["orders"])
    full = paper_settlement.settlement_summary(None)
    assert full["total"]["settled"] == 2 != document_only["total"]["settled"]
    assert paper_settlement.settled_decisions_by_sport() != paper_settlement.settled_decisions_by_sport(
        orders=ledger._load()["orders"]
    )


def test_a_past_dates_summary_finds_its_archived_rows(monkeypatch):
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 1)
    ledger._persist({"orders": [_row("old", outcome="won", date="2026-09-30"),
                                _row("new", date="2026-10-08")]})
    assert ledger.ledger_summary("2026-09-30")["orders"] == 1
    assert ledger.ledger_summary("2026-10-08")["orders"] == 1


def test_the_calibration_fitter_reads_the_archive_beside_the_document(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import fit_probability_calibration as fpc

    order = {"idempotency_key": "x", "outcome": "won", "model_edge_pct": 2.0, "ev_pct": 3.0,
             "fill_price": 100, "sport": "nfl", "market": "h2h", "selected_date": "2026-10-02"}
    archive = tmp_path / "intelligence" / "execution_ledger_archive"
    archive.mkdir(parents=True)
    (archive / "orders_2026-10.jsonl").write_text(json.dumps(order) + "\n", encoding="utf-8")
    assert len(fpc.load_execution_ledger_rows(tmp_path)) == 1  # no document at all

    doc = dict(order, outcome="lost")
    (tmp_path / "intelligence" / "execution_ledger.json").write_text(json.dumps({"orders": [doc]}), encoding="utf-8")
    rows = fpc.load_execution_ledger_rows(tmp_path)
    assert len(rows) == 1 and rows[0]["y"] == 0  # the document's copy won


def test_the_paper_page_shows_archived_rows_for_a_past_date_and_all_time(monkeypatch):
    """Reachability through `/portfolio/paper`: its rows and all-dates tile read
    `full_history_orders`, so a date the cap moved out still renders."""
    import pipeline.portfolio_commit as commit_mod
    from syndicate.blueprints import intelligence as intelligence_bp

    monkeypatch.setattr(commit_mod, "read_portfolio_plan", lambda date: None)
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 1)
    ledger._persist({"orders": [_row("old", outcome="won", pnl=10.0, date="2026-09-30"),
                                _row("new", outcome="lost", pnl=-10.0, date="2026-10-08")]})
    assert _keys(ledger._load()["orders"]) == ["new"]

    payload = intelligence_bp._paper_portfolio_payload("2026-09-30")
    assert payload["settlement_all_time"]["total"]["settled"] == 2
    assert payload["settlement"]["total"]["settled"] == 1
