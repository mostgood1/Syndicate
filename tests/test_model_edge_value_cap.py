"""Longshots owned the top of the board, and the mechanism was arithmetic.

USER-REPORTED 2026-09-04: "the layer 2 board scoring right now is showing a lot
of long shots at the top." Measured on the served shortlist the same hour
(n=1,200), the RANKING value by basis:

    market_fair    n=840   median -0.92   p90 2.25   max  5.14
    model_edge     n=360   median +0.14   p90 7.30   max 14.99

So EVERY row above 5.14 was necessarily a model disagreement -- a real price
dislocation physically could not reach there. `batter_home_runs` was 340 of
1,200 rows, EVERY ONE an `over`, and 25 of the top 50.

WHY: a one-sided prop has no two-sided consensus, so `fair_method` falls to
`book_margin_model` and `ev_pct` collapses to `-hold` (~-6.7) -- a number
carrying nothing about the bet. The row then ranks on the MODELLED edge instead,
at FULL value, while `_MODEL_EDGE_MAX_POINTS = 15.0` only REJECTS above 15 and
clamps nothing below it.

The board's own docstring already argued this: "`blended_score` CAPS the model's
influence when it arrives as `model_edge` -- and the same information was then
routed through `value_ev`, which has NO cap."

SATURATING, NOT CLAMPING. `_model_edge_for` rejects a hard clamp for a stated
and correct reason: it "would keep an unusable number in the ranking at the
ceiling value and make every affected row tie at the top". `tanh` bounds the
magnitude while staying strictly monotone, so ordering among model rows is
preserved exactly.
"""

from __future__ import annotations

import math
import pathlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.layer2_board as lb  # noqa: E402
from syndicate.features.shared.layer2_board import (  # noqa: E402
    _MODEL_EDGE_VALUE_CAP_PCT,
    _compress_model_value,
)

#: The measured market-EV ceiling on the served board, 2026-09-04.
MARKET_EV_MAX = 5.14


# --- the fix ----------------------------------------------------------------


def test_the_observed_top_edge_no_longer_outranks_the_whole_market_board():
    """13.03 was row 1 (Yandy Diaz HR over 0.5 at +650). It must not sit above
    every price-dislocation row on the board."""
    assert _compress_model_value(13.03) <= MARKET_EV_MAX
    assert _compress_model_value(14.99) <= MARKET_EV_MAX


def test_it_is_bounded_for_any_input_however_absurd():
    """`<=`, not `<`: `tanh` saturates to exactly 1.0 in float arithmetic well
    before the inputs stop being absurd (tanh(100) is 1.0), so the cap is
    REACHED rather than merely approached. The property that matters is that it
    is never EXCEEDED."""
    for edge in (5, 15, 50, 500, 1e6):
        assert abs(_compress_model_value(edge)) <= _MODEL_EDGE_VALUE_CAP_PCT
        assert abs(_compress_model_value(-edge)) <= _MODEL_EDGE_VALUE_CAP_PCT
    # And the ties that saturation DOES create sit far outside the real range --
    # the board's observed maximum was 14.99, which is still strictly ordered.
    assert _compress_model_value(14.99) < _MODEL_EDGE_VALUE_CAP_PCT


# --- the objection the existing code raises, answered ------------------------


def test_it_does_NOT_tie_rows_at_the_ceiling():
    """`_model_edge_for`'s comment rejects clamping precisely because it would
    "make every affected row tie at the top". Strict monotonicity is what makes
    this different from the thing that file refused to do."""
    values = [_compress_model_value(e) for e in (8.0, 10.0, 12.0, 13.03, 14.99)]
    assert values == sorted(values)
    assert len(set(values)) == len(values), values


def test_ordering_among_model_rows_is_preserved_exactly():
    edges = [0.4, 1.1, 3.7, 6.2, 9.9, 13.0]
    got = [_compress_model_value(e) for e in edges]
    assert [e for _, e in sorted(zip(got, edges))] == edges


# --- small edges are untouched, which is the point ---------------------------


@pytest.mark.parametrize("edge", [0.05, 0.2, 0.5, 1.0])
def test_a_SMALL_genuine_edge_is_essentially_unchanged(edge):
    """This path exists to surface one-sided rows that would otherwise rank on
    `-hold`. Bending those would throw away the thing it was built for."""
    got = _compress_model_value(edge)
    assert abs(got - edge) < 0.05 * max(edge, 0.1), (edge, got)


def test_it_is_signed_and_symmetric():
    assert _compress_model_value(-7.0) == pytest.approx(-_compress_model_value(7.0))
    assert _compress_model_value(0.0) == pytest.approx(0.0)


# --- off != on ---------------------------------------------------------------


def test_setting_the_cap_to_zero_restores_the_old_behaviour():
    """Explicitly disabled must mean UNCOMPRESSED, not the model floored out of
    the ranking -- an off switch that silently mutes a signal is worse than none."""
    import syndicate.features.shared.layer2_board as board

    original = board._MODEL_EDGE_VALUE_CAP_PCT
    try:
        board._MODEL_EDGE_VALUE_CAP_PCT = 0.0
        assert board._compress_model_value(13.03) == 13.03
    finally:
        board._MODEL_EDGE_VALUE_CAP_PCT = original
    assert _compress_model_value(13.03) < 13.03


def test_none_passes_through():
    """The caller may have no model view at all; that is not a zero."""
    assert _compress_model_value(None) is None


# --- the amplification this also fixes ---------------------------------------


def test_it_also_bounds_the_MODEL_EV_branch_where_1_over_p_amplifies():
    """`model_ev` is `expected_value_pct(price, model_prob)`, which near fair is
    `edge / p` -- so it multiplies by 1/p. Measured on this board: edge 4.11
    became ev 50.92 on a p=0.067 shot. That is how a smaller edge on a longer
    shot outranks a bigger edge on a shorter one."""
    assert _compress_model_value(50.92) <= MARKET_EV_MAX
    assert _compress_model_value(85.13) <= MARKET_EV_MAX
    # and it still orders them correctly
    assert _compress_model_value(85.13) > _compress_model_value(50.92)


def test_the_curve_is_the_documented_one():
    cap = _MODEL_EDGE_VALUE_CAP_PCT
    assert _compress_model_value(7.5) == pytest.approx(cap * math.tanh(7.5 / cap))


# ---------------------------------------------------------------------------
# REACHABILITY -- the tests above pass with the CALL SITES DELETED
# ---------------------------------------------------------------------------
# Found by mutation check: removing `_compress_model_value(...)` from both
# branches in `build_layer2_rows` left every test above GREEN, because they
# exercise the function and not the wiring. That is the same gap this session
# has been chasing everywhere else, produced here in the fix for it. These
# drive the real builder.


def _value_ev_assignments():
    """Every `value_ev = ...` inside `build_layer2_rows`, as (source, is_wrapped).

    AST, NOT REGEX, and that choice is load-bearing -- a sibling lane measured a
    non-greedy regex reading 6 keys where the dict had 10 because a literal
    brace inside a COMMENT truncated the match, producing a false PASS shaped
    exactly like the bug it guarded. Parsing cannot be fooled that way.
    """
    import ast

    tree = ast.parse(pathlib.Path(lb.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "build_layer2_rows")
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "value_ev" for t in node.targets):
            continue
        wrapped = (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_compress_model_value"
        )
        out.append((ast.unparse(node), wrapped))
    return out


def test_BOTH_model_branches_are_actually_WRAPPED_at_the_call_site():
    """REACHABILITY. Every behavioural test above passes with the call sites
    deleted -- confirmed by mutation check -- because they exercise the helper
    and not the wiring. This is the test that goes red for that.

    A live-builder fixture was attempted first and could not reach the branch:
    a genuinely one-sided row never derives a `fair`, so it is dropped unscored
    before `_model_value_ev` is consulted. A SKIPPED reachability test reads as
    coverage and is worse than none, so this pins the wiring structurally
    instead, and says plainly that is what it is doing.
    """
    assignments = _value_ev_assignments()
    assert assignments, "no `value_ev` assignment found -- the branch moved"
    model_branches = [(src, w) for src, w in assignments if "model_" in src]
    assert len(model_branches) == 2, model_branches
    unwrapped = [src for src, wrapped in model_branches if not wrapped]
    assert not unwrapped, (
        "a model-derived ranking value reaches the score UNCOMPRESSED: %s" % unwrapped
    )


def test_the_MARKET_branch_is_deliberately_NOT_wrapped():
    """`off != on` in the other direction. A real market EV is a measured
    quantity on its own scale and must pass through untouched -- compressing it
    too would defeat the whole point, which is to stop the model outranking it."""
    assignments = _value_ev_assignments()
    market = [(src, w) for src, w in assignments if "model_" not in src]
    assert market, assignments
    assert all(not wrapped for _, wrapped in market), market
