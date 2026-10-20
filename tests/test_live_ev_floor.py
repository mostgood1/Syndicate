"""The live-only 0% net EV floor (user 2026-10-20), and its stop rule.

"Build the live-only 0% net floor as shown (Suggested OR only-EV reasons, live
venue plans only, opt-in key, tagged live_ev_floor=0), with a stop rule: revert
to Suggested-only if live 0-2% rows show ROI below -5% after 100 settled bets."
"""

from __future__ import annotations

import pytest

from pipeline import portfolio_commit as pc
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_TICKER = "KXNCAAFTOTAL-26OCT20MTUFIU-45"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    for name in (pc.LIVE_EV_FLOOR_ENV, "SYNDICATE_COMPOUNDING_BANKROLL", "SYNDICATE_LIVE_STAKE_BAND",
                 "SYNDICATE_LIVE_SMALL_EDGE_FRACTION", "SYNDICATE_EXECUTION_MODE"):
        monkeypatch.delenv(name, raising=False)
    pc._LIVE_EV_FLOOR_STOP_CACHE.clear()
    yield
    pc._LIVE_EV_FLOOR_STOP_CACHE.clear()


def _shortlist_row(event_id, *, suggested, reasons=None, **extra):
    row = {"event_id": event_id, "suggested": suggested, "suggested_reasons": reasons or []}
    row.update(extra)
    return row


# ---- the key ---------------------------------------------------------------


@pytest.mark.parametrize("raw, on", [(None, False), ("", False), ("0", True), ("0.0", True), ("1", False), ("2", False), ("abc", False)])
def test_only_zero_turns_it_on(monkeypatch, raw, on):
    if raw is not None:
        monkeypatch.setenv(pc.LIVE_EV_FLOOR_ENV, raw)
    assert pc.live_ev_floor_requested() is on


# ---- the population --------------------------------------------------------


def test_population_is_suggested_plus_ev_only_rows():
    raw = [
        _shortlist_row("s", suggested=True),
        _shortlist_row("ev", suggested=False, reasons=["ev_below_min"]),
        _shortlist_row("ev2", suggested=False, reasons=["ev_below_min", "ev_net_of_fee_below_min"]),
        _shortlist_row("stale", suggested=False, reasons=["ev_below_min", "suspect_stale_quote"]),
        _shortlist_row("onesided", suggested=False, reasons=["one_sided_fair"]),
        _shortlist_row("other_side", suggested=False, reasons=["other_side_suggested"]),
        {"event_id": "noflag"},
    ]
    rows, counts = pc.live_ev_floor_rows(raw)
    assert [r["event_id"] for r in rows] == ["s", "ev", "ev2"]
    assert counts == {"suggested": 1, "ev_only_extra": 2, "other_reasons": 3, "flag_absent": 1}
    assert rows[0] is raw[0] and "live_ev_floor" not in rows[0]       # suggested rows untouched
    assert rows[1]["live_ev_floor"] == 0 and "live_ev_floor" not in raw[1]  # extras are tagged COPIES


def test_population_reaches_the_build_off_differs_from_on(monkeypatch):
    shortlist = {"rows": [_shortlist_row("s", suggested=True), _shortlist_row("ev", suggested=False, reasons=["ev_below_min"])]}
    assert pc._live_ev_floor_population(shortlist, "2026-10-20") is None
    monkeypatch.setenv(pc.LIVE_EV_FLOOR_ENV, "0")
    rows = pc._live_ev_floor_population(shortlist, "2026-10-20")
    assert [r["event_id"] for r in rows] == ["s", "ev"]


# ---- the tag on live positions --------------------------------------------


def _settings():
    return PortfolioSettings(bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
                             max_positions=50, min_stake_units=0.0)


def _venue_row(event_id, *, floor=False):
    row = {
        "sport": "ncaaf", "event_id": event_id, "kind": "game", "market": "h2h", "segment": "full_game",
        "line": None, "player_name": None, "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-10-20T23:05:00Z", "side": "home",
        "quote": {"price": -110, "bookmaker": "kalshi"}, "ev_pct": 4.5, "model_edge_pct": 3.2,
        "score": {"score": 5.0, "price_reliability": 0.82}, "venue": "kalshi",
        "price_source": "venue_feed", "venue_ticker": _TICKER,
    }
    if floor:
        row["live_ev_floor"] = 0
    return row


def test_live_positions_from_floor_rows_are_tagged():
    plan = pc.commit_live_venue_plan([_venue_row("g1"), _venue_row("g2", floor=True)],
                                     selected_date="2026-10-20", settings=_settings())
    tags = {p["event_id"]: p.get("live_ev_floor") for p in plan["positions"]}
    assert tags == {"g1": None, "g2": 0}
    assert plan["live_ev_floor"]["extra_positions"] == 1


def test_the_log_records_each_floor_position_once():
    plan = {"positions": [{"position_key": "k1", "live_ev_floor": 0, "ev_pct": 1.1},
                          {"position_key": "k2"}]}
    assert pc.record_live_ev_floor_positions(plan, selected_date="2026-10-20", venue="kalshi") == 1
    assert pc.record_live_ev_floor_positions(plan, selected_date="2026-10-20", venue="kalshi") == 0
    from syndicate.features.shared.refresh_state_store import read_json_file

    entries = read_json_file(pc._live_ev_floor_log_path())["entries"]
    assert [e["position_key"] for e in entries] == ["k1"]


# ---- the stop rule ---------------------------------------------------------


def _settled(n, roi, key_prefix="k"):
    orders = []
    for i in range(n):
        orders.append({"mode": "live", "selected_date": "2026-10-20", "position_key": f"{key_prefix}{i}",
                       "outcome": "won" if roi >= 0 else "lost", "fill_stake_dollars": 10.0, "pnl_dollars": roi * 10.0})
    return orders


def _write_log(n, key_prefix="k"):
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(pc._live_ev_floor_log_path(), {"entries": [
        {"selected_date": "2026-10-20", "venue": "kalshi", "position_key": f"{key_prefix}{i}"} for i in range(n)
    ]})


@pytest.mark.parametrize("n, roi, tripped", [(100, -0.06, True), (99, -0.5, False), (100, -0.04, False), (150, 0.02, False)])
def test_stop_rule_boundaries(monkeypatch, n, roi, tripped):
    from syndicate.features.shared import execution_ledger

    _write_log(n)
    monkeypatch.setattr(execution_ledger, "full_history_orders", lambda: _settled(n, roi))
    state = pc.live_ev_floor_stop_state(force=True)
    assert state["settled"] == n
    assert state["tripped"] is tripped


def test_only_floor_positions_count_toward_the_stop_rule(monkeypatch):
    from syndicate.features.shared import execution_ledger

    _write_log(10)  # only k0..k9 are floor positions
    monkeypatch.setattr(execution_ledger, "full_history_orders", lambda: _settled(200, -0.5))
    assert pc.live_ev_floor_stop_state(force=True)["settled"] == 10


def test_a_tripped_rule_returns_the_build_to_suggested_only(monkeypatch):
    from syndicate.features.shared import execution_ledger

    monkeypatch.setenv(pc.LIVE_EV_FLOOR_ENV, "0")
    _write_log(100)
    monkeypatch.setattr(execution_ledger, "full_history_orders", lambda: _settled(100, -0.2))
    pc.live_ev_floor_stop_state(force=True)
    shortlist = {"rows": [_shortlist_row("ev", suggested=False, reasons=["ev_below_min"])]}
    assert pc._live_ev_floor_population(shortlist, "2026-10-20") is None


def test_an_unreadable_ledger_does_not_trip(monkeypatch):
    from syndicate.features.shared import execution_ledger

    def _boom():
        raise RuntimeError("store down")

    monkeypatch.setattr(execution_ledger, "full_history_orders", _boom)
    state = pc.live_ev_floor_stop_state(force=True)
    assert state["tripped"] is False and "unknown" in state
