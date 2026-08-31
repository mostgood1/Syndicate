"""Soccer h2h is THREE markets, its outcomes are `Yes`/`No`, and `No` is not
the other team.

Polymarket splits a 3-way into one binary per outcome with the subject in the
slug. Measured 2026-08-21 on one fixture:

    atc-irlp-sha-she-2026-08-21-sha    outcomes=["Yes","No"]
    atc-irlp-sha-she-2026-08-21-draw   outcomes=["Yes","No"]
    atc-irlp-sha-she-2026-08-21-she    outcomes=["No","Yes"]   <- REVERSED

Two facts follow, and the tests below are one per fact.

1. `_side_for_team` cannot match "home"/"away" against `["Yes","No"]`, so EVERY
   soccer moneyline refused as `team_side_not_in_outcomes` and never reached the
   yes-leg gate. Measured 2026-08-31: 9 markets resolved, 0 gate lines.

2. **`No` ON A 3-WAY IS NOT THE OTHER TEAM.** `No` on "will SHA win?" pays on
   SHE *or a draw*. Only the market whose subject IS our side is takeable, as
   `Yes`. The complement is refused, and that refusal is the most important
   assertion in this file.

The `Yes` index is found BY NAME, never by position -- the same fixture ships
both array orders.
"""
from __future__ import annotations

import pytest

from tests.test_execute_portfolio import _artifact_env, _PolyReq


def _row(slug, outcomes, prices):
    return {"slug": slug, "outcomes": list(outcomes), "outcomePrices": list(prices),
            "orderPriceMinTickSize": "0.01", "minimumTradeQty": "1", "orderable": True}


class _SoccerReq(_PolyReq):
    venue_ticker = "atc-irlp-sha-she-2026-08-21-sha"
    sport = "soccer"
    home_team = "she"
    away_team = "sha"
    side = "away"          # we want SHA, and SHA is the slug's subject
    requested_price = 0.50


def test_the_subject_market_resolves_as_yes(monkeypatch):
    """The whole fix: our side IS the subject, so we buy Yes."""
    runner = _artifact_env(monkeypatch, markets=[
        _row("atc-irlp-sha-she-2026-08-21-sha", ["Yes", "No"], ["0.50", "0.50"])])
    resolved = runner._polymarket_resolve_market(_SoccerReq())
    assert resolved is not None, "a soccer h2h still refuses -- the fix is inert"
    assert resolved[4] == 0, "Yes sits at index 0 here"
    assert resolved[5][0] == 0, "the YES leg must reach the order body"


def test_the_yes_index_is_found_by_name_not_position(monkeypatch):
    """The same fixture ships `["No","Yes"]` on the other leg. A positional
    read would buy the wrong contract at a confident-looking price."""
    class _Rev(_SoccerReq):
        venue_ticker = "atc-irlp-sha-she-2026-08-21-she"
        side = "home"      # we want SHE, and SHE is this slug's subject
    runner = _artifact_env(monkeypatch, markets=[
        _row("atc-irlp-sha-she-2026-08-21-she", ["No", "Yes"], ["0.60", "0.40"])])
    resolved = runner._polymarket_resolve_market(_Rev())
    assert resolved is not None
    assert resolved[4] == 1, "Yes is at index 1 on this leg"
    # THE PRICE COMES FROM THE `Yes` OUTCOME, not from `No`. Asserted as a
    # comparison rather than a literal: the resolver CROSSES one tick to take
    # liquidity (`POLYMARKET_CROSS quote=0.4 -> crossed=0.41`), so pinning 0.40
    # would fail on a correct price for a reason that has nothing to do with
    # leg selection. What must never happen is the `No` price (0.60) arriving
    # here -- that is buying the other contract at a confident-looking number.
    assert abs(resolved[1] - 0.40) < abs(resolved[1] - 0.60), (
        f"price {resolved[1]} came from the No outcome, not Yes"
    )


def test_the_opposite_team_is_REFUSED_not_bought_as_no(monkeypatch):
    """THE SAFETY PROPERTY. We want SHE; this market asks about SHA. `No` here
    pays on SHE *or a draw*, so it is NOT a bet on SHE and must not be taken."""
    class _Other(_SoccerReq):
        side = "home"      # we want SHE, but the slug's subject is SHA
    runner = _artifact_env(monkeypatch, markets=[
        _row("atc-irlp-sha-she-2026-08-21-sha", ["Yes", "No"], ["0.50", "0.50"])])
    assert runner._polymarket_resolve_market(_Other()) is None


def test_a_draw_market_is_refused_for_a_team_side(monkeypatch):
    """`-draw` can only ever be the draw leg."""
    class _Draw(_SoccerReq):
        venue_ticker = "atc-irlp-sha-she-2026-08-21-draw"
    runner = _artifact_env(monkeypatch, markets=[
        _row("atc-irlp-sha-she-2026-08-21-draw", ["Yes", "No"], ["0.28", "0.72"])])
    assert runner._polymarket_resolve_market(_Draw()) is None


def test_a_team_named_market_is_untouched(monkeypatch):
    """MLB names both teams in `outcomes`. That path must not change -- it is
    the one the yes-leg gate exists for."""
    from tests.test_execute_portfolio import _polymarket_row
    runner = _artifact_env(monkeypatch, markets=[
        _polymarket_row(teams=("White Sox", "Rangers"), prices=("0.55", "0.45"))])
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None and resolved[4] == 0


def test_the_decoder_is_importable_from_where_the_order_path_imports_it():
    """THE ANTI-VACUOUS GUARD, and it exists because this file lied once.

    The first version imported `parse_slug` from the wrong module. The order
    path caught the ImportError and disabled the branch, so EVERY market
    refused -- and the three refusal tests above passed, because "refuses" was
    exactly what they asserted. A feature can be entirely inert while its own
    tests are green, if every test asserts a NO.

    So: pin the import at the same path the order path uses. If it moves again,
    THIS fails, loudly, instead of the refusals quietly passing for the wrong
    reason. `test_the_subject_market_resolves_as_yes` is the other half -- a
    test that asserts a YES cannot pass while the decoder is missing.
    """
    from syndicate.features.shared.polymarket_board_join import (  # noqa: F401
        _is_yes_no_market,
        _subject_is_side,
        parse_slug,
    )
