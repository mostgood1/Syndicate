"""`sim_coverage` counts sim edges ON THE ROWS, never from a refusal counter.

WHY. It used to read `rows_without_sim_edge = refusals["no_model_edge_pct"]`,
which was only true while EVERY row without a sim edge was refused for exactly
that reason. By user decision 2026-09-16 (lane `portfolio-no-family-exclusion`)
EV-only rows may be staked in every sport, so a row with no sim edge can now be
SIZED, or refused for some other reason (EV floor, in-play). The old derivation
would then report such a book as 100% sim-covered. A coverage number that goes
healthy exactly when the thing it measures gets worse is the instrument
blindness `learnings.md` keeps recording.
"""

from __future__ import annotations

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings


def _row(**over):
    row = {
        "sport": "mlb",
        "market": "h2h",
        "side": "home",
        "line": None,
        "quote": {"price": -110},
        "ev_pct": 5.0,
        "model_edge_pct": 4.0,
        "score": {"score": 61.25, "price_reliability": 0.9},
    }
    row.update(over)
    return row


def _commit(rows):
    return commit_portfolio(
        rows, selected_date="2026-09-16",
        settings=PortfolioSettings(bankroll_units=1000.0),
    )


def test_an_EV_only_row_that_is_SIZED_still_counts_as_without_a_sim_edge(monkeypatch):
    """Red against the refusal-derived count: this row is sized, so nothing is
    refused `no_model_edge_pct`, and the old number read 0 rows without."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "mlb")
    plan = _commit([_row(model_edge_pct=None)])
    assert len(plan.get("positions") or []) == 1, "precondition: the EV-only row is sized"
    assert plan["sim_coverage"]["rows_without_sim_edge"] == 1
    assert plan["sim_coverage"]["rows_with_sim_edge"] == 0


def test_a_row_refused_for_ANOTHER_reason_is_not_counted_as_sim_covered(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "mlb")
    plan = _commit([_row(model_edge_pct=None, ev_pct=-2.0)])
    assert plan["refusals"].get("no_model_edge_pct") is None, "precondition: refused for something else"
    assert plan["sim_coverage"]["rows_without_sim_edge"] == 1
    assert plan["sim_coverage"]["rows_with_sim_edge"] == 0


def test_a_row_with_a_sim_edge_counts_as_covered_whatever_happens_to_it():
    plan = _commit([_row(), _row(ev_pct=-2.0)])
    assert plan["sim_coverage"]["rows_with_sim_edge"] == 2
    assert plan["sim_coverage"]["rows_without_sim_edge"] == 0


def test_the_split_sums_to_rows_in_and_the_share_matches(monkeypatch):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "mlb")
    plan = _commit([_row(), _row(model_edge_pct=None), "not a mapping"])
    cov = plan["sim_coverage"]
    assert cov["rows_in"] == plan["rows_in"] == 3
    assert cov["rows_with_sim_edge"] + cov["rows_without_sim_edge"] == 3
    assert cov["rows_with_sim_edge"] == 1
    assert cov["share_with_sim_edge"] == round(1 / 3, 4)
