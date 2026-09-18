"""A paper run reads the execution ledger once and writes it once.

Lane `paper-execution-ledger-batch`, 2026-09-18. `run_execution` used to load
the whole ledger once per POSITION (`_status_of`, then again in `place_order`
-> `record_order`, duplicates included) and `_persist` it twice per new order.
At 6.1 MB / 5,000 rows on refresh-worker that held the board thread for a
median 189-304 s per build. These tests pin the I/O count AND that the rows the
batch writes are the rows the per-order path wrote.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import execution_ledger
from syndicate.features.shared.portfolio_settings import PortfolioSettings

DATE = "2026-08-22"
_TIMESTAMPS = ("submitted_at", "venue_resolved_at", "settled_at")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in (
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_VENUE",
        "SYNDICATE_PORTFOLIO_COMMIT_ENABLED",
        "SYNDICATE_REFRESH_STATE_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _row(**overrides):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-08-22T23:05:00Z",
        "side": "home",
        "quote": {"price": -110, "bookmaker": "draftkings"},
        "ev_pct": 4.5,
        "model_edge_pct": 3.2,
        "score": {"score": 5.1, "price_reliability": 0.82},
    }
    row.update(overrides)
    return row


def _write_plan(monkeypatch, rows):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": rows})
    from pipeline import portfolio_commit as commit

    monkeypatch.setattr(
        "syndicate.features.shared.portfolio_commit.resolve_settings",
        lambda: PortfolioSettings(
            bankroll_units=1000.0,
            max_slate_exposure_fraction=1.0,
            min_ev_pct=-100.0,
            max_positions=50,
            min_stake_units=0.0,
        ),
    )
    result = commit.run_portfolio_commit(DATE)
    assert result["status"] == "ok", result
    return result["plan"]


def _three_games():
    return [_row(event_id=f"evt-{i}", home_team=f"Home{i}", away_team=f"Away{i}") for i in range(3)]


def _count_io(monkeypatch):
    """Count STORE reads of the ledger and `_persist` calls.

    Store reads, not `_load` calls: while a batch is open, `_load` on its thread
    answers from the batch without touching the store, and that is the point.
    `read_json_file` is what `_load` calls when it does go to the store.
    """
    counts = {"load": 0, "persist": 0}
    real_read, real_persist = execution_ledger.read_json_file, execution_ledger._persist

    def read(path, *args, **kwargs):
        if str(path) == str(execution_ledger._ledger_path()):
            counts["load"] += 1
        return real_read(path, *args, **kwargs)

    def persist(state):
        counts["persist"] += 1
        return real_persist(state)

    monkeypatch.setattr(execution_ledger, "read_json_file", read)
    monkeypatch.setattr(execution_ledger, "_persist", persist)
    return counts


def _stored_rows():
    rows = execution_ledger._load().get("orders") or []
    return sorted(
        ({k: v for k, v in row.items() if k not in _TIMESTAMPS} for row in rows),
        key=lambda r: str(r.get("idempotency_key")),
    )


# --------------------------------------------------------------------------
# The I/O count -- the thing the lane exists to change
# --------------------------------------------------------------------------


def test_a_paper_run_writes_the_ledger_once_however_many_orders_it_places(monkeypatch):
    plan = _write_plan(monkeypatch, _three_games())
    assert plan["totals"]["positions"] == 3
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    io = _count_io(monkeypatch)
    result = runner.run_execution(DATE)

    assert result["placed"] == 3, result
    # Was 2 per new order (record_order, then complete_order): 6 here.
    assert io["persist"] == 1, io
    # unreconciled_orders + spent_today + the batch + ledger_summary's two.
    # Was 16 here: those 4, plus per position `_status_of`, `record_order` and
    # `check_order`'s account-wide `spent_today`, plus `complete_order` per new
    # order. About 560 on a real build.
    assert io["load"] <= 5, io
    assert execution_ledger.ledger_summary(DATE)["orders"] == 3


def test_a_rerun_of_the_same_plan_writes_nothing_and_counts_every_duplicate(monkeypatch):
    _write_plan(monkeypatch, _three_games())
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    runner.run_execution(DATE)
    io = _count_io(monkeypatch)
    second = runner.run_execution(DATE)

    assert second["placed"] == 0 and second["duplicates"] == 3, second
    assert io["persist"] == 0, io
    # Was 4 + 2 per position = 10: every duplicate paid two full loads.
    assert io["load"] <= 5, io
    assert execution_ledger.ledger_summary(DATE)["orders"] == 3


# --------------------------------------------------------------------------
# Same rows as the per-order path -- fewer round trips must not mean other rows
# --------------------------------------------------------------------------


def _requests(monkeypatch):
    plan = _write_plan(monkeypatch, _three_games())
    from pipeline import execute_portfolio as runner

    return [runner._order_from_position(p, DATE, runner.PAPER_VENUE) for p in plan["positions"]]


def test_the_batch_stores_exactly_the_rows_place_order_stores(monkeypatch, tmp_path):
    requests = _requests(monkeypatch)
    assert all(requests) and len(requests) == 3

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "per_order"))
    single = [execution_ledger.place_order(r, mode="paper") for r in requests]
    per_order_rows = _stored_rows()

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "batched"))
    batch = execution_ledger.PaperLedgerBatch("paper")
    batched = [batch.place(r) for r in requests]
    assert batch.flush() == 3
    batched_rows = _stored_rows()

    assert batched_rows == per_order_rows
    assert all(row["status"] == "filled" for row in batched_rows)
    # What each call RETURNS is the same too: the loop reads status off it.
    strip = lambda row: {k: v for k, v in row.items() if k not in _TIMESTAMPS}  # noqa: E731
    assert [strip(r) for r in batched] == [strip(r) for r in single]


def test_a_rejected_row_is_retried_in_a_batch_exactly_as_one_order_would_be(monkeypatch, tmp_path):
    """The rejected-retry rule lives in `_record_into_state`, which both paths
    share: the rejected row is popped and its attempt carried in `prior_attempts`."""
    request = _requests(monkeypatch)[0]

    def seed_rejected():
        record, created = execution_ledger.record_order(request, mode="paper")
        assert created
        execution_ledger.complete_order(record["idempotency_key"], status="rejected", error="route_410")

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "per_order"))
    seed_rejected()
    execution_ledger.place_order(request, mode="paper")
    per_order_rows = _stored_rows()

    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path / "batched"))
    seed_rejected()
    batch = execution_ledger.PaperLedgerBatch("paper")
    assert batch.status_of(request) == "rejected"
    batch.place(request)
    assert batch.flush() == 1
    batched_rows = _stored_rows()

    assert len(batched_rows) == 1 and batched_rows[0]["status"] == "filled"
    strip_attempts = lambda rows: [  # noqa: E731
        {**r, "prior_attempts": [{k: v for k, v in a.items() if "_at" not in k} for a in r.get("prior_attempts") or []]}
        for r in rows
    ]
    assert strip_attempts(batched_rows) == strip_attempts(per_order_rows)
    assert batched_rows[0]["prior_attempts"], "the rejected attempt must be carried, not dropped"


def test_the_same_bet_twice_in_one_run_is_placed_once(monkeypatch):
    """Rows placed earlier in the run are visible to later positions, exactly as
    they were when each order was written before the next was checked."""
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner
    from pipeline import portfolio_commit as commit
    from syndicate.features.shared.refresh_state_store import write_json_file

    plan = commit.read_portfolio_plan(DATE)
    plan["positions"] = [plan["positions"][0], dict(plan["positions"][0])]
    write_json_file(commit.portfolio_plan_path(DATE), plan)

    result = runner.run_execution(DATE)

    assert result["placed"] == 1 and result["duplicates"] == 1, result
    assert execution_ledger.ledger_summary(DATE)["orders"] == 1


def test_the_account_wide_cap_still_counts_this_runs_own_unplaced_writes(monkeypatch):
    """`check_order` reads account-wide spend from the ledger for EACH new order.
    Per-order writes made the run's earlier orders visible to that read; a batch
    holds them unflushed, so `_load` on the batch's thread answers from the
    batch. Without that, a 3-position run under a 2-order ceiling places 3."""
    _write_plan(monkeypatch, _three_games())
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS_ALL_VENUES", "2")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution(DATE)

    assert result["placed"] == 2, result
    assert result["refused"] == {"over_max_day_orders_all_venues": 1}, result
    assert execution_ledger.ledger_summary(DATE)["orders"] == 2


def test_another_thread_reads_the_store_while_a_batch_is_open(monkeypatch):
    """The batch's view is for its OWN thread. Settlement and the other loops on
    refresh-worker share the process, and must never see rows the store does not
    hold -- nor lose sight of the store's rows."""
    import threading

    request = _requests(monkeypatch)[0]
    batch = execution_ledger.PaperLedgerBatch("paper")
    batch.place(request)

    seen = {}
    worker = threading.Thread(target=lambda: seen.setdefault("other", len(execution_ledger._load()["orders"])))
    worker.start()
    worker.join()

    assert len(execution_ledger._load()["orders"]) == 1  # this thread: the batch
    assert seen["other"] == 0  # another thread: the store, unflushed row absent
    assert batch.flush() == 1
    worker = threading.Thread(target=lambda: seen.__setitem__("other", len(execution_ledger._load()["orders"])))
    worker.start()
    worker.join()
    assert seen["other"] == 1
    assert execution_ledger._BATCH_VIEW.state is None, "a flushed batch must close its view"


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------


def test_a_raise_mid_run_still_keeps_the_orders_placed_before_it(monkeypatch):
    """The per-order writes kept everything before a raise. The batch must too:
    `run_execution`'s `finally` flushes it on the way out."""
    _write_plan(monkeypatch, _three_games())
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    real = runner._order_from_position
    seen = {"n": 0}

    def third_one_raises(position, selected_date, venue):
        seen["n"] += 1
        if seen["n"] == 3:
            raise RuntimeError("boom on the third position")
        return real(position, selected_date, venue)

    monkeypatch.setattr(runner, "_order_from_position", third_one_raises)
    with pytest.raises(RuntimeError, match="boom on the third position"):
        runner.run_execution(DATE)

    assert execution_ledger.ledger_summary(DATE)["orders"] == 2


def test_a_live_batch_is_refused_at_construction():
    """A live row must exist BEFORE its send, one order at a time. A batch would
    defer the record past the send, so it cannot be built for live at all."""
    with pytest.raises(ValueError, match="paper-only"):
        execution_ledger.PaperLedgerBatch(execution_ledger.LIVE)


def test_live_mode_places_through_place_order_not_a_batch(monkeypatch):
    """Reachability of the live branch: armed live mode must never construct a
    batch, and must still hand each order to `place_order`."""
    _write_plan(monkeypatch, [_row(venue_ticker="KXMLBGAME-26AUG22AWAYHOME-HOME")])
    from pipeline import execute_portfolio as runner
    from pipeline import portfolio_commit as commit

    plan = commit.read_portfolio_plan(DATE)
    monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, scope: plan)
    monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda date, scope: plan)
    for key, value in (
        ("SYNDICATE_EXECUTION_ENABLED", "1"),
        ("SYNDICATE_EXECUTION_MODE", "live"),
        ("SYNDICATE_EXECUTION_LIVE_ARMED", "1"),
        ("SYNDICATE_EXECUTION_VENUE", "kalshi"),
    ):
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: (lambda request: {"status": "filled"}))

    constructed = {"n": 0}
    real_init = execution_ledger.PaperLedgerBatch.__init__

    def counting_init(self, mode):
        constructed["n"] += 1
        real_init(self, mode)

    monkeypatch.setattr(execution_ledger.PaperLedgerBatch, "__init__", counting_init)
    placed_via = []
    monkeypatch.setattr(
        runner, "place_order", lambda request, submit=None: placed_via.append(request) or {"status": "submitted"}
    )

    result = runner.run_execution(DATE, venue_scope="kalshi")

    assert result["status"] == "ok", result
    assert constructed["n"] == 0
    assert len(placed_via) == 1
