"""live_cell_gate -- the per-cell live gate that replaces the global EV-floor stop (user decision C, 2026-10-24)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import live_cell_gate as g

NOW = datetime(2026, 10, 25, 14, 0, tzinfo=timezone.utc)


def _live(i, *, won, stake=5.0, sport="nba", market="spreads", venue="kalshi", game=None, when=None, **kw):
    when = when or (NOW - timedelta(days=3))
    pnl = stake * 0.9 if won else -stake
    return {"venue": venue, "status": "filled", "outcome": "won" if won else "lost", "fill_stake_dollars": stake,
            "pnl_dollars": pnl, "fill_price": 0.5, "ev_pct": 2.0, "sport": sport, "market": market,
            "event_id": game or f"g{i}", "selected_date": when.date().isoformat(),
            "submitted_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "position_key": f"{venue}:{i}", **kw}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(g.MODE_ENV, raising=False)
    g.reset_cache()
    yield
    g.reset_cache()


def test_cells_match_the_scorecard_grain():
    assert g.cell_of_order(_live(1, won=True)) == "kalshi|nba|spread|pregame"
    assert g.cell_of_order(_live(1, won=True, venue="paper:kalshi:ladder")) == "kalshi|nba|spread|pregame"
    assert g.cell_of_order(_live(1, won=True, ev_pct=None)) == "kalshi|nba|spread|in_game"
    assert g.cell_of_row({"sport": "NBA", "market": "player_points", "player_name": "X"}, "kalshi") == "kalshi|nba|prop|pregame"


def test_a_significantly_negative_cell_trips_and_others_stay_armed():
    losing = [_live(i, won=(i % 5 == 0), sport="nba", market="player_points", player_name="P") for i in range(40)]
    fine = [_live(100 + i, won=(i % 2 == 0)) for i in range(40)]
    state, events = g.evaluate(losing + fine, None, NOW)
    assert state["cells"]["kalshi|nba|prop|pregame"]["status"] == "tripped"
    assert state["cells"]["kalshi|nba|prop|pregame"]["trip"]["reason"] in ("ci90_below_zero", "loss")
    assert state["cells"]["kalshi|nba|spread|pregame"]["status"] == "armed"
    assert [e["event"] for e in events] == ["CELL_TRIP"]


def test_ci_needs_bets_and_games_but_a_75_dollar_loss_trips_alone():
    # 39 losing $1 bets: under 40 bets, and only -$39 -> armed
    small = [_live(i, won=False, stake=1.0) for i in range(39)]
    assert g.evaluate(small, None, NOW)[0]["cells"]["kalshi|nba|spread|pregame"]["status"] == "armed"
    # 40 bets, but all on 3 games -> no CI trip; -$40 -> no loss trip
    clustered = [_live(i, won=False, stake=1.0, game=f"g{i % 3}") for i in range(40)]
    assert g.evaluate(clustered, None, NOW)[0]["cells"]["kalshi|nba|spread|pregame"]["status"] == "armed"
    # 8 bets of $10, all lost: -$80 -> the loss rule trips it
    big = [_live(i, won=False, stake=10.0) for i in range(8)]
    st = g.evaluate(big, None, NOW)[0]["cells"]["kalshi|nba|spread|pregame"]
    assert st["status"] == "tripped" and st["trip"]["reason"] == "loss"


def _tripped_state(at):
    return {"cells": {"kalshi|nba|spread|pregame": {"status": "tripped", "tripped_at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                   "trip": {"reason": "loss"}, "armed_since": None}}}


def _twin(n, games, start, *, win_every=3):
    # wins 2 of every 3 at even money -> clearly positive
    return [_live(1000 + i, won=(i % win_every != 0), venue="paper:kalshi", game=f"t{i % games}",
                  when=start + timedelta(hours=i)) for i in range(n)]


def test_a_tripped_cell_rearms_on_its_forward_paper_twin_only():
    tripped_at = NOW - timedelta(days=20)
    old_live_losses = [_live(i, won=False, stake=10.0, when=tripped_at - timedelta(days=2)) for i in range(10)]
    twin = _twin(160, 44, tripped_at + timedelta(hours=1))
    state, events = g.evaluate(old_live_losses + twin, _tripped_state(tripped_at), NOW)
    cell = state["cells"]["kalshi|nba|spread|pregame"]
    assert cell["status"] == "armed" and cell["armed_since"] == "2026-10-25T14:00:00Z"
    assert [e["event"] for e in events] == ["CELL_REARM"]
    # the next evaluation must not re-trip it on the record from before it re-armed
    again, events2 = g.evaluate(old_live_losses + twin, state, NOW + timedelta(hours=1))
    assert again["cells"]["kalshi|nba|spread|pregame"]["status"] == "armed" and events2 == []


@pytest.mark.parametrize("case", ["too_soon", "pre_trip_record", "too_few_games", "not_positive"])
def test_rearm_is_refused_without_the_full_record(case):
    tripped_at = NOW - timedelta(days=20)
    if case == "too_soon":
        tripped_at = NOW - timedelta(days=10)
        twin = _twin(160, 44, tripped_at + timedelta(minutes=5), win_every=3)
        twin = [dict(t, submitted_at=(tripped_at + timedelta(minutes=5 + i)).strftime("%Y-%m-%dT%H:%M:%SZ"))
                for i, t in enumerate(twin)]
    elif case == "pre_trip_record":
        twin = _twin(160, 44, tripped_at - timedelta(days=10))
    elif case == "too_few_games":
        twin = _twin(160, 30, tripped_at + timedelta(hours=1))
    else:
        twin = _twin(160, 44, tripped_at + timedelta(hours=1), win_every=2)  # 50% at -10% loss per loser
        twin = [dict(t, pnl_dollars=-5.0 if t["outcome"] == "lost" else 4.0) for t in twin]
    state, events = g.evaluate(twin, _tripped_state(tripped_at), NOW)
    assert state["cells"]["kalshi|nba|spread|pregame"]["status"] == "tripped" and events == []


def test_allows_refuses_tripped_and_unknown():
    gate = {"cells": {"kalshi|nba|prop|pregame": {"status": "tripped"}}, "unknown": None}
    assert g.allows("kalshi|nba|prop|pregame", gate) == (False, g.REFUSAL)
    assert g.allows("kalshi|nba|spread|pregame", gate) == (True, None)
    assert g.allows("kalshi|nba|spread|pregame", {"cells": {}, "unknown": "x"}) == (False, g.REFUSAL_UNKNOWN)
    rows = [{"sport": "nba", "market": "player_points", "player_name": "X"}, {"sport": "nba", "market": "spreads"}]
    kept, refused = g.filter_rows(rows, venue="kalshi", gate=gate)
    assert kept == [rows[1]] and refused == {g.REFUSAL: 1}


def test_refresh_fails_closed_on_an_unreadable_state_or_ledger(capsys):
    writes = []
    bad_state = g.refresh(force=True, now=NOW, read_state_fn=lambda: (None, False), orders_fn=lambda: [],
                          write_state_fn=writes.append)
    assert bad_state["unknown"] and writes == []
    assert g.allows("kalshi|nba|spread|pregame", bad_state)[0] is False
    bad_ledger = g.refresh(force=True, now=NOW, read_state_fn=lambda: (None, True), orders_fn=lambda: None,
                           write_state_fn=writes.append)
    assert bad_ledger["unknown"] and writes == []
    assert "CELL_GATE_UNKNOWN" in capsys.readouterr().out


def test_refresh_confirmed_absent_state_is_first_run_and_logs_trips(capsys):
    writes = []
    big = [_live(i, won=False, stake=10.0) for i in range(8)]
    out = g.refresh(force=True, now=NOW, read_state_fn=lambda: (None, True), orders_fn=lambda: big,
                    write_state_fn=writes.append)
    assert out["unknown"] is None and len(writes) == 1
    assert writes[0]["cells"]["kalshi|nba|spread|pregame"]["status"] == "tripped"
    log = capsys.readouterr().out
    assert "CELL_TRIP cell=kalshi|nba|spread|pregame" in log and "LIVE_CELL_GATE cells=1 tripped=1" in log


# ---------------------------------------------------------------- reachability at the consumer (off != on)

def _shortlist():
    return {"rows": [{"suggested": True, "sport": "nba", "market": "spreads"},
                     {"suggested": False, "suggested_reasons": ["ev_below_min"], "sport": "nba", "market": "totals"}]}


def test_stuck_global_stop_gates_live_only_when_the_cell_gate_is_off(monkeypatch):
    from pipeline import portfolio_commit as pc

    monkeypatch.setenv(pc.LIVE_EV_FLOOR_ENV, "0")
    monkeypatch.setattr(pc, "live_ev_floor_stop_state", lambda **_: {"settled": 125, "roi": -0.17, "tripped": True})
    # OFF: today's behaviour -- the stuck trip sends live back to Suggested-only (None)
    assert pc._live_ev_floor_population(_shortlist(), "2026-10-25") is None
    # ON: the stuck trip is replaced; the floor population (Suggested + EV-only extras) reaches the gate
    monkeypatch.setenv(g.MODE_ENV, "on")
    rows = pc._live_ev_floor_population(_shortlist(), "2026-10-25")
    assert rows is not None and len(rows) == 2


def test_only_the_exact_word_on_enables_it(monkeypatch):
    for raw in ("", "1", "true", "ON ", "shadow"):
        monkeypatch.setenv(g.MODE_ENV, raw)
        assert g.enabled() is (raw.strip().lower() == "on")


def test_the_venue_loop_filters_live_rows_before_the_live_plan_is_written():
    src = (Path(__file__).resolve().parents[1] / "pipeline" / "portfolio_commit.py").read_text(encoding="utf-8")
    hook = src.index("live_cell_gate.filter_rows(live_scoped, venue=venue, gate=gate)")
    write = src.index("_write_live_venue_plan(\n                    live_scoped,")
    assert src.index("live_scoped, live_scope_refusals = scoped, scope_refusals") < hook < write
