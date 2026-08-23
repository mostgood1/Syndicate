"""Stage B runner: a committed plan becomes paper orders, exactly once."""

from __future__ import annotations

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
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22", force=True)
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
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
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
    _write_plan(monkeypatch, [_row()])
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "draftkings")
    from pipeline import execute_portfolio as runner

    result = runner.run_execution("2026-08-22")
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
