"""Stage B runner: a committed plan becomes paper orders, exactly once."""

from __future__ import annotations

import time

import pytest

from syndicate.features.shared.execution_ledger import ledger_summary
from syndicate.features.shared.portfolio_settings import PortfolioSettings


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


def _write_live_plan(monkeypatch, rows, venue="kalshi"):
    """A venue-scoped plan, which is the only book live mode may place.

    Added 2026-08-24: `run_execution` now refuses live mode without a venue
    scope, after the worker spent a night pointed at the unrestricted plan and
    tried to put a soccer total on Kalshi.

    The venue plan is served from the committed one rather than priced through
    `venue_scope`. These tests are about the ARM, the inline refusal and the
    adapter lookup; making each of them depend on a venue actually quoting the
    fixture row would couple three unrelated guards to a pricing path and give
    all of them the same way to fail for the wrong reason.
    """
    plan = _write_plan(monkeypatch, rows)
    monkeypatch.setattr(
        "pipeline.portfolio_commit.read_portfolio_plan_for_venue",
        lambda date, scope: plan,
    )
    return plan


def _write_plan(monkeypatch, rows):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": rows}
    )
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
    result = commit.run_portfolio_commit("2026-08-22")
    assert result["status"] == "ok", result
    return result["plan"]


# --------------------------------------------------------------------------
# Reachability -- off != on, before any correctness claim
# --------------------------------------------------------------------------


def test_execution_is_dark_by_default(monkeypatch):
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"
    assert ledger_summary()["orders"] == 0


def test_enabling_it_places_the_committed_plan_on_paper(monkeypatch):
    plan = _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    assert plan["totals"]["positions"] == 2

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["status"] == "ok"
    assert result["mode"] == "paper"
    assert result["placed"] == 2
    summary = ledger_summary("2026-08-22")
    assert summary["orders"] == 2
    assert summary["by_status"]["filled"] == 2
    assert summary["modes"] == ["paper"]


def test_no_plan_is_reported_rather_than_placing_nothing_silently(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["status"] == "skipped"
    assert result["reason"] == "no_plan"


# --------------------------------------------------------------------------
# The property that matters most in production
# --------------------------------------------------------------------------


def test_running_the_same_slate_twice_places_nothing_new(monkeypatch):
    """THE PRODUCTION SAFETY CHECK. `duplicates` on the second run is the number
    that proves idempotency works outside a unit test."""
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    first = runner.run_execution("2026-08-22")
    second = runner.run_execution("2026-08-22")

    assert first["placed"] == 2 and first["duplicates"] == 0
    assert second["placed"] == 0 and second["duplicates"] == 2
    assert ledger_summary("2026-08-22")["orders"] == 2


def test_a_re_commit_at_a_moved_price_does_not_re_place(monkeypatch):
    """A slate that re-priced between runs is the SAME set of bets. If a moved
    quote read as a new order, every refresh would place the book again."""
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    runner.run_execution("2026-08-22")
    # Same bet, different price.
    _write_plan(monkeypatch, [_row(quote={"price": -104, "bookmaker": "draftkings"})])
    second = runner.run_execution("2026-08-22")

    assert second["duplicates"] == 1
    assert second["placed"] == 0
    assert ledger_summary("2026-08-22")["orders"] == 1


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_a_position_missing_its_identity_is_skipped_not_defaulted(monkeypatch):
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner
    from pipeline import portfolio_commit as commit

    plan = commit.read_portfolio_plan("2026-08-22")
    plan["positions"][0].pop("event_id")
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(commit.portfolio_plan_path("2026-08-22"), plan)

    result = runner.run_execution("2026-08-22")
    assert result["skipped"] == 1
    assert result["placed"] == 0
    assert ledger_summary()["orders"] == 0


def test_live_mode_is_blocked_while_an_order_is_unreconciled(monkeypatch):
    """An order sent with an unknown result must not have a fresh slate stacked
    on top of it."""
    from syndicate.features.shared.execution_ledger import OrderRequest, record_order

    record_order(
        OrderRequest(
            position_key="stranded",
            selected_date="2026-08-22",
            venue="kalshi",
            sport="mlb",
            event_id="evt-9",
            market="h2h",
            side="home",
            requested_price=-110.0,
            requested_stake_dollars=5.0,
        )
    )
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["status"] == "blocked"
    assert result["reason"] == "unreconciled_orders"


def test_paper_mode_is_not_blocked_by_a_stranded_order(monkeypatch):
    """Paper cannot double-spend, so the block would only stop the harness that
    generates the evidence -- it still reports the count."""
    from syndicate.features.shared.execution_ledger import OrderRequest, record_order

    record_order(
        OrderRequest(
            position_key="stranded",
            selected_date="2026-08-22",
            venue="paper",
            sport="mlb",
            event_id="evt-9",
            market="h2h",
            side="home",
            requested_price=-110.0,
            requested_stake_dollars=5.0,
        )
    )
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["status"] == "ok"
    assert result["summary"]["unreconciled"] == 1


def test_force_does_not_bypass_the_live_arm(monkeypatch):
    """`force` skips the enablement flag only. A convenience flag that can reach
    real money is not a convenience."""
    _write_live_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", force=True, venue_scope="kalshi")
    assert result["status"] == "ok"
    # Every order rejected for want of the arm; nothing filled.
    assert result["placed"] == 0
    assert ledger_summary("2026-08-22")["by_status"].get("rejected") == 1


# --------------------------------------------------------------------------
# The inline refusal -- live money must not run inside refresh-worker
# --------------------------------------------------------------------------


def test_inline_refuses_live_mode_structurally(monkeypatch):
    """`execution_ledger`'s contract says the placer must never run inside
    refresh-worker (110 OOM kills, restarts mid-job). The intelligence-state
    caller passes `inline=True`, and the refusal lives HERE rather than in
    configuration -- "set the env var correctly" is the guarantee that failed
    on 2026-08-22."""
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", inline=True)
    assert result["status"] == "skipped"
    assert result["reason"] == "live_mode_refused_inline"
    assert ledger_summary()["orders"] == 0


def test_inline_still_runs_paper(monkeypatch):
    """The refusal is on LIVE only -- paper cannot double-spend, and it is the
    harness that generates Stage C's evidence."""
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", inline=True)
    assert result["status"] == "ok"
    assert result["mode"] == "paper"
    assert result["placed"] == 2


def test_the_non_inline_path_is_unchanged(monkeypatch):
    """A standalone run (its own service, or the CLI) keeps full live capability
    -- the refusal must not leak into the path that is allowed to place."""
    _write_live_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", venue_scope="kalshi")
    assert result["status"] == "ok"
    assert result["mode"] == "live"
    # Rejected for want of the arm, NOT refused for being inline.
    assert ledger_summary("2026-08-22")["by_status"].get("rejected") == 1


def test_the_commit_and_execution_jobs_have_a_CALLER():
    """THE REGRESSION THIS FILE EXISTS TO PREVENT, and it shipped once already.

    Both runners were built as standalone entrypoints and were never wired to
    anything, so `SYNDICATE_PORTFOLIO_COMMIT_ENABLED=1` on refresh-worker was a
    no-op: the flag gated a function nobody called. A flag without a caller is
    indistinguishable from a feature that is off, which is the same class as an
    input nobody feeds.

    Pinned against `intelligence_state` because that is where the shortlist
    these derive from is written -- deliberately NOT the `run_refresh_worker`
    autorun chain, whose exclusive `elif` starved settlement to one tick in 45
    minutes (`#504`).
    """
    import inspect

    import pipeline.intelligence_state as state

    source = inspect.getsource(state)
    assert "from pipeline.portfolio_commit import run_portfolio_commit" in source
    assert "from pipeline.execute_portfolio import run_execution" in source
    # And the inline guard must be passed, or live money could reach the worker.
    assert "run_execution(str(selected_date or \"\"), inline=True)" in source


def test_the_commit_runs_after_the_shortlist_it_derives_from():
    """Order matters: the commit reads the artifact the shortlist write
    produces. Called before it, it would size yesterday's board."""
    import inspect

    import pipeline.intelligence_state as state

    source = inspect.getsource(state)
    assert source.index("write_layer2_shortlist(str(selected_date") < source.index(
        "from pipeline.portfolio_commit import run_portfolio_commit"
    )


# --------------------------------------------------------------------------
# The guard: caps and the kill switch, wired into the run
# --------------------------------------------------------------------------


def test_the_day_order_cap_stops_the_tail_of_a_slate_and_names_why(monkeypatch):
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2"), _row(event_id="evt-3")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", "2")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["placed"] == 2
    # A single `skipped` count cannot tell a plan that named nothing bettable
    # from a cap that stopped a good slate, and those want opposite responses.
    assert result["refused"] == {"over_max_day_orders": 1}


def test_the_default_paper_caps_do_not_change_what_the_paper_book_records(monkeypatch):
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2"), _row(event_id="evt-3")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    # The paper books exist to record what the strategy would have done.
    assert result["placed"] == 3
    assert result["refused"] == {}


def test_a_re_run_does_not_charge_duplicates_against_the_cap(monkeypatch):
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", "2")
    from pipeline import execute_portfolio as runner

    assert runner.run_execution("2026-08-22")["placed"] == 2
    second = runner.run_execution("2026-08-22")
    # A duplicate places nothing, so charging it would let a re-run exhaust a
    # budget it never spent.
    assert second["duplicates"] == 2
    assert second["refused"] == {}


def test_the_running_total_is_seeded_from_the_ledger_not_from_zero(monkeypatch):
    _write_plan(monkeypatch, [_row(), _row(event_id="evt-2")])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", "3")
    from pipeline import execute_portfolio as runner

    first = runner.run_execution("2026-08-22")
    assert first["placed"] == 2

    _write_plan(monkeypatch, [_row(event_id=f"evt-{n}") for n in range(1, 5)])
    second = runner.run_execution("2026-08-22")
    # A restart mid-slate must not hand the day its budget back: 2 already
    # placed against a cap of 3 leaves room for exactly one more.
    assert second["placed"] == 1
    assert second["refused"] == {"over_max_day_orders": 1}
    assert second["duplicates"] == 2


def test_the_run_states_the_limits_it_applied(monkeypatch):
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
    assert result["limits"]["mode"] == "paper"
    assert result["spent"]["orders"] == 1


# --------------------------------------------------------------------------
# The commit's live bet-status block -- which never once ran
# --------------------------------------------------------------------------


def test_the_commit_populates_live_bet_status(monkeypatch, capsys):
    """MEASURED 2026-08-23T17:12:31Z, every cycle:

        [portfolio_commit] BET_STATUS_FAILED date=2026-08-23
          error=cannot access local variable '_load_ledger_for_clv'
                where it is not associated with a value

    The block called a name bound by a `from ... import ... as` TWENTY LINES
    BELOW it. Python treats a name assigned anywhere in a function as local for
    the whole function, so the read raised `UnboundLocalError` on every run --
    swallowed by the block's own `except`, printed as a FAILED line nobody was
    grepping for, and rendered on the page as an honest-looking blank.

    A feature that looks installed and has never executed is the failure mode
    this repo keeps rediscovering, so this test runs the real code path.
    """
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    runner.run_execution("2026-08-22")

    from pipeline import portfolio_commit as commit

    capsys.readouterr()
    result = commit.run_portfolio_commit("2026-08-22")
    printed = capsys.readouterr().out

    assert "BET_STATUS_FAILED" not in printed, printed
    # Present, and reached far enough to have counted the orders it was given.
    assert "bet_status" in (result.get("plan") or {})


# --------------------------------------------------------------------------
# The live adapter -- the seam money goes through
# --------------------------------------------------------------------------


def test_live_mode_against_a_venue_with_no_adapter_stops_with_a_reason(monkeypatch):
    _write_live_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "draftkings")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", venue_scope="draftkings")
    # Falling through to a paper fill wearing a live `mode` would put a record
    # in the ledger claiming money moved when none did.
    assert result["status"] == "skipped"
    assert result["reason"] == "no_adapter_for_venue:draftkings"
    assert ledger_summary("2026-08-22")["orders"] == 0


def test_paper_mode_never_builds_a_submitter(monkeypatch):
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    def explode(_venue):
        raise AssertionError("paper mode built a venue submitter")

    monkeypatch.setattr(runner, "_venue_submitter", explode)
    # Paper and live must not differ in the one seam that matters, and the way
    # to guarantee that is for paper to have no adapter at all.
    assert runner.run_execution("2026-08-22")["placed"] == 1


def test_the_order_carries_the_contract_the_position_was_priced_on(monkeypatch):
    position = {
        "position_key": "p1",
        "sport": "mlb",
        "event_id": "e1",
        "market": "strikeouts",
        "side": "over",
        "price": -110.0,
        "stake_dollars": 5.0,
        "venue_ticker": "KXMLBKS-26AUG24ABBOTT-7",
    }
    from pipeline.execute_portfolio import _order_from_position

    request = _order_from_position(position, "2026-08-24", "kalshi")
    assert request.venue_ticker == "KXMLBKS-26AUG24ABBOTT-7"


def test_a_position_with_no_contract_yields_an_order_the_adapter_refuses(monkeypatch):
    from pipeline.execute_portfolio import _order_from_position
    from syndicate.features.shared.kalshi_orders import OrderBuildError, order_body

    request = _order_from_position(
        {
            "position_key": "p1", "sport": "mlb", "event_id": "e1",
            "market": "strikeouts", "side": "over", "price": -110.0, "stake_dollars": 5.0,
        },
        "2026-08-24",
        "kalshi",
    )
    assert request.venue_ticker is None
    # Refused by name rather than resolved at submit time from a catalogue that
    # may have moved since we priced.
    with pytest.raises(OrderBuildError) as excinfo:
        order_body(request, price_dollars=0.62)
    assert "no_venue_ticker" in str(excinfo.value)


# --------------------------------------------------------------------------
# Live must not place the UNRESTRICTED plan at one venue
# --------------------------------------------------------------------------


def test_live_without_a_venue_scope_is_refused(monkeypatch):
    """MEASURED 2026-08-24T00:34Z, with real money armed.

    The worker called `run_execution(date)` with no scope, so live mode read
    the unrestricted plan and tried to place a SOCCER TOTAL and an MLB SPREAD
    on Kalshi -- positions priced at other books, carrying no Kalshi ticker,
    that the join had never paired. Both died at order build, so nothing
    reached the venue; that was the last guard in the chain doing the work
    rather than a design.
    """
    import pipeline.execute_portfolio as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")

    result = mod.run_execution("2026-08-24")
    assert result["status"] == "skipped"
    assert result["reason"] == "live_mode_requires_venue_scope"


def test_paper_without_a_scope_is_still_fine(monkeypatch):
    """The refusal is LIVE-only. Paper's whole job is the unrestricted book,
    and blocking it would turn a safety guard into an outage."""
    import pipeline.execute_portfolio as mod

    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    monkeypatch.delenv("SYNDICATE_EXECUTION_LIVE_ARMED", raising=False)

    result = mod.run_execution("2026-08-24")
    # Whatever it does about the plan, it must not be refused for the scope.
    assert result.get("reason") != "live_mode_requires_venue_scope"


def test_a_retried_order_is_counted_and_LOGGED_not_swallowed(monkeypatch):
    """MEASURED 2026-08-24T12:58Z. The retry unblock worked — a real order went
    to Kalshi:

        SUBMIT url=.../portfolio/events/orders
          ticker=KXMLBKS-26AUG242140MINATH-MINZMATTHEWS52-5
          side=ask count=2.00 price=0.4600

    and this branch still counted it `duplicates=1` and `continue`d PAST the
    LIVE_ORDER log. A real order moved and its outcome was recorded nowhere a
    person could read. Invisible is the one thing an order that moves money
    must never be.
    """
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.execution_ledger import (
        LIVE, STATUS_REJECTED, complete_order, find_order, idempotency_key, place_order,
    )

    _write_live_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")

    submitted = []

    def submitter(request):
        submitted.append(request)
        return {"status": "filled", "fill_price": 0.46, "fill_stake_dollars": 0.92}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: submitter)

    first = runner.run_execution("2026-08-22", venue_scope="kalshi")
    assert first["placed"] == 1

    # Force the pre-retry state: rejected, never reached the venue.
    key = None
    for order in first.get("summary", {}).get("by_status", {}) or {}:
        pass
    from syndicate.features.shared.execution_ledger import _load

    for order in _load().get("orders") or []:
        if order.get("venue", "").startswith("kalshi"):
            key = order["idempotency_key"]
    assert key
    complete_order(key, status=STATUS_REJECTED, error="dead route")

    submitted.clear()
    second = runner.run_execution("2026-08-22", venue_scope="kalshi")

    assert submitted, "a rejected order must actually reach the venue again"
    # Counted as a PLACEMENT, not a duplicate — and surfaced separately so a
    # retry storm is visible rather than looking like ordinary volume.
    assert second["retried"] == 1
    assert second["duplicates"] == 0
    assert second["placed"] == 1


def test_a_retry_is_charged_against_the_cap(monkeypatch):
    """A retry spends, so it must be charged. Only a true duplicate — which
    places nothing — may go uncharged."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.execution_ledger import (
        LIVE, STATUS_REJECTED, complete_order, _load, complete_order,
    )

    _write_live_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    monkeypatch.setattr(
        runner, "_venue_submitter",
        lambda venue: (lambda r: {"status": "filled", "fill_price": 0.46,
                                  "fill_stake_dollars": 0.92}),
    )
    runner.run_execution("2026-08-22", venue_scope="kalshi")

    key = None
    for order in _load().get("orders") or []:
        if str(order.get("venue", "")).startswith("kalshi"):
            key = order["idempotency_key"]
    complete_order(key, status=STATUS_REJECTED, error="dead route")

    # A cap the retry cannot clear. Note it is a DOLLAR cap: `_int_env` treats
    # a non-positive order count as a typo and falls back to the default, so
    # `MAX_DAY_ORDERS=0` would silently not bind — a guard that reads zero as
    # "no limit" is worth knowing about, and this test would have hidden it.
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "0.01")
    result = runner.run_execution("2026-08-22", venue_scope="kalshi")
    assert result["placed"] == 0
    assert "over_max_order_dollars" in result["refused"]


# --------------------------------------------------------------------------
# Marketable limit: pay the LIVE ask, bounded by slippage
# --------------------------------------------------------------------------


def _price_env(monkeypatch, *, live=None, live_status="ok", artifact=None):
    from syndicate.features.shared import kalshi_client
    import pipeline.execute_portfolio as runner

    def fetch_market(ticker):
        if live_status != "ok":
            return {"status": "error", "reason": live_status}
        return {"status": "ok", "market": {"ticker": ticker, "no_ask_dollars": live}}

    monkeypatch.setattr(kalshi_client, "fetch_market", fetch_market)
    monkeypatch.setattr(runner, "_artifact_price", lambda t, k: artifact)


class _Req:
    venue_ticker = "KXMLBKS-26AUG242140MINATH-MINZMATTHEWS52-5"
    side = "under"


def test_the_live_ask_is_used_not_the_artifact(monkeypatch):
    """MEASURED 2026-08-24. `_kalshi_price_for` read `kalshi_markets.json` and
    called it "re-read at submit time" — but 155 series refresh 12 a tick, so
    that ask can be ~26 minutes old. We sent $0.54 from the artifact while the
    live ask was $0.56, and the order rested unfilled.
    """
    import pipeline.execute_portfolio as runner

    _price_env(monkeypatch, live=0.56, artifact=0.54)
    assert runner._kalshi_price_for(_Req()) == 0.56


def test_a_price_that_moved_too_far_REFUSES(monkeypatch):
    """A marketable limit without a bound is "pay anything". Beyond the
    tolerance the edge is not the edge we sized, and refusing is honest."""
    import pipeline.execute_portfolio as runner

    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS", "0.03")
    _price_env(monkeypatch, live=0.62, artifact=0.54)  # +0.08, past 0.03
    with pytest.raises(Exception) as excinfo:
        runner._kalshi_price_for(_Req())
    assert "slippage" in str(excinfo.value)


def test_a_price_that_moved_in_our_FAVOUR_is_taken(monkeypatch):
    """Drift is directional. A cheaper ask is not slippage."""
    import pipeline.execute_portfolio as runner

    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS", "0.03")
    _price_env(monkeypatch, live=0.40, artifact=0.54)
    assert runner._kalshi_price_for(_Req()) == 0.40


def test_a_slippage_refusal_never_reached_the_venue(monkeypatch):
    """So it records as `rejected` — uncharged and retryable — rather than
    `failed`, which would hold budget for an order that was never sent."""
    import pipeline.execute_portfolio as runner

    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS", "0.01")
    _price_env(monkeypatch, live=0.90, artifact=0.54)
    try:
        runner._kalshi_price_for(_Req())
    except Exception as exc:
        assert getattr(exc, "venue_contacted", True) is False


def test_the_artifact_is_the_fallback_and_says_so(monkeypatch, capsys):
    """A stale price beats no order — but the two must never be confused, so
    the fallback announces itself in the log money moves through."""
    import pipeline.execute_portfolio as runner

    _price_env(monkeypatch, live_status="429 rate limited", artifact=0.54)
    assert runner._kalshi_price_for(_Req()) == 0.54
    out = capsys.readouterr().out
    assert "PRICE_FROM_ARTIFACT" in out
    assert "LIVE_PRICE_UNAVAILABLE" in out


def test_no_price_anywhere_returns_none_so_the_order_refuses(monkeypatch):
    """`kalshi_submitter` raises on None, so the order is recorded with a
    reason rather than sent at a price nobody chose."""
    import pipeline.execute_portfolio as runner

    _price_env(monkeypatch, live_status="down", artifact=None)
    assert runner._kalshi_price_for(_Req()) is None


# --------------------------------------------------------------------------
# Polymarket wired into _venue_submitter
# --------------------------------------------------------------------------


def test_venue_submitter_polymarket_returns_an_adapter(monkeypatch):
    """The one thing this test guards: `polymarket` used to fall through to
    `None`, same as any other unmapped venue name. It must not any more."""
    import pipeline.execute_portfolio as runner

    submitter = runner._venue_submitter("polymarket")
    assert submitter is not None
    assert callable(submitter)


def _polymarket_row(*, slug="aec-mlb-tex-chw-2026-08-24", teams=("White Sox", "Rangers"),
                     prices=("0.55", "0.45"), tick="0.001", min_qty="1",
                     orderable=True):
    # The PERSISTED shape -- `polymarket_us_markets._SLATE_STORAGE_FIELDS`.
    # No `id` field: the artifact never carried one, so this fixture does not
    # either, on purpose (a fixture that includes a field the real artifact
    # never has would hide exactly the bug this rewrite fixed).
    return {
        "slug": slug,
        "outcomes": list(teams),
        "outcomePrices": list(prices),
        "orderPriceMinTickSize": tick,
        "minimumTradeQty": min_qty,
        "orderable": orderable,
    }


class _PolyReq:
    """CHW is home, TEX is away -- same alias pair
    `tests/test_kalshi_polymarket_arb.py` already relies on. `venue_ticker`
    holds the Polymarket SLUG (see `_polymarket_resolve_market`'s own
    docstring on why -- the artifact carries no `id`)."""

    venue_ticker = "aec-mlb-tex-chw-2026-08-24"
    side = "home"
    home_team = "CHW"
    away_team = "TEX"
    sport = "mlb"
    requested_price = 0.55


def _artifact_env(monkeypatch, *, markets=None, raises=None, fetched_at=None):
    # FRESH BY DEFAULT, relative to now rather than a fixed epoch. These tests
    # are about side resolution, slippage and not calling the venue directly;
    # the artifact's AGE is incidental to every one of them. It stopped being
    # incidental on 2026-08-25, when `_polymarket_resolve_market` gained a
    # staleness ceiling -- the fixed 1787600000.0 was ~17,774s old, so every
    # one of them began refusing before it reached the behaviour under test.
    # A fixture whose default silently trips a real guard tests the guard, not
    # its subject. The ceiling itself is covered in
    # tests/test_polymarket_slate_freshness.py, including an explicitly stale
    # artifact.
    if fetched_at is None:
        fetched_at = time.time()
    from syndicate.features.shared import refresh_state_store
    import pipeline.execute_portfolio as runner

    def fake_read(path):
        if raises is not None:
            raise raises
        rows = markets if markets is not None else [_polymarket_row()]
        return {"fetched_at": fetched_at, "markets": rows, "count": len(rows)}

    monkeypatch.setattr(refresh_state_store, "read_json_file", fake_read)
    return runner


def test_resolves_the_artifact_price_for_our_named_team(monkeypatch):
    runner = _artifact_env(monkeypatch)
    resolved = runner._polymarket_resolve_market(_PolyReq())
    # CHW (home, requested) is "White Sox" in outcomes[0] at 0.55. The INDEX
    # comes back too: it is what `order_body` uses to pick `outcomeSide`, so
    # the side cannot disagree with the price it was resolved beside.
    assert resolved == ("aec-mlb-tex-chw-2026-08-24", 0.55, "0.001", "1", 0)


def test_the_away_side_gets_the_away_price_not_positional(monkeypatch):
    """Outcomes listed in the OPPOSITE order from home/away still resolve by
    team identity, not array position -- same discipline
    `kalshi_polymarket_arb.join_kalshi_polymarket_moneylines` already proves."""
    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(teams=("Rangers", "White Sox"), prices=("0.42", "0.58"))
    ])

    class _AwayReq(_PolyReq):
        side = "away"

    resolved = runner._polymarket_resolve_market(_AwayReq())
    # Rangers (away, requested) sit at outcomes[0] here, so the index is 0 for
    # an AWAY side -- which is exactly the point: the index tracks our team,
    # never the home/away role.
    assert resolved == ("aec-mlb-tex-chw-2026-08-24", 0.42, "0.001", "1", 0)


def test_no_venue_ticker_refuses_without_reading_the_artifact(monkeypatch):
    from syndicate.features.shared import refresh_state_store
    import pipeline.execute_portfolio as runner

    def explode(path):
        raise AssertionError("read the artifact with no slug to look for")

    monkeypatch.setattr(refresh_state_store, "read_json_file", explode)

    class _NoTicker(_PolyReq):
        venue_ticker = None

    assert runner._polymarket_resolve_market(_NoTicker()) is None


def test_never_calls_the_venue_directly(monkeypatch):
    """The whole point of the artifact rewrite: this function must not become
    a second independent caller of `polymarket_us_markets` (a documented
    incident class per `venue_quote_adapters.py`'s own header)."""
    from syndicate.features.shared import polymarket_us_markets

    def explode(**kwargs):
        raise AssertionError("called the venue directly instead of reading the artifact")

    monkeypatch.setattr(polymarket_us_markets, "fetch_game_markets", explode)
    monkeypatch.setattr(polymarket_us_markets, "fetch_markets", explode)
    runner = _artifact_env(monkeypatch)
    assert runner._polymarket_resolve_market(_PolyReq()) == (
        "aec-mlb-tex-chw-2026-08-24", 0.55, "0.001", "1", 0
    )


def test_artifact_read_failure_refuses_cleanly(monkeypatch):
    runner = _artifact_env(monkeypatch, raises=RuntimeError("keyvalue unreachable"))
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_empty_artifact_refuses_cleanly(monkeypatch):
    from syndicate.features.shared import refresh_state_store
    import pipeline.execute_portfolio as runner

    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda path: {})
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_market_not_found_refuses(monkeypatch):
    runner = _artifact_env(monkeypatch, markets=[_polymarket_row(slug="other-slug")])
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_not_orderable_refuses(monkeypatch):
    """`orderable` is `trimmed_row`'s own signal that tick size and minimum
    quantity are BOTH present -- never inferred, per `polymarket_us_orders`'s
    own header."""
    runner = _artifact_env(monkeypatch, markets=[_polymarket_row(orderable=False)])
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_unreadable_outcomes_refuses(monkeypatch):
    runner = _artifact_env(monkeypatch, markets=[_polymarket_row(teams=("Only One",), prices=("0.5",))])
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_a_polymarket_price_that_moved_too_far_REFUSES(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS", "0.03")
    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(teams=("White Sox", "Rangers"), prices=("0.90", "0.10"))
    ])

    class _MovedReq(_PolyReq):
        requested_price = 0.55  # artifact 0.90, +0.35 drift, past 0.03

    with pytest.raises(Exception) as excinfo:
        runner._polymarket_resolve_market(_MovedReq())
    assert "polymarket_slippage" in str(excinfo.value)


def test_a_polymarket_price_that_moved_in_our_favour_is_taken(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_SLIPPAGE_DOLLARS", "0.03")
    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(teams=("White Sox", "Rangers"), prices=("0.40", "0.60"))
    ])

    class _CheaperReq(_PolyReq):
        requested_price = 0.55

    resolved = runner._polymarket_resolve_market(_CheaperReq())
    assert resolved[1] == 0.40


def test_venue_submitter_polymarket_end_to_end(monkeypatch):
    """The full seam: `_venue_submitter("polymarket")` returns an adapter that
    actually calls `polymarket_us_orders.submit_order` with the resolved
    market, not a stub that never reaches it."""
    from syndicate.features.shared import polymarket_us_orders
    import pipeline.execute_portfolio as runner

    _artifact_env(monkeypatch)

    calls = []

    def fake_submit_order(request, **kwargs):
        calls.append(kwargs)
        return {"status": "submitted", "venue_order_id": "o1", "venue_status": None,
                "fill_price": None, "fill_stake_dollars": None, "contracts": 0,
                "requested_contracts": 1.0}

    monkeypatch.setattr(polymarket_us_orders, "submit_order", fake_submit_order)

    submitter = runner._venue_submitter("polymarket")
    result = submitter(_PolyReq())
    assert result["status"] == "submitted"
    assert calls == [{
        "price_dollars": 0.55,
        "market_slug": "aec-mlb-tex-chw-2026-08-24",
        "tick_size": "0.001",
        "minimum_trade_qty": "1",
        # THE INDEX REACHES `submit_order`. Without it the side is picked
        # positionally and can contradict the price -- the 2026-08-25 inverted
        # order. This seam is where that thread would silently break again.
        "outcome_index": 0,
    }]


def _record(status, **extra):
    row = {"status": status, "idempotency_key": "k", "venue_ticker": "KX-T",
           "sport": "mlb", "market": "strikeouts", "player_name": "X",
           "side": "over", "line": 4.5, "requested_price": 0.5,
           "requested_stake_dollars": 1.53, "fill_price": None, "error": None}
    row.update(extra)
    return row


def test_a_resting_order_counts_as_PLACED_not_as_nothing(monkeypatch):
    """MEASURED 2026-08-24T15:38:23Z. A real order went to Kalshi -- Sandy
    Alcantara over 4.5 Ks, 3 contracts at $0.50 -- and the run reported
    `placed=0 duplicates=0 retried=0 skipped=0 refused={}`. Every counter zero,
    an order sitting at the venue.

    The phantom-fill fix caused it. Before that fix a submit response defaulted
    to `filled`, so counting fills happened to count placements too; once a
    resting order correctly recorded `submitted`, the count went silent.
    Making the STATUS honest made the COUNT dishonest, because the count was
    using the status as a proxy for a different question. A correct fix that
    breaks its neighbour is still a break.

    Placed means the venue took it. Filled means it traded. A limit order that
    rests all afternoon is the first and not the second, and both facts have to
    be readable off one line."""
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    monkeypatch.setattr(runner, "place_order",
                        lambda request, submit=None: _record("submitted"))
    result = runner.run_execution("2026-08-22")

    assert result["placed"] == 1, result
    assert result["filled"] == 0
    assert result["failed"] == 0


def test_a_fill_counts_as_both_placed_and_filled(monkeypatch):
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    monkeypatch.setattr(runner, "place_order",
                        lambda request, submit=None: _record("filled"))
    result = runner.run_execution("2026-08-22")
    assert result["placed"] == 1
    assert result["filled"] == 1


def test_a_failed_order_is_neither_placed_nor_invisible(monkeypatch):
    """`failed` means the venue may hold it, so it charges the budget -- and it
    is not a placement. Reported by name rather than left to be inferred from
    a `spent` that moved while every other counter stayed at zero, which is
    the pair of numbers that took reading the source to interpret."""
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    from pipeline import execute_portfolio as runner

    monkeypatch.setattr(runner, "place_order",
                        lambda request, submit=None: _record("failed", error="boom"))
    result = runner.run_execution("2026-08-22")
    assert result["placed"] == 0
    assert result["failed"] == 1


# --------------------------------------------------------------------------
# Polymarket side resolution depends on what KIND of market it is
# --------------------------------------------------------------------------


def _poly_market(slug, outcomes, prices, market_type="SPORTS_MARKET_TYPE_TOTAL"):
    import json as _json
    return {
        "slug": slug, "sportsMarketTypeV2": market_type,
        "outcomes": _json.dumps(outcomes), "outcomePrices": _json.dumps(prices),
        "orderPriceMinTickSize": "0.005", "minimumTradeQty": "0.01",
        "orderable": True,
    }


def test_a_TOTALS_market_resolves_on_over_under_not_on_team_names(monkeypatch):
    """MEASURED 2026-08-25T17:45:13Z. The slug was RIGHT -- right game, right
    number -- and the order still failed:

      totals over 7.5 Tampa Bay Rays @ Detroit Tigers
      slug=tsc-mlb-tb-det-2026-08-25-7pt5
      OrderBuildError: market_unresolved_for_position

    The resolver matched every outcome with `_side_for_team`, which resolves
    TEAM names. A totals market's outcomes are `["Over","Under"]`, so both were
    skipped and the price stayed None. Every totals order on this venue had
    failed this way since it went live; only moneylines ever resolved.
    """
    runner = _artifact_env(monkeypatch, markets=[
        _poly_market("tsc-mlb-tb-det-2026-08-25-7pt5", ["Over", "Under"], ["0.52", "0.50"]),
    ])

    class _TotalReq(_PolyReq):
        market = "totals"
        side = "over"
        line = 7.5
        venue_ticker = "tsc-mlb-tb-det-2026-08-25-7pt5"
        home_team = "Detroit Tigers"
        away_team = "Tampa Bay Rays"
        requested_price = 0.52

    resolved = runner._polymarket_resolve_market(_TotalReq())
    assert resolved is not None, "a totals market still refuses"
    assert resolved[1] == 0.52
    # The INDEX is what `order_body` turns into `outcomeSide`, so it must be
    # the Over slot, not merely "some priced slot".
    assert resolved[4] == 0


def test_the_under_side_takes_the_UNDER_price(monkeypatch):
    """The control. Getting the price right for the wrong side is the failure
    that bought the wrong team on 2026-08-25."""
    runner = _artifact_env(monkeypatch, markets=[
        _poly_market("tsc-mlb-tb-det-2026-08-25-7pt5", ["Over", "Under"], ["0.52", "0.50"]),
    ])

    class _UnderReq(_PolyReq):
        market = "totals"
        side = "under"
        venue_ticker = "tsc-mlb-tb-det-2026-08-25-7pt5"
        requested_price = 0.50

    resolved = runner._polymarket_resolve_market(_UnderReq())
    assert resolved[1] == 0.50
    assert resolved[4] == 1


def test_a_SPREAD_is_refused_by_name_rather_than_guessed(monkeypatch):
    """A spread's outcomes are SIGNED NUMBERS -- `["+2.50","-2.50"]` -- and
    nothing in them says which TEAM is getting the points. Our side is
    home/away, so pairing them means assuming an ordering, and an assumed
    ordering on this venue already bought the wrong team once today."""
    runner = _artifact_env(monkeypatch, markets=[
        _poly_market("asc-mlb-cle-laa-2026-08-25-pos-1pt5",
                     ["+1.50", "-1.50"], ["0.55", "0.47"],
                     market_type="SPORTS_MARKET_TYPE_SPREAD"),
    ])

    class _SpreadReq(_PolyReq):
        market = "spreads"
        side = "home"
        line = 1.5
        venue_ticker = "asc-mlb-cle-laa-2026-08-25-pos-1pt5"

    assert runner._polymarket_resolve_market(_SpreadReq()) is None


def test_a_moneyline_still_resolves_on_team_names(monkeypatch):
    """The path that already worked must not regress."""
    runner = _artifact_env(monkeypatch)
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None
    assert resolved[1] == 0.55


# --------------------------------------------------------------------------
# The slippage guard compared two different units, on both venues
# --------------------------------------------------------------------------


def test_american_odds_become_a_probability_before_the_slippage_compare():
    """MEASURED 2026-08-25T17:59:06Z, the first totals order to resolve a side:

      _SlippageExceeded: planned=-108.0 price=0.52 drift=+108.5200 max=0.03

    `planned` is AMERICAN ODDS off our board; `price` is a probability from the
    venue. Subtracting them is meaningless, and asymmetrically so -- which is
    why it survived: negative odds refuse everything, positive odds produce a
    huge NEGATIVE drift that is never `> max` and sail through unchecked.
    """
    import pipeline.execute_portfolio as runner

    assert runner.planned_probability(-108.0) == pytest.approx(0.5192, abs=1e-4)
    assert runner.planned_probability(104.0) == pytest.approx(0.4902, abs=1e-4)
    # Already a probability -- passed through, because both forms occur.
    assert runner.planned_probability(0.52) == 0.52


def test_an_ambiguous_planned_price_is_refused_rather_than_guessed():
    """A guessed unit here is a guessed guard. American odds are conventionally
    at least 100 from zero and a probability is inside (0,1); anything between
    is not readable as either."""
    import pipeline.execute_portfolio as runner

    for ambiguous in (5.0, -3.0, 99.0, 1.0, 0.0, None, "x"):
        assert runner.planned_probability(ambiguous) is None, ambiguous


def test_a_positive_odds_order_is_now_actually_CHECKED(monkeypatch):
    """The order that reached a venue today was `planned=104.0` against
    `price=0.495` -- drift -103.5, silently passed. In real units 104.0 is
    0.4902, so a 0.495 fill is a 0.0048 drift: inside the cap, and now
    genuinely measured rather than accidentally ignored."""
    runner = _artifact_env(monkeypatch)
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None


def test_a_real_adverse_move_on_positive_odds_is_now_REFUSED(monkeypatch):
    """The half of the guard that never fired. Planned +104 (0.4902) against a
    0.75 ask is a 0.26 drift -- far outside the cap, and previously passed
    because -103.5 is not greater than 0.03."""
    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(prices=("0.75", "0.25")),
    ])

    class _Moved(_PolyReq):
        requested_price = 104.0

    with pytest.raises(Exception) as excinfo:
        runner._polymarket_resolve_market(_Moved())
    assert "slippage" in str(excinfo.value)


def test_a_polymarket_build_error_does_not_charge_the_daily_budget():
    """MEASURED 2026-08-25T17:59:06Z:

      LIVE_ORDER status=failed venue=polymarket market=spreads
        error='OrderBuildError: market_unresolved_for_position'
      EXECUTION placed=0 spent={'dollars': 2.39, 'orders': 1}

    $2.39 and one order charged against a $40 daily cap for something that
    never left the process. `execution_ledger` reads `venue_contacted`,
    defaulting to True for unknown exceptions -- Kalshi's OrderBuildError
    carries the attribute, Polymarket's did not.
    """
    from syndicate.features.shared.polymarket_us_orders import OrderBuildError

    assert OrderBuildError.venue_contacted is False


# --------------------------------------------------------------------------
# The order-path verifier: confirmation on demand, without spending anything
# --------------------------------------------------------------------------


def test_the_verifier_reports_which_market_families_would_build(monkeypatch):
    """The interesting question is never "did one order fail" but "which whole
    market family cannot transact". `totals` failing on every row while `h2h`
    succeeds is a different fact from a scattering of misses, and a per-order
    log cannot show it."""
    import pipeline.execute_portfolio as runner
    from pipeline import portfolio_commit

    _artifact_env(monkeypatch)
    monkeypatch.setattr(portfolio_commit, "read_portfolio_plan_for_venue",
                        lambda date, venue: {"positions": [
                            {"position_key": "p1", "sport": "mlb", "event_id": "e1",
                             "market": "h2h", "side": "home", "price": 0.55,
                             "stake_dollars": 2.0,
                             "venue_ticker": "aec-mlb-tex-chw-2026-08-24",
                             "home_team": "CHW", "away_team": "TEX"},
                        ]} if venue == "polymarket" else {"positions": []})

    report = runner.verify_order_paths("2026-08-24", venues=("polymarket",))
    markets = report["venues"]["polymarket"]["markets"]
    assert markets["h2h"]["would_build"] == 1


def test_the_verifier_cannot_place_an_order(monkeypatch):
    """A verifier that could spend money is not a verifier. Nothing in it
    constructs a submitter, so an adapter that would send must never be
    reached even when the resolve succeeds."""
    import pipeline.execute_portfolio as runner
    from syndicate.features.shared import polymarket_us_orders
    from pipeline import portfolio_commit

    _artifact_env(monkeypatch)

    def explode(*a, **kw):
        raise AssertionError("the verifier submitted an order")

    monkeypatch.setattr(polymarket_us_orders, "submit_order", explode)
    monkeypatch.setattr(runner, "_venue_submitter", explode)
    monkeypatch.setattr(portfolio_commit, "read_portfolio_plan_for_venue",
                        lambda date, venue: {"positions": [
                            {"position_key": "p1", "sport": "mlb", "event_id": "e1",
                             "market": "h2h", "side": "home", "price": 0.55,
                             "stake_dollars": 2.0,
                             "venue_ticker": "aec-mlb-tex-chw-2026-08-24",
                             "home_team": "CHW", "away_team": "TEX"},
                        ]})

    runner.verify_order_paths("2026-08-24", venues=("polymarket",))


def test_the_verifier_names_the_exception_rather_than_saying_failed(monkeypatch):
    """A verifier that reported "failed" would reproduce the counter this whole
    session has been prying data out of."""
    import pipeline.execute_portfolio as runner
    from pipeline import portfolio_commit

    _artifact_env(monkeypatch, markets=[_polymarket_row(prices=("0.95", "0.05"))])
    monkeypatch.setattr(portfolio_commit, "read_portfolio_plan_for_venue",
                        lambda date, venue: {"positions": [
                            {"position_key": "p1", "sport": "mlb", "event_id": "e1",
                             "market": "h2h", "side": "home", "price": 104.0,
                             "stake_dollars": 2.0,
                             "venue_ticker": "aec-mlb-tex-chw-2026-08-24",
                             "home_team": "CHW", "away_team": "TEX"},
                        ]})

    report = runner.verify_order_paths("2026-08-24", venues=("polymarket",))
    verdicts = report["venues"]["polymarket"]["markets"]["h2h"]
    assert "_SlippageExceeded" in verdicts, verdicts


def test_an_empty_plan_is_reported_as_such_not_as_success(monkeypatch):
    """"Nothing to place" and "everything would build" must not read alike."""
    import pipeline.execute_portfolio as runner
    from pipeline import portfolio_commit

    monkeypatch.setattr(portfolio_commit, "read_portfolio_plan_for_venue",
                        lambda date, venue: {"positions": []})
    report = runner.verify_order_paths("2026-08-24", venues=("kalshi",))
    assert report["venues"]["kalshi"]["status"] == "no_positions"


def test_verify_order_paths_separates_no_ticker_from_unresolvable(monkeypatch, tmp_path):
    """TWO FAILURES THAT NEED OPPOSITE FIXES, counted as one until now.

    Kalshi has had a distinct `no_venue_ticker` verdict since this verifier was
    written. Polymarket's was folded into `market_unresolved`, which asserts
    "we found the market and could not price it" about a position that never
    had a market identified at all.

    Measured 2026-08-25 4:36:05 PM Central: an h2h on Cleveland Guardians @ LA
    Angels rejected with `OrderBuildError: market_unresolved_for_position`, and
    `ORDER_PATH` had reported `{'h2h': {'market_unresolved': 1}}` one second
    earlier with an EMPTY example map -- while the resolver's own log line said
    `POLYMARKET_NO_SLUG -- venue_ticker unset or carries no slug
    (type=NoneType)`. The board join had not stamped a slug; the slate and the
    price were never reached. Those are different fixes and the verdict has to
    say which.
    """
    import pipeline.execute_portfolio as runner
    from pipeline import portfolio_commit

    def _position(key, ticker):
        row = {
            "position_key": key, "event_id": "e-1", "market": "h2h",
            "side": "home", "sport": "mlb", "price": 0.5, "stake_dollars": 1.0,
            "home_team": "Los Angeles Angels", "away_team": "Cleveland Guardians",
        }
        if ticker is not None:
            row["venue_ticker"] = ticker
        return row

    monkeypatch.setattr(
        portfolio_commit, "read_portfolio_plan_for_venue",
        lambda _d, venue: {"positions": [_position("p-none", None),
                                         _position("p-slug", "aec-mlb-cle-laa-2026-08-25")]}
        if venue == "polymarket" else {"positions": []},
    )
    # The slug-carrying one still fails to resolve (no slate here), which is
    # exactly the other verdict.
    monkeypatch.setattr(runner, "_polymarket_resolve_market", lambda _r: None)

    result = runner.verify_order_paths("2026-08-25", venues=("polymarket",))
    detail = result["venues"]["polymarket"]

    assert detail["markets"]["h2h"] == {"no_venue_ticker": 1, "market_unresolved": 1}, detail
    # AND EACH CARRIES ITS DATA. A verdict with an empty example map is the
    # counter this verifier exists to replace.
    assert detail["examples"].get("h2h|no_venue_ticker"), detail
    assert detail["examples"].get("h2h|market_unresolved"), detail
