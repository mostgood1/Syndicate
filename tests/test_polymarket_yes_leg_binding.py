"""The venue states which outcome its YES token pays. Read it.

`_slate_row_for_storage` has been deriving `yesLegIndex` from the venue's own
`marketSides[].long` and persisting it on EVERY row, while
`_resolve_outcome_side` refused every moneyline for want of exactly that field.
The refusal's own text said "nothing in the stored market row names it" -- true
when written, false by the time these tests were.

THE CASE THAT COST REAL MONEY, and the one scored below:

    aec-mlb-az-sf-2026-08-27
    outcomes    ['San Francisco Giants', 'Arizona ...']   <- REVERSED vs slug
    our side    home (SF), matched at outcome_index=0
    sent        OUTCOME_SIDE_YES @0.48
    result      SF won 6-1
    venue       graded LOST, pnl -5.871, held_side=POSITION_RESOLUTION_SIDE_SHORT

The YES token does not pay SF. It pays Arizona -- the AWAY team, at index 1.
The positional rule sent YES and bought the other team. With `yesLegIndex=1`
the same order builds **NO**, which is the token that pays SF.

WHAT THESE TESTS DO NOT ASSERT: that "YES == away" is a venue contract. It is a
regularity over five team-sport markets, and `outcome_side_for_index` already
records a market whose outcomes are reversed against its own slug. That is why
the away-team check is a CORROBORATOR THAT CAN ONLY REFUSE, never a resolver --
see the gate tests at the bottom.
"""
from __future__ import annotations

import pytest

import pipeline.execute_portfolio as EP
from syndicate.features.shared.polymarket_us_orders import (
    OrderBuildError,
    _readable_index,
    _resolve_outcome_side,
    order_body,
)

_YES = "OUTCOME_SIDE_YES"
_NO = "OUTCOME_SIDE_NO"


# --------------------------------------------------------------------------
# THE SCORED CASE.
# --------------------------------------------------------------------------


def test_az_sf_builds_no_where_the_positional_rule_built_yes():
    """The one market with hard venue-settled ground truth."""
    # Positional: our team sits at outcomes[0], so the old rule sent YES.
    with pytest.raises(OrderBuildError, match="team_side_needs_verified_yes_leg"):
        _resolve_outcome_side("home", 0)

    # With the venue's answer, the SAME position resolves to the other leg.
    assert _resolve_outcome_side("home", 0, yes_leg_index=1) == _NO


def test_the_agreeing_case_still_builds_yes():
    """A market whose outcomes are NOT reversed must be unaffected."""
    assert _resolve_outcome_side("away", 0, yes_leg_index=0) == _YES
    assert _resolve_outcome_side("home", 1, yes_leg_index=0) == _NO


# --------------------------------------------------------------------------
# THE REFUSAL SURVIVES WHERE THE VENUE SAYS NOTHING.
# --------------------------------------------------------------------------


def test_absent_yes_leg_still_refuses():
    with pytest.raises(OrderBuildError, match="team_side_needs_verified_yes_leg"):
        _resolve_outcome_side("home", 0, yes_leg_index=None)


def test_the_refusal_names_why_the_venue_did_not_say():
    """`yesLegReason` separates "the venue never says" from "our join broke".

    Without it a census of refusals cannot tell a venue that omits the field
    from a name-matching bug of ours, and those need different fixes.
    """
    with pytest.raises(OrderBuildError, match="two_long_sides"):
        _resolve_outcome_side("home", 0, yes_leg_reason="two_long_sides")


@pytest.mark.parametrize("bad", [None, "", "x", 2, -1, 1.5, True, False])
def test_an_unusable_index_is_not_a_yes_leg(bad):
    """`_readable_index` must never turn junk into a leg. `True` is the trap:
    `int(True) == 1`, so a bool would silently resolve as index 1."""
    assert _readable_index(bad) is None


def test_a_known_leg_with_an_unreadable_position_names_the_right_field():
    """The failure is OUR index, not the venue's -- and the message must say so
    or it sends someone to look at the wrong side of the join."""
    with pytest.raises(OrderBuildError, match="outcome_index_unreadable"):
        _resolve_outcome_side("home", None, yes_leg_index=1)


# --------------------------------------------------------------------------
# PRECEDENCE, AND THE MARKETS THAT MUST NOT CHANGE.
# --------------------------------------------------------------------------


def test_the_venue_answer_outranks_the_positional_escape_hatch(monkeypatch):
    """The hatch restores a rule measured wrong on 3 of 8 settled moneylines.
    A stated YES leg is strictly better evidence, so it wins."""
    monkeypatch.setenv("SYNDICATE_POLYMARKET_ALLOW_TEAM_SIDE", "1")
    # Positional would say YES (index 0 == yes_outcome_index()).
    assert _resolve_outcome_side("home", 0) == _YES
    # The venue says otherwise, and the venue wins.
    assert _resolve_outcome_side("home", 0, yes_leg_index=1) == _NO


@pytest.mark.parametrize(
    "side,index,expected",
    [("over", 0, _YES), ("under", 0, _NO), ("over", 1, _YES), ("under", 1, _NO)],
)
def test_totals_are_untouched(side, index, expected):
    """Over/Under name the yes/no axis themselves and never consult an index.
    A yes-leg change that moved these would be a regression in a market that
    has been settling correctly 9 of 9."""
    assert _resolve_outcome_side(side, index) == expected
    assert _resolve_outcome_side(side, index, yes_leg_index=1) == expected


def test_order_body_threads_the_leg_through():
    """The wiring, not just the function -- a resolver that computes the right
    leg and a body that drops it is the exact shape of this whole defect."""

    class _R:
        side = "home"
        requested_stake_dollars = 10.0
        position_key = "k"
        selected_date = "2026-08-30"
        venue = "polymarket"
        sport = "mlb"
        event_id = "evt-az-sf"
        market = "h2h"
        line = None
        player_name = None

    body = order_body(
        _R(), market_slug="aec-mlb-az-sf-2026-08-27", price_dollars=0.48,
        tick_size=0.01, minimum_trade_qty=1, outcome_index=0, yes_leg_index=1,
    )
    assert body["outcomeSide"] == _NO


# --------------------------------------------------------------------------
# THE CORROBORATION GATE. It may only REFUSE.
# --------------------------------------------------------------------------


def test_the_gate_defaults_on_and_rejects_unknown_values(monkeypatch):
    monkeypatch.delenv("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE", raising=False)
    assert EP._yes_leg_corroboration_required() is True
    # `bool(os.environ.get(...))` reads "false" as True. It must not.
    for off in ("0", "false", "FALSE", "no", "off"):
        monkeypatch.setenv("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE", off)
        assert EP._yes_leg_corroboration_required() is False
    for on in ("1", "true", "yes", "banana"):
        monkeypatch.setenv("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE", on)
        assert EP._yes_leg_corroboration_required() is True


# --------------------------------------------------------------------------
# END TO END THROUGH THE RESOLVER. The leaf function above can be right while
# the row's `yesLegIndex` never reaches it -- which is this defect exactly.
# --------------------------------------------------------------------------

from tests.test_execute_portfolio import (  # noqa: E402
    _artifact_env,
    _PolyReq,
    _polymarket_row,
)


class _PolyOrderReq(_PolyReq):
    """`_PolyReq` carries what the RESOLVER reads; `order_body` also needs the
    stake and ledger fields. Without them it raises `stake_not_positive` before
    it ever reaches the side, and the test passes its regex against the wrong
    error -- which is how a green assertion can prove nothing at all."""

    requested_stake_dollars = 10.0
    position_key = "k"
    selected_date = "2026-08-30"
    venue = "polymarket"
    event_id = "evt-az-sf"
    market = "h2h"
    line = None
    player_name = None


def _az_sf_row(yes_leg_index, reason=None):
    """The `aec-mlb-az-sf-2026-08-27` SHAPE, in the fixture's team vocabulary.

    outcomes are HOME-first (White Sox home, Rangers away), we want HOME, and
    the venue's YES leg is the AWAY team at index 1. That is the same geometry
    that bought Arizona when we asked for San Francisco.
    """
    row = _polymarket_row(teams=("White Sox", "Rangers"), prices=("0.55", "0.45"))
    row["yesLegIndex"] = yes_leg_index
    row["yesLegReason"] = reason
    return row


def test_the_row_s_yes_leg_reaches_the_order_body(monkeypatch):
    """THE WHOLE POINT. Resolver reads it off the row, submitter builds NO."""
    runner = _artifact_env(monkeypatch, markets=[_az_sf_row(1)])
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None, "the agreeing case must not be refused"
    assert resolved[4] == 0, "our HOME team sits at outcomes[0]"
    assert resolved[5] == (1, None), "the venue's YES leg must survive the return"

    body = order_body(
        _PolyOrderReq(), market_slug=resolved[0], price_dollars=resolved[1],
        tick_size=resolved[2], minimum_trade_qty=resolved[3],
        outcome_index=resolved[4],
        yes_leg_index=resolved[5][0], yes_leg_reason=resolved[5][1],
    )
    assert body["outcomeSide"] == _NO, (
        "this is the az-sf order: the positional rule sent YES and bought the "
        "other team"
    )


def test_a_disagreeing_yes_leg_refuses(monkeypatch):
    """Venue says outcomes[0]; our own away-team position says outcomes[1].
    Two sources disagree, so nobody trades -- which is exactly today's
    behaviour for this market, never worse."""
    runner = _artifact_env(monkeypatch, markets=[_az_sf_row(0)])
    assert runner._polymarket_resolve_market(_PolyReq()) is None


def test_the_gate_can_be_stood_down_without_a_deploy(monkeypatch):
    runner = _artifact_env(monkeypatch, markets=[_az_sf_row(0)])
    monkeypatch.setenv("SYNDICATE_POLYMARKET_YES_LEG_CORROBORATE", "0")
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None and resolved[5] == (0, None)


def test_a_row_stating_no_leg_is_unchanged(monkeypatch):
    """The refusing case must still resolve a PRICE -- the refusal belongs to
    the side, not the market. A gate that dropped these would look like the
    fix working while removing rows it never examined."""
    runner = _artifact_env(monkeypatch, markets=[_az_sf_row(None, "no_long_side")])
    resolved = runner._polymarket_resolve_market(_PolyReq())
    assert resolved is not None
    assert resolved[5] == (None, "no_long_side")
    with pytest.raises(OrderBuildError, match="no_long_side"):
        order_body(
            _PolyOrderReq(), market_slug=resolved[0], price_dollars=resolved[1],
            tick_size=resolved[2], minimum_trade_qty=resolved[3],
            outcome_index=resolved[4],
            yes_leg_index=resolved[5][0], yes_leg_reason=resolved[5][1],
        )
