"""`#615` -- a sport-scoped market-family exclusion on the staking path.

WHY THE RULE IS SCOPED THE WAY IT IS, because the scope is the whole point and
an earlier draft of it was aimed at the wrong book.

MEASURED on the portfolio's own settlement, 2026-08-22..08-31 over 16 dates:
MLB `player_prop` returned **-19.27% ROI on $561.23 across 145 settled rows**
while `game_line` returned +15.55% and `game_total` +6.65% on the same slates.
On decided rows, props hit 42.0% (n=257) against game markets at 47.9%
(n=359).

The rule is a FAMILY rule and not a SIDE rule, and that distinction is
measured rather than assumed. A -5.70pp over-side defect does exist, but in the
vendor season betting card -- a book grep confirms is not a staking input. In
the book that actually risks money the sides are indistinguishable: over 41.4%
(n=99) against under 42.4% (n=158). The board carries no model view on prop
rows at all (`model_edge_pct` numeric on 0 of 103 served MLB prop rows), so
side selection there is price, not projection, and a side rule would have been
inert.

It is per-sport because the finding is per-sport. NFL and NBA prop books have
not been measured this way and must not inherit an MLB verdict silently.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_commit import market_family_of
from syndicate.features.shared.portfolio_commit import resolve_excluded_families
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
    }
    row.update(over)
    return row


def _commit(rows):
    return commit_portfolio(
        rows, selected_date="2026-08-31",
        settings=PortfolioSettings(bankroll_units=1000.0),
    )


# ---------------------------------------------------------------------------
# Reachability first: off must not look like on
# ---------------------------------------------------------------------------


def test_OFF_IS_NOT_ON_an_empty_knob_lets_the_prop_through(monkeypatch):
    """The empty string DISABLES the rule -- distinct from unset, which takes
    the default. Without this the other tests here could pass against a commit
    path that refuses every prop for some unrelated reason."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "")
    plan = _commit([_row()])
    assert resolve_excluded_families() == frozenset()
    assert plan["refusals"].get("market_family_excluded") is None


def test_the_default_refuses_an_mlb_player_prop_by_name(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row()])
    assert plan["refusals"]["market_family_excluded"] == 1


# ---------------------------------------------------------------------------
# The scope of the rule
# ---------------------------------------------------------------------------


def test_mlb_game_lines_and_totals_are_untouched(monkeypatch):
    """The measurement that justifies the rule is +15.55% on game_line and
    +6.65% on game_total. Cutting those would invert the finding."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row(market="h2h", side="home", line=None),
                    _row(market="totals", side="over", line=8.5)])
    assert plan["refusals"].get("market_family_excluded") is None


def test_another_sports_props_are_NOT_swept_up(monkeypatch):
    """The finding is MLB-only. An NFL prop book that has never been measured
    this way must not inherit an MLB verdict silently -- that is the whole
    reason the token carries a sport."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row(sport="nfl", market="player_pass_tds")])
    assert plan["refusals"].get("market_family_excluded") is None


def test_the_knob_can_name_another_sport(monkeypatch):
    """Setting the knob REPLACES the default rather than adding to it, so the
    MLB prop in this pair now survives the exclusion while the NFL one does
    not. Both halves are asserted: a rule that excluded everything would pass
    the first assertion alone."""
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", "nfl:player_prop")
    plan = _commit([_row(sport="nfl", market="player_pass_tds"), _row()])
    assert plan["refusals"]["market_family_excluded"] == 1
    assert plan["refusals_by_market"]["market_family_excluded"] == {"player_pass_tds": 1}


# ---------------------------------------------------------------------------
# It must stay VISIBLE, not become an unexplained drop in rows_in
# ---------------------------------------------------------------------------


def test_the_refusal_is_attributed_to_its_market_not_left_unkeyed(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row(market="batter_hits"), _row(market="batter_rbis")])
    by = plan["refusals_by_market"]["market_family_excluded"]
    assert by == {"batter_hits": 1, "batter_rbis": 1}


def test_the_reasons_still_sum_to_rows_in(monkeypatch):
    """A plan with zero positions is routine AND alarming, and only the reasons
    tell them apart. An exclusion that removed rows without counting them would
    break exactly that."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    rows = [_row(), _row(market="h2h", side="home", line=None), "not a mapping"]
    plan = _commit(rows)
    assert sum(plan["refusals"].values()) + len(plan.get("positions") or []) == plan["rows_in"]


# ---------------------------------------------------------------------------
# The family classifier is the SHARED one
# ---------------------------------------------------------------------------


def test_the_family_classifier_is_the_settlement_one_not_a_second_copy():
    """A family used to REFUSE a bet and a family used to REPORT on it must be
    the same function. `paper_settlement` already warns what a second
    definition costs -- three ideas of "never a position" that drifted apart."""
    from syndicate.features.shared import paper_settlement

    for market, expected in (("batter_hits", "player_prop"), ("h2h", "game_line"),
                             ("totals", "game_total")):
        row = {"sport": "mlb", "market": market}
        assert market_family_of(row) == paper_settlement._market_family(row) == expected


def test_the_exclusion_fires_before_pricing_so_it_cannot_be_reseated(monkeypatch):
    """Ordering, and it matters twice: an excluded row must not reach sizing,
    and the surviving refusal counters must describe only rows that were in
    scope. A prop with NO model edge would otherwise land under
    `no_model_edge_pct` and make the exclusion look inert."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES", raising=False)
    plan = _commit([_row(model_edge_pct=None)])
    assert plan["refusals"]["market_family_excluded"] == 1
    assert plan["refusals"].get("no_model_edge_pct") is None
