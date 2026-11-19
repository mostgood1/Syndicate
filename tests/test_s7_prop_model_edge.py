"""Hermetic tests for scripts/s7_prop_model_edge.py (S7 arm B, lane s7-combos-props)."""
from __future__ import annotations

import math

import pytest

from scripts import s7_prop_model_edge as s7


def _order(**kw):
    base = {"venue": "paper:kalshi:ladder", "status": "filled", "outcome": "won", "fill_stake_dollars": 0.5,
            "pnl_dollars": 0.5, "fees_dollars": 0.0, "event_id": "e1", "submitted_at": "2026-11-01T12:00:00Z",
            "commence_time": "2026-11-01T23:00:00Z", "requested_price": 0.5, "fill_price": 0.5,
            "ev_pct": 4.0, "model_edge_pct": 3.0, "market": "player_points", "player_name": "A B",
            "sport": "nba", "position_key": "k1", "side": "over", "line": 20.5}
    base.update(kw)
    return base


def _row(game, ret, edge, window="FIT", sub="2026-11-01T12:00:00Z", book="ladder", venue="kalshi", sport="nba"):
    return {"game": game, "ret": ret, "edge_pp": edge, "window": window, "submitted": sub, "book": book,
            "venue": venue, "sport": sport}


def test_model_terms_reconstructs_the_sizers_model_probability():
    mt = s7.model_terms(_order(requested_price=0.40, fill_price=0.40, ev_pct=10.0, model_edge_pct=5.0))
    assert mt["why"] is None
    assert mt["fair"] == pytest.approx(0.44)          # q * (1 + ev/100)
    assert mt["p_model"] == pytest.approx(0.49)       # fair + me/100
    assert mt["be"] == pytest.approx(0.40)            # no fee
    assert mt["edge_pp"] == pytest.approx(9.0)


def test_fee_enters_the_breakeven():
    # 0.5 stake at 0.5 = 1 contract; 0.02 fee -> breakeven 0.52
    mt = s7.model_terms(_order(fees_dollars=0.02))
    assert mt["be"] == pytest.approx(0.52)
    assert mt["edge_pp"] == pytest.approx(100 * (0.5 * 1.04 + 0.03 - 0.52))


@pytest.mark.parametrize("kw,why", [({"model_edge_pct": None}, "no_model_edge"), ({"ev_pct": None}, "no_ev_pct"),
                                    ({"ev_pct": 150.0}, "fair_out_of_range"),
                                    ({"model_edge_pct": 60.0}, "model_out_of_range")])
def test_unpriceable_orders_are_named(kw, why):
    assert s7.model_terms(_order(**kw))["why"] == why


def test_build_rows_keeps_props_only_and_counts_drops():
    orders = [_order(), _order(position_key="k2", market="totals", player_name="", event_id="e2"),
              _order(position_key="k3", model_edge_pct=None, event_id="e3")]
    rows, drops = s7.build_rows(orders)
    assert len(rows) == 1 and rows[0]["window"] == "FIT"
    assert drops["not_prop"] == 1 and drops["prop:no_model_edge"] == 1


def test_windows():
    assert s7.window_of("2026-11-07T23:59:59Z") == "FIT"
    assert s7.window_of("2026-11-08T00:00:00Z") == "TEST"
    assert s7.window_of("2026-11-18T23:59:59Z") == "TEST"
    assert s7.window_of("2026-11-19T12:00:00Z") == "GAP"
    assert s7.window_of("2026-11-20T00:00:00Z") == "FORWARD"


def _fit_rows(per_t_ret):
    """80 events x 5 orders; edge spread over the grid so each T keeps a known set."""
    rows = []
    for g in range(80):
        for j, edge in enumerate((-1.0, 0.5, 2.5, 4.5, 11.0)):
            rows.append(_row(f"g{g}", per_t_ret(edge) + (0.01 if (g + j) % 2 else -0.01), edge))
    return rows


def test_choose_t_picks_the_best_eligible_and_breaks_ties_low():
    ch = s7.choose_t(_fit_rows(lambda e: 0.10 if e >= 2.0 else -0.20))
    # T in {1, 2}: keeps edges 2.5, 4.5, 11 -> best mean; tie between 1 and 2 goes to 1
    assert ch["t"] == 1.0 and ch["stop"] is False


def test_choose_t_stops_when_no_t_beats_breakeven():
    ch = s7.choose_t(_fit_rows(lambda e: -0.05))
    assert ch["stop"] is True and ch["why"] == "best_fit_roi_not_above_breakeven"


def test_choose_t_respects_the_volume_floor():
    rows = _fit_rows(lambda e: 0.50 if e >= 10.0 else 0.01)
    ch = s7.choose_t(rows)
    # T = 10 keeps 80 orders < 200: not eligible, so it cannot win despite the highest ROI
    assert ch["t"] != 10.0
    assert [r for r in ch["table"] if r["t"] == 10.0][0]["eligible"] is False


def test_verdict_rules():
    assert s7.verdict_test({"hi": -0.1}, False).startswith("KILL")
    assert s7.verdict_test({"hi": 5.0}, False) == "FORWARD TEST owed"
    assert s7.verdict_test({"hi": -5.0}, True).startswith("NO CHALLENGER")


def test_forward_uses_first_n_events_by_first_submit_and_the_frozen_t():
    rows = []
    for g in range(5):
        sub = f"2026-11-2{g}T00:00:00Z"
        rows.append(_row(f"g{g}", 0.5, 3.0, window="FORWARD", sub=sub))
        rows.append(_row(f"g{g}", -1.0, 0.5, window="FORWARD", sub=sub))   # below T: never kept
    rows.append(_row("old", 5.0, 9.0, window="TEST", sub="2026-11-10T00:00:00Z"))  # before forward: ignored
    rule = {"t_pp": 2.0, "forward_events": 3, "forward_start": "2026-11-20T00:00:00Z"}
    out = s7.forward(rows, rule)
    assert out["kept_events"] == 5
    assert out["decision"]["n"] == 3 and out["decision"]["roi"] == pytest.approx(50.0)
    assert s7.forward(rows, dict(rule, forward_events=6))["verdict"].startswith("NOT YET")


def test_slope_recovers_a_known_relation():
    rows = [_row(f"g{i}", 0.02 * e, e) for i, e in enumerate([float(x) for x in range(-5, 15)])]
    s = s7.slope(rows)
    assert s["b"] == pytest.approx(2.0)


def test_rule_round_trips_through_the_findings_block(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("x\n### S7_RULE_JSON (frozen)\n\n```json\n{\"t_pp\": 4.0, \"forward_events\": 150}\n```\n",
                 encoding="utf-8")
    assert s7.load_rule_from(str(p))["t_pp"] == 4.0
    assert not math.isnan(s7.Z95)
