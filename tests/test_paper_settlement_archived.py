"""Grading paper rows the record cap moved to the archive ungraded (`#744`).

`_trim_to_cap` moves an UNGRADED paper row out of the live document once no
settled one is left to move, and `settle_orders` reads only the document. These
pin the pass that grades such rows where they sit: reachability first (off and
on must differ), then the rules `settle_orders` keeps -- grade once, the live
document wins, a push is not a loss.

The eviction here is the real one: the cap is shrunk to 2 and `_trim_to_cap`
archives the oldest paper row on the third placement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import execution_ledger as ledger
from syndicate.features.shared import paper_settlement as settle
from syndicate.features.shared.execution_ledger import OrderRequest, place_order

DATE = "2026-10-10"
TODAY = "2026-10-12"
STARTED = "2026-10-10T18:00:00Z"
NOT_STARTED = "2099-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    monkeypatch.delenv(settle.ARCHIVED_GRADING_ENV, raising=False)
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ledger, "_MAX_RECORDS", 2)
    monkeypatch.setitem(settle._ARCHIVED_WORKER_STATE, "last_run", None)
    monkeypatch.setitem(settle._ARCHIVED_WORKER_STATE, "announced_off", False)
    # The closing-mark read is `stamp_closing_marks`' own concern (tested in
    # test_paper_settlement); here it must not reach odds history.
    import syndicate.features.shared.order_clv as order_clv

    monkeypatch.setattr(order_clv, "clv_for_orders", lambda rows, date=None: {"rows": []})
    yield


def _place(key, *, commence=STARTED, line=6.5, selected_date=DATE):
    return place_order(
        OrderRequest(
            position_key=key,
            selected_date=selected_date,
            venue="paper",
            sport="mlb",
            event_id=f"evt-{key}",
            market="strikeouts",
            side="over",
            requested_price=-110.0,
            requested_stake_dollars=10.0,
            line=line,
            player_name="Andrew Abbott",
            game_pk="777",
            commence_time=commence,
        )
    )


def _evict(key="a1", **kwargs):
    """Place `key` and two more; the cap of 2 archives `key` ungraded."""
    _place(key, **kwargs)
    # The fillers share the slate, so a window test is not muddied by them.
    slate = kwargs.get("selected_date", DATE)
    _place(f"{key}-live1", selected_date=slate)
    _place(f"{key}-live2", selected_date=slate)
    archived = [o for o in ledger.archived_orders() if o["position_key"] == key]
    assert len(archived) == 1 and archived[0]["outcome"] is None, "the trim did not evict the row"
    assert key not in {o["position_key"] for o in ledger._load()["orders"]}
    return archived[0]


class _Resolver:
    """A resolver factory that counts what it was asked."""

    def __init__(self, value, *, is_final=True):
        self.value, self.is_final = value, is_final
        self.dates: list[str] = []
        self.asked: list[str] = []

    def __call__(self, selected_date):
        self.dates.append(selected_date)

        def resolve(order):
            self.asked.append(str(order.get("position_key")))
            return {"current_value": self.value, "is_final": self.is_final, "started": True}

        return resolve


def _shard() -> Path:
    return ledger._archive_dir() / f"orders_{DATE[:7]}.jsonl"


def _last_copy(key):
    return next(o for o in ledger.archived_orders() if o["position_key"] == key)


# --- reachability FIRST: off and on must differ ------------------------------


def test_off_is_not_on_the_worker_hook_grades_only_when_enabled(monkeypatch):
    _evict("a1")
    resolver = _Resolver(9.0)
    monkeypatch.setattr(settle, "_default_resolver", resolver)
    before = _shard().read_bytes()

    off = settle.maybe_settle_archived(today=TODAY)
    assert off == {"status": "skipped", "reason": "disabled"}
    assert _shard().read_bytes() == before
    assert resolver.asked == []
    assert _last_copy("a1")["outcome"] is None

    monkeypatch.setenv(settle.ARCHIVED_GRADING_ENV, "on")
    on = settle.maybe_settle_archived(today=TODAY)
    assert on["status"] == "ok" and on["graded"] == 1 and on["appended"] == 1
    assert resolver.asked == ["a1"]
    assert _last_copy("a1")["outcome"] == "won"
    assert _shard().read_bytes() != before


def test_absent_env_is_off_and_unknown_values_are_off(monkeypatch):
    assert settle.archived_grading_enabled() is False
    for value in ("", "0", "off", "false", "maybe"):
        monkeypatch.setenv(settle.ARCHIVED_GRADING_ENV, value)
        assert settle.archived_grading_enabled() is False, value
    monkeypatch.setenv(settle.ARCHIVED_GRADING_ENV, "on")
    assert settle.archived_grading_enabled() is True


def test_the_worker_tick_calls_the_hook_after_settle_orders():
    """The call site, pinned: deleting it would leave a default-off pass that
    stays off even when enabled, which no other test here would notice."""
    source = (Path(__file__).resolve().parents[1] / "pipeline" / "intelligence_state.py").read_text(encoding="utf-8")
    settle_at = source.index("settle_orders(_settle_date)")
    hook_at = source.index("maybe_settle_archived(", settle_at)
    assert "ARCHIVED_SETTLEMENT_GUARD_SKIP" in source[hook_at : hook_at + 600]


# --- the graded copy wins ----------------------------------------------------


def test_the_graded_copy_is_appended_and_wins_in_every_history_reader():
    _evict("a1")
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(9.0))
    assert result["graded"] == 1

    lines = [line for line in _shard().read_text(encoding="utf-8").splitlines() if '"a1"' in line]
    assert len(lines) == 2, "appended beside the ungraded copy, not rewritten over it"

    copies = [o for o in ledger.archived_orders() if o["position_key"] == "a1"]
    assert len(copies) == 1 and copies[0]["outcome"] == "won"
    assert copies[0]["graded_from"] == settle.GRADED_FROM_ARCHIVE
    assert copies[0]["pnl_dollars"] == pytest.approx(9.0909, abs=1e-3)

    history = [o for o in ledger.full_history_orders() if o["position_key"] == "a1"]
    assert len(history) == 1 and history[0]["outcome"] == "won"
    summary = settle.settlement_summary(DATE, orders=ledger.full_history_orders())
    assert summary["total"]["won"] == 1


def test_a_row_graded_from_the_archive_carries_the_fields_a_live_grade_does():
    _evict("a1")
    settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(9.0))
    live_result = settle.settle_orders(DATE, resolver=_Resolver(9.0)(DATE), closer=lambda rows, d: {"rows": []})
    assert live_result["graded"] == 2

    archived = _last_copy("a1")
    live = next(o for o in ledger._load()["orders"] if o["position_key"] == "a1-live1")
    for field in ("outcome", "pnl_dollars", "pnl_gross_dollars", "settled_value", "graded_at"):
        assert archived.get(field) is not None, field
        assert live.get(field) is not None, field
    assert archived["outcome"] == live["outcome"]
    assert archived["pnl_dollars"] == live["pnl_dollars"]


# --- grade once --------------------------------------------------------------


def test_grade_once_a_second_pass_neither_asks_nor_appends_nor_regrades():
    _evict("a1")
    first = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(9.0))
    assert first["graded"] == 1
    size = _shard().stat().st_size

    # A later read that DISAGREES (a stat correction, a cache miss) must not
    # change a settled bet.
    second_resolver = _Resolver(3.0)
    second = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=second_resolver)
    assert second["candidates"] == 0 and second["graded"] == 0 and second["appended"] == 0
    assert second_resolver.asked == []
    assert _shard().stat().st_size == size
    assert _last_copy("a1")["outcome"] == "won"


def test_a_held_lock_refuses_rather_than_grading_twice(monkeypatch):
    from contextlib import nullcontext

    _evict("a1")
    monkeypatch.setattr(settle, "_archived_grading_lock", lambda: nullcontext(False))
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(9.0))
    assert result == {"status": "skipped", "reason": "busy"}
    assert _last_copy("a1")["outcome"] is None


# --- the live document wins ----------------------------------------------------


def test_a_live_row_beats_its_archived_copy():
    """A row present in BOTH places is `settle_orders`' to grade. Grading the
    archived copy would be invisible (`_with_archive` serves the document's) at
    best, and a second, different grade at worst."""
    from syndicate.features.shared.refresh_state_store import write_json_file

    archived_row = _evict("a1")
    doc = ledger._load()
    doc.pop(ledger._BASELINE_KEY, None)
    doc["orders"] = list(doc["orders"]) + [dict(archived_row)]
    write_json_file(ledger._ledger_path(), doc)
    size = _shard().stat().st_size

    resolver = _Resolver(9.0)
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=resolver)
    assert result["in_live_document"] == 1
    assert result["candidates"] == 0 and result["graded"] == 0
    assert resolver.asked == []
    assert _shard().stat().st_size == size


# --- a push is not a loss ------------------------------------------------------


def test_a_decided_tie_is_a_PUSH_with_the_stake_returned():
    _evict("a1", line=7.0)
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(7.0))
    assert result["outcomes"] == {"push": 1}
    row = _last_copy("a1")
    assert row["outcome"] == "push"
    assert row["pnl_gross_dollars"] == 0.0
    summary = settle.settlement_summary(DATE, orders=ledger.full_history_orders())
    assert summary["total"]["push"] == 1 and summary["total"]["lost"] == 0


# --- what is not a candidate ---------------------------------------------------


def test_a_game_not_yet_started_is_not_asked_and_an_undecided_one_stays_ungraded():
    _evict("future", commence=NOT_STARTED)
    _evict("running")
    # 3 strikeouts so far against over 6.5, game still running: not decided.
    resolver = _Resolver(3.0, is_final=False)
    result = settle.settle_archived_orders(
        today=TODAY, enabled=True, resolver_factory=resolver, include_rows=True
    )
    assert result["game_not_started"] == 1
    assert "future" not in resolver.asked
    assert result["graded"] == 0 and result["appended"] == 0
    assert "running" in resolver.asked
    assert set(result["ungraded"]) == {settle.REASON_NOT_DECIDED}
    reasons = {row["identity"]: row["reason"] for row in result["rows"]}
    assert settle.REASON_GAME_NOT_STARTED in reasons.values()
    assert _last_copy("running")["outcome"] is None


def test_live_money_rows_and_unfilled_rows_in_the_archive_are_never_candidates():
    _evict("a1")
    template = _last_copy("a1")
    ledger._archive_rows(
        [
            {**template, "idempotency_key": "live-1", "position_key": "live-1", "mode": "live"},
            {**template, "idempotency_key": "unfilled-1", "position_key": "unfilled-1", "status": "rejected"},
        ]
    )
    resolver = _Resolver(9.0)
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=resolver)
    assert resolver.asked == ["a1"]
    assert result["graded"] == 1
    assert _last_copy("live-1")["outcome"] is None


def test_the_window_bounds_slates_and_defers_beyond_max_dates():
    _evict("old", selected_date="2026-09-20")
    _evict("d1", selected_date="2026-10-09")
    _evict("d2", selected_date="2026-10-10")
    resolver = _Resolver(9.0)
    result = settle.settle_archived_orders(
        today=TODAY, enabled=True, resolver_factory=resolver, max_age_days=14, max_dates=1
    )
    assert "old" not in resolver.asked
    assert result["dates"] == ["2026-10-10"] and result["deferred_dates"] == ["2026-10-09"]
    assert resolver.asked == ["d2"]


# --- refusals ------------------------------------------------------------------


def test_an_unreadable_live_document_refuses_rather_than_reading_as_empty(monkeypatch):
    _evict("a1")

    def broken():
        raise ledger.LedgerError("store read failed")

    monkeypatch.setattr(ledger, "_read_for_merge", broken)
    resolver = _Resolver(9.0)
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=resolver)
    assert result == {"status": "skipped", "reason": "live_document_unreadable"}
    assert resolver.asked == []


def test_an_empty_live_document_beside_an_archive_is_refused(monkeypatch):
    _evict("a1")
    monkeypatch.setattr(ledger, "_read_for_merge", lambda: {"orders": []})
    result = settle.settle_archived_orders(today=TODAY, enabled=True, resolver_factory=_Resolver(9.0))
    assert result == {"status": "skipped", "reason": "live_document_empty"}


def test_a_dry_run_grades_in_memory_and_writes_nothing():
    _evict("a1")
    before = _shard().read_bytes()
    result = settle.settle_archived_orders(today=TODAY, enabled=True, dry_run=True, resolver_factory=_Resolver(9.0))
    assert result["graded"] == 1 and result["appended"] == 0
    assert _shard().read_bytes() == before
    assert not (ledger._archive_dir() / ".archived_grading.lock").exists()


def test_the_worker_hook_runs_at_most_hourly_and_honours_its_guard(monkeypatch):
    _evict("a1")
    monkeypatch.setattr(settle, "_default_resolver", _Resolver(9.0, is_final=False))
    monkeypatch.setenv(settle.ARCHIVED_GRADING_ENV, "on")

    assert settle.maybe_settle_archived(today=TODAY, guard=lambda: True) == {
        "status": "skipped",
        "reason": "memory_guard",
    }
    assert settle.maybe_settle_archived(today=TODAY)["status"] == "ok"
    assert settle.maybe_settle_archived(today=TODAY) == {"status": "skipped", "reason": "interval"}


# --- the one-off backfill's dry run --------------------------------------------


def test_the_backfill_dry_run_reports_the_verdict_and_writes_nothing(monkeypatch, capsys):
    from scripts import backfill_archived_paper_grades as backfill

    _evict("a1")
    monkeypatch.setattr(settle, "_default_resolver", _Resolver(9.0))
    before = _shard().read_bytes()
    doc_before = ledger._ledger_path().read_bytes()

    code = backfill.main(["--since", "2026-10-01", "--today", TODAY])
    assert code == 0
    out = capsys.readouterr().out
    assert '"would_grade": 1' in out and "CONFIRMED" in out
    assert _shard().read_bytes() == before
    assert ledger._ledger_path().read_bytes() == doc_before
    assert not (ledger._archive_dir() / ".archived_grading.lock").exists()


def test_the_backfill_dry_run_suppresses_and_counts_resolver_side_writes():
    import collections

    from scripts import backfill_archived_paper_grades as backfill
    from syndicate.features.shared import bet_status_soccer, refresh_state_store

    writes = collections.Counter()
    original = refresh_state_store.write_json_file
    with backfill.suppressed_writes(writes):
        bet_status_soccer._remember_finals("2026-10-10", [{"final": True}])
        refresh_state_store.write_json_file(Path("x.json"), {})
        with pytest.raises(RuntimeError):
            ledger._archive_rows([{"selected_date": DATE}])
    assert writes == {"soccer_remember_finals": 1, "refresh_state_store_write": 1}
    assert refresh_state_store.write_json_file is original
