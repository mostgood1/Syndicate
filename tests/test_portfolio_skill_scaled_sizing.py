"""Every model edge SIZES; its measured record SCALES it. No sport or verdict zeroes it.

`[2026-10-05, user directive, lane stop-market-withholding]`: "WE HAVE TO STOP
WITHHOLDING MARKETS! THIS IS A PRIME DIRECTIVE OF THE APP. All lines are judged
individually - models are tested for accuracy but each bet is at the line level".

Replaces `test_portfolio_sim_skill_gate.py` (2026-09-19 "All sports": only a model
measured to beat the market could size) and `test_portfolio_price_basis_sports.py`
(2026-09-18: NCAAF sized on price only). Both gates are deleted from
`portfolio_commit`, so their env keys are pinned inert here.
"""
from __future__ import annotations

import pytest

from syndicate.features.shared import portfolio_commit
from syndicate.features.shared.measured_market_skill import SKILL_FLOOR
from syndicate.features.shared.portfolio_commit import (
    _cut_rank_score,
    _sim_sizing_basis,
    _sizing_model_edge,
    sizing_basis_of,
    sizing_inputs_from_row,
)

FAIR_ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"

UNMEASURED = {"status": "unmeasured", "verdict": "model never backtested"}
LOSES = {"status": "measured", "verdict_class": "loses_to_market", "established_loss_rel": 0.04}
LOSES_BADLY = {"status": "measured", "verdict_class": "loses_to_market", "established_loss_rel": 0.9}
BEATS = {"status": "measured", "verdict_class": "beats_market"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(FAIR_ENV, "mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer")
    monkeypatch.setenv("SYNDICATE_SKILL_OVERLAY", "off")


def _row(skill=UNMEASURED, sport="wnba", **over):
    row = {
        "sport": sport,
        "market": "totals",
        "side": "over",
        "line": 170.5,
        "quote": {"price": -110},
        "ev_pct": 4.5,
        "model_edge_pct": 8.0,
        "score": {"score": 5.0, "price_reliability": 1.0},
        "projection": {"model_skill": dict(skill)},
    }
    row.update(over)
    return row


def test_an_unmeasured_model_sizes_on_its_full_edge():
    assert _sizing_model_edge(_row()) == pytest.approx(8.0)
    assert sizing_basis_of(_row()) == "model_edge"
    assert _sim_sizing_basis(_row()) == "full_model_edge"


def test_a_model_measured_as_LOSING_sizes_on_a_SCALED_edge_not_zero():
    scaled = _sizing_model_edge(_row(LOSES))
    assert 0.0 < scaled < 8.0
    assert _sim_sizing_basis(_row(LOSES)) == "skill_scaled"
    # never below the floor, however badly it lost
    assert _sizing_model_edge(_row(LOSES_BADLY)) == pytest.approx(8.0 * SKILL_FLOOR)


def test_a_beating_model_is_not_scaled():
    assert _sizing_model_edge(_row(BEATS)) == pytest.approx(8.0)


def test_ncaaf_sizes_on_its_model_edge_like_every_other_sport():
    """The 2026-09-18 NCAAF price-basis rule is gone."""
    row = _row(sport="ncaaf")
    assert sizing_basis_of(row) == "model_edge"
    inputs, reason = sizing_inputs_from_row(row)
    assert reason is None
    assert inputs.model_probability > inputs.market_fair_probability


@pytest.mark.parametrize("env,value", [
    ("SYNDICATE_PORTFOLIO_PRICE_BASIS_SPORTS", "ncaaf,wnba"),
    ("SYNDICATE_PORTFOLIO_SIM_SIZING", "measured_only"),
])
def test_the_old_gate_env_keys_are_inert(monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    assert _sizing_model_edge(_row(sport="ncaaf")) == pytest.approx(8.0)
    assert _sizing_model_edge(_row(LOSES)) < 8.0  # scaled, not zeroed


def test_the_gates_no_longer_exist():
    for name in ("_price_basis_sports", "_sim_sizing_mode", "_sim_sizing_gate_reason",
                 "_note_gate_reason", "_PRICE_BASIS_SPORTS_DEFAULT"):
        assert not hasattr(portfolio_commit, name), name


def test_a_row_with_no_model_edge_still_has_none():
    row = _row()
    row.pop("model_edge_pct")
    assert _sizing_model_edge(row) is None
    assert _sim_sizing_basis(row) is None


def test_the_cut_orders_by_the_published_score():
    assert _cut_rank_score(_row(LOSES)) == pytest.approx(5.0)
