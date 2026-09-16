"""The portfolio commit refuses NO row for its sport or market family.

USER DECISION 2026-09-16 (`learnings.md`, lane `portfolio-no-family-exclusion`),
verbatim: "we shouldnt block anything globally - that includes MLB player props.
every prop and game line is its own entity in the scheme of things - we optimize
overall but there's ALWAYS a chance an individual play is viable based on EV, sim
edge, etc".

WHAT THIS REPLACES. `#615` added `resolve_excluded_families`, a `sport:family`
exclusion defaulting to `mlb:player_prop`, applied before pricing. On the
2026-09-16 10:07 CT production plan it refused 1,795 MLB prop rows by name,
before their EV or sim edge was read. The measurement it stood on (MLB props
-19.27% ROI on $561.23 over 145 settled rows, 08-22..08-31, with no model view
on the rows) is kept in `lanes.md` under that lane rather than in code.

WHAT STILL REFUSES A ROW is its OWN numbers: no sim edge, EV below the floor, a
zero Kelly stake, the position caps. The tests below pin both halves, because a
removal that also opened EV-free staking would pass the first half alone.
"""

from __future__ import annotations

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings


def _row(**over):
    row = {
        "sport": "mlb",
        "market": "batter_hits",
        "side": "under",
        "line": 1.5,
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


# ---------------------------------------------------------------------------
# Reachability first: the row the old default refused BY NAME is now evaluated
# ---------------------------------------------------------------------------


def test_an_mlb_player_prop_with_a_sim_edge_is_SIZED(monkeypatch):
    """Red against `#615` (refused `market_family_excluded` before pricing),
    green after. Asserting a position, not merely the absent refusal key, so a
    commit path that dropped the row for some other reason cannot pass."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row()])
    assert plan["refusals"].get("market_family_excluded") is None
    assert len(plan.get("positions") or []) == 1


def test_the_retired_env_var_refuses_nothing(monkeypatch):
    """A stale `SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES` left on a service, or
    copied from an old doc, must not quietly bring a category block back."""
    monkeypatch.setenv(
        "SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES",
        "mlb:player_prop,soccer:game_line,soccer:game_total",
    )
    plan = _commit([
        _row(),
        _row(sport="soccer", market="h2h", side="home", line=None),
        _row(sport="soccer", market="totals", side="over", line=2.5),
    ])
    assert plan["refusals"].get("market_family_excluded") is None
    assert len(plan.get("positions") or []) == 3


# ---------------------------------------------------------------------------
# Per-play gates are untouched: removal must not open EV-free staking
# ---------------------------------------------------------------------------


def test_a_prop_with_no_sim_edge_is_still_refused_on_its_OWN_numbers(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", raising=False)
    plan = _commit([_row(model_edge_pct=None)])
    assert plan["refusals"] == {"no_model_edge_pct": 1}
    assert not plan.get("positions")


def test_a_prop_below_the_ev_floor_is_still_refused_on_its_OWN_numbers():
    plan = _commit([_row(ev_pct=-1.0)])
    assert plan["refusals"].get("below_min_ev_pct") == 1
    assert not plan.get("positions")


# ---------------------------------------------------------------------------
# Every row is still accounted for
# ---------------------------------------------------------------------------


def test_the_reasons_and_positions_still_sum_to_rows_in():
    rows = [
        _row(),
        _row(model_edge_pct=None),
        _row(market="h2h", side="home", line=None),
        _row(sport="nfl", market="player_pass_tds"),
        "not a mapping",
    ]
    plan = _commit(rows)
    assert plan["refusals"].get("market_family_excluded") is None
    assert sum(plan["refusals"].values()) + len(plan.get("positions") or []) == plan["rows_in"] == 5
