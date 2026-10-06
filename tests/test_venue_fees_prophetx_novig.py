"""ProphetX and Novig fee schedules (lane published-negative-ev, 2026-10-06, user "add fee schedules").

ProphetX: 2% of net winnings per market, on a WIN only (straights). Novig: takers pay coef x p x (1-p)
per contract, coef 0 pregame straight / 0.03 live. Published terms, not yet measured from a fill.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import execution_ledger as el
from syndicate.features.shared import paper_settlement as ps
from syndicate.features.shared import venue_fees as vf


def _iso(delta_hours):
    return (datetime.now(timezone.utc) + timedelta(hours=delta_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_the_published_rates():
    assert vf.taker_fee_per_contract("prophetx", 0.5) == (pytest.approx(0.02 * 0.5 * 0.5), "prophetx_expected_win_commission", False)
    assert vf.taker_fee_per_contract("novig", 0.4, in_play=False) == (0.0, "novig_pregame_straight", False)
    assert vf.taker_fee_per_contract("novig", 0.4, in_play=True) == (pytest.approx(0.03 * 0.4 * 0.6), "novig_live", False)


def test_an_unknown_phase_at_novig_is_charged_live_and_flagged_as_a_bound():
    fee, basis, bound = vf.taker_fee_per_contract("novig", 0.4)
    assert fee == pytest.approx(0.03 * 0.4 * 0.6) and basis == "novig_assumed_live_rate" and bound is True


def test_a_sportsbook_is_still_free():
    assert vf.taker_fee_per_contract("fanduel", 0.5) == (0.0, "none", False)


def _order(book, commence_hours, price=100, stake=10.0):
    return {"venue": "paper", "book": book, "fill_price": price, "fill_stake_dollars": stake,
            "commence_time": _iso(commence_hours), "sport": "nfl", "market": "h2h", "status": "filled"}


def test_reachability_a_prophetx_paper_fill_pays_nothing_at_fill_and_2pct_of_a_win_at_settlement():
    fields = el.paper_fill_fee_fields(_order("prophetx", 5))
    assert fields == {"fees_dollars": 0.0, "fee_basis": vf.PROPHETX_SETTLEMENT_BASIS, "fee_is_upper_bound": False}
    order = {**_order("prophetx", 5), **fields}
    won = ps.grade_order(order, {"decided": True, "status": "won"})
    lost = ps.grade_order(order, {"decided": True, "status": "lost"})
    assert won["pnl_dollars"] == pytest.approx(10.0 - 0.2)  # +100: win 10, 2% of 10
    assert lost["pnl_dollars"] == pytest.approx(-10.0)      # no fee on a loss


def test_a_novig_paper_fill_is_free_pregame_and_charged_live():
    pregame = el.paper_fill_fee_fields(_order("novig", 5, price=-150))
    live = el.paper_fill_fee_fields(_order("novig", -1, price=-150))
    assert pregame["fees_dollars"] == 0.0 and pregame["fee_basis"] == "novig_pregame_straight"
    p = 150 / 250
    contracts = 10.0 / p
    assert live["fees_dollars"] == pytest.approx(vf.ceil_to_fee_precision(contracts * 0.03 * p * (1 - p)))
    assert live["fee_basis"] == "novig_live"
