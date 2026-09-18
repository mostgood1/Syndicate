"""NCAAF's sim edge is SHOWN and RANKED, but its stake stays on PRICE.

`[2026-09-18, user decisions, lane ncaaf-board-sim-coverage]`: "Publish,
skill-discounted" made NCAAF rows carry `model_edge_pct` for the first time
(0 of 938 served NCAAF rows had one that morning), and "Show edges, size on
price" asked that the money keep following the market-fair basis. Without the
rule under test, publishing the edge would have switched every NCAAF paper and
live stake to `fair + model_edge_pct/100` Kelly in the same deploy.

The invariant is BYTE-IDENTICAL SIZING: an NCAAF row with a sim edge sizes
exactly as the same row without one did the day before.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.portfolio_commit import (  # noqa: E402
    _price_basis_sports,
    sizing_basis_of,
    sizing_inputs_from_row,
)

PRICE_ENV = "SYNDICATE_PORTFOLIO_PRICE_BASIS_SPORTS"
FAIR_ENV = "SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS"


def _row(sport="ncaaf", **kw):
    row = {"sport": sport, "quote": {"price": -110}, "ev_pct": 4.5,
           "score": {"price_reliability": 1.0}}
    row.update(kw)
    return row


def test_default_holds_ncaaf_and_only_ncaaf(monkeypatch):
    monkeypatch.delenv(PRICE_ENV, raising=False)
    assert _price_basis_sports() == frozenset({"ncaaf"})
    # Blank is not "off": a blank value on a service is far more often an
    # accident than a decision, and off here would move real stakes.
    monkeypatch.setenv(PRICE_ENV, "   ")
    assert _price_basis_sports() == frozenset({"ncaaf"})
    monkeypatch.setenv(PRICE_ENV, "none")
    assert _price_basis_sports() == frozenset()


def test_an_ncaaf_sim_edge_does_not_move_the_stake(monkeypatch):
    """THE INVARIANT. Same row, with and without a sim edge, same stake."""
    monkeypatch.delenv(PRICE_ENV, raising=False)
    monkeypatch.setenv(FAIR_ENV, "ncaaf")
    without, reason_without = sizing_inputs_from_row(_row())
    with_edge, reason_with = sizing_inputs_from_row(_row(model_edge_pct=6.0))
    assert reason_without is None and reason_with is None
    assert with_edge.model_probability == without.model_probability
    assert with_edge.model_probability == with_edge.market_fair_probability
    assert sizing_basis_of(_row(model_edge_pct=6.0)) == "market_fair"


def test_ncaaf_is_still_refused_where_it_was_refused(monkeypatch):
    """Not in the market-fair allowlist -> refused before, refused now. A sim
    edge must not become the thing that lets an NCAAF row be staked."""
    monkeypatch.delenv(PRICE_ENV, raising=False)
    monkeypatch.delenv(FAIR_ENV, raising=False)
    inputs, reason = sizing_inputs_from_row(_row(model_edge_pct=6.0))
    assert inputs is None and reason == "no_model_edge_pct"


def test_reachability_off_is_not_on(monkeypatch):
    """Clearing the rule restores model-edge sizing, so the rule is what holds
    the stake -- not some other path that happens to agree."""
    monkeypatch.setenv(FAIR_ENV, "ncaaf")
    monkeypatch.setenv(PRICE_ENV, "none")
    assert sizing_basis_of(_row(model_edge_pct=6.0)) == "model_edge"
    cleared, _ = sizing_inputs_from_row(_row(model_edge_pct=6.0))
    monkeypatch.delenv(PRICE_ENV, raising=False)
    held, _ = sizing_inputs_from_row(_row(model_edge_pct=6.0))
    assert cleared is not None and held is not None
    assert cleared.model_probability != held.model_probability


def test_other_sports_are_untouched(monkeypatch):
    monkeypatch.delenv(PRICE_ENV, raising=False)
    assert sizing_basis_of(_row(sport="mlb", model_edge_pct=3.0)) == "model_edge"
    assert sizing_basis_of(_row(sport="nfl", model_edge_pct=3.0)) == "model_edge"
