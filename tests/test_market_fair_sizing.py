"""A named sport may size on MARKET FAIR when it carries no model edge.

WHY THIS EXISTS. NCAAF's margin model is gated off by a MEASURED 17-sigma
out-of-sample loss to the closing line -- 3.563 pts MAE over 2,233 games
(`syndicate/features/ncaaf/game_projections.py:104-108`). So `model_edge_pct` is
never numeric on an NCAAF row (0 of 480 measured) and every one refuses
`no_model_edge_pct`.

**THAT GATE IS ABOUT MODEL SKILL. It says nothing about PRICE DISPERSION.**
Buying the best book's price against the no-vig consensus needs no model at all;
the edge is `fair - implied`.

THE COMMENT THAT BLOCKED THIS WAS WRONG. It claimed that without a model view
`model_probability` would equal `fair` and "Kelly would be exactly zero anyway".
Kelly differences the model against the PRICE (`bankroll_manager.py:135`), and
`fair = (ev_pct/100 + 1)/(profit + 1)` equals the price-implied probability only
at zero EV. `test_the_stake_scales_with_EV_and_is_zero_only_at_zero_EV` is that
correction, asserted rather than argued.

DEFAULT IS OFF. Enabling this globally would begin sizing ~40% of the whole
board -- every row that ranks on price alone, in every sport -- in one
unreviewed step, so a sport opts in by name.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.bankroll_manager import compute_board_stake  # noqa: E402
from syndicate.features.shared.portfolio_commit import (  # noqa: E402
    _market_fair_sports,
    sizing_basis_of,
    sizing_inputs_from_row,
)

ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"


def _row(sport="ncaaf", **kw):
    row = {"sport": sport, "quote": {"price": -110}, "ev_pct": 4.5,
           "score": {"price_reliability": 1.0}}
    row.update(kw)
    return row


# --- default OFF -------------------------------------------------------------


def test_absent_env_means_off_and_the_refusal_is_unchanged(monkeypatch):
    """Byte-identical to today. Absent must not mean permissive -- that is the
    shape of the unknown-defaults-permissive failure this repo has a rule for."""
    monkeypatch.delenv(ENV, raising=False)
    inputs, reason = sizing_inputs_from_row(_row())
    assert inputs is None and reason == "no_model_edge_pct"
    assert _market_fair_sports() == frozenset()


def test_an_empty_or_blank_value_is_also_off(monkeypatch):
    for value in ("", "   ", ","):
        monkeypatch.setenv(ENV, value)
        assert _market_fair_sports() == frozenset(), value
        assert sizing_inputs_from_row(_row())[1] == "no_model_edge_pct"


# --- reachability: off != on -------------------------------------------------


def test_enabling_the_sport_makes_the_row_sizable(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert sizing_inputs_from_row(_row())[0] is None, "off"

    monkeypatch.setenv(ENV, "ncaaf")
    inputs, reason = sizing_inputs_from_row(_row())
    assert inputs is not None and reason is None, "on"
    assert inputs.model_probability == inputs.market_fair_probability, (
        "with no model view the model probability IS the market fair -- the bet "
        "is on the price, not on a forecast")


def test_it_is_scoped_to_the_named_sport_only(monkeypatch):
    """The whole point of an allowlist. Enabling NCAAF must not size MLB."""
    monkeypatch.setenv(ENV, "ncaaf")
    assert sizing_inputs_from_row(_row("ncaaf"))[0] is not None
    for other in ("mlb", "soccer", "nba", ""):
        assert sizing_inputs_from_row(_row(other))[1] == "no_model_edge_pct", other


def test_a_real_model_edge_still_wins_where_one_exists(monkeypatch):
    """Opting a sport in must not DISCARD a model view it does have."""
    monkeypatch.setenv(ENV, "ncaaf")
    with_edge = _row(model_edge_pct=3.2)
    inputs, _ = sizing_inputs_from_row(with_edge)
    assert inputs.model_probability > inputs.market_fair_probability
    assert sizing_basis_of(with_edge) == "model_edge"


# --- the correction ----------------------------------------------------------


def test_the_stake_scales_with_EV_and_is_zero_only_at_zero_EV():
    """The claim that replaced "Kelly would be exactly zero anyway".

    Sizing on `fair` bets `fair - implied`, which is the price-shopping edge.
    It vanishes at zero EV -- correctly, there is nothing to bet -- and grows
    with EV thereafter.
    """
    def stake(ev_pct, price=-110):
        profit = 100.0 / abs(price)
        fair = (ev_pct / 100.0 + 1.0) / (profit + 1.0)
        return float(compute_board_stake(
            {"model_probability": fair, "fair_probability": fair,
             "decimal_price": profit + 1.0, "odds": price, "price_reliability": 1.0},
            settled_sample_size=616)["stake_fraction"])

    assert stake(0.0) == 0.0, "no EV, no bet -- the old comment's only true case"
    assert stake(3.0) > 0.0
    assert stake(6.0) > stake(3.0), "the stake must track the edge it is betting"


# --- attribution -------------------------------------------------------------


def test_the_basis_travels_so_the_two_strategies_stay_separable():
    """Two strategies in one settlement pool have one uninterpretable ROI. A
    model-edge bet is a claim about the world; a market-fair bet is a claim
    about the price."""
    assert sizing_basis_of(_row()) == "market_fair"
    assert sizing_basis_of(_row(model_edge_pct=3.2)) == "model_edge"
    assert sizing_basis_of(_row(model_edge_pct=0.0)) == "model_edge", (
        "a model edge of exactly zero is still a MODEL VIEW -- it is not the "
        "same fact as having none")


def test_the_allowlist_is_case_and_space_tolerant(monkeypatch):
    monkeypatch.setenv(ENV, " NCAAF , ncaab ")
    assert _market_fair_sports() == {"ncaaf", "ncaab"}
    assert sizing_inputs_from_row(_row("ncaaf"))[0] is not None


def test_the_gating_checklist_still_passes_with_the_feature_off(monkeypatch):
    """It gates every plan write, and its canonical row is MLB. If enabling a
    sport ever turned this red, the portfolio would stop writing entirely."""
    monkeypatch.delenv(ENV, raising=False)
    from scripts.portfolio_commit_input_checklist import run_checklist

    ok, lines = run_checklist()
    assert ok, "\n".join(lines)
