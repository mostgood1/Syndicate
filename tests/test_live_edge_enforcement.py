"""No row keeps an edge the live-edge policy refuses, whichever producer set it.

WHY THIS EXISTS. Every projection producer is supposed to call
`live_edge_unavailable_reason` itself, and each believes it does. Measured on
production 2026-08-16 18:38Z, soccer: **27 rows carried an edge on a game whose
own `game.state` read `final`**, plus 9 on live games from a pregame
projection. GRO @ ADO — `final`, 4-1, eight hours old — served
`edge_vs_line: -0.175` on `spreads -0.0`.

The producer's refusal existed and was unreachable. `soccer_projections`
`_price_against_market` opens `if model_prob is None: return`, and
`_mean_projection` sets `model_prob_over: None` alongside `edge_vs_line`, so
every mean-based row returned before the refusal ran. The comment on that
refusal claimed it applied "for every row, mean-based and probability-based
alike. Checked rather than assumed." It did not.

So the policy is enforced once at the wrapper, over the finished grid, where no
producer's control flow can route around it — the same argument
`attach_projections` already makes for the degeneracy check.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.board_enrichment import _enforce_live_edge_policy


def _row(state, projection):
    row = {"projection": dict(projection)}
    if state is not None:
        row["game"] = {"state": state}
    return row


def test_a_finished_game_loses_a_mean_based_edge():
    """The GRO @ ADO shape: settled market, `edge_vs_line`, no model prob.

    This is the row the whole change exists for, and note WHICH field carries
    the edge — a producer that only clears `edge_vs_market_pct` leaves this
    bettable while looking suppressed.
    """
    row = _row("final", {"edge_vs_line": -0.175, "model_prob_over": None})
    out = _enforce_live_edge_policy([row])

    assert row["projection"]["edge_vs_line"] is None
    assert row["projection"]["edge_vs_market_pct"] is None
    assert "settled" in row["projection"]["edge_unavailable_reason"]
    assert out["live_edge_enforced_rows"] == 1


def test_a_live_game_loses_a_pregame_projections_edge():
    row = _row("live", {"edge_vs_market_pct": 5.0})
    _enforce_live_edge_policy([row])
    assert row["projection"]["edge_vs_market_pct"] is None
    assert "cannot be priced against a live market" in row["projection"]["edge_unavailable_reason"]


def test_a_live_AWARE_projection_keeps_its_edge():
    """MLB's live re-sim is the signal worth ranking, not the failure.

    The most important negative case here. If this sweep suppressed live-aware
    edges it would delete the only genuinely live number on the board, and it
    would do so quietly — the board would just look calm.
    """
    row = _row("live", {"edge_vs_market_pct": 5.0, "live_aware": True})
    out = _enforce_live_edge_policy([row])
    assert row["projection"]["edge_vs_market_pct"] == 5.0
    assert "edge_unavailable_reason" not in row["projection"]
    assert out["live_edge_enforced_rows"] == 0


@pytest.mark.parametrize("state", ["pregame", "unknown", None])
def test_pregame_and_unknown_keep_their_edge(state):
    """Unknown must stay permissive, and that is deliberate, not an oversight.

    A row whose state failed to resolve is overwhelmingly a pregame row on a
    board with a join gap. Suppressing those would blank the edge column on
    exactly the days the join degrades — turning an enrichment gap into a
    silent loss of the board's purpose.
    """
    row = _row(state, {"edge_vs_line": 0.5})
    out = _enforce_live_edge_policy([row])
    assert row["projection"]["edge_vs_line"] == 0.5
    assert out["live_edge_enforced_rows"] == 0


def test_a_producers_own_reason_is_not_overwritten():
    """A more specific message must survive; this sweep is a backstop."""
    row = _row("final", {"edge_vs_line": 1.0, "edge_unavailable_reason": "something specific"})
    _enforce_live_edge_policy([row])
    assert row["projection"]["edge_vs_line"] is None
    assert row["projection"]["edge_unavailable_reason"] == "something specific"


def test_the_counter_is_reported_even_when_zero():
    """A counter that only appears on failure cannot confirm the sweep ran.

    This repo has relearned that several times; the field is unconditional.
    """
    out = _enforce_live_edge_policy([_row("pregame", {"edge_vs_line": 0.5})])
    assert out["live_edge_enforced_rows"] == 0
    assert out["live_edge_enforced_reasons"] == {}


def test_rows_without_an_edge_are_untouched_and_uncounted():
    row = _row("final", {"projected": 1.5})
    out = _enforce_live_edge_policy([row])
    assert "edge_unavailable_reason" not in row["projection"]
    assert out["live_edge_enforced_rows"] == 0


def test_non_dict_rows_do_not_break_the_sweep():
    """`Mapping` is not imported in this module and the rows are plain dicts.

    An isinstance check against an unimported name would raise NameError on the
    FIRST row and take the whole projection join down with it — which is how
    this nearly shipped.
    """
    out = _enforce_live_edge_policy(["not a row", None, _row("final", {"edge_vs_line": 2.0})])
    assert out["live_edge_enforced_rows"] == 1
