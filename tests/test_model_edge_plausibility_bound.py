"""The measured-edge plausibility bound tests PROBABILITY, not magnitude.

`[2026-10-19, user decision: "replace the ceiling"]`

The old bound refused `abs(edge) > 15`. Its own docstring says it is not about
magnitude -- *"the bound is on PLAUSIBILITY IN PROBABILITY SPACE ... an edge is
accepted only if the probability it implies is one a bettor could act on"* --
and measured against that criterion it failed, by two instruments:

- of 525 rows it refused, **0** implied an impossible probability and **470
  (89.5%)** implied an ORDINARY one, i.e. rows its own test would admit;
- of 116 refused NFL-yardage markets, **84 (72.4%)** were refused on magnitude
  ALONE -- neither implausible as a probability nor low-role.

The replacement is the docstring's own example: a model claiming ~86% against a
market priced near even. Refuse when the model's probability is EXTREME *while
the market's is not*.

MEASURED off/on over 3,651 served rows with the deployed function: edges
produced 3,015 -> 3,354, ceiling refusals 377 -> 36, `model_probability_impossible`
0. Scoped to `_model_edge_for`; the modelled-fair, three-way and calibrated
bounds are untouched and pinned below.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import layer2_board as L  # noqa: E402


@pytest.fixture(autouse=True)
def _default_mode(monkeypatch):
    """Every test states its own mode; none inherits the ambient env."""
    monkeypatch.delenv(L.PLAUSIBILITY_BOUND_ENV, raising=False)


def _row(edge, model_prob, market_prob, side="over"):
    return {"side": side, "home_team": "Home FC", "away_team": "Away FC",
            "projection": {"edge_vs_market_pct": edge, "side": side,
                           "model_prob_over": model_prob,
                           "market_fair_prob_over": market_prob}}


def _edge(row, side="over", refusal=None):
    return L._model_edge_for(row, side, None, refusal=refusal)


# ---------------------------------------------------------------------------
# the new test: extreme model against an ORDINARY market
# ---------------------------------------------------------------------------

def test_an_extreme_model_against_an_ordinary_market_is_refused_and_named():
    """The docstring's own example: ~86% claimed where the market says ~47%."""
    ref = {}
    assert _edge(_row(39.38, 0.862, 0.468), refusal=ref) is None
    assert ref["reason"] == "model_probability_extreme_against_ordinary_market"
    assert ref["model_prob_over"] == pytest.approx(0.862)
    assert ref["market_fair_prob_over"] == pytest.approx(0.468)
    assert ref["extreme_at_or_above"] == pytest.approx(0.85)
    assert ref["extreme_at_or_below"] == pytest.approx(0.15)


def test_the_measured_catch_from_the_served_board():
    """nfl rushing attempts: model 0.066 against a market at 0.530."""
    ref = {}
    assert _edge(_row(-46.37, 0.066, 0.530), refusal=ref) is None
    assert ref["reason"] == "model_probability_extreme_against_ordinary_market"


# ---------------------------------------------------------------------------
# THE LOAD-BEARING CASE: a flat band would be wrong here
# ---------------------------------------------------------------------------

def test_an_extreme_model_against_an_EXTREME_market_is_ALLOWED():
    """Both sides agree the outcome is unlikely -- agreement, not implausibility.

    A bare 0.15 floor would refuse an anytime-TD at 8% model vs 8% market, which
    is perfectly actionable. Measured on the served board: **9 rows** carry an
    extreme model AND an extreme market (alt totals, alt spreads, ncaaf h2h,
    `batter_home_runs`). Requiring the market to be ordinary spares exactly
    those, and this test is why the condition cannot be dropped.
    """
    ref = {}
    got = _edge(_row(2.0, 0.08, 0.06), refusal=ref)
    assert got == pytest.approx(2.0)
    assert ref == {}

    # and at the top end too
    assert _edge(_row(-3.0, 0.93, 0.96)) == pytest.approx(-3.0)


def test_a_huge_edge_with_an_ORDINARY_implied_probability_is_now_ALLOWED():
    """The 470-row case: ordinary probability, refused by the old bound only
    because the magnitude was large. 0.50 -> 0.82 is 32 points and both ends are
    probabilities a bettor can act on."""
    ref = {}
    assert _edge(_row(32.0, 0.82, 0.50), refusal=ref) == pytest.approx(32.0)
    assert ref == {}


def test_an_impossible_probability_is_refused_and_named_separately():
    """The real units/join-error catcher. It fires on 0 served rows today, which
    is the honest reason the magnitude bound was never doing this job."""
    ref = {}
    assert _edge(_row(60.0, 1.09, 0.49), refusal=ref) is None
    assert ref["reason"] == "model_probability_impossible"
    assert ref["model_prob_over"] == pytest.approx(1.09)


# ---------------------------------------------------------------------------
# REACHABILITY and revertibility
# ---------------------------------------------------------------------------

def test_off_does_not_equal_on_for_the_same_row(monkeypatch):
    """`model_engine_standard.md` requires this before any correctness test."""
    row = _row(32.0, 0.82, 0.50)   # ordinary probability, big magnitude
    assert _edge(row) == pytest.approx(32.0)            # probability mode: allowed
    monkeypatch.setenv(L.PLAUSIBILITY_BOUND_ENV, "magnitude")
    assert _edge(row) is None                            # magnitude mode: refused


def test_the_magnitude_mode_reproduces_the_OLD_bound_verbatim(monkeypatch):
    """The revert path must be a real revert, including the refusal's NAME, so a
    rollback leaves no trace in the refusal vocabulary downstream readers parse.
    """
    monkeypatch.setenv(L.PLAUSIBILITY_BOUND_ENV, "MAGNITUDE")  # case-insensitive
    ref = {}
    assert _edge(_row(15.87, 0.728, 0.5693), refusal=ref) is None
    assert ref["reason"] == "edge_exceeds_plausibility_ceiling"
    assert ref["edge"] == pytest.approx(15.87)
    assert ref["ceiling"] == pytest.approx(L._MODEL_EDGE_MAX_POINTS)
    # and an extreme-vs-ordinary row that the NEW rule refuses is refused here
    # too, but under the OLD name -- the two modes must not blend vocabularies
    ref2 = {}
    assert _edge(_row(39.38, 0.862, 0.468), refusal=ref2) is None
    assert ref2["reason"] == "edge_exceeds_plausibility_ceiling"


def test_an_unrecognised_flag_value_means_the_NEW_default(monkeypatch):
    monkeypatch.setenv(L.PLAUSIBILITY_BOUND_ENV, "banana")
    assert _edge(_row(32.0, 0.82, 0.50)) == pytest.approx(32.0)


# ---------------------------------------------------------------------------
# UNKNOWN DOES NOT PASS
# ---------------------------------------------------------------------------

def test_a_missing_probability_falls_back_to_the_magnitude_bound():
    """Absent must not map onto the permissive branch. 0 of 1,769 served rows
    needed this path, so it is defensive -- which is exactly why it must be
    tested rather than assumed."""
    ref = {}
    row = _row(40.0, None, 0.50)
    assert _edge(row, refusal=ref) is None
    assert ref["reason"] == "edge_exceeds_plausibility_ceiling_no_probability_to_test"
    assert ref["model_prob_over"] is None

    ref2 = {}
    assert _edge(_row(40.0, 0.82, None), refusal=ref2) is None
    assert ref2["reason"] == "edge_exceeds_plausibility_ceiling_no_probability_to_test"


def test_a_missing_probability_with_a_SMALL_edge_still_passes():
    """The fallback is the old bound, not a blanket refusal: a small edge with
    no probability to test was always allowed and still is."""
    assert _edge(_row(4.0, None, None)) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# SCOPE: the other three bounds on the same constant are untouched.
# A source guard, and labelled as one -- it cannot tell those bounds are
# CORRECT, only that this change did not silently move them. Their populations
# were never measured, so moving them would have been unevidenced.
# ---------------------------------------------------------------------------

def _func_source(name):
    """One function's source, bounded by the next top-level def/class.

    A fixed character window is the wrong instrument here: these functions
    carry very long docstrings, and a window that happens to be too short
    reports a missing anchor as a FAILURE rather than as a bad probe. Two of
    these guards failed that way on their first run.
    """
    src = (ROOT / "syndicate/features/shared/layer2_board.py").read_text(encoding="utf-8")
    lines = src.split(chr(10))
    start = next(i for i, l in enumerate(lines) if l.startswith("def %s(" % name))
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith(("def ", "class "))), len(lines))
    return chr(10).join(lines[start:end])


def test_the_other_three_bounds_still_use_the_magnitude_constant():
    for name in ("_modelled_fair_edge_for",   # modelled-fair edge
                 "_three_way_leg_edge",       # price_moneyline leg edge
                 "_calibrate_model_edge"):    # calibrated edge
        body = _func_source(name)
        assert "_MODEL_EDGE_MAX_POINTS" in body, (
            "%s no longer bounds on the magnitude constant; its population was "
            "never measured, so this change must not have moved it" % name)


def test_model_edge_for_no_longer_tests_magnitude_directly():
    """The call site must delegate, so the mode flag actually governs it."""
    body = _func_source("_model_edge_for")
    assert "_plausibility_refusal(projection, edge)" in body
    assert "abs(edge) > _MODEL_EDGE_MAX_POINTS" not in body, (
        "the magnitude test is back inline and would bypass the mode flag")


def test_the_bound_helper_itself_still_holds_the_magnitude_path():
    """The revert path lives in the helper, so it must keep the constant."""
    body = _func_source("_plausibility_refusal")
    assert "_MODEL_EDGE_MAX_POINTS" in body
    assert "_PLAUSIBILITY_MAGNITUDE" in body
