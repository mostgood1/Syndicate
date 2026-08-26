"""`/portfolio/live` -- the real-money book, and the wall between it and paper.

Two things are worth testing here and they are both about CONFUSION, not
arithmetic:

1. A live order must never render on `/portfolio/paper`. That page's banner
   says "Simulated fills only. No money moves, no book is contacted, nothing
   here is a real wager." A real position under that sentence is the single
   most dangerous thing either surface could show, and until 2026-08-23 the
   paper payload had no mode filter at all -- the first live order would have
   appeared there.
2. An unreadable ledger must never render as "no live positions". "We cannot
   see the money" and "there is no money at risk" are opposite facts that an
   empty table renders identically.
"""

from __future__ import annotations

import pytest

from syndicate.app import app as flask_app
from syndicate.blueprints import intelligence as intelligence_bp


DATE = "2026-08-23"


@pytest.fixture
def app_client():
    return flask_app.test_client()


def _order(**overrides):
    order = {
        "idempotency_key": "k-live-1",
        "position_key": "pos-1",
        "selected_date": DATE,
        "mode": "live",
        "sport": "wnba",
        "market": "player_points",
        "player_name": "Test Guard",
        "side": "Over",
        "line": 17.5,
        "home_team": "LAS",
        "away_team": "SEA",
        "book": "kalshi",
        "venue": "kalshi",
        "venue_ticker": "KXWNBAPTS-25AUG23-TG-17.5",
        "requested_price": -110.0,
        "requested_stake_dollars": 5.0,
        "submitted_at": "2026-08-23T23:10:05Z",
        "status": "filled",
        "fill_price": -115.0,
        "fill_stake_dollars": 5.0,
        "error": None,
    }
    order.update(overrides)
    return order


@pytest.fixture
def live_env(monkeypatch):
    """Inject the ledger rather than reading disk.

    `data/` in this checkout is a lossy mirror, so a test that read it would
    pass or fail on mirror vintage instead of on this code.
    """
    state = {
        "orders": [],
        "raise_on_load": None,
        "mode": "live",
        "armed": True,
        "execution": True,
        "kill_switch": {"engaged": False, "source": "env"},
    }

    import pipeline.execute_portfolio as exec_mod
    import pipeline.portfolio_commit as commit_mod
    import syndicate.features.shared.execution_guard as guard_mod
    import syndicate.features.shared.execution_ledger as ledger_mod

    def fake_load():
        if state["raise_on_load"] is not None:
            raise state["raise_on_load"]
        return {"orders": list(state["orders"])}

    monkeypatch.setattr(ledger_mod, "_load", fake_load)
    monkeypatch.setattr(ledger_mod, "execution_mode", lambda: state["mode"])
    monkeypatch.setattr(ledger_mod, "live_execution_armed", lambda: state["armed"])
    monkeypatch.setattr(exec_mod, "execution_enabled", lambda: state["execution"])
    monkeypatch.setattr(guard_mod, "kill_switch_engaged", lambda: state["kill_switch"])
    # NO WORKER STAMP BY DEFAULT. The page prefers `execution_state.json` when
    # the worker has written one, and a real one can be sitting on disk from an
    # earlier run -- these tests drive the web-env fallback and must not pass or
    # fail on whether that file happens to exist. The tests that DO exercise the
    # stamp override this themselves.
    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: None)
    # The paper page reads these too; a live-only test must not depend on
    # whatever plan happens to be on disk.
    monkeypatch.setattr(commit_mod, "read_portfolio_plan", lambda date: None)
    monkeypatch.setattr(commit_mod, "paper2_venues", lambda: ())
    return state


def _payload(_live_env):
    return intelligence_bp._live_portfolio_payload(DATE)


# --------------------------------------------------------------------------
# The wall
# --------------------------------------------------------------------------


def test_a_live_order_is_not_on_the_paper_page(live_env):
    """The defect this page was built around.

    `_paper_portfolio_payload` filtered by DATE and by nothing else, so the
    first real Kalshi fill would have rendered under a banner promising no
    money moves.
    """
    live_env["orders"] = [_order()]
    paper = intelligence_bp._paper_portfolio_payload(DATE)
    # No plan is injected, so a paper order on this date would land in
    # `orphan_orders` -- which is exactly where a live one must NOT.
    assert paper["orphan_orders"] == []
    assert paper["rows"] == []


def test_a_live_order_does_not_reach_the_rendered_paper_page(app_client, live_env):
    live_env["orders"] = [_order()]
    body = app_client.get(f"/portfolio/paper?date={DATE}").get_data(as_text=True)
    assert "Test Guard" not in body


def test_a_live_order_is_excluded_from_the_paper_all_dates_record(live_env):
    """The all-dates rollup is computed from the unfiltered list, so it is the
    one place the mode filter is easy to forget."""
    live_env["orders"] = [
        _order(outcome="won", pnl_dollars=4.35, fill_stake_dollars=5.0),
    ]
    paper = intelligence_bp._paper_portfolio_payload(DATE)
    assert paper["settlement_all_time"]["total"]["settled"] == 0


def test_an_order_with_no_mode_is_treated_as_paper(live_env):
    """Absent mode predates the field. It must default to the SAFE reading --
    paper -- rather than to live."""
    live_env["orders"] = [_order(mode=None)]
    assert _payload(live_env)["orders"] == []
    assert len(intelligence_bp._paper_portfolio_payload(DATE)["orphan_orders"]) == 1


def test_the_live_page_shows_only_live_orders(live_env):
    live_env["orders"] = [_order(), _order(idempotency_key="k-paper", mode="paper")]
    payload = _payload(live_env)
    assert [o["idempotency_key"] for o in payload["orders"]] == ["k-live-1"]


# --------------------------------------------------------------------------
# Absence vs failure
# --------------------------------------------------------------------------


def test_an_unreadable_ledger_is_never_rendered_as_no_positions(app_client, live_env):
    live_env["raise_on_load"] = RuntimeError("keyvalue unreachable")
    payload = _payload(live_env)
    assert "keyvalue unreachable" in payload["ledger_error"]

    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "not claiming there are no positions" in body
    assert "No live positions have ever been placed" not in body


def test_no_positions_says_so_plainly(app_client, live_env):
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "No live positions have ever been placed" in body


def test_nothing_settled_is_not_a_zero_pnl(app_client, live_env):
    live_env["orders"] = [_order(outcome=None, pnl_dollars=None)]
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    # "+0.00" on nothing decided and "+0.00" on fifty decided are the same
    # string, and only one of them means the book is flat.
    assert "nothing settled yet" in body


# --------------------------------------------------------------------------
# Positions carry all dates, not the selected one
# --------------------------------------------------------------------------


def test_yesterdays_open_position_is_still_shown(live_env):
    """A real position is not interesting only on the day it was opened. A page
    that hides yesterday's open bet behind a date picker will one day let one
    expire unwatched."""
    live_env["orders"] = [_order(selected_date="2026-08-22")]
    assert len(_payload(live_env)["orders"]) == 1


# --------------------------------------------------------------------------
# The arming badge is DERIVED, never a label
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "off",
    ["execution", "mode", "armed", "kill"],
)
def test_any_one_switch_off_means_the_badge_is_not_real_money(app_client, live_env, off):
    if off == "execution":
        live_env["execution"] = False
    elif off == "mode":
        live_env["mode"] = "paper"
    elif off == "armed":
        live_env["armed"] = False
    else:
        live_env["kill_switch"] = {"engaged": True, "source": "env"}

    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "LIVE MODE OFF" in body
    assert "LIVE — REAL MONEY" not in body


def test_all_four_on_is_the_only_state_that_says_real_money(app_client, live_env):
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "LIVE — REAL MONEY" in body
    assert "real submissions to a real venue" in body


def test_a_kill_switch_read_failure_reads_as_engaged(live_env, monkeypatch):
    """Fail CLOSED. A switch we cannot read is a switch we must assume is on."""
    import syndicate.features.shared.execution_guard as guard_mod

    def boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(guard_mod, "kill_switch_engaged", boom)
    payload = _payload(live_env)
    assert payload["kill_switch"]["engaged"] is True
    assert payload["kill_switch"]["source"] == "read_failed"


# --------------------------------------------------------------------------
# The rows a person has to look at first
# --------------------------------------------------------------------------


def test_a_submitted_order_is_flagged_as_unreconciled(app_client, live_env):
    """Sent, or possibly sent, with an unknown result. A restart between submit
    and record produces exactly these, and the answer is to check the venue --
    never to re-submit."""
    live_env["orders"] = [_order(status="submitted", fill_price=None, fill_stake_dollars=None)]
    payload = _payload(live_env)
    assert len(payload["unreconciled"]) == 1

    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "unknown result" in body
    assert "do not re-submit" in body


def test_a_filled_order_is_not_flagged_as_unreconciled(live_env):
    live_env["orders"] = [_order(status="filled")]
    assert _payload(live_env)["unreconciled"] == []


def test_the_page_shows_the_venue_ticker_and_the_slippage(app_client, live_env):
    live_env["orders"] = [_order()]
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "KXWNBAPTS-25AUG23-TG-17.5" in body
    # Requested -110, filled -115: the gap is what a person checks first after
    # a real submit, so both numbers have to be on the row.
    assert "-110" in body
    assert "-115" in body


def test_the_caps_in_force_are_on_the_page(app_client, live_env, monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "5")
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "$5" in body


# --------------------------------------------------------------------------
# Reachability -- a page nobody can navigate to is a page nobody watches
# --------------------------------------------------------------------------


def test_the_paper_page_links_to_the_live_book(app_client, live_env):
    body = app_client.get(f"/portfolio/paper?date={DATE}").get_data(as_text=True)
    assert 'href="/portfolio/live"' in body


def test_the_api_and_the_page_read_the_same_payload(app_client, live_env):
    live_env["orders"] = [_order()]
    data = app_client.get(f"/api/portfolio/live?date={DATE}").get_json()
    assert data["execution_mode"] == "live"
    assert data["live_armed"] is True
    assert len(data["orders"]) == 1


# --------------------------------------------------------------------------
# The switches must report the WORKER, not this web process
# --------------------------------------------------------------------------


def test_the_page_shows_the_workers_switches_not_the_webs(app_client, live_env, monkeypatch):
    """MEASURED 2026-08-24: `/portfolio/live` read "LIVE MODE OFF", "Mode
    paper", "Armed no" and caps of $25/$100 while live-odds-worker was live,
    armed and capped at $10/$40.

    Every one of those was true of the WEB process, which has none of the
    execution env vars, and worthless to a person looking at a live book. It is
    the same defect the paper page had with "COMMIT JOB off" beside filled
    orders, and it needs the same fix: the worker stamps its state and the page
    reports that.
    """
    import syndicate.features.shared.execution_ledger as ledger_mod

    # Web's own env says nothing is on...
    live_env["execution"] = False
    live_env["mode"] = "paper"
    live_env["armed"] = False
    # ...while the worker reports live, armed, and the real caps.
    monkeypatch.setattr(
        ledger_mod,
        "read_execution_state",
        lambda: {
            "recorded_by": "live-odds-worker",
            "recorded_at": "2026-08-24T02:00:00Z",
            "execution_mode": "live",
            "live_armed": True,
            "execution_enabled": True,
            "kill_switch": {"engaged": False},
            "limits": {"max_order_dollars": 10.0, "max_day_dollars": 40.0, "max_day_orders": 10},
        },
    )

    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["execution_mode"] == "live"
    assert payload["live_armed"] is True
    assert payload["state_source"] == "worker"
    assert payload["limits"]["max_order_dollars"] == 10.0

    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "LIVE — REAL MONEY" in body
    assert "$10" in body
    assert "live-odds-worker" in body


def test_no_worker_stamp_is_reported_as_unknown_not_as_off(app_client, live_env, monkeypatch):
    """"The worker has not reported" and "execution is off" are different facts
    with opposite responses, and an unlabelled fallback renders them the same."""
    import syndicate.features.shared.execution_ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: None)
    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["state_source"] == "web_env"

    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "worker has not reported" in body
    assert "Treat them as unknown, not as off" in body


def test_a_stale_stamp_says_so(app_client, live_env, monkeypatch):
    """A stopped worker's last known state looks identical to its current one."""
    import syndicate.features.shared.execution_ledger as ledger_mod

    monkeypatch.setattr(
        ledger_mod,
        "read_execution_state",
        lambda: {
            "recorded_by": "live-odds-worker",
            "recorded_at": "2020-01-01T00:00:00Z",
            "execution_mode": "live",
            "live_armed": True,
            "execution_enabled": True,
            "kill_switch": {"engaged": False},
            "limits": {"max_order_dollars": 10.0, "max_day_dollars": 40.0, "max_day_orders": 10},
        },
    )
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "may be stale" in body


def test_a_kalshi_dollar_price_renders_as_cents_not_american_odds(app_client, live_env):
    """MEASURED from the live page 2026-08-24: a Kalshi fill price of $0.54
    rendered as "+0".

    `"%+d"|format(0.54|int)` is `+0` — the column destroyed the number it
    existed to show, beside a REQUESTED column carrying American odds from the
    board. Two units in one table with nothing to tell them apart.
    """
    live_env["orders"] = [_order(fill_price=0.54, requested_price=0.46)]
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "54&cent;" in body or "54¢" in body
    assert "+0" not in body


def test_an_american_price_still_renders_as_american(app_client, live_env):
    """The other venues quote American odds and must not become cents."""
    live_env["orders"] = [_order(fill_price=-117.0, requested_price=163.0)]
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "-117" in body
    assert "+163" in body


def _live_order(status, error="", key="k1"):
    return {
        "mode": "live", "selected_date": "2026-08-25", "venue": "kalshi",
        "status": status, "error": error, "position_key": key,
        "submitted_at": "2026-08-25T23:00:00Z", "requested_stake_dollars": 1.0,
    }


def test_orders_that_never_opened_a_position_are_hidden_by_default(monkeypatch):
    """[USER DECISION 2026-08-25] Default to hiding them, with a toggle.

    HIDDEN, NOT DROPPED, and counted either way: a page that silently omitted
    them would make "we placed nothing" and "we tried and were refused" look
    identical, which is the distinction this whole system keeps paying to
    preserve. They are also the rows that say WHY a bet did not happen.
    """
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    orders = [
        _live_order("filled", key="a"),
        _live_order("rejected", "OrderBuildError: no_venue_ticker", key="b"),
        _live_order("failed", "KalshiAuthError: http_404: market_not_found", key="c"),
    ]
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": orders})

    default = mod._live_portfolio_payload("2026-08-25")
    assert [o["position_key"] for o in default["orders"]] == ["a"]
    assert default["hidden_count"] == 2
    assert default["show_all"] is False

    shown = mod._live_portfolio_payload("2026-08-25", show_all=True)
    assert len(shown["orders"]) == 3
    assert shown["hidden_count"] == 2
    assert shown["show_all"] is True


def test_a_failed_order_of_UNKNOWN_outcome_stays_visible(monkeypatch):
    """The row a person must see FIRST.

    A submit that timed out may well have landed -- that gap is why the
    write-ahead record exists. Hiding it would bury the one order that needs
    checking against the venue before anything else is placed, which is what
    the page's own banner says. Only a failure the venue ANSWERED (a 4xx) is
    certainly not a position.
    """
    from syndicate.blueprints import intelligence as mod
    from syndicate.features.shared import execution_ledger as ledger_mod

    orders = [
        _live_order("failed", "ReadTimeout", key="unknown"),
        _live_order("failed", "http_500: internal", key="broke"),
        _live_order("failed", "http_404: market_not_found", key="refused"),
    ]
    monkeypatch.setattr(ledger_mod, "_load", lambda: {"orders": orders})

    payload = mod._live_portfolio_payload("2026-08-25")
    visible = {o["position_key"] for o in payload["orders"]}
    assert visible == {"unknown", "broke"}, visible
    assert payload["hidden_count"] == 1


def test_the_page_and_the_cap_agree_on_what_is_not_a_position(monkeypatch):
    """One rule, two readers. The page's filter and the day-budget's spend
    accounting both come from `_is_venue_refusal`, so a row that is hidden is
    exactly a row that did not consume an order slot -- rather than two
    functions that agree today and drift apart later."""
    from syndicate.blueprints.intelligence import _is_non_position
    from syndicate.features.shared.execution_guard import _is_venue_refusal

    refused = _live_order("failed", "http_404: market_not_found")
    assert _is_non_position(refused) is True
    assert _is_venue_refusal(refused) is True

    timed_out = _live_order("failed", "ReadTimeout")
    assert _is_non_position(timed_out) is False
    assert _is_venue_refusal(timed_out) is False


# ---------------------------------------------------------------------------
# THE PIVOTS. [USER DECISION 2026-08-25] daily, monthly, yearly views.
#
# REACHABILITY FIRST, per this repo's own standard: a rollup that computes
# correctly and never reaches the page is indistinguishable from one that was
# never built, at every level except looking at it.
# ---------------------------------------------------------------------------


def test_the_period_pivot_reaches_the_page(app_client, live_env):
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0, outcome="won", pnl_dollars=1.5),
        _order(idempotency_key="k2", selected_date="2026-07-04", status="filled",
               fill_stake_dollars=2.0, outcome="lost", pnl_dollars=-2.0),
    ]
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "Performance" in body
    assert "2026-08-25" in body
    # The day view is the default, so July's own DAY row is present too.
    assert "2026-07-04" in body


def test_the_month_and_year_views_are_selectable(app_client, live_env):
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0, outcome="won", pnl_dollars=1.5),
        _order(idempotency_key="k2", selected_date="2026-07-04", status="filled",
               fill_stake_dollars=2.0, outcome="lost", pnl_dollars=-2.0),
    ]
    month = app_client.get("/portfolio/live?period=month").get_data(as_text=True)
    assert "2026-08<" in month or ">2026-08<" in month
    year = app_client.get("/portfolio/live?period=year").get_data(as_text=True)
    # One row for 2026 -- both orders, collapsed.
    assert ">2026<" in year


def test_the_pivot_does_not_move_when_the_show_toggle_flips(app_client, live_env):
    """The `?show=` toggle changes what is DISPLAYED, never what is counted.
    A rollup that moved with a display toggle would not be quotable."""
    live_env["orders"] = [
        _order(idempotency_key="k1", selected_date="2026-08-25", status="filled",
               fill_stake_dollars=2.0),
        _order(idempotency_key="k2", selected_date="2026-08-25", status="rejected",
               error="zero_kelly_stake"),
    ]
    hidden = intelligence_bp._live_portfolio_payload("2026-08-25")
    shown = intelligence_bp._live_portfolio_payload("2026-08-25", show_all=True)
    assert hidden["periods"] == shown["periods"]
    # And the refused order is not in the count either way.
    assert hidden["periods"]["by_day"][0]["orders"] == 1


# ---------------------------------------------------------------------------
# THE BANNER COLOUR. [USER DECISION 2026-08-25] green when healthy, red when
# anything is an issue.
#
# This INVERTED the previous scheme, where `on` was red because red meant
# "real money is live, pay attention". A working system rendered as a wall of
# red and a broken one looked the same. These tests pin the new direction so
# it cannot quietly drift back.
# ---------------------------------------------------------------------------


def test_a_healthy_live_book_is_green(app_client, live_env, monkeypatch):
    """A WORKER STAMP IS PART OF HEALTHY. The fixture's default leaves
    `read_execution_state` returning None, which is `web env (worker silent)`
    -- correctly not green, however the switches read."""
    from syndicate.features.shared import execution_ledger as ledger_mod

    live_env["orders"] = [_order()]
    monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: {
        "execution_mode": "live", "live_armed": True, "execution_enabled": True,
        "kill_switch": {"engaged": False}, "limits": {},
        "recorded_by": "live-odds-worker",
        "recorded_at": _now_iso(),
    })
    payload = intelligence_bp._live_portfolio_payload(DATE)
    assert payload["health"]["ok"] is True
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    # ANCHORED ON THE MARKUP. Both class names appear in the stylesheet, so a
    # bare substring test passes whatever the badge actually renders.
    assert 'class="live-badge live-badge--ok"' in body
    assert 'class="live-badge live-badge--bad"' not in body
    assert "LIVE — REAL MONEY" in body
    assert 'class="live-banner is-ok"' in body


def test_each_broken_switch_turns_the_line_red(app_client, live_env, monkeypatch):
    """One field is enough. The verdict is `all()`, not a majority.

    Given a healthy worker stamp first, so each case fails on the field under
    test rather than on a silent worker -- a test that is red for the wrong
    reason proves nothing about the reason it names."""
    from syndicate.features.shared import execution_ledger as ledger_mod

    def stamp(**over):
        base = {
            "execution_mode": "live", "live_armed": True, "execution_enabled": True,
            "kill_switch": {"engaged": False}, "limits": {},
            "recorded_by": "live-odds-worker", "recorded_at": _now_iso(),
        }
        base.update(over)
        monkeypatch.setattr(ledger_mod, "read_execution_state", lambda: base)

    for field, break_it in (
        ("job", lambda: stamp(execution_enabled=False)),
        ("mode", lambda: stamp(execution_mode="paper")),
        ("armed", lambda: stamp(live_armed=False)),
        ("kill_switch", lambda: stamp(kill_switch={"engaged": True, "source": "env"})),
    ):
        stamp()
        assert intelligence_bp._live_portfolio_payload(DATE)["health"]["ok"] is True
        break_it()
        health = intelligence_bp._live_portfolio_payload(DATE)["health"]
        assert health[field] is False, field
        assert health["ok"] is False, field
        body = app_client.get("/portfolio/live").get_data(as_text=True)
        assert 'class="live-badge live-badge--bad"' in body, field
        assert 'class="live-banner is-bad"' in body, field


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def test_an_engaged_kill_switch_is_red(app_client, live_env):
    """DELIBERATE REVERSAL. Engaged used to be painted as fine ("the SAFE
    state"). It is still safe, and it is also a system that cannot trade --
    which is exactly what this banner reports."""
    live_env["kill_switch"] = {"engaged": True, "source": "env"}
    body = app_client.get("/portfolio/live").get_data(as_text=True)
    assert "ENGAGED" in body
    assert intelligence_bp._live_portfolio_payload(DATE)["health"]["kill_switch"] is False


def test_a_silent_worker_is_red_even_with_every_switch_on(app_client, live_env):
    """"The worker has not reported" and "execution is off" are different
    facts. Neither is healthy, and web's own env is not a reading of the
    process that places orders."""
    health = intelligence_bp._live_portfolio_payload(DATE)["health"]
    # The fixture leaves `read_execution_state` returning None -> web_env.
    payload = intelligence_bp._live_portfolio_payload(DATE)
    if payload["state_source"] != "worker":
        assert health["source"] is False
        assert health["ok"] is False


def test_a_stale_worker_stamp_is_red(monkeypatch):
    """A stamp from forty minutes ago is not current state. A stopped worker's
    last known settings look identical to its live ones."""
    from syndicate.blueprints.intelligence import _live_health, _STATE_STALE_SECONDS

    healthy = {
        "execution_enabled": True, "execution_mode": "live", "live_armed": True,
        "kill_switch": {"engaged": False}, "state_source": "worker",
        "state_age_seconds": 60,
    }
    assert _live_health(healthy)["ok"] is True
    stale = {**healthy, "state_age_seconds": _STATE_STALE_SECONDS + 1}
    assert _live_health(stale)["source"] is False
    assert _live_health(stale)["ok"] is False
    # The boundary belongs to fresh.
    assert _live_health({**healthy, "state_age_seconds": _STATE_STALE_SECONDS})["source"] is True


def test_the_api_answers_the_same_health_question_as_the_page(app_client, live_env):
    """A caller must not have to re-derive green from six fields."""
    api = app_client.get("/api/portfolio/live").get_json()
    assert "health" in api
    assert set(api["health"]) == {"job", "mode", "armed", "kill_switch", "source", "ok"}
