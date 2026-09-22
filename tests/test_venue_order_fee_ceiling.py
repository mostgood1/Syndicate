"""Venue-repriced orders: the shortlist's implausible-book ceiling and the venue's fee,
both applied BEFORE an order exists (lane `layer2-score-outcome-calibration`).

User decisions 2026-09-21: "apply the 5.26 ceiling and fee to venue-repriced orders" and
"we should have the fee deduction prior to submit not at submit". Measured on the paper
book 09-08..09-20: 133 orders above 5.27% stated EV, all Kalshi/Polymarket venue-repriced,
returned -26.7% ROI [-46.3, -5.9].
"""
from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings
from syndicate.features.shared.venue_scope import REASON_VENUE_EV_IMPLAUSIBLE, scope_rows_to_venue


@pytest.fixture(autouse=True)
def _sim_sizing_legacy(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_SIM_SIZING", "legacy")


def _p(american):
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def _row(best=-120, ev_pct=1.0, venue_price=-110, market="h2h", sport="mlb", **overrides):
    row = {
        "sport": sport, "event_id": "evt-1", "kind": "game", "market": market, "segment": "full",
        "side": "home", "line": None, "player_name": None, "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-09-22T23:05:00Z", "ev_pct": ev_pct, "model_edge_pct": 2.0,
        "score": {"score": 3.0, "price_reliability": 0.9},
        "quote": {"bookmaker": "draftkings", "price": best,
                  "book_prices": {"draftkings": best, "kalshi": venue_price, "polymarket": venue_price}},
    }
    row.update(overrides)
    return row


def _settings(**overrides):
    base = {"bankroll_units": 1000.0, "max_slate_exposure_fraction": 1.0, "min_ev_pct": 2.0,
            "max_positions": 50, "min_stake_units": 0.0}
    base.update(overrides)
    return PortfolioSettings(**base)


def test_a_venue_price_past_the_shortlist_ceiling_is_refused_by_name():
    # 1% at -130 is a fair of 0.571; at the venue's -105 that re-derives to +11.4% -- an
    # implied book total of ~89.8%, under the shortlist's 95% (EV > 5.26%).
    scoped, refusals = scope_rows_to_venue([_row(best=-130, venue_price=-105)], "kalshi")
    assert scoped == []
    assert refusals == {REASON_VENUE_EV_IMPLAUSIBLE: 1}


def test_a_plausible_venue_row_carries_its_fee_and_net_ev_and_keeps_gross_ev():
    scoped, _ = scope_rows_to_venue([_row()], "kalshi", ticker_resolver=lambda r: "KXMLBGAME-26SEP22X-HOME")
    (row,) = scoped
    P = _p(-110)
    assert row["venue_fee_basis"] == "kalshi_series"          # read off the resolved ticker
    assert row["venue_fee_per_contract"] == pytest.approx(0.07 * 0.5 * P * (1 - P), abs=1e-6)
    fair = (1.01) / (1 + 100 / 120)
    assert row["ev_pct"] == pytest.approx((fair / P - 1) * 100, abs=1e-4)      # GROSS, unchanged
    assert row["ev_pct_net_of_fee"] == pytest.approx((fair / (P + row["venue_fee_per_contract"]) - 1) * 100, abs=1e-4)
    assert row["ev_pct_net_of_fee"] < row["ev_pct"]


def test_polymarket_rows_pay_the_measured_flat_fee():
    (row,), _ = scope_rows_to_venue([_row()], "polymarket")
    assert row["venue_fee_basis"] == "polymarket_measured_notional"
    assert row["venue_fee_per_contract"] == pytest.approx(0.015)


def test_a_row_that_is_positive_only_before_the_fee_is_refused_by_its_own_name():
    # -116 -> -110 on Polymarket: gross venue EV ~2.5% passes the 2% minimum; the
    # 1.5c/contract fee takes it NEGATIVE (~-0.3%), so it is not a +EV bet at all.
    scoped, _ = scope_rows_to_venue([_row(best=-116, ev_pct=0.0)], "polymarket")
    (row,) = scoped
    assert row["ev_pct"] >= 2.0 and row["ev_pct_net_of_fee"] <= 0.0, (row["ev_pct"], row["ev_pct_net_of_fee"])
    plan = commit_portfolio(scoped, selected_date="2026-09-22", settings=_settings())
    assert not plan.get("positions")
    assert (plan.get("refusals") or {}).get("below_min_ev_pct_net_of_fee") == 1


def test_positive_after_fees_is_enough_the_2pct_minimum_stays_on_the_venue_price():
    # -118 -> -110: gross ~4.4%, net ~1.6% -- positive after the fee, so it is kept
    # (user decision "Positive after fees"; a 2%-after-fee bar would have refused it).
    scoped, _ = scope_rows_to_venue([_row(best=-118, ev_pct=0.0)], "polymarket")
    (row,) = scoped
    assert 0.0 < row["ev_pct_net_of_fee"] < 2.0 <= row["ev_pct"]
    plan = commit_portfolio(scoped, selected_date="2026-09-22", settings=_settings())
    assert len(plan.get("positions") or []) == 1, plan.get("refusals")


def test_the_after_fee_floor_is_a_setting(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MIN_EV_NET_OF_FEE_PCT", "2.0")
    scoped, _ = scope_rows_to_venue([_row(best=-118, ev_pct=0.0)], "polymarket")
    plan = commit_portfolio(scoped, selected_date="2026-09-22", settings=_settings())
    assert (plan.get("refusals") or {}).get("below_min_ev_pct_net_of_fee") == 1
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MIN_EV_NET_OF_FEE_PCT", "not-a-number")
    plan = commit_portfolio(scoped, selected_date="2026-09-22", settings=_settings())
    assert len(plan.get("positions") or []) == 1


def test_the_fee_shrinks_the_stake_but_not_the_committed_price():
    with_fee, _ = scope_rows_to_venue([_row()], "kalshi", ticker_resolver=lambda r: "KXMLBGAME-26SEP22X-HOME")
    without_fee = [dict(with_fee[0], venue_fee_per_contract=0.0, ev_pct_net_of_fee=None)]
    fee_plan = commit_portfolio(with_fee, selected_date="2026-09-22", settings=_settings(min_ev_pct=-100.0))
    free_plan = commit_portfolio(without_fee, selected_date="2026-09-22", settings=_settings(min_ev_pct=-100.0))
    (fee_pos,), (free_pos,) = fee_plan["positions"], free_plan["positions"]
    assert fee_pos["price"] == free_pos["price"] == -110          # the order is sent at the venue price
    assert 0 < fee_pos["stake_fraction"] < free_pos["stake_fraction"]


def test_a_sportsbook_plan_row_is_untouched():
    """The main plan never scopes; a row with no venue fields sizes exactly as before."""
    row = _row()
    plan = commit_portfolio([row], selected_date="2026-09-22", settings=_settings(min_ev_pct=-100.0))
    (pos,) = plan["positions"]
    assert pos["price"] == -120 and pos["book"] == "draftkings"
