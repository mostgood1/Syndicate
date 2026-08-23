"""`#530`. The market fair value must survive the live-edge refusal.

WHY THIS EXISTS. `_price_against_market` computed `market_fair_prob_over` BELOW
its `live_edge_unavailable_reason` early-return, so on a live game soccer never
got a fair value at all. `live_projection_join` then had a genuine LIVE
probability from the re-sim and nothing to price it against.

MEASURED IN PRODUCTION 2026-08-23 16:41-16:49Z, three consecutive builds:

    LIVE_PROJECTION_JOIN sport=soccer considered=1585 projected=188 edged=0
                         edge_why={'no_fair_value_devig_failed': 188}

**188 of 188.** The withheld reason read "the market is one-sided, so de-vig has
no answer" -- a real thing that happens to SOME soccer props and cannot happen to
all of them. Reading the RATE rather than the reason is what turned a
nine-hour-old "pricing decision, deliberately not taken" into a misplaced
`return`.

THE TWO CLAIMS THE OLD ORDER CONFLATED. The refusal says a PREGAME MODEL must not
be priced against a re-priced market -- true, and it must keep suppressing the
edge. The fair value is not the model: it is a de-vig of the quote in front of us,
a property of the MARKET, and it stays valid when the game goes live. Withholding
it discarded the one input that was still good.

`prop_projections.py` has always ordered these correctly, which is why MLB's live
tier worked (`live_proj=252` on the same board) while soccer's was zero. The last
test here pins that the two files agree, because one rule with two
implementations is what produced the divergence.
"""

from __future__ import annotations

import inspect

import pytest

from syndicate.features.shared import soccer_projections


def _row(**over):
    row = {
        "sport": "soccer",
        "kind": "prop",
        "market": "player_shots",
        "line": 1.5,
        "sides": ["over", "under"],
        # `_no_vig_over_probability` reads `consensus` per side, NOT a best price
        # and not a `prices` map -- de-vigging the best price would understate the
        # market's view and manufacture edge. My first fixture used `prices` and
        # the CONTROL test failed, which is the only reason the shape got checked
        # rather than assumed. -110/-110 -> implied 0.5238 each, fair = 0.5.
        "consensus": {"over": -110, "under": -110},
        "game": {"state": "pregame"},
    }
    row.update(over)
    return row


def _project(**over):
    projection = {"model_prob_over": 0.62, "basis": "poisson_shots"}
    soccer_projections._price_against_market(_row(**over), projection)
    return projection


def test_a_pregame_row_gets_a_fair_value():
    """The control. If this ever fails the fixture stopped de-vigging and every
    other assertion here is vacuous."""
    projection = _project()
    assert projection.get("market_fair_prob_over") is not None


def test_a_LIVE_row_still_gets_a_fair_value():
    """THE REGRESSION. Before `#530` this was None and 188 of 188 live soccer
    rows were withheld for the lack of it."""
    projection = _project(game={"state": "live"})
    assert projection.get("market_fair_prob_over") is not None, (
        "the live refusal swallowed the de-vig; live_projection_join has a real "
        "live probability and nothing to price it against"
    )


def test_the_fair_value_is_the_SAME_whether_the_game_is_live():
    """It is a property of the quote, not of the clock. A different number for a
    live game would mean the refusal is still leaking into the market read."""
    assert _project().get("market_fair_prob_over") == pytest.approx(
        _project(game={"state": "live"}).get("market_fair_prob_over")
    )


def test_the_LIVE_ROW_STILL_CARRIES_NO_PREGAME_EDGE():
    """THE GUARD THIS MUST NOT WEAKEN, and the reason the order matters rather
    than the refusal simply being deleted. A pregame model against a re-priced
    market is not an edge, it is the score."""
    projection = _project(game={"state": "live"})
    assert projection.get("edge_vs_market_pct") is None
    assert projection.get("edge_unavailable_reason")


def test_a_final_row_carries_no_edge_and_still_reports_the_market():
    projection = _project(game={"state": "final"})
    assert projection.get("edge_vs_market_pct") is None
    assert projection.get("market_fair_prob_over") is not None


def test_an_unknown_leg_set_is_still_refused_without_a_fair_value():
    """The one refusal that SHOULD return before the de-vig: nothing here can
    confirm a many-legged market's quoted set is complete, so de-vigging it would
    span an unknown span."""
    projection = _project(
        market="player_first_goal_scorer",
        sides=["a", "b", "c", "d"],
        consensus={"a": -110, "b": -110, "c": -110, "d": -110},
    )
    assert projection.get("market_fair_prob_over") is None
    assert "no de-vig spans an unknown leg set" in (projection.get("edge_unavailable_reason") or "")


def test_a_row_with_no_model_probability_is_untouched():
    projection = {"basis": "mean_only"}
    soccer_projections._price_against_market(_row(game={"state": "live"}), projection)
    assert "market_fair_prob_over" not in projection


def test_soccer_and_the_prop_path_order_these_the_same_way():
    """ONE RULE, TWO IMPLEMENTATIONS -- which is what produced the divergence.

    `prop_projections` stamps the fair value before consulting
    `live_edge_unavailable_reason`; soccer did the reverse, and only soccer's
    live tier was dead. Asserted structurally rather than behaviourally because
    the two functions take different inputs; what has to match is the ORDER.
    """
    from syndicate.features.shared import prop_projections

    soccer_src = inspect.getsource(soccer_projections._price_against_market)
    s_fair = soccer_src.index('projection["market_fair_prob_over"]')
    s_live = soccer_src.index("live_edge_unavailable_reason(row)")
    assert s_fair < s_live, "soccer stamps the fair value after the live refusal again"

    prop_src = inspect.getsource(prop_projections)
    p_fair = prop_src.index('projection["market_fair_prob_over"] = fair')
    p_live = prop_src.index("live_edge_unavailable_reason(row)")
    assert p_fair < p_live, "the reference implementation changed; re-check soccer"


# ---------------------------------------------------------------------------
# `#531` — the miss attribution was INERT for soccer
# ---------------------------------------------------------------------------


def test_soccer_live_prop_index_emits_the_attribution_keys():
    """`live_projection_join._has_attribution` tests for the PRESENCE of these
    two keys and, without them, routes every miss to the catch-all while leaving
    `miss_player` and `miss_line_match` structurally zero.

    Measured 2026-08-23 16:41Z: soccer reported `miss_player=0 miss_market=620
    miss_line_match=0` with all eight samples showing `player_in_lens: False,
    lens_lines_available: []`. Those look like findings and were constants --
    `miss_market=620` reads as "620 markets we cannot name" and actually meant
    "620 misses we could not attribute".
    """
    from syndicate.features.shared import soccer_live_gameline_source as src
    from syndicate.features.shared import live_projection_join as join

    report = src.soccer_live_prop_index("2026-08-23", data_root=None)
    assert "players_seen" in report, "the attribution is off; every miss becomes the catch-all"
    assert "lines_by_player_market" in report

    # THE PREDICATE ITSELF, not a proxy for it. Asserting the two keys exist is
    # only useful if it is the same test the consumer makes.
    assert (
        isinstance(report, dict)
        and "players_seen" in report
        and "lines_by_player_market" in report
    ), "does not satisfy live_projection_join._has_attribution"
    assert 'and "players_seen" in indexed' in inspect.getsource(join), (
        "the consumer's predicate changed; this test is now checking the wrong keys"
    )


def test_the_attribution_keys_are_the_right_shape():
    """A key present but wrongly shaped is worse than absent: `_has_attribution`
    would pass and the lookups would silently miss."""
    from syndicate.features.shared import soccer_live_gameline_source as src

    report = src.soccer_live_prop_index("2026-08-23", data_root=None)
    assert isinstance(report["players_seen"], set)
    assert isinstance(report["lines_by_player_market"], dict)
    for key, lines in report["lines_by_player_market"].items():
        assert isinstance(key, tuple) and len(key) == 2, key
        assert isinstance(lines, set), lines


# ---------------------------------------------------------------------------
# `#536` — WHY the de-vig came back empty, carried across the live return
# ---------------------------------------------------------------------------


def test_a_one_sided_live_row_is_named_as_one_sided():
    """`#530` fixed the ordering and `edged` stayed 0 at
    `no_fair_value_devig_failed: 45`. That name covers two states with different
    owners: a one-sided quote nothing downstream can fix, and a two-sided quote
    whose de-vig failed anyway, which is ours."""
    projection = _project(
        game={"state": "live"},
        sides=["over"],
        consensus={"over": -110},
    )
    assert projection.get("market_fair_prob_over") is None
    assert projection.get("market_fair_unavailable_reason") == "one_sided_quote"


def test_a_two_sided_row_whose_devig_fails_is_named_differently():
    """Both sides quoted and still no fair value -- an unparseable price. This is
    the half we own, and it must not hide inside the one-sided count."""
    projection = _project(
        game={"state": "live"},
        sides=["over", "under"],
        consensus={"over": "not-a-price", "under": "also-not"},
    )
    assert projection.get("market_fair_prob_over") is None
    assert projection.get("market_fair_unavailable_reason") == "consensus_present_devig_returned_none"


def test_a_successful_devig_clears_the_reason():
    """A stale reason left beside a real fair value would be read as a failure."""
    projection = _project(game={"state": "live"})
    assert projection.get("market_fair_prob_over") is not None
    assert "market_fair_unavailable_reason" not in projection


def test_the_live_join_reports_the_narrowed_reason():
    """The producer stamps it before its own early-return so it survives to the
    live join; the join must actually USE it rather than keep the flat name."""
    from syndicate.features.shared import live_projection_join as join

    src = inspect.getsource(join)
    assert 'projection.get("market_fair_unavailable_reason")' in src
    assert 'f"no_fair_value_{devig_detail}"' in src


def test_the_join_falls_back_when_the_producer_said_nothing():
    """WNBA and MLB do not stamp it. An absent detail must give the flat name,
    not an empty suffix -- `no_fair_value_` would be a new bucket nobody owns."""
    from syndicate.features.shared import live_projection_join as join

    src = inspect.getsource(join)
    assert 'withheld_key = "no_fair_value_devig_failed"' in src
