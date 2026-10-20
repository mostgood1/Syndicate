"""Paper books keep recording while the fleet trades live (lane paper-alongside-live).

Measured 2026-10-20: `local_production.env` sets `SYNDICATE_EXECUTION_MODE=live` on
every role, so refresh-worker's inline paper harness refused every build
(`REFUSED_LIVE_INLINE` x634) and no paper row was written after go-live. These
tests pin that the inline caller now books PAPER under a live env, that it never
reaches a venue, that it stamps its approach tags, and that live placement and
live accounting are unchanged by the paper rows beside them.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.execution_ledger import _load, ledger_summary

from tests.test_execute_portfolio import _TICKER, _row, _write_live_plan, _write_plan

TAGS = ("selection", "season_phase", "paper_alongside_live")


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
        "SYNDICATE_PAPER_ALONGSIDE_LIVE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _live_env(monkeypatch):
    """The fleet's env since 2026-10-19 16:04Z, on every role."""
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi,polymarket")


def _no_venue_contact(monkeypatch):
    """Any venue read or adapter lookup fails the test."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared import execution_ledger

    def explode(*args, **kwargs):
        raise AssertionError("the paper harness must never reach a venue")

    monkeypatch.setattr(runner, "_venue_submitter", explode)
    monkeypatch.setattr(execution_ledger, "reconcile_live_orders", explode)


def _rows(mode=None, venue=None):
    return [
        o
        for o in _load().get("orders") or []
        if (mode is None or o.get("mode") == mode) and (venue is None or o.get("venue") == venue)
    ]


# --------------------------------------------------------------------------
# Reachability -- off != on
# --------------------------------------------------------------------------


def test_off_refuses_and_default_books_paper(monkeypatch):
    """OFF is the old behaviour (refused, nothing written); absent books paper."""
    from pipeline import execute_portfolio as runner

    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    _live_env(monkeypatch)
    _no_venue_contact(monkeypatch)

    monkeypatch.setenv("SYNDICATE_PAPER_ALONGSIDE_LIVE", "off")
    off = runner.run_execution("2026-08-22", inline=True)
    assert off["status"] == "skipped"
    assert off["reason"] == "live_mode_refused_inline"
    assert ledger_summary()["orders"] == 0

    monkeypatch.delenv("SYNDICATE_PAPER_ALONGSIDE_LIVE")
    on = runner.run_execution("2026-08-22", inline=True)
    assert on["status"] == "ok"
    assert on["mode"] == "paper"
    assert on["venue"] == "paper"
    assert on["paper_alongside_live"] is True
    assert on["placed"] == 2
    rows = _rows()
    assert len(rows) == 2
    assert {o["mode"] for o in rows} == {"paper"}
    assert {o["status"] for o in rows} == {"filled"}


@pytest.mark.parametrize("value", ["0", "false", "no", "OFF"])
def test_every_off_spelling_refuses(monkeypatch, value):
    from pipeline import execute_portfolio as runner

    _write_plan(monkeypatch, [_row()])
    _live_env(monkeypatch)
    monkeypatch.setenv("SYNDICATE_PAPER_ALONGSIDE_LIVE", value)
    assert runner.run_execution("2026-08-22", inline=True)["reason"] == "live_mode_refused_inline"
    assert ledger_summary()["orders"] == 0


def test_paper_env_is_unchanged_and_untagged_as_alongside(monkeypatch):
    """With the env on paper nothing changes except the tags, and the row says it
    was NOT booked alongside live."""
    from pipeline import execute_portfolio as runner

    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    result = runner.run_execution("2026-08-22", inline=True)
    assert result["mode"] == "paper"
    assert result["paper_alongside_live"] is False
    (row,) = _rows()
    assert row["paper_alongside_live"] is False


# --------------------------------------------------------------------------
# The paper2 venue books, and the tags
# --------------------------------------------------------------------------


def test_scoped_run_books_the_venue_paper_book_with_tags(monkeypatch):
    """paper2's venue plan carries no `suggested_gate`; the selection comes from
    the unrestricted plan of the same build."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.season_phase import season_phase

    plan = _write_plan(monkeypatch, [_row(venue_ticker=_TICKER)])
    assert isinstance(plan.get("suggested_gate"), dict)
    venue_plan = {k: v for k, v in plan.items() if k != "suggested_gate"}
    monkeypatch.setattr(
        "pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, scope: venue_plan
    )
    _live_env(monkeypatch)
    _no_venue_contact(monkeypatch)

    result = runner.run_execution("2026-08-22", inline=True, venue_scope="kalshi")
    assert result["status"] == "ok"
    assert result["mode"] == "paper"
    assert result["venue"] == "paper:kalshi"
    assert result["plan_source"] == "paper2"
    (row,) = _rows(venue="paper:kalshi")
    assert row["mode"] == "paper"
    assert row["selection"] == "suggested_only"
    assert row["season_phase"] == season_phase("mlb", "2026-08-22") == "regular"
    assert row["paper_alongside_live"] is True
    # The fields the study and the tuner already read are all there.
    for field in ("ev_pct", "model_edge_pct", "sport", "market", "opening_key", "selected_date"):
        assert field in row


def test_a_plan_with_no_gate_claims_no_selection(monkeypatch):
    """Unknown must not take a label: no `suggested_gate` anywhere -> None."""
    from pipeline import execute_portfolio as runner

    plan = _write_plan(monkeypatch, [_row()])
    bare = {k: v for k, v in plan.items() if k != "suggested_gate"}
    monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan", lambda date: bare)
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    runner.run_execution("2026-08-22", inline=True)
    (row,) = _rows()
    assert row["selection"] is None


# --------------------------------------------------------------------------
# Live is untouched -- placement, accounting, and row shape
# --------------------------------------------------------------------------


def test_paper_rows_do_not_touch_live_accounting_or_block_live(monkeypatch):
    """Paper first, then the live executor on the SAME bet: live still places,
    paper is not charged to live caps, and the live row has its old shape."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.execution_guard import spent_today
    from syndicate.features.shared.execution_ledger import unreconciled_orders

    _write_live_plan(monkeypatch, [_row(venue_ticker=_TICKER)])
    _live_env(monkeypatch)
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")

    paper = runner.run_execution("2026-08-22", inline=True, venue_scope="kalshi")
    assert paper["mode"] == "paper" and paper["placed"] == 1
    assert spent_today("2026-08-22", venue="kalshi", mode="live") == {"dollars": 0.0, "orders": 0}
    assert spent_today("2026-08-22", venue=None, mode="live") == {"dollars": 0.0, "orders": 0}
    assert unreconciled_orders() == []

    submitted = []

    def submitter(request):
        submitted.append(request)
        return {"status": "filled", "fill_price": 0.46, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: submitter)
    live = runner.run_execution("2026-08-22", venue_scope="kalshi")
    assert live["mode"] == "live"
    assert live["placed"] == 1, live
    assert len(submitted) == 1
    assert "already_held_other_slate" not in live["refused"]

    (live_row,) = _rows(mode="live")
    (paper_row,) = _rows(mode="paper")
    assert live_row["venue"] == "kalshi"
    assert paper_row["venue"] == "paper:kalshi"
    assert live_row["idempotency_key"] != paper_row["idempotency_key"]
    for tag in TAGS:
        assert tag not in live_row, f"live row grew a paper tag: {tag}"
    # Live spend is the live order only. A live order is charged to the day it
    # was PLACED (todo #707 D2, 72407b6c), and this one was placed now.
    from syndicate.features.shared.timezone import central_today_iso

    assert spent_today(central_today_iso(), venue="kalshi", mode="live")["orders"] == 1


def test_live_first_then_paper_still_records_paper(monkeypatch):
    """A bet live already holds is still a paper bet: the paper book is the whole
    plan, not the plan minus what live took."""
    from pipeline import execute_portfolio as runner

    _write_live_plan(monkeypatch, [_row(venue_ticker=_TICKER)])
    _live_env(monkeypatch)
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    monkeypatch.setattr(
        runner,
        "_venue_submitter",
        lambda venue: (lambda r: {"status": "filled", "fill_price": 0.46, "fill_stake_dollars": 0.92}),
    )
    assert runner.run_execution("2026-08-22", venue_scope="kalshi")["placed"] == 1

    _no_venue_contact(monkeypatch)
    paper = runner.run_execution("2026-08-22", inline=True, venue_scope="kalshi")
    assert paper["mode"] == "paper"
    assert paper["placed"] == 1
    assert len(_rows(mode="live")) == 1
    assert len(_rows(mode="paper", venue="paper:kalshi")) == 1


def test_a_rerun_is_a_duplicate_not_a_second_bet(monkeypatch):
    from pipeline import execute_portfolio as runner

    _write_plan(monkeypatch, [_row()])
    _live_env(monkeypatch)
    first = runner.run_execution("2026-08-22", inline=True)
    second = runner.run_execution("2026-08-22", inline=True)
    assert first["placed"] == 1
    assert second["placed"] == 0 and second["duplicates"] == 1
    assert len(_rows()) == 1
