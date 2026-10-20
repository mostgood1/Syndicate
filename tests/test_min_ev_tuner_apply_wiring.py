"""The per-cell min_ev cut, wired into the two gates (lane min-ev-tuner-shadow).

Reachability first: with `SYNDICATE_MIN_EV_TUNER` unset (the fleet) or `shadow`, a stored
override must change NOTHING and the tuner state must not even be read; with `apply`, the
same override must change the refusal. A tuner that silently returns the base would pass
every other test here and still not be wired.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import min_ev_tuner as T

# MLB 2026-10-10 is POSTSEASON in `season_phase`; venue kalshi -> this cell.
CELL = "kalshi|mlb|batter_hits|postseason"


def _row(**overrides):
    row = {
        "sport": "mlb",
        "venue": "kalshi",
        "event_id": "evt-1",
        "kind": "prop",
        "market": "batter_hits",
        "segment": "full_game",
        "player_name": "Test Batter",
        "home_team": "HOU",
        "away_team": "SEA",
        "side": "Over",
        "line": 0.5,
        "quote": {"bookmaker": "DraftKings", "price": -125},
        "ev_pct": 6.0,
        "model_edge_pct": 3.0,
        "score": {"score": 61.25, "price_reliability": 0.9},
    }
    row.update(overrides)
    return row


@pytest.fixture
def tuner(monkeypatch):
    """A stored override for CELL, and a counter of state reads."""
    import syndicate.features.shared.portfolio_settings as ps

    monkeypatch.setattr(ps, "_read_stored", lambda: ({}, None))
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_MIN_EV_PCT", raising=False)
    for key in ("SYNDICATE_MIN_EV_TUNER", "SYNDICATE_MIN_EV_TUNER_FLOOR_PCT", "SYNDICATE_MIN_EV_TUNER_CEILING_PCT"):
        monkeypatch.delenv(key, raising=False)
    box = {"override": 5.5, "reads": 0, "raise": False}

    def load_state():
        box["reads"] += 1
        if box["raise"]:
            raise RuntimeError("store down")
        return {"cells": {CELL: {"min_ev_pct": box["override"]}}}

    monkeypatch.setattr(T, "load_state", load_state)
    return box


def _commit(rows):
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    return commit_portfolio(rows, selected_date="2026-10-10")


def test_unset_mode_ignores_a_stored_override_and_never_reads_the_state(tuner):
    plan = _commit([_row()])
    assert plan["positions"], plan.get("refusals")
    assert plan["min_ev_cut_sources"] == {"base": 1}
    assert plan["tuned_min_ev_refusals"] == {}
    assert tuner["reads"] == 0


def test_shadow_mode_is_identical_to_unset(tuner, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "shadow")
    plan = _commit([_row()])
    assert plan["positions"] and plan["min_ev_cut_sources"] == {"base": 1} and tuner["reads"] == 0


def test_apply_with_a_raised_cell_refuses_the_row_and_says_the_tuned_cut_did_it(tuner, monkeypatch):
    # off != on: the same row and the same stored override, only the mode differs.
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    plan = _commit([_row(ev_pct=5.0)])  # ev 5.0 < tuned 5.5 (base 2.0); 5.0 clears the base
    assert not plan["positions"]
    assert plan["refusals"].get("below_min_ev_pct") == 1
    assert plan["min_ev_cut_sources"] == {"tuned_cell": 1}
    assert plan["tuned_min_ev_refusals"] == {"below_min_ev_pct": 1}
    assert tuner["reads"] == 1  # once per commit, not per row


def test_apply_reads_the_state_once_per_commit_not_per_row(tuner, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    _commit([_row(), _row(event_id="evt-2", player_name="Other Batter")])
    assert tuner["reads"] == 1


def test_apply_with_a_lowered_cell_admits_and_a_row_outside_the_cell_keeps_the_base(tuner, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    tuner["override"] = 1.0
    other = _row(event_id="evt-2", market="batter_total_bases", player_name="Other Batter")
    plan = _commit([_row(), other])
    assert plan["min_ev_cut_sources"] == {"base": 1, "tuned_cell": 1}
    assert plan["tuned_min_ev_refusals"] == {}


def test_apply_with_an_unreadable_state_falls_to_the_base_never_a_looser_cut(tuner, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    tuner["raise"] = True
    plan = _commit([_row(ev_pct=1.5)])  # under the 2.0 base: must still be refused
    assert plan["refusals"].get("below_min_ev_pct") == 1
    assert plan["min_ev_cut_sources"] == {"base": 1}


def test_an_out_of_bounds_override_is_ignored(tuner, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    tuner["override"] = 50.0  # above the 6.0 ceiling: shadow_cut_line refuses it
    plan = _commit([_row()])
    assert plan["positions"] and plan["min_ev_cut_sources"] == {"base": 1}


# --- the Polymarket ask check reads the same cut ----------------------------


def _pm_request(ev):
    import test_polymarket_us_orders as pm

    request = pm._priced(ev=ev)
    request.sport = "ncaaf"
    request.venue = "polymarket"
    request.selected_date = "2026-10-10"
    return pm, request


def test_polymarket_ask_uses_the_tuned_cut_only_in_apply(monkeypatch, capsys):
    pm, request = _pm_request(ev=10.0)  # +10.1% at the ask (see that module's test (c))
    cell = "polymarket|ncaaf|h2h|regular"
    monkeypatch.setattr(T, "load_state", lambda: {"cells": {cell: {"min_ev_pct": 5.0}}})
    monkeypatch.delenv("SYNDICATE_MIN_EV_TUNER", raising=False)
    sent, refused = pm._ask_build(request, monkeypatch, min_ev=2.0)
    assert refused is None
    assert "min_ev_source=base" in capsys.readouterr().out

    # A cut above the ask's EV refuses only when applied (ceiling raised for the test).
    monkeypatch.setattr(T, "load_state", lambda: {"cells": {cell: {"min_ev_pct": 12.0}}})
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER_CEILING_PCT", "15")
    sent, refused = pm._ask_build(request, monkeypatch, min_ev=2.0)
    assert refused is None  # still unset -> base
    monkeypatch.setenv("SYNDICATE_MIN_EV_TUNER", "apply")
    sent, refused = pm._ask_build(request, monkeypatch, min_ev=2.0)
    assert sent is None and refused == "ask_ev_below_min"
    assert "min_ev_source=tuned_cell" in capsys.readouterr().out
