"""Offline fitters read a live venue CONTRACT price as a contract price (todo #719 follow-up).

The execution ledger holds both units in one column: a paper fill records
American odds (-110), a live Kalshi/Polymarket fill records the contract price
(0.65). Read as American, 0.65 gives a profit of 0.0065 per unit, `fair` lands
outside (0, 1) and the row is dropped from the fit with no log line.

A live order's `requested_price` is the plan's venue price in American odds and
is what `ev_pct` was stamped against (`venue_scope.py`); its `fill_price` is the
contract price actually paid. A paper order copies requested into fill.
"""

from __future__ import annotations

import pytest

from scripts import ev_overstatement_decomp as decomp
from scripts import fit_probability_calibration as calib


def _american_profit(american: float) -> float:
    return american / 100.0 if american > 0 else 100.0 / abs(american)


def _order(**overrides):
    order = {
        "sport": "nfl",
        "market": "h2h",
        "segment": "full_game",
        "outcome": "won",
        "model_edge_pct": 2.0,
        "ev_pct": 3.0,
        "selected_date": "2026-10-21",
        "scorer_version": "v1",
    }
    order.update(overrides)
    return order


# ---------------------------------------------------------------- calibration fitter


def test_contract_price_profit_multiple():
    assert calib._net_profit_per_unit(0.65) == pytest.approx(0.35 / 0.65)
    assert calib._net_profit_per_unit(0.46) == pytest.approx(0.54 / 0.46)


def test_american_profit_multiple_unchanged():
    for american in (-110.0, -186.0, 150.0, -900.0, 100.0):
        assert calib._net_profit_per_unit(american) == pytest.approx(_american_profit(american))
    assert calib._net_profit_per_unit(0.0) is None


def test_live_row_with_contract_fill_is_kept_and_fair_comes_from_the_stamp():
    order = _order(requested_price=-186.0, fill_price=0.66)
    row = calib.row_from_order(order, artifact_root="r")
    assert row is not None
    fair = 1.03 / (_american_profit(-186.0) + 1.0)
    assert row["model_probability"] == pytest.approx(fair + 0.02)


def test_contract_only_row_is_kept():
    # No requested price at all: the contract fill alone must still be usable.
    row = calib.row_from_order(_order(requested_price=None, fill_price=0.65), artifact_root="r")
    assert row is not None
    assert row["model_probability"] == pytest.approx(1.03 * 0.65 + 0.02)
    row = calib.row_from_order(_order(requested_price=0.65, fill_price=None), artifact_root="r")
    assert row is not None
    assert row["model_probability"] == pytest.approx(1.03 * 0.65 + 0.02)


@pytest.mark.parametrize("american", [-110.0, -186.0, 150.0, 240.0])
def test_paper_american_row_unchanged(american):
    # A paper fill copies requested into fill (execution_ledger fill_price=requested_price).
    for fields in ({"requested_price": american, "fill_price": american},
                   {"fill_price": american}, {"requested_price": american}):
        row = calib.row_from_order(_order(**fields), artifact_root="r")
        assert row is not None
        expected = 1.03 / (_american_profit(american) + 1.0) + 0.02
        assert row["model_probability"] == pytest.approx(expected, abs=1e-12)


def test_ambiguous_or_missing_price_still_dropped():
    assert calib.row_from_order(_order(), artifact_root="r") is None
    assert calib.row_from_order(_order(fill_price=0.0), artifact_root="r") is None


# ---------------------------------------------------------------- ev overstatement decomp


def test_decimal_odds_reads_both_units():
    assert decomp.decimal_odds(0.65) == pytest.approx(1.0 / 0.65)
    assert decomp.decimal_odds(-110) == pytest.approx(1.0 + 100.0 / 110.0)
    assert decomp.decimal_odds(150) == pytest.approx(2.5)


def test_decomp_enrich_live_row_fair_from_stamp_return_at_fill():
    live = _order(requested_price=-186.0, fill_price=0.66, event_id="e1",
                  fill_stake_dollars=6.6, pnl_dollars=3.4)
    paper = _order(requested_price=-110.0, fill_price=-110.0, event_id="e2", outcome="lost")
    rows = {r["event_id"]: r for r in decomp.enrich([live, paper])}
    assert rows["e1"]["_pf"] == pytest.approx(1.03 / (1.0 + 100.0 / 186.0))
    assert rows["e1"]["_ret"] == pytest.approx(0.34 / 0.66)
    assert rows["e2"]["_pf"] == pytest.approx(1.03 / (1.0 + 100.0 / 110.0))
    assert rows["e2"]["_ret"] == -1.0
