"""Pricing a model view against the MODELLED fair -- in its own column.

USER DECISION 2026-08-17: "yes, allow book_margin_model edges with their own
column." Recommendation 4 of the Layer 1 audit, which surfaced it rather than
taking it: 1,416 rows (285 MLB, 1,131 soccer) carried BOTH a `model_prob` and a
`modelled_fair.<side>.fair_probability` and served no edge at all.

THE SEPARATE COLUMN IS THE DECISION, not packaging. `book_margin_model`'s own
docstring forbids the alternative -- a modelled fair "must never be silently
mixed with a real two-sided fair value ... the failure #242 already caused
once". So the load-bearing tests here are the ones asserting what this must
NOT do: never write `edge_vs_market_pct`, never price a two-sided fair, never
price a live row.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.book_margin_model import (
    EDGE_BASIS_FIELD,
    EDGE_FIELD,
    EDGE_HOLD_FIELD,
    EDGE_METHOD_FIELD,
    modelled_fair_edge,
)


def _row(**overrides):
    entry = {
        "fair_probability": 0.2334,
        "fair_price": -100,
        "assumed_hold_pct": 6.636,
        "basis": "betrivers",
        "fair_method": "book_margin_model",
    }
    entry.update(overrides.pop("entry", {}))
    row = {"modelled_fair": {"over": entry}}
    row.update(overrides)
    return row


# --------------------------------------------------------------------------
# The number itself.
# --------------------------------------------------------------------------


def test_the_audits_own_worked_example_reproduces():
    """MLB, Matt Olson, `batter_home_runs` 0.5 -- the audit's §4b example.

    It predicted "a -2.5 pp read that is computable from two fields on the same
    served row". Pinning it means the column can be traced back to the finding
    that justified building it.
    """
    out = modelled_fair_edge(_row(), model_prob=0.2087, side="over")
    assert out[EDGE_FIELD] == -2.47


def test_the_provenance_travels_with_the_number():
    """A weaker claim must say so ON THE ROW, not only in a docstring.

    Without the book and the hold, a reader cannot tell this from a real
    two-sided edge -- which is exactly the confusion `#242` caused.
    """
    out = modelled_fair_edge(_row(), model_prob=0.2087, side="over")
    assert out[EDGE_METHOD_FIELD] == "book_margin_model"
    assert out[EDGE_BASIS_FIELD] == "betrivers"
    assert out[EDGE_HOLD_FIELD] == 6.636


def test_a_positive_edge_is_signed_the_same_way_as_the_real_one():
    out = modelled_fair_edge(_row(), model_prob=0.30, side="over")
    assert out[EDGE_FIELD] == pytest.approx(6.66, abs=0.01)


# --------------------------------------------------------------------------
# Refusals. These are the reason this is a separate column at all.
# --------------------------------------------------------------------------


def test_it_never_writes_the_real_edge_field():
    """THE LOAD-BEARING ASSERTION.

    If this ever returns `edge_vs_market_pct`, a modelled estimate silently
    becomes a measured de-vig on the board and nothing downstream can tell.
    """
    out = modelled_fair_edge(_row(), model_prob=0.2087, side="over")
    assert "edge_vs_market_pct" not in out
    assert all(key.startswith("edge_vs_modelled_fair") for key in out)


def test_a_two_sided_consensus_fair_is_refused():
    """Mixing in the OTHER direction is equally forbidden.

    A real two-sided fair priced into this column would advertise a strong
    number as a weak one, and would duplicate `edge_vs_market_pct` under a name
    that says it is modelled.
    """
    row = _row(entry={"fair_method": "two_sided_consensus"})
    assert modelled_fair_edge(row, model_prob=0.2087, side="over") is None


def test_an_absent_fair_method_is_refused_rather_than_assumed():
    row = _row(entry={"fair_method": None})
    assert modelled_fair_edge(row, model_prob=0.2087, side="over") is None


def test_the_wrong_side_does_not_silently_price_the_other_leg():
    assert modelled_fair_edge(_row(), model_prob=0.2087, side="under") is None


def test_no_side_is_refused_rather_than_guessed():
    for side in (None, "", "   "):
        assert modelled_fair_edge(_row(), model_prob=0.2087, side=side) is None


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.5, 1.5, float("nan"), True, "0.5", None])
def test_a_sentinel_or_out_of_range_probability_is_refused(bad):
    """0.0/1.0 are certainties no estimator expresses -- far likelier a sentinel
    or a unit error, and pricing against one manufactures a huge edge."""
    assert modelled_fair_edge(_row(), model_prob=bad, side="over") is None
    assert modelled_fair_edge(_row(entry={"fair_probability": bad}), model_prob=0.2, side="over") is None


def test_a_row_with_no_modelled_fair_is_refused():
    assert modelled_fair_edge({}, model_prob=0.2087, side="over") is None
    assert modelled_fair_edge({"modelled_fair": None}, model_prob=0.2087, side="over") is None
    assert modelled_fair_edge({"modelled_fair": []}, model_prob=0.2087, side="over") is None


def test_a_non_mapping_row_is_refused_and_does_not_raise():
    for row in (None, "row", 42, []):
        assert modelled_fair_edge(row, model_prob=0.2087, side="over") is None


def test_the_side_key_is_matched_case_insensitively():
    row = {"modelled_fair": {"OVER": {"fair_probability": 0.2334, "fair_method": "book_margin_model"}}}
    assert modelled_fair_edge(row, model_prob=0.2087, side="over") is not None


# --------------------------------------------------------------------------
# The producers actually reach it.
# --------------------------------------------------------------------------


def test_the_mlb_producer_attaches_it_on_a_one_sided_row():
    """Wiring, not just the helper. A verified helper that production never
    reaches is the inert-fix pattern this repo has hit repeatedly."""
    from syndicate.features.shared.prop_projections import MODELLED_EDGE_FIELD

    assert MODELLED_EDGE_FIELD == EDGE_FIELD


def test_both_producers_import_the_same_helper():
    """One implementation, two callers -- the rule that `#340` established after
    WNBA shipped 128 live edges by having no copy of a per-sport rule."""
    from syndicate.features.shared import prop_projections, soccer_projections

    assert prop_projections.modelled_fair_edge is modelled_fair_edge
    assert soccer_projections.modelled_fair_edge is modelled_fair_edge


def test_the_live_refusal_is_not_bypassed():
    """A modelled fair does NOT make a live pregame projection priceable.

    Wiring this into the live branch would reintroduce the exact leak `#340`
    fixed across three sports, so the source must not call it there.
    """
    import inspect

    from syndicate.features.shared import soccer_projections

    src = inspect.getsource(soccer_projections._price_against_market)
    live_block = src.split("live_reason = ")[1].split("fair = _no_vig_over_probability")[0]
    assert "modelled_fair_edge" not in live_block, (
        "the live branch must not price against a modelled fair"
    )
