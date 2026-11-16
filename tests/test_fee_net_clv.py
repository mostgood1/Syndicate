"""Fee-net CLV: the close compared with what a bet cost INCLUDING the venue's fee (todo #815).

Measured on the fleet's live ledger 2026-11-16 (545 same-book marks): gross CLV
+1.32 pp, mean taker fee 1.63 pp, fee-net -0.30 +- 0.19 pp -- while settled
results were significantly negative. The gross number made a losing book read
as "beating the close". These tests pin the unit, the unknown-fee rule, the
order marks, and that the tuner's decision actually changes with the basis
(reachability: off != on).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import min_ev_tuner as T
from syndicate.features.shared import paper_settlement as settle
from syndicate.features.shared.order_clv import (
    REASON_RESOLVED,
    SCOPE_SAME_BOOK,
    clv_for_orders,
    fee_net_clv_pct,
    fee_pp_for_order,
    order_clv_report_line,
)

DATE = "2026-11-10"
CELL = "kalshi|ncaaf|totals|regular"


# --- the unit -----------------------------------------------------------------


def test_fee_in_probability_points_is_price_times_fee_over_stake():
    # $6.00 at 0.60 buys 10 contracts; a $0.11 fee is 1.1 cents a contract = 1.1 pp.
    order = {"fill_price": 0.60, "fill_stake_dollars": 6.0, "fees_dollars": 0.11}
    assert fee_pp_for_order(order) == pytest.approx(1.1)


def test_american_price_is_converted_before_the_fee_is_scaled():
    # -150 is 0.60 implied; $10 stake, $0.20 fee -> 100 * 0.6 * 0.02 = 1.2 pp.
    order = {"fill_price": -150, "fill_stake_dollars": 10.0, "fees_dollars": 0.20}
    assert fee_pp_for_order(order) == pytest.approx(1.2, abs=1e-3)


def test_fill_price_and_stake_win_over_the_request():
    order = {
        "requested_price": 0.40, "fill_price": 0.60,
        "requested_stake_dollars": 20.0, "fill_stake_dollars": 6.0,
        "fees_dollars": 0.11,
    }
    assert fee_pp_for_order(order) == pytest.approx(1.1)


def test_unknown_fee_is_no_reading_never_zero():
    order = {"fill_price": 0.60, "fill_stake_dollars": 6.0, "fees_dollars": None}
    assert fee_pp_for_order(order) is None
    assert fee_net_clv_pct(order, 1.5) is None
    assert fee_pp_for_order({"fill_price": 0.60, "fill_stake_dollars": 6.0}) is None


def test_a_recorded_zero_fee_is_zero_at_any_price():
    assert fee_pp_for_order({"fees_dollars": 0.0}) == 0.0
    assert fee_net_clv_pct({"fill_price": -110, "fees_dollars": 0.0}, 4.1) == pytest.approx(4.1)


def test_prophetx_uses_the_expected_commission_never_the_realised_one():
    # Charged on a win only, at settlement. A won order's realised fee depends on the result,
    # so the pre-result measure uses venue_fees' expected commission at the fill's probability.
    won = {
        "fill_price": 0.40, "fill_stake_dollars": 10.0,
        "fee_basis": "prophetx_win_commission_at_settlement", "fees_dollars": 0.30,
    }
    lost = dict(won, fees_dollars=0.0)
    expected = 100 * 0.02 * 0.40 * 0.60
    assert fee_pp_for_order(won) == pytest.approx(expected)
    assert fee_pp_for_order(lost) == pytest.approx(expected)


def test_net_is_gross_less_fee():
    order = {"fill_price": 0.60, "fill_stake_dollars": 6.0, "fees_dollars": 0.11}
    assert fee_net_clv_pct(order, 1.32) == pytest.approx(0.22)
    assert fee_net_clv_pct(order, None) is None


# --- order CLV rows and aggregates ---------------------------------------------


def _order(key, *, fees, fill=0.60, stake=6.0, opening_key=None):
    return {
        "idempotency_key": key,
        "opening_key": opening_key or f"o-{key}",
        "sport": "ncaaf",
        "market": "totals",
        "side": "over",
        "book": "kalshi",
        "venue": "kalshi",
        "fill_price": fill,
        "requested_price": fill,
        "fill_stake_dollars": stake,
        "requested_stake_dollars": stake,
        "fees_dollars": fees,
    }


def _close(key, close_price):
    return {"key": f"o-{key}", "sport": "ncaaf", "market": "totals", "close_price": close_price,
            "close_source": "book_quotes_last_pregame"}


def test_resolved_rows_carry_gross_and_net_side_by_side():
    report = clv_for_orders(
        [_order("a", fees=0.11), _order("b", fees=None)],
        date=DATE,
        clv_rows=[_close("a", 0.62), _close("b", 0.62)],
    )
    rows = {row["idempotency_key"]: row for row in report["rows"]}
    a, b = rows["a"], rows["b"]
    assert a["reason"] == b["reason"] == REASON_RESOLVED
    assert a["clv_pct"] == pytest.approx(2.0)
    assert a["fee_pp"] == pytest.approx(1.1)
    assert a["clv_net_pct"] == pytest.approx(0.9)
    # Unknown fee: the gross reading stands, the net one is absent -- not the gross under a net name.
    assert b["clv_pct"] == pytest.approx(2.0)
    assert b["fee_pp"] is None and b["clv_net_pct"] is None

    scope = next(e for e in report["by_scope"] if e["close_book_scope"] == SCOPE_SAME_BOOK)
    assert scope["n"] == 2 and scope["clv_net_n"] == 1
    assert scope["avg_clv_pct"] == pytest.approx(2.0)
    assert scope["avg_clv_net_pct"] == pytest.approx(0.9)
    line = order_clv_report_line(report)
    assert "same_book_avg_clv_net_pct=" in line and "same_book_net_n=" in line


def test_a_bet_that_beats_the_close_by_less_than_its_fee_is_net_negative():
    report = clv_for_orders([_order("a", fees=0.11)], date=DATE, clv_rows=[_close("a", 0.605)])
    row = report["rows"][0]
    assert row["beat_close"] is True
    assert row["clv_net_pct"] < 0


# --- the closing mark on the order ---------------------------------------------


def test_closing_mark_stamps_net_beside_gross_and_none_when_unknown():
    orders = [
        dict(_order("a", fees=0.11), status="filled", outcome="won"),
        dict(_order("b", fees=None), status="filled", outcome="lost"),
    ]

    def closer(rows, date):
        return clv_for_orders(rows, date=date, clv_rows=[_close("a", 0.62), _close("b", 0.62)])

    result = settle.stamp_closing_marks(orders, DATE, closer=closer)
    assert result["stamped"] == 2
    a, b = orders[0]["closing_mark"], orders[1]["closing_mark"]
    assert a["clv_pct"] == pytest.approx(2.0)
    assert a["fee_pp"] == pytest.approx(1.1)
    assert a["clv_net_pct"] == pytest.approx(0.9)
    # Always present on a new mark, None when the fee is unknown.
    assert "clv_net_pct" in b and b["clv_net_pct"] is None
    assert b["clv_pct"] == pytest.approx(2.0)


def test_an_old_mark_without_the_net_key_is_netted_from_the_order_fee():
    # Marks stamped before 2026-11-16 carry no clv_net_pct and are not rewritten.
    order = dict(_order("a", fees=0.11), closing_mark={"clv_pct": 2.0, "close_price": 0.62,
                                                      "close_book_scope": "same_book"})
    assert "clv_net_pct" not in order["closing_mark"]
    assert fee_net_clv_pct(order, order["closing_mark"]["clv_pct"]) == pytest.approx(0.9)


# --- the tuner: reachability first (net != gross) ------------------------------


def _tuner_order(i, *, fees=0.4, won=None):
    """A Kalshi fill at 0.50 that BEATS the close gross (+1.0..+2.0 pp) but pays a
    2.0 pp fee ($0.40 on $10 at 0.50), so it LOSES to the close net (-1.0..0.0 pp).
    Mostly losses: ROI is significantly negative either way. This is the 2026-11-16
    live book in miniature."""
    won = (i % 5 == 0) if won is None else won
    close = (0.51, 0.515, 0.52)[i % 3]
    stake = 10.0
    fee = fees if fees is not None else 0.4
    pnl = (stake * (1 / 0.5 - 1) - fee) if won else (-stake - fee)
    return {
        "idempotency_key": f"k{i}",
        "event_id": f"e{i}",
        "venue": "paper:kalshi",
        "mode": "paper",
        "sport": "ncaaf",
        "market": "totals",
        "selected_date": "2026-10-10",
        "status": "filled",
        "outcome": "won" if won else "lost",
        "pnl_dollars": pnl,
        "fill_price": 0.5,
        "requested_price": 0.5,
        "fill_stake_dollars": stake,
        "fees_dollars": fees,
        "ev_pct": 2.0,
        "graded_at": f"2026-10-10T23:{i % 60:02d}:00Z",
        "closing_mark": {"clv_pct": None, "close_price": close, "close_book_scope": "same_book"},
    }


@pytest.fixture
def clean_env(monkeypatch):
    for key in [k for k in __import__("os").environ if k.startswith("SYNDICATE_MIN_EV_TUNER")]:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_tuner_basis_changes_the_decision_net_raises_gross_holds(clean_env):
    rows = [_tuner_order(i) for i in range(60)]
    net = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0, clv_basis_override="net")
    gross = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0, clv_basis_override="gross")
    n_cell, g_cell = net["cells"][CELL], gross["cells"][CELL]
    assert n_cell["marginal"]["clv_basis"] == "net"
    assert n_cell["marginal"]["avg_clv_pct"] < 0 < n_cell["marginal"]["avg_clv_gross_pct"]
    assert n_cell["action"] == T.ACTION_RAISE
    assert n_cell["reason"] == "roi_and_clv_significantly_negative"
    # Gross CLV says "beat the close" while ROI loses: the RAISE the fee hid.
    assert g_cell["action"] == T.ACTION_HOLD
    assert g_cell["reason"] == "roi_and_clv_opposite_signs"
    assert net["clv_basis"] == "net" and gross["clv_basis"] == "gross"


def test_absent_or_unknown_basis_is_net_and_gross_is_explicit(clean_env):
    assert T.clv_basis() == T.CLV_BASIS_NET
    clean_env.setenv("SYNDICATE_MIN_EV_TUNER_CLV_BASIS", "grosss")
    assert T.clv_basis() == T.CLV_BASIS_NET
    clean_env.setenv("SYNDICATE_MIN_EV_TUNER_CLV_BASIS", "gross")
    assert T.clv_basis() == T.CLV_BASIS_GROSS
    rows = [_tuner_order(i) for i in range(60)]
    assert T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"][CELL]["action"] == T.ACTION_HOLD


def test_tuner_drops_unknown_fee_rows_from_net_clv_but_keeps_them_gross(clean_env):
    rows = [_tuner_order(i, fees=None) for i in range(60)]
    ev = T.cell_evidence(rows, trailing_events=150, clv_scopes=("same_book",), clv_basis="net")
    assert ev["clv_events"] == 0 and ev["avg_clv_pct"] is None
    assert ev["clv_gross_events"] == 60
    cell = T.compute_proposals(rows, state={}, base_min_ev_pct=2.0)["cells"][CELL]
    assert cell["action"] == T.ACTION_HOLD and cell["reason"] == "insufficient_clv_events"


def test_tuner_nets_the_RECOMPUTED_gross_not_the_stale_stamped_one(clean_env):
    # todo #719: a live contract mark stamped ~-34 pt. The tuner recomputes ~+1.0 from prices,
    # and the fee comes off THAT number.
    order = _tuner_order(1)
    order["closing_mark"]["clv_pct"] = -34.3
    order["closing_mark"]["close_price"] = 0.51
    assert T._clv(order, ("same_book",), T.CLV_BASIS_GROSS) == pytest.approx(1.0)
    assert T._clv(order, ("same_book",)) == pytest.approx(-1.0)


def test_nightly_state_and_log_name_the_basis(clean_env, monkeypatch, capsys):
    store: dict = {}
    monkeypatch.setattr(T, "load_state", lambda: dict(store.get("s") or {}))
    monkeypatch.setattr(T, "_save_state", lambda state: store.__setitem__("s", dict(state)))
    monkeypatch.setattr(T, "_LAST_RUN_DATE_IN_PROCESS", {})
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_MIN_EV_PCT", raising=False)
    import syndicate.features.shared.portfolio_settings as ps

    monkeypatch.setattr(ps, "_read_stored", lambda: ({}, None))
    result = T.run_nightly(orders_loader=lambda: [_tuner_order(i) for i in range(60)], force=True)
    assert result["ran"] is True
    assert store["s"]["clv_basis"] == "net"
    assert store["s"]["mode"] == "shadow"
    assert result["moves"] and result["moves"][0]["clv_basis"] == "net"
    assert result["moves"][0]["avg_clv_gross_pct"] > 0 > result["moves"][0]["avg_clv_pct"]
    assert "clv_basis=net" in capsys.readouterr().out
