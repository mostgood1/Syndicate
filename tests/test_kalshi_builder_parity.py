"""The dry run must build the same body the live path does -- for KALSHI too.

`verify_order_paths` answers "would this position become an order?", and the
whole `ORDER_PATH` line rests on that answer being the live path's answer. For
Kalshi it was not: the verifier imported v1 `order_body` directly, while
`kalshi_submitter` builds through `build_order_body` (v2 by default). v1 never
passed the board line to `_side_to_kalshi`, and a spread's leg comes from the
SIGN of that line -- so every spread was reported `spread_line_missing: None`
for a position the live path builds.

MEASURED 2026-09-22 (`#683`, found by `scripts/venue_order_family_census.py`):
kalshi `spreads` 117 position-passes over 55 passes, 0 `would_build`, while the
same row built `side='bid'` through `build_order_body`.

The pick'em refusal is NOT part of that defect and must survive: a spread with
no line, or a line of exactly zero, is still refused by both builders.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from syndicate.features.shared.kalshi_orders import (
    OrderBuildError,
    build_order_body,
    order_body,
    order_body_v2,
)

REPO = Path(__file__).resolve().parents[1]


class _Spread:
    """The NCAAF spread that sat in production's kalshi plan on 2026-09-22."""

    venue_ticker = "KXNCAAFSPREAD-26SEP26OKLAUGA-UGA15"
    market = "spreads"
    side = "home"
    line = -14.5
    requested_price = 0.52
    requested_stake_dollars = 5.0
    position_key = "pk-uga-spread"
    selected_date = "2026-09-22"
    venue = "kalshi"
    sport = "ncaaf"
    event_id = "evt-1"
    player_name = None
    segment = None
    book = None
    home_team = "Georgia Bulldogs"
    away_team = "Oklahoma Sooners"
    commence_time = "2026-09-27T00:00:00Z"


def _req(**over):
    cls = type("_R", (_Spread,), over)
    return cls()


# --------------------------------------------------------------- the fix
def test_v1_order_body_builds_a_spread():
    """The one-line defect: v1 dropped the line and refused every spread."""
    body = order_body(_req(), price_dollars=0.52)
    assert body, "v1 still refuses a spread with a real line"


@pytest.mark.parametrize("builder", [order_body, order_body_v2, build_order_body])
def test_every_builder_agrees_a_real_spread_is_buildable(builder):
    assert builder(_req(), price_dollars=0.52)


@pytest.mark.parametrize("side,line", [("home", -14.5), ("away", 2.5)])
def test_both_legs_build(side, line):
    assert build_order_body(_req(side=side, line=line), price_dollars=0.52)


# ------------------------------------------------- the deliberate refusals survive
@pytest.mark.parametrize("builder", [order_body, build_order_body])
@pytest.mark.parametrize("line", [None, 0, 0.0, "", "not-a-number"])
def test_a_spread_with_no_usable_line_is_still_refused(builder, line):
    """A spread with no number is not a pick'em, it is a row we cannot place,
    and defaulting it either way is a real bet on a leg nobody chose."""
    with pytest.raises(OrderBuildError) as caught:
        builder(_req(line=line), price_dollars=0.52)
    assert "spread_line" in str(caught.value) or "spread" in str(caught.value)


def test_a_missing_ticker_still_refuses():
    with pytest.raises(OrderBuildError):
        build_order_body(_req(venue_ticker=""), price_dollars=0.52)


# --------------------------------------------------- the divergence cannot return
def test_verify_order_paths_uses_the_LIVE_builder_not_a_private_one():
    """THE STRUCTURAL GUARD. A behavioural test cannot see this: both builders
    accept a well-formed spread now, so the day someone points the verifier at
    a builder the submitter does not use, every behavioural test still passes
    and `ORDER_PATH` quietly goes back to describing a path nobody runs.

    Read off the AST of `verify_order_paths` itself, not the whole module --
    `execute_portfolio` legitimately imports other builders elsewhere.
    """
    src = (REPO / "pipeline" / "execute_portfolio.py").read_text(encoding="utf-8")
    fn = next(
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.FunctionDef) and node.name == "verify_order_paths"
    )
    kalshi_imports = {
        alias.name
        for node in ast.walk(fn)
        if isinstance(node, ast.ImportFrom) and "kalshi_orders" in (node.module or "")
        for alias in node.names
    }
    assert "build_order_body" in kalshi_imports, (
        "verify_order_paths must build through the live entry point; it imports "
        f"{sorted(kalshi_imports)}"
    )
    assert "order_body" not in kalshi_imports, (
        "verify_order_paths imports a builder the live submitter does not call -- "
        "the dry run would report on a path nobody runs"
    )


def test_the_live_submitter_still_builds_through_build_order_body():
    """The other half of the same invariant: this test is only meaningful while
    `kalshi_submitter` itself uses `build_order_body`."""
    src = (REPO / "syndicate" / "features" / "shared" / "kalshi_orders.py").read_text(encoding="utf-8")
    fn = next(
        node
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.FunctionDef) and node.name == "kalshi_submitter"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "build_order_body" in called, sorted(called)
