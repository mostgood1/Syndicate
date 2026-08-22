"""`/portfolio/paper` and `/api/portfolio/paper` -- the read surface for Stage B.

The page is a PURE READ of two worker-written artifacts, so what is worth
testing is not arithmetic but that the four absence states stay distinguishable
and that a ledger the reader cannot open says so instead of rendering an empty
table. An empty page that means "no bets" and an empty page that means "cannot
see the bets" look identical, and only one of them is safe.
"""

from __future__ import annotations

import pytest

from syndicate.app import app as flask_app
from syndicate.blueprints import intelligence as intelligence_bp


@pytest.fixture
def app_client():
    return flask_app.test_client()


DATE = "2026-08-22"


def _plan(positions=None, **overrides):
    plan = {
        "selected_date": DATE,
        "generated_at": "2026-08-22T18:00:00Z",
        "bankroll_units": 1000.0,
        "positions": positions if positions is not None else [],
        "totals": {
            "positions": len(positions or []),
            "staked_dollars": 30.27,
            "staked_fraction": 0.03027,
            "staked_dollars_sim_attributed": 23.93,
            "sim_share_of_staked": 0.7906,
            "positions_where_sim_picked_the_side": 2,
        },
        "refusals": {"no_model_edge_pct": 43, "below_min_ev": 12},
        "sim_coverage": {
            "rows_in": 108,
            "rows_with_sim_edge": 65,
            "rows_without_sim_edge": 43,
            "share_with_sim_edge": 0.6019,
        },
    }
    plan.update(overrides)
    return plan


def _position(**overrides):
    position = {
        "position_key": "abc123",
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "batter_hits",
        "player_name": "Test Batter",
        "home_team": "HOU",
        "away_team": "SEA",
        "side": "Over",
        "line": 0.5,
        "book": "draftkings",
        "price": -125.0,
        "stake_dollars": 6.4,
        "stake_fraction": 0.0064,
        "ev_pct": 3.2,
        "model_edge_pct": 2.1,
        "board_score": 61.25,
        "attribution": {
            "stake_fraction_ev_only": 0.0031,
            "stake_fraction_sim_delta": 0.0033,
            "sim_share_of_stake": 0.5156,
            "stake_dollars_ev_only": 3.1,
            "stake_dollars_sim_delta": 3.3,
            "side_picked_by": "simulation",
        },
    }
    position.update(overrides)
    return position


def _order(**overrides):
    order = {
        "idempotency_key": "k1",
        "position_key": "abc123",
        "selected_date": DATE,
        "mode": "paper",
        "sport": "mlb",
        "market": "batter_hits",
        "side": "Over",
        "book": "draftkings",
        "requested_price": -125.0,
        "requested_stake_dollars": 6.4,
        "submitted_at": "2026-08-22T18:00:05Z",
        "status": "filled",
        "fill_price": -125.0,
        "fill_stake_dollars": 6.4,
        "error": None,
    }
    order.update(overrides)
    return order


@pytest.fixture
def paper_env(monkeypatch):
    """Drive the payload from injected artifacts rather than whatever is on disk.

    `data/` in this checkout is a lossy mirror, so a test that read it would
    pass or fail on mirror vintage instead of on this code.
    """
    state = {"plan": None, "orders": [], "raise_on_load": None, "mode": "paper",
             "commit": True, "execution": True}

    import pipeline.portfolio_commit as commit_mod
    import pipeline.execute_portfolio as exec_mod
    import syndicate.features.shared.execution_ledger as ledger_mod

    def fake_load():
        if state["raise_on_load"] is not None:
            raise state["raise_on_load"]
        return {"orders": list(state["orders"])}

    monkeypatch.setattr(commit_mod, "read_portfolio_plan", lambda date: state["plan"])
    monkeypatch.setattr(commit_mod, "portfolio_commit_enabled", lambda: state["commit"])
    monkeypatch.setattr(exec_mod, "execution_enabled", lambda: state["execution"])
    monkeypatch.setattr(ledger_mod, "_load", fake_load)
    monkeypatch.setattr(ledger_mod, "execution_mode", lambda: state["mode"])
    return state


def _payload(paper_env):
    return intelligence_bp._paper_portfolio_payload(DATE)


def test_commit_disabled_is_its_own_state(paper_env):
    paper_env["commit"] = False
    payload = _payload(paper_env)
    assert payload["commit_enabled"] is False
    assert payload["plan_present"] is False
    assert payload["rows"] == []


def test_missing_plan_is_not_the_same_as_an_empty_plan(paper_env):
    missing = _payload(paper_env)
    assert missing["plan_present"] is False

    paper_env["plan"] = _plan(positions=[])
    empty = _payload(paper_env)
    assert empty["plan_present"] is True
    assert empty["rows"] == []
    # The refusal counts are what make an empty plan readable as a decision.
    assert empty["refusals"]["no_model_edge_pct"] == 43


def test_orders_join_onto_positions_by_position_key(paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    paper_env["orders"] = [_order()]
    payload = _payload(paper_env)
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["order"]["status"] == "filled"
    assert payload["orphan_orders"] == []


def test_position_without_an_order_keeps_a_null_order(paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    payload = _payload(paper_env)
    assert payload["rows"][0]["order"] is None


def test_order_with_no_matching_position_is_surfaced_not_dropped(paper_env):
    # The board rebuilt and dropped the position, but the order was submitted.
    # Hiding it would make a placed bet invisible.
    paper_env["plan"] = _plan(positions=[])
    paper_env["orders"] = [_order(position_key="gone")]
    payload = _payload(paper_env)
    assert [o["position_key"] for o in payload["orphan_orders"]] == ["gone"]


def test_orders_from_other_dates_are_excluded(paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    paper_env["orders"] = [_order(selected_date="2026-08-21")]
    payload = _payload(paper_env)
    assert payload["rows"][0]["order"] is None
    assert payload["orphan_orders"] == []


def test_unreadable_ledger_reports_the_error_rather_than_reading_empty(paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    paper_env["raise_on_load"] = RuntimeError("keyvalue unreachable")
    payload = _payload(paper_env)
    assert "keyvalue unreachable" in payload["ledger_error"]
    # The plan still renders -- only the order column is unknown.
    assert len(payload["rows"]) == 1


def test_unreadable_plan_does_not_take_the_page_down(paper_env, monkeypatch):
    import pipeline.portfolio_commit as commit_mod

    def boom(_date):
        raise RuntimeError("plan artifact corrupt")

    monkeypatch.setattr(commit_mod, "read_portfolio_plan", boom)
    payload = _payload(paper_env)
    assert payload["plan_present"] is False
    assert payload["rows"] == []


def test_page_renders_with_positions(app_client, paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    paper_env["orders"] = [_order()]
    response = app_client.get(f"/portfolio/paper?date={DATE}")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "Test Batter" in body
    assert "PAPER" in body
    assert "-125" in body
    assert "$6.40" in body


def test_page_renders_when_there_is_nothing_to_show(app_client, paper_env):
    response = app_client.get(f"/portfolio/paper?date={DATE}")
    assert response.status_code == 200
    assert "No plan artifact" in response.data.decode("utf-8")


def test_api_mirrors_the_page_payload(app_client, paper_env):
    paper_env["plan"] = _plan(positions=[_position()])
    response = app_client.get(f"/api/portfolio/paper?date={DATE}")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["date"] == DATE
    assert data["execution_mode"] == "paper"
    assert len(data["rows"]) == 1


def test_live_mode_is_visible_in_the_payload(paper_env):
    paper_env["mode"] = "live"
    assert _payload(paper_env)["execution_mode"] == "live"
